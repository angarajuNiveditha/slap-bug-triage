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
import re
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
from src.agent_scorer     import (
    score_severity as rb_score,
    PRIORITY_ID_MAP,
    SEVERITY_FOR_PRIORITY,
)
from src.tfidf_similarity import SimilarityEngine as RuleEngine

# Multi-agent pipeline (Claude Code headless, supports media)
from src.agents.host_agent      import HostAgent, detect_quality_issues
from src.agents.subagent_media  import (
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MEDIA_EXTENSIONS,
    MAX_VIDEO_DURATION_SECONDS, MediaResult,
)

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")
DATA_DIR      = Path(__file__).parent / "data"

# ── Manager exceptions ─────────────────────────────────────────────────────
# People who can be assigned bugs in any component regardless of which team
# the empirical assignee-history derivation puts them in. They show up in the
# Owner dropdown labelled "Manager" so it's obvious the assignment isn't
# scoped to a particular team.
#
# Extend this set when new managers are identified — purely a display /
# routing-flexibility override; the underlying team_roster JSON is
# unchanged so model-side suggestions still use the empirical data.
MANAGER_NAMES = {
    "Yatin Grover",
}

# ── Editable-output config ─────────────────────────────────────────────────
# These power the override widgets that appear under the metric tiles so a
# reviewer can correct the model's choices before downloading the JSON.

PRIORITY_OPTIONS  = ["P0", "P1", "P2"]
COMPONENT_OPTIONS = ["Backend", "Backend-Labs", "DS", "UI", "immersive", "bugs"]

TEAM_FOR_COMPONENT = {
    "Backend":      "BE_Flippi",
    "Backend-Labs": "BE_Labs",
    "DS":           "DS",
    "UI":           "UI",
    "immersive":    "Immersive",
    "bugs":         "bugs",
}

