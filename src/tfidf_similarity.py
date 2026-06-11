"""
tfidf_similarity.py — TF-IDF cosine-similarity engine (no GPU/API required).

Replaces src/similarity.py for the agent pipeline.
Uses scikit-learn TF-IDF + cosine similarity over bug summary + description text.

TF-IDF scores are lower in absolute value than embedding scores, so thresholds
are tuned accordingly:
  > 0.45 → duplicate candidate  (equivalent to ~0.88 embedding threshold)
  > 0.12 → similar bug          (equivalent to ~0.70 embedding threshold)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import os
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .jira_client import JiraClient

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")

DUPLICATE_THRESHOLD = 0.38
SIMILAR_THRESHOLD   = 0.12
TOP_K               = 5


@dataclass
class SimilarBug:
    key: str
    summary: str
    similarity: float
    assignee: Optional[str]
    priority: str
    is_duplicate_candidate: bool
    url: str = ""  # clickable link to the Jira ticket


@dataclass
class SimilarityResult:
    top_matches: list
    suggested_owner: Optional[str]
    owner_reason: str
    duplicate_of: Optional[str]
    duplicate_confidence: float


class SimilarityEngine:
    def __init__(self):
        print("  [similarity] initializing TF-IDF engine (bigrams, 10k features)...")
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=1,
            max_features=10_000,
            stop_words='english',
            sublinear_tf=True,
        )
        self._issue_index: list = []
        self._tfidf_matrix    = None

    def build_index(self, issues: list) -> None:
        if not issues:
            print("  [similarity] no issues to index")
            return
        texts = [JiraClient.extract_text(issue) for issue in issues]
        print(f"  [similarity] fitting TF-IDF over {len(texts)} issues...")
        self._tfidf_matrix = self._vectorizer.fit_transform(texts)
        self._issue_index  = issues
        print(f"  [similarity] index ready — {len(issues)} bugs, "
              f"vocab size {len(self._vectorizer.vocabulary_)}")

    def find_similar(self, query_text: str) -> SimilarityResult:
        if self._tfidf_matrix is None or not self._issue_index:
            return SimilarityResult(
                top_matches=[],
                suggested_owner=None,
                owner_reason="No historical bugs indexed.",
                duplicate_of=None,
                duplicate_confidence=0.0,
            )

        q_vec  = self._vectorizer.transform([query_text])
        scores = cosine_similarity(q_vec, self._tfidf_matrix).flatten()

        top_indices = np.argsort(scores)[::-1][:TOP_K].tolist()

        matches: list[SimilarBug] = []
        for idx in top_indices:
            sim = float(scores[idx])
            if sim < SIMILAR_THRESHOLD:
                break
            issue = self._issue_index[idx]
            key   = issue.get('key', '')
            matches.append(SimilarBug(
                key=key,
                summary=issue.get('fields', {}).get('summary', ''),
                similarity=round(sim, 3),
                assignee=JiraClient.extract_assignee(issue),
                priority=JiraClient.extract_priority(issue),
                is_duplicate_candidate=(sim >= DUPLICATE_THRESHOLD),
                url=f"{JIRA_BASE_URL}/browse/{key}" if key else "",
            ))

        dup_confidence = float(scores[top_indices[0]]) if top_indices else 0.0
        duplicate_of   = matches[0].key if (matches and matches[0].is_duplicate_candidate) else None
        suggested_owner, owner_reason = _suggest_owner(matches)

        return SimilarityResult(
            top_matches=matches,
            suggested_owner=suggested_owner,
            owner_reason=owner_reason,
            duplicate_of=duplicate_of,
            duplicate_confidence=round(dup_confidence, 3),
        )


def _suggest_owner(matches: list) -> tuple:
    counts: dict[str, int] = {}
    for m in matches:
        if m.assignee:
            counts[m.assignee] = counts.get(m.assignee, 0) + 1
    if not counts:
        return None, "No assignee data in similar bugs."
    top  = max(counts, key=lambda k: counts[k])
    n    = counts[top]
    tot  = sum(counts.values())
    reason = (
        f"Assigned to {top} on {n}/{tot} most-similar past bugs "
        f"(similarity ≥ {SIMILAR_THRESHOLD})."
    )
    return top, reason
