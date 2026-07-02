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
    method:          str    # "claude" | "frequency-fallback" | "manager-escalation" | "no-candidates"


PROMPT_TEMPLATE = """You are the SLAP triage owner-suggestion sub-agent. Pick the single best owner for a new bug, given:

NEW BUG:
  Title:           {title}
  Description:     {description}
  Component:       {component}

TEAM ROSTER for {component} (engineers who have owned bugs on this component, ordered by frequency; managers are excluded from this list):
{roster}

TEAM MANAGER for {component}: {manager}
(The manager is the ESCALATION target, not the default owner. Pick them only when NO engineer has plausibly worked on this failure mode.)

SIMILAR PAST BUGS (filtered to {component}; assignees marked `[MANAGER]` were managers acting as escalation owners — do NOT treat them as engineer picks):
{similar_bugs}

Selection rule (apply in order):
1. Prefer engineers (non-managers) who appear as assignees in the similar-bugs list — they've fixed similar bugs before.
2. If no such engineer stands out, fall back to the team roster for someone whose area of ownership matches the failure mode.
3. If NO engineer on the roster or in the similar-bug assignees has plausibly worked on this failure mode, return `null` — the system will escalate to the team manager automatically. Do NOT pick a `[MANAGER]` name yourself; managers are only assigned via the automated escalation path.

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "suggested_owner": "Full Name of an engineer (never a [MANAGER])" or null,
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
    """Format the similar-bugs table for the prompt. Assignees who are
    managers get a `[MANAGER]` marker so Claude doesn't treat them as
    default owners."""
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


def _pick_ic_via_frequency(
    same_component_bugs: list,
    ic_valid_names:      set,
) -> tuple:
    """Return (owner, reason) for the most-frequent IC assignee among
    the component-matching similar bugs, or (None, None) if none of the
    similar-bug assignees are eligible ICs.

    Managers are already excluded via `ic_valid_names` — the caller
    computes that set from the manager-free roster plus non-manager
    similar-bug assignees.
    """
    counts: dict[str, int] = Counter()
    for s in same_component_bugs:
        if s.assignee and s.assignee in ic_valid_names:
            counts[s.assignee] += 1

    if not counts:
        return None, None

    owner, n = counts.most_common(1)[0]
    total = sum(counts.values())
    return owner, (
        f"Most frequent engineer among the {len(same_component_bugs)} "
        f"similar bugs on this component ({n}/{total} matches; managers excluded)."
    )


def _escalate_to_manager(component: str) -> OwnerResult:
    """Final fallback per the routing rule: when no engineer on the team
    has similar-bug history for this failure mode, assign the bug to the
    team's manager. If the component has no manager mapped (e.g. DS),
    return `no-candidates` and let the human triage it."""
    manager = TEAM_MANAGERS.get(component)
    if manager:
        return OwnerResult(
            suggested_owner = manager,
            owner_reason    = (
                f"No engineer on the {component} team has been assigned a similar bug — "
                f"escalating to team manager ({manager})."
            ),
            method = "manager-escalation",
        )
    return OwnerResult(
        suggested_owner = None,
        owner_reason    = (
            f"No engineer with similar-bug history on {component} and no team "
            f"manager mapped — manual triage required."
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
    Suggest an owner for a new bug on the routed component.

    Selection rule (applied in order):
      1. Ask Claude to pick from engineers who've been on similar bugs.
      2. If Claude fails or its pick is invalid (null / manager /
         hallucinated), fall back to frequency-count of engineer
         assignees on the component-matching similar bugs.
      3. If NO engineer has similar-bug history on this component,
         escalate to the team manager (see TEAM_MANAGERS in team_config).

    The `team_roster` passed in is expected to be manager-free (the
    classifier's build_index step filters MANAGER_NAMES out during
    roster derivation). Managers still appear as assignees on similar
    bugs — we mark them in the prompt so Claude doesn't pick them, and
    exclude them from the frequency-fallback pool as belt-and-suspenders.
    """
    # 1. Filter similar bugs to those on the routed component.
    same_component = [s for s in similar_bugs if (s.component or "") == component]

    # 2. Pull the (manager-free) roster for this component.
    roster_entries = team_roster.get(component, []) or []
    roster_names   = {m["name"] for m in roster_entries}

    # 3. Engineer candidate pool: roster + non-manager similar-bug assignees.
    ic_valid = roster_names | {
        s.assignee for s in same_component
        if s.assignee and s.assignee not in MANAGER_NAMES
    }

    # 4. Nothing at all → straight to manager escalation.
    if not ic_valid and not same_component:
        return _escalate_to_manager(component)

    # 5. Try Claude.
    prompt = PROMPT_TEMPLATE.format(
        title        = title,
        description  = description[:1500],
        component    = component,
        roster       = _format_roster(roster_entries),
        manager      = TEAM_MANAGERS.get(component, "(none mapped)"),
        similar_bugs = _format_similar(same_component),
    )
    try:
        response = call_claude(prompt, expect_json=True, timeout=60)
    except Exception:
        response = None

    if isinstance(response, dict):
        owner     = response.get("suggested_owner")
        reasoning = (response.get("reasoning") or "").strip()
        if owner and owner in ic_valid and owner not in MANAGER_NAMES:
            return OwnerResult(
                suggested_owner = owner,
                owner_reason    = reasoning or "Suggested by Claude based on similar-bug history.",
                method          = "claude",
            )
        # Otherwise (null, manager pick, hallucinated name) → fall through.

    # 6. Frequency fallback among engineers.
    owner, reason = _pick_ic_via_frequency(same_component, ic_valid)
    if owner:
        return OwnerResult(
            suggested_owner = owner,
            owner_reason    = reason,
            method          = "frequency-fallback",
        )

    # 7. Nobody has similar-bug history → escalate to team manager.
    return _escalate_to_manager(component)
