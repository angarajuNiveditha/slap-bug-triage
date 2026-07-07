# `slap-feed` — repo skill (auto-generated)

_Last refreshed: 2026-07-07 06:30 UTC_

## At a glance

- **Owner team**: Backend-Labs
- **Declared stack** (from repos.json): java
- **Production branch**: `slap-feed`
- **Remote**: https://github.fkinternal.com/Flipkart/edison.git
- **Source files** (filtered to relevant extensions): 1538

**Stated purpose** (from manifest):
> Feed + card generation work for SLAP. Branched off edison's mainline; includes a feed-adk-poc/ directory plus the standard edison modules.

**Owns these features:**
- feed cards
- card generation
- Vibes Player feed
- feed personalisation

## Build / dependency files present

- `pom.xml` → Java (Maven)
- `Dockerfile` → containerised service

## Language breakdown

Source-file counts by extension (top 8):

- `.java`: 1537 files
- `.sh`: 1 files

## Module map — top directories with mined symbols

Symbols below are extracted from real class-file names / grep output on the current clone. Each list is capped to keep the skill file readable (limit: 20 per bucket).

### `product-page/` — 161 source files
- **Services** (1): `OffersService`
- **HTTP entry points** (1): `ProductPageResource`
- **Exceptions** (2): `ComponentException`, `ProductPageException`
- **Enums** (10): `Currency`, `DynamicDataType`, `DynamicTaskStatus`, `ErrorCode`, `MarkerType`, `MarketPlace`, `MediaType`, `ProductSpecificationType`, `SentimentType`, `Serviceability`
- **Data contracts**: 15 DTO / Request / Response classes

### `edison-discovery/` — 156 source files
- **Services** (10): `AgenticSessionResponseCacheService`, `GeminiService`, `GroundingService`, `MoodBoardService`, `ProductSearchService`, `QueryReformulationService`, `ResponseBuilderService`, `ResponseFrameService`, `SourceLinksWidgetService`, `ViewMoreService`
- **HTTP entry points** (7): `AgentHandler`, `DecisionAssistantHandler`, `DriveConversationHandler`, `FeedSearchResource`, `FindProductsHandler`, `MoodBoardResource`, `ViewMoreResource`
- **Exceptions** (1): `EdisonDiscoveryException`
- **Enums** (8): `AgentType`, `ErrorCode`, `Offers`, `ProductCardSource`, `ProductCardStatus`, `QueryClassifier`, `SearchPipeline`, `StreamingStatus`
- **Data contracts**: 11 DTO / Request / Response classes

### `edison-common/` — 138 source files
- **Services** (4): `EdisonConfigService`, `FDPService`, `NPSExecutorService`, `SimilarProductExecutorService`
- **Exceptions** (5): `EdisonBotException`, `EdisonClientException`, `EdisonCommonException`, `EdisonException`, `OtaException`
- **Enums** (14): `ActionNameFdp`, `EdisonConfigBucketKey`, `EdisonModules`, `Environment`, `ErrorCode`, `ImageType`, `InHouseModel`, `NpsMinimalImageType`, `OtaErrorCode`, `PillType`, `RateLimiterKey`, `RequestFlowStep`, `UseCase`, `WaitlistStatus`
- **Data contracts**: 2 DTO / Request / Response classes

### `authentication/` — 116 source files
- **Services** (6): `AccountMappingService`, `AuthenticationService`, `KevlarTokenService`, `OtpService`, `TokenService`, `UserProfileService`
- **HTTP entry points** (2): `AuthenticationResource`, `ExceptionHandler`
- **Exceptions** (4): `AuthenticationException`, `ServiceException`, `TokenServiceException`, `ValidationException`
- **Enums** (6): `AgeGroup`, `AuthVerificationType`, `ErrorCode`, `ErrorType`, `Gender`, `StatusType`
- **Data contracts**: 11 DTO / Request / Response classes

