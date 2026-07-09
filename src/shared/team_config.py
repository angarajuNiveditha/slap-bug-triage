"""
team_config.py — shared team-routing constants.

Kept in a small standalone module so both the classifier (which derives
the team roster during index build) and the Streamlit UI (which labels
suggested owners in the dropdown) reference the same source of truth.
Avoids drift from duplicated in-line sets.
"""

# People who appear as historical assignees on Jira bugs but are NOT
# active engineers on the routing pool — they're the team's manager.
# Excluded from the derived team roster (see build_index in
# embedding_classifier.py) and labelled "Manager" in the Streamlit owner
# dropdown. Also used by subagent_owner as the escalation target when
# no engineer on the team has similar-bug history.
MANAGER_NAMES = {
    "Yatin Grover",
    "Veeramreddy ChakradharReddy",
}


# Which manager owns which component. Populated from the SLAP org chart
# (Yatin manages UI + Backend-Labs + immersive; Veeramreddy manages the
# Backend team, which reports separately from Yatin). DS has no named
# manager in the current chart, so it isn't mapped — the owner
# sub-agent falls through to "no candidate" for DS bugs with no
# similar-bug engineer, rather than picking an arbitrary manager.
#
# The keys MUST match the classifier's component labels exactly.
TEAM_MANAGERS = {
    "UI":           "Yatin Grover",
    "Backend-Labs": "Yatin Grover",
    "immersive":    "Yatin Grover",
    "Backend":      "Veeramreddy ChakradharReddy",
    # "DS":         intentionally unmapped — no manager in the org chart yet
}
