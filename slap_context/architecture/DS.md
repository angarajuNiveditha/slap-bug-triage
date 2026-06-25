# DS team — architecture skill

**Team:** DS (Data Science)
**Jira component:** `DS` (id 14384)
**Stack:** Python

## Repos owned

| Repo | Role | Prod branch | Freshness |
|---|---|---|---|
| `expert-opinion-offline-flow` | Offline ranking / scoring pipeline used by the chat-AI ranker | `develop` | lazy |
| `slap-auto-qc-pipeline` | Automated quality-control for SLAP responses (NPS-adjacent metrics) | `main` | lazy |

> Code at github.fkinternal.com/<org>/{expert-opinion-offline-flow,slap-auto-qc-pipeline}

## Surface area DS owns

- **Ranking & recommendation quality** — quality of which products SLAP shows
- **Result relevance** — "wrong results", "results not shown", "irrelevant", "less relevant", "old query products", "stale results", "got only N results"
- **Summary / suggestion mismatches** — "summary not matching", "wrong summary", "product suggestion is missing"
- **Model behaviour** — "failed to answer", "model failed", "general intelligence", "grounding", "inappropriate", "unsafe request", "prompt still needs work", "bot failed to understand"
- **Content presentation / model output formatting** — "text cut off", "showing tables", "tabular", "hyperlink instead", "bad state message"
- **Scope/range mismatch** — "above price range but results are for below", context-switching wrong results
- **NPS, %Positive, ranking-quality dashboards**
- **Model-quality monitoring** — auto-QC pipeline outputs
- **Reasons to buy / Reasons to avoid** quality — "RTB strangely phrased", "RTA around low product rating"
- **Conversation context / memory quality** — "bot not holding context long enough", "conversation title is off"

## What is NOT DS

- The chat-AI service implementation itself (logic, routing, conversation state) — Backend (Edison)
- The visual rendering of results (cards, scroll behaviour) — UI
- Generation models for Styledrops / VTON / Vibes (those produce *content*, not *rankings*) — Backend-Labs

## How to tell a DS bug from a Backend bug when both mention search / chat AI

| Symptom | Likely owner |
|---|---|
| "Search returned no results" / 500 / API error | Backend |
| "Search returned wrong/irrelevant results" | **DS** |
| "Search results are stale (old query)" | **DS** |
| "Search summary doesn't match the products shown" | **DS** |
| "Search results above price filter range" | **DS** |
| "Login broken, can't search" | Backend (auth) |
| "Bot failed to understand" | **DS** |
| "Same response every time" / "Getting repeated results" | **DS** |
| "RTB strangely phrased" / "Reasons to buy missing" | **DS** |

The litmus test: *if the service responded with results but the wrong ones, it's DS. If the service didn't respond properly, it's Backend.*

## Note on Backend label noise

Based on a label audit, **DS is the most-common destination for mis-labelled Backend bugs**. Many chat-AI / response-quality complaints are filed against the Backend Jira component but are textbook DS. When in doubt and the bug is about *what the model said*, route to DS.

## Common bug patterns

- "Wrong results", "no results", "less relevant", "irrelevant"
- "NPS dropped", "%Positive dropped"
- "Summary not matching"
- "Failed to answer", "model said X but should have said Y"
- "Grounding issue", "hallucination"
- "Inappropriate response", "unsafe request handled poorly"
- "RTB strangely phrased", "Reasons to avoid is wrong"
