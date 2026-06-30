# Spaghetti — Component & Screen Inventory

React Native UI library for SLAP (Flipkart fashion platform). Exports via `src/components/index.ts` and `src/screens/index.ts`, re-exported from root `index.ts`.

---

## Common Bug Routing Signals

> Bugs mentioning these UI elements route here:

| Symptom | Component / Screen |
|---|---|
| "address bottomsheet not refreshing" | `AddressListScreen` |
| "logout doesn't clear my account" | `UserProfileScreen` / `DeleteAccountScreen` |
| "tag pill font wrong on iOS" | `FeedsCardHeader` (`feedscommoncomponents/`) |
| "cart summary bar not updating" | `CartSummaryBar` |
| "try-on image not showing" | `VTOnImageOverlay` / `VTOnTryOnResult` |
| "style drops catalog blank" | `SDCatalogScreen` |
| "mood board not loading" | `MoodBoard` / `MoodBoardCarousel` |
| "product card price missing" | `FashionProductCardCarousel` / `MELProductCardCarousel` |
| "chat input bar freezes" | `AnimatedInputBar` / `TextInputBar` |
| "feeds card not rendering" | `FeedsLoaderComponent` / `ExploreFeedCard` |
| "onboarding screen skip broken" | `OnboardingScreen` / `WelcomeScreen` |
| "size chart not opening" | `SizeChartContent` / `SwatchSelectorScreen` |
| "minutes product out of stock" | `MinutesItemsUnaviliable` |
| "review bottomsheet crash" | `AllUserReviewBottomSheet` |
| "notification permission prompt missing" | `NotificationScreenBottomSheet` / `PermissionScreen` |

---

## Components

### Core UI
| Component | Export |
|---|---|
| `AppImageView` | `appimageview/` |
| `AppListView` | `applistview/` |
| `AppVideoPlayer` | `appvideoplayer/` |
| `Markdown` (default) | `Markdown/lib/Markdown` |
| `PillButton` | `Buttons/` |
| `RadioIcon` | `RadioIcon/` |
| `SwitchButton` | `switchbutton/` |
| `VerticalPager` | `verticalpager/` |
| `MaskedViewGradientText` | `common/` |

### Input & Interaction
| Component | Export |
|---|---|
| `AnimatedInputBar` | `AnimatedInputBar/` |
| `TextInputBar` | `TextInputBar/` |
| `QuickReplyWidget` | `quickReply/` |
| `RetryChat` | `retryChat/` |

### Carousels & Pagination
| Component | Export |
|---|---|
| `FashionProductCardCarousel` | `FashionProductCard/` |
| `MELProductCardCarousel` | `melproductcard/` |
| `MinutesCardCarousel` | `minutesproductcard/` |
| `MinutesAutoAddCarousel` | `minutesautoadd/` |
| `MinutesFBTCarousel` | `minutesfbtcarousel/` |
| `ScaleCarousel` / `ScaleCarouselItem` | `common/scalecarousel/` |
| `SlidingPaginationDots` | `common/slidingpaginationdots/` |
| `MoodBoard` / `MoodBoardCarousel` | `moodBoard/` |
| `SourcesCarousel` | `sources/` |

### Loaders & Skeletons
| Component | Export |
|---|---|
| `FeedsLoaderComponent` | `feedscommoncomponents/` |
| `ContextualLoader` | `contextualLoader/` |
| `NewContextualLoader` | `contextualLoader/` |
| `ConversationHistorySkeleton` | `skeletons/` |
| `Chatskeleton` | `skeletons/` |
| `EmptyChatMessage` | `emptychatmessage/` |

### Cart & Commerce
| Component | Export |
|---|---|
| `CartSummaryBar` | `cartsummarybar/` |
| `SizeChartContent` | `sizeselector/` |
| `PriceOfferCard` | `feedspriceoffer/` |
| `MinutesItemsUnaviliable` | `minutesitemsunaviliable/` |
| `CrossCategoryNudge` | `crosscategorynudge/` |
| `DiscoverPillCard` | `DiscoverPillCard/` |
| `SlapExclusiveOffer` | `slapexclusiveoffer/` |
| `MinimumOrderBanner` / `MinimumOrderBottomSheet` | `minimumorderbanner/` |

