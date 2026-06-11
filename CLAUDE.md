# SLAP Bug Triage Prototype — Claude Context

## What this project is

A prototype of an agentic bug triage system for **SLAP** (Shop Like A Pro —
Flipkart's GenAI conversational shopping app). It takes a raw bug report email
(as a .txt file), fetches real historical bugs from the FLIPPI Jira project,
finds duplicates, suggests an owner, scores severity, and outputs a
dev-ready Jira ticket draft as JSON.

**Two pipelines exist:**
- `run_agent.py` — **fully working today**, no Anthropic API key needed. Uses rule-based parsing, TF-IDF similarity, and multi-layer scoring.
- `main.py` — original design using Claude API for parsing + scoring. Blocked until `ANTHROPIC_API_KEY` is provided.

**This is a prototype only. It never writes to Jira. All Jira access is read-only.**

---

## Project structure

```
slap-bug-triage/
├── run_agent.py             # PRIMARY: agent pipeline (no API key required)
├── main.py                  # ORIGINAL: Claude API pipeline (needs ANTHROPIC_API_KEY)
│
├── src/
│   │
│   │  ── Agent pipeline modules (run_agent.py uses these) ──
│   ├── agent_parser.py       # Rule-based email → BugReport extractor (regex + heuristics)
│   ├── agent_scorer.py       # Multi-layer priority scorer (keywords → templates → voting)
│   ├── tfidf_similarity.py   # TF-IDF cosine similarity engine (scikit-learn, no GPU)
│   ├── agent_ticket_builder.py # ADF ticket builder wired to agent modules
│   │
│   │  ── Original pipeline modules (main.py uses these) ──
│   ├── parser.py             # Claude API → BugReport
│   ├── severity_scorer.py    # Claude API → SeverityResult
│   ├── similarity.py         # sentence-transformers similarity engine
│   └── ticket_builder.py     # ADF ticket builder (original)
│   │
│   └── jira_client.py        # Shared: read-only Jira REST v3 wrapper
│
├── data/                     # Input bug report emails (.txt files)
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
├── output/                   # Generated ticket drafts (gitignored)
├── .env                      # Secrets — never commit
├── .env.example              # Template for .env
└── requirements.txt
```

---

## How to run

```bash
# Install dependencies (first time only)
pip3 install -r requirements.txt

# Run agent pipeline on ALL .txt files in data/
python3 run_agent.py

# Run on specific file(s)
python3 run_agent.py data/bug_01_p0_checkout_crash.txt
python3 run_agent.py data/bug_comp_immersive.txt data/bug_comp_ds.txt
```

Output written to `output/ticket_<input_stem>_<timestamp>.json`.

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
network. Only required if switching to `main.py`.

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
requests>=2.31.0        # Jira REST API calls
python-dotenv>=1.0.0    # .env loading
numpy>=1.26.0           # similarity math
scikit-learn>=1.9.0     # TF-IDF vectorizer + cosine similarity
anthropic>=0.25.0       # only needed for main.py (Claude API pipeline)
sentence-transformers>=2.7.0  # only needed for main.py (original similarity.py)
```

Install: `pip3 install requests python-dotenv numpy scikit-learn`
(anthropic + sentence-transformers not needed for `run_agent.py`)

---

## Current status (as of 2026-06-11)

- `run_agent.py` fully working end-to-end
- Jira token verified, 300 real FLIPPI bugs fetched successfully
- 15 test bug reports covering all priority levels (P0–P3) and all 6 team components
- Multi-layer scorer implemented: keywords → templates → weighted voting → fallback
- Clickable Jira URLs in all similar-bug results
- `scoring_path` field shows which layer decided every priority
- Git repo initialized and committed; pushed to GitHub
- `main.py` (Claude API version) ready but blocked on `ANTHROPIC_API_KEY`
