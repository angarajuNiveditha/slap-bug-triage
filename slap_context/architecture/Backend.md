# Backend — Team, Modules & Routing Guide

**Team:** Backend (a.k.a. BE_Flippi)
**Manager:** Veeramreddy ChakradharReddy *(reports separately from Yatin's tracks)*
**Jira component:** `Backend` (id `14386`)
**Stack:** Java (Spring), Maven, Docker
**Primary repo:** [`edison`](https://github.fkinternal.com/Flipkart/edison) — prod branch `productions`
**Secondary repos:** `edison-gateway`, `cp-service-clients`

Everything server-side that isn't experimental ML (VTON / Styledrops / Vibes / Cosmos → **Backend-Labs**) or model quality (ranking / relevance / prompt / grounding → **DS**). If the failure is a real HTTP/service problem — 5xx, timeout, wrong data returned, auth denied, session lost, secret unresolvable — this team owns it.

---

## Common Bug Routing Signals

> Symptoms extracted from real Backend-labelled bugs in the 564-bug FLIPPI corpus. Match on failure mode, not surface tokens.

| Symptom / phrase in the report | Owning module | Likely service class |
|---|---|---|
| "Failed to verify on authenticating" / "authentication failed" | `authentication/` | `AuthenticationService`, `KevlarTokenService` |
| "OTP not received" (server-side dispatch) | `authentication/` | `OtpService` |
| "Getting null from Login Federator" | `authentication/` | `AuthenticationService`, `AccountMappingService` |
| "Kevlar failing during registration" | `authentication/` | `KevlarTokenService` |
| "Account ID Details Fetch error" | `authentication/` | `UserProfileService`, `AccountMappingService` |
| "Grayskull integration for secrets" | `authentication/` (secrets sub-path) | *(GraySkull integration lives across services)* |
| "Product Compare card failing" | `product-page/` | *(Product Compare handler)* |
| "Product Page Call Graph re-arch" | `product-page/` | `ProductPageResource` |
| "Add product family dedup in journey continuation" | `edison-discovery/` | Search-side services |
| "streaming stopped midway", "next part of message not loading" | `edison-core/` | Streaming/SSE layer |
| "Conversation Title generation errors" | `conversation-history/` | `ConversationSummaryService` |
| "Old conversations missing" | `conversation-history/` | `ConversationHistoryService` |
| "Feeds — error in querying created_at field" | `edison-discovery/` (feed DAO) | Feed enrichment path |
| "Feed — Mandatory attributes missing" | `edison-discovery/` | Feed enrichment path |
| "Payment-callback not coming to edison" | `checkout/` | `CheckoutService` |
| "Checkout API 500 / wrong cart total" | `checkout/` | `CheckoutService`, `AddressService` |
| "profile update lost after signup" | `user-memory/` | `UserMemoryService` |
| "preferences not saved" | `user-memory/` | `UserMemoryService`, `UserMemoryEmbeddingService` |
| "order not showing up after purchase" | `my-orders/` | `MyOrdersService` |
| "Broken image thumbnails" *(server-side fetch)* | `catalog/` | `ProductDetailService`, `DocumentService` |
| "Log verification for key presence" / "Update log level on runtime" | `edison-common/` | Config/observability plumbing |
| "Remove mobile number from logs" | `edison-common/` | Log-redaction plumbing |

---

## The Backend ↔ DS litmus test

Both teams sit "behind the API." Bugs *look* similar in Jira but the routing rule is sharp:

> **If the service responded but the content was wrong → DS.**
> **If the service did not respond properly (5xx, timeout, null, wrong shape) → Backend.**

| Symptom | Right team |
|---|---|
| "Search returned no results" / 500 / API error | **Backend** |
| "Payment-callback not coming to edison" | **Backend** |
| "Failed to verify on authenticating" | **Backend** |
| "Edison stability / API failures" | **Backend** |
| "Search returned wrong / irrelevant results" | **DS** |
| "Bot failed to understand the query" | **DS** |
| "Same response every time" / "Repeated results" | **DS** |
| "Reasons to Buy missing / phrased oddly" | **DS** |
| "Model asking for today's date" | **DS** |

A label-noise audit of the 564-bug corpus found **~70% of misclassified Backend bugs are actually DS bugs mis-filed against `Backend`** in Jira — usually chat-quality or relevance complaints. When in doubt and the bug is about *what the model said*, route to DS.

---

## The Backend ↔ Backend-Labs boundary

Both teams touch `edison/` (BE-Labs features often live inside Edison as sub-modules like `style-drop/`, `social-finds/`). The rule:

> **Core service failure (search / cart / checkout / auth / session / payments / secrets / product page) → Backend.**
> **Experimental-ML feature failure (VTON / Styledrops / Social Finds / Vibes / Cosmos / MoodBoard / Review Synth / Decoded Looks / avatar generation) → Backend-Labs**, *even if the code lives inside `edison/`.*

Cross-references:
- `edison/social-finds/` → Backend-Labs (see `social-finds-pipeline.md`)
- `edison/style-drop/` → Backend-Labs (see `dropsense.md`, `slap-feed.md`)
- Everything else in `edison/` → Backend

---

## Module map — `edison/` (1,704 Java files, prod branch `productions`)

Real modules with their real class inventories. Extracted from the current clone via `build_repo_skills.py` code mining; verifiable by grepping the actual repo.

### `authentication/` (117 source files)
- **Services**: `AccountMappingService`, `AuthenticationService`, `KevlarTokenService`, `OtpService`, `TokenService`, `UserProfileService`
- **HTTP entry point**: `AuthenticationResource` (JAX-RS)
- **Exceptions**: `AuthenticationException`, `DobLimitExceededException`, `TokenServiceException`, `ValidationException`
- **Real state enums**: `AgeGroup`, `AuthVerificationType`, `ErrorCode`, `ErrorType`, `Gender`, `StatusType`
- **Owns**: login, signup, OTP, Kevlar registration path, session tokens, session cache, Grayskull-backed secret resolution

### `edison-core/` (163 source files)
- **Owns**: core Edison runtime — request routing, streaming/SSE layer, response assembly, feature flags
- **Bug patterns land here when**: streaming stops midway, response never arrives, malformed response body

### `edison-discovery/` (178 source files)
- **Owns**: search, feeds, journey continuation, product-family dedup
- **Bug patterns**: "wrong results returned", "feed query error", "product family duplicates in results", `[Journey Continuation]:` tickets
- **⚠ crossover**: chat-AI quality inside these code paths → **DS**, not Backend

### `product-page/` (162 source files)
- **HTTP entry point**: `ProductPageResource`
- **Services**: `OffersService`
- **Owns**: Product Page fetch, Product Compare card, offers callouts, warranty callouts, "Only for You" callout
- **Data contracts**: 15 DTO/Request/Response classes

### `edison-common/` (159 source files)
- **Owns**: cross-module utilities — logging, feature flags, redaction, config, observability, App Eval enrichment
- **Exceptions**: `EdisonBotException`, `EdisonClientException`, `EdisonCommonException`, `EdisonException`
- **Real enums**: `Environment`, `RateLimiterKey`, `RequestFlowStep`, `EdisonModules`

### `catalog/` (115 source files)
- **Services**: `DocumentService`, `OfflineDataLoaderService`, `PolicyService`, `ProductDetailService`, `UserReviewService`, `VariantService`, `VariantsPivotService`, `VerticalClassifierService`
- **HTTP entry points**: `OfflineDataLoaderResource`, `ProductInfoResource`, `VerticalClassifierResource`
- **Owns**: product/catalog fetch, image URLs, stock/availability, review images, variant handling

### `checkout/` (54 source files)
- **Services**: `AddressService`, `CheckoutService`
- **HTTP entry point**: `CheckoutResource`
- **Exceptions**: `CheckoutServiceException`, `CheckoutServiceRuntimeException`
- **Real state enums**: `AdjustmentType`, `CheckoutStatus`, `ItemState`, `UseCase`
- **Owns**: cart → checkout orchestration, payment session handoff, order create, address management

### `conversation-history/` (46 source files)
- **Services**: `ConversationHistoryService`, `ConversationSummaryService`, `SFConversationHistoryService`
- **Exceptions**: `ConversationHistoryException`
- **Enums**: `ChatType`, `ConversationStatus`, `ConversationSummaryStrategy`
- **Owns**: chat history storage, conversation title generation, chat→session link

### `user-memory/` (46 source files)
- **Services**: `EmbeddingGenerationService`, `UserMemoryEmbeddingService`, `UserMemoryService`
- **HTTP entry point**: `UserMemoryResource`
- **Owns**: persistent user preferences, profile store, embedding-backed memory generation

### `my-orders/` (48 source files)
- **Service**: `MyOrdersService`
- **HTTP entry point**: `MyOrdersResource`
- **Real enum**: `SlapOrderStatus`
- **Owns**: order history, order state fetch, tracking

### `aerospike-client/` (46 source files)
- **Service**: `AerospikePolicyService`
- **Handlers**: `BatchDeleteSuccessHandler`, `BatchFailureHandler`, `DeleteSuccessHandler`, `ExistsSuccessHandler`, `FailureHandler`, `RecordSuccessHandler`, `WriteSuccessHandler`
- **Owns**: Aerospike wrapper — session cache, short-lived cache. **Cache-consistency bugs land here.**

### `cron/` (55 source files)
- **Owns**: batch jobs, scheduled aggregations, session-memory generation

### `notifications/` (42 source files)
- **Owns**: push notification triggers, in-app notification API

### `social-finds/` (117 source files) — **routes to Backend-Labs**
Lives in `edison/` for co-deployment reasons but functionally BE-Labs. See `social-finds-pipeline.md`.

### `style-drop/` (99 source files) — **routes to Backend-Labs**
Same story. See `dropsense.md`.

*(Plus `waitlist/`, `expert-review/`, `payments/`, and a few smaller dirs.)*

---

## Team roster & sub-area ownership

Populated from the SLAP org chart (Veeramreddy's team, reports separately from Yatin's tracks):

| Engineer | Role | Sub-area focus |
|---|---|---|
| **Shubham** | SDE-3 | *Used to lead SLAP; works exclusively on AI mode now.* Chat AI, streaming, prompt/response infrastructure. |
| **Divya** *(Chhibber)* | SDE-3 | Partially owns SLAP alongside other work. Broad generalist — auth, product page, checkout. |
| **Vandana** | SDE-3 | Mostly Feeds-related backend flows (`edison-discovery/` feed paths, feed enrichment, feed DAO). |
| Veeramreddy | *Manager* | Escalation owner (see `subagent_owner.py` — team-manager escalation on P0 / no-IC-match). |

*(Frequency in historical assignees is not a good proxy for current ownership — Backend has had triage assignments to managers that inflate their counts. The names above come from the org chart, which supersedes assignee frequency.)*

---

## Data stores

- **Aerospike** — session + short-lived cache. Wrapped by `aerospike-client/`. Cache key: session token + user ID. TTL typically 24 h.
- **MySQL** — persistent stores for user memory, conversation history, order history.
- **Grayskull** — secret store integration. Used across `authentication/` and any code needing secrets.
- **CP services** — Flipkart-wide commerce-platform services called via `cp-service-clients`.

Tell-tale signs a "data bleed across users" bug is server-side (Backend, not UI):
- Description references *API response* containing wrong data
- Reproduces from a fresh app install (no client state to blame)
- Bug mentions session token, Grayskull, or a specific service name
- Network log shows the wrong data coming from `GET /profile` or similar

If reproduces only after logout → login on the same device and a fresh install fixes it, it's **UI's cache** (MMKV / Redux persist), not Backend.

---

## What is NOT Backend

- Any visual / layout / rendering bug on a Backend-owned surface (checkout UI, cart UI, chat UI) → **UI**
- Any VTON / Styledrops / Vibes / Social Finds / MoodBoard / Cosmos / Review Synth / Decoded Looks / avatar bug → **Backend-Labs** *(even when the code lives inside `edison/social-finds/` or `edison/style-drop/`)*
- Chat AI / model quality / response relevance / prompt / grounding / ranking → **DS** (see litmus test above)
- 3D / AR / VR / VTO SDK / Beauty VTO / Camera Filters → **Immersive** (owned by Yatin's Labs track)
- Client-side cache bugs (MMKV, Redux persist, disk cache) → **UI**

---

## Common title-prefix conventions in Backend bugs

- `[Auth]:`, `[Login]:`, `[Kevlar]:` — authentication path
- `[Checkout]:`, `[Cart]:`, `[Payments]:` — order flow (server side)
- `[Product Compare]`, `[Product Page]` — product-page module
- `[Feeds]:`, `[Journey Continuation]:` — discovery module
- `[Grayskull]:` — secret integration
- `App Eval - X` — observability / eval harness

If the title starts with `[iOS]`, `[Android]`, `[RN]`, `[Native]` — this is **UI**, not Backend, even when the feature area sounds Backend-y (e.g. `[iOS] Payment page back button`).