### Feeds Cards
| Component | Export |
|---|---|
| `OccasionCard` | `feedsocassioncard/` |
| `FeedsLowIntentJourneyCard` | `feedsintentjourney/` |
| `FeedsLowIntentJourneyContinuationCard` | `feedsintentjourney/` |
| `FeedsProductCompare` | `feedsproductcompare/` |
| `FeedsCategoryCompare` | `feedscategorycompare/` |
| `FeedsDiscoverApparelsCard` | `feedsdiscoverapparels/` |
| `FeedsReviewSynthesizer` | `feedsreviewsynthesizer/` |
| `FeedsPricingTrend` | `feedspricingtrend/` |
| `CompleteYourLook` | `feedscompleteyourlook/` |
| `FeedsBestSeller` | `feedsbestseller/` |
| `FeedsBottomCard` | `feedsbottom/` |
| `ExploreFeedCard` | `explorefeedcard/` |
| `GetToKnowYouBetterCard` | `gettoknowyoubetter/` |
| `AnswerSpecificProductQuestion` | `answerspecificquestion/` |

### StyleDrops & VTON
| Component | Export |
|---|---|
| `StyleDropsFeedCard` | `styledropsfeedcard/` |
| `SocialFindsFeedsCard` | `socialfindsfeedscard/` |
| `SocialFindsHeader` | `socialFindsHeader/` |
| `VTOnImageOverlay` | `screens/vtonbottomsheet/tryOnResult/` |
| `VTOnTryOnResult` | `screens/vtonbottomsheet/tryOnResult/` |
| `SDTryOnCard` / `SDTryOnList` / `SDGeneratedList` | `screens/styledrops/sdtryongeneratedsection/` |
| `SDTryOnGeneratedSection` | `screens/styledrops/sdtryongeneratedsection/` |
| `SDSavedLook` | `screens/styledrops/savedLooks/` |
| `DeleteVtonDataBottomSheet` | `screens/deletevtondatabottomsheet/` |
| `OutOfTryOnsBottomSheet` | `screens/vtonbottomsheet/outoftryon/` |
| `VirtualTryOnStatusBannerView` | `screens/vtonbanner/` |
| `AllDropsSection` | `screens/styledrops/sdcatalog/components/` |

### Feedback & Chat
| Component | Export |
|---|---|
| `ChatFeedback` | `feedback/` |
| `ShareFeedBackForm` | `screens/ShareFeedBackFormScreen` |

---

## Screens

### Auth & Onboarding
| Screen | Export |
|---|---|
| `OnboardingScreen` | `loginscreen/` |
| `WelcomeScreen` | `welcomescreen/` |
| `LoginSuccess` | `onboarding/` |
| `UserNameScreen` | `onboarding/username/` |
| `OnboardingQuestionnaireScreen` | `onboarding/onboardingquestionnaire/` |
| `IOSConsentScreen` | `iosconsentscreen/` |
| `KnowMoreBottomSheet` | `onboarding/` |
| `InformationBottomSheet` | `onboarding/` |
| `CustomerContactBottomSheet` | `onboarding/` |
| `PrivacyPolicyScreen` | `onboarding/` |
| `SocialFindsScreen` | `socialFindsOnboarding/` |

### Home & Navigation
| Screen | Export |
|---|---|
| `HomeScreen` / `HomeScreenHeader` | `homescreen/` |
| `HomeErrorScreen` | `homescreen/` |
| `AppErrorFallbackScreen` | `apperrorfallback/` |
| `FeedsScreenEntranceOverlay` | `feeds/` |
| `BottomSheetModalScreen` | `bottomsheetmodalscreen/` |
| `InAPPBrowser` | `inAppBrowser/` |

