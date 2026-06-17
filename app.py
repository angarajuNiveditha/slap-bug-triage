"""
app.py — Streamlit front-end for the SLAP Bug Triage prototype.

Paste a bug report, optionally attach screenshots, pick a pipeline, and the
agent drafts a Jira ticket. No tickets are filed automatically.

Pipelines:
  • Multi-agent (Astral)   — Claude Code headless, sub-agents for media,
    parser, embeddings, dedup, triage. Accepts image attachments.
  • Rule-based             — fast, deterministic, text-only (no Claude).

Run:
    streamlit run app.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Pipeline imports ────────────────────────────────────────────────────────
from src.agent_ticket_builder import build_ticket
from src.jira_client          import JiraClient

# Rule-based pipeline (instant, text-only)
from src.agent_parser     import parse_bug_report as rb_parse
from src.agent_scorer     import score_severity   as rb_score
from src.tfidf_similarity import SimilarityEngine as RuleEngine

# Multi-agent pipeline (Claude Code headless, supports media)
from src.agents.host_agent      import HostAgent, detect_quality_issues
from src.agents.subagent_media  import IMAGE_EXTENSIONS, MediaResult

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")
DATA_DIR      = Path(__file__).parent / "data"


# ── Page setup ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SLAP Bug Triage",
    page_icon="🐞",
    layout="wide",
)

# Bump this counter (via the "Refile" button) to force-reset the input
# widgets when the user wants to refile after a quality warning.
if "input_version" not in st.session_state:
    st.session_state.input_version = 0


# ── Cached resources ────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Connecting to Jira and indexing 300 historical bugs (one-time per session)...")
def get_engines() -> tuple[RuleEngine, HostAgent, int]:
    """Build both pipelines' indexes once and reuse across triage calls."""
    jira   = JiraClient()
    issues = jira.fetch_recent_bugs(limit=300)

    rb = RuleEngine()
    rb.build_index(issues)

    host = HostAgent()
    host.build_index(issues)

    return rb, host, len(issues)


# ── Helpers ─────────────────────────────────────────────────────────────────

def jira_link(key: Optional[str]) -> str:
    if not key:
        return "—"
    return f"[{key}]({JIRA_BASE_URL}/browse/{key})"


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
    pipeline       = triage.get("pipeline", "—")

    dup_cell = (
        f"[{dup_key}]({JIRA_BASE_URL}/browse/{dup_key}) (confidence {dup_conf:.2f})"
        if dup_key
        else f"_(no duplicate)_ — top-match similarity {dup_conf:.2f}"
    )

    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| **Pipeline** | `{pipeline}` |",
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

    qissues = triage.get("quality_issues") or []
    if qissues:
        lines += ["### ⚠ Quality Issues — Refile Recommended", ""]
        for q in qissues:
            kind = q.get("type", "issue")
            lines += [
                f"**{kind}**",
                "",
                f"{q.get('message','')}",
                "",
                f"_Suggested action:_ {q.get('suggested_action','')}",
                "",
            ]

    findings = triage.get("media_findings") or []
    if findings:
        lines += ["### Media Findings (from attached images)", ""]
        for f in findings:
            screen = f.get("screen", "?")
            state  = f.get("state", "?")
            sig    = f.get("triage_signals", {}) or {}
            lines += [
                f"**{Path(f.get('image_path','')).name}** — screen: *{screen}*, state: *{state}*",
                "",
                f"> {f.get('one_line_summary','')}",
                "",
            ]
            if f.get("ui_anomalies"):
                lines.append("Anomalies:")
                for a in f["ui_anomalies"]:
                    lines.append(f"- {a}")
                lines.append("")
            if sig.get("contradicts_email_claim"):
                lines += [f"⚠ Contradicts email: {sig['contradicts_email_claim']}", ""]

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


