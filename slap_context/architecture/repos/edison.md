# `edison` — repo skill (auto-generated)

_Last refreshed: 2026-07-07 06:30 UTC_

## At a glance

- **Owner team**: Backend
- **Declared stack** (from repos.json): java
- **Production branch**: `productions`
- **Remote**: https://github.fkinternal.com/Flipkart/edison.git
- **Source files** (filtered to relevant extensions): 1704

**Stated purpose** (from manifest):
> Core SLAP backend service. Owns chat AI, search, cart, checkout, payment, auth, session management, conversation handling, journey continuation, secrets (Grayskull).

**Owns these features:**
- chat AI
- search
- cart
- checkout
- payment
- auth
- OTP
- sessions
- Grayskull
- secrets
- Edison
- journey continuation
- conversation handling
- log levels
- product compare

## Build / dependency files present

- `pom.xml` → Java (Maven)
- `Dockerfile` → containerised service

## Language breakdown

Source-file counts by extension (top 8):

- `.java`: 1702 files
- `.sh`: 2 files

## Module map — top directories with mined symbols

Symbols below are extracted from real class-file names / grep output on the current clone. Each list is capped to keep the skill file readable (limit: 20 per bucket).

### `edison-discovery/` — 178 source files
- **Services** (13): `AgenticSessionResponseCacheService`, `GeminiService`, `GroundingService`, `HyperlocalExecutorService`, `MinutesProductEnrichmentService`, `MoodBoardService`, `ProductSearchService`, `QueryReformulationService`, `ReasonsToBuyService`, `ResponseBuilderService`, `ResponseFrameService`, `SourceLinksWidgetService`, `ViewMoreService`
- **HTTP entry points** (5): `AgentHandler`, `DriveConversationHandler`, `FindProductsHandler`, `MoodBoardResource`, `ViewMoreResource`
- **Exceptions** (1): `EdisonDiscoveryException`
- **Enums** (8): `AgentType`, `ErrorCode`, `Offers`, `ProductCardSource`, `ProductCardStatus`, `QueryClassifier`, `SearchPipeline`, `StreamingStatus`
- **Data contracts**: 11 DTO / Request / Response classes

### `edison-core/` — 163 source files
- **Services** (10): `AddressSelectionService`, `DavinciSearchService`, `FbtService`, `FeatureFlagsService`, `HyperLocalSearchService`, `HyperlocalServiceabilityService`, `LandingPageService`, `SimilarProductService`, `WebProductLookupService`, `WebSearchService`
- **HTTP entry points** (8): `AddressResource`, `DAToolErrorHandler`, `FbtResource`, `FeatureFlagsResource`, `HealthCheckResource`, `LandingPageResource`, `OtaApiResource`, `PingResource`
- **Exceptions** (2): `DAToolExecutionException`, `DAToolValidationException`
- **Enums** (1): `DAIntentType`
- **Data contracts**: 12 DTO / Request / Response classes

### `product-page/` — 162 source files
- **Services** (1): `OffersService`
- **HTTP entry points** (1): `ProductPageResource`
- **Exceptions** (2): `ComponentException`, `ProductPageException`
- **Enums** (10): `Currency`, `DynamicDataType`, `DynamicTaskStatus`, `ErrorCode`, `MarkerType`, `MarketPlace`, `MediaType`, `ProductSpecificationType`, `SentimentType`, `Serviceability`
- **Data contracts**: 16 DTO / Request / Response classes

### `edison-common/` — 159 source files
- **Services** (4): `EdisonConfigService`, `FDPService`, `NPSExecutorService`, `SimilarProductExecutorService`
- **Exceptions** (5): `EdisonBotException`, `EdisonClientException`, `EdisonCommonException`, `EdisonException`, `OtaException`
- **Enums** (15): `ActionNameFdp`, `EdisonConfigBucketKey`, `EdisonModules`, `Environment`, `ErrorCode`, `ImageType`, `InHouseModel`, `MarketPlace`, `NpsMinimalImageType`, `OtaErrorCode`, `PillType`, `RateLimiterKey`, `RequestFlowStep`, `UseCase`, `WaitlistStatus`
- **Data contracts**: 4 DTO / Request / Response classes

### `authentication/` — 117 source files
- **Services** (6): `AccountMappingService`, `AuthenticationService`, `KevlarTokenService`, `OtpService`, `TokenService`, `UserProfileService`
- **HTTP entry points** (2): `AuthenticationResource`, `ExceptionHandler`
- **Exceptions** (5): `AuthenticationException`, `DobLimitExceededException`, `ServiceException`, `TokenServiceException`, `ValidationException`
- **Enums** (6): `AgeGroup`, `AuthVerificationType`, `ErrorCode`, `ErrorType`, `Gender`, `StatusType`
- **Data contracts**: 11 DTO / Request / Response classes

### `social-finds/` — 117 source files
- **Services** (10): `MediaPipelineService`, `MessageHandlerService`, `RateLimitService`, `SFFrameProductsService`, `SFResponseBuilderService`, `SocialFindsChatService`, `SocialFindsCronService`, `SocialFindsDataService`, `SocialFindsPostService`, `SocialFindsService`
- **HTTP entry points** (17): `AbstractDmUsecaseHandler`, `AbstractPnUsecaseHandler`, `ConversationStartedDuplicateHandler`, `DeeplinkNotOpenedPnUsecaseHandler`, `DuplicateRequestHandler`, `HealthCheckResource`, `InactivePnUsecaseHandler`, `MediaPipelineInvocationFailedHandler`, `MediaPipelineStartedHandler`, `NoProductFoundHandler`, `ReelsRefreshDmUsecaseHandler`, `SocialFindsDelayHandler`, `SocialFindsResource`, `SocialFindsWebhookHandler`, `UsecaseHandler`, `UserMessageFailedHandler`, `UserMessageSentHandler`
- **Exceptions** (1): `SocialFindException`
- **Enums** (12): `BotResponseType`, `ConversationStatus`, `DeliveryError`, `ErrorCode`, `FailureReason`, `MediaType`, `PushNotificationFailureReason`, `RequestCategory`, `SFUsecaseType`, `Source`, `UserMessageType`, `VtonStatus`
- **Data contracts**: 9 DTO / Request / Response classes

