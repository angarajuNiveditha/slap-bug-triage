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
from src.agents.subagent_media  import (
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MEDIA_EXTENSIONS,
    MAX_VIDEO_DURATION_SECONDS, MediaResult,
)

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")
DATA_DIR      = Path(__file__).parent / "data"


# ── Page setup ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SLAP Bug Triage",
    page_icon="🪲",
    layout="wide",
)

# ── Theme: typography, colours, polish ─────────────────────────────────────
# Pulled toward SLAP's own aesthetic: clean white background, large
# headings, soft pink (#E11D74) accent that mimics the SLAP brand's
# magenta star, minimal borders, generous breathing room.
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

      /* Belt-and-suspenders Deploy hide (config.toml does the real work). */
      [data-testid="stDeployButton"], .stDeployButton,
      [data-testid="stAppDeployButton"], .stAppDeployButton,
      [class*="DeployButton"] { display: none !important; }

      /* Page background — clean white with a very subtle pink wash up top */
      [data-testid="stAppViewContainer"] {
          background:
              radial-gradient(1200px 600px at 90% -100px, #FFF1F5 0%, transparent 60%),
              radial-gradient(800px 400px at -10% 200px, #FEF5F9 0%, transparent 55%),
              #FFFFFF;
      }
      [data-testid="stMain"] .block-container {
          padding: 1.2rem 2rem 3rem 2rem;
          max-width: 1480px;
      }

      /* Typography */
      html, body, [class*="css"], .stMarkdown, .stTextArea, .stSelectbox, .stRadio {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
          color: #1A1A1A;
      }
      code, pre { font-family: 'JetBrains Mono', monospace !important; font-size: 12.5px !important; }

      /* ── Hero (no dark box; clean, SLAP-style) ─────────────────────── */
      .slap-hero {
          display: flex; align-items: flex-end; justify-content: space-between;
          padding: 8px 4px 24px 4px;
          border-bottom: 1px solid #F0EFEB;
          margin-bottom: 28px;
      }
      .slap-hero-text { display: flex; flex-direction: column; gap: 4px; }
      .slap-hero-title {
          font-size: 32px; font-weight: 700; letter-spacing: -0.6px;
          color: #18181B; line-height: 1.15; margin: 0;
          display: flex; align-items: center; gap: 22px;
      }
      .slap-hero-bug {
          display: inline-flex; align-items: center; justify-content: center;
          width: 44px; height: 44px; border-radius: 12px;
          background: linear-gradient(135deg, #FFE4EC 0%, #FCE7F3 100%);
          border: 1px solid #FBCFE0;
          box-shadow: 0 6px 18px -8px rgba(225,29,116,0.30);
      }
      .slap-hero-bug svg { width: 26px; height: 26px; }
      .slap-hero-sub {
          color: #78716C; font-size: 14px; line-height: 1.45;
          max-width: 640px;
      }

      /* ── Pipeline stepper (vertical, left rail) ───────────────────── */
      .pipeline-rail {
          display: flex; flex-direction: column; align-items: flex-start;
          padding: 18px 18px 12px 18px;
          position: sticky; top: 1.2rem;
          background: linear-gradient(180deg, #FFF5F8 0%, #FFFFFF 100%);
          border: 1px solid #FCE7F0;
          border-radius: 18px;
          box-shadow: 0 12px 30px -18px rgba(225,29,116,0.16);
      }
      .pipeline-rail-title {
          font-size: 10.5px; font-weight: 700; letter-spacing: 1.4px;
          text-transform: uppercase; color: #BE185D; margin: 0 0 16px 4px;
      }
      .pipe-vnode {
          display: flex; align-items: flex-start; gap: 12px;
          position: relative;
          padding: 4px 0;
          width: 100%;
      }
      .pipe-vnode-icon {
          width: 32px; height: 32px; border-radius: 9px;
          flex-shrink: 0;
          display: flex; align-items: center; justify-content: center;
          font-size: 13px; font-weight: 700;
          background: #FFF1F5; color: #E11D74;
          border: 1px solid #FBCFE0;
          z-index: 2;
      }
      .pipe-vnode-icon.endpoint {
          background: #18181B; color: #FCE7F0; border-color: #18181B;
      }
      .pipe-vnode-icon.endpoint.output { background: #E11D74; color: white; border-color: #E11D74; }
      .pipe-vnode-text { flex: 1; padding-top: 4px; padding-bottom: 18px; }
      .pipe-vnode-name { font-size: 13px; font-weight: 600; color: #18181B; line-height: 1.2; }
      .pipe-vnode-desc { font-size: 11.5px; color: #78716C; line-height: 1.4; margin-top: 3px; }
      /* Vertical connecting line — drawn from below the icon to the next node */
      .pipe-vnode:not(:last-child)::before {
          content: ""; position: absolute;
          left: 15px; top: 36px; bottom: -4px;
          width: 2px; background: #F0EFEB;
          z-index: 1;
      }

      /* ── Section labels (subtler, no boxes) ───────────────────────── */
      .section-label {
          font-size: 15px; font-weight: 700; letter-spacing: 1.4px;
          text-transform: uppercase; color: #BE185D;
          margin: 14px 0 18px 0;
          display: flex; align-items: center; gap: 12px;
      }
      .section-label::before {
          content: "";
          width: 36px; height: 4px; border-radius: 3px;
          background: linear-gradient(90deg, #E11D74 0%, #F9A8D4 100%);
      }

      /* ── Custom metric tiles ──────────────────────────────────────── */
      .metric-grid {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
          margin: 6px 0 22px 0;
          padding: 16px 18px;
          border-radius: 16px;
          background: linear-gradient(135deg, #FFF5F8 0%, #FFFFFF 60%);
          border: 1px solid #FBE0EC;
          box-shadow: 0 12px 30px -18px rgba(225,29,116,0.18);
      }
      .mtile {
          padding: 12px 6px;
          border-bottom: 2px solid #FBE0EC;
          transition: border-color 0.15s;
      }
      .mtile:hover { border-bottom-color: #E11D74; }
      .mtile-label { font-size: 10.5px; font-weight: 700; letter-spacing: 1.1px;
                     text-transform: uppercase; color: #A8A29E; margin-bottom: 8px; }
      .mtile-value { font-size: 24px; font-weight: 700; color: #18181B; line-height: 1.1; letter-spacing: -0.3px; }
      .mtile-sub   { font-size: 11.5px; color: #78716C; margin-top: 4px; }

      .mtile.prio-P0 .mtile-value { color: #B91C1C; }
      .mtile.prio-P0 { border-bottom-color: #FCA5A5; }
      .mtile.prio-P1 .mtile-value { color: #C2410C; }
      .mtile.prio-P1 { border-bottom-color: #FDBA74; }
      .mtile.prio-P2 .mtile-value { color: #B45309; }
      .mtile.prio-P2 { border-bottom-color: #FCD34D; }
      .mtile.prio-P3 .mtile-value { color: #1D4ED8; }
      .mtile.prio-P3 { border-bottom-color: #93C5FD; }

      /* ── Buttons ─────────────────────────────────────────────────── */
      /* Streamlit 1.58 wraps primary buttons in several DOM shapes
         depending on context (`kind="primary"`, data-testid variants,
         emotion class names). Covering all of them so the pink hits. */
      .stButton button[kind="primary"],
      .stButton button[data-testid="stBaseButton-primary"],
      [data-testid="stButton"] button[kind="primary"],
      button[kind="primary"] {
          background: linear-gradient(135deg, #E11D74 0%, #BE185D 100%) !important;
          background-color: #E11D74 !important;
          border: 0 !important;
          border-radius: 14px !important;
          padding: 14px 28px !important;
          font-weight: 600 !important;
          letter-spacing: 0.2px !important;
          color: #FFFFFF !important;
          font-size: 14px !important;
          box-shadow: 0 8px 24px -8px rgba(225,29,116,0.45) !important;
          transition: transform 0.12s, box-shadow 0.12s, filter 0.12s !important;
      }
      .stButton button[kind="primary"]:hover:not(:disabled),
      .stButton button[data-testid="stBaseButton-primary"]:hover:not(:disabled),
      button[kind="primary"]:hover:not(:disabled) {
          filter: brightness(1.06) !important;
          transform: translateY(-1px) !important;
          box-shadow: 0 14px 30px -10px rgba(225,29,116,0.60) !important;
      }
      .stButton button[kind="primary"]:disabled,
      button[kind="primary"]:disabled {
          background: #F4D9E4 !important;
          background-color: #F4D9E4 !important;
          color: #B384A0 !important;
          box-shadow: none !important;
          opacity: 0.7 !important;
      }
      .stButton button[kind="secondary"] {
          background: white; border: 1px solid #E7E5E4; color: #18181B;
          border-radius: 10px; font-weight: 500;
      }

      /* ── Inputs (minimal — no heavy borders) ──────────────────────── */
      .stTextArea textarea {
          border-radius: 14px !important;
          border: 1px solid #FBE0EC !important;
          font-family: 'JetBrains Mono', monospace !important;
          font-size: 13px !important;
          background: #FFFFFF !important;
          box-shadow: 0 4px 18px -10px rgba(225,29,116,0.18) !important;
          padding: 14px 16px !important;
      }
      .stTextArea textarea:focus {
          border-color: #E11D74 !important;
          box-shadow: 0 0 0 4px rgba(225,29,116,0.12), 0 6px 22px -10px rgba(225,29,116,0.28) !important;
      }
      [data-testid="stFileUploader"] section {
          border-radius: 14px;
          border: 1.5px dashed #FBCFE0 !important;
          background: linear-gradient(135deg, #FFF1F5 0%, #FFFFFF 100%);
          padding: 8px 10px !important;
      }
      /* The default thumbnail in the uploader chip — keep small */
      [data-testid="stFileUploaderFile"] img { max-width: 64px !important; max-height: 64px !important; border-radius: 6px; }

      /* Radio (pipeline picker) — slightly larger label */
      .stRadio label { font-size: 13.5px !important; }

      /* Selectbox — softer borders */
      div[data-baseweb="select"] > div {
          border-radius: 12px !important;
          border-color: #F0EFEB !important;
      }

      /* ── Tabs (underline-on-active, no boxes) ─────────────────────── */
      .stTabs [data-baseweb="tab-list"] {
          gap: 4px; border-bottom: 1px solid #F0EFEB;
          background: transparent;
      }
      .stTabs [data-baseweb="tab"] {
          font-weight: 600; font-size: 13.5px;
          padding: 12px 20px; color: #78716C;
      }
      .stTabs [aria-selected="true"] {
          color: #E11D74 !important;
          border-bottom: 2px solid #E11D74 !important;
      }

      /* ── Quality issues ──────────────────────────────────────────── */
      .quality-banner {
          background: #FEF2F2;
          border: 1px solid #FCA5A5;
          border-left: 4px solid #DC2626;
          border-radius: 10px;
          padding: 15px 19px;
          margin: 6px 0 14px 0;
      }
      .quality-banner h4 { margin: 0 0 3px 0; color: #B91C1C; font-size: 15px; font-weight: 700; }
      .quality-banner p  { margin: 0; color: #7F1D1D; font-size: 13px; }

      .quality-card {
          background: white;
          border: 1px solid #FECACA;
          border-radius: 10px;
          padding: 13px 17px;
          margin-bottom: 9px;
      }
      .quality-card-kind {
          display: inline-block;
          background: #FEE2E2; color: #B91C1C;
          padding: 2px 9px; border-radius: 999px;
          font-size: 10.5px; font-weight: 700; letter-spacing: 0.6px;
          text-transform: uppercase;
          margin-bottom: 7px;
      }
      .quality-card-msg    { color: #18181B; font-size: 13.5px; line-height: 1.55; margin: 4px 0; }
      .quality-card-action { color: #57534E; font-size: 12.5px; line-height: 1.55; margin-top: 6px;
                             padding-top: 7px; border-top: 1px dashed #E7E5E4; }

      /* ── Attachment thumb strip — BIGGER previews ──────────────────── */
      .thumb-strip { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 10px; }
      .thumb {
          width: 180px; max-height: 320px;
          border-radius: 14px; border: 1px solid #F0EFEB;
          object-fit: contain; background: #FAFAF7;
          box-shadow: 0 4px 16px -8px rgba(0,0,0,0.08);
      }
      .thumb-cap {
          font-size: 11.5px; color: #78716C; text-align: center; margin-top: 6px;
          max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
      .thumb-wrap { display: flex; flex-direction: column; align-items: center; }

      /* ── Misc ────────────────────────────────────────────────────── */
      .stCaption, .caption { color: #78716C !important; }
      hr { border-color: #F0EFEB !important; margin: 18px 0 !important; }

      /* Quality issue cards — minimal borders, more breathing */
      .quality-banner {
          background: #FEF2F2;
          border-left: 3px solid #DC2626;
          border-radius: 0 14px 14px 0;
          padding: 16px 22px;
          margin: 6px 0 18px 0;
      }
      .quality-card { padding: 14px 18px; }
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
        if ext not in MEDIA_EXTENSIONS:
            continue
        path = tmp_dir / f.name
        path.write_bytes(f.getvalue())
        saved.append(str(path))
    return saved


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "SLAP Bug Triage takes a bug-report email (plus optional media) "
        "and drafts a Jira ticket — with priority, team routing, duplicate "
        "detection, and owner suggestion."
    )
    st.markdown("**No tickets are filed automatically.** A human reviews and files.")


# ── Hero (clean, SLAP-style) ───────────────────────────────────────────────

st.markdown(
    """
    <div class="slap-hero">
      <div class="slap-hero-text">
        <h1 class="slap-hero-title">
          <span class="slap-hero-bug" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
              <ellipse cx="12" cy="13.5" rx="5" ry="6.5" fill="#FCE7F3" stroke="#E11D74"/>
              <line x1="12" y1="7"  x2="12" y2="20" stroke="#E11D74" stroke-width="1.2"/>
              <circle cx="9.7"  cy="11" r="0.9" fill="#E11D74" stroke="none"/>
              <circle cx="14.3" cy="11" r="0.9" fill="#E11D74" stroke="none"/>
              <path d="M11 6 L9 3.5"  stroke="#E11D74"/>
              <path d="M13 6 L15 3.5" stroke="#E11D74"/>
              <path d="M7 12 L4 10"   stroke="#E11D74"/>
              <path d="M7 15 L4 17"   stroke="#E11D74"/>
              <path d="M17 12 L20 10" stroke="#E11D74"/>
              <path d="M17 15 L20 17" stroke="#E11D74"/>
              <path d="M10 20 L9 23"  stroke="#E11D74"/>
              <path d="M14 20 L15 23" stroke="#E11D74"/>
            </svg>
          </span>
          Slap Bug Triage
        </h1>
        <div class="slap-hero-sub">
          Drafts a Jira ticket from a bug-report email plus screenshots or videos.
          Read-only Jira — nothing is auto-filed; a human reviews every draft.
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Body: left rail (pipeline) + main column (input) ───────────────────────

col_rail, col_main = st.columns([1, 3], gap="large")

PIPELINE_RAIL_HTML = """
<div class="pipeline-rail">
  <div class="pipeline-rail-title">Multi-agent pipeline</div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon endpoint">in</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Input</div>
      <div class="pipe-vnode-desc">Email + screenshots / videos</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">M</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Media</div>
      <div class="pipe-vnode-desc">Reads attachments, identifies the SLAP screen, extracts visible bug evidence.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">P</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Parser</div>
      <div class="pipe-vnode-desc">Turns email + media findings into a structured BugReport.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">E</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Embeddings</div>
      <div class="pipe-vnode-desc">Ranks the top-5 most similar bugs from 300 historical FLIPPI tickets.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">D</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Dedup</div>
      <div class="pipe-vnode-desc">Duplicate decision over the top-5 (≥ 0.80 confidence).</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">T</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Triage</div>
      <div class="pipe-vnode-desc">Assigns priority P0-P3 with a plain-English justification.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon endpoint output">out</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Output</div>
      <div class="pipe-vnode-desc">Jira draft + triage_notes JSON.</div>
    </div>
  </div>
</div>
"""

with col_rail:
    st.markdown(PIPELINE_RAIL_HTML, unsafe_allow_html=True)

# Main column — the right-hand side of the rail. Everything from Step 1
# through the Triage button lives in here.
samples       = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []
sample_names  = ["(paste your own)"] + [p.name for p in samples]

with col_main:
    st.markdown('<div class="section-label">Step 1 · Bug report</div>', unsafe_allow_html=True)

    # Compact top-row controls: sample picker + pipeline radio
    ctrl_pick, ctrl_pipe = st.columns([1, 1])
    with ctrl_pick:
        pick = st.selectbox(
            "Pre-fill from a sample",
            sample_names,
            index=0,
            key=f"pick_{st.session_state.input_version}",
        )
        default_text = ""
        if pick != "(paste your own)":
            default_text = (DATA_DIR / pick).read_text(encoding="utf-8")

    with ctrl_pipe:
        pipeline_choice = st.radio(
            "Pipeline",
            ["Multi-agent (semantic, accepts images)", "Rule-based (instant, text-only)"],
            index=0,
            help=(
                "Multi-agent reads images and reasons semantically (~90–150 s). "
                "Rule-based is instant but ignores attachments."
            ),
        )

    # Textarea — full width of col_main
    raw_text = st.text_area(
        "Bug report email",
        value=default_text,
        height=300,
        placeholder="From: someone@flipkart.com\nSubject: [URGENT] ...\n\nDescribe the bug here...",
        key=f"input_{pick}_{st.session_state.input_version}",
        label_visibility="collapsed",
    )

    # Attachments — full width, with LARGER previews
    uploaded_files = st.file_uploader(
        "Attach screenshots or videos (multi-agent only)",
        type=["png", "jpg", "jpeg", "webp", "gif",
              "mp4", "mov", "webm", "avi", "mkv", "m4v"],
        accept_multiple_files=True,
        help=(
            "Images: media sub-agent identifies the SLAP screen and extracts "
            "visible evidence. Videos: keyframes are extracted with ffmpeg "
            f"(scene-detect, max 8 frames; ≤ {MAX_VIDEO_DURATION_SECONDS}s)."
        ),
        key=f"upload_{st.session_state.input_version}",
    )

    if uploaded_files:
        import base64 as _b64
        image_items = []
        video_items = []
        for f in uploaded_files:
            ext = Path(f.name).suffix.lower()
            safe_name = html.escape(f.name)
            if ext in IMAGE_EXTENSIONS:
                data_url = "data:image/png;base64," + _b64.b64encode(f.getvalue()).decode("ascii")
                image_items.append(
                    f'<div class="thumb-wrap">'
                    f'<img class="thumb" src="{data_url}" alt="{safe_name}"/>'
                    f'<div class="thumb-cap" title="{safe_name}">{safe_name}</div>'
                    f'</div>'
                )
            else:
                video_items.append(f)

        if image_items:
            st.markdown('<div class="thumb-strip">' + "".join(image_items) + "</div>",
                        unsafe_allow_html=True)
        for v in video_items:
            st.video(v.getvalue(), format=f"video/{Path(v.name).suffix.lstrip('.')}")
            st.caption(f"🎬 {v.name}")

    if uploaded_files and pipeline_choice.startswith("Rule-based"):
        st.caption("⚠ Rule-based ignores attachments. Switch to multi-agent to use them.")

    # Triage button — full width of col_main
    triage_btn = st.button(
        "Triage this bug",
        type="primary",
        disabled=not raw_text.strip(),
        use_container_width=True,
    )


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

                # Stream live step updates as each sub-agent actually
                # finishes, not all at once before host.triage() runs.
                step_icons = {
                    "start":   "▸",
                    "done":    "✓",
                    "skipped": "⊘",
                }
                def on_step(event: str, message: str) -> None:
                    _, suffix = event.split(":", 1) if ":" in event else (event, event)
                    icon = step_icons.get(suffix, "•")
                    st.markdown(f"{icon} {message}")

                result   = host.triage(raw_text, image_paths=image_paths, on_step=on_step)
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

        # Use a versioned key so a previous click doesn't latch True after
        # rerun, AND wipe every input widget's stored state explicitly —
        # bumping the version alone isn't enough; Streamlit's file uploader
        # in particular leaves ghost state on some builds.
        refile_key = f"refile_btn_v{st.session_state.input_version}"
        if st.button("Refile this bug", type="primary", key=refile_key):
            # NB: never delete `input_version` itself — that's the counter
            # we just bumped to force-new widget keys. The old code wiped
            # it (it starts with "input_"), so the bump on the next line
            # crashed silently and widget keys stayed identical, leaving
            # the textarea text in place. Guard against that explicitly.
            for k in list(st.session_state.keys()):
                if k == "input_version":
                    continue
                if k.startswith(("input_", "upload_", "pick_", "FormSubmitter")):
                    del st.session_state[k]
            st.session_state.input_version = st.session_state.get("input_version", 0) + 1
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
    # Summary tab dropped — its content (justification, scoring path, owner
    # reason, similar bugs) is already in Triage notes (which renders them
    # in a richer markdown table with clickable Jira links). The metric
    # tiles above already give the at-a-glance view.

    tab_names = ["Findings", "Raw JSON"]
    if use_multi_agent and media and media.findings:
        tab_names.insert(1, "Media findings")
    tabs = st.tabs(tab_names)

    # Tabs render in the order they appear in tab_names:
    #   1. Findings  (always first — primary detail view; was "Triage notes")
    #   2. Media findings  (only when multi-agent + attachments)
    #   3. Raw JSON
    idx = 0

    with tabs[idx]:
        st.markdown(render_triage_md(draft.triage_notes))
    idx += 1

    if use_multi_agent and media and media.findings:
        with tabs[idx]:
            st.caption("What the media sub-agent saw in each attachment.")
            for f in media.findings:
                kind_chip = "🎬 VIDEO" if f.kind == "video" else "🖼 IMAGE"
                st.markdown(f"#### {kind_chip} · {Path(f.image_path).name}")

                # Layout: media preview on the left, structured findings on the right.
                left, right = st.columns([1, 2])
                with left:
                    if f.kind == "video":
                        if Path(f.image_path).exists():
                            st.video(f.image_path)
                        if f.duration_seconds:
                            st.caption(f"Duration: {f.duration_seconds:.1f}s · {f.frame_count} keyframe(s)")
                    else:
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
                    if f.kind == "video" and f.action_observed:
                        st.markdown(f"**Action observed:**  \n{f.action_observed}")
                    if f.kind == "video" and f.failure_moment:
                        st.error(f"**Failure moment:** {f.failure_moment}")
                    st.markdown(f"**One-line summary:**  \n{f.one_line_summary}")
                    if f.kind == "video" and f.screen_sequence:
                        st.markdown(
                            "**Screen sequence:**  \n"
                            + " → ".join(f.screen_sequence)
                        )
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

                # For videos: show the keyframes the sub-agent actually saw,
                # so the reviewer can audit Claude's frame-by-frame reasoning.
                if f.kind == "video" and f.frames:
                    st.markdown("**Keyframes the sub-agent analysed:**")
                    cols = st.columns(min(len(f.frames), 4))
                    for i, frame_path in enumerate(f.frames):
                        if Path(frame_path).exists():
                            with cols[i % len(cols)]:
                                st.image(frame_path, caption=f"Frame {i+1}", use_container_width=True)

                st.divider()
        idx += 1

    with tabs[idx]:
        triage_json = json.dumps(draft.triage_notes, indent=2, ensure_ascii=False)
        st.code(triage_json, language="json")

        full_json = json.dumps(
            {
                "pipeline":          draft.triage_notes.get("pipeline", pipeline_label),
                "jira_ticket_draft": draft.jira_payload,
                "triage_notes":      draft.triage_notes,
            },
            indent=2, ensure_ascii=False,
        )
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "⬇ Download triage_notes.json",
                data=triage_json,
                file_name="triage_notes.json",
                mime="application/json",
                use_container_width=True,
            )
        with col_dl2:
            st.download_button(
                "⬇ Download full ticket draft JSON",
                data=full_json,
                file_name=f"ticket_draft_{pipeline_label.replace(' ', '_')}.json",
                mime="application/json",
                use_container_width=True,
            )
