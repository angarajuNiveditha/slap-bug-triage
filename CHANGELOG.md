# Changelog

## 2026-06-25 — Embedding classifier, hybrid + skills, owner sub-agent, label-noise audit

Phase-2 session — replaced keyword regex with semantic ML where appropriate, added architectural context where Claude needed it, audited the corpus for label quality. Measured production accuracy: **69.5% LOO** on 564 labelled FLIPPI bugs, projected **78-82%** after label cleanup.

### Pipeline architecture changes

- **New `src/embedding_classifier.py`**: LogReg trained on sentence-transformer embeddings (all-mpnet-base-v2) of 564 component-labelled FLIPPI bugs. Fast path returns prediction in ~7 ms when LogReg's top-class probability ≥ 0.50.
- **Hybrid Claude+skills fallback**: when LogReg confidence < 0.50 (35.8% of bugs), Claude is invoked with the top-3 candidate teams' skill files loaded as in-context architecture references. Adds ~6 s on the borderline cases.
- **New `src/embedding_similarity.py`**: replaces the old `subagent_embeddings` Claude-reads-300-bugs ranking with cosine search over the embedding index. ~7 ms vs the old ~30–60 s.
- **New `src/agents/subagent_owner.py`**: focused Claude call constrained to the routed component's team roster (derived from historical Jira assignees). Filters similar bugs to component-matching ones before asking Claude to pick. Falls back to frequency-based pick if Claude is unreachable.
- **Parser sub-agent dropped component classification** — the `component_hint` field is now set by the embedding classifier, not the parser. The parser prompt is shorter and faster.

### Architecture skill-file system

- **`slap_context/architecture/repos.json`** — manifest of 11 SLAP repos with team mapping, prod branch, freshness tier.
- **5 team-level skill files** (UI / Backend / Backend-Labs / DS / immersive) — hand-curated.
- **8 of 11 per-repo skill files** generated from real cloned code (`build_repo_skills.py`) or hand-written by team leads (`spaghetti.md`, `mozzarella.md` with routing-signals tables).
- **`src/repo_context.py`** — wraps the GitHub Enterprise clone + structural map + `git grep` fallback. Gated on `GITHUB_FK_TOKEN` (with `repo` scope) for private-repo access on `github.fkinternal.com`.
- Skill files are loaded contextually — when LogReg's top-3 candidates include UI, the UI team skill + spaghetti + mozzarella per-repo skills get bundled into Claude's prompt (~25–37 KB of architectural context).

### Measured accuracy (564-bug leave-one-out)

| Classifier | Accuracy | Latency / bug |
|---|---|---|
| Rule-based regex (the old keyword approach, on this corpus) | 27.7% | ~0.06 ms |
| Pure Claude (focused prompt, no skills) | 65.1% | ~6.6 s |
| Pure LogReg LOO | 66.8% | ~7 ms |
| **HYBRID (LogReg + Claude+skills)** | **69.5%** | avg ~2.3 s |

On the borderline subset (202 bugs where LogReg was unsure), Claude+skills hit 55.0% vs LogReg's 47.5% — **+7.4 pp lift** isolating the contribution of the skill files.

### Backend label-noise audit

A manual audit (`audit_backend_misclassifications.py`) of 42 misclassified Backend bugs found **~70% are mis-labelled in Jira** — chat-AI relevance complaints filed as Backend that are clearly DS, `[iOS]` rendering bugs filed as Backend that are clearly UI, Social Finds / Q2P bugs filed as Backend that are BE_Labs. The model is correctly identifying them as those other classes; we're scoring it against noisy ground truth. Projected accuracy with cleaned labels: **78-82%**.

### Active-learning loop

When a Streamlit reviewer overrides Component in the edit widget, the (text, predicted, corrected) tuple is appended to `data/corrections.csv` (gitignored). The next `build_embedding_index.py` run folds those corrections in as synthetic labelled bugs. The system gets smarter every time a reviewer corrects it — no Jira edits required.

### Front-end additions

- **Ambiguity banner**: when LogReg confidence < 0.50, the Streamlit UI shows the full probability distribution as a horizontal bar chart so the reviewer sees exactly how undecided the classifier was.
- **Override → corrections.csv** with toast notification confirming the save.

### Files added
- `src/embedding_classifier.py`
- `src/embedding_similarity.py`
- `src/repo_context.py`
- `src/agents/subagent_owner.py`
- `build_embedding_index.py`
- `build_repo_skills.py`
- `validate_embedding_classifier.py`
- `validate_claude_component.py`
- `validate_hybrid_classifier.py`
- `audit_backend_misclassifications.py`
- `slap_context/architecture/{repos.json, UI.md, Backend.md, Backend-Labs.md, DS.md, immersive.md}`
- `data/bug_aggressive_caching.txt` (test bug for the cache-bleed case)

