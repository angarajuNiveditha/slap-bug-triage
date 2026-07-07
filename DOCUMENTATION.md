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

The host agent (`src/agents/host_agent.py`, codenamed **Astral**) is a thin coordinator. The pipeline now mixes Claude calls (for tasks Claude is good at: parsing, dedup judgement, triage reasoning, multimodal media analysis) with light local ML (embedding similarity, LogReg classification) for tasks where Claude was previously doing what a sentence-transformer can do faster and better.

```
bug input (email OR structured form + optional images / videos)
    │
    ▼
[1] subagent_media           — only if attachments present                 [Gemini + Claude]
    │     Stage A: Gemini vision (per-image OR per-video-keyframe,
    │              in parallel via ThreadPoolExecutor)
    │     Stage B: Claude reasoning over the vision descriptions
    │              (screen mapping, triage signals, contradiction detection)
    │     Falls back to legacy single-Claude call if Gemini is unreachable.
    │     ↳ one-line summary folded into the email body
    ▼
[2] subagent_parser          — email + media findings → BugReport          [Claude]
    │
    ▼
[2b] subagent_form_consistency — only if from_form=True                    [Claude]
    │                             refile if title/summary/steps don't match
    ▼
[3] EmbeddingClassifier      — LogReg over 564-bug embedding index        [local ML]
    │     ~7ms; if top-class prob < 0.50, falls back to Claude with
    │     skill files for the top-3 candidate teams                       [Claude+skills]
    ▼
[4] EmbeddingSimilarityEngine — TWO-STAGE retrieval:                       [local ML + rerank]
    │     • cosine top-30 recall (~200 µs)
    │     • cross-encoder ms-marco-MiniLM-L-6-v2 rerank of the 30 pairs
    │       (~1.2 s CPU) → top-10 to the parallel block
    ▼
[5] PARALLEL BLOCK (ThreadPoolExecutor, ~8-12s wall clock)
    ├─ subagent_dedup        — dup/no-dup over top-10                     [Claude]
    │                          (fires only if confidence ≥ 0.80)
    ├─ subagent_owner        — engineer pick with escalation ladder:      [Claude + rules]
    │                          1. Engineer with same-component similar-bug
    │                             history → Claude picks best; else
    │                          2. Only managers in similar bugs → closest
    │                             one by cosine sim; else
    │                          3. TEAM_MANAGERS[component]:
    │                             • UI, Backend-Labs, immersive → Yatin Grover
    │                             • Backend → Veeramreddy ChakradharReddy
    │                             • DS → unmapped (manual triage)
    └─ subagent_triage       — BugReport + similar bugs → SeverityResult  [Claude]
                                3-tier ladder: P0 / P1 / P2
    ▼
agent_ticket_builder         — assembles Jira ADF + triage_notes JSON
    │
    ▼
human override (UI)          — reviewer edits Priority / Component / Owner
                              + sees full probability distribution when
                                LogReg confidence < 0.50
                              + override goes into corrections.csv for
                                active learning on the next rebuild
                              + widget keys are versioned per triage run,
                                so re-triaging always resets tiles to
                                the fresh prediction
```

### Sub-agent / stage responsibilities