def save_uploads_to_tmp(uploaded_files) -> list:
    """
    Streamlit gives us in-memory UploadedFile objects. The media sub-agent
    needs file paths on disk so Claude can Read them. Stage to a tempdir.
    Returns the list of saved absolute paths.
    """
    if not uploaded_files:
        return []
    tmp_dir = Path(tempfile.mkdtemp(prefix="slap_attachments_"))
    saved = []
    for f in uploaded_files:
        ext = Path(f.name).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        path = tmp_dir / f.name
        path.write_bytes(f.getvalue())
        saved.append(str(path))
    return saved


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "SLAP Bug Triage takes a bug-report email (plus optional screenshots) "
        "and drafts a Jira ticket — with priority, team routing, duplicate "
        "detection, and owner suggestion."
    )
    st.markdown("**No tickets are filed automatically.** A human reviews and files.")

    st.divider()
    st.markdown("### Pipelines")
    st.markdown(
        "- **Multi-agent (Astral)** — Claude Code headless. Sub-agents for "
        "media, parser, embeddings, dedup, triage. Reads images. ~90–150 s/bug.\n"
        "- **Rule-based** — regex + TF-IDF, instant, text-only. Fallback / simulation."
    )

    st.divider()
    st.markdown("### Sub-agents (multi-agent)")
    st.markdown(
        "1. **Media** — images → SLAP-aware findings (skipped if no attachments)\n"
        "2. **Parser** — email + media → structured BugReport\n"
        "3. **Embeddings** — top-5 similar bugs from 300 historical FLIPPI bugs\n"
        "4. **Dedup** — duplicate decision (≥ 0.80 confidence)\n"
        "5. **Triage** — priority P0/P1/P2/P3 + justification"
    )


# ── Header ──────────────────────────────────────────────────────────────────

st.title("🐞 SLAP Bug Triage")
st.caption("Paste the report. Attach screenshots if you have them. The agent drafts the ticket.")


# ── Input ───────────────────────────────────────────────────────────────────

st.subheader("1. Bug report")

samples       = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []
sample_names  = ["(paste your own)"] + [p.name for p in samples]

col_pick, col_pipeline = st.columns([2, 2])

with col_pick:
    pick = st.selectbox("Pre-fill from a sample", sample_names, index=0)
    default_text = ""
    if pick != "(paste your own)":
        default_text = (DATA_DIR / pick).read_text(encoding="utf-8")

with col_pipeline:
    pipeline_choice = st.radio(
        "Pipeline",
        ["Multi-agent (semantic, accepts images)", "Rule-based (instant, text-only)"],
        horizontal=False,
        index=0,
        help=(
            "Multi-agent reads images and reasons semantically (~90–150 s). "
            "Rule-based is instant but ignores attachments."
        ),
    )

raw_text = st.text_area(
    "Bug report email",
    value=default_text,
    height=280,
    placeholder="From: someone@flipkart.com\nSubject: [URGENT] ...\n\nDescribe the bug here...",
    key=f"input_{pick}_{st.session_state.input_version}",
)

uploaded_files = st.file_uploader(
    "Attach screenshots (optional — multi-agent only)",
    type=["png", "jpg", "jpeg", "webp", "gif"],
    accept_multiple_files=True,
    help="Images are sent to the media sub-agent, which identifies the SLAP screen and extracts visible bug evidence.",
    key=f"upload_{st.session_state.input_version}",
)

if uploaded_files:
    cols = st.columns(min(4, len(uploaded_files)))
    for i, f in enumerate(uploaded_files):
        with cols[i % len(cols)]:
            st.image(f.getvalue(), caption=f.name, use_container_width=True)

triage_btn = st.button(
    "Triage this bug",
    type="primary",
    disabled=not raw_text.strip(),
    use_container_width=True,
)

if uploaded_files and pipeline_choice.startswith("Rule-based"):
    st.info("Heads up: rule-based pipeline ignores image attachments. Switch to multi-agent to use them.")

st.divider()


# ── Pipeline run ────────────────────────────────────────────────────────────

