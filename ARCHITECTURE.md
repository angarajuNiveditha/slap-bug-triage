# SLAP Bug Triage — Architecture Reference

The full design of the multi-agent triage pipeline as it stands today.
Read this when you want to extend the system, modify a sub-agent, or
hand the prototype off to someone new.

For a higher-level overview, see [`README.md`](README.md).
For the rule-based simulation harness, see [`TRIAGE_LOGIC.md`](TRIAGE_LOGIC.md).

---

## 1. System overview

The system has three pipelines that all produce the same output shape
(a Jira ADF draft + a `triage_notes` JSON block), so a reviewer can
compare results across them on the same input:

| Entry point | Pipeline | Role today |
|---|---|---|
| `run_multi_agent.py` | Multi-agent Claude (this doc) | **Primary** — used for real triage and the demo. Reads images, runs semantic similarity over the full historical corpus, makes auditable per-stage decisions. |
| `run_agent.py` | Rule-based (regex + TF-IDF + multi-layer scorer) | **Simulation harness** — fast iteration, deterministic, no LLM cost. Used for batch reruns, regression baselines, and as a fallback when Claude allotment is constrained. |
| `main.py` | Anthropic SDK | **Production-shape reference** — blocked on `ANTHROPIC_API_KEY` (corp network restriction), kept for the eventual swap to FK-GPT or Bedrock. |

This document covers the **multi-agent Claude pipeline** in detail. The
rule-based pipeline is documented in `TRIAGE_LOGIC.md`.

---

## 2. The multi-agent pipeline

### 2.1 Host agent + five sub-agents

