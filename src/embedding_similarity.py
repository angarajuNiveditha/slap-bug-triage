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

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .tfidf_similarity     import SimilarBug
from .embedding_classifier import _get_model, EmbeddingClassifier

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")

TOP_K               = 5
DUPLICATE_THRESHOLD = 0.80   # high bar; downstream dedup sub-agent makes the final call


@dataclass
class EmbeddingSimilarityResult:
    """Lightweight result from the embedding similarity engine.

    Owner suggestion lives in a separate sub-agent now (see subagent_owner),
    so this result intentionally does NOT carry owner data.
    """
    top_matches: list   # list[SimilarBug]


class EmbeddingSimilarityEngine:
    """
    Wraps an EmbeddingClassifier (or loads one) and exposes find_similar()
    for a new bug. Shares the loaded index in memory if you pass an
    existing classifier — avoids loading 564 × 768-dim float32 twice.
    """

    def __init__(self, classifier: Optional[EmbeddingClassifier] = None) -> None:
        self._clf = classifier if classifier is not None else EmbeddingClassifier()

    def find_similar(self, text: str, top_k: int = TOP_K) -> EmbeddingSimilarityResult:
        clf   = self._clf
        model = _get_model()

        # Embed the new bug (the only inference cost — ~7ms on CPU)
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]

        # Cosine = dot product since both sides are L2-normalised
        sims    = clf.embeddings @ q
        top_idx = np.argpartition(-sims, kth=min(top_k, clf.n - 1))[:top_k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        matches: list[SimilarBug] = []
        for i in top_idx:
            key      = str(clf.keys[i])
            sim      = float(sims[i])
            summary  = ""
            assignee = None
            priority = "Unknown"
            label    = str(clf.labels[i])    # the Jira component this bug was filed against

            if clf.texts is not None:
                # texts is "title\ndescription" — title is the first line.
                summary = str(clf.texts[i]).split("\n", 1)[0]
            if clf.assignees is not None:
                a = str(clf.assignees[i])
                assignee = a if a else None
            if clf.priorities is not None:
                priority = str(clf.priorities[i]) or "Unknown"

            matches.append(SimilarBug(
                key                    = key,
                summary                = summary,
                similarity             = round(sim, 3),
                assignee               = assignee,
                priority               = priority,
                is_duplicate_candidate = (sim >= DUPLICATE_THRESHOLD),
                url                    = f"{JIRA_BASE_URL}/browse/{key}" if key else "",
                component              = label,
            ))

        return EmbeddingSimilarityResult(top_matches=matches)

    @property
    def team_roster(self) -> dict:
        """Pass-through to the underlying classifier's team roster."""
        return self._clf.team_roster