### `edison-core/` — 108 source files
- **Services** (6): `DavinciSearchService`, `FeatureFlagsService`, `LandingPageService`, `SimilarProductService`, `WebProductLookupService`, `WebSearchService`
- **HTTP entry points** (6): `DAToolErrorHandler`, `FeatureFlagsResource`, `HealthCheckResource`, `LandingPageResource`, `OtaApiResource`, `PingResource`
- **Exceptions** (2): `DAToolExecutionException`, `DAToolValidationException`
- **Enums** (1): `DAIntentType`
- **Data contracts**: 8 DTO / Request / Response classes

### `social-finds/` — 106 source files
- **Services** (9): `MediaPipelineService`, `MessageHandlerService`, `RateLimitService`, `SFResponseBuilderService`, `SocialFindsChatService`, `SocialFindsCronService`, `SocialFindsDataService`, `SocialFindsPostService`, `SocialFindsService`
- **HTTP entry points** (17): `AbstractDmUsecaseHandler`, `AbstractPnUsecaseHandler`, `ConversationStartedDuplicateHandler`, `DeeplinkNotOpenedPnUsecaseHandler`, `DuplicateRequestHandler`, `HealthCheckResource`, `InactivePnUsecaseHandler`, `MediaPipelineInvocationFailedHandler`, `MediaPipelineStartedHandler`, `NoProductFoundHandler`, `ReelsRefreshDmUsecaseHandler`, `SocialFindsDelayHandler`, `SocialFindsResource`, `SocialFindsWebhookHandler`, `UsecaseHandler`, `UserMessageFailedHandler`, `UserMessageSentHandler`
- **Exceptions** (1): `SocialFindException`
- **Enums** (11): `BotResponseType`, `ConversationStatus`, `DeliveryError`, `ErrorCode`, `FailureReason`, `MediaType`, `PushNotificationFailureReason`, `RequestCategory`, `SFUsecaseType`, `Source`, `UserMessageType`
- **Data contracts**: 4 DTO / Request / Response classes

### `catalog/` — 104 source files
- **Services** (8): `DocumentService`, `OfflineDataLoaderService`, `PolicyService`, `ProductDetailService`, `UserReviewService`, `VariantService`, `VariantsPivotService`, `VerticalClassifierService`
- **HTTP entry points** (3): `OfflineDataLoaderResource`, `ProductInfoResource`, `VerticalClassifierResource`
- **Exceptions** (1): `CatalogException`
- **Enums** (9): `ContentType`, `DataIngestionFlow`, `ErrorCode`, `ImageType`, `MarketPlace`, `NpsMinimalImageType`, `VariantStatus`, `VerticalClassification`, `ViewType`
- **Data contracts**: 5 DTO / Request / Response classes

### `feed-adk-poc/` — 91 source files
- **Services** (18): `CartService`, `ConcurrentInMemorySessionService`, `FeedSearchService`, `NoOpProductRatingEnrichmentService`, `NpsProductDetailEnrichmentService`, `OffersService`, `OrderService`, `PersonaDataService`, `PersonaGenerationService`, `PnpService`, `ProductDetailEnrichmentService`, `ProductRatingEnrichmentService`, `RecentSearchesService`, `SelfieDataService`, `TrendsGenerationService`, `UgcProductRatingEnrichmentService`, `VisualAttributeExtractionService`, `WishlistService`
- **HTTP entry points** (2): `FeedSseController`, `PersonaTrendsController`
- **Enums** (2): `ConversationLogicType`, `CtaType`

### `style-drop/` — 64 source files
- **Services** (5): `AutoQCService`, `DocumentService`, `EventIngestionService`, `GCSService`, `StyleDropService`
- **HTTP entry points** (1): `StyleDropResource`
- **Exceptions** (1): `StyleDropException`
- **Enums** (6): `AutoQCStatus`, `ErrorCode`, `Gender`, `ImageType`, `LikeDislikeState`, `StyleDropStatus`
- **Data contracts**: 20 DTO / Request / Response classes