| Stage | File | Implementation | What it does |
|---|---|---|---|
| **Media** | `subagent_media.py` | **Gemini vision + Claude reasoning** | Two-stage. Stage A: Gemini describes each image / video keyframe in parallel via `ThreadPoolExecutor` (Flipkart's internal Gemini proxy at `10.83.64.112`, dual auth: subscription key + short-lived JWT). Stage B: Claude reads the descriptions + `slap_context/SLAP_KNOWLEDGE.md` + `reference_screens/` and emits the structured `MediaFinding` (screen, state, triage signals, contradiction detection, `screen_sequence` / `action_observed` / `failure_moment` for videos). Falls back to a single-Claude-call path (Claude reads image PNGs directly) if Gemini is unavailable. |
| **Parser** | `subagent_parser.py` | Claude | Turns the email body into a structured `BugReport` — title, description, steps, expected/actual, impact, platform, reproducibility, reporter. **No longer outputs `component_hint`** — that's the classifier's job. |
| **Form consistency** | `subagent_form_consistency.py` | Claude | Only runs when `from_form=True`. Asks Claude whether title/summary/steps describe the same bug. Refile banner if not. |
| **Component classifier** | `embedding_classifier.py` | LogReg + Claude fallback | Trained on 564 labelled FLIPPI bugs (mpnet embeddings, `class_weight='balanced'`). ~7 ms per prediction. If LogReg's top-class probability ≥ 0.50, returns it directly. Otherwise (~36% of bugs), calls Claude with the top-3 candidate teams' skill files + per-repo skills loaded into context — Claude makes an architecture-grounded final call. Managers (Yatin, Veeramreddy) are filtered from the derived team roster at build time via `MANAGER_NAMES` in `team_config.py`. |
| **Similarity engine** | `embedding_similarity.py` | **Cosine recall + cross-encoder rerank** | `find_similar_with_rerank()`: cosine over the 564-bug index picks the top-30 candidates (~200 µs); a lazily-loaded cross-encoder (`ms-marco-MiniLM-L-6-v2`) rescores those 30 pairs with joint attention (~1.2 s CPU); returns the top-10 with sigmoid-normalised scores in `.similarity`. Falls back to plain cosine top-K if the cross-encoder can't load. `is_duplicate_candidate` still tracks raw cosine vs the 0.80 threshold (calibrated for that scale). |
| **Dedup** | `subagent_dedup.py` | Claude | Focused dup/no-dup over the reranked top-10. Only flags duplicates ≥ 0.80 confidence. |
| **Owner suggestion** | `subagent_owner.py` | Claude + escalation rules | Strict "similar-bug engineer > closest-similar-bug manager > team manager" rule. (1) If any non-manager engineer appears in same-component similar-bug assignees, Claude picks between them. (2) If only managers appear, the manager on the *closest* similar bug wins. (3) Else `TEAM_MANAGERS[component]` from `team_config.py` (Yatin for UI/BE-Labs/immersive; Veeramreddy for Backend). Frequency-of-roster fallback removed — an engineer needs actual similar-bug history to be a candidate. |
| **Triage** | `subagent_triage.py` | Claude | Priority (P0 / P1 / P2) using similar bugs' priorities as primary signal. Hard overrides: 100% repro crash → P0; Grayskull/secrets/infra → P0. |

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
| bugs | *(no component)* | — | Low-confidence — needs manual routing |

### The current production classifier: embedding + LogReg + Claude+skills fallback

The keyword-regex approach reached 78.7% on an early 300-bug sample but collapsed to 27.7% when re-measured against a larger, more recent 564-bug labelled corpus — the keyword list couldn't keep up with FLIPPI's evolving vocabulary. The current classifier replaces regex with a hybrid stack:

```
1. Embed bug text with sentence-transformers/all-mpnet-base-v2 (~7ms, local CPU, no API key)
2. LogisticRegression (class_weight='balanced') over the 564 indexed bug embeddings
3. Read the top class's predicted probability:
     • probability >= 0.50  → return it (fast path, no Claude call)
     • probability < 0.50   → call Claude with the top-3 candidate teams'
                              skill files loaded into the prompt, take Claude's verdict
     • probability < 0.40 even after Claude → route to "bugs" (manual)
```

The 564-bug index is built once by `build_embedding_index.py` and cached as:
- `data/embedding_index.npz` — embeddings + labels + texts + assignees + priorities
- `data/embedding_index_logreg.pkl` — the trained LogReg model
- `data/embedding_index_team_roster.json` — derived `team → [engineer, bug_count]` mapping for the owner sub-agent

Rebuild whenever Jira has new labelled bugs or the corrections.csv (active-learning) file has new overrides.

### Measured accuracy on 564-bug leave-one-out

| Classifier | LOO accuracy | Latency / bug | Notes |
|---|---|---|---|
| Rule-based regex (the old keyword approach, on this corpus) | 27.7% | ~0.06 ms | Falls back to "bugs" on 68% of cases |
| Pure Claude (focused prompt, no skill files) | 65.1% | ~6.6 s | Measured serially on all 564 bugs |
| Pure LogReg LOO | 66.8% | ~7 ms | The fast-path baseline |
| **HYBRID (LogReg + Claude+skills fallback)** | **69.5%** | avg ~2.3 s | **Production behaviour** |

Two observations on the hybrid number:

- **+2.7 pp over pure LogReg** overall, modest but real on 564 samples
- **+7.4 pp on the 202 borderline bugs** where LogReg was unsure — this isolates the contribution of the architecture skill files. On the cases that actually need disambiguation, the skills push from 47.5% → 55.0%

Per-class F1 on the hybrid:

| Class | Support | Precision | Recall | F1 |
|---|---|---|---|---|
| UI | 235 | 81.4% | 81.7% | **0.82** |
| DS | 115 | 61.4% | 88.7% | **0.73** |
| Backend-Labs | 69 | 62.5% | 72.5% | **0.67** |
| Backend | 145 | 63.2% | 33.1% | **0.43** ← floor |

### Why Backend F1 is the floor — the label-noise audit finding

A manual audit (`audit_backend_misclassifications.py`) of 42 of the 85 misclassified Backend bugs found:

| Verdict | Share |
|---|---|
| **Mislabelled in Jira** (should be DS / UI / BE_Labs) | **~70%** |
| Cross-team ambiguous (defensible either way) | ~20% |
| Genuine model error | ~10% |

The dominant pattern: **Backend → DS leakage**. Chat-AI / model-relevance complaints ("wrong results", "bot didn't understand", "reasons to buy missing", "ranking is off") are systematically being filed against the `Backend` component when they're textbook DS bugs. The classifier correctly identifies them as DS-shaped (top-3 nearest neighbours are all DS bugs at high similarity); we're scoring it against noisy ground truth.

If those ~60 mislabelled bugs were relabelled to DS / UI / BE_Labs, projected accuracy would be **~78–82%** with no model changes. This is the single highest-leverage move available — see §12.

The audit output (gitignored — contains reporter emails / chat URLs) is regenerable from `python3 audit_backend_misclassifications.py`.

### Active learning loop

When a reviewer overrides Component in the Streamlit edit widget, the override is appended to `data/corrections.csv` (gitignored) with the bug text, predicted class, and corrected class. The next index rebuild (`python3 build_embedding_index.py`) folds these synthetic bugs into the training corpus alongside fresh Jira data. The model gets better every time a reviewer corrects it; no Jira edit required.

---

## 6b. Architecture skill files & repo-context system

When LogReg is confident (≥0.50), the classifier doesn't need any architectural context. But for the ~36% of bugs that fall to the Claude fallback, Claude reads **architecture skill files** describing what each candidate team owns. This is what turns a "65.1% pure Claude" into a "55.0% Claude+skills on the hard subset" — the skills give Claude concrete code/module references to reason against.

**All skill files were revamped 2026-07-07.** Per-repo files (previously just directory listings) are now derived from **actual code mining** by `build_repo_skills.py` — grepping `*Service.java`, `*Exception.java`, `*Controller/Handler/Endpoint/Resource.java`, `*Dto/Request/Response.java`, `public enum`, `@GetMapping` / `@PostMapping` / `@RequestMapping` routes, and Spring config files. Team-level files were rewritten to cite the real class names from the mined per-repo files rather than inferred prose.

### File layout

```
slap_context/architecture/
├── repos.json                 # repo → team → metadata manifest (source of truth)
├── UI.md                      # 148 lines — spaghetti/mozzarella cross-ref + Varun/Hyzam split
├── Backend.md                 # 214 lines — real class inventories per edison module
├── Backend-Labs.md            # 147 lines — VTON / Styledrops / Social Finds routing
├── DS.md                      # 142 lines — 30+ real symptom patterns, Backend↔DS litmus test
├── immersive.md               # 141 lines — org-chart-derived (no repo cloned yet, honestly caveated)
└── repos/                     # per-repo skill files
    ├── edison.md              # 170 lines, mined services + exceptions + enums per module
    ├── dropsense.md           # 152 lines — 15 services, 23 exceptions, 11 enums listed
    ├── FaceNet.md             # 123 lines — small Python VTON model service
    ├── slap-feed.md           # 177 lines — feed-adk-poc + edison-discovery mined
    ├── social-finds-pipeline.md  # 134 lines
    ├── slap-auto-qc-pipeline.md  # 78 lines — all 37 QC classes listed
    ├── spaghetti.md           # 255 lines, hand-authored — ~100 RN components + ~80 screens
    └── mozzarella.md          # 284 lines, hand-authored — 17 Redux slices, routing table
```

Per-repo skills are loaded *alongside* the team-level skill when that team is one of the top-3 candidates. A "UI" candidate bug gets the UI team skill + spaghetti + mozzarella skills bundled into Claude's prompt — typically ~25–37 KB of architectural context.

**How the mining works**: `build_repo_skills.py` walks each repo under `data/repos/` and per top-level directory extracts (via `grep`) the service / exception / entry-point / enum class names. These land in the auto-generated per-repo `.md` files under `slap_context/architecture/repos/`. The team-level files (`Backend.md` etc.) cite those class names directly, so reviewers can grep the real codebase to verify any claim in the skill file. `HAND_AUTHORED = {"spaghetti", "mozzarella"}` in the script means bulk runs skip those two — they're richer than mining alone can produce.

### Repo coverage

- **8 of 11 manifest repos** currently have skill files committed
- 6 are auto-generated by `build_repo_skills.py` from local clones (edison, dropsense, FaceNet, slap-feed, social-finds-pipeline, slap-auto-qc-pipeline)
- 2 are hand-authored (spaghetti, mozzarella) — these include a "Common Bug Routing Signals" table mapping symptoms → exact file paths, which is the highest-value content for the classifier
- 3 not yet covered: `edison-gateway`, `cp-service-clients`, `expert-opinion-offline-flow` (repos not cloned)
- Immersive team has no cloned repos → `immersive.md` is honestly caveated as org-chart-inferred

### Refreshing the skill files

```bash
python3 build_repo_skills.py            # all cloned repos except HAND_AUTHORED
python3 build_repo_skills.py edison     # just one repo
python3 build_repo_skills.py spaghetti  # forces regeneration of a HAND_AUTHORED file
```

The team-level files are hand-maintained; run through the diffs against the newly-mined per-repo output when the code changes materially.

### Repo cloning (production-prototype mapping)

| Production | Prototype equivalent (`src/repo_context.py`) |
|---|---|
| K8s indexer workers | One Python script: `build_repo_skills.py` |
| Vector One (shared, namespaced) | Local `.npz` + `.md` per repo under `data/repos/` and `slap_context/architecture/repos/` |
| Cryptex-managed token | `GITHUB_FK_TOKEN` env var |
| GitHub push webhook → incremental re-index | Manual `python3 build_repo_skills.py` |
| tree-sitter + LSP | File-tree walk + extension counts + recent commits via `git log` |
| Per-repo agent + shared index | `RepoContextEngine` per-repo with shared manifest |
| Live agentic search fallback | `git grep` over the local clone (`repo_context.grep_repo()`) |

`src/repo_context.py` exposes `load_manifest()`, `clone_repo()`, `structural_map()`, `grep_repo()`, and `report_status()`. Run `python3 src/repo_context.py` for a one-shot diagnostic showing token availability + which repos are cloned locally.

### When the manifest lies (and how the skill catches it)

Two manifest entries (`slap-feed`, `social-finds-pipeline`) are labelled as standalone repos but are actually **branches of `Flipkart/edison`** (the URLs are `github.fkinternal.com/Flipkart/edison/tree/slap-feed` and `.../tree/social-finds-master-uat`). The build script clones the right branch and produces skill files that accurately reflect what's there. Similarly, the manifest claimed `dropsense` was JavaScript — auto-generated skill caught that it's Java/Maven (271 .java files, Pulsar + Aerospike infra). Auto-generation > hand-curated manifests for ground-truth fields.

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

**Backend label noise is the headline limitation.** The audit (§6) found that ~70% of misclassified Backend bugs are actually mislabelled in Jira — they should have been DS, UI, or BE_Labs. The model is correctly identifying them as those other classes; we score it against the noisy ground truth. Until those labels are cleaned, measured accuracy understates the model's real performance by an estimated 8-12 percentage points.

**3 of 11 manifest repos are not yet cloned / skill-mapped.** `edison-gateway`, `cp-service-clients`, `expert-opinion-offline-flow` — the GitHub Enterprise org names for these aren't yet known. The Backend team in particular would benefit from `edison-gateway` (gateway / rate-limiting) and `cp-service-clients` (downstream commerce platform integration) being added.

**Class imbalance still affects training.** Even with the updated 564-bug corpus, UI has 235 examples while BE_Labs has only 69. `class_weight='balanced'` in LogReg helps but doesn't fully solve it.

**Immersive has zero training examples** in the corpus. The LogReg classifier won't predict Immersive at all. Native AR / VTO SDK bugs route to UI or "bugs" — needs human override.

### Recommended next iteration (ranked by ROI)

1. **Relabel the ~60 mislabelled Backend bugs (highest ROI).** The audit (`audit_backend_misclassifications.py` → `audit_backend_misclassifications.md`) lists each one with the model's prediction. A reviewer accepting the model's suggestion where clearly correct (DS for relevance bugs, UI for `[iOS]` rendering, BE_Labs for Social Finds) and rebuilding the index would push headline accuracy from 69.5% to ~78-82% with no code changes. Best path: fold reviewer verdicts into `corrections.csv` so the model re-trains automatically on the cleaned labels (no Jira edits required).

2. **Clone + skill the missing 3 repos.** Token already has the right scope; we just need the GitHub Enterprise org names. Each unlocks one more concrete file of evidence Claude can reason over during borderline classifications. Probably +1-3 pp on Backend recall specifically.

3. **Add a "Common Bug Routing Signals" table to `spaghetti.md` (similar to mozzarella's).** Mozzarella's symptom-to-file-path mapping is the highest-value content for the Claude fallback — it lets Claude match a bug description directly to a code location. Spaghetti currently has only the inventory.

4. **Audit the `bugs` class.** A non-trivial number of bugs in Jira have no component set. Some of those, when classified by LogReg, could be added back to training data with a confident label. Active learning loop applied to historical unlabelled bugs.

5. **Track latency variance.** Production Claude calls are 6-10s; cold-start can be longer. Adding a latency histogram in the Streamlit UI would surface degradation early.

6. **Switch to a hosted embedding (Voyage `voyage-3` or OpenAI `text-embedding-3-small`) if Flipkart network allows.** A stronger embedding would lift recall on every class by 2-4 pp. Currently blocked on the same network restrictions that block `ANTHROPIC_API_KEY`.

The single highest-leverage move is **#1 (relabel Backend)** — it's measurable, well-scoped (a worklist already exists), and converts model "errors" into model wins without writing code.

---

## 13. Quick start — running from scratch

This is the full from-zero setup. Anyone with a Flipkart Atlassian account + Claude Desktop should be able to follow this and have a working triage UI in ~15 minutes.

### 1. Clone the repo

```bash
git clone https://github.com/angarajuNiveditha/slap-bug-triage.git
cd slap-bug-triage
```

### 2. Install Claude Code CLI + sign in

The multi-agent pipeline talks to Claude via the local `claude -p` binary, **not** an `ANTHROPIC_API_KEY`. So no API key is needed — your locally-signed-in Claude session provides authentication.

```bash
# Mac
brew install --cask claude

# Then open Claude Desktop, sign in with your Flipkart Google account.
# Verify the CLI is on the PATH:
which claude        # should print a path
echo "ping" | claude -p   # should respond
```

### 3. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

Pulls `requests`, `python-dotenv`, `numpy`, `scikit-learn`, `streamlit`, `sentence-transformers>=2.7.0`, `imageio-ffmpeg`. ~5 min depending on connection. The sentence-transformer model itself (~420 MB) downloads on first triage, not during install.

### 4. Configure `.env` with YOUR credentials

```bash
cp .env.example .env
# then edit .env
```

Required fields:

```
JIRA_EMAIL=<your flipkart email>
JIRA_TOKEN=<your Atlassian PAT — generate at id.atlassian.com/manage-profile/security/api-tokens>
JIRA_BASE_URL=https://flipkart.atlassian.net
JIRA_PROJECT=FLIPPI

# Leave empty — the multi-agent pipeline uses the local claude -p CLI
ANTHROPIC_API_KEY=
```

Optional fields:

```
# Gemini API key (only if you want to test the hybrid media sub-agent —
# get one at aistudio.google.com)
GEMINI_API_KEY=

# Pin a specific Claude binary path. Auto-detected on most macs.
CLAUDE_BIN=
```

You do NOT need a GitHub Enterprise token for the mentor flow — the per-repo skill files are already checked into this repo (under `slap_context/architecture/repos/`).

### 5. Build the embedding index (one-time, ~75 seconds)

```bash
python3 build_embedding_index.py
```

This fetches ~564 component-labelled FLIPPI bugs from Jira (last 15 months), embeds each with sentence-transformers, trains the LogReg classifier, and derives the team roster from assignee history. Writes three files to `data/`:

- `embedding_index.npz` — embeddings + labels + texts + assignees + priorities
- `embedding_index_logreg.pkl` — trained LogReg model
- `embedding_index_team_roster.json` — team → engineer roster

These are local to your machine (gitignored).

### 6. Launch the Streamlit UI

```bash
streamlit run app.py
# → http://localhost:8501
```

First load fetches a 300-bug similarity corpus and warms the embedding model (~10 s). Subsequent triages are fast.

### 7. Try a few test bugs

The repo ships with labelled test bugs you can paste into the Email mode of the UI, or run via CLI:

```bash
python3 run_multi_agent.py data/bug_01_p0_checkout_crash.txt        # P0 / UI
python3 run_multi_agent.py data/bug_02_p1_search_wrong_results.txt  # P1 / DS
python3 run_multi_agent.py data/bug_aggressive_caching.txt          # ambiguous → Claude+skills fallback
```

Each writes a ticket draft into `output_claude/`.

### 8. (Optional) Reproduce the measured numbers

```bash
python3 validate_embedding_classifier.py    # ~3 s — LOO accuracy (66.8%)
python3 validate_claude_component.py        # ~24 min — pure Claude baseline (65.1%)
python3 validate_hybrid_classifier.py       # ~14 min — hybrid (69.5%)
python3 audit_backend_misclassifications.py # ~3 s — Backend label-noise audit
```

Numbers match what's in `CHANGELOG.md`.

### 9. (Optional) Test Gemini for the hybrid media sub-agent

If you've set `GEMINI_API_KEY` in `.env`:

```bash
python3 test_gemini.py                          # network + key + text generation
python3 test_gemini.py path/to/screenshot.png   # also test vision
```

### Rule-based fallback pipeline

For fast deterministic iteration without Claude in the loop:

```bash
python3 run_agent.py data/bug_01_p0_checkout_crash.txt   # ~35 ms per bug
# Output → output/ticket_<stem>_<timestamp>.json
```

---

## 14. Project structure

```
slap-bug-triage/
├── app.py                      # Streamlit UI (Email / Form, editable outputs, ambiguity banner)
├── run_multi_agent.py          # PRIMARY: multi-agent pipeline (Claude headless)
├── run_agent.py                # Rule-based simulation harness
├── main.py                     # Anthropic SDK pipeline (blocked)
│
├── build_embedding_index.py    # One-time: fetch 564 labelled bugs + embed + train LogReg + roster
├── build_repo_skills.py        # Generate per-repo skill files from cloned repos
├── validate_embedding_classifier.py   # LOO accuracy + rule-based comparison
├── validate_claude_component.py       # Claude-only component-classifier benchmark
├── validate_hybrid_classifier.py      # **Production accuracy: LogReg + Claude+skills**
├── audit_backend_misclassifications.py # Worklist generator for Backend label-noise audit
│
├── DOCUMENTATION.md            # THIS FILE — single project guide
├── CHANGELOG.md                # Dated record of feature additions
├── README.md                   # Quickstart
├── ARCHITECTURE.md             # Deep architecture notes
├── CLAUDE.md                   # Project context loaded into Claude sessions
├── TRIAGE_LOGIC.md             # PM-style report on rule-based logic
├── CLAUDE_PIPELINE_REPORT.md   # PM-style report on the Claude pipeline
│
├── slap_context/               # SLAP domain knowledge
│   ├── SLAP_KNOWLEDGE.md       # screen catalog, vocabulary, visual triage cues
│   ├── reference_screens/      # labeled Figma exports (gitignored — design IP)
│   └── architecture/           # Team & repo skill files for the classifier fallback
│       ├── repos.json          # Repo → team metadata manifest (11 entries)
│       ├── UI.md               # Hand-curated team skill
│       ├── Backend.md          # Hand-curated team skill
│       ├── Backend-Labs.md     # Hand-curated team skill
│       ├── DS.md               # Hand-curated team skill
│       ├── immersive.md        # Hand-curated team skill
│       └── repos/              # Per-repo skills (gitignored — contains real code refs)
│           ├── edison.md, dropsense.md, FaceNet.md, …  (auto-generated)
│           └── spaghetti.md, mozzarella.md             (hand-written, with routing tables)
│
├── src/
│   ├── embedding_classifier.py          # LogReg + Claude+skills fallback
│   ├── embedding_similarity.py          # Cosine search → SimilarBugs (replaces stage 3)
│   ├── repo_context.py                  # GitHub Enterprise clone + structural map + grep
│   │
│   ├── agents/                          # Multi-agent pipeline
│   │   ├── host_agent.py                # Astral — coordinates sub-agents
│   │   ├── subagent_media.py            # images / video → SLAP-aware findings
│   │   ├── subagent_parser.py           # email + media → BugReport (no component_hint)
│   │   ├── subagent_form_consistency.py # form-only: title/summary/steps coherence
│   │   ├── subagent_dedup.py            # final duplicate decision (≥ 0.80 conf)
│   │   ├── subagent_owner.py            # NEW — owner suggestion, roster-constrained
│   │   ├── subagent_triage.py           # priority assignment (3-tier)
│   │   └── (subagent_embeddings.py)     # deprecated — replaced by embedding_similarity.py
│   ├── claude_cli.py                    # subprocess wrapper around `claude -p`
│   │
│   ├── agent_parser.py                  # Rule-based: regex parser (still used by run_agent.py)
│   ├── agent_scorer.py                  # Rule-based: multi-layer priority scorer
│   ├── tfidf_similarity.py              # Rule-based: TF-IDF cosine similarity
│   │
│   ├── agent_ticket_builder.py          # Shared: ADF ticket builder
│   ├── jira_client.py                   # Shared: read-only Jira REST v3 wrapper (+ component & training-corpus fetchers)
│   │
│   ├── parser.py / severity_scorer.py / similarity.py / ticket_builder.py
│   │                                    # Anthropic SDK pipeline (blocked)
│
├── data/                                # Input bug-report .txt files + caches
│   ├── bug_with_media/                  # multi-modal test bugs (gitignored media)
│   ├── bug_*.txt                        # text-only test bugs
│   ├── embedding_index.npz              # GITIGNORED — embeddings + labels + texts + assignees + priorities
│   ├── embedding_index_logreg.pkl       # GITIGNORED — trained LogReg model
│   ├── embedding_index_team_roster.json # GITIGNORED — team → engineers (active-learning roster)
│   ├── corrections.csv                  # GITIGNORED — human overrides feeding back into training
│   └── repos/                           # GITIGNORED — cloned SLAP repos for skill generation
│
├── tests/                               # Paired tests for mentor review
├── output/                              # Rule-based outputs (gitignored)
├── output_claude/                       # Multi-agent outputs (gitignored)
├── .env                                 # Secrets (gitignored) — incl. GITHUB_FK_TOKEN
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

*Last refreshed 2026-06-25. Phase-2 work: embedding-based classifier (LogReg over sentence-transformer embeddings on 564 labelled FLIPPI bugs); skill-aware Claude fallback for borderline cases; cosine-similarity engine replacing the old in-context Claude similarity stage; team-roster-constrained owner sub-agent; active-learning loop via corrections.csv; backend label-noise audit revealing ~70% of misclassified Backend bugs are mis-labelled in Jira. Production accuracy: 69.5% LOO on the 564-bug corpus; estimated 78–82% with cleaned labels.*
