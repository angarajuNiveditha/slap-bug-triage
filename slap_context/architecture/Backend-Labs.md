# Backend-Labs — Team, Modules & Routing Guide

**Team:** Backend-Labs (a.k.a. BE-Labs)
**Manager:** Yatin Grover (labs team owns experimental-ML backend under Yatin)
**Jira component:** `Backend-Labs` (id `14385`)
**Stack:** mostly Java (Spring), some Python for ML inference
**Repos:**
| Repo | Role | Prod branch |
|---|---|---|
| `dropsense` | Style Drops + FTUE feature service — job orchestration, autoQC, draping | `main` |
| `FaceNet` | VTON face-embedding / persona-match model service | `master` |
| `slap-feed` | Feed + card generation *(feature branch of `edison`)* | `slap-feed` |
| `social-finds-pipeline` | Social Finds ingestion + processing *(feature branch of `edison`)* | `social-finds-master-uat` |

Every experimental-ML feature on SLAP that isn't ranking/relevance (which is DS) or the shell around it (which is UI). The distinguishing signature is: bugs about **AI-generated content** — draping, avatars, style drops, moodboards, social-finds Q2P, reels ingestion, review synthesis.

---

## Common Bug Routing Signals

> Symptoms extracted from real Backend-Labs bugs in the 564-bug FLIPPI corpus.

| Symptom / phrase | Feature area | Owning module / service |
|---|---|---|
| "VTON gender mismatch" / "wrong persona" | VTON | `FaceNet` + `dropsense/PersonaService` |
| "P75 of VTON draping" / "VTON draping" issues | VTON | `dropsense/DrapingService` |
| "Vton usage counter bug" | VTON | `dropsense` (usage tracking) |
| "Generating random VTONs on bad image upload" | VTON | `dropsense/AutoQCService` |
| "Style Drops for Male / Female users mismatch" | Styledrops | `slap-feed/style-drop/StyleDropService` |
| "Styledrops product card missing images" | Styledrops | `dropsense/StyleDropJobService` |
| "Styledrops edison testcases are failing" | Styledrops | `edison/style-drop/` |
| "Social Finds Q2P not happening" | Social Finds | `social-finds-pipeline/social-finds/` |
| "Social Finds Text message reply missing" | Social Finds | `social-finds-pipeline/social-finds/MessageHandlerService` |
| "Review Synth prompt update" / "Review Synth bug fixes" | Review Synth | `slap-feed/expert-review/ExpertReviewService` |
| "Decoded Looks feed bugs" | Decoded Looks | `dropsense` + `slap-feed` feed side |
| "Cosmos Functional Dashboard not working" | Cosmos | `dropsense` observability |
| "Retro for avatar generation" | Avatar | `dropsense/AvatarGenService` |
| "AI Generation/Rendering Glitch (separate human head)" | Avatar / draping | `dropsense/AvatarGenService` |
| "Update Vibe Api Bug" | Vibes Player | *(Vibes API path)* |
| "Frames status not updating" | Cosmos frames | `dropsense/StyleDropJobService` |
| "MoodBoard: FK products not showing up" | MoodBoard | `slap-feed/edison-discovery/MoodBoardService` |
| "Enhanced image product response completely wrong" | Enhanced-image (Q2P) | `social-finds-pipeline` |
| "MySQL db increase due to xcom" | Airflow / BE-Labs infra | Pipelines |
| "Timeout issues in gemini" | GenAI infra | `slap-feed/edison-discovery/GeminiService` |
| "Genvoy results mismatch for VTON" | Genvoy gateway | `dropsense` (calls Genvoy) |
| "Products sorting issue in edison" *(Styledrops context)* | Styledrops | `slap-feed/style-drop/` |

---

## Boundary with Backend

BE-Labs code lives partly in `edison/` (the `social-finds/`, `style-drop/`, `feed-adk-poc/` sub-modules). The rule for a bug that touches Edison:

> **Failure in a core service (search / cart / checkout / auth / payments) → Backend, even if code is inside a BE-Labs feature area.**
> **Failure in the ML feature itself (draping, avatar, Q2P, VTON persona, feed generation, MoodBoard) → BE-Labs, even if the code path passes through `edison/`.**

## Boundary with DS

Both teams touch AI. The rule:

> **BE-Labs owns the ML-feature CODE PATH (draping models, VTON inference, image gen, avatar rendering, Q2P pipeline).**
> **DS owns the MODEL QUALITY (why the LLM said the wrong thing, why the ranking was off, why relevance is bad).**

Example: "VTON generated the wrong gender" → BE-Labs (persona logic bug). "VTON quality is bad" → DS (model quality).

## Boundary with UI

BE-Labs owns the *feature backend*; UI owns the RN rendering layer. A `[RN]` or `[iOS]`/`[Android]` prefix on a Styledrops/VTON/Social Finds bug is **UI**, not BE-Labs.

---

## Module map — `dropsense` (Java, 271 source files, prod branch `main`)

The most feature-dense BE-Labs repo. Owns Style Drops + FTUE + AvatarGen + Draping + AutoQC.

