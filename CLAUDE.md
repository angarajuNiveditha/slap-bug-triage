# SLAP Bug Triage Prototype — Claude Context

## What this project is

A prototype of an agentic bug triage system for **SLAP** (Shop Like A Pro —
Flipkart's GenAI conversational shopping app). It takes a raw bug report email
(as a .txt file), fetches real historical bugs from the FLIPPI Jira project,
finds duplicates, suggests an owner, scores severity, and outputs a
dev-ready Jira ticket draft as JSON.

**Three pipelines exist:**
- `run_multi_agent.py` — **primary**. Multi-agent (Astral host + 6 sub-agents: media, parser, form-consistency, embeddings, dedup, triage) running on Claude Code headless mode (`claude -p`). Accepts image attachments. No `ANTHROPIC_API_KEY` required. ~90–150 s per bug.
- `run_agent.py` — local simulation harness, fully rule-based (regex + TF-IDF + multi-layer keyword scorer). ~35 ms per bug. Text-only. Used for fast iteration and as a deterministic baseline.
- `main.py` — original Anthropic SDK design. Blocked on `ANTHROPIC_API_KEY`; kept as production-shape reference.

**Front-end:** `app.py` is a Streamlit UI with two input modes (pasted email **or** structured form: title / platform / summary / steps), a pipeline toggle, an `st.file_uploader` for image / video attachments, and editable Priority / Component / Owner widgets so the reviewer can override the model's choices before downloading the Jira draft JSON. The multi-agent pipeline reads attached media via the media sub-agent. Run with `streamlit run app.py` → `localhost:8501`.

**This is a prototype only. It never writes to Jira. All Jira access is read-only.**

---

## Project structure

```
slap-bug-triage/
├── app.py                    # Streamlit UI — pipeline toggle + image uploader
├── run_multi_agent.py        # PRIMARY: multi-agent pipeline (Claude, no API key)
├── run_agent.py              # Local simulation harness: rule-based (no API key)
├── main.py                   # Anthropic SDK pipeline (needs ANTHROPIC_API_KEY) — blocked
├── TRIAGE_LOGIC.md           # PM-style report on rule-based logic
├── CLAUDE_PIPELINE_REPORT.md # PM-style report on the Claude pipeline
│
├── slap_context/                  # SLAP domain knowledge for the media sub-agent
│   ├── SLAP_KNOWLEDGE.md          # screen catalog, vocabulary, visual triage cues
│   └── reference_screens/         # labeled Figma exports (gitignored — design IP)
│
├── src/
│   │
│   │  ── Multi-agent pipeline (run_multi_agent.py uses these) ──
│   ├── agents/
│   │   ├── host_agent.py            # Astral — coordinates sub-agents
│   │   ├── subagent_media.py        # images → SLAP-aware findings
│   │   ├── subagent_parser.py       # email + media → BugReport
│   │   ├── subagent_form_consistency.py  # form-only: are title/summary/steps the same bug?
│   │   ├── subagent_embeddings.py   # rank top-K similar past bugs
│   │   ├── subagent_dedup.py        # final duplicate decision (≥ 0.80 conf)
│   │   └── subagent_triage.py       # priority assignment (3-tier: P0/P1/P2)
│   ├── claude_cli.py            # subprocess wrapper around `claude -p`
│   │
│   │  ── Rule-based simulation harness (run_agent.py uses these) ──
│   ├── agent_parser.py          # email → BugReport via regex + heuristics
│   ├── agent_scorer.py          # multi-layer priority scorer
│   ├── tfidf_similarity.py      # TF-IDF cosine similarity (scikit-learn)
│   │
│   │  ── Shared (used by both Claude and rule-based) ──
│   ├── agent_ticket_builder.py  # ADF ticket builder
│   ├── jira_client.py           # read-only Jira REST v3 wrapper
│   │
│   │  ── Anthropic SDK pipeline (main.py — blocked) ──
│   ├── parser.py                # Anthropic SDK → BugReport
│   ├── severity_scorer.py       # Anthropic SDK → SeverityResult
│   ├── similarity.py            # sentence-transformers similarity engine
│   └── ticket_builder.py        # ADF ticket builder (original)
│
├── data/                      # Input bug report emails (.txt files)
│   ├── bug_with_media/                     # multi-modal test bugs (folders)
│   │   ├── bug_m01_checkout_crash_screenshot/   # email.txt + screenshot1.png
│   │   ├── bug_m02_vton_wrong_persona/          # VTON gender mismatch
│   │   └── bug_m03_cart_empty_price/            # vague email + cart screenshot
│   ├── bug_report.txt                     # original sample (cart freeze)
│   ├── bug_01_p0_checkout_crash.txt       # P0: checkout crash, all Android users
│   ├── bug_02_p1_search_wrong_results.txt # P1: AI ignores price constraints
│   ├── bug_03_p2_image_not_loading.txt    # P2: images broken on slow network
│   ├── bug_04_duplicate_of_bug_report.txt # P2: add-to-cart broken
│   ├── bug_05_vague_minimal_info.txt      # P3: vague report, no details
│   ├── bug_dup_FLIPPI3044_secrets.txt     # duplicate of real FLIPPI-3044
│   ├── bug_dup_FLIPPI2905_dedup.txt       # duplicate of real FLIPPI-2905
│   ├── bug_dup_FLIPPI2902_auth.txt        # duplicate of real FLIPPI-2902
│   ├── bug_comp_immersive.txt             # component test: Immersive (ANR in VTO SDK)
│   ├── bug_comp_belabs.txt                # component test: BE_Labs (VTON gender mismatch)
│   ├── bug_comp_ds.txt                    # component test: DS (NPS discrepancy)
│   ├── bug_comp_ui.txt                    # component test: UI (iOS cold start flash)
│   ├── bug_comp_belippi.txt               # component test: BE_Flippi (price filter ignored)
│   └── bug_comp_unclassified.txt          # component test: bugs/unclassified (vague)
│
├── tests/                     # 15 paired tests for mentor review (.txt + .json + _claude.json)
│   ├── _build.py              # generator: extracts triage_notes from output/ into tests/
│   ├── _run_claude.py         # generator: runs the Claude pipeline on every test
│   └── test 1/ ... test 15/   # one folder per test (input + both pipelines' triage_notes)
│
├── output/                    # Rule-based pipeline outputs (gitignored)
├── output_claude/             # Claude pipeline outputs (gitignored)
├── .env                       # Secrets — never commit
├── .env.example               # Template for .env
└── requirements.txt
```

---

## How to run

```bash
# Install dependencies (first time only)
pip3 install -r requirements.txt

# ── Multi-agent pipeline (PRIMARY — Claude, no API key) ──────────────────
# Requires the Claude Code CLI installed and logged in on this machine.
python3 run_multi_agent.py                                  # all text bugs + bug_with_media/* folders
python3 run_multi_agent.py data/bug_01_p0_checkout_crash.txt
python3 run_multi_agent.py data/bug_with_media/bug_m01_checkout_crash_screenshot
# Output → output_claude/ticket_<label>_<timestamp>.json

# ── Rule-based simulation harness (fast, deterministic, no API key) ──────
python3 run_agent.py                                        # all data/*.txt
python3 run_agent.py data/bug_01_p0_checkout_crash.txt
# Output → output/ticket_<stem>_<timestamp>.json

# ── Streamlit front-end (pipeline toggle + image uploader) ───────────────
streamlit run app.py
# Opens at http://localhost:8501. First load fetches 300 Jira bugs (~5s).

# ── Regenerate the tests/ folder for mentor review ───────────────────────
python3 tests/_build.py        # rule-based triage_notes → tests/test N/*.json
python3 tests/_run_claude.py   # multi-agent triage_notes → tests/test N/*_claude.json
```

---

## Environment variables (.env)

```
JIRA_EMAIL=angaraju.v@flipkart.com
JIRA_TOKEN=<flipkart atlassian API token>
JIRA_BASE_URL=https://flipkart.atlassian.net
JIRA_PROJECT=FLIPPI
ANTHROPIC_API_KEY=             # only needed for main.py, not run_agent.py
```

**Jira token**: Created, token name: `GetJiraInfo_APItoken`.
Verified working against `flipkart.atlassian.net` on 2026-06-10.

**Anthropic API key**: Pending — `console.anthropic.com` is blocked on Flipkart
network. Only required for `main.py` (the Anthropic SDK pipeline).
**Neither `run_agent.py` nor `run_claude_agent.py` need it** — the Claude pipeline
authenticates via the locally signed-in Claude Code session instead.

---

## Agent pipeline steps (run_agent.py)

```
bug_report.txt (input)
    ↓
[Step 0]  Verify Jira credentials (whoami)
[Step 1]  Read raw text from file
[Step 2]  agent_parser.py → extract BugReport via regex + heuristics (no API)
[Step 3]  jira_client.py → fetch 300 recent FLIPPI bugs (READ ONLY)
[Step 4]  tfidf_similarity.py → build TF-IDF index over 300 bugs
[Step 5]  Cosine similarity → top-5 similar bugs
              → duplicate flag if TF-IDF similarity > 0.38
              → owner suggestion from assignee frequency
[Step 6]  agent_scorer.py → multi-layer priority scoring (no API):
              L1 keyword signals  (crash, ANR, revenue, scope, Grayskull...)
              L2 TF-IDF templates (paraphrase matching, 40 template sentences)
              L3 weighted similar-bug voting (sim-weighted priority average)
              L4 impact-text fallback
[Step 7]  agent_ticket_builder.py → assemble ADF Jira JSON draft
[Step 8]  Write output/ticket_<stem>_<timestamp>.json
```

---

## Output JSON structure

```json
{
  "generated_at": "...",
  "input_file": "data/bug_01_p0_checkout_crash.txt",
  "pipeline": "agent (no API key)",
  "parsed_bug": {
    "title": "[Checkout]: ...",
    "platform": "Android",
    "app_version": "2.4.2",
    "component_hint": "Backend",
    "reproducibility": "100%",
    "reporter": "Rahul Verma <rahul.verma@flipkart.com>"
  },
  "jira_ticket_draft": {
    "fields": {
      "project": {"key": "FLIPPI"},
      "issuetype": {"id": "10036"},
      "summary": "...",
      "priority": {"id": "10000"},
      "description": { ...ADF... },
      "components": [{"name": "Backend"}],
      "labels": ["slap", "agentic-triage", "be-flippi", "android"],
      "customfield_10331": {"value": "Blocker"}
    }
  },
  "triage_notes": {
    "team": "BE_Flippi",
    "jira_component": "Backend",
    "priority_scoring_path": "L1-keyword: app crash(?:es|ed)\\b",
    "severity_justification": "...",
    "owner_suggestion": "Shailja Rani",
    "owner_reason": "...",
    "duplicate_of": null,
    "duplicate_confidence": 0.0,
    "similar_bugs": [
      {
        "key": "FLIPPI-1663",
        "url": "https://flipkart.atlassian.net/browse/FLIPPI-1663",
        "summary": "Checkout Page Price Discrepancy",
        "similarity": 0.181,
        "assignee": "Shailja Rani",
        "priority": "P0"
      }
    ]
  }
}
```

---

## Multi-layer priority scoring (agent_scorer.py)

Priority is decided by 4 layers; first confident signal wins:

### Layer 1 — Keyword signals
Regex patterns matched against `title + description + impact + actual_result + raw_text`.

| Bucket | Condition to fire | Effect |
|---|---|---|
| `P0_HARD` | Any single match | → P0 immediately |
| `P0_SOFT` + 100% repro | Any soft match AND reproducibility == "100%" | → P0 |
| `P1_HARD` | Any single match | → P1 |
| `P1_SOFT` ≥ 2 | Two or more soft matches | → P1 |
| `P2_SIGNALS` | Any match | → P2 |
| `P3_SIGNALS` or vague | Short report + no steps | → P3 |

Key P0 patterns: `app crashes`, `force kill`, `proceed to pay`, `grayskull`,
`all users`, `all \w+ users` (catches "all male users", "all iOS users"),
`login outage`, `complete outage`, `revenue-blocking`.

Key P1 patterns: `\banr\b`, `application not responding`, `price constraint`,
`wrong recommendation`, `ignores budget`, `trust in the ai`, `\d+% of users`.

**Crash detection is context-sensitive** — `\bcrash\b` alone won't fire.
Requires active-voice context (`app crashes`, `crashes to home`) to avoid
false-positives from "no crash logs".

### Layer 2 — Template scoring (paraphrase handling)
A TF-IDF vectorizer is fitted at import time over ~40 template sentences per
priority level. For a new bug, cosine similarity is computed against all templates
and the highest-scoring priority bucket (above its threshold) wins.

Thresholds: P0 ≥ 0.28, P1 ≥ 0.22, P2 ≥ 0.18, P3 ≥ 0.15.

Example: "The NPS score shows different values than the FK main app" has no
keyword match but scores 0.52 against P1 templates → classified P1 correctly.

### Layer 3 — Weighted similar-bug voting
All similar bugs with `similarity ≥ 0.20` cast a weighted priority vote.
Priority is converted to a number (P0=0 … P4=4), multiplied by similarity score,
averaged, and converted back. Fires only when total weight ≥ 0.25.

### Layer 4 — Impact-text fallback
Last resort: scans the `Impact:` field for keywords like `blocking`, `revenue`,
`significant`, `majority`, `subset`, `workaround`. Defaults to P2.

### scoring_path field
Every ticket's `triage_notes.priority_scoring_path` shows exactly which layer
and signal decided the priority. Useful for debugging and tuning.

| Prefix | Meaning |
|---|---|
| `L1-keyword` | A specific regex matched |
| `L1-soft` | A soft keyword matched |
| `L1-duplicate` | Priority inherited from a near-duplicate ticket |
| `L1-vague` | Report was too short/sparse |
| `L2-template` | TF-IDF template similarity decided |
| `L3-similar-weighted` | Weighted vote from similar bugs |
| `L4-impact-fallback` | Last-resort impact text scan |

---

## Multi-agent pipeline (run_multi_agent.py)

A host agent (Astral, `src/agents/host_agent.py`) coordinates five sub-agents.
Each sub-agent is a focused Claude prompt with one responsibility. The
host calls them in this order:

```
bug input (email OR structured form + optional images / videos)
    │
    ▼
[1] subagent_media           — only if attachments present
    │     ↳ one-line summary folded into the email body
    ▼
[2] subagent_parser          — email + media findings → BugReport
    │
    ▼
[2b] subagent_form_consistency — only if from_form=True
    │                             refile if title/summary/steps mismatch
    ▼
[3] subagent_embeddings      — 300 historical Jira bugs + new bug → top-K ranked
    │                          candidates + suggested owner
    ▼
[4] subagent_dedup           — focused dup/no-dup decision over the top-K
    │                          (only fires if confidence ≥ 0.80)
    ▼
[5] subagent_triage          — BugReport + similar bugs → SeverityResult
    │                          3-tier ladder: P0 / P1 / P2
    ▼
agent_ticket_builder         — assembles Jira ADF + triage_notes JSON
    │
    ▼
human override (UI)          — reviewer edits Priority / Component / Owner;
                              audit trail recorded in triage_notes.human_overrides
```

### Media sub-agent (images)

`src/agents/subagent_media.py`. Loads `slap_context/SLAP_KNOWLEDGE.md` and the
labeled `slap_context/reference_screens/` PNGs, then calls `claude -p` with
`--add-dir` so Claude can `Read` each bug attachment as a multimodal input.
Per image it returns: screen label, state, visible text, UI anomalies,
device hints, triage signals (likely component + severity hint +
*contradicts_email_claim*), and a one-line summary.

The combined summary is folded into the email body before the parser runs, so
every downstream stage sees the visual evidence without handling images itself.

### Why split embeddings and dedup

The production diagram has them as separate sub-agents. The split makes the
duplicate decision independently auditable (you can see Claude's dedup
reasoning in `triage_notes.duplicate_reasoning`) and lets us tune the
0.80 confidence threshold without touching the ranking step.

### How Claude Code headless mode works

`src/claude_cli.py` wraps
`subprocess.run(["claude", "-p", prompt, "--output-format", "json"])`. The
wrapper now supports `add_dirs=[...]` (for granting Read access to image
attachments) and `allowed_tools=[...]`. No `ANTHROPIC_API_KEY` is needed —
the CLI uses the local Claude Code session's authentication.

### Why this beats lexical similarity on hard cases

Example: `bug_01_p0_checkout_crash` (Android, "Proceed to Pay" crash):
- **TF-IDF top match**: FLIPPI-1663 *Checkout Page Price Discrepancy*
  (sim 0.18) — matched on the word "checkout."
- **Multi-agent top match**: FLIPPI-1198 *[iOS] App crashing on "continue
  to payment"* (sim 0.85, flagged duplicate) — matched on the failure mode,
  spotting the iOS↔Android parallel.

Example: `bug_m03_cart_empty_price` (vague email "checkout is broken" +
cart-full-view screenshot). The media sub-agent identifies the cart screen,
notices currency-symbol rendering anomalies the email never mentioned, and
routes to UI / P2 — overriding the user's incorrect "checkout" framing.

### Trade-offs

| | Rule-based (simulation) | Multi-agent (primary) |
|---|---|---|
| Per-bug latency | ~35 ms | ~90–150 s |
| Cost | $0 (local CPU) | ~$0.20–$0.40 (Claude inference) |
| Determinism | Yes | No — small variations across runs |
| Reads images / audio / video | No | Images today; audio/video planned |
| Handles paraphrases / synonyms | Only what's in the keyword/template list | Yes |
| Brittle to format changes | Yes (regex) | No (LLM adapts) |

---

## Component classification (6 teams)

`_extract_component` in `agent_parser.py` classifies each bug into one of:

| Team label | Jira component | Jira ID | Owns |
|---|---|---|---|
| BE_Flippi | `Backend` | 14386 | Chat AI, search, cart, checkout, price, session, auth, onboarding, infra |
| BE_Labs | `Backend-Labs` | 14385 | VTON, Feed ML, Social Finds, Review Synth, Machine Identity, Decoded Looks |
| DS | `DS` | 14384 | NPS, %Positive, product page analytics, model quality, ranking |
| UI | `UI` | 14383 | React Native, iOS/Android rendering, images, login screen, cold start, styling |
| Immersive | `immersive` | 14387 | Native AR, VTO SDK, ANRs, drishyamukh-core |
| bugs | *(no component)* | — | Unclassifiable — needs manual routing |

Classification uses priority-ordered keyword matching. When `"bugs"` is returned,
no Jira `components` field is set on the ticket. The team label is always written
to `triage_notes.team`.

---

## Similarity engine (tfidf_similarity.py)

Replaces `sentence-transformers` (no GPU/download required).

- **Vectorizer**: TF-IDF bigrams, 10k features, sublinear TF
- **Index**: built over `summary + description` of 300 real FLIPPI bugs
- **Duplicate threshold**: cosine similarity ≥ 0.38
- **Similar threshold**: cosine similarity ≥ 0.12
- **Top-K**: 5 matches returned
- **Each similar bug includes**: key, summary, similarity score, assignee, priority, clickable URL

---

## Jira details (FLIPPI project)

- **Base URL**: https://flipkart.atlassian.net
- **Cloud ID**: `ba691f9e-703c-4694-be8e-2a532386325d`
- **Project key**: FLIPPI (name: SLAP)
- **Project ID**: 11206
- **Board**: "SLAP Planned" (scrum, board ID 2247)
- **Bug issue type ID**: 10036
- **Auth**: HTTP Basic — email:token
- **Search endpoint**: POST /rest/api/3/search/jql (v3)
- **Read-only guardrail**: `jira_client.py` has NO write methods.

### Jira component IDs (verified 2026-06-11):
| Component | ID |
|---|---|
| Backend | 14386 |
| Backend-Labs | 14385 |
| DS | 14384 |
| UI | 14383 |
| immersive | 14387 |
| Design | 14382 |
| Product | 14388 |
| SLAP_PRODUCT | 14389 |

### Real FLIPPI bugs used in test data (verified 2026-06-10):
- FLIPPI-3044: "Grayskull Integration for Secrets in Edison" — P0, component: Backend
- FLIPPI-2905: "Add product family dedup in journey continuation search results" — P0, assignee: Saumya Chauhan, component: Backend
- FLIPPI-2902: "Getting 'Failed to verify' on authenticating with credentials: 7087935097" — P3, assignee: Saumya Chauhan, no component

---

## Production mapping

| Agent prototype | Production (Flipkart PaaS) |
|---|---|
| bug report `.txt` | Gmail email via fk-mart-ai-pulse |
| `run_agent.py` direct calls | Synapse (auth/routing) |
| Python script | Astral (agent runtime) |
| `agent_parser.py` rule-based | Genvoy / FK-GPT (LLM parsing) |
| `tfidf_similarity.py` | Vector One (managed vector DB) |
| `agent_scorer.py` rule-based | Genvoy / FK-GPT (LLM scoring) |
| Jira REST API (read) | Jira via MART MCP |
| output JSON | Pulse SMTP reply to reporter |

Swapping prototype → production is a one-line change per component.
All business logic (dedup logic, component routing, ADF structure) stays the same.

---

## Key constraints (from team design decisions)

1. **No auto-write to Jira** — agent produces draft only; human files the ticket
2. **No auto-merge duplicates** — engineer verifies before linking
3. **Human in the loop always** — deliberate design decision, not a limitation
4. **Read-only Jira access** — `jira_client.py` enforces this; no create/edit/transition methods

---

## Dependencies

```
requests>=2.31.0              # Jira REST API calls
python-dotenv>=1.0.0          # .env loading
numpy>=1.26.0                 # similarity math
scikit-learn>=1.9.0           # TF-IDF vectorizer + cosine similarity
streamlit>=1.32.0             # front-end UI (app.py)
anthropic>=0.25.0             # only needed for main.py (Anthropic SDK pipeline)
sentence-transformers>=2.7.0  # only needed for main.py (original similarity.py)
```

Install minimal set: `pip3 install requests python-dotenv numpy scikit-learn streamlit`
(`anthropic` + `sentence-transformers` only needed for `main.py`)

External dependency: `run_claude_agent.py` and the Claude toggle in `app.py`
also require the **Claude Code CLI** to be installed and authenticated on
this machine (`which claude` should return a path).

---

## Current status (as of 2026-06-25)

- `run_multi_agent.py` fully working end-to-end. The pipeline now mixes Claude
  (media / parser / form-consistency / dedup / owner / triage) with local ML
  (embedding classifier + cosine similarity engine). Latency dropped to
  ~50–90 s per bug.
- `run_agent.py` rule-based simulation harness still fully working (~35 ms/bug)
- `app.py` Streamlit UI: input-format toggle, pipeline toggle, media uploader,
  editable Priority/Component/Owner widgets with audit trail, **ambiguity banner**
  showing full probability distribution when LogReg confidence < 0.50, and
  override → `corrections.csv` writer for active learning
- Triage ladder is 3-tier (P0 / P1 / P2 — no P3). Vague reports → refile.
- **Component classifier: hybrid LogReg + Claude+skills fallback.**
  - LogReg trained on 564 component-labelled FLIPPI bugs (sentence-transformer
    embeddings, class_weight balanced). Fast path: ~7 ms when top-class prob ≥ 0.50.
  - Borderline cases (35.8%) fall back to Claude with the top-3 candidate
    teams' architecture skill files loaded as in-context evidence.
  - Measured **69.5% LOO accuracy** on 564 bugs. Projected 78–82% after
    backend label cleanup (see audit findings below).
- **Architecture skill files** at `slap_context/architecture/` — 5 team skills
  (hand-curated) + 8 of 11 per-repo skills (6 auto-generated from real clones via
  `build_repo_skills.py`, 2 hand-written by team leads with routing-signals tables)
- **Backend label-noise audit finding:** ~70% of misclassified Backend bugs
  are mis-labelled in Jira (chat-AI / relevance complaints filed against Backend
  that should be DS; visual bugs that should be UI; Social Finds / Q2P bugs that
  should be BE_Labs). The single highest-leverage improvement is relabelling.
- **Active learning loop:** UI overrides → `corrections.csv` → next index rebuild.
- **GitHub Enterprise integration** via `src/repo_context.py` (clone + structural
  map + `git grep` fallback) — gated on `GITHUB_FK_TOKEN`. 4 SLAP repos cloned locally
  (edison + dropsense + FaceNet + slap-auto-qc-pipeline + slap-feed branch +
  social-finds-pipeline branch).
- Form-consistency sub-agent flags title/summary/steps mismatches when
  `from_form=True`; multi-agent path uses Claude, rule-based has a conservative
  word-overlap heuristic fallback
- `slap_context/SLAP_KNOWLEDGE.md` extracted from the SLAP-2026 Figma file
  (393 frames, 198 unique screen names, 1117 unique strings)
- `slap_context/reference_screens/` holds 16 labeled Figma PNGs — gitignored
  (unreleased design IP); media sub-agent loads them at runtime via `--add-dir`
- 3 multi-modal test bugs under `data/bug_with_media/` (PNGs gitignored;
  email.txt files committed)
- Jira token verified, 300 real FLIPPI bugs fetched successfully
- 15 text test bugs covering all priority levels and all 6 team components
- `TRIAGE_LOGIC.md` documents the rule-based logic
- `CLAUDE_PIPELINE_REPORT.md` documents the Claude pipeline
- Git repo committed and pushed to GitHub
- `main.py` (Anthropic SDK pipeline) still blocked on `ANTHROPIC_API_KEY`