A host agent (`src/agents/host_agent.py`, called **Astral** internally to
match Flipkart's production naming) coordinates five sub-agents. Each
sub-agent is a single focused Claude prompt with one job:

```
                            ┌────────────────────────┐
       email + images  ────►│      HOST AGENT        │◄──── 300 historical bugs
                            │       (Astral)         │       (cached from Jira)
                            └───┬────────────────────┘
                                │
              ┌─────────────────┼────────────────┬─────────────┬────────────┐
              ▼                 ▼                ▼             ▼            ▼
        ┌──────────┐      ┌──────────┐    ┌───────────┐  ┌────────┐  ┌──────────┐
        │  Media   │  →   │  Parser  │ →  │Embeddings │→ │ Dedup  │→ │  Triage  │
        │ (vision) │      │  (text)  │    │(retrieval)│  │ (judge)│  │ (priority)│
        └──────────┘      └──────────┘    └───────────┘  └────────┘  └──────────┘
              │                 │              │             │            │
              └─ findings ──────┴── BugReport ─┴── ranked ───┴── dup? ────┴── severity
                                                  candidates
                                                                                │
                                                                                ▼
                                                                        ┌─────────────┐
                                                                        │ build_ticket│
                                                                        └─────────────┘
                                                                                │
                                                                                ▼
                                                                       Jira ADF + triage_notes
```

| Sub-agent | File | Responsibility | Inputs | Output type |
|---|---|---|---|---|
| **Media** | `src/agents/subagent_media.py` | Read screenshots (and later audio/video), identify the SLAP screen, extract visible text, spot anomalies, flag email-vs-image contradictions. | `image_paths`, `email_text`, SLAP context | `MediaResult` (per-image findings + combined summary) |
| **Parser** | `src/agents/subagent_parser.py` | Turn the raw email + media-findings summary into a structured `BugReport`. | `raw_text`, optional `media_summary` | `BugReport` dataclass |
| **Embeddings** | `src/agents/subagent_embeddings.py` | Rank top-K most similar historical bugs from a one-time cached corpus of 300 FLIPPI tickets; suggest an owner. | `BugReport`, cached 300 issues | `EmbeddingsResult` (ranked `SimilarBug`s + owner suggestion) |
| **Dedup** | `src/agents/subagent_dedup.py` | Focused dup-or-not call over the top-K candidates with a 0.80 confidence threshold. | `BugReport`, top-K candidates | `DedupResult` (key + confidence + reasoning, or null) |
| **Triage** | `src/agents/subagent_triage.py` | Assign P0/P1/P2/P3 with a plain-English justification grounded in scope, reproducibility, and similar bugs. | `BugReport`, top-K similar | `SeverityResult` |

### 2.2 Why the host + sub-agent split (vs. one big prompt)

Three reasons:

1. **Auditability.** Each sub-agent's reasoning is recorded in
   `triage_notes`. You can see why dedup said "yes" and why triage said
   "P1" independently. A monolithic prompt loses that.
2. **Independent tuning.** The dedup confidence threshold (currently
   `0.80`) can be tuned without touching how similarity is ranked. The
   triage prompt can grow without bloating the embeddings prompt.
3. **Production-shape match.** The Flipkart production diagram already
   has these as separate sub-agents under Astral. Prototype shape
   matches production shape; the swap is one transport-layer change
   per sub-agent.

### 2.3 Why Claude Code in headless mode (vs. the SDK)

`src/claude_cli.py` wraps `subprocess.run(["claude", "-p", prompt, …])`.
This uses Claude Code's non-interactive mode and authenticates via the
locally signed-in account — **no `ANTHROPIC_API_KEY` required**. That
matters because `console.anthropic.com` is blocked on the Flipkart
corporate network.

The wrapper also accepts:

- `add_dirs=[...]` — grants Claude `Read` access to specific folders
  (used by the media sub-agent for the SLAP reference screens + the
  bug-attachment folder).
- `allowed_tools=[...]` — explicit tool allow-list (e.g. `["Read", "Glob"]`).

The binary path is resolved at import time with a priority chain:
`CLAUDE_BIN` env var → `claude` on `$PATH` → Claude Desktop's bundled
CLI in `~/Library/Application Support/Claude/claude-code/<ver>/`. The
last fallback exists because some corporate endpoint-security tools
delete brew-installed binaries; the Claude Desktop app's bundled CLI
lives inside the app's own data dir, which is trusted.

---

## 3. Data flow (one bug, end to end)

Concrete walkthrough of what happens when a user clicks **Triage this
bug** with the email `bug_01_p0_checkout_crash.txt` and no attachments:

```
1. Streamlit/CLI calls HostAgent.triage(raw_text, image_paths=[])
2. image_paths is empty → media sub-agent SKIPPED, media = empty
3. Parser sub-agent (Claude call ~5s):
       prompt = parser template + email text
       response → BugReport(title="[Checkout]:...", platform="Android",
                            steps_to_reproduce=[5 steps], component_hint="Backend", ...)
4. Embeddings sub-agent (Claude call ~30–60s):
       prompt = embeddings template + new bug + 300 historical bugs (JSON)
       response → top-5 candidates with similarity 0.0-1.0,
                  suggested_owner + reasoning
5. Dedup sub-agent (Claude call ~5s):
       prompt = dedup template + new bug + top-5 candidates
       response → duplicate_of=FLIPPI-1198 (confidence 0.85) OR null
6. Triage sub-agent (Claude call ~5s):
       prompt = triage template + bug + top-5 similar
       response → priority=P0, severity=Blocker, justification=...
7. Assemble SimilarityResult (merges embeddings + dedup outputs)
8. build_ticket(bug, severity, similarity) → TicketDraft (ADF + triage_notes)
9. Annotate triage_notes with:
       pipeline="multi-agent (Astral)"
       media_findings (if any)
       media_combined_summary (if any)
       duplicate_reasoning (if dedup fired)
10. detect_quality_issues(bug, media) → quality_issues (if any)
       — vague_report      : raw email missing 2+ required section headers
       — media_contradicts_text : any media finding has contradicts_email_claim
11. Return HostResult — entry-point script serializes to output_claude/<...>.json
```

For an image-attached bug the only change is **step 2**:

```
2. image_paths is non-empty → media sub-agent runs:
   - subprocess: claude -p <prompt> --add-dir <bug_folder> --add-dir <slap_context>
                                    --allowedTools Read,Glob
   - prompt includes: SLAP_KNOWLEDGE.md path, reference_screens dir,
                       verbatim email body, list of bug image paths,
                       CONTRADICTION DETECTION instructions
   - Claude uses Read to load each image and the SLAP knowledge doc,
     returns per-image findings + a combined_summary
   - combined_summary gets prepended to the email body before the
     parser runs (so the parser sees the visual evidence)
```

---

## 4. SLAP context (`slap_context/`)

The media sub-agent's accuracy depends on giving Claude the right
SLAP-specific vocabulary. The `slap_context/` folder is the
single source of truth for that domain knowledge.

- **`SLAP_KNOWLEDGE.md`** (committed) — extracted from the SLAP-2026
  Figma file (393 frames, 198 unique screen names, 1117 unique strings).
  Sections: product overview, vocabulary (chat/PDP/price/VTON/onboarding/auth/nudges),
  screen catalog (with reference-image filenames), component-to-team
  routing recap, and **visual cues that flip the triage decision**
  (e.g. *"`Hi ,` with no name → persona load failed → Backend regression"*).
- **`reference_screens/`** (gitignored) — 16 labelled Figma PNG exports
  used by the media sub-agent as canonical screen references at runtime.
  Local-only because the designs are unreleased product IP.

The media sub-agent's prompt has Claude `Read` both before analyzing
the bug attachments. This is what lets it identify a screenshot as
e.g. `"Cart (full view)"` or `"Phone login / OTP"` instead of just
"some product page."

### 4.1 Video attachments

The media sub-agent handles videos in addition to images. The dispatch
is internal to `src/agents/subagent_media.py`:

| Aspect | Detail |
|---|---|
| **Accepted extensions** | `.mp4 .mov .webm .avi .mkv .m4v` |
| **Pre-processor** | `ffmpeg` from `imageio-ffmpeg` (no system install required — binary lives inside `site-packages/imageio_ffmpeg/binaries/`) |
| **Keyframe strategy** | Scene-change detection (threshold 0.30) capped at `MAX_KEYFRAMES = 8`. Fallback to evenly-spaced sampling if scene-detect yields 0 frames on a static clip. |
| **Duration cap** | `MAX_VIDEO_DURATION_SECONDS = 60`. Longer videos return a `state="rejected"` MediaFinding with a clear `one_line_summary` — no Claude call wasted, refile prompt fires through the same UX path. |
| **Audio** | Not transcribed in this iteration. Whisper / `faster-whisper` integration is intentionally deferred. |
| **Claude calls** | One Claude call **per video** (not per frame) so the prompt can ask for **sequence reasoning** — what action does the user take across frames, where is the failure moment, what's the final state. |
| **Output shape** | One `MediaFinding` per video. The `kind` field disambiguates from images; video-only fields (`screen_sequence`, `action_observed`, `failure_moment`, `frame_count`, `duration_seconds`, `frames`) are populated alongside the existing common fields. |
| **Frame lifecycle** | Keyframes are written into a `tempfile.mkdtemp(prefix="slap_video_frames_")` directory. We don't context-manage that dir because the Streamlit UI reads the frame paths after the sub-agent returns. Tempdirs accumulate in `/tmp` and the OS cleans them; acceptable for a prototype. |

The combined_summary returned by `MediaResult` aggregates across both
images and videos — image batch summary first, each video's
`one_line_summary` appended — so the parser sub-agent sees one unified
evidence narrative regardless of attachment type.

### 4.2 Why one Claude call per video (not per frame)

A video tells you more than a stack of independent screenshots because
of the **temporal ordering**. "User taps Proceed to Pay → spinner →
crash to home" is qualitatively different from three random
screenshots of the same screens. Asking Claude to reason about all
keyframes in one call preserves that ordering. The trade-off — that
each video costs N× an image's vision-token budget — is acceptable
given the 8-frame cap.

---

## 5. Quality gating (the refile path)

Not every report is good enough to triage. The host agent runs two
quality checks after building the draft and surfaces them under
`triage_notes.quality_issues`:

### 5.1 `vague_report` (format compliance)

Scans the **raw email text** (not the parsed fields — see why below)
for required section headers:

| Section | Accepted header patterns (case-insensitive) |
|---|---|
| Steps to Reproduce | `steps to reproduce`, `reproduction steps`, `repro steps`, `Steps:` |
| Expected Result | `Expected:`, `expected result`, `expected behaviour` |
| Actual Result | `Actual:`, `actual result`, `actual behaviour` |
| Impact | `Impact:`, `user impact`, `business impact` |
| Reproducibility | `Reproducibility:`, `Repro:`, `repro rate`, `frequency:` |
| Environment | `Environment:`, `Platform:`, `App version:`, `Device:`, `OS version` |

If **two or more** sections are missing, the report is flagged. A
short body (under 300 chars) also adds a "too short" reason.

**Why check raw text instead of parsed fields:** the parser sub-agent
(Claude) is too lenient — when an email doesn't have an explicit
`Impact:` section but mentions impact inline, Claude infers a value
and fills the parsed field. So checking parsed fields lets
format-incomplete reports through. The raw-text check is purely about
format compliance and isn't affected by parser inference.

### 5.2 `media_contradicts_text`

Trusts the media sub-agent's `triage_signals.contradicts_email_claim`.
The media sub-agent receives the email body, the image, and the SLAP
context, and is prompted aggressively about when to flag — e.g. the
example case `[Checkout]:`-tagged email with a Phone-login screenshot
is explicitly called out.

When this fires, the issue includes the contradiction text Claude
produced — so the reviewer sees *why* the agent thinks the inputs
disagree, not just *that* they do.

### 5.3 UI behaviour on quality issues

When `quality_issues` is non-empty, the Streamlit UI:

1. Renders a red banner: **"This bug cannot be triaged confidently."**
2. Lists one card per issue with the kind chip, message, and
   "What to do" line.
3. Shows a **Refile this bug** button.
4. Calls `st.stop()` — the tentative draft (metric tiles, tabs) is
   NOT rendered, because the input wasn't good enough to draft from.

The Refile button:

1. Wipes every input-related `session_state` key (with a guard to
   skip `input_version` itself).
2. Bumps `input_version`, which is suffixed onto the sample picker,
   textarea, and file uploader keys — Streamlit treats them as new
   widgets on the next rerun, reverting them to defaults.
3. Calls `st.rerun()`.

Net effect: the page returns to its initial state (empty textarea,
no attachments, "(paste your own)" picker, multi-agent radio default).

---

## 6. The output JSON

Every run writes a JSON file to `output_claude/` with this shape:

```json
{
  "generated_at": "2026-06-17T19:30:03.123",
  "input_label":  "bug_prices_showing_zero",
  "pipeline":     "multi-agent (Astral)",
  "attachment_count": 1,
  "parsed_bug": {
    "title":           "[Price]: Muesli cards showing ₹0 ...",
    "platform":        "iOS",
    "app_version":     null,
    "component_hint":  "Backend",
    "reproducibility": "consistent",
    "reporter":        "Aditya Joshi <aditya.joshi@flipkart.com>"
  },
  "jira_ticket_draft": {
    "fields": {
      "project":      { "key": "FLIPPI" },
      "issuetype":    { "id": "10036" },
      "summary":      "[Price]: Muesli cards showing ₹0 ...",
      "priority":     { "id": "10001" },
      "description":  { /* ADF document */ },
      "components":   [{ "name": "Backend" }],
      "labels":       ["slap", "agentic-triage", "be-flippi", "ios"],
      "customfield_10331": { "value": "Critical" }
    }
  },
  "triage_notes": {
    "pipeline":               "multi-agent (Astral)",
    "team":                   "BE_Flippi",
    "jira_component":         "Backend",
    "priority_scoring_path":  "claude-llm: ₹0 price display, ...",
    "severity_justification": "Prices displaying as ₹0 directly suppresses purchases...",
    "owner_suggestion":       "Veeramreddy ChakradharReddy",
    "owner_reason":           "Assigned to three of the five closest matches...",
    "duplicate_of":           "FLIPPI-1620",
    "duplicate_confidence":   0.82,
    "duplicate_reasoning":    "Both reports are about prices rendering as ₹0...",
    "similar_bugs": [
      { "key": "FLIPPI-1620", "url": "...", "similarity": 0.82, ... },
      ...
    ],
    "media_findings": [
      {
        "image_path":       "/.../screenshot.png",
        "screen":           "15 Minutes category browse",
        "state":            "error",
        "visible_text":     [...],
        "error_indicators": [...],
        "ui_anomalies":     [...],
        "device_hints":     { "platform": "iOS", ... },
        "triage_signals": {
          "likely_component":         "Backend",
          "severity_hint":            "P1",
          "contradicts_email_claim":  null
        },
        "one_line_summary": "..."
      }
    ],
    "media_combined_summary": "...",
    "quality_issues": [
      /* present only when refile is required */
    ]
  }
}
```

The `triage_notes` block is the durable contract — the Streamlit UI
and the test pack read it; downstream tools should too.

---

## 7. Component routing (6 teams)

Every bug is routed to one of six Flipkart team labels. The parser
sub-agent assigns `component_hint`; the ticket builder maps it to a
Jira component:

| Team label | Jira component | Jira ID | Owns |
|---|---|---|---|
| **BE_Flippi** | `Backend` | 14386 | Chat AI, search, cart, checkout, price, session, auth, onboarding, infra |
| **BE_Labs** | `Backend-Labs` | 14385 | VTON, Feed ML, Social Finds, Review Synth, Machine Identity, Decoded Looks |
| **DS** | `DS` | 14384 | NPS, %Positive, product page analytics, model quality, ranking |
| **UI** | `UI` | 14383 | React Native, iOS/Android rendering, image loading, login screen flashes |
| **Immersive** | `immersive` | 14387 | Native AR, VTO SDK, ANRs, drishyamukh-core |
| **bugs** | *(no component)* | — | Unclassifiable — needs manual routing |

The parser prompt encodes the priority-ordered keyword classification
rules; when classification falls through to `"bugs"`, the ticket
builder leaves the Jira `components` field empty so the ticket lands
in the manual-triage queue.

---

## 8. Production mapping

Each piece of the prototype has a direct production counterpart:

| Prototype | Production |
|---|---|
| Bug report `.txt` file | Gmail email via `fk-mart-ai-pulse` |
| `run_multi_agent.py` (entry point) | Astral agent runtime |
| `subagent_*` Claude calls (via `claude -p`) | Genvoy / FK-GPT internal LLM gateway, or AWS Bedrock |
| Sub-agent imports | Synapse (auth/routing) |
| 300-bug embeddings cache | Vector One (managed vector DB) |
| Jira REST (read) | Jira via MART MCP |
| Output JSON | Pulse SMTP reply to reporter |

The swap is roughly **one line per sub-agent** — change the
`call_claude(...)` call in `src/claude_cli.py` to an HTTP request to
the production gateway. All prompts, output shapes, business rules
(dedup threshold, quality gating, component routing, ADF builder)
stay the same.

---

## 9. Design decisions log (most recent first)

Decisions worth remembering, with brief rationale.

### D-10: Video attachments share `subagent_media` rather than a separate sub-agent

We considered a `subagent_video.py` parallel to `subagent_media.py`.
Decided against it. Reasons:
  - Most bugs will have at most one or two attachments — the
    "switchboard" overhead at the host-agent layer is unnecessary
    duplication.
  - Image and video processing share the same SLAP context, the same
    contradiction-detection rules, and the same output type
    (`MediaFinding`). Splitting them would re-duplicate all of that.
  - The dispatch is by file extension and lives inside a single
    `process_attachments` function — three lines of routing logic, no
    abstraction needed.

So a single `src/agents/subagent_media.py` handles both kinds: images
go through `_process_images` (one Claude call for the whole batch),
videos go through `_process_one_video` (one Claude call per video,
preceded by ffmpeg keyframe extraction). The host agent doesn't know
the difference.

Audio transcription was intentionally deferred — adding `faster-whisper`
is a separate decision to make when we actually have videos with
narration that matters.

### D-09: Drop the structural cross-check, trust Claude's contradiction flag

Originally `detect_quality_issues` had two contradiction detectors:
(a) Claude's `contradicts_email_claim` field, and
(b) a rule-based fallback that compared the bug-title's module tag
    against the media-finding's screen name as a substring.

The rule-based fallback false-fired on screen names that didn't
include the title's keyword (e.g. `"15 Minutes — category-browse view"`
was correctly identified as a price bug but the screen string didn't
include "price"). The original reason for the fallback — Claude
returning `null` for the obvious checkout-vs-OTP mismatch — was
already fixed by passing the email body into the media sub-agent's
prompt. The fallback is now removed entirely.

