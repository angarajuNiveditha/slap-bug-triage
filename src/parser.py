"""
parser.py — Parse a raw bug report email into a structured BugReport.

Uses Claude API (claude-sonnet-4-6) to extract fields reliably from
free-form text, which is exactly what production Genvoy would do.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional
import anthropic


@dataclass
class BugReport:
    # Core fields
    title: str                          # One-liner summary
    description: str                    # Full explanation of the issue
    steps_to_reproduce: list[str]       # Ordered list of steps
    expected_result: str
    actual_result: str
    impact: str                         # Business/user impact

    # Classification hints
    platform: str                       # Android / iOS / Web / Unknown
    app_version: Optional[str]          # e.g. "2.4.1"
    component_hint: str                 # e.g. "Cart", "Chat", "Payments"
    reproducibility: str                # "100%", "intermittent", "conditional"

    # Meta
    reporter_email: Optional[str]
    reporter_name: Optional[str]
    raw_text: str                       # original unmodified input


PARSE_SYSTEM_PROMPT = """You are a bug triage assistant for SLAP (Shop Like A Pro),
Flipkart's GenAI conversational shopping app.

Your job is to extract structured information from a raw bug report email.
Return ONLY a valid JSON object — no markdown, no explanation, no code fences.

JSON schema:
{
  "title": "one-line summary in format [Module]: [Brief description]",
  "description": "2-3 sentence explanation of what is broken",
  "steps_to_reproduce": ["step 1", "step 2", ...],
  "expected_result": "what should happen",
  "actual_result": "what actually happens",
  "impact": "business/user impact in 1-2 sentences",
  "platform": "Android | iOS | Web | Unknown",
  "app_version": "version string or null",
  "component_hint": "the part of the app most likely affected (e.g. Cart, Chat, Payments, Search)",
  "reproducibility": "100% | intermittent | conditional | unknown",
  "reporter_email": "email or null",
  "reporter_name": "name or null"
}

Rules:
- title must start with a module prefix in square brackets, e.g. [Chat/Cart]
- steps_to_reproduce must be a list of strings, not a single string
- If a field is not mentioned in the report, use null or "Unknown"
- Never add fields not in the schema
"""


def parse_bug_report(raw_text: str) -> BugReport:
    """
    Send raw bug report text to Claude and parse the response into a BugReport.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print("  [parser] calling Claude to extract structured fields...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=PARSE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Parse this bug report:\n\n{raw_text}",
            }
        ],
    )

    raw_json = message.content[0].text.strip()

    # Defensive: strip accidental markdown fences
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]
    raw_json = raw_json.strip()

    parsed = json.loads(raw_json)

    return BugReport(
        title=parsed.get("title", "Unknown bug"),
        description=parsed.get("description", ""),
        steps_to_reproduce=parsed.get("steps_to_reproduce") or [],
        expected_result=parsed.get("expected_result", ""),
        actual_result=parsed.get("actual_result", ""),
        impact=parsed.get("impact", ""),
        platform=parsed.get("platform", "Unknown"),
        app_version=parsed.get("app_version"),
        component_hint=parsed.get("component_hint", "Unknown"),
        reproducibility=parsed.get("reproducibility", "unknown"),
        reporter_email=parsed.get("reporter_email"),
        reporter_name=parsed.get("reporter_name"),
        raw_text=raw_text,
    )
