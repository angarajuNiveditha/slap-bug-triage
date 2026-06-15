# SLAP Bug Triage — How the Agent Decides

A plain-English walkthrough of the logic the agent uses to read a bug
report email, find duplicates, classify it, and pick a priority. Aimed
at PMs, EMs, and reviewers — focuses on *why this works*, not the code.

---

## 1. The pipeline at a glance

```
bug_report.txt
   │
   ▼
[ Parse ]        Pull title, platform, version, steps, impact, reporter
   │             out of the raw email using regex + heuristics.
   ▼
[ Fetch ]        Read the last 300 FLIPPI bugs from Jira (read-only).
   │
   ▼
[ Compare ]      Use TF-IDF cosine similarity to find the 5 most
   │             similar past bugs from those 300.
   ▼
[ Decide ]       • Duplicate?  → similarity ≥ 0.38
   │             • Component?  → keyword routing into 6 teams
   │             • Owner?      → most frequent assignee on top matches
   │             • Priority?   → 4-layer scoring cascade
   ▼
[ Draft ]        Assemble a Jira ticket JSON (never filed automatically).
```

The agent never writes to Jira. It produces a draft that a human files.

---

## 2. Parsing the email

The reporter sends a free-form email. We don't ask them to fill a form,
so we extract structured fields with **regex and heuristics** — no LLM
needed for this step.

What we pull out:

| Field | How we find it |
|---|---|
| **Title** | `Subject:` line, with prefixes like `[URGENT]` stripped |
| **Reporter** | `From:` line, or signature like `Regards, <name>` |
| **Platform** | `Platform:` field, or mentions of "Android", "iOS", "Web" |
| **Version** | `App Version: 2.4.2` style patterns |
| **Steps** | Numbered/bulleted lines under a `Steps to Reproduce:` header |
| **Impact** | Text under the `Impact:` label |
| **Reproducibility** | "100%", "every time", "intermittent" etc. |

If the title has no module tag, we add one ourselves (`[Checkout]`,
`[Cart]`, `[Chat/AI]`, etc.) by matching keywords in the subject line.

**Why rules, not LLM?** The email format is well-known (it's our own
team), so deterministic parsing is fast, free, and predictable. The
LLM version (`main.py`) is available when format drift becomes a real
problem.

---

## 3. Finding similar past bugs (TF-IDF cosine similarity)

Once we have a parsed bug, we compare its text to every recent bug in
the FLIPPI Jira project to find the closest matches.

### The intuition

Think of each bug as a bag of words. We turn each bag into a numeric
vector, then measure the **angle** between two vectors. If the angle is
small, the bugs talk about the same things.

* **TF (term frequency)** — words that appear often in *this* bug get more weight.
* **IDF (inverse document frequency)** — words that appear in *every* bug (like "user", "app", "issue") get less weight, because they don't help distinguish bugs.
* **Cosine similarity** — measures angle between vectors; ranges from 0 (totally different) to 1 (identical).

### The setup

* Index built once over the **last 300 FLIPPI bugs** (their `summary + description`).
* Vectorizer uses **bigrams** ("proceed to pay", "force kill") in addition to single words, so phrases matter, not just isolated tokens.
* English stop words are removed ("the", "a", "is" …) before vectorizing.
* Vocabulary capped at 10,000 features to keep it fast (subsecond) and avoid noise from one-off typos.

### Output

For each new bug we return the **top 5** matches, each with:

* Jira key + clickable URL
* Summary
* Similarity score (0.000 – 1.000)
* Assignee
* Priority

### Thresholds (tuned by hand against real FLIPPI data)

| Threshold | Meaning |
|---|---|
| **≥ 0.38** | Likely **duplicate** — flag for engineer to verify and link |
| **≥ 0.20** | Strong enough to **vote on priority** (used in Layer 3 below) |
| **≥ 0.12** | Worth **showing** as a similar bug in the report |

These thresholds are deliberately lower than what you'd see with a
neural embedding model (which would give 0.8+ for the same pair),
because TF-IDF scores are absolute word overlap, not semantic distance.

### Why not embeddings?

The original `main.py` used sentence-transformers (a neural model). We
switched the prototype to TF-IDF because:

1. No GPU / no model download / no API key needed.
2. Faster on first run (no model warm-up).
3. **Good enough** at ≥ 0.38 for duplicate detection — verified against
   the real FLIPPI-3044, FLIPPI-2905, FLIPPI-2902 dedup cases.

Production swaps this for Vector One (managed vector DB with real
embeddings). The logic above stays the same — only the engine changes.

---

## 4. Detecting duplicates