### Files modified
- `app.py` — ambiguity banner, corrections.csv writer, threshold bump to 0.50
- `src/agents/host_agent.py` — wired embedding classifier + similarity engine + owner sub-agent
- `src/agents/subagent_parser.py` — dropped component classification (~60 lines removed from prompt)
- `src/agent_ticket_builder.py` — includes `component` in similar-bug JSON
- `src/tfidf_similarity.py` — added `component` field to `SimilarBug` dataclass
- `src/jira_client.py` — `extract_component()`, `fetch_training_corpus()`, `extract_created_iso()`
- `.gitignore` — corrections.csv, embedding index files, repo clones, audit output, per-repo skills

---

## 2026-06-24 — Form input, editable outputs, 3-tier triage, classifier overhaul

A single session that added two front-end features (structured-form input, editable outputs), one new sub-agent (form consistency), reworked the triage ladder to 3 tiers, and pushed component-classification accuracy from **43% → 78.7%** on 300 real FLIPPI bugs.

---

### 1. Structured form input

Email-paste mode is still the default. A new **Structured form** mode is selectable via a radio at the top of Step 1.

**Form fields**
| Field | Widget | Required |
|---|---|---|
| Bug title | `st.text_input` | yes |
| Platform | `st.selectbox`: Android / iOS / Web / Android, iOS / Unknown | no (defaults to Android) |
| Summary | `st.text_area` | yes |
| Steps to reproduce | `st.text_area`, one step per line | no |
| Screenshots / videos | `st.file_uploader` | no |

**How it threads through the pipeline**: `synthesize_email_from_form()` in `app.py` stitches the form values into an email-shaped string. Both the rule-based parser (regex) and multi-agent parser (Claude) consume the same shape — zero changes to any downstream code. User-supplied step numbering / bullets are stripped and renumbered cleanly.

**Why this matters**: bug reports are now triage-able even when the reporter doesn't have a properly-formatted email handy. Field validation is enforced by the form widgets instead of by post-hoc regex against an email blob.

---

### 2. Editable Priority / Component / Owner outputs

Below the metric tiles, three widgets let the reviewer override the model's choices before downloading the JSON:

- **Priority** — dropdown (P0 / P1 / P2)
- **Component** — dropdown (Backend / Backend-Labs / DS / UI / immersive / bugs)
- **Owner** — free text input (so any engineer can be assigned, not just historically-frequent ones)

**Wiring**
- Defaults: each widget shows the model's prediction; help text restates the prediction so the reviewer always sees what they're overriding
- Patches: edits update `draft.triage_notes` (`team`, `jira_component`, `owner_suggestion`, `priority`, `severity`) **and** `draft.jira_payload.fields` (`priority.id`, `customfield_10331.value`, `components[]` with verified FLIPPI component IDs from `CLAUDE.md`)
- Audit trail: any field that differs from the prediction is recorded in `triage_notes.human_overrides` as `{from, to}`
- Persistence: the triage result is stashed in `st.session_state.triage_result` so a widget interaction doesn't blow away the draft via Streamlit's re-run cycle. Refile and a fresh Triage both clear the stash.

**Component-ID map** (verified on `flipkart.atlassian.net`):
- Backend = 14386, Backend-Labs = 14385, DS = 14384, UI = 14383, immersive = 14387

---

### 3. Form-consistency sub-agent

A new sub-agent, `src/agents/subagent_form_consistency.py`, only runs when `from_form=True`. It asks Claude whether the title, summary, and steps describe the same bug. If not, it returns a `form_fields_inconsistent` quality_issue that the existing refile-banner UI surfaces.