### Product
| Screen | Export |
|---|---|
| `ProductScreen` / `ProductDisplayCardScreen` | `productscreen/` |
| `KeySpecificationBottomSheet` | `keyspecificationbottomsheet/` |
| `PriceTrendBottomSheet` | `pricetrendbottomsheet/` |
| `AllUserReviewBottomSheet` | `reviewbottomsheet/` |
| `MediaListScreen` | `allmediasheet/` |
| `ViewSimilarBottomSheet` | `viewsimilarbottomsheet/` |
| `ChatVariantBottomSheetScreen` / `ChatVariantBottomSheetSkeleton` | `chatvariantbottomsheet/` |
| `SwatchSelectorScreen` | `swatchselector/` |
| `VariantSelectorScreen` | `variantselector/` |
| `ServiceCenterBottomSheet` | `components/trustmarkers/` |

### StyleDrops
| Screen | Export |
|---|---|
| `SDOnboardingScreen` | `styledrops/` |
| `SDCreateAvatar` | `styledrops/` |
| `SDCatalogScreen` | `styledrops/sdcatalog/` |
| `StyleDropsLookDetailView` | `styledrops/` |
| `SDSelfiePreviewScreen` | `styledrops/` |
| `SDImageUploadReview` | `styledrops/` |
| `StyleDropImageUploadScreen` | `styledrops/` |
| `SDErrorScreen` | `styledrops/components/` |
| `StyleDropSupportScreen` | `StyleDropSupportScreen/` |
| `StyledropReupload` | `styledropreuploadbottomsheet/` |
| `CameraPermissionModal` | `styledrops/components/` |

### VTON (Virtual Try-On)
| Screen | Export |
|---|---|
| `VTOnBottomSheet` | `vtonbottomsheet/productSheet/` |
| `VTOnTryOnResult` | `vtonbottomsheet/tryOnResult/` |
| `OutOfTryOnsBottomSheet` | `vtonbottomsheet/outoftryon/` |
| `DeleteVtonDataBottomSheet` | `deletevtondatabottomsheet/` |
| `SDTryOnGeneratedSection` / `SDTryOnList` / `SDGeneratedList` | `styledrops/sdtryongeneratedsection/` |
| `SDSavedLook` | `styledrops/savedLooks/` |

### Social Finds
| Screen | Export |
|---|---|
| `SocialFindsHistory` | `socialFindsHistory/` |
| `ConversationHistory` | `conversationHistory/` |

### Cart & Payment
| Screen | Export |
|---|---|
| `CartBottomSheetScreen` | `cartBottomsheet/` |
| `PaymentScreen` | `paymentscreen/` |
| `OfferTnCDetailsScreen` / `OfferDetailsBottomSheet` | `offers/` |

### Orders
| Screen | Export |
|---|---|
| `MyOrdersPageScreen` | `MyOrdersListPageScreen` |
| `OrderPageNavigation` | `OrderPageNavigation` |
| `NoOrderPageScreen` | `NoOrderPageScreen` |

### Profile & Account
| Screen | Export |
|---|---|
| `UserProfileScreen` | `profilescreen/` |
| `EditProfileScreen` | `editprofilescreen/` |
| `DeleteAccountScreen` | `deleteaccountscreen/` |
| `PrivacyScreen` | `privacyscreen/` |

### Address
| Screen | Export |
|---|---|
| `AddressListScreen` | `addresbottomsheet/` |
| `AddressChangeConfirmationBottomSheet` | `addresschangeconfirmationbottomsheet/` |

### Permissions & Settings
| Screen | Export |
|---|---|
| `PermissionScreen` | `permissionscreen/` |
| `PermissionSettingsScreen` | `permissionsettings/` |
| `NotificationScreenBottomSheet` | `notificationscreenbottomsheet/` |

### Misc
| Screen | Export |
|---|---|
| `SupportScreen` | `supportscreen/` |
| `MediaHandler` | `mediahandler/` |
| `MoodboardList` | `moodboardbottomsheet/` |
| `TPLScreen` | `TPLscreen/` |
| `WaitingListScreen` | `waitingList/` |
| `UnseenScreen` | `unseenscreen/` |
| `ShareFeedBackForm` | `ShareFeedBackFormScreen` |

---

## Utilities (exported from screens/index.ts)
| Utility | Export |
|---|---|
| `triggerHaptic` / `HapticFeedbackTypes` / `defaultHapticOptions` | `Utils/hapticTouchConstant` |
| `getNextMidnightIST` | `vtonbottomsheet/outoftryon/` |
