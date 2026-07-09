"""
similarity.py — Duplicate detection and owner routing via local embeddings.

Production equivalent: Vector One (Flipkart managed vector DB).
Prototype: sentence-transformers + numpy cosine similarity in memory.

One search does two jobs:
  1. Duplicate detection  — if top-1 similarity > DUPLICATE_THRESHOLD, flag it
  2. Owner routing        — look at assignees of top-K matches, pick most frequent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from ..shared.jira_client import JiraClient

# -----------------------------------------------------------------------
# Thresholds
# -----------------------------------------------------------------------
DUPLICATE_THRESHOLD = 0.88   # cosine similarity above this → likely duplicate
SIMILAR_THRESHOLD   = 0.70   # above this → relevant for owner routing
TOP_K               = 5      # how many similar bugs to surface

# Model — runs fully local, no API key needed
# "all-MiniLM-L6-v2" is fast (80MB) and good enough for bug text
EMBED_MODEL = "all-MiniLM-L6-v2"


@dataclass
class SimilarBug:
    key: str
    summary: str
    similarity: float           # 0.0 – 1.0
    assignee: Optional[str]
    priority: str
    is_duplicate_candidate: bool


@dataclass
class SimilarityResult:
    top_matches: list[SimilarBug]
    suggested_owner: Optional[str]      # display name or None
    owner_reason: str                   # one-line explanation
    duplicate_of: Optional[str]         # Jira key if flagged, else None
    duplicate_confidence: float         # cosine score of top match


class SimilarityEngine:
    def __init__(self):
        print("  [similarity] loading embedding model (first run downloads ~80MB)...")
        self._model = SentenceTransformer(EMBED_MODEL)
        self._issue_index: list[dict] = []       # raw Jira issue dicts
        self._embeddings: Optional[np.ndarray] = None  # shape (N, D)

    # ------------------------------------------------------------------
    # Build index from Jira issues
    # ------------------------------------------------------------------

    def build_index(self, issues: list[dict]) -> None:
        """
        Embed all fetched Jira issues and store in memory.
        Call this once after fetching bugs from Jira.
        """
        if not issues:
            print("  [similarity] no issues to index")
            return

        texts = [JiraClient.extract_text(issue) for issue in issues]
        print(f"  [similarity] embedding {len(texts)} issues...")
        embeddings = self._model.encode(texts, show_progress_bar=False, batch_size=64)
        self._embeddings = np.array(embeddings, dtype=np.float32)
        self._issue_index = issues
        print(f"  [similarity] index ready — {len(issues)} bugs")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def find_similar(self, query_text: str) -> SimilarityResult:
        """
        Find top-K similar bugs to query_text.
        Returns duplicate flag + owner suggestion.
        """
        if self._embeddings is None or len(self._issue_index) == 0:
            return SimilarityResult(
                top_matches=[],
                suggested_owner=None,
                owner_reason="No historical bugs indexed.",
                duplicate_of=None,
                duplicate_confidence=0.0,
            )

        # Embed the query
        q_emb = self._model.encode([query_text], show_progress_bar=False)
        q_emb = np.array(q_emb, dtype=np.float32)

        # Cosine similarity: normalise both, then dot product
        q_norm = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-9)
        idx_norm = self._embeddings / (
            np.linalg.norm(self._embeddings, axis=1, keepdims=True) + 1e-9
        )
        scores = (idx_norm @ q_norm.T).flatten()  # shape (N,)

        # Top-K indices (descending)
        top_indices = np.argsort(scores)[::-1][:TOP_K].tolist()

        matches: list[SimilarBug] = []
        for idx in top_indices:
            issue = self._issue_index[idx]
            sim = float(scores[idx])
            if sim < SIMILAR_THRESHOLD:
                break
            matches.append(
                SimilarBug(
                    key=issue.get("key", ""),
                    summary=issue.get("fields", {}).get("summary", ""),
                    similarity=round(sim, 3),
                    assignee=JiraClient.extract_assignee(issue),
                    priority=JiraClient.extract_priority(issue),
                    is_duplicate_candidate=sim >= DUPLICATE_THRESHOLD,
                )
            )

        # Duplicate detection
        duplicate_of = None
        duplicate_confidence = float(scores[top_indices[0]]) if top_indices else 0.0
        if matches and matches[0].is_duplicate_candidate:
            duplicate_of = matches[0].key

        # Owner routing — frequency count over top matches
        suggested_owner, owner_reason = _suggest_owner(matches)

        return SimilarityResult(
            top_matches=matches,
            suggested_owner=suggested_owner,
            owner_reason=owner_reason,
            duplicate_of=duplicate_of,
            duplicate_confidence=round(duplicate_confidence, 3),
        )


# ------------------------------------------------------------------
# Owner routing helper
# ------------------------------------------------------------------

def _suggest_owner(matches: list[SimilarBug]) -> tuple[Optional[str], str]:
    """
    Count assignees across top matches. Return the most frequent one
    with a one-line reason.
    """
    assignees: dict[str, int] = {}
    for m in matches:
        if m.assignee:
            assignees[m.assignee] = assignees.get(m.assignee, 0) + 1

    if not assignees:
        return None, "No assignee data in similar bugs."

    top_owner = max(assignees, key=lambda k: assignees[k])
    count = assignees[top_owner]
    total = len([m for m in matches if m.assignee])
    reason = (
        f"Assigned to {top_owner} on {count}/{total} most similar past bugs "
        f"(similarity ≥ {SIMILAR_THRESHOLD})."
    )
    return top_owner, reason
