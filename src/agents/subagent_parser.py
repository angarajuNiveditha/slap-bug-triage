"""
subagent_parser.py — Email + media findings → structured BugReport.

Sub-agent in the Astral multi-agent pipeline. Takes raw email text plus an
optional one-line summary from the media sub-agent (folded into the body
before parsing), and returns a populated BugReport dataclass.
"""

from __future__ import annotations

from typing import Optional

from ..agent_parser import BugReport
from ..claude_cli   import call_claude


PROMPT_TEMPLATE = """You are the SLAP triage parser sub-agent. Read the bug report below and extract structured fields. Reply with ONLY a single JSON object — no markdown fences, no commentary.

Required keys:

{{
  "title":              short ticket title prefixed with a module tag. Choose from: [Checkout]:, [Cart]:, [Payments]:, [Auth]:, [UI/Images]:, [Search/AI]:, [Chat/AI]:, [Feed/Search]:, [Backend/Infra]:, [VTON]:, [Price]:, or [SLAP]: if uncertain.
  "description":        2-3 sentence summary (max 450 chars).
  "steps_to_reproduce": array of strings; empty list if none.
  "expected_result":    string; "Not provided." if missing.
  "actual_result":      string; "Not provided." if missing.
  "impact":             string; "Not provided." if missing.
  "platform":           one of: "Android", "iOS", "Web", or comma-separated combos, or "Unknown".
  "app_version":        e.g. "2.4.2" or null.
  "reproducibility":    one of: "100%", "intermittent", "conditional", "~N%", "unknown".
  "reporter_email":     string or null.
  "reporter_name":      string or null.
}}

Note: component classification is NOT your job. The host pipeline runs a
dedicated embedding-based classifier on the parsed bug after you finish.
Do not include a "component_hint" field in your output.

BUG REPORT:
---
{email_text}
---

Reply with ONLY the JSON object."""


def parse_bug_report(raw_text: str, media_summary: Optional[str] = None) -> BugReport:
    """
    Parse the bug report. If media_summary is provided (from subagent_media),
    it is prepended to the email body so the parser has visual context too.
    """
    body = raw_text.strip()
    if media_summary:
        body = (
            f"[Media findings from attached images]\n{media_summary.strip()}\n"
            f"\n[Email body]\n{body}"
        )

    prompt = PROMPT_TEMPLATE.format(email_text=body)
    parsed = call_claude(prompt, expect_json=True)
    if not isinstance(parsed, dict):
        raise ValueError(f"Parser returned non-object: {type(parsed).__name__}")

    return BugReport(
        title              = parsed.get("title") or "[SLAP]: Bug report",
        description        = parsed.get("description") or "",
        steps_to_reproduce = parsed.get("steps_to_reproduce") or [],
        expected_result    = parsed.get("expected_result") or "Not provided.",
        actual_result      = parsed.get("actual_result") or "Not provided.",
        impact             = parsed.get("impact") or "Not provided.",
        platform           = parsed.get("platform") or "Unknown",
        app_version        = parsed.get("app_version"),
        component_hint     = parsed.get("component_hint") or "bugs",
        reproducibility    = parsed.get("reproducibility") or "unknown",
        reporter_email     = parsed.get("reporter_email"),
        reporter_name      = parsed.get("reporter_name"),
        raw_text           = raw_text,
    )
