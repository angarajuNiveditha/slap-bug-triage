# Backend-Labs (BE_Labs) — architecture skill

**Team:** BE_Labs
**Jira component:** `Backend-Labs` (id 14385)
**Stack:** mostly Java + Python (mixed)

## Repos owned

| Repo | Role | Prod branch | Freshness | Stack |
|---|---|---|---|---|
| `dropsense` | FTUE + Styledrops service (drop generation, drop liking) | `main` | lazy | **java** (manifest said js — manifest was wrong) |
| `slap-feed` | Feed + card generation work (lives as branch of edison) | `slap-feed` | warm | java |
| `social-finds-pipeline` | Social Finds ingestion (lives as branch of edison) | `social-finds-master-uat` | warm | java |
| `FaceNet` | VTON / virtual try-on model service, face detection, persona match | `master` | lazy | python |

## Surface area BE_Labs owns

- **Styledrops** — drop generation, drop ready/showing, "[Styledrops]", "styledrops edison" (i.e. Edison integration in the Styledrops context)
- **FTUE** — first-time user experience flow (drop-based onboarding journey)
- **Vibes Player / Moodboard** — vibes, vibes player, moodboard, "Vibes API"
- **Avatar generation / AI generation / AI rendering** — model inference for SLAP visuals
- **Cosmos dashboard / Frame status** — internal Cosmos tooling
- **Reels ingestion** ("sending reel", "after sending reel") — social-finds-pipeline branch
- **Social Finds** — social discovery surface
- **Liked drops, drop generation** — "drops are showing", "drop ready", "generating your drops"
- **VTON / virtual try-on / draping / Q2P / Machine Identity** — FaceNet
- **Review Synth, Decoded Looks** — adjacent BE_Labs features

## What is NOT BE_Labs

- Visual / rendering bugs on a BE_Labs surface that are tagged `[iOS]`/`[Android]`/`[RN]` — UI owns those (the failure is in React Native, not in the feature service)
- Core Edison features (cart, checkout, auth) — Backend
- Ranking quality of recommendations — DS

## Distinguishing from Backend (the Edison gotcha)

"Edison" appears in both Backend and BE_Labs contexts:

| Mention | Likely owner |
|---|---|
| "Grayskull integration for Edison" / "secrets for Edison" | **Backend** (Edison core) |
| "Styledrops Edison" / "notifying Edison from Styledrops" | **Backend-Labs** (dropsense calling Edison) |
| "Edison crashed", "Edison returned 500" without other context | **Backend** (Edison is the main service) |
| Branch slap-feed or social-finds-master-uat of edison | **Backend-Labs** (feature branches owned by BE_Labs) |

## Common bug patterns

- `[Styledrops]`, `[VTON]`, "drop ready", "drop generation", "liked drop"
- "Vibes player", "vibes API", "moodboard"
- "Avatar not generating", "AI generation failed"
- "Cosmos dashboard not loading"
- "After sending reel", "reels ingestion"
- VTON gender / persona mismatches → FaceNet
