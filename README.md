# SLAP Bug Triage

An **agentic bug-triage prototype** for **SLAP** (Shop Like A Pro — Flipkart's
GenAI conversational shopping app). Takes a raw bug-report email (and
optional screenshots), reads the last 300 real FLIPPI Jira bugs, then
produces a Jira-ready ticket draft as JSON — with priority, team routing,
duplicate detection, owner suggestion, and a plain-English justification.

> **Read-only Jira. Nothing is auto-filed.** A human reviews every draft
> before filing the actual ticket.

---

## Pipeline at a glance

```
bug-report email + optional screenshots
        │
        ▼
[1] Media       — vision sub-agent reads each screenshot; identifies
                  the SLAP screen, extracts visible text and anomalies,
                  flags contradictions with the email body.
        │
        ▼
[2] Parser      — email + media findings → structured BugReport
                  (title, platform, version, steps, expected, actual,
                  impact, reproducibility, component).
        │
        ▼
[3] Embeddings  — semantic retrieval over the last 300 FLIPPI bugs;
                  returns the top-5 most similar past tickets + a
                  suggested owner.
        │
        ▼
[4] Dedup       — focused dup/no-dup decision over the top-5
                  (≥ 0.80 confidence to flag).
        │
        ▼
[5] Triage      — assigns P0 / P1 / P2 / P3 with a justification
                  grounded in scope, reproducibility, and similar bugs.
        │
        ▼
build_ticket   — Jira ADF draft + triage_notes JSON.
```

A host agent (Astral, `src/agents/host_agent.py`) coordinates the five
sub-agents. Each sub-agent is a focused Claude prompt with one
responsibility. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full
design.

---

## Three pipelines (which to use)

| Pipeline | When | Latency | API key? |
|---|---|---|---|
| **`run_multi_agent.py`** (primary) | All real use — supports images, semantic similarity, multi-agent reasoning. | ~90–150 s/bug | None — uses Claude Code in headless mode (locally signed-in session). |
| **`run_agent.py`** (simulation) | Fast iteration, deterministic baselines, batch reruns under cost constraints. | ~35 ms/bug | None — pure Python (regex + scikit-learn TF-IDF). |
| **`main.py`** (reference) | Production-shaped Anthropic SDK pipeline. | — | Yes — blocked on `ANTHROPIC_API_KEY` (corp network restriction). Kept as the production-swap reference. |

---

## Quick start

```bash
# 1. Install deps (first time)
pip3 install -r requirements.txt

# 2. Make sure Claude Code is installed + signed in on this machine
which claude          # must return a path
claude --version      # should print 2.1.x

# 3. Verify Jira credentials in .env
cat .env              # JIRA_EMAIL / JIRA_TOKEN / JIRA_BASE_URL / JIRA_PROJECT

# 4. Run the multi-agent pipeline on a sample bug
python3 run_multi_agent.py data/bug_01_p0_checkout_crash.txt

# 5. Or on a bug with screenshots
python3 run_multi_agent.py data/bug_with_media/bug_otp_send_failed

# 6. Launch the Streamlit UI
streamlit run app.py
# → http://localhost:8501
```

Outputs land in `output_claude/` for the multi-agent pipeline and
`output/` for the rule-based pipeline (both gitignored).

---

## What you'll see in the UI

The Streamlit front-end at `localhost:8501` gives you:

- A pipeline-architecture stepper at the top (`Input → Media → Parser → Embeddings → Dedup → Triage → Output`) so reviewers see the multi-agent shape inline.
- A two-column input panel: bug-report textarea on the left; sample picker + pipeline radio + screenshot uploader on the right.
- A full-width **Triage this bug** button.
- A result panel with priority-coloured tiles (P0 red, P1 orange, P2 amber, P3 blue), Team, Owner, Duplicate-of, plus four detail tabs: Summary / Media findings / Triage notes (rendered markdown) / Raw JSON / Jira ADF preview.
- A **Refile this bug** flow that fires when the report is vague or its image contradicts the text — see [Quality gating](#quality-gating).

---

## Quality gating

The host agent flags two kinds of reports as "cannot be triaged
confidently" and forces a refile instead of producing a draft:

| Trigger | When it fires |
|---|---|
| **`vague_report`** | The raw email is missing 2+ required sections — checked against header patterns like `Impact:`, `Reproducibility:`, `Environment:`, `Steps to Reproduce`, `Expected:`, `Actual:`. Independent of what the parser inferred. |
| **`media_contradicts_text`** | The media sub-agent's `contradicts_email_claim` is set — e.g. an email about a checkout crash with a phone-login screenshot attached. |

When either fires, the UI shows a red banner + per-issue cards + a
**Refile this bug** button. The tentative draft is **not** shown — by
definition the input wasn't good enough.

---

## Repository layout

```
slap-bug-triage/
├── app.py                       # Streamlit UI
├── run_multi_agent.py           # PRIMARY: multi-agent Claude pipeline
├── run_agent.py                 # Local rule-based simulation
├── main.py                      # Anthropic SDK reference (blocked)
│
├── README.md                    # this file
├── ARCHITECTURE.md              # full multi-agent design reference
├── CLAUDE.md                    # Claude-loaded project context
├── TRIAGE_LOGIC.md              # rule-based scoring logic deep-dive
├── CLAUDE_PIPELINE_REPORT.md    # PM-style report for mentor review
│
├── slap_context/                # SLAP domain knowledge
│   ├── SLAP_KNOWLEDGE.md        # screen catalog, terminology, visual cues
│   └── reference_screens/       # Figma exports (gitignored — design IP)
│
├── src/
│   ├── agents/                  # multi-agent pipeline
│   │   ├── host_agent.py
│   │   ├── subagent_media.py
│   │   ├── subagent_parser.py
│   │   ├── subagent_embeddings.py
│   │   ├── subagent_dedup.py
│   │   └── subagent_triage.py
│   ├── claude_cli.py            # `claude -p` subprocess wrapper
│   ├── agent_parser.py          # rule-based parser
│   ├── agent_scorer.py          # rule-based scorer
│   ├── tfidf_similarity.py      # rule-based similarity
│   ├── agent_ticket_builder.py  # shared ADF builder
│   ├── jira_client.py           # read-only Jira v3 wrapper
│   ├── parser.py                # SDK parser (blocked)
│   ├── severity_scorer.py       # SDK scorer (blocked)
│   ├── similarity.py            # sentence-transformers similarity (blocked)
│   └── ticket_builder.py        # SDK ADF builder
│
├── data/                        # bug-report fixtures
│   ├── bug_*.txt                # text-only sample bugs
│   └── bug_with_media/          # multi-modal (email.txt + screenshot.png)
│       └── bug_*/email.txt      # email committed; PNGs gitignored
│
├── tests/                       # 15-bug mentor-review test pack
│   ├── _build.py                # generator: rule-based outputs
│   ├── _run_claude.py           # generator: multi-agent outputs
│   └── test N/                  # input + both pipelines' triage_notes
│
├── output/                      # rule-based outputs (gitignored)
├── output_claude/               # multi-agent outputs (gitignored)
├── .streamlit/config.toml       # toolbarMode=viewer (hides Deploy)
├── .env                         # secrets (gitignored)
├── .env.example                 # template
└── requirements.txt
```

---

## Documentation

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — multi-agent design reference. Sub-agent contracts, data flow, quality gating, design decisions, known limitations.
- **[`CLAUDE.md`](CLAUDE.md)** — Claude-loaded project context. Pipelines, environment, current status, production mapping.
- **[`TRIAGE_LOGIC.md`](TRIAGE_LOGIC.md)** — deep dive on the rule-based scoring (the simulation pipeline).
- **[`CLAUDE_PIPELINE_REPORT.md`](CLAUDE_PIPELINE_REPORT.md)** — PM-style writeup of the Claude pipeline for mentor review.
- **[`slap_context/SLAP_KNOWLEDGE.md`](slap_context/SLAP_KNOWLEDGE.md)** — SLAP screen catalog, UI vocabulary, visual triage cues — what the media sub-agent reads as domain context.
- **[`tests/README.md`](tests/README.md)** — the paired test pack (input + rule-based output + Claude output, 15 tests).

---

## Production mapping

This is a prototype; production parts have direct equivalents:

| Prototype | Production target |
|---|---|
| `bug_report.txt` | Gmail email via fk-mart-ai-pulse |
| `run_multi_agent.py` | Astral agent runtime |
| `subagent_*` Claude calls | Genvoy / FK-GPT internal LLM gateway |
| 300-bug embeddings cache | Vector One (managed vector DB) |
| Jira REST (read) | Jira via MART MCP |
| Output JSON | Pulse SMTP reply to reporter |

Swapping prototype → production is roughly one-line changes per stage.
All business logic (dedup threshold, component routing, ADF structure,
quality gating) stays the same.

---

## Constraints (deliberate design choices)

1. **No auto-write to Jira.** Agent produces drafts only — humans file
   the actual ticket.
2. **No auto-merge duplicates.** Engineer verifies before linking.
3. **Read-only Jira access.** `src/jira_client.py` has no
   create/edit/transition methods.
4. **Human in the loop, always.** Refile is preferred over a confident
   wrong answer.
