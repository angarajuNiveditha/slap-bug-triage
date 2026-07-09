"""
subagent_form_consistency.py — Form-field consistency sub-agent.

The structured form (app.py) lets the reporter fill three fields
independently — title, summary, and steps-to-reproduce — which can drift
apart and describe completely different bugs. (Example: title about a
caching/InfoSec issue, summary about a search-query routing bug, steps
about a login flow.) Email input doesn't have this failure mode because
it's a single narrative; a free-form email is internally consistent or
it isn't a coherent report at all.

This sub-agent only runs when the host's `from_form=True`. It uses Claude
to judge whether the three fields are talking about the same defect. If
not, it returns a quality_issue dict that the UI surfaces as the same
"refile" banner used for vague reports and image/text contradictions.

The check is conservative — short fields and naturally-different
vocabulary are fine. Only obviously-different bugs get flagged.
"""

from __future__ import annotations

from typing import Optional

from ..shared.claude_cli import call_claude


PROMPT_TEMPLATE = """You are the SLAP triage consistency-check sub-agent. The reporter filled a structured form with three fields. Decide whether they describe the SAME bug.

TITLE:
{title}

SUMMARY:
{description}

STEPS TO REPRODUCE:
{steps}

Rules:

- The three fields don't need to overlap word-for-word. A short title and a longer summary naturally use different vocabulary.
- One field elaborating on details the others didn't mention is fine.
- One field being thin or missing is fine — flag only when content is present but mismatched.
- ONLY flag when the fields obviously describe different bugs: different feature areas (e.g. caching vs. search), different failure modes (e.g. wrong-data-shown vs. wrong-routing), different user flows.

Reply with ONLY a single JSON object — no markdown fences:

{{
  "consistent":       true | false,
  "explanation":      "1-2 sentences explaining your judgement. Quote specific phrases from each field if inconsistent. Empty string if consistent.",
  "primary_bug":      "Best guess at which field(s) describe the bug the reporter actually intended. Empty string if consistent.",
  "suggested_action": "What the reporter should do to fix the report. Empty string if consistent."
}}

Reply with ONLY the JSON object."""


def check_form_consistency(
    title: str,
    description: str,
    steps_to_reproduce: list,
) -> Optional[dict]:
    """
    Returns a quality_issue dict ready to append to triage_notes.quality_issues
    when the form fields obviously describe different bugs. Returns None when
    they're consistent (or when the check failed — we never let this break the
    pipeline).
    """
    steps_text = "\n".join(f"- {s}" for s in (steps_to_reproduce or [])) or "(none)"
    prompt = PROMPT_TEMPLATE.format(
        title       = (title       or "").strip() or "(empty)",
        description = (description or "").strip() or "(empty)",
        steps       = steps_text,
    )

    try:
        response = call_claude(prompt, expect_json=True)
    except Exception:
        # Consistency-check failures must never block triage — they're a
        # nice-to-have quality gate, not a load-bearing pipeline step.
        return None

    if not isinstance(response, dict):
        return None
    if response.get("consistent", True):
        return None

    return {
        "type":             "form_fields_inconsistent",
        "severity":         "warning",
        "message": (
            response.get("explanation")
            or "The form fields appear to describe different bugs."
        ),
        "primary_bug": response.get("primary_bug", "") or "",
        "suggested_action": (
            response.get("suggested_action")
            or "Refile the form with title, summary, and steps that all describe the same bug."
        ),
    }
