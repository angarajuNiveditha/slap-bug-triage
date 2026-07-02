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

from ..claude_cli  import call_claude
from ..team_config import MANAGER_NAMES, TEAM_MANAGERS


@dataclass
class OwnerResult:
    suggested_owner: Optional[str]
    owner_reason:    str
    method:          str
    # Values:
    #   "claude"                     — Claude picked an engineer with similar-bug history
    #   "frequency-fallback"         — deterministic pick from engineers with similar-bug history
    #   "manager-from-similar-bug"   — no engineer in similar bugs; used the manager on the closest bug
    #   "manager-escalation"         — no similar bugs at all; used TEAM_MANAGERS[component]
    #   "no-candidates"              — nothing to assign (e.g. DS with no manager mapped)


PROMPT_TEMPLATE = """You are the SLAP triage owner-suggestion sub-agent. Pick the single best owner for a new bug from the ENGINEERS BELOW (all of whom have been assigned similar bugs on this component).

NEW BUG:
  Title:           {title}
  Description:     {description}
  Component:       {component}

CANDIDATE ENGINEERS (each has at least one similar-bug hit on {component} — assignee, count of similar-bug matches):
{engineer_candidates}

SIMILAR PAST BUGS on {component} (for context — includes bugs assigned to managers marked [MANAGER], but you do NOT pick those):
{similar_bugs}

Selection rule:
- Pick the single engineer from CANDIDATE ENGINEERS whose historical bugs most closely match this new bug's failure mode (screen, symptom, feature area — not just keyword overlap).
- If NO candidate engineer is a plausible match for the failure mode described, return `null` — the system will fall back to a manager automatically.
- Do NOT pick any name that isn't in CANDIDATE ENGINEERS. Do NOT pick a `[MANAGER]` name. Do NOT invent names.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "suggested_owner": "Full Name from CANDIDATE ENGINEERS" or null,
  "reasoning":       "1-2 sentences explaining the choice. Reference specific similar bugs by key."
}}
"""


def _format_similar(similar_bugs: list) -> str:
    """Format the similar-bugs table for the prompt. Assignees who are
    managers get a `[MANAGER]` marker so Claude doesn't treat them as
    default owners — they're for context only in the prompt."""
    if not similar_bugs:
        return "(none — no similar bugs in this component)"
    lines = []
    for s in similar_bugs[:10]:
        if s.assignee:
            tag = " [MANAGER]" if s.assignee in MANAGER_NAMES else ""
            assignee_str = f"{s.assignee}{tag}"
        else:
            assignee_str = "(unassigned)"
        lines.append(
            f"  - {s.key} (sim {s.similarity:.2f}, priority {s.priority}, "
            f"assigned to {assignee_str}): {s.summary[:120]}"
        )
    return "\n".join(lines)


def _format_engineer_candidates(engineer_counts: dict, engineer_bugs: dict) -> str:
    """Format the CANDIDATE ENGINEERS block: engineers with at least one
    similar-bug hit on this component. Each line shows the name, hit
    count, and the keys of the bugs that back the count."""
    if not engineer_counts:
        return "(none — no engineer has similar-bug history on this component)"
    lines = []
    for name, count in sorted(engineer_counts.items(), key=lambda kv: -kv[1]):
        keys = ", ".join(engineer_bugs.get(name, [])[:5])
        lines.append(f"  - {name} ({count} similar-bug hit(s); e.g. {keys})")
    return "\n".join(lines)


def _closest_manager_owner(same_component_bugs: list) -> OwnerResult:
    """No engineer has similar-bug history. If any similar bug on this
    component was assigned to a manager, pick the manager who was on the
    single most-similar bug (highest cosine similarity) — that manager
    is the closest to the failure mode."""
    manager_bugs = [
        s for s in same_component_bugs
        if s.assignee and s.assignee in MANAGER_NAMES
    ]
    if not manager_bugs:
        return None    # caller will fall through to team-manager escalation
    closest = max(manager_bugs, key=lambda s: s.similarity)
    return OwnerResult(
        suggested_owner = closest.assignee,
        owner_reason    = (
            f"No engineer has been assigned a similar bug on this component. "
            f"The closest similar bug ({closest.key}, sim {closest.similarity:.2f}) "
            f"was owned by manager {closest.assignee} — assigning to them as the "
            f"most-relevant owner."
        ),
        method = "manager-from-similar-bug",
    )


