# `social-finds-pipeline` — repo skill (auto-generated)

_Last refreshed: 2026-07-07 06:30 UTC_

## At a glance

- **Owner team**: Backend-Labs
- **Declared stack** (from repos.json): java
- **Production branch**: `social-finds-master-uat`
- **Remote**: https://github.fkinternal.com/Flipkart/edison.git
- **Source files** (filtered to relevant extensions): 526

**Stated purpose** (from manifest):
> Social Finds ingestion + processing. Branched off edison's mainline; includes the social-finds/ module plus uat-track variations.

**Owns these features:**
- Social Finds
- reels ingestion
- social content discovery

## Build / dependency files present

- `pom.xml` → Java (Maven)
- `Dockerfile` → containerised service

## Language breakdown

Source-file counts by extension (top 8):

- `.java`: 525 files
- `.sh`: 1 files

## Module map — top directories with mined symbols

Symbols below are extracted from real class-file names / grep output on the current clone. Each list is capped to keep the skill file readable (limit: 20 per bucket).

### `product-page/` — 101 source files
- **HTTP entry points** (1): `ProductPageResource`
- **Exceptions** (2): `ComponentException`, `ProductPageException`
- **Enums** (11): `Currency`, `DynamicSectionType`, `DynamicTaskStatus`, `ErrorCode`, `MarketPlace`, `MediaType`, `ProductSpecificationType`, `SentimentType`, `VariantStatus`, `VarientType`, `VarientViewType`
- **Data contracts**: 8 DTO / Request / Response classes

### `edison-discovery/` — 81 source files
- **Services** (3): `MoodboardService`, `ResponseFrameService`, `SaqService`
- **HTTP entry points** (4): `AgentHandler`, `DriveConversationHandler`, `FindProductsHandler`, `MoodBoardResource`
- **Enums** (5): `AgentType`, `AppdataKey`, `MessageType`, `QueryIntentTypeStatus`, `StreamingStatus`
- **Data contracts**: 19 DTO / Request / Response classes

### `catalog/` — 64 source files
- **Services** (8): `DocumentService`, `OfflineDataLoaderService`, `OfflineLoaderExecutorService`, `PricingService`, `ProductDetailService`, `UserReviewService`, `VariantService`, `VariantsPivotService`
- **HTTP entry points** (2): `OfflineDataLoaderResource`, `ProductInfoResource`
- **Exceptions** (1): `CatalogException`
- **Enums** (5): `ContentType`, `ErrorCode`, `ImageType`, `VariantStatus`, `ViewType`
- **Data contracts**: 4 DTO / Request / Response classes

### `edison-common/` — 50 source files
- **Services** (1): `EdisonConfigService`
- **Exceptions** (3): `EdisonBotException`, `EdisonClientException`, `TokenServiceException`
- **Enums** (5): `EdisonConfigBucketKey`, `EdisonModules`, `Environment`, `ErrorCode`, `UseCase`

### `authentication/` — 48 source files
- **Services** (2): `AuthenticationService`, `KevlarTokenService`
- **HTTP entry points** (1): `AuthenticationResource`
- **Exceptions** (1): `AuthenticationException`
- **Enums** (6): `AgeGroup`, `AuthVerificationType`, `ErrorCode`, `ErrorType`, `Gender`, `StatusType`
- **Data contracts**: 11 DTO / Request / Response classes

### `aerospike-client/` — 38 source files
- **Services** (1): `AerospikePolicyService`
- **HTTP entry points** (7): `BatchDeleteSuccessHandler`, `BatchFailureHandler`, `DeleteSuccessHandler`, `ExistsSuccessHandler`, `FailureHandler`, `RecordSuccessHandler`, `WriteSuccessHandler`
- **Exceptions** (1): `AerospikeClientException`
- **Enums** (1): `ErrorCode`
- **Data contracts**: 7 DTO / Request / Response classes

### `conversation-history/` — 33 source files
- **Services** (2): `ConversationHistoryService`, `ConversationSummaryService`
- **HTTP entry points** (1): `ConversationHistoryResource`
- **Exceptions** (1): `ConversationHistoryException`
- **Enums** (2): `ConversationSummaryStrategy`, `ErrorCode`
- **Data contracts**: 3 DTO / Request / Response classes

### `social-finds/` — 25 source files
- **Services** (3): `SlapUserSocialsService`, `SocialFindService`, `UserSocialFindService`
- **HTTP entry points** (2): `HealthCheckResource`, `SocialFindsResource`
- **Exceptions** (1): `SocialFindException`
- **Enums** (2): `ErrorCode`, `MediaType`
- **Data contracts**: 1 DTO / Request / Response classes

### `style-drop/` — 22 source files
- **Services** (2): `GCSService`, `StyleDropService`
- **HTTP entry points** (1): `StyleDropResource`
- **Enums** (2): `Gender`, `ImageType`
- **Data contracts**: 5 DTO / Request / Response classes

### `edison-core/` — 20 source files
- **Services** (1): `EdisonService`
- **HTTP entry points** (3): `HealthCheckResource`, `LandingPageResource`, `PingResource`
- **Data contracts**: 4 DTO / Request / Response classes

### `expert-review/` — 18 source files
- **Services** (1): `ExpertReviewService`
- **HTTP entry points** (2): `ExpertReviewResource`, `HealthCheckResource`
- **Exceptions** (1): `ExpertReviewException`
- **Enums** (3): `ErrorCode`, `MediaType`, `Sentiment`
- **Data contracts**: 2 DTO / Request / Response classes

### `multi-turn/` — 18 source files
- **Exceptions** (1): `MultiTurnException`
- **Enums** (1): `ErrorCode`

### `prompts-manager/` — 8 source files
- **Exceptions** (1): `PromptsManagerException`
- **Enums** (1): `PromptId`

### `charts/` — 0 source files

### `config/` — 0 source files

## Recent commits (1 most recent)

| Date | Author | Subject |
|---|---|---|
| 2025-07-03 | sachin.srinivasan | req body |

## README excerpt (first ~3 KB)

> To run edison locally plz run this:
> ssh -N -L localhost:3000:10.68.202.42:3000 10.50.146.109 
>
> https://docs.google.com/document/d/1aE4mk7zg7CcT8wCDZ7Rev0Dk1eM7YwKPVxY3K--vjv0/edit?tab=t.0

---

_This file is auto-generated by `build_repo_skills.py` from the live clone. Re-run that script to refresh._
