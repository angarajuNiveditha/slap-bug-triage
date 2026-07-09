"""
subagent_triage.py — Severity / priority sub-agent.

Receives the parsed bug + the top-K similar historical bugs and assigns
a priority (P0–P3) with a plain-English justification.
"""

from __future__ import annotations

import json

from ..rule_based.agent_parser import BugReport
from ..rule_based.agent_scorer import (
    PRIORITY_ID_MAP,
    SEVERITY_FOR_PRIORITY,
    SeverityResult,
)
from ..shared.claude_cli import call_claude


PROMPT_TEMPLATE = """You are the SLAP triage sub-agent. Assign a priority (P0, P1, or P2) to the bug below.

PRIMARY METHOD — use the priorities of similar past bugs.
You are given the top similar bugs from FLIPPI's history (below), each
with the priority your team filed it at. Those priorities are your
STRONGEST signal: if 3 of the 5 closest matches are P1, the new bug is
almost certainly P1. If they unanimously agree on a priority, go with
that priority unless a hard override below kicks in. Use the priority
ladder only when the similar bugs disagree, are weak matches, or are
absent.

PRIORITY LADDER (3 tiers):

P0  — Critical, needs immediate hotfix. Any of:
        • App crash
        • ANR (Application Not Responding)
        • Payment failed or blocked
        • Security or secrets risk
        • User blocked / user loop / cannot make progress
        • Revenue-blocking
        • Major UI/UX breaking (user cannot use the affected feature at all)

P1  — Significant, ship soon. Any of:
        • UI/UX improvements (not blocking but visibly wrong)
        • Price or budget ignored / wrong
        • Text or copy changes
        • Image loading issues
        • Network interruptions
        • Error messages (missing, misleading, or wrong)
        • Tooltips
        • Toast notifications

P2  — Low scope, low severity. Any of:
        • Minor edge cases
        • Low priority / low severity bugs

HARD OVERRIDES — these win regardless of what similar bugs say:
  • A 100%-reproducible crash is ALWAYS P0
  • Any Grayskull / secrets / infra concern is ALWAYS P0

Reply with ONLY a single JSON object — no markdown fences:

{{
  "priority":      "P0" | "P1" | "P2",
  "justification": "2-3 sentences. Reference the priorities of the similar bugs you weighted. If a hard override fired, say so explicitly.",
  "key_signals":   ["short phrase", ...]   (1-4 short phrases that drove the decision)
}}

BUG:
  Title:           {title}
  Description:     {description}
  Impact:          {impact}
  Actual:          {actual}
  Platform:        {platform}
  Reproducibility: {repro}

TOP SIMILAR HISTORICAL BUGS — use their priorities as the primary signal:
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

    # 3-tier classification only: P0 / P1 / P2. Anything else (including a
    # stray P3 from a stale model response) collapses to P2 — the lowest
    # active tier in the new ladder. Vague reports never reach this point
    # because detect_quality_issues in host_agent.py routes them to refile.
    priority = response.get("priority", "P2")
    if priority not in {"P0", "P1", "P2"}:
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