### `cron/` — 55 source files
- **Services** (4): `AbstractCronService`, `ConversationHistoryFetchService`, `CronService`, `SessionMemoryGenerationCronService`
- **HTTP entry points** (1): `GenericMemoryGenerationResource`
- **Exceptions** (1): `CronServiceException`
- **Enums** (2): `ErrorCode`, `MemoryGenerationType`

### `checkout/` — 52 source files
- **Services** (2): `AddressService`, `CheckoutService`
- **HTTP entry points** (2): `CheckoutResource`, `HealthCheckResource`
- **Exceptions** (2): `CheckoutServiceException`, `CheckoutServiceRuntimeException`
- **Enums** (5): `AdjustmentType`, `CheckoutStatus`, `ErrorCode`, `ItemState`, `UseCase`
- **Data contracts**: 4 DTO / Request / Response classes

### `user-memory/` — 46 source files
- **Services** (3): `EmbeddingGenerationService`, `UserMemoryEmbeddingService`, `UserMemoryService`
- **HTTP entry points** (1): `UserMemoryResource`
- **Exceptions** (1): `UserMemoryException`
- **Enums** (1): `ErrorCode`
- **Data contracts**: 8 DTO / Request / Response classes

### `aerospike-client/` — 45 source files
- **Services** (1): `AerospikePolicyService`
- **HTTP entry points** (7): `BatchDeleteSuccessHandler`, `BatchFailureHandler`, `DeleteSuccessHandler`, `ExistsSuccessHandler`, `FailureHandler`, `RecordSuccessHandler`, `WriteSuccessHandler`
- **Exceptions** (1): `AerospikeClientException`
- **Enums** (1): `ErrorCode`
- **Data contracts**: 10 DTO / Request / Response classes

### `my-orders/` — 44 source files
- **Services** (1): `MyOrdersService`
- **HTTP entry points** (1): `MyOrdersResource`
- **Exceptions** (1): `MyOrdersServiceException`
- **Enums** (2): `ErrorCode`, `SlapOrderStatus`
- **Data contracts**: 1 DTO / Request / Response classes

### `conversation-history/` — 39 source files
- **Services** (3): `ConversationHistoryService`, `ConversationSummaryService`, `SFConversationHistoryService`
- **HTTP entry points** (1): `ConversationHistoryResource`
- **Exceptions** (1): `ConversationHistoryException`
- **Enums** (4): `ChatType`, `ConversationStatus`, `ConversationSummaryStrategy`, `ErrorCode`
- **Data contracts**: 3 DTO / Request / Response classes

_(plus 11 smaller dirs not shown)_

## HTTP routes (12 @*Mapping annotations found)

| Verb | Path |
|---|---|
| `GET` | `/feed/{userId}` |
| `GET` | `/feed/{userId}/json` |
| `GET` | `/persona` |
| `GET` | `/persona/{accountId}` |
| `GET` | `/persona/{accountId}/json` |
| `GET` | `/trends` |
| `GET` | `/trends/{accountId}` |
| `GET` | `/trends/{accountId}/json` |
| `GET` | `/visual` |
| `POST` | `/visual/extract-all` |
| `GET` | `/visual/{accountId}` |
| `GET` | `/visual/{accountId}/json` |

## Config files present (1 Spring/YAML)

- `feed-adk-poc/src/main/resources/application.yml`

## Recent commits (1 most recent)

| Date | Author | Subject |
|---|---|---|
| 2026-03-26 | saumya.chauhan | prompt updated continue con & product comp |

## README excerpt (first ~3 KB)

> To run edison locally plz run this:
> ssh -N -L localhost:3000:10.68.202.42:3000 10.50.146.109 
>
> https://docs.google.com/document/d/1aE4mk7zg7CcT8wCDZ7Rev0Dk1eM7YwKPVxY3K--vjv0/edit?tab=t.0

---

_This file is auto-generated by `build_repo_skills.py` from the live clone. Re-run that script to refresh._
