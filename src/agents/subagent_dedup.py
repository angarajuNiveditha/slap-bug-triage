"""
subagent_dedup.py — Final duplicate-decision sub-agent.

Takes the new bug + the top-K candidates from subagent_embeddings and
makes a focused dup/no-dup call. Separated from embeddings so the
decision is independently auditable and matches the production diagram.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..agent_parser import BugReport
from ..claude_cli   import call_claude


DUPLICATE_CONFIDENCE_THRESHOLD = 0.80


@dataclass
class DedupResult:
    duplicate_of:          Optional[str]
    duplicate_confidence:  float
    duplicate_reasoning:   Optional[str]


PROMPT_TEMPLATE = """You are the SLAP dedup sub-agent. You receive a new bug report and a short list of similar historical bugs (already ranked by an embeddings sub-agent). Your single job: decide whether the new bug is essentially the SAME bug as any of the candidates, with confidence ≥ {threshold:.2f}.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "duplicate_of":         "FLIPPI-XXXX" or null,
  "duplicate_confidence": number 0.0-1.0,
  "reasoning":            "one sentence — why this IS or ISN'T a duplicate"
}}

Strict criteria for marking a duplicate:
- Same root cause / failure mode (not just same area or topic).
- Same user-facing symptom and trigger.
- A confidence ≥ {threshold:.2f} should mean "if these were filed today as two tickets, an engineer would link them as duplicates."
- If unsure → return null. False duplicates waste engineer time.

NEW BUG:
  Title:        {title}
  Description:  {description}
  Impact:       {impact}
  Actual:       {actual}
  Platform:     {platform}

TOP CANDIDATES (already ranked, JSON):
{candidates_json}

Reply with ONLY the JSON object."""


def decide_duplicate(bug: BugReport, candidates: list) -> DedupResult:
    if not candidates:
        return DedupResult(None, 0.0, None)

    import json
    compact = [
        {
            "key":        m.key,
            "summary":    m.summary,
            "priority":   m.priority,
            "similarity": m.similarity,
        }
        for m in candidates
    ]

    prompt = PROMPT_TEMPLATE.format(
        threshold       = DUPLICATE_CONFIDENCE_THRESHOLD,
        title           = bug.title,
        description     = bug.description,
        impact          = bug.impact,
        actual          = bug.actual_result,
        platform        = bug.platform,
        candidates_json = json.dumps(compact, indent=2),
    )

    response = call_claude(prompt, expect_json=True)
    if not isinstance(response, dict):
        raise ValueError(f"Dedup sub-agent returned non-object: {type(response).__name__}")

    dup_key = response.get("duplicate_of")
    try:
        dup_conf = float(response.get("duplicate_confidence", 0.0))
    except (TypeError, ValueError):
        dup_conf = 0.0

    # Trust only if confidence clears the threshold AND the key was in our candidates
    candidate_keys = {m.key for m in candidates}
    if dup_key and (dup_conf < DUPLICATE_CONFIDENCE_THRESHOLD or dup_key not in candidate_keys):
        dup_key = None

    return DedupResult(
        duplicate_of         = dup_key,
        duplicate_confidence = round(dup_conf, 3),
        duplicate_reasoning  = response.get("reasoning"),
    )
