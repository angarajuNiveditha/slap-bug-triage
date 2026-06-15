"""
claude_parser.py — Email → BugReport via Claude Code headless mode.

Drop-in replacement for src/agent_parser.parse_bug_report. Returns the same
BugReport dataclass so the rest of the pipeline (ticket builder) works
unchanged.
"""

from __future__ import annotations

from .agent_parser import BugReport
from .claude_cli import call_claude


PROMPT_TEMPLATE = """You are a bug-report parser for an internal Flipkart engineering tool (the SLAP triage agent).

Read the bug report email below and extract structured fields. Reply with ONLY a single JSON object — no markdown fences, no prose, no commentary before or after.

Required keys (use exact names):

{{
  "title":              string — short ticket title prefixed with a module tag. Choose from: [Checkout]:, [Cart]:, [Payments]:, [Auth]:, [UI/Images]:, [Search/AI]:, [Chat/AI]:, [Feed/Search]:, [Backend/Infra]:, or [SLAP]: if uncertain.
  "description":        string — 2–3 sentence summary of the bug (max 450 chars).
  "steps_to_reproduce": array of strings — extracted from the Steps section, empty list if none.
  "expected_result":    string — what the user expected. "Not provided." if missing.
  "actual_result":      string — what actually happened. "Not provided." if missing.
  "impact":             string — the Impact section. "Not provided." if missing.
  "platform":           string — one of: "Android", "iOS", "Web", "Android, iOS, Web" (comma-separated combos), or "Unknown".
  "app_version":        string or null — version like "2.4.2" if mentioned.
  "component_hint":     string — exactly one of: "Backend", "Backend-Labs", "DS", "UI", "immersive", "bugs".
  "reproducibility":    string — one of: "100%", "intermittent", "conditional", "~N%" (with a number), or "unknown".
  "reporter_email":     string or null — From: header email.
  "reporter_name":      string or null — sender's display name.
}}

COMPONENT CLASSIFICATION RULES (priority order, first match wins):
  immersive    — native AR, VTO SDK, ANRs in native code, drishyamukh.
  Backend-Labs — VTON, virtual try-on, Social Finds, Review Synth, Decoded Looks, Style Drops, Q2P, machine identity.
  DS           — NPS, %Positive, model quality, ranking, product-page analytics, recommendation quality discrepancies.
  UI           — React Native, iOS/Android visual rendering, image loading, cold start, login screen flashes.
  Backend      — chat AI, search, cart, checkout, payments, auth, OTP, sessions, Grayskull, infra, feed dedup, journey continuation, bot.
  bugs         — cannot confidently classify; needs manual routing.

BUG REPORT EMAIL:
---
{email_text}
---

Reply with ONLY the JSON object."""


def parse_bug_report(raw_text: str) -> BugReport:
    """
    Parse a raw bug report email into a BugReport using Claude Code.
    Same signature as src.agent_parser.parse_bug_report.
    """
    prompt = PROMPT_TEMPLATE.format(email_text=raw_text.strip())
    parsed = call_claude(prompt, expect_json=True)

    if not isinstance(parsed, dict):
        raise ValueError(f"Claude parser returned non-object: {type(parsed).__name__}")

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
