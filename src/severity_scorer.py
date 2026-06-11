"""
severity_scorer.py — Score severity and priority using Claude.

Production equivalent: Genvoy (FK managed LLM) + Astral triage classifier sub-agent.
Prototype: direct Claude API call (claude-sonnet-4-6).

Claude receives:
  - The parsed bug report
  - Top similar past bugs with their priorities
  - The FLIPPI priority definitions (P0–P4)

Returns a SeverityResult with priority, severity, and a justification.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic

from .parser import BugReport
from .similarity import SimilarBug


@dataclass
class SeverityResult:
    priority: str           # P0 / P1 / P2 / P3 / P4
    priority_id: str        # Jira priority ID for FLIPPI
    severity: str           # Blocker / Critical / Major / Minor / Cosmetic
    justification: str      # one-paragraph explanation


# Maps priority names to FLIPPI Jira IDs (from API reference §10)
PRIORITY_ID_MAP = {
    "P0": "10000",
    "P1": "10001",
    "P2": "10002",
    "P3": "10003",
    "P4": "10004",
}

SEVERITY_FOR_PRIORITY = {
    "P0": "Blocker",
    "P1": "Critical",
    "P2": "Major",
    "P3": "Minor",
    "P4": "Cosmetic",
}

SCORE_SYSTEM_PROMPT = """You are a senior engineering lead triaging bugs for SLAP
(Shop Like A Pro), Flipkart's GenAI conversational shopping app.

Your job is to assign a priority and severity to a new bug, using:
1. The bug description and impact
2. Historical similar bugs and the priorities they were assigned

Priority definitions:
- P0: Critical, blocks core flows (checkout, payment, app launch). Fix in < 30 min.
- P1: High impact, significant user/revenue impact, degradation acceptable short-term.
- P2: Medium impact, important but a workaround exists.
- P3: Low impact, cosmetic or edge-case.
- P4: Negligible impact, nice-to-fix.

Severity:
- Blocker  → P0
- Critical → P1
- Major    → P2
- Minor    → P3
- Cosmetic → P4

Return ONLY a valid JSON object (no markdown, no fences):
{
  "priority": "P0 | P1 | P2 | P3 | P4",
  "severity": "Blocker | Critical | Major | Minor | Cosmetic",
  "justification": "2-3 sentence explanation of why this priority was chosen, referencing similar bugs if relevant"
}
"""


def score_severity(bug: BugReport, similar_bugs: list[SimilarBug]) -> SeverityResult:
    """
    Ask Claude to score the severity of a bug given its description
    and a list of similar past bugs with their priorities.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Build context block for similar bugs
    similar_context = ""
    if similar_bugs:
        lines = []
        for sb in similar_bugs:
            lines.append(
                f"  - {sb.key} (similarity {sb.similarity}): "
                f'"{sb.summary}" — priority {sb.priority}'
            )
        similar_context = "Similar past bugs:\n" + "\n".join(lines)
    else:
        similar_context = "No similar past bugs found."

    user_message = f"""New bug report:
Title: {bug.title}
Platform: {bug.platform}  App version: {bug.app_version or 'unknown'}
Reproducibility: {bug.reproducibility}
Impact: {bug.impact}
Description: {bug.description}
Actual result: {bug.actual_result}

{similar_context}

Assign the priority and severity."""

    print("  [severity] calling Claude to score severity...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SCORE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_json = message.content[0].text.strip()
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]
    raw_json = raw_json.strip()

    parsed = json.loads(raw_json)
    priority = parsed.get("priority", "P2")

    return SeverityResult(
        priority=priority,
        priority_id=PRIORITY_ID_MAP.get(priority, "10002"),
        severity=parsed.get("severity", SEVERITY_FOR_PRIORITY.get(priority, "Major")),
        justification=parsed.get("justification", ""),
    )
