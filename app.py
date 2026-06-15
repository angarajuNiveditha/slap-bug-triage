"""
app.py — Streamlit frontend for the SLAP Bug Triage prototype.

Paste a bug report email, pick a pipeline (rule-based or Claude), and the
agent produces a Jira ticket draft. No tickets are filed automatically.

Run:
    streamlit run app.py

Opens at http://localhost:8501.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Pipeline imports ────────────────────────────────────────────────────────
from src.agent_ticket_builder import build_ticket
from src.jira_client          import JiraClient

# Rule-based pipeline (instant)
from src.agent_parser      import parse_bug_report as rb_parse
from src.agent_scorer      import score_severity   as rb_score
from src.tfidf_similarity  import SimilarityEngine as RuleEngine

# Claude pipeline (semantic, ~90s per call)
from src.claude_parser     import parse_bug_report as cl_parse
from src.claude_scorer     import score_severity   as cl_score
from src.claude_similarity import SimilarityEngine as ClaudeEngine

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")
DATA_DIR      = Path(__file__).parent / "data"


# ── Page setup ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SLAP Bug Triage",
    page_icon="🐞",
    layout="wide",
)


# ── Cached resources ────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Connecting to Jira and indexing 300 historical bugs (one-time per session)...")
def get_engines() -> tuple[RuleEngine, ClaudeEngine, int]:
    """Build both similarity engines once and reuse across all triage calls."""
    jira   = JiraClient()
    issues = jira.fetch_recent_bugs(limit=300)

    rb = RuleEngine()
    rb.build_index(issues)

    cl = ClaudeEngine()
    cl.build_index(issues)

    return rb, cl, len(issues)


# ── Helpers ─────────────────────────────────────────────────────────────────

def render_triage_md(triage: dict) -> str:
    """Render the triage_notes dict as a clickable-link Markdown document."""
    lines: list[str] = []

    team           = triage.get("team", "—")
    component      = triage.get("jira_component") or "_(none — needs manual routing)_"
    scoring_path   = (triage.get("priority_scoring_path") or "—").replace("|", "\\|")
    layer          = scoring_path.split(":")[0]
    owner          = triage.get("owner_suggestion") or "_(no suggestion)_"
    owner_reason   = triage.get("owner_reason") or ""
    dup_key        = triage.get("duplicate_of")
    dup_conf       = triage.get("duplicate_confidence", 0.0)
    justification  = triage.get("severity_justification", "")

    dup_cell = (
        f"[{dup_key}]({JIRA_BASE_URL}/browse/{dup_key}) (confidence {dup_conf:.2f})"
        if dup_key
        else f"_(no duplicate)_ — top-match similarity {dup_conf:.2f}"
    )

    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| **Team** | {team} |",
        f"| **Jira component** | {component} |",
        f"| **Scoring layer** | `{layer}` |",
        f"| **Scoring path** | `{scoring_path}` |",
        f"| **Duplicate of** | {dup_cell} |",
        f"| **Owner suggestion** | {owner} |",
        f"| **Owner reason** | {owner_reason} |",
        "",
    ]

    if justification:
        lines += ["### Severity Justification", "", f"> {justification}", ""]

    similar = triage.get("similar_bugs") or []
    if similar:
        lines += [
            "### Similar Past Bugs",
            "",
            "| Jira Key | Priority | Similarity | Assignee | Summary |",
            "|---|---|---|---|---|",
        ]
        for s in similar:
            key      = s.get("key", "")
            url      = s.get("url") or f"{JIRA_BASE_URL}/browse/{key}"
            priority = s.get("priority", "—")
            sim      = s.get("similarity", 0.0)
            assignee = s.get("assignee") or "_(unassigned)_"
            summary  = (s.get("summary") or "").replace("|", "\\|")
            lines.append(f"| [{key}]({url}) | {priority} | {sim:.3f} | {assignee} | {summary} |")
        lines.append("")

    note = triage.get("note")
    if note:
        lines += ["---", "", f"_{note}_", ""]

    return "\n".join(lines)


def jira_link(key: str | None) -> str:
    """Return a markdown link for a Jira key, or '—'."""
    if not key:
        return "—"
    return f"[{key}]({JIRA_BASE_URL}/browse/{key})"


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "SLAP Bug Triage is a prototype that takes a raw bug report email "
        "and drafts a Jira ticket — with priority, team routing, duplicate "
        "detection, and owner suggestion."
    )
    st.markdown(
        "**No tickets are filed automatically.** A human reviews the draft "
        "and files the ticket themselves."
    )
    st.divider()
    st.markdown("### Pipelines")
    st.markdown(
        "- **Rule-based** uses regex parsing + TF-IDF similarity + keyword "
        "scoring. Instant, fully deterministic.\n"
        "- **Claude** uses Claude Code (no API key) for parsing, semantic "
        "similarity over all 300 historical bugs, and severity reasoning. "
        "Slower (~90s per bug) but understands paraphrases and intent."
    )


# ── Header ──────────────────────────────────────────────────────────────────

st.title("🐞 SLAP Bug Triage")
st.caption("Paste a bug report email. The agent drafts a Jira ticket. You review and file it.")


# ── Input ───────────────────────────────────────────────────────────────────

st.subheader("1. Bug report")

samples = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []
sample_names = ["(paste your own)"] + [p.name for p in samples]

col_pick, col_pipeline = st.columns([2, 2])

with col_pick:
    pick = st.selectbox("Pre-fill from a sample", sample_names, index=0)
    default_text = ""
    if pick != "(paste your own)":
        default_text = (DATA_DIR / pick).read_text(encoding="utf-8")

with col_pipeline:
    pipeline_choice = st.radio(
        "Pipeline",
        ["Rule-based (instant)", "Claude (semantic, ~90s)"],
        horizontal=False,
        index=0,
        help="Rule-based is fast and deterministic. Claude is slower but reads semantically.",
    )

raw_text = st.text_area(
    "Bug report email",
    value=default_text,
    height=320,
    placeholder="From: someone@flipkart.com\nSubject: [URGENT] ...\n\nDescribe the bug here...",
    key=f"input_{pick}",  # reset textarea when sample changes
)

triage_btn = st.button(
    "Triage this bug",
    type="primary",
    disabled=not raw_text.strip(),
    use_container_width=True,
)

st.divider()


# ── Pipeline run ────────────────────────────────────────────────────────────

if triage_btn:
    use_claude = pipeline_choice.startswith("Claude")

    try:
        rb_engine, cl_engine, n_indexed = get_engines()
    except Exception as e:
        st.error(f"Could not connect to Jira: {type(e).__name__}: {e}")
        st.stop()

    with st.status(f"Running {'Claude' if use_claude else 'rule-based'} pipeline...", expanded=True) as status:
        try:
            st.write("**Step 1** — Parsing bug report...")
            bug = (cl_parse if use_claude else rb_parse)(raw_text)
            st.write(f"  → Title: `{bug.title}`")
            st.write(f"  → Platform: {bug.platform}  |  Version: {bug.app_version or '?'}  |  Repro: {bug.reproducibility}")

            st.write(f"**Step 2** — Finding similar bugs across {n_indexed} historical FLIPPI bugs...")
            if use_claude:
                sim = cl_engine.find_similar(bug)
            else:
                query = f"{bug.title}\n{bug.description}\n{bug.actual_result}"
                sim   = rb_engine.find_similar(query)
            st.write(f"  → {len(sim.top_matches)} match(es) returned")

            st.write("**Step 3** — Scoring severity...")
            severity = (cl_score if use_claude else rb_score)(bug, sim.top_matches)
            st.write(f"  → Priority: **{severity.priority}** ({severity.severity})")

            st.write("**Step 4** — Building Jira ticket draft...")
            draft = build_ticket(bug, severity, sim)

            status.update(label="Triage complete", state="complete", expanded=False)
        except Exception as e:
            status.update(label="Pipeline failed", state="error")
            st.exception(e)
            st.stop()

    # ── Headline ────────────────────────────────────────────────────────────

    st.subheader("2. Result")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Priority", severity.priority, severity.severity)
    m2.metric("Team",     draft.triage_notes.get("team", "—"))
    m3.metric("Owner",    sim.suggested_owner or "—")
    m4.metric("Duplicate of", sim.duplicate_of or "—",
              f"{sim.duplicate_confidence:.0%} confidence" if sim.duplicate_of else None)

    # Clickable Jira link for the duplicate (metric tiles don't render links)
    if sim.duplicate_of:
        st.markdown(f"🔗 Open duplicate: {jira_link(sim.duplicate_of)}", unsafe_allow_html=False)

    # ── Tabs ────────────────────────────────────────────────────────────────

    t_summary, t_notes, t_json, t_adf = st.tabs(
        ["Summary", "Triage notes", "Raw JSON", "Jira ADF preview"]
    )

    with t_summary:
        st.markdown(f"**Justification.** {severity.justification}")
        st.markdown(f"**Scoring path.** `{severity.scoring_path}`")
        if sim.suggested_owner:
            st.markdown(f"**Owner reason.** {sim.owner_reason}")
        st.markdown(f"**Pipeline.** `{'claude-code-headless' if use_claude else 'agent (rule-based)'}`")

        if sim.top_matches:
            st.markdown("**Top similar bugs:**")
            for m in sim.top_matches:
                tag = "  🚩 _duplicate candidate_" if m.is_duplicate_candidate else ""
                st.markdown(
                    f"- {jira_link(m.key)} ({m.priority}, sim={m.similarity:.2f}) — "
                    f"{m.summary}{tag}"
                )

    with t_notes:
        st.markdown(render_triage_md(draft.triage_notes))

    with t_json:
        triage_json = json.dumps(draft.triage_notes, indent=2, ensure_ascii=False)
        st.code(triage_json, language="json")
        st.download_button(
            "⬇ Download triage_notes.json",
            data=triage_json,
            file_name="triage_notes.json",
            mime="application/json",
        )

    with t_adf:
        st.caption("This is the Jira-flavored ADF document the ticket builder produced. "
                   "Paste-ready into Jira's create-issue API.")
        st.json(draft.jira_payload, expanded=False)
        full_json = json.dumps(
            {"pipeline": "claude-code-headless" if use_claude else "agent (rule-based)",
             "jira_ticket_draft": draft.jira_payload,
             "triage_notes": draft.triage_notes},
            indent=2, ensure_ascii=False,
        )
        st.download_button(
            "⬇ Download full ticket draft JSON",
            data=full_json,
            file_name=f"ticket_draft_{'claude' if use_claude else 'rule_based'}.json",
            mime="application/json",
        )
