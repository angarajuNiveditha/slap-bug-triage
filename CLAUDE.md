# SLAP Bug Triage Prototype — Claude Context

## What this project is

A prototype of an agentic bug triage system for **SLAP** (Shop Like A Pro —
Flipkart's GenAI conversational shopping app). It takes a raw bug report email
(as a .txt file), fetches real historical bugs from the FLIPPI Jira project,
finds duplicates, suggests an owner, scores severity, and outputs a
dev-ready Jira ticket draft as JSON.

**Three pipelines exist:**
- `run_agent.py` — **fully working today**, no Anthropic API key needed. Uses rule-based parsing, TF-IDF similarity, and multi-layer scoring. ~35 ms per bug.
- `run_claude_agent.py` — **also fully working today**, no API key needed. Uses Claude Code in headless mode (`claude -p`) for all three stages (parse, semantic similarity over 300 bugs, severity reasoning). Authenticates via the local Claude Code session. ~50–90 s per bug.
- `main.py` — original design using the Anthropic Python SDK. Blocked until `ANTHROPIC_API_KEY` is provided; kept for reference / production swap.

**Front-end:** `app.py` is a Streamlit UI that wraps both working pipelines with a side-by-side toggle. Run with `streamlit run app.py` → `localhost:8501`.

**This is a prototype only. It never writes to Jira. All Jira access is read-only.**

---

## Project structure

```
slap-bug-triage/
├── app.py                    # Streamlit UI — runs either pipeline with a toggle
├── run_agent.py              # Rule-based pipeline (no API key)
├── run_claude_agent.py       # Claude Code headless pipeline (no API key)
├── main.py                   # Anthropic SDK pipeline (needs ANTHROPIC_API_KEY) — blocked
├── TRIAGE_LOGIC.md           # PM-style report of the triage logic, for mentor review
│
├── src/
│   │
│   │  ── Rule-based pipeline (run_agent.py) ──
│   ├── agent_parser.py        # email → BugReport via regex + heuristics
│   ├── agent_scorer.py        # multi-layer priority scorer
│   ├── tfidf_similarity.py    # TF-IDF cosine similarity (scikit-learn)
│   ├── agent_ticket_builder.py # ADF ticket builder (shared by Claude pipeline too)
│   │
│   │  ── Claude Code headless pipeline (run_claude_agent.py) ──
│   ├── claude_cli.py          # subprocess wrapper around `claude -p`
│   ├── claude_parser.py       # email → BugReport via Claude
│   ├── claude_similarity.py   # 300 bugs + new bug → similar bugs (replaces TF-IDF)
│   ├── claude_scorer.py       # bug + similar → SeverityResult via Claude
│   │
│   │  ── Anthropic SDK pipeline (main.py — blocked) ──
│   ├── parser.py              # Anthropic SDK → BugReport
│   ├── severity_scorer.py     # Anthropic SDK → SeverityResult
│   ├── similarity.py          # sentence-transformers similarity engine
│   ├── ticket_builder.py      # ADF ticket builder (original)
│   │
│   └── jira_client.py         # Shared: read-only Jira REST v3 wrapper
│
├── data/                      # Input bug report emails (.txt files)
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

# ── Rule-based pipeline (fast, deterministic, no API key) ─────────────────
python3 run_agent.py                                       # all data/*.txt
python3 run_agent.py data/bug_01_p0_checkout_crash.txt     # specific file
# Output → output/ticket_<stem>_<timestamp>.json

# ── Claude Code headless pipeline (semantic, no API key) ─────────────────
# Requires the Claude Code CLI installed and logged in on this machine.
python3 run_claude_agent.py                                # all data/*.txt (~15 min total)
python3 run_claude_agent.py data/bug_01_p0_checkout_crash.txt
# Output → output_claude/ticket_<stem>_<timestamp>.json

# ── Streamlit front-end (both pipelines, side-by-side toggle) ────────────
streamlit run app.py
# Opens at http://localhost:8501. First load fetches 300 Jira bugs (~5s).

# ── Regenerate the tests/ folder for mentor review ───────────────────────
python3 tests/_build.py        # rule-based triage_notes → tests/test N/*.json
python3 tests/_run_claude.py   # Claude triage_notes → tests/test N/*_claude.json
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

## Claude Code headless pipeline (run_claude_agent.py)

Same 8-step shape as `run_agent.py`, but the three "intelligence" stages are
replaced by Claude Code calls (`claude -p`) instead of rule-based code:

| Stage | Rule-based module | Claude Code module |
|---|---|---|
| Parse email → BugReport | `agent_parser.py` (regex) | `claude_parser.py` |
| Find similar past bugs | `tfidf_similarity.py` (TF-IDF cosine) | `claude_similarity.py` |
| Score severity | `agent_scorer.py` (multi-layer) | `claude_scorer.py` |

`jira_client.py` and `agent_ticket_builder.py` are reused unchanged. The
outputs land in `output_claude/` (gitignored) with the same JSON shape as
`output/`, except `pipeline` is `"claude-code-headless"`.

### How the headless mode works

`src/claude_cli.py` wraps `subprocess.run(["claude", "-p", prompt, "--output-format", "json"])`:

1. Spawns the `claude` CLI in non-interactive mode (no API key required —
   uses the local Claude Code session's authentication).
2. Parses the JSON envelope, extracts the `result` field.
3. Strips ```` ```json … ``` ```` fences (Claude often wraps JSON answers in
   markdown).
4. Parses the inner JSON and returns it to the caller.

Each subprocess call is independent — no shared session state across stages.

### Why Claude similarity beats TF-IDF on hard cases

The Claude similarity engine sends **all 300 historical bugs** as context
(~30k tokens) on every query, then asks Claude to rank them. This is slow
(~30–60s per query) but **semantically aware** in ways TF-IDF is not.

Example: `bug_01_p0_checkout_crash` (Android, "Proceed to Pay" crash):
- **TF-IDF top match**: FLIPPI-1663 *Checkout Page Price Discrepancy* (sim 0.18) — matched on the word "checkout."
- **Claude top match**: FLIPPI-1198 *[iOS] App crashing on "continue to payment"* (sim 0.85, flagged duplicate) — matched on the failure mode (crash on the pay button), and made the iOS↔Android parallel TF-IDF couldn't.

Trade-off summary:

| | Rule-based | Claude Code |
|---|---|---|
| Per-bug latency | ~35 ms | ~50–90 s |
| Cost | $0 (local CPU) | ~$0.15 (Claude inference) |
| Determinism | Yes — same input → same output | No — small variations across runs |
| Handles paraphrases / synonyms | Only what's in the keyword/template list | Yes — reads meaning |
| Brittle to format changes | Yes (regex-based) | No (LLM adapts) |

For demos and one-shot triage: Claude. For batch automated runs: rule-based.
The Streamlit UI lets you toggle between them on the same bug.

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

## Current status (as of 2026-06-15)

- `run_agent.py` fully working end-to-end (rule-based, ~35 ms/bug)
- `run_claude_agent.py` fully working end-to-end (Claude Code headless,
  ~50–90 s/bug, no API key required)
- `app.py` Streamlit UI with pipeline toggle, clickable Jira links, and
  4-tab result view (Summary / Triage notes / Raw JSON / Jira ADF)
- Jira token verified, 300 real FLIPPI bugs fetched successfully
- 15 test bug reports covering all priority levels (P0–P3) and all 6 team components
- Both pipelines have been run over the full 15-bug test suite; results saved
  side-by-side under `tests/test N/` as `<name>.json` (rule-based) and
  `<name>_claude.json` (Claude)
- Multi-layer scorer implemented: keywords → templates → weighted voting → fallback
- `TRIAGE_LOGIC.md` documents the rule-based logic for mentor review
- Git repo committed and pushed to GitHub
- `main.py` (Anthropic SDK pipeline) still blocked on `ANTHROPIC_API_KEY` —
  kept as the production-shape reference