# Verified component IDs on flipkart.atlassian.net (FLIPPI project).
COMPONENT_ID_MAP = {
    "Backend":      "14386",
    "Backend-Labs": "14385",
    "DS":           "14384",
    "UI":           "14383",
    "immersive":    "14387",
}


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

      /* ── Editable result tiles — bold + colourful ──────────────────
         The marker sits inside mc1 (first column). CSS uses :has() on
         the parent stHorizontalBlock — which matched reliably in earlier
         testing — and on the first column for priority colour coding.
         The marker wrapper is forced to display:none separately. */

      /* Outer tile container: brighter pink, stronger border, more pop. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) {
          margin: 8px 0 24px 0 !important;
          padding: 18px 22px 14px !important;
          border-radius: 18px !important;
          background: linear-gradient(135deg, #FFE0EE 0%, #FFF5F8 55%, #FFFFFF 100%) !important;
          border: 1.5px solid #F9A8D4 !important;
          box-shadow: 0 14px 32px -14px rgba(225,29,116,0.32) !important;
          gap: 16px !important;
          align-items: stretch !important;
          position: relative !important;
      }

      /* Top accent stripe in pink gradient (purely decorative). */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker)::before {
          content: "" !important;
          position: absolute !important;
          top: -1px !important;
          left: 22px !important;
          width: 64px !important;
          height: 4px !important;
          background: linear-gradient(90deg, #E11D74 0%, #F472B6 100%) !important;
          border-radius: 0 0 6px 6px !important;
      }

      /* Each column = one tile. Pink underline (gets coloured for the
         Priority column below). */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) > [data-testid="stColumn"] {
          padding: 6px 10px 14px !important;
          border-bottom: 3px solid #F9A8D4 !important;
          transition: border-color 0.15s !important;
          display: flex !important;
          flex-direction: column !important;
      }

      /* Tile label — pink-tinted, bolder, slightly tighter. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) [data-testid="stSelectbox"] label,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) [data-testid="stTextInput"] label {
          font-size: 11px !important;
          font-weight: 800 !important;
          letter-spacing: 1.3px !important;
          text-transform: uppercase !important;
          color: #BE185D !important;
          margin-bottom: 6px !important;
          padding: 0 !important;
          line-height: 1 !important;
      }

      /* Selectbox combobox — stripped of chrome at rest; pink on hover. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-baseweb="select"] > div {
          min-height: 48px !important;
          padding: 4px 26px 4px 0 !important;
          border: 1px solid transparent !important;
          background: transparent !important;
          box-shadow: none !important;
          border-radius: 8px !important;
          color: #18181B !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-baseweb="select"] > div:hover {
          background: rgba(255,255,255,0.85) !important;
          border-color: #F472B6 !important;
      }

      /* Value text — extra-bold, bigger (26px), tight letter spacing. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-baseweb="select"] *:not(svg):not(path) {
          font-size: 26px !important;
          font-weight: 800 !important;
          line-height: 1.2 !important;
          letter-spacing: -0.4px !important;
          height: auto !important;
          overflow: visible !important;
      }

      /* Chevron — visible but subtle; pinker on hover for affordance. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-baseweb="select"] svg {
          width: 16px !important;
          height: 16px !important;
          opacity: 0.5 !important;
          color: #BE185D !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-baseweb="select"] > div:hover svg {
          opacity: 1 !important;
      }

      /* Captions — darker grey, slightly bolder so they read clearly. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) div[data-testid="stCaptionContainer"],
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) [data-testid="stCaptionContainer"] p,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker) small {
          font-size: 13px !important;
          font-weight: 500 !important;
          color: #6B5470 !important;
          margin-top: 4px !important;
          margin-bottom: 0 !important;
          padding: 0 !important;
          line-height: 1.4 !important;
      }

      /* Hide every Streamlit wrapper around the marker so it reserves
         zero vertical space — that's how the Priority cell aligns with
         the others. Display:none doesn't remove from the DOM, so the
         :has() rules above (which key off the marker) still match. */
      .metric-tile-row-marker { display: none !important; }
      [data-testid="stMarkdown"]:has(.metric-tile-row-marker),
      [data-testid="stElementContainer"]:has(.metric-tile-row-marker),
      .element-container:has(.metric-tile-row-marker) {
          display: none !important;
      }

      /* Priority-colour underline + value text — keyed off data-prio
         attribute on the marker. The :first-child column inside the
         horizontal block is the Priority cell. Deeper, more saturated
         shades for the "bolder/colourful" look. */
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P0"]) > [data-testid="stColumn"]:first-child {
          border-bottom-color: #DC2626 !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P1"]) > [data-testid="stColumn"]:first-child {
          border-bottom-color: #EA580C !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P2"]) > [data-testid="stColumn"]:first-child {
          border-bottom-color: #D97706 !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P3"]) > [data-testid="stColumn"]:first-child {
          border-bottom-color: #2563EB !important;
      }

      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P0"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] > div,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P0"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] *:not(svg):not(path) {
          color: #DC2626 !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P1"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] > div,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P1"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] *:not(svg):not(path) {
          color: #EA580C !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P2"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] > div,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P2"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] *:not(svg):not(path) {
          color: #D97706 !important;
      }
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P3"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] > div,
      [data-testid="stHorizontalBlock"]:has(.metric-tile-row-marker[data-prio="P3"]) > [data-testid="stColumn"]:first-child div[data-baseweb="select"] *:not(svg):not(path) {
          color: #2563EB !important;
      }

      /* Static "Duplicate-of" tile — matches the editable cells'
         updated sizing (label 11px pink, value 26px extra-bold,
         sub 13px) so the 4 tiles read as a uniform bold row. */
      .static-tile { padding: 0; }
      .static-tile-label {
          font-size: 11px !important;
          font-weight: 800 !important;
          letter-spacing: 1.3px !important;
          text-transform: uppercase !important;
          color: #BE185D !important;
          margin-bottom: 6px !important;
          line-height: 1 !important;
      }
      .static-tile-value {
          font-size: 26px;
          font-weight: 800;
          color: #18181B;
          line-height: 1.2;
          letter-spacing: -0.4px;
          padding: 4px 0;
          min-height: 48px;
          display: flex;
          align-items: center;
      }
      .static-tile-sub {
          font-size: 13px;
          font-weight: 500;
          color: #6B5470;
          margin-top: 4px;
          line-height: 1.4;
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


def synthesize_email_from_form(title: str, platform: str, summary: str, steps: str) -> str:
    """
    Build an email-shaped string from the structured-form fields so the
    existing parser pipeline (regex on the rule-based side, LLM on the
    multi-agent side) handles it identically to a pasted .txt email.

    Returns "" when title and summary are both empty so the Triage button
    stays disabled via the same `not raw_text.strip()` check the email
    mode uses.
    """
    title   = (title   or "").strip()
    summary = (summary or "").strip()
    if not title and not summary:
        return ""

    parts: list[str] = []
    if title:
        parts.append(f"Subject: {title}")
        parts.append("")
    if platform and platform != "Unknown":
        parts.append(f"Platform: {platform}")
        parts.append("")
    if summary:
        parts.append("Description:")
        parts.append(summary)
        parts.append("")

    step_lines = [s.strip() for s in (steps or "").splitlines() if s.strip()]
    if step_lines:
        parts.append("Steps to Reproduce:")
        for i, s in enumerate(step_lines, 1):
            # Strip user-supplied numbering / bullets so we don't double-number.
            clean = re.sub(r"^\s*(?:\d+[\.\)]\s*|[-*]\s*)", "", s)
            parts.append(f"{i}. {clean}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


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
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Body: left rail (pipeline) + main column (input) ───────────────────────

col_rail, col_main = st.columns([1, 3], gap="large")

PIPELINE_RAIL_HTML = """
<div class="pipeline-rail">
  <div class="pipeline-rail-title">Pipeline</div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon endpoint">in</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Input</div>
      <div class="pipe-vnode-desc">Email or structured form + optional screenshots / videos.</div>
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
      <div class="pipe-vnode-desc">Turns text + media findings into a structured BugReport.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">C</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Classifier</div>
      <div class="pipe-vnode-desc">LogReg on 564 labelled bugs; falls back to Claude+skills when confidence &lt; 0.50.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">S</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Similarity</div>
      <div class="pipe-vnode-desc">Cosine search ranks the top-5 most similar bugs from historical FLIPPI tickets.</div>
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
    <div class="pipe-vnode-icon">O</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Owner</div>
      <div class="pipe-vnode-desc">Picks an owner from the routed component's team roster, grounded in similar past bugs.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon">T</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Triage</div>
      <div class="pipe-vnode-desc">Assigns priority P0 / P1 / P2 with a plain-English justification.</div>
    </div>
  </div>

  <div class="pipe-vnode">
    <div class="pipe-vnode-icon endpoint output">out</div>
    <div class="pipe-vnode-text">
      <div class="pipe-vnode-name">Output</div>
      <div class="pipe-vnode-desc">Jira draft + triage_notes JSON. Reviewer approves before filing.</div>
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

    # Top-row controls: input format + pipeline choice
    ctrl_fmt, ctrl_pipe = st.columns([1, 1])
    with ctrl_fmt:
        input_format = st.radio(
            "Input format",
            ["Email (.txt)", "Structured form"],
            index=0,
            horizontal=True,
            help=(
                "Email accepts pasted email text. Structured form is a "
                "guided alternative — fill title / platform / summary / steps."
            ),
            key=f"input_format_{st.session_state.input_version}",
        )
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

    use_form = input_format.startswith("Structured")

    if not use_form:
        # ── Email mode ─────────────────────────────────────────────────
        pick = st.selectbox(
            "Pre-fill from a sample",
            sample_names,
            index=0,
            key=f"pick_{st.session_state.input_version}",
        )
        default_text = ""
        if pick != "(paste your own)":
            default_text = (DATA_DIR / pick).read_text(encoding="utf-8")

        raw_text = st.text_area(
            "Bug report email",
            value=default_text,
            height=300,
            placeholder="From: someone@flipkart.com\nSubject: [URGENT] ...\n\nDescribe the bug here...",
            key=f"input_{pick}_{st.session_state.input_version}",
            label_visibility="collapsed",
        )
    else:
        # ── Structured form mode ───────────────────────────────────────
        form_title = st.text_input(
            "Bug title",
            placeholder="e.g. [Checkout] App crashes when tapping Proceed to Pay on Android",
            key=f"form_title_{st.session_state.input_version}",
        )

        col_plat, _col_sp = st.columns([1, 2])
        with col_plat:
            form_platform = st.selectbox(
                "Platform",
                ["Android", "iOS", "Web", "Android, iOS", "Unknown"],
                index=0,
                key=f"form_platform_{st.session_state.input_version}",
            )

        form_summary = st.text_area(
            "Summary",
            height=120,
            placeholder="Describe what's broken and what should have happened instead.",
            key=f"form_summary_{st.session_state.input_version}",
        )

        form_steps = st.text_area(
            "Steps to reproduce (one step per line — optional)",
            height=140,
            placeholder=(
                "Open the SLAP app\n"
                "Go to Cart\n"
                "Tap Proceed to Pay\n"
                "(app crashes)"
            ),
            key=f"form_steps_{st.session_state.input_version}",
        )

        raw_text = synthesize_email_from_form(
            form_title, form_platform, form_summary, form_steps,
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

                # Defensive: Streamlit's @st.cache_resource may be holding
                # a HostAgent instance built before on_step / from_form
                # existed. Only pass kwargs the cached signature actually
                # accepts, and warn the user if features got skipped.
                import inspect
                sig_params = inspect.signature(host.triage).parameters
                kwargs = {"image_paths": image_paths}
                if "on_step" in sig_params:
                    kwargs["on_step"] = on_step
                if "from_form" in sig_params:
                    kwargs["from_form"] = use_form
                if "on_step" not in sig_params or (use_form and "from_form" not in sig_params):
                    st.warning(
                        "Streamlit is running a cached pipeline build from before a "
                        "recent change. Restart Streamlit "
                        "(`pkill -f streamlit && streamlit run app.py`) to pick it up."
                    )
                result = host.triage(raw_text, **kwargs)
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
                # Pass from_form so structured-form input isn't graded on
                # email-format compliance.
                q = detect_quality_issues(
                    bug,
                    MediaResult(findings=[], combined_summary=""),
                    from_form=use_form,
                )
                # Rule-based + form: cheap consistency heuristic. The
                # multi-agent path gets a proper LLM check via the form-
                # consistency sub-agent; rule-based gets this fallback.
                # Bar is intentionally high to avoid false-positives on
                # synonym pairs ([VTON] vs "virtual try-on"): the title
                # must share ZERO content words with summary AND with
                # steps (when steps exist), and all involved fields must
                # be substantial.
                if use_form:
                    STOPWORDS = {
                        "the","a","an","is","are","was","were","be","been","being",
                        "and","or","but","not","for","with","from","into","over","under",
                        "of","to","in","on","at","by","as","that","this","these","those",
                        "have","has","had","do","does","did","will","would","could","should",
                        "can","may","might","when","if","after","before","then","than",
                        "i","we","you","he","she","it","they","my","our","your","their",
                        "out","up","down","off","app","slap","bug","issue","error",
                    }
                    def _content_words(s):
                        return {w for w in re.findall(r"[a-z]+", (s or "").lower())
                                if len(w) > 2 and w not in STOPWORDS}
                    tw = _content_words(bug.title)
                    sw = _content_words(bug.description)
                    stw = _content_words(" ".join(bug.steps_to_reproduce or []))

                    # Bar set at >= 6 content words each — high enough that
                    # synonym pairs (e.g. "[VTON]" vs "virtual try-on") almost
                    # always have at least one accidental collision, low
                    # enough that genuinely mismatched long submissions
                    # (like the screenshot case at 15 / 11) still trigger.
                    title_substantial          = len(tw) >= 6
                    summary_substantial        = len(sw) >= 6
                    no_overlap_with_summary    = not (tw & sw)
                    no_overlap_with_steps      = (not stw) or not (tw & stw)
                    if (title_substantial
                            and summary_substantial
                            and no_overlap_with_summary
                            and no_overlap_with_steps):
                        q.append({
                            "type":             "form_fields_inconsistent",
                            "severity":         "warning",
                            "message": (
                                "The form's title shares no content words with the "
                                "summary or steps, suggesting they describe different bugs."
                            ),
                            "primary_bug": "",
                            "suggested_action": (
                                "Refile the form with title, summary, and steps that all "
                                "describe the same bug."
                            ),
                        })
                if q:
                    draft.triage_notes["quality_issues"] = q

            status.update(label="Triage complete", state="complete", expanded=False)
        except Exception as e:
            status.update(label="Pipeline failed", state="error")
            st.exception(e)
            st.stop()

    # Stash the result so the priority / component / owner override widgets
    # below can re-render the same draft without re-running the pipeline.
    # (Every widget interaction triggers a Streamlit script re-run, during
    # which triage_btn is False — without this, the result would disappear
    # the moment the user touches a dropdown.)
    st.session_state.triage_result = {
        "bug":             bug,
        "sim":             sim,
        "severity":        severity,
        "draft":           draft,
        "media":           media,
        "use_multi_agent": use_multi_agent,
        "pipeline_label":  pipeline_label,
    }
    # Fresh run — drop stale override selections from a previous bug so the
    # new prediction shows as the dropdown's default.
    for k in ("edit_priority", "edit_component", "edit_owner",
              "edit_owner_choice", "edit_owner_jira_query", "edit_owner_jira_pick",
              "draft_approved", "btn_approve_draft", "btn_publish_jira"):
        st.session_state.pop(k, None)


# ── Render result (runs for both fresh triage and edit-widget re-runs) ─────

if "triage_result" in st.session_state:
    r = st.session_state.triage_result
    bug             = r["bug"]
    sim             = r["sim"]
    severity        = r["severity"]
    draft           = r["draft"]
    media           = r["media"]
    use_multi_agent = r["use_multi_agent"]
    pipeline_label  = r["pipeline_label"]

    # ── Headline ────────────────────────────────────────────────────────────

    st.markdown('<div class="section-label">Step 2 · Result</div>', unsafe_allow_html=True)

    # ── Quality warnings (vague report / image-vs-text contradiction) ──────
    # If we flag a quality issue we STOP rendering — no tentative draft is
    # shown below, because the whole point of the refile prompt is that the
    # input wasn't good enough to triage on.
    quality_issues = draft.triage_notes.get("quality_issues") or []
    if quality_issues:
        # Lead the banner with the most-relevant message. If any quality
        # issue is a vague_report we use the "Insufficient info" wording;
        # otherwise the contradiction message.
        kinds_present = {q.get("type") for q in quality_issues}
        if "vague_report" in kinds_present:
            banner_h4 = "⚠ Insufficient info — please refile"
            banner_p  = ("This bug report is missing the sections needed for confident triage. "
                         "Refile with the corrections below.")
        elif "form_fields_inconsistent" in kinds_present:
            banner_h4 = "⚠ Form fields describe different bugs"
            banner_p  = ("The title, summary, and steps appear to describe different bugs. "
                         "Refile with all three fields aligned to a single bug.")
        else:
            banner_h4 = "⚠ This bug cannot be triaged confidently"
            banner_p  = ("The attached image contradicts the text of the report. "
                         "Refile with the corrections below.")
        st.markdown(
            f"""
            <div class="quality-banner">
              <h4>{banner_h4}</h4>
              <p>{banner_p}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for q in quality_issues:
            kind = q.get("type", "issue")
            label = {
                "vague_report":              "Insufficient info",
                "media_contradicts_text":    "Image ⇄ email mismatch",
                "form_fields_inconsistent":  "Mixed-up form fields",
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
                if k.startswith(("input_", "upload_", "pick_", "form_", "edit_", "FormSubmitter")):
                    del st.session_state[k]
                if k == "triage_result":
                    del st.session_state[k]
            st.session_state.input_version = st.session_state.get("input_version", 0) + 1
            st.rerun()

        st.stop()

    # ── Editable result tiles ─────────────────────────────────────────────
    # The result IS the edit form — no separate "view then edit" step. The
    # widgets carry both the model's prediction (their default value) and
    # the reviewer's override (their current value). Downloads + the Approve
    # / Publish flow below pick up whatever's in the widgets at submit time.
    prio = severity.priority if severity.priority in ("P0", "P1", "P2", "P3") else "P2"
    predicted_prio  = prio if prio in PRIORITY_OPTIONS else "P2"
    predicted_comp  = draft.triage_notes.get("jira_component") or "bugs"
    if predicted_comp not in COMPONENT_OPTIONS:
        predicted_comp = "bugs"
    predicted_owner = sim.suggested_owner or ""
    dup_v   = sim.duplicate_of or "—"
    dup_sub = f"{sim.duplicate_confidence:.0%} confidence" if sim.duplicate_of else "no duplicate found"

    st.caption(
        "Pick a different value to override the model. Component overrides are "
        "saved to data/corrections.csv as labelled training data — the model "
        "gets smarter every time you correct it."
    )

    # ── Low-confidence ambiguity banner ──────────────────────────────────
    # When LogReg can't commit to a single team (top class probability is
    # below 0.45) we surface the full probability distribution and tell
    # the user *why* — better than letting them assume a confident answer.
    classifier_info = draft.triage_notes.get("classifier") or {}
    probabilities   = classifier_info.get("probabilities") or {}
    clf_confidence  = float(classifier_info.get("confidence") or 0.0)
    # Show the full probability distribution when LogReg couldn't commit
    # confidently — same threshold the Claude fallback triggers at, so the
    # user sees the ambiguity whenever the system fell back to Claude.
    AMBIGUITY_THRESHOLD = 0.50

    if probabilities and clf_confidence < AMBIGUITY_THRESHOLD:
        sorted_probs = sorted(probabilities.items(), key=lambda kv: -kv[1])
        bar_html = ""
        for cls, p in sorted_probs:
            width = int(p * 100)
            bar_html += (
                f'<div style="margin:6px 0;">'
                f'  <div style="display:flex;justify-content:space-between;font-size:13px;color:#18181B;">'
                f'    <span style="font-weight:600;">{html.escape(cls)}</span>'
                f'    <span style="color:#78716C;">{p:.0%}</span>'
                f'  </div>'
                f'  <div style="height:10px;background:#FCE7F0;border-radius:6px;overflow:hidden;">'
                f'    <div style="height:100%;width:{width}%;background:linear-gradient(90deg,#E11D74,#F9A8D4);"></div>'
                f'  </div>'
                f'</div>'
            )
        st.markdown(
            f"""
            <div style="background:#FFF7ED;border:1px solid #FED7AA;border-left:4px solid #EA580C;
                        border-radius:10px;padding:14px 18px;margin:6px 0 18px 0;">
              <div style="font-weight:700;color:#9A3412;font-size:14px;margin-bottom:4px;">
                ⚠ Low-confidence routing — please decide
              </div>
              <div style="color:#7C2D12;font-size:13px;margin-bottom:10px;">
                The classifier couldn't commit to a single team (top class only {clf_confidence:.0%} confident).
                Probability distribution:
              </div>
              {bar_html}
              <div style="color:#7C2D12;font-size:12px;margin-top:8px;">
                Your pick below will be saved to <code>data/corrections.csv</code> as a labelled
                training example for next time.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Single row, 4 tiles — Priority + Component + Owner (editable) +
    # Duplicate-of (read-only). Matches the original .metric-grid layout.
    mc1, mc2, mc3, mc4 = st.columns([1, 1.1, 1.7, 1.1])

    with mc1:
        # Marker INSIDE mc1 so the :has() selectors on the parent
        # stHorizontalBlock (and on this column) match reliably across
        # Streamlit versions. The wrapper is hidden via display:none
        # which doesn't affect :has() matching (DOM-presence based).
        current_prio_for_colour = st.session_state.get("edit_priority", predicted_prio)
        st.markdown(
            f'<div class="metric-tile-row-marker" data-prio="{current_prio_for_colour}"></div>',
            unsafe_allow_html=True,
        )
        edited_prio = st.selectbox(
            "Priority",
            PRIORITY_OPTIONS,
            index=PRIORITY_OPTIONS.index(predicted_prio),
            key="edit_priority",
            help=f"Model predicted: {predicted_prio} ({severity.severity})",
        )
        st.caption(SEVERITY_FOR_PRIORITY[edited_prio])

    with mc2:
        edited_comp = st.selectbox(
            "Component",
            COMPONENT_OPTIONS,
            index=COMPONENT_OPTIONS.index(predicted_comp),
            key="edit_component",
            help=f"Model predicted: {predicted_comp}",
        )
        st.caption(f"Team: {TEAM_FOR_COMPONENT[edited_comp]}")

    with mc3:
        # ── Owner picker — Jira-style searchable dropdown ─────────────
        # Source: the team roster derived from historical Jira assignees
        # (see EmbeddingClassifier.team_roster). Streamlit's selectbox
        # supports search-as-you-type out of the box for lists this size,
        # matching Jira's own assignee picker UX.
        #
        # When the reviewer wants someone outside the roster (an engineer
        # who hasn't been assigned a FLIPPI bug recently), the "Other —
        # search Jira" option opens a live search against
        # /rest/api/3/user/assignable/multiProjectSearch — same endpoint
        # Jira's UI calls.

        OTHER_OPTION = "(Other — search Jira directly)"

        try:
            host_for_roster = get_engines()[1]
            team_roster = host_for_roster.classifier.team_roster or {}
        except Exception:
            team_roster = {}

        # Build a flat list of unique engineers, with team annotated.
        # Managers get a "Manager" team label so they appear cross-team
        # in the dropdown (any bug can be assigned to them).
        engineer_to_team: dict[str, str] = {}
        for team, members in team_roster.items():
            for m in members:
                name = m.get("name")
                if not name or name in engineer_to_team:
                    continue
                engineer_to_team[name] = "Manager" if name in MANAGER_NAMES else team

        # Ensure the model-suggested owner is always selectable even if
        # somehow not in the roster (defensive).
        if predicted_owner and predicted_owner not in engineer_to_team:
            engineer_to_team[predicted_owner] = (
                "Manager" if predicted_owner in MANAGER_NAMES else "?"
            )

        # Sort: managers first (any-team), then alphabetical within each group.
        # Within-group alphabetical sort plays nicely with search-as-you-type.
        owner_options = sorted(
            engineer_to_team.keys(),
            key=lambda n: (0 if engineer_to_team[n] == "Manager" else 1, n.lower()),
        )

        # Default to the suggested owner if present, else first entry.
        if predicted_owner and predicted_owner in owner_options:
            default_idx = owner_options.index(predicted_owner)
        else:
            default_idx = 0 if owner_options else None

        # Append "Other" sentinel at the end.
        owner_options_with_other = owner_options + [OTHER_OPTION]

        chosen_owner = st.selectbox(
            "Owner",
            options       = owner_options_with_other,
            index         = default_idx if default_idx is not None else 0,
            key           = "edit_owner_choice",
            help          = (
                f"Model suggested: {predicted_owner or '(none)'}. "
                f"Type to search the roster ({len(owner_options)} SLAP engineers). "
                f"Pick \"Other\" to search all assignable Jira users."
            ),
            format_func   = lambda n: (
                n if n == OTHER_OPTION
                else f"{n}  ·  {engineer_to_team.get(n, '?')}"
            ),
        )

        # ── "Other" branch: live Jira search ─────────────────────────
        if chosen_owner == OTHER_OPTION:
            jira_query = st.text_input(
                "Search Jira for an assignable user",
                placeholder="Type a name or email…",
                key="edit_owner_jira_query",
            )
            edited_owner = None
            if jira_query and len(jira_query.strip()) >= 2:
                # Cache the search results in session_state so re-rendering
                # (when the user picks from the results dropdown) doesn't
                # re-fire the API call on every keystroke.
                cache_key = f"jira_user_search_{jira_query.strip().lower()}"
                if cache_key not in st.session_state:
                    try:
                        rb_for_search, _, _ = get_engines()
                    except Exception:
                        rb_for_search = None
                    # JiraClient lives on the host or can be re-instantiated.
                    from src.jira_client import JiraClient
                    jc = JiraClient()
                    st.session_state[cache_key] = jc.search_assignable_users(
                        jira_query.strip(), limit=15
                    )
                results = st.session_state[cache_key]

                if not results:
                    st.caption(f"No assignable users matched “{jira_query}”.")
                else:
                    result_labels = [
                        f"{r['displayName']}  ·  {r.get('emailAddress') or '(no email)'}"
                        for r in results
                    ]
                    sel = st.selectbox(
                        "Jira matches",
                        options = result_labels,
                        key     = "edit_owner_jira_pick",
                    )
                    # Recover the displayName from the label.
                    chosen_idx = result_labels.index(sel)
                    edited_owner = results[chosen_idx]["displayName"]
            else:
                st.caption("Type at least 2 characters to search Jira.")
        else:
            edited_owner = chosen_owner

    with mc4:
        # Duplicate-of — read-only tile (no editable widget, the dedup
        # decision is the model's, not the reviewer's).
        st.markdown(
            f"""
            <div class="static-tile">
              <div class="static-tile-label">Duplicate of</div>
              <div class="static-tile-value">{html.escape(str(dup_v))}</div>
              <div class="static-tile-sub">{html.escape(dup_sub)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if sim.duplicate_of:
            st.markdown(f"🔗 [Open]({JIRA_BASE_URL}/browse/{sim.duplicate_of})")

    # ── Patch draft so JSON downloads at the bottom reflect overrides ─────
    edited_owner_clean = (edited_owner.strip() if edited_owner else None) or None

    draft.triage_notes["team"]             = TEAM_FOR_COMPONENT[edited_comp]
    draft.triage_notes["jira_component"]   = None if edited_comp == "bugs" else edited_comp
    draft.triage_notes["owner_suggestion"] = edited_owner_clean
    draft.triage_notes["priority"]         = edited_prio
    draft.triage_notes["severity"]         = SEVERITY_FOR_PRIORITY[edited_prio]

    fields = draft.jira_payload.setdefault("fields", {})
    fields["priority"] = {"id": PRIORITY_ID_MAP[edited_prio]}
    # Severity is filed under the custom field on FLIPPI.
    fields["customfield_10331"] = {"value": SEVERITY_FOR_PRIORITY[edited_prio]}
    if edited_comp == "bugs":
        fields.pop("components", None)
    else:
        comp_entry = {"name": edited_comp}
        if edited_comp in COMPONENT_ID_MAP:
            comp_entry["id"] = COMPONENT_ID_MAP[edited_comp]
        fields["components"] = [comp_entry]

    # ── Active learning: persist component overrides as labelled data ────
    # Every time the user picks a different component than the model did,
    # we append the (bug-text, corrected-component) pair to corrections.csv.
    # On the next index rebuild, those rows fold into the training corpus.
    # Dedup via session_state so we don't write the same row repeatedly
    # as the user clicks around — only the latest correction per bug wins.
    if edited_comp != predicted_comp and edited_comp != "bugs":
        import hashlib, csv
        from datetime import datetime
        bug_text_for_training = f"{bug.title}\n\n{bug.description}\n\n{bug.actual_result}"
        bug_hash = hashlib.md5(bug_text_for_training.encode("utf-8")).hexdigest()[:12]

        already_saved = st.session_state.setdefault("corrections_written", {})
        if already_saved.get(bug_hash) != edited_comp:
            corrections_path = Path(__file__).parent / "data" / "corrections.csv"
            corrections_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not corrections_path.exists()
            with corrections_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow([
                        "timestamp", "bug_hash", "predicted_component",
                        "corrected_component", "confidence_at_prediction",
                        "title", "bug_text",
                    ])
                writer.writerow([
                    datetime.utcnow().isoformat(),
                    bug_hash,
                    predicted_comp,
                    edited_comp,
                    f"{clf_confidence:.3f}",
                    bug.title or "",
                    bug_text_for_training,
                ])
            already_saved[bug_hash] = edited_comp
            st.toast(
                f"✓ Saved correction to corrections.csv — model will learn "
                f"{predicted_comp} → {edited_comp} on next rebuild.",
                icon="🧠",
            )

    # Audit trail — record that a human edited this, so a downstream reader
    # can tell the JSON is a corrected draft, not the raw model output.
    overrides = {}
    if edited_prio  != predicted_prio:   overrides["priority"]  = {"from": predicted_prio,  "to": edited_prio}
    if edited_comp  != predicted_comp:   overrides["component"] = {"from": predicted_comp,  "to": edited_comp}
    if edited_owner_clean != (predicted_owner or None):
        overrides["owner"] = {"from": predicted_owner or None, "to": edited_owner_clean}
    if overrides:
        draft.triage_notes["human_overrides"] = overrides

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

    # ── Approve & Publish (prototype demo) ─────────────────────────────────
    # Approve gates Publish-to-Jira. Publish itself is intentionally a no-op
    # in this prototype — the project's hard constraint is read-only Jira,
    # so the button exists only to demonstrate where production wiring would
    # plug in. State is per-bug via st.session_state, reset on every fresh
    # triage by the cleanup loop above.

    st.markdown('<div class="section-label">Step 3 · Approve &amp; file</div>', unsafe_allow_html=True)

    if not st.session_state.get("draft_approved"):
        st.caption(
            "Review the metric tiles, override Priority / Component / Owner above if needed, "
            "then approve the draft to enable Publish-to-Jira."
        )
        if st.button("✓ Approve this draft", type="primary", use_container_width=True, key="btn_approve_draft"):
            st.session_state["draft_approved"] = True
            st.rerun()
    else:
        st.success("✓ Draft approved — ready to file.")
        if st.button("📤 Publish to Jira", type="primary", use_container_width=True, key="btn_publish_jira"):
            # Intentionally a no-op for the prototype. Production would call
            # JiraClient.create_issue() here (which doesn't exist yet — the
            # client is deliberately read-only). Show a non-committal toast
            # so the click feels acknowledged without misrepresenting state.
            st.toast(
                "📤 Publish-to-Jira clicked — UI demo only; no Jira write happens in this prototype.",
                icon="ℹ",
            )
