"""
subagent_triage.py — Severity / priority sub-agent.

Receives the parsed bug + the top-K similar historical bugs and assigns
a priority (P0–P3) with a plain-English justification.
"""

from __future__ import annotations

import json

from ..agent_parser import BugReport
from ..agent_scorer import (
    PRIORITY_ID_MAP,
    SEVERITY_FOR_PRIORITY,
    SeverityResult,
)
from ..claude_cli import call_claude


PROMPT_TEMPLATE = """You are the SLAP triage sub-agent. Assign a priority (P0, P1, P2, or P3) to the bug below.

Priority ladder:
  P0  Crash, checkout/payment blocked, security/secrets risk, all-users outage, revenue-blocking. Immediate hotfix.
  P1  Wrong AI results, price/budget ignored, ANRs, majority-user impact, core value-proposition damage. Significant degradation but not full outage.
  P2  Partial UX degradation, image loading on slow networks, workaround exists, affects only a subset of users.
  P3  Vague reports, cosmetic issues, minor edge cases, low scope.

A 100%-reproducible crash, or any Grayskull/secrets/infra concern, is always P0.
A vague report (under ~350 chars with no steps) defaults to P3 pending more info.

Reply with ONLY a single JSON object — no markdown fences:

{{
  "priority":      "P0" | "P1" | "P2" | "P3",
  "justification": "2-3 sentence explanation grounded in scope, reproducibility, and similar bugs.",
  "key_signals":   ["short phrase", ...]   (1-4 short phrases that drove the decision)
}}

BUG:
  Title:           {title}
  Description:     {description}
  Impact:          {impact}
  Actual:          {actual}
  Platform:        {platform}
  Reproducibility: {repro}

TOP SIMILAR HISTORICAL BUGS (may be empty):
{similar_json}

Reply with ONLY the JSON object."""


def score_severity(bug: BugReport, similar_bugs: list) -> SeverityResult:
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
        title       = bug.title,
        description = bug.description,
        impact      = bug.impact,
        actual      = bug.actual_result,
        platform    = bug.platform,
        repro       = bug.reproducibility,
        similar_json= json.dumps(similar_compact, indent=2),
    )

    response = call_claude(prompt, expect_json=True)
    if not isinstance(response, dict):
        raise ValueError(f"Triage sub-agent returned non-object: {type(response).__name__}")

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
