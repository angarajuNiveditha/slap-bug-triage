# SLAP Bug Triage — Project Documentation

A single-file guide to the project. Covers what it does, how it's built, how to run it, and what's left to improve.

---

## 1. What this is

A prototype of an **agentic bug-triage system** for **SLAP** (Shop Like A Pro — Flipkart's GenAI conversational shopping app).

The system takes a bug report — either a pasted email or a filled-in form, with optional screenshots / videos — and produces a dev-ready Jira ticket draft that includes:

- A priority (P0 / P1 / P2) with a plain-English justification
- A team / component assignment
- An owner suggestion based on who fixes similar bugs
- A duplicate detection result with confidence
- A list of the top-5 most similar past bugs from FLIPPI history

**Hard constraints (deliberate design choices):**

1. **Read-only Jira access.** The pipeline never creates, edits, or transitions a ticket. `jira_client.py` has no write methods.
2. **No auto-filing.** Every draft requires a human to review and file.
3. **Human in the loop, always.** Duplicate suggestions are not auto-merged. Owner suggestions are not auto-assigned.

These constraints aren't limitations — they're the product spec. The goal is to give a triage engineer a high-quality 80%-complete draft, not to remove them from the loop.

---

## 2. Three pipelines, one purpose

The repo carries three implementations of the same triage pipeline. They exist for different reasons:

| Pipeline | File | Runtime per bug | Cost | API key |
|---|---|---|---|---|
| **Multi-agent** (primary) | `run_multi_agent.py` | 90–150 s | ~$0.20–0.40 in Claude inference | None — uses local `claude` CLI |
| **Rule-based** (simulation) | `run_agent.py` | ~35 ms | $0 | None |
| **Anthropic SDK** (reference) | `main.py` | n/a | n/a | Blocked — `ANTHROPIC_API_KEY` unavailable on the Flipkart network |

**Why all three exist:**

- The **multi-agent** pipeline is what the production system would look like. Astral host coordinates six focused sub-agents (each a Claude prompt with one job), uses semantic reasoning, handles paraphrases, reads images and video keyframes. It is the primary pipeline.
- The **rule-based** pipeline is a fast deterministic baseline. It uses regex keyword matching, TF-IDF cosine similarity, and a multi-layer scorer. It's useful for fast iteration during development and as a numerical baseline to measure the multi-agent pipeline against.
- The **Anthropic SDK** pipeline is preserved as a reference for what the production-shape code looks like when the `ANTHROPIC_API_KEY` is available. It is currently blocked.

---

## 3. The multi-agent pipeline

The host agent (`src/agents/host_agent.py`, codenamed **Astral**) is a thin coordinator. It calls six sub-agents in sequence; each one is a focused Claude prompt:

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
    │                             refile if title/summary/steps don't match
    ▼
[3] subagent_embeddings      — top-K ranked similar bugs from 300 history
    │                          + suggested owner
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
                              audit trail in triage_notes.human_overrides
```

### Sub-agent responsibilities

| Sub-agent | File | What it does |
|---|---|---|
| **Media** | `subagent_media.py` | Reads attached images / video keyframes. Identifies the SLAP screen using `slap_context/SLAP_KNOWLEDGE.md` and `reference_screens/`. Extracts visible text, UI anomalies, error indicators, and triage signals (likely component, severity hint, *contradicts_email_claim*). Folds a one-line summary into the email body so downstream stages get visual evidence without handling pixels. |
| **Parser** | `subagent_parser.py` | Turns the email body (now enriched with media findings) into a structured `BugReport` — title, description, steps, expected/actual, impact, platform, reproducibility, reporter, and a `component_hint`. Uses a natural-language ladder for component classification. Explicitly told to prefer `bugs` over a wrong guess. |
| **Form consistency** | `subagent_form_consistency.py` | Only runs when `from_form=True`. Asks Claude whether the title, summary, and steps describe the same bug. If they don't (e.g. title about caching, summary about search routing, steps about login), returns a quality_issue that surfaces as a refile banner. |
| **Embeddings** | `subagent_embeddings.py` | Ranks the top-K most similar bugs from 300 historical FLIPPI tickets. Suggests an owner based on the assignee frequency of those top matches. |
| **Dedup** | `subagent_dedup.py` | Focused dup/no-dup decision over the top-K. Only flags a duplicate when confidence ≥ 0.80. Independent of the ranking step so the threshold can be tuned without touching ranking. |
| **Triage** | `subagent_triage.py` | Assigns a priority (P0 / P1 / P2) using the priorities of similar past bugs as the primary signal. Falls back to a hard-coded ladder when neighbours disagree. Hard overrides: 100% repro crash → P0, Grayskull / secrets / infra → P0. |

### How Claude headless mode works

`src/claude_cli.py` is a thin subprocess wrapper around `claude -p`, the Claude Code CLI. No `ANTHROPIC_API_KEY` is required — authentication is inherited from the local Claude Code session. The wrapper supports `add_dirs=[...]` (for granting Claude read access to image attachments) and `allowed_tools=[...]`.

This is the key engineering choice that makes the multi-agent pipeline runnable on Flipkart's network without API-key access.

---

## 4. The rule-based pipeline

A fully deterministic baseline using regex + TF-IDF + a multi-layer scorer.

```
bug_report.txt (input)
    ↓
[Step 0]  Verify Jira credentials (whoami)
[Step 1]  Read raw text
[Step 2]  agent_parser.py    — extract BugReport via regex + heuristics (no API)
[Step 3]  jira_client.py     — fetch 300 recent FLIPPI bugs (READ ONLY)
[Step 4]  tfidf_similarity   — build TF-IDF index over 300 bugs
[Step 5]  Cosine similarity  — top-5 similar bugs
                              → duplicate flag if TF-IDF similarity > 0.38
                              → owner suggestion from assignee frequency
[Step 6]  agent_scorer.py    — multi-layer priority scoring (no API):
                              L1: keyword regex signals (P0_HARD, P1_HARD, etc.)
                              L2: TF-IDF templates (paraphrase matching)
                              L3: weighted similar-bug voting
                              L4: impact-text fallback
[Step 7]  agent_ticket_builder.py → assemble ADF Jira JSON draft
[Step 8]  Write output/ticket_<stem>_<timestamp>.json
```

The rule-based pipeline is text-only — it doesn't read attachments and doesn't handle synonyms beyond what's been added to the keyword list. It is meant for **fast iteration during development** and **measurable accuracy benchmarking**, not production use.

---

## 5. Input modes

The Streamlit UI offers two input formats, picked from a radio at the top of Step 1:

### Email mode
Paste a raw email blob into a textarea. Optionally pre-fill from one of the sample `.txt` files in `data/`. This is the original input mode.

### Structured form mode
Fill four fields:
- **Bug title** (text input)
- **Platform** (dropdown: Android / iOS / Web / Android, iOS / Unknown)
- **Summary** (textarea)
- **Steps to reproduce** (textarea, one step per line, optional)

Plus optional screenshots / videos via the same uploader as email mode.

**How both modes converge:** `synthesize_email_from_form()` in `app.py` stitches the form values into an email-shaped string. Both modes feed the **same** `raw_text` into the pipeline, so zero changes are needed downstream. Form-supplied step numbering / bullets are stripped and renumbered cleanly.

**`from_form` flag:** when the user submits via form, the host pipeline gets `from_form=True`. This flag:
- Skips the `vague_report` quality check (form fields are short by design)
- Activates the form-consistency sub-agent (multi-agent path) or a heuristic word-overlap check (rule-based path)

---

## 6. Component classification

Bugs route to one of six teams. Each team owns a Jira component:

| Team label | Jira component | Jira ID | Owns |
|---|---|---|---|
| BE_Flippi | `Backend` | 14386 | Chat AI, search, cart, checkout, price, session, auth, onboarding, infra |
| BE_Labs | `Backend-Labs` | 14385 | VTON, Feed ML, Social Finds, Review Synth, Decoded Looks, Styledrops, Vibes, Cosmos, Moodboard |
| DS | `DS` | 14384 | NPS, %Positive, product page analytics, model quality, ranking, result relevance |
| UI | `UI` | 14383 | React Native, iOS/Android rendering, images, login screen, cold start, styling |
| Immersive | `immersive` | 14387 | Native AR, VTO SDK, ANRs, drishyamukh-core |
| bugs | *(no component)* | — | Unclassifiable — needs manual routing |

### Rule-based classifier — `src/agent_parser.py`

`_extract_component()` runs a **priority-ordered keyword waterfall**:

1. **immersive** (native AR / VTO SDK / drishyamukh / ANRs in native code)
2. **UI** (platform prefixes like `[iOS]` / `[Android]` / `[RN]`, visual / layout / spacing / alignment, touch interaction, native build issues, animation, "Show all / View more" UI controls)
3. **Backend-Labs** (VTON, Styledrops / styledrops with no space, Vibes Player, Cosmos, Moodboard, Liked Drops, reels ingestion)
4. **DS** (NPS, ranking quality, result relevance — "wrong results", "irrelevant", "less relevant", summary mismatches, model failures to answer, grounding, "showing tables")
5. **Backend** (chat AI, search, cart, checkout, payment, auth, OTP, sessions, Grayskull, Edison-when-not-in-Labs-context, infra, feed dedup, journey continuation, bot)
6. **bugs** (fallthrough — return when no team matches confidently)

**UI is checked before BE_Labs and DS** because platform-prefixed bugs (`[iOS]`, `[Android]`, `[RN]`) belong to UI even on BE_Labs surfaces (e.g. a Styledrops rendering bug tagged `[iOS]` is UI, not BE_Labs).

### Multi-agent classifier — `src/agents/subagent_parser.py`

The parser sub-agent's prompt contains a natural-language version of the same ladder, mirroring the rule-based vocabulary. It includes:
- Explicit ordering note: UI checked before BE_Labs / DS / Backend, and why
- Specific vocabulary for each team
- The explicit instruction: *"Prefer `bugs` over a wrong guess. Manual routing wastes less engineering time than mis-routing."*

### Accuracy

Validated against 300 real FLIPPI bugs on `flipkart.atlassian.net` (rule-based pipeline):

| Team | Before this iteration | After this iteration |
|---|---|---|
| Backend | 82% | 86% |
| Backend-Labs | 51% | 81% |
| DS | 4% | 78% |
| UI | 7% | 70% |
| **Overall** | **43%** | **78.7%** |

The improvement came from three things:
1. Keyword vocabulary expansion (Styledrops no-space, Vibes / Cosmos / Moodboard, `[iOS]`/`[Android]`/`[RN]` prefixes, visual / interaction / animation terms, DS-specific relevance vocabulary)
2. Waterfall reorder so UI is checked before BE_Labs / DS / Backend
3. Removing keywords that were too aggressive and stealing bugs from neighbouring teams

The remaining 21% mismatch is largely cases where the meaning is clear to a human reader but the exact keywords aren't there — e.g. a UI bug worded entirely in backend vocabulary, or a BE_Labs bug that uses generic phrasing matching Backend's `edison` / `logs` keywords. See *§12 Recommendations* below for paths to push past 78.7%.

The multi-agent classifier has been aligned with the same vocabulary but **has not yet been measured against the same 300-bug corpus**.

---

## 7. Triage ladder

3-tier classification. The primary signal is the priorities of similar past bugs; the ladder is only consulted when neighbours disagree or are weak matches.

### Priorities

**P0 — Critical, needs immediate hotfix.** Any of:
- App crash
- ANR (Application Not Responding)
- Payment failed or blocked
- Security or secrets risk
- User blocked / user loop / cannot make progress
- Revenue-blocking
- Major UI/UX breaking (user cannot use the affected feature at all)

**P1 — Significant, ship soon.** Any of:
- UI/UX improvements (not blocking but visibly wrong)
- Price / budget ignored / wrong
- Text or copy changes
- Image loading issues
- Network interruptions
- Error messages (missing, misleading, or wrong)
- Tooltips
- Toast notifications

**P2 — Low scope, low severity.** Minor edge cases.

### Hard overrides (win regardless of similar-bug consensus)
- A 100%-reproducible crash is **always** P0
- Any Grayskull / secrets / infra concern is **always** P0

### Why no P3
Vague reports used to drop to P3 by default. They now route to **"Insufficient info — refile"** instead. The information value of the P3 bucket was low; an explicit refile prompt is more useful for the reporter.

### Rule-based scoring path

The rule-based pipeline (`src/agent_scorer.py`) uses a four-layer scorer; first confident signal wins:

| Layer | What it does | Threshold |
|---|---|---|
| L1 — Keyword regex | Hard-coded regex against title/description/impact/actual_result/raw_text | First match wins |
| L2 — TF-IDF templates | Cosine similarity against ~40 template sentences per priority bucket | P0 ≥ 0.28, P1 ≥ 0.22, P2 ≥ 0.18 |
| L3 — Weighted similar-bug voting | Average priority of matches with sim ≥ 0.20, weighted by similarity | Total weight ≥ 0.25 |
| L4 — Impact text fallback | Scans the `Impact:` field for revenue / blocking / scope keywords | Defaults to P2 |

Every ticket records `triage_notes.priority_scoring_path` showing which layer and signal decided the priority — useful for debugging and tuning.

---

## 8. Quality gates

Three kinds of issues can flag a bug for refile. The UI surfaces them as a refile banner with per-issue cards; if any issue is present, the metric tiles and edit widgets are not rendered.

| Issue | When it fires | Detection |
|---|---|---|
| `vague_report` | Email mode only. Report is missing required section headers (Impact, Reproducibility, Environment, etc.) or under the text-length threshold. | Regex-based section detection in `detect_quality_issues()` in `host_agent.py`. Skipped when `from_form=True`. |
| `form_fields_inconsistent` | Form mode only. Title, summary, and steps describe different bugs. | Multi-agent: `subagent_form_consistency.py` asks Claude. Rule-based: heuristic in `app.py` — flags only when title has ≥ 6 content words **and** summary has ≥ 6 content words **and** title shares zero content words with summary **and** zero with steps. |
| `media_contradicts_text` | Both modes. An attached image's media-agent findings disagree with the email body / form text. | Media sub-agent populates `contradicts_email_claim` per image; host folds these into quality_issues. |

---

## 9. Editable outputs

Below the metric tiles, the reviewer can override the model's choices:

- **Priority** — dropdown (P0 / P1 / P2), defaulted to the model's prediction
- **Component** — dropdown (Backend / Backend-Labs / DS / UI / immersive / bugs), defaulted to the model's prediction
- **Owner** — free text input, defaulted to the model's suggested owner (free text so any engineer can be assigned, not just historically-frequent ones)

Help text under each widget restates the model's prediction so the reviewer always sees what they're overriding.

### What gets patched on edit

- `draft.triage_notes` — `team`, `jira_component`, `owner_suggestion`, `priority`, `severity`
- `draft.jira_payload["fields"]` — `priority.id`, `customfield_10331.value` (Severity), `components[]` with verified FLIPPI component IDs (removed entirely for `bugs`)

### Audit trail

Any field that differs from the model's prediction is recorded in `triage_notes.human_overrides`:

```json
{
  "priority":  {"from": "P1", "to": "P0"},
  "component": {"from": "Backend", "to": "UI"},
  "owner":     {"from": "Shailja Rani", "to": "Samiksha"}
}
```

Downstream readers can tell at a glance which fields were reviewer-corrected vs. model-predicted.

### Why the result is stashed in `st.session_state`

Every Streamlit widget interaction triggers a full script re-run during which the "Triage" button is False. Without persistence the result would disappear the moment the reviewer touched a dropdown. The triage result is therefore stashed in `st.session_state.triage_result` after the pipeline finishes; the render block reads from there. Refile and a fresh Triage both clear the stash.

---

## 10. Front-end (Streamlit)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Hero: SLAP Bug Triage                                                   │
├──────────────────┬──────────────────────────────────────────────────────┤
│ Pipeline rail    │ Step 1 · Bug report                                  │
│ (vertical):      │                                                      │
│  • Input         │ [Input format: Email | Structured form]              │
│  • Media         │ [Pipeline:     Multi-agent | Rule-based]             │
│  • Parser        │                                                      │
│  • Embeddings    │ ┌── Email mode ──┐  OR  ┌── Form mode ──┐            │
│  • Dedup         │ │ [Sample picker] │     │ Bug title     │            │
│  • Triage        │ │ [Email textarea]│     │ Platform ▼    │            │
│  • Output        │ └─────────────────┘     │ Summary       │            │
│                  │                         │ Steps         │            │
│                  │                         └───────────────┘            │
│                  │                                                      │
│                  │ [📎 Attach screenshots or videos]                    │
│                  │ [Triage this bug]                                    │
│                  │                                                      │
│                  │ Step 2 · Result                                      │
│                  │ ┌──────┬──────┬──────┬──────┐                        │
│                  │ │ P0   │ Team │Owner │ Dup  │  ← metric tiles        │
│                  │ └──────┴──────┴──────┴──────┘                        │
│                  │                                                      │
│                  │ Edit before filing                                   │
│                  │ [Priority ▼] [Component ▼] [Owner _________]         │
│                  │                                                      │
│                  │ Tabs: Findings | Media findings | Raw JSON           │
│                  │                                                      │
│                  │ [⬇ Download triage_notes.json]                       │
│                  │ [⬇ Download full ticket draft JSON]                  │
└──────────────────┴──────────────────────────────────────────────────────┘
```

Run with `streamlit run app.py` → `http://localhost:8501`. First load fetches 300 Jira bugs (~5s) and builds both indexes. Subsequent triage calls reuse cached engines.

---

## 11. Output JSON structure

```json
{
  "generated_at": "...",
  "input_file":   "data/bug_01_p0_checkout_crash.txt",
  "pipeline":     "multi-agent (Astral)",
  "parsed_bug": {
    "title":          "[Checkout]: App crashes on Proceed to Pay",
    "platform":       "Android",
    "app_version":    "2.4.2",
    "component_hint": "Backend",
    "reproducibility": "100%",
    "reporter":       "Rahul Verma <rahul.verma@flipkart.com>"
  },
  "jira_ticket_draft": {
    "fields": {
      "project":      {"key": "FLIPPI"},
      "issuetype":    {"id": "10036"},
      "summary":      "...",
      "priority":     {"id": "10000"},
      "description":  { ...ADF... },
      "components":   [{"name": "Backend", "id": "14386"}],
      "labels":       ["slap", "agentic-triage", "be-flippi", "android"],
      "customfield_10331": {"value": "Blocker"}
    }
  },
  "triage_notes": {
    "team":              "BE_Flippi",
    "jira_component":    "Backend",
    "priority":          "P0",
    "severity":          "Blocker",
    "priority_scoring_path": "claude-llm: app crash, payment-blocking",
    "severity_justification": "...",
    "owner_suggestion":  "Shailja Rani",
    "owner_reason":      "Assigned to Shailja Rani on 3/5 most-similar past bugs (similarity ≥ 0.20).",
    "duplicate_of":      "FLIPPI-1198",
    "duplicate_confidence": 0.85,
    "similar_bugs": [...],
    "media_findings": [...],
    "media_combined_summary": "...",
    "quality_issues": [...],
    "human_overrides": {
      "priority":  {"from": "P1", "to": "P0"}
    }
  }
}
```

---

## 12. Limitations & recommendations for next iteration

### Known limitations

**Owner suggestion ignores the routed component.** `src/tfidf_similarity.py:121-135` and `src/agents/subagent_embeddings.py:38-73` both pick an owner by assignee frequency across similar bugs, with no filter on whether the assignee is on the routed team. A frequent UI engineer can be suggested for a Backend-routed ticket if a few of the top-K matches happen to be UI bugs. The editable Owner field is the immediate workaround; the proper fix is to filter the similar-bug pool to component-matching bugs before counting assignees.

**Multi-agent classifier accuracy is not yet measured.** The rule-based classifier was validated at 78.7% on the 300-bug corpus. The multi-agent prompt has been aligned with the same vocabulary and given the "prefer bugs over a wrong guess" instruction, but it hasn't been run against the same 300 bugs to measure whether it closes part of the 21% gap.

**Class imbalance in the corpus.** DS has only 27 historical bugs, BE_Labs has 47, while Backend has 113 and UI 104. Any classifier trained from scratch on this corpus will under-represent the smaller classes. k-NN-based approaches (see below) handle imbalance better than from-scratch training.

### Recommended next iteration (ranked by ROI)

1. **Embedding-based k-NN classifier (highest ROI).** Embed each historical bug with a sentence-transformer or hosted embedding API, label by component, find nearest neighbours for a new bug, majority-vote the component. Uses existing labels directly; gets better automatically as Jira grows; handles class imbalance gracefully. ~$0.0001 per bug if using a hosted embedding API.

2. **Few-shot examples in the multi-agent parser prompt.** Replace the natural-language team descriptions with 5–8 real labeled FLIPPI examples per team, drawn from history. Pure prompt change, ~30 minutes of work, measurable in a day's testing.

3. **Feedback loop from `human_overrides`.** Persist the audit trail to a CSV / sqlite / Jira label. Periodically re-validate the classifier against accumulated overrides and feed corrections back into the few-shot pool or keyword list. Turns a static 78.7% into a continuously-improving system.

4. **Expand corpus from 300 → 1000+.** One-line change in `JiraClient.fetch_recent_bugs(limit=...)`. Only valuable **after** an ML method (#1) is in place that can use it. The rule-based engine doesn't benefit from a bigger corpus.

5. **Filter similar-bug pool by routed component before owner suggestion.** Addresses the owner/team mismatch limitation noted above. Small change in `_suggest_owner()` (rule-based) and `subagent_embeddings.py` (multi-agent).

The combination of #1 + #3 is the realistic path from 78.7% into the 90s.

---

## 13. Quick start

### Setup

```bash
# First time
pip3 install -r requirements.txt

# Minimal install (skip the SDK pipeline)
pip3 install requests python-dotenv numpy scikit-learn streamlit
```

The multi-agent pipeline additionally requires the **Claude Code CLI** installed and authenticated on the machine (`which claude` should return a path). No `ANTHROPIC_API_KEY` is needed — the CLI uses the local Claude Desktop session.

### Environment variables (`.env`)

```
JIRA_EMAIL=angaraju.v@flipkart.com
JIRA_TOKEN=<flipkart atlassian API token>
JIRA_BASE_URL=https://flipkart.atlassian.net
JIRA_PROJECT=FLIPPI
ANTHROPIC_API_KEY=            # only needed for main.py

# Pin the Claude binary so the pipeline survives corp endpoint security
# deleting brew-installed copies. The path below points at Claude Desktop's
# bundled CLI; override when Claude Desktop updates.
CLAUDE_BIN=/Users/.../Claude/claude-code/<version>/claude.app/Contents/MacOS/claude
```

### Running

```bash
# Streamlit front-end (recommended)
streamlit run app.py
# → http://localhost:8501

# Multi-agent pipeline directly (CLI)
python3 run_multi_agent.py                                  # all text + media bugs
python3 run_multi_agent.py data/bug_01_p0_checkout_crash.txt
python3 run_multi_agent.py data/bug_with_media/bug_m01_checkout_crash_screenshot
# Output → output_claude/ticket_<label>_<timestamp>.json

# Rule-based pipeline directly (CLI)
python3 run_agent.py                                        # all data/*.txt
python3 run_agent.py data/bug_01_p0_checkout_crash.txt
# Output → output/ticket_<stem>_<timestamp>.json
```

---

## 14. Project structure

```
slap-bug-triage/
├── app.py                      # Streamlit UI (Email / Form, editable outputs)
├── run_multi_agent.py          # PRIMARY: multi-agent pipeline (Claude headless)
├── run_agent.py                # Rule-based simulation harness
├── main.py                     # Anthropic SDK pipeline (blocked)
│
├── DOCUMENTATION.md            # THIS FILE — single project guide
├── CHANGELOG.md                # Dated record of feature additions
├── README.md                   # Quickstart
├── ARCHITECTURE.md             # Deep architecture notes
├── CLAUDE.md                   # Project context loaded into Claude sessions
├── TRIAGE_LOGIC.md             # PM-style report on rule-based logic
├── CLAUDE_PIPELINE_REPORT.md   # PM-style report on the Claude pipeline
│
├── slap_context/               # SLAP domain knowledge for the media sub-agent
│   ├── SLAP_KNOWLEDGE.md       # screen catalog, vocabulary, visual triage cues
│   └── reference_screens/      # labeled Figma exports (gitignored — design IP)
│
├── src/
│   ├── agents/                          # Multi-agent pipeline
│   │   ├── host_agent.py                # Astral — coordinates sub-agents
│   │   ├── subagent_media.py            # images / video → SLAP-aware findings
│   │   ├── subagent_parser.py           # email + media → BugReport
│   │   ├── subagent_form_consistency.py # form-only: title/summary/steps coherence
│   │   ├── subagent_embeddings.py       # rank top-K similar past bugs
│   │   ├── subagent_dedup.py            # final duplicate decision (≥ 0.80 conf)
│   │   └── subagent_triage.py           # priority assignment (3-tier)
│   ├── claude_cli.py                    # subprocess wrapper around `claude -p`
│   │
│   ├── agent_parser.py                  # Rule-based: regex parser
│   ├── agent_scorer.py                  # Rule-based: multi-layer priority scorer
│   ├── tfidf_similarity.py              # Rule-based: TF-IDF cosine similarity
│   │
│   ├── agent_ticket_builder.py          # Shared: ADF ticket builder
│   ├── jira_client.py                   # Shared: read-only Jira REST v3 wrapper
│   │
│   ├── parser.py                        # Anthropic SDK pipeline (blocked)
│   ├── severity_scorer.py               # Anthropic SDK pipeline (blocked)
│   ├── similarity.py                    # Anthropic SDK pipeline (blocked)
│   └── ticket_builder.py                # Anthropic SDK pipeline (blocked)
│
├── data/                                # Input bug-report .txt files
│   ├── bug_with_media/                  # multi-modal test bugs (gitignored media)
│   ├── bug_*.txt                        # text-only test bugs
│
├── tests/                               # Paired tests for mentor review
├── output/                              # Rule-based outputs (gitignored)
├── output_claude/                       # Multi-agent outputs (gitignored)
├── .env                                 # Secrets (gitignored)
├── .env.example                         # Template
└── requirements.txt
```

---

## 15. Production mapping

When the prototype is ported to production (Flipkart PaaS), each component swaps to its production counterpart with no logic changes:

| Prototype | Production |
|---|---|
| Bug report `.txt` / form | Gmail email via fk-mart-ai-pulse |
| `run_multi_agent.py` direct calls | Synapse (auth / routing) |
| Python script | Astral (agent runtime) |
| `agent_parser.py` rule-based | Genvoy / FK-GPT (LLM parsing) |
| `tfidf_similarity.py` | Vector One (managed vector DB) |
| `agent_scorer.py` rule-based | Genvoy / FK-GPT (LLM scoring) |
| Jira REST API (read) | Jira via MART MCP |
| Output JSON | Pulse SMTP reply to reporter |

All business logic — dedup logic, component routing, priority ladder, quality gates, ADF structure — stays the same. The prototype is the spec; production swaps the substrate.

---

## 16. Jira reference

- **Base URL**: https://flipkart.atlassian.net
- **Cloud ID**: `ba691f9e-703c-4694-be8e-2a532386325d`
- **Project key**: FLIPPI (name: SLAP)
- **Project ID**: 11206
- **Board**: "SLAP Planned" (scrum, board ID 2247)
- **Bug issue type ID**: 10036
- **Auth**: HTTP Basic — `email:token`
- **Search endpoint**: `POST /rest/api/3/search/jql` (v3)
- **Read-only guardrail**: `jira_client.py` has zero write methods.

### Component IDs (verified on `flipkart.atlassian.net`)

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

### Priority IDs

| Priority | Jira ID |
|---|---|
| P0 | 10000 |
| P1 | 10001 |
| P2 | 10002 |

---

## 17. Dependencies

```
requests>=2.31.0              # Jira REST API calls
python-dotenv>=1.0.0          # .env loading
numpy>=1.26.0                 # similarity math
scikit-learn>=1.9.0           # TF-IDF vectorizer + cosine similarity
streamlit>=1.32.0             # front-end UI (app.py)
imageio-ffmpeg>=0.4.9         # video keyframe extraction (multi-agent only)
anthropic>=0.25.0             # only for main.py (Anthropic SDK pipeline)
sentence-transformers>=2.7.0  # only for main.py (original similarity.py)
```

Plus the external **Claude Code CLI** (multi-agent pipeline only) — no PyPI dependency, must be installed and authenticated on the machine.

---

*Last refreshed 2026-06-24.*
