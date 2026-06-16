# SLAP Bug Triage — Claude-Powered Pipeline

A report describing the primary approach used by the SLAP bug triage agent: a three-stage Claude pipeline that reads bug-report emails, finds semantically similar past bugs across the full FLIPPI Jira history, and reasons about severity to produce a Jira ticket draft for human review.

Audience: mentors, reviewers, and anyone evaluating the system.

---

## 1. What the system does

A SLAP bug reporter sends an unstructured email. The system reads that email, looks at every recent Jira bug on the FLIPPI project, decides whether the new report is a duplicate or a fresh issue, picks the right team, picks the right priority, suggests an owner, and writes a Jira-ready ticket draft as JSON. A human reviews the draft and files it. The agent never writes to Jira itself.

The flow, at a glance:

```
bug_report.txt (email)
   │
   ▼
[ 1. Parse ]            Claude turns the raw email into structured fields.
   │
   ▼
[ 2. Fetch ]            Read-only call to Jira: pull the last 300 FLIPPI bugs.
   │
   ▼
[ 3. Similarity ]       Claude reads the new bug + all 300 historical bugs
   │                    in one prompt and ranks the top 5 most similar.
   ▼
[ 4. Scoring ]          Claude reasons about scope, reproducibility, and
   │                    similar history to assign P0 / P1 / P2 / P3.
   ▼
[ 5. Draft ]            Assemble a Jira-flavored ADF JSON ticket and write
                        it to disk. Human reviews and files.
```

---

## 2. Why an LLM at the core

Bug-report emails are unstructured. People describe the same problem in radically different language — "the app crashes on continue to payment" and "tap proceed to pay then the app dies" are the same bug, but no keyword list catches both without manual tuning. Reporter sentiment, hedging ("seems like… maybe… "), and mixed-platform mentions are common. Critical signals like "v2.4.2 — was working in v2.4.1" require *reading*, not pattern-matching.

Claude is well-suited here because:

1. **It reads emails like a senior engineer would** — picks up regression hints, scope qualifiers, severity-implying phrases without an explicit dictionary.
2. **It reasons across documents** — given 300 past bugs as context, it can connect "Android crashes on Proceed to Pay" with "iOS crashes on continue to payment" as the same failure mode on different platforms. A bag-of-words approach cannot.
3. **It justifies every decision** in plain English, which is exactly what a human reviewer needs to validate a draft quickly.

This is also why we avoided a hand-tuned classifier or a smaller embedding model. The bug surface is too varied; the value is in *understanding*, not in *matching*.

---

## 3. How Claude is invoked (no API key)

We use Claude Code in **headless mode**. The Claude Code CLI exposes a non-interactive flag — `claude -p "<prompt>"` — that takes a single prompt, sends it to Claude, prints the response, and exits. Authentication piggybacks on the locally signed-in Claude Code session, so no `ANTHROPIC_API_KEY` is required.

A small wrapper (`src/claude_cli.py`) runs the subprocess, parses the JSON envelope, strips any ```` ```json … ``` ```` fences Claude might wrap its answer in, and returns the inner JSON to the caller. Three Claude calls happen per bug (parse, similarity, score), each independent of the others.

---

## 4. Stage 1 — Parsing the email

Input: the raw bug-report email (any format).
Output: a structured `BugReport` object with these fields:

| Field | Example |
|---|---|
| `title` | `[Checkout]: SLAP app crashes on 'Proceed to Pay' — all Android users, v2.4.2` |
| `description` | 2–3 sentence summary, max 450 chars |
| `steps_to_reproduce` | list of strings |
| `expected_result` | what the user expected |
| `actual_result` | what actually happened |
| `impact` | reporter's stated business impact |
| `platform` | Android / iOS / Web / combination |
| `app_version` | `"2.4.2"` |
| `component_hint` | one of: Backend, Backend-Labs, DS, UI, immersive, bugs |
| `reproducibility` | `100%`, `intermittent`, `~30%`, etc. |
| `reporter_email`, `reporter_name` | extracted from headers / signature |

Claude is given a strict JSON schema and the email body. It returns one JSON object, which we deserialize into the dataclass. The prompt also includes the six-team component routing rules (Backend, Backend-Labs, DS, UI, immersive, bugs) with concrete keywords per team, so Claude classifies team ownership at parse time — no separate routing call needed.

**Why this matters:** the rest of the pipeline operates on a clean schema. Downstream stages never have to re-parse the email.

---

## 5. Stage 2 — Semantic similarity over 300 bugs

This is the most distinctive stage and where the Claude approach pulls ahead the hardest.

### The setup

* Fetch the last 300 FLIPPI bugs via Jira's REST API (read-only).
* For each one, build a compact JSON record: `{key, summary, description (trimmed), priority, assignee}` — about 110 KB of total context (~30,000 tokens).
* In a single Claude call, send: the new bug + all 300 historical bugs + instructions.

### What Claude is asked to return

