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

import html
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
    page_icon="🪲",
    layout="wide",
)

# ── Theme: typography, colours, polish ─────────────────────────────────────
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

      /* Strip Streamlit chrome */
      [data-testid="stDeployButton"], .stDeployButton,
      [data-testid="stStatusWidget"]         { display: none !important; }
      header[data-testid="stHeader"]         { background: transparent; height: 0; }
      footer                                  { display: none !important; }
      #MainMenu                               { display: none !important; }

      /* Page background */
      [data-testid="stAppViewContainer"] {
          background: linear-gradient(180deg, #F8FAFC 0%, #FFFFFF 50%);
      }
      [data-testid="stMain"] .block-container {
          padding-top: 1.2rem;
          max-width: 1180px;
      }

      /* Typography */
      html, body, [class*="css"], .stMarkdown, .stTextArea, .stSelectbox, .stRadio {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
      }
      code, pre { font-family: 'JetBrains Mono', monospace !important; font-size: 12.5px !important; }

      /* ── Hero ─────────────────────────────────────────────────────── */
      .slap-hero {
          background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 50%, #DB2777 100%);
          color: white;
          padding: 26px 32px;
          border-radius: 18px;
          box-shadow: 0 20px 40px -12px rgba(79, 70, 229, 0.35);
          margin-bottom: 24px;
          display: flex;
          align-items: center;
          gap: 20px;
      }
      .slap-hero-icon {
          width: 60px; height: 60px;
          background: rgba(255,255,255,0.18);
          border-radius: 14px;
          display: flex; align-items: center; justify-content: center;
          backdrop-filter: blur(8px);
          flex-shrink: 0;
      }
      .slap-hero-icon svg { width: 36px; height: 36px; }
      .slap-hero-title { font-size: 26px; font-weight: 700; margin: 0; letter-spacing: -0.4px; }
      .slap-hero-sub   { margin-top: 4px; color: rgba(255,255,255,0.85); font-size: 13.5px; }

      /* ── Section headers ─────────────────────────────────────────── */
      .section-label {
          display: inline-flex; align-items: center; gap: 8px;
          font-size: 11px; font-weight: 600; letter-spacing: 1.2px;
          text-transform: uppercase;
          color: #6366F1;
          margin: 24px 0 8px 0;
      }
      .section-label::before {
          content: ""; width: 24px; height: 2px;
          background: linear-gradient(90deg, #4F46E5, #DB2777);
          border-radius: 2px;
      }

      /* ── Custom metric tiles ──────────────────────────────────────── */
      .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 8px 0 18px 0; }
      .mtile {
          background: white;
          border: 1px solid #E2E8F0;
          border-radius: 14px;
          padding: 16px 18px;
          transition: transform 0.15s, box-shadow 0.15s;
      }
      .mtile:hover { transform: translateY(-2px); box-shadow: 0 10px 24px -8px rgba(15,23,42,0.12); }
      .mtile-label { font-size: 10.5px; font-weight: 600; letter-spacing: 0.9px;
                     text-transform: uppercase; color: #64748B; margin-bottom: 8px; }
      .mtile-value { font-size: 22px; font-weight: 700; color: #0F172A; line-height: 1.15; }
      .mtile-sub   { font-size: 12px; color: #64748B; margin-top: 4px; }

      .mtile.prio-P0 { background: linear-gradient(135deg, #FEF2F2 0%, #FFFFFF 100%); border-color: #FCA5A5; }
      .mtile.prio-P0 .mtile-value { color: #B91C1C; }
      .mtile.prio-P1 { background: linear-gradient(135deg, #FFF7ED 0%, #FFFFFF 100%); border-color: #FDBA74; }
      .mtile.prio-P1 .mtile-value { color: #C2410C; }
      .mtile.prio-P2 { background: linear-gradient(135deg, #FFFBEB 0%, #FFFFFF 100%); border-color: #FCD34D; }
      .mtile.prio-P2 .mtile-value { color: #B45309; }
      .mtile.prio-P3 { background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 100%); border-color: #93C5FD; }
      .mtile.prio-P3 .mtile-value { color: #1D4ED8; }

      /* ── Buttons ─────────────────────────────────────────────────── */
      .stButton button[kind="primary"] {
          background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
          border: 0; border-radius: 10px; padding: 10px 18px;
          font-weight: 600; letter-spacing: 0.2px;
          box-shadow: 0 6px 14px -4px rgba(79,70,229,0.45);
          transition: transform 0.15s, box-shadow 0.15s;
      }
      .stButton button[kind="primary"]:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 10px 20px -6px rgba(79,70,229,0.55);
      }
      .stButton button[kind="primary"]:disabled {
          background: #CBD5E1; color: white; box-shadow: none; opacity: 0.6;
      }

      /* ── Text area + uploader polish ─────────────────────────────── */
      .stTextArea textarea {
          border-radius: 12px !important;
          border-color: #E2E8F0 !important;
          font-family: 'JetBrains Mono', monospace !important;
          font-size: 13px !important;
      }
      .stTextArea textarea:focus {
          border-color: #6366F1 !important;
          box-shadow: 0 0 0 3px rgba(99,102,241,0.12) !important;
      }
      [data-testid="stFileUploader"] section {
          border-radius: 12px;
          border-style: dashed !important;
          border-color: #CBD5E1 !important;
          background: #F8FAFC;
      }

      /* ── Tabs ────────────────────────────────────────────────────── */
      .stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #E2E8F0; }
      .stTabs [data-baseweb="tab"] {
          font-weight: 600; font-size: 13.5px;
          padding: 10px 16px; border-radius: 8px 8px 0 0;
      }
      .stTabs [aria-selected="true"] {
          color: #4F46E5 !important;
          background: #EEF2FF;
      }

      /* ── Quality issues card ─────────────────────────────────────── */
      .quality-banner {
          background: linear-gradient(135deg, #FEF2F2 0%, #FFF7ED 100%);
          border: 1px solid #FCA5A5;
          border-left: 4px solid #DC2626;
          border-radius: 12px;
          padding: 18px 22px;
          margin: 10px 0 18px 0;
      }
      .quality-banner h4 { margin: 0 0 4px 0; color: #B91C1C; font-size: 16px; font-weight: 700; }
      .quality-banner p  { margin: 0; color: #7F1D1D; font-size: 13.5px; }

      .quality-card {
          background: white;
          border: 1px solid #FECACA;
          border-radius: 10px;
          padding: 14px 18px;
          margin-bottom: 10px;
      }
      .quality-card-kind {
          display: inline-block;
          background: #FEE2E2; color: #B91C1C;
          padding: 3px 10px; border-radius: 999px;
          font-size: 11px; font-weight: 600; letter-spacing: 0.5px;
          text-transform: uppercase;
          margin-bottom: 8px;
      }
      .quality-card-msg    { color: #0F172A; font-size: 14px; line-height: 1.5; margin: 4px 0; }
      .quality-card-action { color: #475569; font-size: 13px; line-height: 1.5; margin-top: 6px;
                             padding-top: 8px; border-top: 1px dashed #E2E8F0; }

      /* ── Misc ────────────────────────────────────────────────────── */
      .stCaption, .caption { color: #64748B !important; }
      hr { border-color: #E2E8F0 !important; margin: 12px 0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
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


# ── Hero ───────────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="slap-hero">
      <div class="slap-hero-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
          <ellipse cx="12" cy="13.5" rx="5" ry="6.5" fill="white" stroke="white"/>
          <line x1="12" y1="7"  x2="12" y2="20" stroke="#7C3AED" stroke-width="1.2"/>
          <circle cx="9.7" cy="11" r="0.9" fill="#7C3AED" stroke="none"/>
          <circle cx="14.3" cy="11" r="0.9" fill="#7C3AED" stroke="none"/>
          <path d="M11 6 L9 3.5"  />
          <path d="M13 6 L15 3.5" />
          <path d="M7 12 L4 10"   />
          <path d="M7 15 L4 17"   />
          <path d="M17 12 L20 10" />
          <path d="M17 15 L20 17" />
          <path d="M10 20 L9 23"  />
          <path d="M14 20 L15 23" />
        </svg>
      </div>
      <div>
        <div class="slap-hero-title">SLAP Bug Triage</div>
        <div class="slap-hero-sub">Paste the report. Attach screenshots. The agent drafts a Jira ticket — no auto-filing.</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Input ───────────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Step 1 · Bug report</div>', unsafe_allow_html=True)

samples       = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []
sample_names  = ["(paste your own)"] + [p.name for p in samples]

col_pick, col_pipeline = st.columns([2, 2])

with col_pick:
    pick = st.selectbox(
        "Pre-fill from a sample",
        sample_names,
        index=0,
        key=f"pick_{st.session_state.input_version}",
    )
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

    st.markdown('<div class="section-label">Step 2 · Result</div>', unsafe_allow_html=True)

    # ── Quality warnings (vague report / image-vs-text contradiction) ──────
    # If we flag a quality issue we STOP rendering — no tentative draft is
    # shown below, because the whole point of the refile prompt is that the
    # input wasn't good enough to triage on.
    quality_issues = draft.triage_notes.get("quality_issues") or []
    if quality_issues:
        st.markdown(
            """
            <div class="quality-banner">
              <h4>⚠ This bug cannot be triaged confidently</h4>
              <p>The report is missing critical details, or the attached image contradicts the text.
              Please refile with the corrections below.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for q in quality_issues:
            kind = q.get("type", "issue")
            label = {
                "vague_report":            "Vague report",
                "media_contradicts_text":  "Image ⇄ email mismatch",
            }.get(kind, kind)

            msg    = html.escape(q.get("message", ""))
            action = html.escape(q.get("suggested_action", ""))
            st.markdown(
                f"""
                <div class="quality-card">
                  <span class="quality-card-kind">{label}</span>
                  <div class="quality-card-msg">{msg}</div>
                  {f'<div class="quality-card-action"><strong>What to do.</strong> {action}</div>' if action else ''}
                </div>
                """,
                unsafe_allow_html=True,
            )

        if st.button("Refile this bug", type="primary", key="refile_btn"):
            st.session_state.input_version += 1
            st.rerun()

        st.stop()

    # Priority-coloured tile grid
    prio = severity.priority if severity.priority in ("P0", "P1", "P2", "P3") else "P2"
    team_v   = draft.triage_notes.get("team", "—")
    owner_v  = sim.suggested_owner or "—"
    dup_v    = sim.duplicate_of or "—"
    dup_sub  = f"{sim.duplicate_confidence:.0%} confidence" if sim.duplicate_of else "no duplicate found"

    st.markdown(
        f"""
        <div class="metric-grid">
          <div class="mtile prio-{prio}">
            <div class="mtile-label">Priority</div>
            <div class="mtile-value">{prio}</div>
            <div class="mtile-sub">{html.escape(severity.severity)}</div>
          </div>
          <div class="mtile">
            <div class="mtile-label">Team</div>
            <div class="mtile-value">{html.escape(str(team_v))}</div>
            <div class="mtile-sub">{html.escape(draft.triage_notes.get('jira_component', '—'))}</div>
          </div>
          <div class="mtile">
            <div class="mtile-label">Owner</div>
            <div class="mtile-value">{html.escape(str(owner_v))}</div>
            <div class="mtile-sub">most-similar past bugs</div>
          </div>
          <div class="mtile">
            <div class="mtile-label">Duplicate of</div>
            <div class="mtile-value">{html.escape(str(dup_v))}</div>
            <div class="mtile-sub">{html.escape(dup_sub)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
