"""
claude_similarity.py — Find similar bugs via Claude Code (replaces TF-IDF).

Single LLM call per query: we send the new bug + all 300 cached historical
bugs in one prompt, and Claude returns the top-K similar bugs with confidence
scores, a duplicate flag, and a suggested owner.

Returns the SAME dataclasses (SimilarBug, SimilarityResult) as
src.tfidf_similarity so downstream code (ticket builder) works unchanged.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .agent_parser import BugReport
from .claude_cli import call_claude
from .jira_client import JiraClient
from .tfidf_similarity import SimilarBug, SimilarityResult

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")

# Confidence threshold for marking a similar bug as a duplicate candidate.
# Claude's self-reported similarity is on a 0–1 scale, where 0.80+ means
# "essentially the same bug" per the prompt instructions.
DUPLICATE_THRESHOLD = 0.80
TOP_K               = 5

# Trim each historical bug's description so the prompt stays in budget.
HIST_SUMMARY_MAX = 200
HIST_DESC_MAX    = 350


PROMPT_TEMPLATE = """You are a bug-deduplication assistant for the Flipkart SLAP team.

You will be given (1) a NEW bug report and (2) a list of HISTORICAL bugs from our Jira project. Your job is to find the {top_k} historical bugs that are most similar to the new one, decide whether any of them is essentially the same bug (a duplicate), and suggest an owner based on assignee patterns in the top matches.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "similar_bugs": [
    {{
      "key":        "FLIPPI-XXXX",
      "similarity": number 0.0–1.0,
      "reasoning":  "one-line reason this historical bug is similar"
    }},
    ... up to {top_k} entries, ordered by similarity descending
  ],
  "duplicate_of":         "FLIPPI-XXXX" or null,
  "duplicate_confidence": number 0.0–1.0,
  "duplicate_reasoning":  "one sentence" or null,
  "suggested_owner":      "Full Name" or null,
  "owner_reasoning":      "one sentence based on assignees of top matches"
}}

SIMILARITY SCALE
  0.00 — unrelated
  0.30 — same general area or symptom
  0.60 — same component and similar failure mode
  0.80 — very close, likely same root cause
  1.00 — essentially the same bug
A duplicate requires similarity ≥ 0.80.

NEW BUG:
  Title:        {new_title}
  Description:  {new_description}
  Impact:       {new_impact}
  Actual:       {new_actual}
  Platform:     {new_platform}
  Reproducibility: {new_repro}

HISTORICAL BUGS (JSON list of {hist_count} entries):
{historical_bugs_json}

Reply with ONLY the JSON object."""


class SimilarityEngine:
    """
    Claude-powered similarity engine. Caches 300 historical bugs once,
    then sends them as context on every `find_similar` call.
    """

    def __init__(self):
        self._issues: list = []
        self._by_key: dict = {}
        # Cache: compact representation of all historical bugs, built once.
        self._compact_cache: Optional[list] = None

    # ----- index management -------------------------------------------------

    def build_index(self, issues: list) -> None:
        if not issues:
            print("  [claude-similarity] no issues to cache")
            return
        self._issues = issues
        self._by_key = {iss.get("key"): iss for iss in issues if iss.get("key")}
        self._compact_cache = [self._compact_one(iss) for iss in issues]
        print(
            f"  [claude-similarity] cached {len(issues)} historical bugs "
            f"(~{sum(len(json.dumps(c)) for c in self._compact_cache)//1024} KB of prompt context)"
        )

    # ----- query ------------------------------------------------------------

    def find_similar(self, bug: BugReport) -> SimilarityResult:
        if not self._compact_cache:
            return SimilarityResult(
                top_matches=[],
                suggested_owner=None,
                owner_reason="No historical bugs cached.",
                duplicate_of=None,
                duplicate_confidence=0.0,
            )

        prompt = PROMPT_TEMPLATE.format(
            top_k=TOP_K,
            hist_count=len(self._compact_cache),
            new_title=bug.title,
            new_description=bug.description,
            new_impact=bug.impact,
            new_actual=bug.actual_result,
            new_platform=bug.platform,
            new_repro=bug.reproducibility,
            historical_bugs_json=json.dumps(self._compact_cache, indent=2),
        )

        response = call_claude(prompt, expect_json=True, timeout=240)
        if not isinstance(response, dict):
            raise ValueError(
                f"Claude similarity returned non-object: {type(response).__name__}"
            )

        return self._build_result(response)

    # ----- helpers ----------------------------------------------------------

    def _compact_one(self, issue: dict) -> dict:
        """Turn a full Jira issue into the minimal dict we send to Claude."""
        fields  = issue.get("fields", {}) or {}
        summary = (fields.get("summary") or "")[:HIST_SUMMARY_MAX]
        desc    = JiraClient.extract_text(issue)
        # extract_text returns "summary\n\ndescription"; drop the summary prefix
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

    def _build_result(self, response: dict) -> SimilarityResult:
        similar_raw = response.get("similar_bugs") or []
        top_matches: list[SimilarBug] = []

        for entry in similar_raw[:TOP_K]:
            key = entry.get("key", "")
            try:
                sim = float(entry.get("similarity", 0.0))
            except (TypeError, ValueError):
                sim = 0.0
            issue = self._by_key.get(key, {})
            summary  = (issue.get("fields", {}) or {}).get("summary", "")
            assignee = JiraClient.extract_assignee(issue) if issue else None
            priority = JiraClient.extract_priority(issue) if issue else "P3"

            top_matches.append(SimilarBug(
                key=key,
                summary=summary,
                similarity=round(sim, 3),
                assignee=assignee,
                priority=priority,
                is_duplicate_candidate=(sim >= DUPLICATE_THRESHOLD),
                url=f"{JIRA_BASE_URL}/browse/{key}" if key else "",
            ))

        # Duplicate
        dup_key  = response.get("duplicate_of")
        try:
            dup_conf = float(response.get("duplicate_confidence", 0.0))
        except (TypeError, ValueError):
            dup_conf = 0.0
        # Trust Claude's flag only if it picks a key from the top matches.
        if dup_key and dup_key not in self._by_key:
            dup_key = None

        # Owner
        owner        = response.get("suggested_owner")
        owner_reason = response.get("owner_reasoning") or ""
        if not owner and top_matches:
            # Fallback: most frequent assignee on top matches
            counts: dict[str, int] = {}
            for m in top_matches:
                if m.assignee:
                    counts[m.assignee] = counts.get(m.assignee, 0) + 1
            if counts:
                owner = max(counts, key=lambda k: counts[k])
                owner_reason = (
                    f"Assigned to {owner} on {counts[owner]}/{len(top_matches)} "
                    "most-similar past bugs (fallback — Claude returned no owner)."
                )

        return SimilarityResult(
            top_matches=top_matches,
            suggested_owner=owner,
            owner_reason=owner_reason,
            duplicate_of=dup_key,
            duplicate_confidence=round(dup_conf, 3),
        )