```json
{
  "similar_bugs": [
    {
      "key": "FLIPPI-1198",
      "similarity": 0.85,
      "reasoning": "Both reports are 100%-reproducible crashes triggered by tapping the final payment button on the checkout screen. FLIPPI-1198 happened on iOS continue-to-payment, this one on Android proceed-to-pay — almost certainly the same root cause across platforms."
    },
    ...
  ],
  "duplicate_of": "FLIPPI-1198",
  "duplicate_confidence": 0.85,
  "duplicate_reasoning": "Same failure mode, same trigger, same severity — Android/iOS variant.",
  "suggested_owner": "Shailja Rani",
  "owner_reasoning": "Shailja owns the SLAP checkout flow in the top-similar bugs (FLIPPI-1663, FLIPPI-1665). FLIPPI-1198 was iOS-specific so the Android equivalent should route to the checkout owner, not the iOS specialist."
}
```

The owner suggestion is the surprising win — Claude doesn't just pick the most frequent assignee, it *reasons about who should fit this new bug* based on platform and component, including overriding the obvious frequency-based pick when it's not the right call.

### Why this beats keyword/vector similarity

| Approach | Top match for "Android Proceed-to-Pay crash" |
|---|---|
| Bag-of-words / TF-IDF | FLIPPI-1663 *"Checkout Page Price Discrepancy"* — matched on the word **"checkout"**. Not the same bug. |
| Claude over 300 bugs | FLIPPI-1198 *"[iOS] App is crashing on continue to payment"* — matched on the **failure mode**, flagged as cross-platform duplicate. The right answer. |

Lexical similarity sees words. Semantic similarity sees what the bug is *actually about*.

### Cost & latency

About 30–60 seconds per query (most of it is Claude reading 30k tokens of context). Roughly $0.10 of inference per call at Sonnet pricing. Cheaper and faster than the embeddings-DB + LLM-rerank approach typically used in production systems, with no infra to maintain.

---

## 6. Stage 3 — Severity scoring

Given the parsed bug + the top-5 similar past bugs (from Stage 2), Claude assigns a priority:

| Priority | Bar |
|---|---|
| **P0** | Crash; checkout/payment blocked; security/secrets concern; all-users outage; revenue-blocking. Immediate hotfix. |
| **P1** | Wrong AI results, ignored price/budget, ANRs, majority-user impact, core value-prop damage. Significant but not full outage. |
| **P2** | Partial UX degradation, workaround exists, subset of users. |
| **P3** | Vague reports, cosmetic, edge cases. |

Claude returns:
- `priority`: one of P0–P3
- `justification`: 2–3 sentence explanation grounded in the bug's scope, reproducibility, and the similar bugs it just saw
- `key_signals`: short phrases that drove the decision (e.g. `"100% reproducible crash on Proceed to Pay, all Android users, revenue-blocking checkout outage, confirmed regression from v2.4.1"`)

The justification flows into the Jira draft so the reviewer immediately sees *why* the agent picked P0 — no audit trail black-box.

---

## 7. Concrete walk-through

Input: `bug_01_p0_checkout_crash.txt` — a 1358-character report about a SLAP crash on the Proceed-to-Pay button on Android.

What Claude produces, end-to-end:

| Field | Value |
|---|---|
| **Parsed title** | `[Checkout]: SLAP app crashes to home screen on 'Proceed to Pay' — all Android users, v2.4.2` |
| **Component** | Backend → routed to team **BE_Flippi** |
| **Top similar bug** | [FLIPPI-1198](https://flipkart.atlassian.net/browse/FLIPPI-1198) *"[iOS] App is crashing on continue to payment"* (sim **0.85**) → flagged as duplicate candidate |
| **Suggested owner** | Shailja Rani — with reasoning explaining why the iOS assignee was *not* the right pick |
| **Priority** | **P0 / Blocker** |
| **Justification** | "The app crashes 100% reproducibly for all Android users on v2.4.2 immediately at 'Proceed to Pay', making it impossible for ~60% of the user base to complete any purchase — a complete revenue block. This is a confirmed regression from v2.4.1 with a highly similar historical precedent in FLIPPI-1198 (iOS crash on 'continue to payment', P0, similarity 0.85). The combination of crash + checkout block + all-users scope + revenue impact meets every P0 criterion simultaneously." |

That entire chain — extract, retrieve, reason, draft — runs from one bash command. No vector DB, no fine-tuning, no API key.

---

## 8. Front-end

`app.py` is a Streamlit web app that wraps the pipeline. A reviewer can:

1. Pick a sample bug from `data/` or paste their own.
2. Click **Triage this bug**.
3. Watch live step-by-step progress (parse → similar → score → draft) so the ~60-second Claude latency feels intentional, not frozen.
4. See a headline (priority, team, owner, duplicate) as big tile cards.
5. Drill into four tabs:
   - **Summary** — short reasoning + clickable Jira links to similar bugs.
   - **Triage notes** — full markdown of triage decisions, identical to the JSON content but rendered for humans.
   - **Raw JSON** — the `triage_notes` block, downloadable.
   - **Jira ADF preview** — exactly what would be sent if a human chose to file the ticket.

Run with `streamlit run app.py`. Opens at `localhost:8501`.

---

## 9. Output

Every run produces a JSON file in `output_claude/`:

```json
{
  "generated_at": "...",
  "input_file": "data/bug_01_p0_checkout_crash.txt",
  "pipeline": "claude-code-headless",
  "parsed_bug": { ... },
  "jira_ticket_draft": {
    "fields": {
      "project":   {"key": "FLIPPI"},
      "issuetype": {"id": "10036"},
      "summary":   "[Checkout]: ...",
      "priority":  {"id": "10000"},
      "description": { ...ADF blocks: heading / paragraph / lists... },
      "components": [{"name": "Backend"}],
      "labels":    ["slap", "agentic-triage", "be-flippi", "android"],
      "customfield_10331": {"value": "Blocker"}
    }
  },
  "triage_notes": {
    "team": "BE_Flippi",
    "jira_component": "Backend",
    "priority_scoring_path": "claude-llm: ...key signals...",
    "severity_justification": "...",
    "owner_suggestion": "Shailja Rani",
    "owner_reason": "...",
    "duplicate_of": "FLIPPI-1198",
    "duplicate_confidence": 0.85,
    "similar_bugs": [ ... ]
  }
}
```

The `triage_notes.priority_scoring_path` field carries Claude's `key_signals` so every priority decision is traceable.

---

## 10. What this gets us over a non-LLM approach

| Capability | Without LLM (keywords / embeddings) | With Claude pipeline |
|---|---|---|
| Handle paraphrases ("hangs" ↔ "ANR" ↔ "freezes") | Only if explicitly listed | Yes — out of the box |
| Cross-platform parallels (iOS bug ≈ Android bug) | No | Yes |
| Reason about regressions ("worked in v2.4.1") | No | Yes |
| Owner reasoning beyond "most-frequent assignee" | No | Yes |
| Auditable justification per ticket | Hard-coded explanations | Plain-English, per-bug |
| Maintenance as new bug shapes appear | Keyword/regex updates needed | Zero — Claude adapts |
| Brittleness to format changes in emails | High | Low |

---

## 11. Honest limitations

| Limitation | Mitigation / production answer |
|---|---|
| Per-bug latency ~50–90 seconds | Acceptable for one-off triage; not real-time. Production gateway (FK-GPT / Bedrock) can cache prompts across runs. |
| Stochastic — same input may give slightly different rankings | Always show the reasoning so a reviewer can validate. Re-run for stability if needed. |
| Headless mode needs a Claude-Code-authenticated machine | Production runs through FK-GPT or AWS Bedrock — same prompts, no Claude Code dependency. |
| 300-bug window only | Full corpus via Vector One in production. |
| One bug at a time — doesn't detect bug *clusters* (5 similar reports in 1 day) | Stream-based dedup at intake in production. |
| Uses Claude allotment for inference | Production routes through Flipkart's internal LLM gateway. |

None of these block prototype use. They are conscious trade-offs.

---

## 12. Production mapping

| Prototype piece | Production equivalent |
|---|---|
| Bug email `.txt` file | Gmail email via `fk-mart-ai-pulse` |
| `claude -p` subprocess | FK-GPT / Genvoy HTTP gateway (or AWS Bedrock) |
| `src/claude_*.py` modules | Same code, swap the transport in `claude_cli.py` |
| Jira REST read | Jira via MART MCP |
| Output JSON | Pulse SMTP reply to reporter |

The whole pipeline is structured so swapping any one stage is a single-line change. Prompts, similarity logic, output shape, and human-review guarantees stay the same.

---

## Appendix — The local simulation pipeline

For easier simulation and to keep iteration tight under time / cost constraints, we also developed a **fully local pipeline** (`run_agent.py`) that mirrors the Claude pipeline's shape exactly. Same input contract (`bug_report.txt`), same output contract (`triage_notes` JSON), same Jira fetch, same ADF ticket builder. The three "intelligence" stages are simulated:

- **Parse** — regex + heuristics over the email format (`src/agent_parser.py`)
- **Similarity** — TF-IDF cosine similarity over the same 300 historical bugs (`src/tfidf_similarity.py`)
- **Severity scoring** — a four-layer cascade: keyword regex → TF-IDF paraphrase templates → weighted similar-bug voting → impact-text fallback (`src/agent_scorer.py`)

The local pipeline runs in ~35 milliseconds per bug, costs nothing, and is fully deterministic. We used it during development to:

- Iterate fast on prompt design and output schema without burning Claude allotment.
- Generate baseline outputs for the 15-bug test corpus, then compare against Claude's outputs side-by-side.
- Provide a regression-safe reference: any time a Claude run produces a strange result, the local pipeline shows whether the issue is in the prompt or in the underlying data.

The local pipeline is preserved in the repository (and exposed in the Streamlit UI as a togglable second pipeline) for demos, fast iteration, and as a fallback if the Claude allotment is ever constrained. **The main approach — the one intended for production — is the Claude pipeline.** The local one is the simulation harness around it.
