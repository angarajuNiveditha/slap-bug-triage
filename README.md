# SLAP Bug Triage

An agentic bug-triage prototype for **SLAP** 

Given a raw bug-report email / csv and optional screenshots or video, the system
fetches real historical tickets from the FLIPPI Jira project, finds
semantic duplicates, suggests a component owner, scores severity, and
produces a reviewer-ready Jira ticket draft as JSON — without writing
anything to Jira.

> **Read-only Jira. Nothing is auto-filed.** A human reviews every draft
> before the actual ticket is filed.

---

## Table of Contents

1. [What it does](#what-it-does)
2. [Two pipelines](#two-pipelines)
3. [How the multi-agent pipeline works](#how-the-multi-agent-pipeline-works)
4. [Repository structure](#repository-structure)
5. [Prerequisites](#prerequisites)
6. [Setup](#setup)
7. [Running the pipelines](#running-the-pipelines)
8. [Streamlit UI](#streamlit-ui)
9. [Output format](#output-format)
10. [Production mapping](#production-mapping)
11. [Design constraints](#design-constraints)

---

## What it does

A SLAP bug report arrives as an email/csv (sometimes with screenshots or a
screen recording). Today that input is manually triaged: someone reads it,
searches Jira for duplicates, picks a priority, routes it to a team, and
opens the ticket. This prototype automates every step:

| Step | What happens |
|---|---|
| **Parse** | Extracts title, platform, version, steps-to-reproduce, impact, and reproducibility from free-form email text |
| **Media** | Reads each attached screenshot or video keyframe; identifies the SLAP screen, visible anomalies, and contradiction with the email body |
| **Classify** | Routes the bug to one of five engineering teams (Backend, BE_Labs, DS, UI, Immersive) using a LogReg classifier trained on 564 real FLIPPI bugs(In cases where the classifier is not confident, skill files are pulled for context and the component is decided) |
| **Similar-bug retrieval** | Cosine top-30 recall over an mpnet embedding index → cross-encoder rerank → top-10 most similar past tickets |
| **Dedup** | Decides whether the new report is a duplicate of any retrieved ticket (fires only at ≥ 0.80 confidence) |
| **Triage** | Assigns P0 / P1 / P2 with a plain-English justification grounded in scope, reproducibility, and similar bugs |
| **Owner suggestion** | Picks an engineer from same-component historical assignees; escalates to team manager if no match |
| **Ticket draft** | Assembles an Atlassian Document Format (ADF) Jira ticket JSON ready for human review |
| **Review dashboard** | Streamlit UI at `localhost:8501` — triage result view lets the reviewer override any field and click **Publish** to save the ticket to the local DB; **Ticket Dashboard** view shows all locally stored BUGT-* tickets in an editable table where Status can be updated (New → In Review → Escalated → Resolved → Closed) |

---

## Two pipelines

| | Multi-agent (primary) | Rule-based (simulation) |
|---|---|---|
| **Entry point** | `run_multi_agent.py` | `run_agent.py` |
| **How it works** | Host agent + 6 Claude sub-agents, local ML for retrieval/classification | Regex + TF-IDF + multi-layer keyword scorer, pure Python |
| **Latency** | ~150-180 s/bug with images | ~35 ms/bug |
| **Reads images/video** | Yes — Gemini vision + Claude reasoning | No |
| **Handles paraphrases** | Yes | Only what's in the keyword/template list |
| **API key needed** | None — uses Claude Code CLI (local session) | None |
| **Deterministic** | No — small LLM variation across runs | Yes |


A third pipeline `main.py` exists as a production-shape Anthropic SDK
reference. It is blocked on `ANTHROPIC_API_KEY` (Flipkart corp network
restricts `console.anthropic.com`); it is kept because swapping it in for
production is a one-line change per stage.

---

## How the multi-agent pipeline works

```
bug input (email .txt or structured form + optional images / videos)
    │
    ▼
[1] subagent_media  ──── only if attachments present ────────────────────
    │   Stage 1: each image (or ≤8 video keyframes) → Gemini vision in
    │            parallel via Flipkart's internal proxy (~3 s images,
    │            ~14 s video). Falls back to Claude-direct if Gemini
    │            JWT is expired or off-corp.
    │   Stage 2: Claude reads the Gemini descriptions + SLAP_KNOWLEDGE.md
    │            + slap_context/reference_screens/ → emits MediaFinding
    │            (screen label, anomalies, contradiction flag).
    ▼
[2] subagent_parser
    │   Email text + any media findings → structured BugReport
    │   (title, platform, version, steps, expected, actual, impact,
    │    reproducibility, component).
    ▼
[2b] subagent_form_consistency  ── only when input is from the UI form ──
    │   Checks that title / summary / steps describe the same bug.
    │   Refiles if they diverge.
    ▼
[3a] EmbeddingClassifier  (local ML, ~7 ms)
    │   LogReg on 564 component-labelled FLIPPI bugs (mpnet embeddings).
    │   Confidence ≥ 0.60 → returns team immediately.
    │   Confidence < 0.60 (~45 % of bugs) → falls back to Claude with
    │   the top-3 candidate teams' architecture skill files loaded.
    ▼
[3b] EmbeddingSimilarityEngine  (local ML)
    │   (i)  Cosine top-30 recall over the mpnet embedding index (~200 µs)
    │   (ii) Cross-encoder rerank (ms-marco-MiniLM-L-6-v2) of those 30
    │        pairs (~1.2 s CPU) → top-10 handed to the parallel block.
    ▼
[4] PARALLEL BLOCK (ThreadPoolExecutor, ~8–15 s wall)
    ├── subagent_dedup   → dup / no-dup decision (≥ 0.80 confidence)
    ├── subagent_owner   → engineer pick from same-component assignees
    │                      → closest-bug manager → TEAM_MANAGERS fallback
    └── subagent_triage  → P0 / P1 / P2 with severity justification
    ▼
agent_ticket_builder  → Jira ADF draft + triage_notes JSON
    ▼
human review (Streamlit UI — triage view)
    ├── Override Priority / Component / Owner
    │       └── overrides written to triage_notes.human_overrides
    │           and appended to data/corrections.csv
    │               └── active-learning loop: corrections.csv is folded
    │                   into the next build_embedding_index.py run,
    │                   retraining the LogReg classifier on human-verified labels
    └── Publish button
            ├── ticket saved to data/tickets.db (SQLAlchemy — SQLite or MySQL)
            ├── attachments copied to data/tickets_attachments/<BUGT-N>/
            ├── INSERT event appended to data/tickets_events.csv
            └── UI navigates to Ticket Dashboard
    ▼
Ticket Dashboard (Streamlit UI — dashboard view)
    Editable table of all BUGT-* tickets
    Status column: New → In Review → Escalated → Resolved → Closed
    Status changes write back to the DB immediately
```

---

## Repository structure

```
slap-bug-triage/
│
├── app.py                        # Streamlit UI (pipeline toggle + media uploader)
├── run_multi_agent.py            # PRIMARY: multi-agent Claude pipeline
├── run_agent.py                  # Rule-based simulation harness (fast, no API)
├── main.py                       # Anthropic SDK reference pipeline (blocked)
│
├── requirements.txt
├── .env.example                  # template — copy to .env and fill in
│
├── src/
│   ├── agents/                   # ── multi-agent pipeline ──────────────────
│   │   ├── host_agent.py         #   Astral — orchestrates sub-agents
│   │   ├── subagent_media.py     #   Gemini vision → Claude reasoning
│   │   ├── subagent_parser.py    #   email + media → BugReport
│   │   ├── subagent_form_consistency.py  # form-mode: title/summary/steps same bug?
│   │   ├── subagent_dedup.py     #   dup / no-dup decision
│   │   ├── subagent_owner.py     #   engineer / manager pick
│   │   └── subagent_triage.py    #   priority assignment (P0/P1/P2)
│   │
│   ├── ml/                       # ── local ML models ───────────────────────
│   │   ├── embedding_classifier.py  # LogReg component classifier (mpnet)
│   │   └── embedding_similarity.py  # cosine + cross-encoder retrieval
│   │
│   ├── rule_based/               # ── simulation pipeline ───────────────────
│   │   ├── agent_parser.py       #   regex + heuristic BugReport extractor
│   │   ├── agent_scorer.py       #   multi-layer priority scorer (L1–L4)
│   │   └── tfidf_similarity.py   #   TF-IDF cosine similarity (scikit-learn)
│   │
│   ├── shared/                   # ── shared utilities ──────────────────────
│   │   ├── agent_ticket_builder.py  # ADF Jira JSON assembler
│   │   ├── jira_client.py        #   read-only Jira REST v3 wrapper
│   │   ├── db.py                 #   local ticket store (SQLAlchemy, MySQL/SQLite)
│   │   ├── claude_cli.py         #   subprocess wrapper for `claude -p`
│   │   ├── genvoy_client.py      #   Flipkart Gemini proxy client
│   │   ├── repo_context.py       #   GitHub Enterprise clone + git grep
│   │   └── team_config.py        #   team labels, Jira IDs, manager mapping
│   │
│   └── sdk/                      # ── Anthropic SDK reference (blocked) ─────
│       ├── parser.py
│       ├── severity_scorer.py
│       ├── similarity.py
│       └── ticket_builder.py
│
├── scripts/
│   ├── build_embedding_index.py  # fetch Jira → embed → save index (one-time)
│   └── build_repo_skills.py      # mine SLAP repos → generate architecture/*.md
│
├── slap_context/
│   ├── SLAP_KNOWLEDGE.md         # screen catalog, vocabulary, visual triage cues
│   ├── reference_screens/        # 16 labelled Figma PNGs (Figma export)
│   └── architecture/             # team + per-repo skill files for the classifier
│       ├── Backend.md
│       ├── Backend-Labs.md
│       ├── DS.md
│       ├── UI.md
│       ├── immersive.md
│       └── repos/                # 8 per-repo skill files (auto-generated)
│
├── data/
│   ├── bug_with_media/           # multi-modal test bugs
│   │   └── bug_*/                # email.txt + screenshots (.png) + recordings (.mp4) committed
│   ├── embedding_index.npz       # gitignored — built by scripts/build_embedding_index.py
│   ├── embedding_index_logreg.pkl
│   ├── embedding_index_team_roster.json
│   └── tickets.db                # gitignored — local SQLite/MySQL ticket store
│
├── report/                       # PDF report goes here (screenshots/, videos/)
│
├── output/                       # rule-based outputs (gitignored)
└── output_claude/                # multi-agent outputs (gitignored)
```

---

## Prerequisites

### 1. Python 3.10 or later

```bash
python3 --version   # should be 3.10+
```

### 2. Claude Code CLI (for the multi-agent pipeline)

Install the Claude Code CLI and sign in. The multi-agent pipeline calls
`claude -p` as a subprocess — no `ANTHROPIC_API_KEY` is needed because it
authenticates via your local Claude Code session.

```bash
# Verify it's installed and authenticated
which claude          # must return a path, e.g. /usr/local/bin/claude
claude --version      # prints the version
claude -p "hello"     # should return a short JSON response
```

If `claude` is not found, install it from [claude.ai/code](https://claude.ai/code)
and run `claude login` to authenticate.

### 3. Jira credentials

You need a read-only Atlassian API token for the FLIPPI project
(`flipkart.atlassian.net`).

- The **multi-agent pipeline** uses a pre-built local embedding index
  (`data/embedding_index.npz`, built once by `scripts/build_embedding_index.py`
  from up to 2000 FLIPPI bugs). At runtime it only hits Jira to verify
  credentials and to resolve ticket metadata for the top similar bugs.
  Similarity search runs over the local index **and** the local ticket
  store (`data/tickets.db`, BUGT-* tickets) — no full corpus fetch per run.
- The **rule-based pipeline** fetches 300 recent FLIPPI bugs from Jira at
  startup to build its TF-IDF index.

Generate a token at `id.atlassian.net → Security → API tokens` and keep it
ready for the `.env` step below.

### 4. (Optional) Flipkart internal Gemini proxy

The media sub-agent's fast path runs Gemini vision via Flipkart's internal
proxy at `10.83.64.112`. This requires two headers: an APIM subscription
key and a Genvoy JWT. Both go in `.env` (see below). If either is absent
or expired the sub-agent automatically falls back to a direct Claude-only
vision pass with no functional difference in output.

---

## Setup

### Step 1 — Clone and install dependencies

```bash
git clone https://github.com/angarajuNiveditha/slap-bug-triage.git
cd slap-bug-triage

pip3 install -r requirements.txt
```

`requirements.txt` installs:

| Package | Used by |
|---|---|
| `requests` | Jira REST API, Gemini proxy |
| `python-dotenv` | `.env` loading |
| `numpy` | embedding math |
| `scikit-learn` | TF-IDF vectorizer, LogReg classifier, cosine similarity |
| `sentence-transformers` | mpnet embedder + cross-encoder reranker |
| `streamlit` | Streamlit UI |
| `sqlalchemy` + `pymysql` | local ticket store |
| `imageio-ffmpeg` | video keyframe extraction |
| `anthropic` | `main.py` only (SDK reference pipeline) |

### Step 1b — Pre-download the sentence-transformer models

The pipeline uses two models from `sentence-transformers`. They are
downloaded automatically on first use, but the combined download is
~420 MB. Pre-downloading avoids a surprise pause mid-triage:

```bash
python3 - <<'EOF'
from sentence_transformers import SentenceTransformer, CrossEncoder
print("Downloading bi-encoder (all-mpnet-base-v2)...")
SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
print("Downloading cross-encoder (ms-marco-MiniLM-L-6-v2)...")
CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
print("Done — models cached in ~/.cache/torch/sentence_transformers/")
EOF
```

| Model | Role | Size |
|---|---|---|
| `all-mpnet-base-v2` | Embeds bug text → 768-dim vectors for cosine recall and the LogReg classifier | ~420 MB |
| `ms-marco-MiniLM-L-6-v2` | Cross-encoder reranker — scores each (new bug, candidate) pair jointly to rerank the cosine top-30 → top-10 | ~23 MB |

Both are cached after the first download and never re-fetched.

### Step 2 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```ini
# REQUIRED
JIRA_EMAIL=your.email@flipkart.com
JIRA_TOKEN=your_atlassian_api_token_here
JIRA_BASE_URL=https://flipkart.atlassian.net
JIRA_PROJECT=FLIPPI
DATABASE_URL=sqlite:///data/tickets.db

# OPTIONAL — media sub-agent Gemini fast path (falls back to Claude if absent)
GEMINI_API_URL=
GEMINI_API_KEY=
GENVOY_TOKEN=

# OPTIONAL — re-generate architecture skill files from live SLAP repos
GITHUB_FK_TOKEN=
GITHUB_FK_ORG=flipkart-incubator

# OPTIONAL — main.py SDK reference pipeline only (blocked on corp network)
ANTHROPIC_API_KEY=
```

Verify your Jira credentials work:

```bash
python3 -c "
from dotenv import load_dotenv; load_dotenv()
from src.shared.jira_client import JiraClient
j = JiraClient()
print(j.whoami())
"
```

You should see your Atlassian account email returned.

### Step 3 — Build the embedding index

The multi-agent pipeline's component classifier and similarity engine
both run off a local embedding index. Build it once after setup, and
rebuild whenever you want to incorporate new FLIPPI bugs:

```bash
python3 scripts/build_embedding_index.py
```

This fetches the last 2000 FLIPPI bugs from Jira (~30–60 s depending on
network), embeds each with `all-mpnet-base-v2`, trains the LogReg
classifier, and writes three files to `data/`:

```
data/embedding_index.npz            ← 764-dim embedding matrix
data/embedding_index_logreg.pkl     ← trained LogReg weights
data/embedding_index_team_roster.json  ← per-component assignee list
```

Options:

```bash
python3 scripts/build_embedding_index.py --limit 3000   # larger corpus
python3 scripts/build_embedding_index.py --months 12    # last 12 months only
```

> The rule-based pipeline (`run_agent.py`) does **not** need this index —
> it builds a TF-IDF index from 300 freshly fetched bugs at runtime.

---

## Streamlit UI

```bash
streamlit run app.py
# Opens at http://localhost:8501
```

**Input panel** — two modes:

- **Paste email**: free-form text area for the raw bug report
- **Structured form**: separate fields for Title, Platform, Summary, Steps
  to Reproduce, Expected, Actual, Impact, Reporter

Both modes support drag-and-drop image / video upload (PNG, JPG, MP4).

**Pipeline toggle** — switch between Multi-agent (Claude) and Rule-based
(local) with a radio button. The rule-based toggle is useful for instant
turnaround when iterating on prompts or testing the classifier.

**After triage**, the results panel shows:

| Element | Description |
|---|---|
| Priority tile | P0 (red) / P1 (orange) / P2 (amber) with severity justification |
| Team badge | Classified component + confidence |
| Owner tile | Suggested engineer (or manager if no history) |
| Duplicate tile | `FLIPPI-XXXX` link if a dup was found at ≥ 0.80 confidence |
| Similar bugs | Top-3 with similarity scores and Jira links |
| Triage notes tab | Full LLM reasoning in rendered markdown |
| Raw JSON tab | Complete output JSON |
| Jira ADF tab | ADF-formatted description preview |

**Edit widgets** — Priority, Component, and Owner are editable dropdowns.
Changes are tracked in `triage_notes.human_overrides` and written to
`data/corrections.csv` for the next active-learning index rebuild.

**Ambiguity banner** — shown when the LogReg classifier confidence is
below 0.60 (borderline routing). Prompts the reviewer to verify the team
before downloading.

**Refile banner** — shown when the report is vague (missing 2+ required
sections) or when the media sub-agent's `contradicts_email_claim` flag is
set (e.g., email says "checkout crash" but the attached screenshot shows
the login screen). The draft is withheld; the reviewer is prompted to ask
the reporter for more information.

**Publish button** — saves the reviewed ticket to the local store
(`data/tickets.db` via SQLAlchemy, MySQL or SQLite). Attachments are
copied to `data/tickets_attachments/<BUGT-N>/`. An INSERT event is
appended to `data/tickets_events.csv` for audit. After publishing, the UI
navigates automatically to the Ticket Dashboard.

### Ticket Dashboard

Accessible from the **📋 Dashboard (N)** button in the top-right nav (N
is the current count of stored tickets). A separate full-page view — the
triage input columns are not shown.

```

- **Key** — auto-assigned `BUGT-N` (local store; not a Jira key)
- **Status** — inline editable dropdown: `New` → `In Review` → `Escalated` → `Resolved` → `Closed`. Changes are written back to the DB immediately on save.
- All other columns are read-only in the table.
- If a locally stored ticket is flagged as a duplicate of an incoming bug, the triage view shows a `🏠 BUGT-N` badge and warns if that ticket's status is already Resolved or Closed.

---
## Production mapping

Every prototype component has a direct production equivalent:

| Prototype | Production (Flipkart PaaS) |
|---|---|
| Bug report `.txt` file | Gmail email via fk-mart-ai-pulse |
| `run_multi_agent.py` | Astral agent runtime |
| `claude -p` subprocess | Genvoy / FK-GPT (internal LLM gateway) |
| Gemini proxy at `10.83.64.112` | Same endpoint — already production |
| `data/embedding_index.npz` | Vector One (managed vector DB) |
| Jira REST v3 (read-only) | Jira via MART MCP |
| Output JSON file | Pulse SMTP reply to the bug reporter |
| `data/tickets.db` (SQLite) | MySQL on Flipkart PaaS |
---

## Design constraints

These are deliberate product decisions, not limitations:

1. **No auto-write to Jira.** The agent produces a draft only. A human
   files the actual ticket.
2. **No auto-merge duplicates.** The engineer verifies before linking two
   tickets.
3. **Read-only Jira access enforced in code.** `src/shared/jira_client.py`
   has no create, edit, or transition methods.
4. **Human in the loop, always.** When the report is vague or the image
   contradicts the text, the system refiles rather than producing a
   confident wrong answer.
5. **No P3 in the multi-agent pipeline.** Vague reports trigger a refile
   banner in the UI — the sub-agents are not asked to guess intent from
   incomplete inputs.