### `catalog/` — 115 source files
- **Services** (8): `DocumentService`, `OfflineDataLoaderService`, `PolicyService`, `ProductDetailService`, `UserReviewService`, `VariantService`, `VariantsPivotService`, `VerticalClassifierService`
- **HTTP entry points** (3): `OfflineDataLoaderResource`, `ProductInfoResource`, `VerticalClassifierResource`
- **Exceptions** (1): `CatalogException`
- **Enums** (8): `ContentType`, `DataIngestionFlow`, `ErrorCode`, `ImageType`, `NpsMinimalImageType`, `VariantStatus`, `VerticalClassification`, `ViewType`
- **Data contracts**: 5 DTO / Request / Response classes

### `style-drop/` — 99 source files
- **Services** (8): `DocumentService`, `EventIngestionService`, `FtuePipelineTriggerService`, `GCSService`, `ImageQcService`, `StyleDropOptOutService`, `StyleDropService`, `VtonService`
- **HTTP entry points** (2): `StyleDropResource`, `VtonResource`
- **Exceptions** (1): `StyleDropException`
- **Enums** (10): `ErrorCode`, `Gender`, `ImageType`, `LikeDislikeState`, `OnboardStatus`, `OptOutStatus`, `PipelineJobStatus`, `RawImagePathKeys`, `StyleDropStatus`, `VtonStatusEnum`
- **Data contracts**: 33 DTO / Request / Response classes

### `cron/` — 55 source files
- **Services** (4): `AbstractCronService`, `ConversationHistoryFetchService`, `CronService`, `SessionMemoryGenerationCronService`
- **HTTP entry points** (1): `GenericMemoryGenerationResource`
- **Exceptions** (1): `CronServiceException`
- **Enums** (2): `ErrorCode`, `MemoryGenerationType`

### `checkout/` — 54 source files
- **Services** (2): `AddressService`, `CheckoutService`
- **HTTP entry points** (2): `CheckoutResource`, `HealthCheckResource`
- **Exceptions** (2): `CheckoutServiceException`, `CheckoutServiceRuntimeException`
- **Enums** (5): `AdjustmentType`, `CheckoutStatus`, `ErrorCode`, `ItemState`, `UseCase`
- **Data contracts**: 4 DTO / Request / Response classes

### `my-orders/` — 48 source files
- **Services** (1): `MyOrdersService`
- **HTTP entry points** (1): `MyOrdersResource`
- **Exceptions** (1): `MyOrdersServiceException`
- **Enums** (2): `ErrorCode`, `SlapOrderStatus`
- **Data contracts**: 2 DTO / Request / Response classes

### `aerospike-client/` — 46 source files
- **Services** (2): `AerospikePolicyService`, `GraySkullService`
- **HTTP entry points** (7): `BatchDeleteSuccessHandler`, `BatchFailureHandler`, `DeleteSuccessHandler`, `ExistsSuccessHandler`, `FailureHandler`, `RecordSuccessHandler`, `WriteSuccessHandler`
- **Exceptions** (1): `AerospikeClientException`
- **Enums** (1): `ErrorCode`
- **Data contracts**: 10 DTO / Request / Response classes

### `conversation-history/` — 46 source files
- **Services** (4): `ConversationHistoryService`, `ConversationSummaryService`, `SFConversationHistoryService`, `SuggestedQueriesCacheService`
- **HTTP entry points** (1): `ConversationHistoryResource`
- **Exceptions** (1): `ConversationHistoryException`
- **Enums** (4): `ChatType`, `ConversationStatus`, `ConversationSummaryStrategy`, `ErrorCode`
- **Data contracts**: 3 DTO / Request / Response classes

### `user-memory/` — 46 source files
- **Services** (3): `EmbeddingGenerationService`, `UserMemoryEmbeddingService`, `UserMemoryService`
- **HTTP entry points** (1): `UserMemoryResource`
- **Exceptions** (1): `UserMemoryException`
- **Enums** (1): `ErrorCode`
- **Data contracts**: 8 DTO / Request / Response classes

### `notifications/` — 42 source files
- **Services** (1): `PushNotificationService`
- **HTTP entry points** (2): `PushNotificationExceptionHandler`, `PushNotificationResource`
- **Exceptions** (3): `NotificationException`, `ServiceException`, `ValidationException`
- **Enums** (3): `ErrorCode`, `NotificationChannel`, `NotificationType`
- **Data contracts**: 8 DTO / Request / Response classes

_(plus 14 smaller dirs not shown)_

## Recent commits (1 most recent)

| Date | Author | Subject |
|---|---|---|
| 2026-06-22 | Aryan Goenka | FLIPPI-2066 : Adding FailureReason (#1631) |

## README excerpt (first ~3 KB)

> To run edison locally plz run this:
> ssh -N -L localhost:3000:10.68.202.42:3000 10.50.146.109 
>
>
> https://docs.google.com/document/d/1aE4mk7zg7CcT8wCDZ7Rev0Dk1eM7YwKPVxY3K--vjv0/edit?tab=t.0

---

_This file is auto-generated by `build_repo_skills.py` from the live clone. Re-run that script to refresh._