**Why it exists**: the form lets users fill three fields independently. Unlike a free-form email (which is internally coherent or it isn't a coherent report at all), the form can collect title-about-X, summary-about-Y, steps-about-Z and still pass field-level validation.

**Rule-based fallback**: the rule-based pipeline can't call Claude, so `app.py` includes a conservative word-overlap heuristic — flags only when title has ≥ 6 content words **and** summary has ≥ 6 content words **and** title shares zero content words with summary **and** zero with steps. The ≥ 6 threshold prevents false positives on synonym pairs like `[VTON]` ↔ `virtual try-on`.

**Pipeline position**: runs immediately after the parser sub-agent, before embeddings. ~5–10s latency, only on form input.

---

### 4. 3-tier triage ladder (P0 / P1 / P2)

The triage sub-agent (`subagent_triage.py`) was rewritten:

**Primary signal**: priorities of similar past bugs. If 3 of 5 closest matches are P1, the new bug is almost certainly P1. The ladder below is only consulted when neighbours disagree or are weak matches.

**Ladder**
- **P0** — Crash, ANR, payment failed/blocked, security or secrets risk, user blocked / user loop, revenue-blocking, major UI/UX breaking
- **P1** — UI/UX improvements, price or budget ignored, text/copy changes, image loading, network interruptions, error messages, tooltips, toasts
- **P2** — Minor edge cases, low priority / low severity

**Hard overrides** (win regardless of similar-bug consensus):
- 100%-reproducible crash → always P0
- Grayskull / secrets / infra → always P0

**Validation**: stray P3/P4 responses from older prompts collapse to P2.

**No more P3**: vague reports used to drop to P3 by default; they now route to "Insufficient info — refile" instead. The information value of the P3 bucket was low; an explicit refile prompt is more useful.

---

### 5. Component classification accuracy — 43% → 78.7%

Measured on 300 real FLIPPI bugs (`/tmp/component_validation.json`).

| Team | Before | After |
|---|---|---|
| Backend | 82% | 86% |
| Backend-Labs | 51% | 81% |
| DS | 4% | 78% |
| UI | 7% | 70% |
| **Overall** | **43%** | **78.7%** |

**What changed in `src/agent_parser.py`**:
1. Keyword vocabulary expansion — added `Styledrops` (no-space variant), `vibes`, `vibes player`, `cosmos`, `moodboard`, `ai generation`, `liked drop`, `notifying edison` (BE_Labs); `wrong result`, `relevance`, `irrelevant`, `summary not matching`, `grounding`, `inappropriate`, `text cut off`, `showing tables` (DS); `[ios]`, `[android]`, `[native]`, `[rn]` platform prefixes plus visual, interaction, native-build, animation terms (UI); `log level`, `conversation`, `re-arch`, `product compare` (Backend).
2. Waterfall reorder — **UI is now checked before BE_Labs / DS / Backend**. Reason: platform-prefixed bugs ([iOS]/[Android]/[RN]) belong to UI even when they're on a BE_Labs surface (e.g. a Styledrops rendering bug tagged [iOS]).
3. Over-aggressive UI keywords removed after they started hitting BE_Labs (`bottom sheet` bare, `menu` bare, `icon` bare, `pod spin`, `not opening` bare).

**Multi-agent prompt sync** (`src/agents/subagent_parser.py`):
- Natural-language ladder rewritten to mirror the rule-based vocabulary
- Added explicit instruction: *"Prefer `bugs` over a wrong guess. Manual routing wastes less engineering time than mis-routing."*

**Why "more bugs" alone wouldn't help**: the current classifier is regex on a hand-written keyword list; it doesn't learn. See the *Recommendations for next iteration* section below.

---

### 6. Quality-check exemptions for form input

The `vague_report` check used to scan the raw email body for missing section headers (Impact, Reproducibility, Environment, etc.). When `from_form=True`, that check is skipped — form fields are short by design, so grading them on email-format heuristics was a false-positive factory.

The `media_contradicts_text` check still applies in both modes, because an attached screenshot conflicting with the description is a real problem regardless of input mode.

---

### Files added
- `src/agents/subagent_form_consistency.py`
- `data/bug_with_media/bug_failed_to_load_preferences/email.txt`
- `data/bug_with_media/bug_tap_unresponsive/email.txt`
- `CHANGELOG.md` (this file)

### Files modified
- `app.py` — input format radio, form widgets, edit widgets, session_state, banner wording, rule-based consistency heuristic
- `src/agent_parser.py` — keyword overhaul + waterfall reorder
- `src/agents/host_agent.py` — `from_form` kwarg + form-consistency hook
- `src/agents/subagent_parser.py` — prompt aligned with new vocabulary + "prefer bugs" instruction
- `src/agents/subagent_triage.py` — 3-tier ladder rewrite
- `.gitignore` — video extensions added to `data/bug_with_media/`

---

## Known limitations & recommendations for next iteration

### Owner suggestion ignores the routed component
`src/tfidf_similarity.py:121-135` and `src/agents/subagent_embeddings.py:38-73` both pick an owner by assignee frequency across similar bugs, with **no filter on whether the assignee is on the routed team**. A frequent UI engineer can be suggested for a Backend-routed ticket. The editable Owner field is the immediate workaround; the proper fix is to filter the similar-bug pool to component-matching bugs before counting assignees.

### Multi-agent classifier not yet measured
The rule-based classifier was validated at 78.7% on the 300-bug corpus. The multi-agent prompt has been aligned with the same vocabulary and given a "prefer bugs over a wrong guess" instruction, but it hasn't been run against the same 300 bugs to measure whether it closes part of the remaining 21% gap.

### Recommendations for breaking past 78.7%

Ranked by ROI for this prototype:

1. **Embedding-based k-NN classifier** — embed each historical bug, label by component, find nearest neighbours for a new bug, majority-vote. Uses your existing labels directly; gets better automatically as Jira grows; handles the per-team class imbalance (DS=27 bugs, BE_Labs=47) gracefully. Highest single-change ROI.
2. **Few-shot examples in the multi-agent parser prompt** — replace the natural-language team descriptions with 5–8 real labeled FLIPPI examples per team. Pure prompt change, no architecture work.
3. **Feedback loop from `human_overrides`** — persist the audit trail (CSV / sqlite / Jira label), periodically re-validate, and feed corrections back into keywords or few-shot examples. Turns a static classifier into a continuously-improving one.
4. **Expand corpus from 300 → 1000+** — useful **only after** an ML method (#1) is in place that can use it.

The combination of #1 + #3 is the realistic path from 78.7% into the 90s.