### D-08: Vague-check reads raw email text, not parsed fields

The parser sub-agent infers values for missing sections when the
email mentions the concepts inline, so checking parsed fields
(`bug.impact == "Not provided."`) misses format-incomplete reports.
The current vague-check scans the **raw email text** for section
headers (`Impact:`, `Reproducibility:`, `Environment:`, etc.) and
fires when 2+ are missing.

### D-07: Don't delete `input_version` when wiping session state

The Refile handler used to wipe every session-state key starting
with `input_` — which included `input_version` itself (the counter
that suffixes widget keys). After the wipe the next line tried to
bump the counter and silently no-op'd, the counter stayed at 0, the
widget keys didn't change, and the textarea kept its previous text
on rerun. The fix skips `input_version` in the delete loop.

### D-06: Multi-detector approach for contradictions (now superseded by D-09)

Originally both Claude's semantic flag AND a structural check fed
`quality_issues`, deduped on `(image, screen)`. D-09 removed the
structural check.

### D-05: Pass email body to media sub-agent

The media sub-agent originally only saw the image + SLAP context, so
`contradicts_email_claim` always defaulted to null — Claude had
nothing to compare against. The host now passes `email_text` to
`process_attachments(...)`, and the prompt has an explicit
CONTRADICTION DETECTION section with the checkout-vs-OTP example.

