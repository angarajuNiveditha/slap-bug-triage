"""
claude_scorer.py — Severity scoring via Claude Code (replaces agent_scorer).

Drop-in replacement for src/agent_scorer.score_severity. Returns the same
SeverityResult dataclass so the ticket builder works unchanged.

We reuse PRIORITY_ID_MAP and SEVERITY_FOR_PRIORITY from agent_scorer to keep
the priority → ID and severity-label mappings centralized in one place.
"""

from __future__ import annotations

import json

from .agent_parser import BugReport
from .agent_scorer import (
    PRIORITY_ID_MAP,
    SEVERITY_FOR_PRIORITY,
    SeverityResult,
)
from .claude_cli import call_claude


PROMPT_TEMPLATE = """You are a severity-triage assistant for the Flipkart SLAP team.

Decide a priority (P0, P1, P2, or P3) for the bug below. Use this ladder:

  P0  Crash, checkout/payment blocked, security/secrets risk, all-users outage,
      revenue-blocking. Anything that requires an immediate hotfix.
  P1  Wrong AI results, price/budget ignored, ANRs, majority-user impact,
      core value-proposition damage. Significant degradation, not a full outage.
  P2  Partial UX degradation, image loading on slow networks, workaround exists,
      affects only a subset of users.
  P3  Vague reports with little context, cosmetic issues, minor edge cases,
      low scope.

A 100%-reproducible crash or a Grayskull/secrets/infra concern is always P0.
A vague report (under ~350 chars, no steps) defaults to P3 pending more info.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "priority":      "P0" | "P1" | "P2" | "P3",
  "justification": "2-3 sentence explanation grounded in the bug's scope, reproducibility, and similar past bugs (if any).",
  "key_signals":   ["short phrase", ...]   (1-4 short phrases that drove the decision)
}}

BUG:
  Title:           {title}
  Description:     {description}
  Impact:          {impact}
  Actual result:   {actual_result}
  Platform:        {platform}
  Reproducibility: {reproducibility}

TOP SIMILAR HISTORICAL BUGS (JSON, may be empty):
{similar_bugs_json}

Reply with ONLY the JSON object."""


def score_severity(bug: BugReport, similar_bugs: list) -> SeverityResult:
    """
    Score a BugReport's priority/severity using Claude.
    Same signature as src.agent_scorer.score_severity.
    """
    similar_compact = [
        {
            "key":        m.key,
            "summary":    m.summary,
            "priority":   m.priority,
            "similarity": m.similarity,
            "assignee":   m.assignee,
        }
        for m in (similar_bugs or [])
    ]

    prompt = PROMPT_TEMPLATE.format(
        title           = bug.title,
        description     = bug.description,
        impact          = bug.impact,
        actual_result   = bug.actual_result,
        platform        = bug.platform,
        reproducibility = bug.reproducibility,
        similar_bugs_json = json.dumps(similar_compact, indent=2),
    )

    response = call_claude(prompt, expect_json=True)
    if not isinstance(response, dict):
        raise ValueError(
            f"Claude scorer returned non-object: {type(response).__name__}"
        )

    priority = response.get("priority", "P2")
    if priority not in PRIORITY_ID_MAP:
        priority = "P2"

    signals     = response.get("key_signals") or []
    signals_str = ", ".join(str(s) for s in signals[:4]) if signals else "claude-reasoning"

    return SeverityResult(
        priority      = priority,
        priority_id   = PRIORITY_ID_MAP[priority],
        severity      = SEVERITY_FOR_PRIORITY[priority],
        justification = response.get("justification", ""),
        scoring_path  = f"claude-llm: {signals_str}",
    )