if triage_btn:
    use_multi_agent = pipeline_choice.startswith("Multi-agent")

    try:
        rb_engine, host, n_indexed = get_engines()
    except Exception as e:
        st.error(f"Could not connect to Jira: {type(e).__name__}: {e}")
        st.stop()

    pipeline_label = "multi-agent" if use_multi_agent else "rule-based"
    with st.status(f"Running {pipeline_label} pipeline...", expanded=True) as status:
        try:
            if use_multi_agent:
                image_paths = save_uploads_to_tmp(uploaded_files) if uploaded_files else []

                if image_paths:
                    st.write(f"**Step 1** — Media sub-agent processing {len(image_paths)} image(s)...")
                else:
                    st.write("**Step 1** — No attachments; skipping media sub-agent.")

                st.write("**Step 2** — Parser sub-agent (email → BugReport)...")
                st.write(f"**Step 3** — Embeddings sub-agent ranking similar bugs across {n_indexed} historical bugs...")
                st.write("**Step 4** — Dedup sub-agent deciding duplicate...")
                st.write("**Step 5** — Triage sub-agent assigning priority...")
                st.write("**Step 6** — Building Jira ticket draft...")

                result   = host.triage(raw_text, image_paths=image_paths)
                bug      = result.bug
                sim      = result.similarity
                severity = result.severity
                draft    = result.draft
                media    = result.media
            else:
                st.write("**Step 1** — Parsing (regex)...")
                bug = rb_parse(raw_text)
                st.write(f"**Step 2** — TF-IDF similarity over {n_indexed} historical bugs...")
                query = f"{bug.title}\n{bug.description}\n{bug.actual_result}"
                sim   = rb_engine.find_similar(query)
                st.write("**Step 3** — Multi-layer keyword/template scorer...")
                severity = rb_score(bug, sim.top_matches)
                st.write("**Step 4** — Building Jira ticket draft...")
                draft = build_ticket(bug, severity, sim)
                media = None
                # Rule-based path doesn't run the host agent — add the
                # quality check inline so the same UI warnings show up.
                q = detect_quality_issues(bug, MediaResult(findings=[], combined_summary=""))
                if q:
                    draft.triage_notes["quality_issues"] = q

            status.update(label="Triage complete", state="complete", expanded=False)
        except Exception as e:
            status.update(label="Pipeline failed", state="error")
            st.exception(e)
            st.stop()

    # ── Headline ────────────────────────────────────────────────────────────

    st.subheader("2. Result")

    # ── Quality warnings (vague report / image-vs-text contradiction) ──────
    # If we flag a quality issue we STOP rendering — no tentative draft is
    # shown below, because the whole point of the refile prompt is that the
    # input wasn't good enough to triage on.
    quality_issues = draft.triage_notes.get("quality_issues") or []
    if quality_issues:
        st.error(
            "⚠ **This bug cannot be triaged confidently.** "
            "The report is missing critical details, or the attached image "
            "contradicts the text. Please refile with the corrections below."
        )

        for q in quality_issues:
            kind = q.get("type", "issue")
            label = {
                "vague_report":            "📝 Vague report",
                "media_contradicts_text":  "🖼 Image ⇄ email mismatch",
            }.get(kind, kind)

            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.markdown(q.get("message", ""))
                action = q.get("suggested_action")
                if action:
                    st.markdown(f"_What to do:_ {action}")

        if st.button("📝 Refile this bug", type="primary", key="refile_btn"):
            st.session_state.input_version += 1
            st.rerun()

        st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Priority", severity.priority, severity.severity)
    m2.metric("Team",     draft.triage_notes.get("team", "—"))
    m3.metric("Owner",    sim.suggested_owner or "—")
    m4.metric("Duplicate of", sim.duplicate_of or "—",
              f"{sim.duplicate_confidence:.0%} confidence" if sim.duplicate_of else None)

    if sim.duplicate_of:
        st.markdown(f"🔗 Open duplicate: {jira_link(sim.duplicate_of)}")

    # ── Tabs ────────────────────────────────────────────────────────────────

    tab_names = ["Summary", "Triage notes", "Raw JSON", "Jira ADF preview"]
    if use_multi_agent and media and media.findings:
        tab_names.insert(1, "Media findings")
    tabs = st.tabs(tab_names)

    idx = 0
    with tabs[idx]:
        st.markdown(f"**Justification.** {severity.justification}")
        st.markdown(f"**Scoring path.** `{severity.scoring_path}`")
        if sim.suggested_owner:
            st.markdown(f"**Owner reason.** {sim.owner_reason}")
        st.markdown(f"**Pipeline.** `{draft.triage_notes.get('pipeline', pipeline_label)}`")

        if media and media.combined_summary:
            st.markdown(f"**Media summary.** {media.combined_summary}")

        if sim.top_matches:
            st.markdown("**Top similar bugs:**")
            for m in sim.top_matches:
                tag = "  🚩 _duplicate candidate_" if m.is_duplicate_candidate else ""
                st.markdown(
                    f"- {jira_link(m.key)} ({m.priority}, sim={m.similarity:.2f}) — "
                    f"{m.summary}{tag}"
                )
    idx += 1

    if use_multi_agent and media and media.findings:
        with tabs[idx]:
            st.caption("What the media sub-agent saw in each attached image.")
            for f in media.findings:
                st.markdown(f"#### {Path(f.image_path).name}")
                left, right = st.columns([1, 2])
                with left:
                    if Path(f.image_path).exists():
                        st.image(f.image_path, use_container_width=True)
                with right:
                    sig = f.triage_signals or {}
                    st.markdown(f"**Screen:** {f.screen}")
                    st.markdown(f"**State:** {f.state}")
                    if sig:
                        st.markdown(f"**Likely component:** {sig.get('likely_component', '?')}")
                        st.markdown(f"**Severity hint:** {sig.get('severity_hint', '?')}")
                        if sig.get("contradicts_email_claim"):
                            st.warning(f"Contradicts email: {sig['contradicts_email_claim']}")
                    st.markdown(f"**One-line summary:**  \n{f.one_line_summary}")
                    if f.ui_anomalies:
                        st.markdown("**Anomalies:**")
                        for a in f.ui_anomalies:
                            st.markdown(f"- {a}")
                    if f.error_indicators:
                        st.markdown("**Error indicators:**")
                        for e in f.error_indicators:
                            st.markdown(f"- {e}")
                    if f.visible_text:
                        with st.expander("Visible text extracted"):
                            for t in f.visible_text:
                                st.markdown(f"- {t}")
                st.divider()
        idx += 1

    with tabs[idx]:
        st.markdown(render_triage_md(draft.triage_notes))
    idx += 1

    with tabs[idx]:
        triage_json = json.dumps(draft.triage_notes, indent=2, ensure_ascii=False)
        st.code(triage_json, language="json")
        st.download_button(
            "⬇ Download triage_notes.json",
            data=triage_json,
            file_name="triage_notes.json",
            mime="application/json",
        )
    idx += 1

    with tabs[idx]:
        st.caption(
            "ADF document the ticket builder produced. Paste-ready into Jira's "
            "create-issue API. (Auto-create is OFF by design.)"
        )
        st.json(draft.jira_payload, expanded=False)
        full_json = json.dumps(
            {
                "pipeline":          draft.triage_notes.get("pipeline", pipeline_label),
                "jira_ticket_draft": draft.jira_payload,
                "triage_notes":      draft.triage_notes,
            },
            indent=2, ensure_ascii=False,
        )
        st.download_button(
            "⬇ Download full ticket draft JSON",
            data=full_json,
            file_name=f"ticket_draft_{pipeline_label.replace(' ', '_')}.json",
            mime="application/json",
        )