Simple rule on top of the similarity engine:

> If the **top match's** similarity is **≥ 0.38**, mark this bug as a
> duplicate candidate of that ticket.

We never auto-merge. The output JSON says
`duplicate_of: "FLIPPI-2905", duplicate_confidence: 0.41` and the
engineer decides whether to link.

When a duplicate is detected, the new bug **inherits the priority** of
the duplicate (a P0 dup is a P0 — see Layer 1 below).

---

## 5. Classifying which team owns the bug (6-way routing)

Every bug must go to one of 6 SLAP teams. We classify by **priority-ordered
keyword matching** on `title + body`.

| Team | Owns | Example keywords |
|---|---|---|
| **Immersive** | Native AR, VTO SDK, ANRs | "native AR", "VTO SDK", "drishyamukh", "ANR" |
| **BE_Labs** | VTON, Feed ML, Social Finds, Review Synth | "VTON", "virtual try", "social finds", "decoded looks" |
| **DS** | NPS, %Positive, model quality, ranking | "NPS", "%positive", "model quality", "discrepancy" |
| **UI** | React Native, iOS/Android visuals | "cold start", "screen flash", "image not loading", "React Native" |
| **BE_Flippi** | Chat AI, search, cart, checkout, auth | "checkout", "cart", "search", "Grayskull", "OTP", "thinking…" |
| **bugs** | Unclassifiable — manual routing | (default if nothing matches) |

**Order matters.** We check Immersive first, then BE_Labs, then DS,
then UI, then BE_Flippi, then fall through to `bugs`. This is because
a "VTON gender mismatch" bug mentions both "VTON" (BE_Labs) and "gender"
(could match BE_Flippi) — by checking BE_Labs first, we route it correctly.

When the result is `bugs`, the ticket draft leaves the `components`
field empty (no wrong team gets assigned). The team label is still
written to `triage_notes.team` so the on-call engineer knows it needs
manual routing.

---

## 6. Suggesting an owner

A trivial but effective heuristic:

> Count assignees across the top similar bugs. Suggest the **most
> frequent** one.

If 3 of the top 5 similar bugs were assigned to Shailja Rani, we
suggest Shailja Rani — with the reason
`"Assigned to Shailja Rani on 3/5 most-similar past bugs."`

If no similar bug has an assignee, we say so and skip the suggestion.

This isn't a smart matcher, but it works because the same engineer
typically owns the same area of the codebase over time.

---

## 7. Scoring priority (the 4-layer cascade)

This is the most complex piece. We use **four layers**, applied in
order. The **first confident signal wins** — we don't average across
layers, because each layer is meant to catch a different kind of bug.

The reasoning behind a layered approach: no single technique handles
every bug. Keywords catch the obvious cases. Templates catch the
paraphrases. Similar-bug voting catches the bugs that look just like
something we've seen before. Impact-text fallback handles the rest.

Every output JSON includes `triage_notes.priority_scoring_path` showing
which layer decided — so we can debug or tune later.

### Layer 1 — Keyword signals (fast, specific)

Regex patterns matched against the bug's combined text:

| Bucket | Fires when… | Priority |
|---|---|---|
| **P0 hard** | Any one matches (e.g. `app crashes`, `proceed to pay`, `Grayskull`, `all users`, `revenue-blocking`) | → P0 |
| **P0 soft + 100% repro** | A softer P0 hint AND reproducibility = 100% | → P0 |
| **P1 hard** | Any one matches (`ANR`, `wrong recommendation`, `ignores budget`, `30% of users`, `trust in the AI`) | → P1 |
| **P1 soft** | Two or more soft hints (`majority`, `login failing`, `affects all platforms`) | → P1 |
| **Duplicate inheritance** | Top similar bug is P0/P1 *and* it's a duplicate | → match priority |
| **P2 signals** | Any match (`image not loading`, `slow network`, `workaround`, `tier 2`) | → P2 |

**Smart crash detection.** A naive `\bcrash\b` would fire on phrases
like "no crash logs" or "didn't see any crash" — false positive. So we
only match active voice: `app crashes`, `crashes to home`, `crash on launch`.

**Scope phrases.** `all \w+ users` catches "all male users", "all iOS
users", "all Android orders" — different shape, same scope signal.

### Layer 2 — Template scoring (handles paraphrases)

Layer 1 misses bugs that don't use the exact phrasing. Example:

> "The NPS score shows different values than the FK main app."

No keyword fires. But it's clearly a P1 data-discrepancy issue.

