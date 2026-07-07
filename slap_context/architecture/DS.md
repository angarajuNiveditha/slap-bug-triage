# DS — Team, Modules & Routing Guide

**Team:** DS (Data Science)
**Manager:** *(not in the current org chart — no auto-escalation mapped; DS bugs with no engineer similar-bug history return `no-candidates` for manual triage)*
**Jira component:** `DS` (id `14384`)
**Stack:** Python (auto-QC pipeline) + integration work inside Java repos (Backend + BE-Labs)
**Repos:**
| Repo | Role | Prod branch |
|---|---|---|
| `slap-auto-qc-pipeline` | Automated quality-control pipeline for SLAP response quality | `main` |
| `expert-opinion-offline-flow` | Offline ranking / model-quality pipeline for product recommendation *(not cloned locally — no per-repo skill)* | `develop` |

DS is the "what came out of the model" team. They don't own the code path that CALLS the model (that's Backend or BE-Labs), and they don't own the RN screen that displays the response (that's UI). They own **response quality** — relevance, ranking, prompt design, grounding, model behaviour, content presentation.

---

## Common Bug Routing Signals

> Symptoms extracted from real DS-labelled bugs in the 564-bug FLIPPI corpus. This is the largest and most nuanced routing signal set — DS bugs frequently get mis-filed as `Backend` in Jira (see litmus test below).

| Symptom / phrase in the report | Sub-area | What's actually broken |
|---|---|---|
| "Results weren't shown, though mentioned in the summary" | Grounding / retrieval | Answer text references products the retrieval didn't fetch |
| "Text cut off in the paragraph" | Content presentation | Response formatting / truncation logic |
| "We need to solve for showing tables" | Content presentation | Tabular data rendering in chat |
| "Product suggestions included in text below cards" | Response layout | Model duplicating info in text + card |
| "Grounding related improvements" | Grounding | RAG grounding — response must cite retrieved products |
| "user query for above price range but results below" | Filter logic | Price / attribute filter respected in retrieval, not response |
| "Getting old query products with current query summary" | Context tracking | Conversation state — old context bleeding into new turn |
| "I was searching for chess sets and changed context to mobiles" | Context tracking | Multi-turn context switching |
| "prompt still needs work on general intelligence" | Prompt | Prompt-engineering follow-ups |
| "Scanning the inventory for matches" is a bad state message | Error copy | State messages / error strings |
| "Getting response mentioned Developed by Google" | Prompt leak | Prompt / model identity leaking into output |
| "DA for is failing quite often" | Decision Assistant | DA agent path |
| "Got only 2 results" | Recall | Retrieval-recall too low |
| "Bot failed to answer for the current year" | Time understanding | Prompt / model time-awareness |
| "Almost all products are same" | Diversity | Result-set diversity too low |
| "when I said I want to buy the item, suggesting to head over to Flipkart" | Routing | Model routing to wrong action |
| "even after mentioning gender neutral, results didn't change" | Filter respect | Attribute filter ignored |
| "Product title does not align with Reasons to Avoid" | Attribute alignment | Content generation inconsistency |
| "SLAP throwing error that I can't show Apple products" | Prompt / policy | Model applying wrong policy |
| "Model asking for today's date" | Prompt | Missing prompt context |
| "The top recommendation is wrong" | Ranking | Recommendation ordering |
| "Didn't get any results, rather slap mentioned to stay tuned" | Error fallback | Response fallback copy |
| "Budget Rs 1000, product suggested Rs 2300" | Filter | Budget filter ignored |
| "Electric scooter → electric bike also shown" | Intent understanding | Cross-category leakage |
| "Not suggesting well-known brands based on rating" | Ranking | Brand / rating weighting |
| "Products listed under motorcycle vertical, still says not available" | Cross-vertical | Vertical classification vs availability |
| "Suggesting 3 probable questions similar to copilot" | Follow-up suggestions | Follow-up question generation |
| "Tries to keep asking questions to narrow down while saying no worries" | Conversation flow | Multi-turn state machine |
| "Show me one minute saree says inappropriate/unsafe request" | Content policy | Policy classifier |
| "Gender Mismatch issue" | Filter | Gender attribute in filter |
| "Reasons to Avoid missing / phrased oddly" | Content generation | RTB/RTA generation |
| "Getting URL1, URL2 in bottom text (not clickable)" | Content generation | Response template variables not filled |
| "streaming stopped midway" *(vs. server-side)* | Streaming quality | If the response STARTED (i.e. server responded), broken mid-content → DS |

---

## The Backend ↔ DS litmus test

The single most important disambiguation in the whole skill corpus. Backend bugs get mis-filed as DS all the time and vice versa:

> **If the service responded but the content was wrong → DS.**
> **If the service did not respond properly (5xx, timeout, null, wrong shape) → Backend.**

If the reporter's description talks about *what the response said* — words, ranking, phrasing, product choices, filter respect, category leakage, prompt behaviour — it's DS regardless of what Jira component was originally set.

If the description talks about *the server / API / timeout / 500 / did not respond* — it's Backend.

The 70% mis-labelled Backend → DS pattern comes from this exact confusion.

---

## The DS ↔ BE-Labs boundary

Both teams touch AI features. Rule:

> **BE-Labs owns the ML-feature CODE PATH (VTON, draping, Q2P, avatar generation).**
> **DS owns the MODEL QUALITY (why the ranking is off, why the LLM said the wrong thing, why the prompt behaves incorrectly).**

Examples:
- "VTON generated wrong gender" → **BE-Labs** (persona routing code bug in `dropsense/PersonaService`)
- "VTON quality is bad" → **DS** (model quality)
- "Social Finds Q2P not happening" → **BE-Labs** (pipeline code bug)
- "Social Finds response is irrelevant" → **DS** (ranking/relevance)

---

## Module map — `slap-auto-qc-pipeline` (Python, 34 source files, prod `main`)

The one DS repo we have cloned locally. Owns automated QC of SLAP responses — NSFW checks, image quality, face detection, comprehensive-QC orchestration.

- **Classes** (37 in `app/`): `AutoQC`, `AutoQCPipeline`, `ComprehensiveQCResponse`, `ComprehensiveQCResult`, `ComprehensiveQCService`, `ConfigSvcClient`, `Edison`, `FaceNetRequest`, `FaceNetResponse`, `FaceNetService`, `ImageDownloadUtils`, `ImageProcessingUtils`, `ImageQCDetails`, `ManualQC`, `MetricsMiddleware`, `ModelConfig`, `NSFWResult`, `ODResults`, `OWLViTRequest`, `OWLViTResponse`, and 17 more
- **Exceptions**: `FaceDetectionException`, `FaceSimilarityException`, `ImageProcessingException`, `NSFWException`, `QCException`, `ServiceException`, `URLException`
- **Tests**: 17 test classes covering the QC service, controllers, image processing, and utilities — the repo has good coverage

## Module map — `expert-opinion-offline-flow` (Python, not cloned)

From `repos.json`: offline ranking / model-quality pipeline for product recommendation. Computes scoring features used by the chat AI ranker. Owns:
- Offline ranking
- Ranking quality
- Recommendation scoring
- The "expert-opinion" model

Since the repo isn't cloned, we don't have module or class-level detail — bugs mentioning "expert opinion", "recommendation scoring", "offline ranking" route here on name recognition.

---

## Team roster

The `data/embedding_index_team_roster.json` roster for DS (from historical assignees):
`SrinivasaMadhava PhaneendraAngara`, `Anjali Nainani`, `Amey Patil`, `Panyam GouthamSai`, `Manish Rathi`, plus a few others with ≥2 bugs.

No named manager in the SLAP org chart the user provided. `TEAM_MANAGERS["DS"]` is intentionally unmapped in `src/team_config.py` — DS bugs where no engineer has similar-bug history return `no-candidates` (manual triage) rather than escalating to a manager who might not own DS.

---

## Where DS "sits" in the pipeline

DS doesn't own a standalone service most of the time. Their work lives inside Backend and BE-Labs code paths — writing prompts consumed by `slap-feed/edison-discovery/GeminiService`, tuning the ranking that ships in `edison/edison-discovery/`, etc. When a DS bug is filed, the fix often lands as a PR against a Backend or BE-Labs repo but authored by a DS engineer.

Consequence for triage: the ROUTED team is DS, but the code change might happen in `edison/`. That's normal — component labels the *responsible* team, not the *repo* where the fix lives.

---

## What is NOT DS

- Service that returned 5xx / timeout / no response → **Backend**
- ML-feature code bug (VTON persona, draping, Q2P pipeline) → **Backend-Labs**
- RN rendering / touch / visual layout → **UI**
- If the ranking/content is fine but the UI clipped the text → **UI**

---

## Common title-prefix conventions

- `[Chat/AI]:` — chat-AI response, usually DS (unless it's a streaming / API failure, then Backend)
- `[Search]:` — response quality → DS; API failure → Backend
- `[Ranking]`, `[Recommendation]:` — DS
- `[RTB]`, `[Reasons to buy]`, `[Reasons to avoid]` — content generation → DS
- `[NPS]`, `[%Positive]`, `[QC]:` — auto-QC pipeline → DS
- `[Grounding]:` — RAG grounding → DS