### D-04: Split dedup out of embeddings

Originally `claude_similarity.py` combined ranking and the duplicate
decision into one call. Splitting them into
`subagent_embeddings.py` (ranks only) and `subagent_dedup.py`
(focused dup-or-not) matches the production diagram and makes the
0.80 confidence threshold independently tunable.

### D-03: Multi-agent shape: host + sub-agents (not autonomous agents)

The Flipkart production diagram has Astral as a coordinator dispatching
to specialized sub-agents. Each sub-agent is a focused Claude prompt
with one job, called in a deterministic order by the host. The
alternative — autonomous agents that decide for themselves what to
do — was rejected as overkill: the triage tasks are well-defined
and don't benefit from autonomy.

### D-02: Claude Code headless mode, not the Anthropic SDK

`console.anthropic.com` is blocked on the Flipkart corporate network,
so we can't obtain an `ANTHROPIC_API_KEY`. Claude Code's `-p` flag
gives us non-interactive access using the local signed-in session.
Production will swap this for the FK-GPT internal gateway via HTTP.

### D-01: Keep the rule-based pipeline as a simulation harness

`run_agent.py` (regex + TF-IDF + multi-layer scorer) runs in ~35 ms
per bug with zero cost. It's preserved as a simulation harness for
fast iteration, deterministic regression baselines, and demos when
Claude allotment is constrained. It produces the **same** output
contract as the multi-agent pipeline, so they're directly comparable.