So we built a second TF-IDF model — this time over **template sentences**
we wrote ourselves, ~10 per priority level (~40 total). Each template
represents a *way of saying* a P0/P1/P2/P3 problem. Examples:

| Priority | Sample template |
|---|---|
| P0 | "app crashes force closes users cannot complete purchase" |
| P0 | "secrets credentials exposed security vulnerability production" |
| P1 | "ai ignores price budget constraint recommends expensive wrong products" |
| P1 | "wrong gender profile shown personalization incorrect wrong recommendations" |
| P2 | "images not loading slow network no retry broken placeholder missing" |
| P3 | "minor cosmetic issue alignment spacing low priority edge case" |

The incoming bug is vectorized against these templates. The priority
with the highest-scoring template **above its threshold** wins.

| Priority | Min cosine similarity |
|---|---|
| P0 | 0.28 |
| P1 | 0.22 |
| P2 | 0.18 |
| P3 | 0.15 |

The NPS example above scores **0.52** against P1 templates — classified
correctly without any keyword match.

### Layer 3 — Weighted similar-bug voting

If neither keywords nor templates fire, we fall back to: *what priority
did the most similar past bugs have?*

For every similar bug with similarity ≥ 0.20:

* Convert its priority to a number (P0 = 0, P1 = 1, P2 = 2, P3 = 3).
* Multiply by its similarity score (higher similarity = louder vote).
* Average the weighted votes; convert back to a priority bucket.

Only fires if the **total weight ≥ 0.25** — otherwise we don't have
enough signal to trust this layer.

Example: 3 past bugs at similarity 0.22, 0.21, 0.20, all P1.
Weighted average = 1.0 → P1.

### Layer 4 — Impact-text fallback

Last resort. Scan the `Impact:` field for words:

* `blocking`, `revenue`, `all users`, `zero` → P0
* `significant`, `majority`, `trust`, `multiple` → P1
* `subset`, `some users`, `workaround` → P2
* anything else → P2 (safe default)

Used when the bug is too short or unusual for any earlier layer to fire.

### Vague-report safety net

If the bug is **under 350 characters AND has no steps to reproduce**,
we classify it as P3 with the note *"re-triage once more context is
provided."* This protects against accidentally scoring a 2-line "the app
is broken" message as P0.

---

## 8. What the output looks like

Every run writes a JSON file to `output/`:

```json
{
  "parsed_bug": { /* extracted fields */ },
  "jira_ticket_draft": { /* ADF Jira JSON, ready to paste */ },
  "triage_notes": {
    "team": "BE_Flippi",
    "jira_component": "Backend",
    "priority_scoring_path": "L1-keyword: app crash(?:es|ed)\\b",
    "severity_justification": "100%-reproducible crash on Android directly blocks the core conversion flow…",
    "owner_suggestion": "Shailja Rani",
    "owner_reason": "Assigned to Shailja Rani on 3/5 most-similar past bugs (similarity ≥ 0.12).",
    "duplicate_of": null,
    "duplicate_confidence": 0.182,
    "similar_bugs": [
      { "key": "FLIPPI-1663", "similarity": 0.181, "priority": "P0", "url": "…" },
      …
    ]
  }
}
```

The `priority_scoring_path` and `severity_justification` together
make every decision **auditable** — a reviewer can see exactly which
layer fired and why.

---

## 9. Where this is limited (honest list)

| Limitation | Mitigation in production |
|---|---|
| TF-IDF misses true semantic synonyms ("car" vs "vehicle") | Vector One with real embeddings |
| Keyword lists need maintenance as new bug patterns emerge | LLM-based scoring (Genvoy / FK-GPT) |
| Owner heuristic is "most frequent past assignee" — doesn't account for who left the team | Pull from team roster + on-call rotation |
| Component routing has 6 buckets; new product areas need code change | LLM-based classification with team docs as context |
| Index of 300 bugs — older bugs are not considered | Full corpus via managed vector DB |
| Single-bug analysis — doesn't detect bug *clusters* (e.g. 5 similar reports in 1 day) | Stream-based dedup at intake |

None of these are blockers for the prototype — they're conscious
trade-offs to keep the agent fast, deterministic, and dependency-free.

---

## 10. Why we trust it

* Every classification produces a **scoring path** field — no hidden logic.
* The agent **never writes to Jira** — it cannot accidentally re-prioritize a real ticket.
* The duplicate threshold (0.38) was tuned against real FLIPPI dedup cases (3044, 2905, 2902).
* The 15-bug test suite covers every priority level (P0–P3) and every team component.
* The Claude-API pipeline (`main.py`) exists as a higher-accuracy fallback once API access is available — same data contract, swap one module.