- **Services** (15): `AutoQCService`, `AvatarGenService`, `CatalogueService`, `DailyDropTriggerService`, `DrapingService`, `DynamicPromptService`, `FdpService`, `GcsService`, `GcsStorageService`, `GraySkullService`, `PersonaService`, `PushNotificationService`, `StorageService`, `StyleDropJobService`, `StyleDropOptOutService`
- **Exceptions** (23 total): `AutoQCApiException`, `AvatarGenApiException`, `AvatarStoreException`, `CatalogueServiceException`, `CircuitBreakerOpenException`, `DrapingApiException`, `DrapingValidationException`, `DropsenseException`, `DynamicPromptApiException`, `GcsOperationException`, `GenvoyRateLimitException`, `InvalidRequestException`, `JobNotFoundException`, `NpsApiException`, `PersonaApiException`, `PersonaValidationException`, `PipelineDataNotFoundException`, and 3 more
- **State enums**: `AggFragmentType`, `AvatarStatus`, `Gender`, `JobMode`, `NotificationStatus`, `OptOutStatus`, `PipelineStatus`, `PipelineTopic`, `StageStatus`, `StyleDropStatus`, `VTONAggFragmentType`
- **Data contracts**: 19 DTO / Request / Response classes

## Module map — `slap-feed` (Java feature branch of edison, prod `slap-feed`)

Feed + card generation, plus a **large `feed-adk-poc/`** sub-module (18 services including `CartService`, `PersonaGenerationService`, `TrendsGenerationService`, `VisualAttributeExtractionService`). Feed-side services in `edison-discovery/`:

- `AgenticSessionResponseCacheService`, `GeminiService`, `GroundingService`, `MoodBoardService`, `ProductSearchService`, `QueryReformulationService`, `ResponseBuilderService`, `ResponseFrameService`, `SourceLinksWidgetService`, `ViewMoreService`

Style-drop side (`style-drop/`, 64 files): `AutoQCService`, `DocumentService`, `EventIngestionService`, `GCSService`, `StyleDropService` + enum `LikeDislikeState`, `StyleDropStatus`.

Feed-related bug lands here typically → `slap-feed/edison-discovery/` or `slap-feed/feed-adk-poc/`.

## Module map — `social-finds-pipeline` (Java feature branch of edison)

Social Finds ingestion + processing. Notable modules:

- **`social-finds/`** — `SlapUserSocialsService`, `SocialFindService`, `UserSocialFindService`, `SocialFindsResource` (HTTP entry point)
- **`edison-discovery/`** — `MoodboardService`, `ResponseFrameService`, `SaqService`; handlers include `AgentHandler`, `DriveConversationHandler`, `FindProductsHandler`
- **`expert-review/`** — `ExpertReviewService`, enum `Sentiment` — this is the Review Synth pipeline
- **`multi-turn/`**, **`prompts-manager/`** — small support modules

## Module map — `FaceNet` (Python)

Small — just 3 classes: `FaceEmbedding`, `InputData`, `OutputData`. This is the VTON face-embedding model service. Bugs about VTON *inference quality* (embeddings failing, wrong persona match) land here; bugs about *VTON UI* (upload flow, image display) are UI.

---

## Team roster & sub-area ownership

From Yatin's Labs org chart:

| Engineer | Role | Sub-area |
|---|---|---|
| **Sachin** | SDE-3 | VTON, Social Finds, Style Drops, any new VTON/StyleDrops image-gen offshoot alongside Social Finds ("Find your clothes"). Reports to Yatin. |
| Yatin | Manager | Escalation target — see `subagent_owner.py`. Also manages UI + Immersive. |

Historical assignees who show up in the corpus (from `data/embedding_index_team_roster.json`): Aryan Goenka, Divyansh Khandelwal, Kuldeep Singh Bhandari, Darjidarshan Kanubhai, Shreya Choudhary. Some may be present-day contributors, some may be alumni — treat as "have historically touched BE-Labs code" not "current owner."

---

## Data stores + external services

- **GCS** — dropsense's storage layer (`GcsService`, `GcsStorageService`, `AvatarStoreException`)
- **Airflow / xcom** — pipelines. Real bug: "MySQL db increase due to xcom" traces here.
- **Genvoy** — GenAI gateway used from `GraySkullService`, VTON pipelines. Rate limits show up as `GenvoyRateLimitException`.
- **Gemini** — `GeminiService` in `slap-feed/edison-discovery/`. Timeouts → `GeminiService`.
- **FaceNet inference service** — VTON persona matching. Owns face-embedding logic.

---

## What is NOT Backend-Labs

- Chat AI / search / cart / checkout / auth / payment / product-page core failures → **Backend**
- Chat model quality / response relevance / ranking / prompt / grounding → **DS**
- Any `[iOS]`, `[Android]`, `[RN]`, `[Native]` prefixed bug on a BE-Labs surface — the failure is in the React Native shell → **UI**
- 3D SDK / AR-VR / Beauty VTO / Camera Filters — those are Immersive under Yatin (separate track)

---

## Common title-prefix conventions

- `[VTON]`, `[Vton]` — Virtual Try-On
- `[StyleDrops]`, `[Style Drops]`, `[Styledrops]` — Style Drops
- `[Social Finds]`, `[SF]` — Social Finds
- `[Decoded Looks]` — Decoded Looks
- `[Review Synth]` — Expert Review pipeline
- `[Complete your look]`, `[Feed]` — feed generation
- `[Cosmos]` — observability dashboard
- `[MoodBoard]` — MoodBoard feature