---

## 10. Known limitations

| Limitation | Production answer |
|---|---|
| Per-bug latency ~90–150 s (multi-agent) | Acceptable for one-off triage; not real-time. Production gateway (FK-GPT) caches prompts across runs. |
| Stochastic — same input may give slightly different rankings | Always show reasoning so reviewers can validate. Re-run for stability if needed. |
| Headless mode needs a Claude-Code-authenticated machine | Production runs through FK-GPT / Bedrock — same prompts, no Claude Code dependency. |
| 300-bug Jira window only | Full corpus via Vector One in production. |
| One bug at a time — doesn't detect bug clusters | Stream-based dedup at intake in production. |
| Audio + video attachments not yet supported | Roadmap: Whisper transcription + ffmpeg keyframe extraction; output contract unchanged. |
| Reference screens are unreleased design IP | `slap_context/reference_screens/` is gitignored; lives local-only on each dev machine. |

---

## 11. Quick references

| Want to … | Open |
|---|---|
| Change a sub-agent's prompt | `src/agents/subagent_*.py` |
| Change the dedup threshold | `subagent_dedup.DUPLICATE_CONFIDENCE_THRESHOLD` (default 0.80) |
| Change the vague threshold | `host_agent.MAX_MISSING_SECTIONS` (default 2) |
| Change which sections count toward "vague" | `host_agent.REQUIRED_SECTION_PATTERNS` |
| Change the priority colours | `app.py` CSS (`.mtile.prio-P0` ... `.mtile.prio-P3`) |
| Change the host orchestration order | `HostAgent.triage` in `src/agents/host_agent.py` |
| Add a new SLAP screen reference | drop the PNG into `slap_context/reference_screens/` + describe it in `slap_context/SLAP_KNOWLEDGE.md` |
| Add a new sample bug | `data/bug_*.txt` (text) or `data/bug_with_media/<folder>/{email.txt, screenshot.png}` |
| Regenerate the test pack | `python3 tests/_build.py && python3 tests/_run_claude.py` |

---

_Last updated: 2026-06-17. If you change something architectural, add
an entry to §9 (Design decisions log) so future-you knows why._
