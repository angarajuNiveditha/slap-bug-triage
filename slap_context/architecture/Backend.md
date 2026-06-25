# Backend team (BE_Flippi) — architecture skill

**Team:** BE_Flippi
**Jira component:** `Backend` (id 14386)
**Stack:** Java (Spring) — server-side

## Repos owned

| Repo | Role | Prod branch | Freshness |
|---|---|---|---|
| `edison` | Core SLAP backend service | `productions` | warm |
| `edison-gateway` | API gateway / edge layer in front of Edison | `main` | lazy |
| `cp-service-clients` | Java client libraries for downstream commerce-platform calls | `master` | lazy |

> Code at github.fkinternal.com/<org>/{edison,edison-gateway,cp-service-clients}

## Surface area Backend owns

- **Chat AI** — conversation handling, intent routing, response generation, log levels
- **Search** — query handling, filters, the `journey continuation` flow
- **Cart / Checkout** — server-side cart state, checkout orchestration, price calculation
- **Payment** — payment session, payment-flow APIs (NOT the React Native payment UI)
- **Auth / Session** — login, signup, OTP, session management, JWT issuance, session-token cache, "Failed to verify on authenticating with credentials"
- **Grayskull / secrets** — secret management, integration of Grayskull in Edison
- **Bot** — server-side bot, conversation routing
- **Server-side caching** — Edison's per-user cache by session token, Grayskull-keyed cache
- **Product compare** — backend logic for comparing products
- **DA flow** — Daily Active / engagement tracking

## What is NOT Backend

- Any visual / layout / rendering bug — UI (even when the failure is in a Backend-routed feature like checkout)
- Experimental ML features (VTON, Styledrops, Vibes, Cosmos) — Backend-Labs
- **Chat-AI / model quality / response relevance complaints — DS** (see below — this is the most common mis-routing)

## ⚠ The Backend/DS confusion — most common mislabel

A label-noise audit found that **~70% of misclassified Backend bugs are actually DS bugs filed under Backend in Jira**. The pattern: anything mentioning *"wrong results", "irrelevant", "bot didn't understand", "RTB strangely phrased", "reasons to buy missing", "results not shown", "same response every time", "summary not matching"* → almost always DS, not Backend, even though it touches Edison's chat code path.

| Symptom | Right owner |
|---|---|
| "Search returned no results" / 500 / API error | Backend |
| "Search returned wrong / irrelevant results" | **DS** |
| "Bot failed to understand the query" | **DS** |
| "Same response every time" / "Got repeated results" | **DS** |
| "Reasons to buy missing" / "RTB phrased oddly" | **DS** |
| "Conversation titles are off" | **DS** |
| "Payment-callback not coming to edison" | Backend |
| "Edison stability / API failures" | Backend |
| "Failed to verify on authenticating" | Backend |

The litmus test: *if the service responded but the response was the wrong content, it's DS. If the service didn't respond properly, it's Backend.*

## Server-side caching (relevant to "data bleed across users" bugs)

Edison caches user profile reads. Cache key: session token + user ID. TTL: typically 24 h. **If a logout/login bug shows User A's data after User B logs in AND the bug clearly indicates the data came from a server response, that's Backend.** If the data appears stale even after a fresh server fetch (i.e. the client never asked the server), it's UI (client-side cache).

Tell-tale signs the bug is *server-side*:
- Mentions API response containing wrong data
- Reproduces from a fresh app install (no client state)
- Bug description references session token, Grayskull, or service names
- Network log shows GET /profile returning wrong user's data

## Edison module map (auto-generated from `productions` clone)

`edison/` (the main Java repo) has 1,704 .java files across modules including:
- `edison-discovery/` (178 files), `edison-core/` (163), `edison-common/` (159), `product-page/` (162)
- `authentication/` (117 files) — auth and session management
- `social-finds/` (117 files) ← also surfaces in BE_Labs context
- `catalog/` (115 files)
- `style-drop/` (99 files) ← also surfaces in BE_Labs context
- `cron/` (55), `checkout/` (54), `my-orders/` (48)
- `conversation-history/` (46), `user-memory/` (46), `notifications/` (42)

The `social-finds/` and `style-drop/` modules within Edison are why some BE_Labs bugs route to Backend if the bug mentions Edison directly. The skill files for `dropsense.md` and the `slap-feed` / `social-finds-pipeline` branches clarify which side owns what.

## Common bug patterns

- `[Checkout]:`, `[Cart]:`, `[Payments]:`, `[Auth]:` — when the failure is server-side
- "Failed to verify", "OTP not received", "session expired"
- "Edison" (when not in Styledrops / Vibes context)
- "Grayskull integration for X"
- 5xx errors in API responses
- Wrong data returned by the server (price discrepancies, wrong product detail)