def _escalate_to_team_manager(component: str) -> OwnerResult:
    """No similar bugs at all (or none had assignees). Assign to the
    team's manager per TEAM_MANAGERS. If the component has no manager
    mapped (e.g. DS), return `no-candidates` for manual triage."""
    manager = TEAM_MANAGERS.get(component)
    if manager:
        return OwnerResult(
            suggested_owner = manager,
            owner_reason    = (
                f"No similar bugs exist for {component} — escalating to team "
                f"manager ({manager})."
            ),
            method = "manager-escalation",
        )
    return OwnerResult(
        suggested_owner = None,
        owner_reason    = (
            f"No similar bugs on {component} and no team manager mapped — "
            f"manual triage required."
        ),
        method = "no-candidates",
    )


def suggest_owner(
    title:        str,
    description:  str,
    component:    str,
    similar_bugs: list,            # list[SimilarBug] — top-K from embedding_similarity
    team_roster:  dict,            # full roster dict (component → list of {name, bug_count})
) -> OwnerResult:
    """
    Suggest an owner for a new bug on the routed component using a strict
    "who has actually touched this failure area" rule:

      1. If any ENGINEER (non-manager) has been assigned a similar bug
         on this component, Claude picks the best match among them; on
         Claude failure, the highest-count engineer wins deterministically.

      2. Otherwise, if only MANAGERS appear in the similar-bug assignees,
         assign to the manager who owned the SINGLE CLOSEST bug (highest
         cosine similarity) — they're the person most familiar with this
         specific failure mode.

      3. Otherwise (no similar bugs, or none had assignees), escalate to
         the component's team manager per TEAM_MANAGERS.

      4. If the component has no team manager mapped (DS), return
         `no-candidates` and let the human triage.

    Roster frequency alone is NEVER used to pick an owner — an engineer
    with 60 general Backend bugs but zero hits on this failure mode is
    not a better candidate than the manager who actually owned the
    closest similar bug. `team_roster` is unused in the picking logic
    today but kept in the signature for a possible future "active
    engineer" filter (someone might appear in similar-bug assignees
    but no longer be on the team — the roster is where we'd check).
    """
    # Suppress the "team_roster unused" hint until we bring active-engineer
    # filtering back. Keeps the call-site signature stable.
    _ = team_roster

    # 1. Filter similar bugs to those on the routed component.
    same_component = [s for s in similar_bugs if (s.component or "") == component]

    if not same_component:
        return _escalate_to_team_manager(component)

    # 2. Count similar-bug hits per engineer (managers excluded).
    engineer_counts: dict = Counter()
    engineer_bugs:   dict = {}
    for s in same_component:
        if s.assignee and s.assignee not in MANAGER_NAMES:
            engineer_counts[s.assignee] += 1
            engineer_bugs.setdefault(s.assignee, []).append(s.key)

    # 3. No engineer in similar-bug assignees → manager-based fallbacks.
    if not engineer_counts:
        closest = _closest_manager_owner(same_component)
        if closest:
            return closest
        return _escalate_to_team_manager(component)

    # 4. At least one engineer has similar-bug history — ask Claude to
    #    pick the most-relevant one. Constrain the pool via prompt +
    #    validation so we never accept a name outside the candidate list.
    candidate_names = set(engineer_counts.keys())
    prompt = PROMPT_TEMPLATE.format(
        title               = title,
        description         = description[:1500],
        component           = component,
        engineer_candidates = _format_engineer_candidates(engineer_counts, engineer_bugs),
        similar_bugs        = _format_similar(same_component),
    )
    try:
        response = call_claude(prompt, expect_json=True, timeout=60)
    except Exception:
        response = None

    if isinstance(response, dict):
        owner     = response.get("suggested_owner")
        reasoning = (response.get("reasoning") or "").strip()
        if owner and owner in candidate_names:
            return OwnerResult(
                suggested_owner = owner,
                owner_reason    = reasoning or "Suggested by Claude based on similar-bug history.",
                method          = "claude",
            )
        # Otherwise (null, off-list name, manager pick) → deterministic fallback.

    # 5. Deterministic fallback: highest-count engineer among the candidates.
    winner, n = engineer_counts.most_common(1)[0]
    return OwnerResult(
        suggested_owner = winner,
        owner_reason    = (
            f"Highest similar-bug match count on {component} "
            f"({n} of {sum(engineer_counts.values())} candidate hits); "
            f"e.g. {', '.join(engineer_bugs[winner][:3])}."
        ),
        method = "frequency-fallback",
    )
