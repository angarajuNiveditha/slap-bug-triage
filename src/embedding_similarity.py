"""
embedding_similarity.py — Cosine-similarity-based similar-bug ranking.

Replaces the in-context ranking that subagent_embeddings does (Claude reads
all 300 bugs and eyeballs similarity). The replacement uses actual
sentence-transformer embeddings:

  - Production latency: ~7ms per query (vs ~30-60s for the Claude version)
  - Quality: embeddings are *specifically trained* on semantic-similarity
    tasks. Claude-in-context is not.

Owner suggestion is intentionally NOT part of this engine — it's now a
separate sub-agent (subagent_owner) that runs on top of the top-K
filtered by the routed component.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .tfidf_similarity     import SimilarBug
from .embedding_classifier import _get_model, EmbeddingClassifier

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")

TOP_K                    = 5     # legacy find_similar default (cosine-only)
DUPLICATE_THRESHOLD      = 0.80  # cosine threshold — still evaluated against the
                                 # raw cosine sim of the top match, not the rerank
                                 # score (which lives in a different scale)

# Two-stage retrieval knobs (used by find_similar_with_rerank)
RECALL_K                 = 30    # candidates cosine feeds to the cross-encoder
RERANK_K                 = 10    # final K after the rerank
CROSS_ENCODER_MODEL      = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Sigmoid-normalised cross-encoder score below which the whole retrieval is
# treated as "no relevant matches found." Downstream sub-agents (owner,
# triage) receive an empty list in that case so they escalate to defaults
# rather than reasoning over unrelated bugs. The full top-K is still
# returned for UI display — this only gates the downstream reasoning path.
#
# Calibration: sigmoid(-2.2) ≈ 0.10. A raw cross-encoder score below -2.2
# means the model is meaningfully leaning "these bugs are not related."
# Good matches typically score 0.6+; loosely-related in the 0.2-0.4 band;
# below 0.10 is the "clearly not related" zone.
RELEVANCE_THRESHOLD      = 0.10


# ── Cross-encoder singleton (lazy) ──────────────────────────────────────────
# First call downloads ~90 MB from the Hugging Face hub, then caches under
# ~/.cache/huggingface. Subsequent calls are instant. Held at module scope so
# we don't re-pay the load cost on every retrieval.

_cross_encoder = None


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        # Quiet down sentence-transformers' progress bars during load.
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        from sentence_transformers import CrossEncoder
        print(f"  [similarity] loading cross-encoder {CROSS_ENCODER_MODEL}...")
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
    return _cross_encoder


@dataclass
class EmbeddingSimilarityResult:
    """Lightweight result from the embedding similarity engine.

    Owner suggestion lives in a separate sub-agent now (see subagent_owner),
    so this result intentionally does NOT carry owner data.

    `top_relevance_score` and `is_low_confidence` are used by the host to
    decide whether to pass `top_matches` to the downstream reasoning
    sub-agents (owner / triage) or an empty list. See RELEVANCE_THRESHOLD
    above for the calibration.
    """
    top_matches:         list           # list[SimilarBug] — always shown to UI
    top_relevance_score: float = 0.0    # max .similarity across top_matches
    is_low_confidence:   bool  = False  # True when top_relevance_score < RELEVANCE_THRESHOLD


def _make_result(matches: list) -> "EmbeddingSimilarityResult":
    """Build a result carrying the low-confidence flag derived from the
    top match's score. Used by every return site in the engine so the
    flag can never fall out of sync with the ranking."""
    top = max((m.similarity for m in matches), default=0.0)
    return EmbeddingSimilarityResult(
        top_matches         = matches,
        top_relevance_score = top,
        is_low_confidence   = (top < RELEVANCE_THRESHOLD),
    )


class EmbeddingSimilarityEngine:
    """
    Wraps an EmbeddingClassifier (or loads one) and exposes find_similar()
    for a new bug. Shares the loaded index in memory if you pass an
    existing classifier — avoids loading 564 × 768-dim float32 twice.
    """

    def __init__(self, classifier: Optional[EmbeddingClassifier] = None) -> None:
        self._clf = classifier if classifier is not None else EmbeddingClassifier()

    def find_similar(self, text: str, top_k: int = TOP_K) -> EmbeddingSimilarityResult:
        """Legacy cosine-only path. Fast (~200 µs) but no rerank —
        the top-K may include cosmetically-similar bugs that don't match
        the failure mode. Kept for the rule-based pipeline and as the
        recall stage of `find_similar_with_rerank`."""
        clf   = self._clf
        model = _get_model()

        # Embed the new bug (the only inference cost — ~7ms on CPU)
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]

        # Cosine = dot product since both sides are L2-normalised
        sims    = clf.embeddings @ q
        top_idx = np.argpartition(-sims, kth=min(top_k, clf.n - 1))[:top_k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        matches = [self._build_match(i, float(sims[i])) for i in top_idx]
        return _make_result(matches)

    def find_similar_with_rerank(
        self,
        text:     str,
        top_k:    int = RERANK_K,
        recall_k: int = RECALL_K,
    ) -> EmbeddingSimilarityResult:
        """
        Two-stage similarity search — the intended default for the
        multi-agent pipeline.

          Stage 1 (recall):  cosine over the embedding index → top-`recall_k`.
                             Fast (~200 µs) and high-recall — designed to
                             include the true best matches even if they
                             aren't ranked #1.
          Stage 2 (rerank):  cross-encoder rescores the recall set with
                             joint attention across query + candidate,
                             then returns the top-`top_k`. Slower per pair
                             (~5-15 ms) but only runs on `recall_k` pairs
                             (~150-450 ms total for recall_k=30).

        The returned SimilarBug objects carry the cross-encoder-derived
        score in `.similarity` (sigmoid-normalised to [0, 1] so it's
        comparable across queries), and are ordered by that score.

        `is_duplicate_candidate` still tracks the RAW COSINE similarity
        vs DUPLICATE_THRESHOLD — the threshold is calibrated for cosine
        and downstream dedup logic depends on that scale.

        Falls back to `find_similar(top_k=top_k)` if the cross-encoder
        model can't be loaded (offline first run, disk full, etc.).
        """
        clf   = self._clf
        model = _get_model()

        # ── Stage 1: cosine recall ─────────────────────────────────
        t0 = time.perf_counter()
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]
        sims    = clf.embeddings @ q
        # Guard: if the corpus is small, don't ask for more than exists.
        k       = min(recall_k, clf.n)
        top_idx = np.argpartition(-sims, kth=min(k, clf.n - 1))[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        recall_ms = (time.perf_counter() - t0) * 1000

        # If we can't rerank meaningfully (tiny corpus or user asked for
        # more than we have), just return the cosine ranking as-is.
        if len(top_idx) <= top_k:
            matches = [self._build_match(i, float(sims[i])) for i in top_idx]
            return _make_result(matches)

        # ── Stage 2: cross-encoder rerank ──────────────────────────
        try:
            ce = _get_cross_encoder()
        except Exception as e:
            print(f"  [similarity] cross-encoder unavailable ({e}); returning cosine top-{top_k}")
            top_idx = top_idx[:top_k]
            matches = [self._build_match(i, float(sims[i])) for i in top_idx]
            return _make_result(matches)

        # Build (query, candidate_text) pairs for the recall set.
        pairs = []
        for i in top_idx:
            candidate_text = str(clf.texts[i]) if clf.texts is not None else ""
            pairs.append((text, candidate_text))

        t1 = time.perf_counter()
        ce_scores = ce.predict(pairs, show_progress_bar=False)   # shape (recall_k,)
        rerank_ms = (time.perf_counter() - t1) * 1000

        # Sort the recall set by cross-encoder score (descending) and take top-k.
        order       = np.argsort(-ce_scores)[:top_k]
        winning_idx = top_idx[order]                 # indices back into the corpus
        winning_ce  = ce_scores[order]               # raw CE scores in ranked order
        winning_cos = sims[winning_idx]              # original cosine for the threshold check

        # Sigmoid-normalise the raw CE scores into [0, 1] so downstream code
        # comparing "similarity" values (e.g. _closest_manager_owner in
        # subagent_owner) gets a bounded, monotonic signal.
        matches = []
        for i, ce_raw, cos_raw in zip(winning_idx, winning_ce, winning_cos):
            ce_norm = 1.0 / (1.0 + math.exp(-float(ce_raw)))
            matches.append(self._build_match(
                idx        = int(i),
                similarity = ce_norm,
                is_dup     = bool(cos_raw >= DUPLICATE_THRESHOLD),
            ))

        print(
            f"  [similarity] cosine recall {len(top_idx)} in {recall_ms:.1f}ms; "
            f"cross-encoder rerank in {rerank_ms:.1f}ms → top-{top_k}"
        )
        return _make_result(matches)

    # ── Internal ────────────────────────────────────────────────────

    def _build_match(
        self,
        idx:        int,
        similarity: float,
        is_dup:     Optional[bool] = None,
    ) -> SimilarBug:
        """Convert an index into the embedding corpus into a SimilarBug.

        `is_dup` overrides the default cosine-threshold check — pass the
        raw-cosine-based flag when the caller has done its own rerank
        (so the `similarity` value on the returned object may not be
        cosine anymore).
        """
        clf = self._clf
        key      = str(clf.keys[idx])
        summary  = ""
        assignee = None
        priority = "Unknown"
        label    = str(clf.labels[idx])

        if clf.texts is not None:
            summary = str(clf.texts[idx]).split("\n", 1)[0]
        if clf.assignees is not None:
            a = str(clf.assignees[idx])
            assignee = a if a else None
        if clf.priorities is not None:
            priority = str(clf.priorities[idx]) or "Unknown"

        return SimilarBug(
            key                    = key,
            summary                = summary,
            similarity             = round(float(similarity), 3),
            assignee               = assignee,
            priority               = priority,
            is_duplicate_candidate = (is_dup if is_dup is not None
                                      else similarity >= DUPLICATE_THRESHOLD),
            url                    = f"{JIRA_BASE_URL}/browse/{key}" if key else "",
            component              = label,
        )

    @property
    def team_roster(self) -> dict:
        """Pass-through to the underlying classifier's team roster."""
        return self._clf.team_roster
