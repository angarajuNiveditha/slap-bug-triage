"""
subagent_embeddings.py — Retrieve top-K similar historical bugs from Jira.

This sub-agent does NOT make the duplicate decision (that belongs to
subagent_dedup). It only ranks candidates by semantic similarity and
suggests an owner based on assignee patterns.

The result is consumed by the host agent (Astral) and passed on to
subagent_dedup for the final duplicate call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from ..agent_parser     import BugReport
from ..claude_cli       import call_claude
from ..jira_client      import JiraClient
from ..tfidf_similarity import SimilarBug

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")

TOP_K            = 5
HIST_SUMMARY_MAX = 200
HIST_DESC_MAX    = 350


@dataclass
class EmbeddingsResult:
    top_matches:     list                    # list[SimilarBug] — duplicate flag NOT set here
    suggested_owner: Optional[str]
    owner_reason:    str


PROMPT_TEMPLATE = """You are the SLAP embeddings sub-agent — you find the bugs in the historical Jira corpus that are most similar to a new bug, and suggest an owner. You do NOT decide whether anything is a duplicate; that is a separate sub-agent's job.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "similar_bugs": [
    {{
      "key":        "FLIPPI-XXXX",
      "similarity": number 0.0-1.0,
      "reasoning":  "one-line reason this historical bug is similar"
    }},
    ... up to {top_k} entries, ordered by similarity descending
  ],
  "suggested_owner": "Full Name" or null,
  "owner_reasoning": "one sentence based on assignees of top matches and the nature of the new bug"
}}

SIMILARITY SCALE
  0.00 — unrelated
  0.30 — same general area or symptom
  0.60 — same component and similar failure mode
  0.80 — very close, likely same root cause
  1.00 — essentially the same bug

NEW BUG:
  Title:           {new_title}
  Description:     {new_description}
  Impact:          {new_impact}
  Actual:          {new_actual}
  Platform:        {new_platform}
  Reproducibility: {new_repro}

HISTORICAL BUGS (JSON list of {hist_count} entries):
{historical_bugs_json}

Reply with ONLY the JSON object."""


class EmbeddingsEngine:
    def __init__(self) -> None:
        self._issues: list = []
        self._by_key: dict = {}
        self._compact_cache: Optional[list] = None

    def build_index(self, issues: list) -> None:
        if not issues:
            print("  [embeddings] no issues to cache")
            return
        self._issues = issues
        self._by_key = {iss.get("key"): iss for iss in issues if iss.get("key")}
        self._compact_cache = [self._compact_one(iss) for iss in issues]
        print(
            f"  [embeddings] cached {len(issues)} historical bugs "
            f"(~{sum(len(json.dumps(c)) for c in self._compact_cache)//1024} KB)"
        )

    def find_similar(self, bug: BugReport) -> EmbeddingsResult:
        if not self._compact_cache:
            return EmbeddingsResult([], None, "No historical bugs cached.")

        prompt = PROMPT_TEMPLATE.format(
            top_k                = TOP_K,
            hist_count           = len(self._compact_cache),
            new_title            = bug.title,
            new_description      = bug.description,
            new_impact           = bug.impact,
            new_actual           = bug.actual_result,
            new_platform         = bug.platform,
            new_repro            = bug.reproducibility,
            historical_bugs_json = json.dumps(self._compact_cache, indent=2),
        )

        response = call_claude(prompt, expect_json=True, timeout=240)
        if not isinstance(response, dict):
            raise ValueError(f"Embeddings sub-agent returned non-object: {type(response).__name__}")

        return self._build_result(response)

    # ------------------------------------------------------------------
    def _compact_one(self, issue: dict) -> dict:
        fields  = issue.get("fields", {}) or {}
        summary = (fields.get("summary") or "")[:HIST_SUMMARY_MAX]
        desc    = JiraClient.extract_text(issue)
        if desc.startswith(summary):
            desc = desc[len(summary):].strip()
        if len(desc) > HIST_DESC_MAX:
            desc = desc[:HIST_DESC_MAX].rstrip() + "..."
        return {
            "key":         issue.get("key", ""),
            "summary":     summary,
            "description": desc,
            "priority":    JiraClient.extract_priority(issue),
            "assignee":    JiraClient.extract_assignee(issue),
        }

    def _build_result(self, response: dict) -> EmbeddingsResult:
        similar_raw = response.get("similar_bugs") or []
        top: list[SimilarBug] = []

        for entry in similar_raw[:TOP_K]:
            key = entry.get("key", "")
            try:
                sim = float(entry.get("similarity", 0.0))
            except (TypeError, ValueError):
                sim = 0.0
            issue    = self._by_key.get(key, {})
            summary  = (issue.get("fields", {}) or {}).get("summary", "")
            assignee = JiraClient.extract_assignee(issue) if issue else None
            priority = JiraClient.extract_priority(issue) if issue else "P3"
            top.append(SimilarBug(
                key=key,
                summary=summary,
                similarity=round(sim, 3),
                assignee=assignee,
                priority=priority,
                is_duplicate_candidate=False,   # dedup sub-agent decides this
                url=f"{JIRA_BASE_URL}/browse/{key}" if key else "",
            ))

        owner        = response.get("suggested_owner")
        owner_reason = response.get("owner_reasoning") or ""
        if not owner and top:
            counts: dict[str, int] = {}
            for m in top:
                if m.assignee:
                    counts[m.assignee] = counts.get(m.assignee, 0) + 1
            if counts:
                owner = max(counts, key=lambda k: counts[k])
                owner_reason = (
                    f"Assigned to {owner} on {counts[owner]}/{len(top)} "
                    "most-similar past bugs (frequency fallback)."
                )

        return EmbeddingsResult(top, owner, owner_reason)
