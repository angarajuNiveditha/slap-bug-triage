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

from ..rule_based.tfidf_similarity import SimilarBug
from .embedding_classifier         import _get_model, EmbeddingClassifier

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
        Two-stage similarity search over BOTH the Jira embedding index AND
        the local ticket store — the intended default for the multi-agent
        pipeline.

          Stage 1 (recall):  cosine over the Jira index (top-`recall_k`)
                             PLUS cosine over every embedding in the local
                             ticket store (see src/db.py). Both are fast
                             (~200 µs for Jira, negligible for the local
                             store which is small).
          Stage 2 (rerank):  cross-encoder rescores the merged pool with
                             joint attention across (query, candidate),
                             then returns the top-`top_k`.

        Local tickets appear alongside Jira tickets in the same ranking,
        so a recently-Published BUGT ticket that duplicates the new bug
        will surface even if the Jira corpus doesn't contain it.

        The returned SimilarBug objects carry the cross-encoder-derived
        score in `.similarity` (sigmoid-normalised to [0, 1]) and are
        ordered by that score. `is_duplicate_candidate` tracks the RAW
        COSINE similarity vs DUPLICATE_THRESHOLD (0.80) — the threshold
        is calibrated for cosine and downstream dedup logic depends on
        that scale.

        Falls back gracefully when the cross-encoder can't be loaded
        (returns merged cosine ranking) or when the local store can't
        be reached (returns Jira-only results, unchanged from previous
        behaviour).
        """
        clf   = self._clf
        model = _get_model()

        # ── Encode the query once — both sources compare against it. ──
        t0 = time.perf_counter()
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]

        # ── Stage 1a: Jira cosine recall ─────────────────────────────
        sims_jira = clf.embeddings @ q
        k_jira    = min(recall_k, clf.n)
        jira_idx  = np.argpartition(-sims_jira, kth=min(k_jira, clf.n - 1))[:k_jira]
        jira_idx  = jira_idx[np.argsort(-sims_jira[jira_idx])]

        candidates: list[dict] = []
        for i in jira_idx:
            cos = float(sims_jira[i])
            text_i = str(clf.texts[i]) if clf.texts is not None else ""
            candidates.append({
                "source":     "jira",
                "text":       text_i,
                "cosine":     cos,
                "sb_kwargs":  self._sb_kwargs_from_jira_idx(int(i)),
            })

        # ── Stage 1b: local ticket cosine recall ─────────────────────
        # Deliberately swallow errors — if the local store isn't reachable
        # (fresh install, DB migration in progress, etc.), we still want
        # the Jira results to flow through.
        try:
            from src.shared import db as ticket_db
            local_hits = ticket_db.local_similar(q, top_k=recall_k)
        except Exception as e:
            print(f"  [similarity] local store unavailable ({e}); Jira-only ranking")
            local_hits = []

        for hit in local_hits:
            cos = float(hit["similarity"])
            candidates.append({
                "source":    "local",
                "text":      "\n".join(filter(None, [hit.get("summary"), hit.get("description")])),
                "cosine":    cos,
                "sb_kwargs": {
                    "key":       hit["key"],
                    "summary":   hit["summary"] or "",
                    "assignee":  hit.get("assignee") or None,
                    "priority":  hit.get("priority") or "Unknown",
                    "url":       "",                       # local — no external link
                    "component": hit.get("component") or None,
                },
            })
        recall_ms = (time.perf_counter() - t0) * 1000

        n_jira, n_local = len(jira_idx), len(local_hits)

        # If we have too few to bother reranking (tiny corpus / empty),
        # just sort by raw cosine and return.
        if len(candidates) <= top_k:
            candidates.sort(key=lambda c: -c["cosine"])
            matches = [self._sb_from_candidate(c, similarity=c["cosine"]) for c in candidates]
            print(
                f"  [similarity] merged {n_jira} Jira + {n_local} local candidates in "
                f"{recall_ms:.1f}ms (below rerank threshold; returned by cosine)"
            )
            return _make_result(matches)

        # ── Stage 2: cross-encoder rerank of the MERGED pool ─────────
        try:
            ce = _get_cross_encoder()
        except Exception as e:
            print(f"  [similarity] cross-encoder unavailable ({e}); returning merged cosine top-{top_k}")
            candidates.sort(key=lambda c: -c["cosine"])
            matches = [self._sb_from_candidate(c, similarity=c["cosine"]) for c in candidates[:top_k]]
            return _make_result(matches)

        pairs = [(text, c["text"]) for c in candidates]

        t1 = time.perf_counter()
        ce_scores = ce.predict(pairs, show_progress_bar=False)   # shape (N,)
        rerank_ms = (time.perf_counter() - t1) * 1000

        # Sort by cross-encoder score, take top_k, build final SimilarBugs.
        order = np.argsort(-ce_scores)[:top_k]

        matches = []
        for i in order:
            c        = candidates[int(i)]
            ce_raw   = float(ce_scores[int(i)])
            ce_norm  = 1.0 / (1.0 + math.exp(-ce_raw))
            matches.append(self._sb_from_candidate(
                c,
                similarity = ce_norm,
                # is_duplicate_candidate is a threshold check on RAW
                # cosine (calibrated), not the rerank score.
                is_dup     = c["cosine"] >= DUPLICATE_THRESHOLD,
            ))

        n_jira_kept  = sum(1 for i in order if candidates[int(i)]["source"] == "jira")
        n_local_kept = len(order) - n_jira_kept
        print(
            f"  [similarity] cosine recall {n_jira} Jira + {n_local} local in "
            f"{recall_ms:.1f}ms; cross-encoder rerank over {len(candidates)} pairs "
            f"in {rerank_ms:.1f}ms → top-{top_k} "
            f"({n_jira_kept} Jira, {n_local_kept} local)"
        )
        return _make_result(matches)

    # ── Internal ────────────────────────────────────────────────────

    def _sb_kwargs_from_jira_idx(self, idx: int) -> dict:
        """Extract the source-agnostic SimilarBug fields from a Jira
        embedding-index row. Called by find_similar_with_rerank when
        assembling the merged (Jira + local) candidate pool.

        Deliberately does NOT include `similarity` or
        `is_duplicate_candidate` — those get filled in by
        _sb_from_candidate after the rerank."""
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
        return {
            "key":       key,
            "summary":   summary,
            "assignee":  assignee,
            "priority":  priority,
            "url":       f"{JIRA_BASE_URL}/browse/{key}" if key else "",
            "component": label,
        }


    def _sb_from_candidate(
        self,
        candidate: dict,
        similarity: float,
        is_dup:     Optional[bool] = None,
    ) -> SimilarBug:
        """Build a SimilarBug from a unified-pool candidate dict, using
        the caller-provided similarity (post-rerank sigmoid, or raw
        cosine when the rerank stage was skipped). is_duplicate_candidate
        defaults to `similarity >= DUPLICATE_THRESHOLD` for the cosine
        case, but callers pass an explicit `is_dup` after rerank so the
        threshold is checked on the RAW COSINE (calibrated), not the
        rerank score."""
        return SimilarBug(
            similarity             = round(float(similarity), 3),
            is_duplicate_candidate = (
                is_dup if is_dup is not None else similarity >= DUPLICATE_THRESHOLD
            ),
            **candidate["sb_kwargs"],
        )


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
