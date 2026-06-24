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
  "component_hint":     exactly one of: "Backend", "Backend-Labs", "DS", "UI", "immersive", "bugs".
  "reproducibility":    one of: "100%", "intermittent", "conditional", "~N%", "unknown".
  "reporter_email":     string or null.
  "reporter_name":      string or null.
}}

COMPONENT CLASSIFICATION (priority order — check teams top-to-bottom; the first one that fits wins).

This ordering was tuned against 300 real FLIPPI bug routings. Note that UI is checked BEFORE Backend-Labs / DS / Backend because platform-prefixed bugs ([iOS]/[Android]/[RN]) are tagged UI even on BE_Labs surfaces.

immersive — Native AR / VTO SDK layer (objective-C / native Java / AR SDK).
            • ANRs in native code
            • drishyamukh
            • Crashes in the native-AR rendering layer (not React Native crashes)

UI — React Native / iOS / Android frontend layer. Pick this for:
   • Titles starting with [iOS], [Android], [RN], [Native][...], or "iOS_" / "Android_"
   • Visual / layout / spacing / alignment / overlap issues
   • Element visibility / hidden states / not rendering
   • Touch interaction: not clickable, not tappable, swipe, gesture, scroll, pull-to-refresh
   • UI components when the bug is about UI behaviour:
       keyboard, hamburger menu, dropdown, textbox / TextInput / textinputbar / inputbar
   • Inside-bottomsheet click / scroll issues
   • Image cropping / pixelation / clipping / cropper UI
   • Animation / flickering / flashing / frozen animation
   • Native build issues: CocoaPods, Xcode, objectVersion, gradle, pbxproj
   • Onboarding-page DESIGN bugs ([RN] Onboarding Page Design Changes) — distinct from
     onboarding-FLOW logic which is Backend
   • Form validation visuals (character limits, name input, OTP input UX)
   • UI controls failing: "Show all reviews", "View more", "View all offers"
   • "Not opening any" specific page

Backend-Labs — Experimental ML / personalization features:
   • VTON / virtual try-on / draping / Q2P / Machine Identity
   • Social Finds, Review Synth, Decoded Looks
   • Style Drops — also spelled "Styledrops", "styledrops", or "[StyleDrops]" with no space
   • Vibes Player feature (vibe / vibes / "Vibes API")
   • Moodboard, Avatar generation, AI generation / AI rendering
   • Cosmos dashboard, Frame status, Frames status
   • Reels ingestion ("sending reel" / "after sending reel")
   • Liked drops, drop generation ("drops are showing", "drop ready", "generating your drops")
   • Edison touches when in BE_Labs context ("styledrops edison", "notifying edison")
   • IMPORTANT: a visual/rendering bug on a BE_Labs surface that's tagged
     [iOS]/[Android]/[RN] is UI (handled above), NOT BE_Labs.

DS — Data science / model quality / content presentation / result relevance:
   • NPS, %Positive, ranking quality, recommendation quality discrepancies
   • Result relevance: "wrong results", "results not shown", "got only N results",
     "irrelevant", "less relevant", "old query products", "stale results"
   • Summary / suggestion mismatches: "summary not matching", "wrong summary",
     "product suggestion is missing"
   • Model behaviour: "failed to answer", "model failed", "general intelligence",
     "grounding", "inappropriate", "unsafe request", "prompt still needs work"
   • Content presentation: "text cut off", "showing tables", "tabular", "hyperlink instead",
     "bad state message"
   • Scope/range mismatch ("above price range but results are for below"),
     context-switching wrong results

Backend — Core backend: chat AI, search, cart, checkout, payment, auth, OTP, sessions,
          login, signup, Grayskull, secrets management, Edison (when NOT in Styledrops /
          Vibes context), infra, feed dedup, journey continuation, bot, conversation
          handling, API endpoints, log levels, product compare, DA flow.

bugs — Return "bugs" when you genuinely cannot classify with confidence. A wrong
       routing wastes more engineering time than a manual-triage step. **Prefer
       "bugs" over a guess.**

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
