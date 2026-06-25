"""
subagent_owner.py — Owner-suggestion sub-agent.

Replaces the owner-suggestion piece that used to live inside subagent_embeddings.
The split exists because:

  1. The old embeddings sub-agent was a single Claude call doing both
     similarity ranking AND owner picking. Similarity is now done by
     cosine (instant), so we don't need a 30-60s Claude call to wrap it.
  2. Owner suggestion can be meaningfully constrained to the routed
     component — historical assignees for the WRONG team should never
     show up in the suggestion (the bug that motivated this split:
     a UI engineer was being suggested for a Backend-routed ticket).

This sub-agent:
  - Takes the routed component + the top-K similar bugs + the team roster
  - Filters similar bugs to those whose component matches the routed one
  - Asks Claude to pick the most-relevant owner *from the team roster only*
  - Falls back to "most frequent assignee in component-matching similar
    bugs" if Claude is unreachable or returns an off-roster name

The fallback is important: a non-Claude path means the pipeline still
produces an owner suggestion even when the local Claude CLI is down or
the call times out.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from ..claude_cli import call_claude


@dataclass
class OwnerResult:
    suggested_owner: Optional[str]
    owner_reason:    str
    method:          str    # "claude" | "frequency-fallback" | "no-candidates"


PROMPT_TEMPLATE = """You are the SLAP triage owner-suggestion sub-agent. Pick the single best owner for a new bug, given:

NEW BUG:
  Title:           {title}
  Description:     {description}
  Component:       {component}

TEAM ROSTER for {component} (engineers who have owned bugs on this component, ordered by frequency):
{roster}

SIMILAR PAST BUGS (filtered to {component}; the closest historical neighbours of the new bug):
{similar_bugs}

Pick the owner who is most likely to be the right person for this bug. Strongly prefer assignees who appear in the similar-bugs list above — those are people who have actually fixed similar bugs. You MUST pick from the team roster; never invent a name. If multiple people on the roster look equally good, prefer the one with the most relevant similar-bug history (matches in failure mode, screen, or feature area — not just keyword overlap).

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "suggested_owner": "Full Name from the roster" or null,
  "reasoning":       "1-2 sentences explaining the choice. Reference specific similar bugs by key when relevant."
}}
"""


def _format_roster(team_roster_entries: list) -> str:
    if not team_roster_entries:
        return "(no roster available)"
    return "\n".join(
        f"  - {m['name']} ({m['bug_count']} bugs on this component)"
        for m in team_roster_entries[:15]   # cap to keep prompt tight
    )


def _format_similar(similar_bugs: list) -> str:
    if not similar_bugs:
        return "(none — no similar bugs in this component)"
    lines = []
    for s in similar_bugs[:10]:
        assignee = s.assignee or "(unassigned)"
        lines.append(
            f"  - {s.key} (sim {s.similarity:.2f}, priority {s.priority}, "
            f"assigned to {assignee}): {s.summary[:120]}"
        )
    return "\n".join(lines)


def _frequency_fallback(
    similar_component_bugs: list,
    team_roster_entries: list,
) -> OwnerResult:
    """No Claude — pick the assignee most-represented in the
    component-matching similar bugs, restricted to the team roster."""
    roster_names = {m["name"] for m in team_roster_entries}
    counts: dict[str, int] = Counter()
    for s in similar_component_bugs:
        if s.assignee and (not roster_names or s.assignee in roster_names):
            counts[s.assignee] += 1

    if counts:
        owner, n = counts.most_common(1)[0]
        total = sum(counts.values())
        return OwnerResult(
            suggested_owner = owner,
            owner_reason = (
                f"Most frequent assignee among the {len(similar_component_bugs)} "
                f"similar bugs on this component ({n}/{total} matches; roster-verified)."
            ),
            method = "frequency-fallback",
        )

    # No assignee data in the similar bugs — fall back to the top roster name.
    if team_roster_entries:
        top = team_roster_entries[0]
        return OwnerResult(
            suggested_owner = top["name"],
            owner_reason = (
                f"No assignee data in the similar bugs; defaulting to the most-active "
                f"owner on this component ({top['bug_count']} bugs)."
            ),
            method = "frequency-fallback",
        )

    return OwnerResult(
        suggested_owner = None,
        owner_reason    = "No similar bugs and no team roster available for this component.",
        method          = "no-candidates",
    )


def suggest_owner(
    title:        str,
    description:  str,
    component:    str,
    similar_bugs: list,            # list[SimilarBug] — top-K from embedding_similarity
    team_roster:  dict,            # full roster dict (component → list of {name, bug_count})
) -> OwnerResult:
    """
    Suggest an owner for a new bug, constrained to the team roster for
    `component` and informed by the subset of similar_bugs that match it.
    """
    # 1. Filter similar bugs to those on the routed component.
    same_component = [s for s in similar_bugs if (s.component or "") == component]

    # 2. Pull the roster for this component.
    roster_entries = team_roster.get(component, []) or []

    # 3. If we have nothing to work with, return null.
    if not same_component and not roster_entries:
        return OwnerResult(
            suggested_owner = None,
            owner_reason    = f"No historical bugs or roster for component '{component}'.",
            method          = "no-candidates",
        )

    # 4. Try Claude first.
    prompt = PROMPT_TEMPLATE.format(
        title        = title,
        description  = description[:1500],
        component    = component,
        roster       = _format_roster(roster_entries),
        similar_bugs = _format_similar(same_component),
    )

    try:
        response = call_claude(prompt, expect_json=True, timeout=60)
    except Exception:
        return _frequency_fallback(same_component, roster_entries)

    if not isinstance(response, dict):
        return _frequency_fallback(same_component, roster_entries)

    owner = response.get("suggested_owner")
    reasoning = (response.get("reasoning") or "").strip()

    # Validate: owner must be on the roster (or in similar-bug assignees) — guard
    # against hallucinated names.
    valid_names = {m["name"] for m in roster_entries} | {
        s.assignee for s in same_component if s.assignee
    }
    if owner and owner not in valid_names:
        # Claude made up a name — fall back.
        return _frequency_fallback(same_component, roster_entries)

    if not owner:
        # Claude returned null — fall back to frequency.
        return _frequency_fallback(same_component, roster_entries)

    return OwnerResult(
        suggested_owner = owner,
        owner_reason    = reasoning or "Suggested by Claude based on similar-bug history.",
        method          = "claude",
    )
