# Mozzarella — Screen & Module Inventory

React Native app (slap-frontend) consuming the spaghetti UI library. Feature-based directory structure under `src/`. State via Redux Toolkit (17 slices), navigation via React Navigation.

---

## Common Bug Routing Signals

> Bugs mentioning these UI elements route here:

| Symptom | Screen / Module |
|---|---|
| "login OTP not sending" | `src/screens/auth/OtpVerificationScreenHOC` |
| "chat screen freezes / crashes" | `src/screens/chat/ChatScreen` |
| "feed cards not loading" | `src/screens/feeds/FeedsScreenHOC` |
| "product page blank" | `src/screens/product/ProductDisplay` |
| "cart not syncing with chat" | `src/screens/chat/components/CartChatSync` |
| "address sheet not refreshing" | `src/screens/product/addressbottomsheet/AddressBottomSheet` |
| "style drops upload stuck" | `src/screens/styledrops/StyleDropImageUploadScreen` |
| "virtual try-on not starting" | `src/screens/vton/VtonBottomSheet` / `src/screens/socialFinds/vton/` |
| "order page empty" | `src/screens/order/OrderConfirmedScreen` / `MyOrderScreenHOC` |
| "profile not saving" | `src/screens/user/EditProfileScreen` |
| "payment screen crash" | `src/screens/payment/PaymentScreen` |
| "notification permission not prompting" | `src/screens/notificationbottomsheet/PermissionScreenBottomSheet` |
| "conversation history missing" | `src/screens/chat/ConversationHistory` |
| "unseen feature not working" | `src/screens/onboarding/unseen/` |
| "waitlist screen not navigating" | `src/screens/waitlist/WaitlistScreen` |
| "deep link not opening correct screen" | `src/deeplink/deeplink.utils` + `src/navigation/routes.ts` |
| "redux state stale after logout" | `src/store/resetStore.ts` + `authSlice` |
| "OTA update not applying" | `src/services/otaUpdater/` |

---

## Screens

### Auth
| Screen | Path |
|---|---|
| `MobileNumberScreenHOC` | `screens/auth/` |
| `OtpVerificationScreenHOC` | `screens/auth/` |
| `LoginSuccessScreen` | `screens/auth/` |
| `OnboardingBottomSheet` | `screens/auth/` |
| `CustomerContactBottomSheet` | `screens/auth/` |
| `InformationBottomSheet` | `screens/auth/` |
| `PermissionScreen` | `screens/auth/permission/` |
| `OnboardingScreenHOC` | `screens/auth/tutorial/` |

### Home
| Screen | Path |
|---|---|
| `HomeScreen` | `screens/home/` |
| `HomeHolderScreen` | `screens/home/` |
| `ConversationsScreen` | `screens/home/` |
| `SearchScreen` | `screens/home/` |
| `WelcomeScreen` | `screens/home/` |
| `SplashScreen` | `screens/home/` |

### Chat
| Screen | Path |
|---|---|
| `ChatScreen` | `screens/chat/` |
| `DefaultChatScreen` | `screens/chat/` |
| `MinutesChatScreen` | `screens/chat/` |
| `ShopAlertsScreen` | `screens/chat/` |
| `SocialFindsScreen` | `screens/chat/` |
| `ConversationHistory` | `screens/chat/` |
| `ChatProductsBottomSheet` | `screens/chat/` |
| `ChatVariantBottomSheet` | `screens/chat/` |

### Feeds
| Screen | Path |
|---|---|
| `FeedsScreenHOC` | `screens/feeds/` |
| `FeedCardHoc` | `screens/feeds/components/` |
| `GetToKnowYouCardHoc` | `screens/feeds/components/gettoknowyou/` |

### Product
| Screen | Path |
|---|---|
| `ProductDisplay` | `screens/product/` |
| `ProductDisplayBottomSheet` | `screens/product/` |
| `ProductDisplayCardBottomSheet` | `screens/product/` |
| `KeySpecificationSheetScreen` | `screens/product/` |
| `PriceTrendBottomSheet` | `screens/product/` |
| `MinimumOrderPriceBottomSheet` | `screens/product/` |
| `ServiceCenterBottomSheet` | `screens/product/` |
| `SizeChartBottomSheet` | `screens/product/` |
| `AddressBottomSheet` | `screens/product/addressbottomsheet/` |
| `MinutesAddressBottomSheet` | `screens/product/addressbottomsheet/` |
| `AllMediaScreen` | `screens/product/allmediascreen/` |

### StyleDrops
| Screen | Path |
|---|---|
| `SDOnboardingScreen` | `screens/styledrops/` |
| `StyleDropImageUploadScreen` | `screens/styledrops/` |
| `SDAvatarGeneratingScreen` | `screens/styledrops/` |
| `SDImageUploadPreviewScreen` | `screens/styledrops/` |
| `SDSelfieReviewScreen` | `screens/styledrops/` |
| `SDTryOnGeneratedScreen` | `screens/styledrops/` |
| `SDCatalogScreen` | `screens/styledrops/` |
| `SDSavedLookScreen` | `screens/styledrops/` |
| `StyleDropsLookDetailScreenHOC` | `screens/styledrops/` |
| `SDErrorScreenHOC` | `screens/styledrops/` |
| `SDPrivacyInformationBottomSheet` | `screens/styledrops/` |
| `StyleDropsSupportScreenHOC` | `screens/` (HOC) |
| `StyledropReuploadHOC` | `screens/styledropreuploadbottomsheet/` |

### VTON (Virtual Try-On)
| Screen | Path |
|---|---|
| `VtonBottomSheet` | `screens/vton/` |
| `VtonTryOnResultBottomSheet` | `screens/vton/` |
| `VtonOutOfTriesBottomSheet` | `screens/vton/` |
| `VirtualTryOnStatusBanner` | `screens/socialFinds/vton/` |
| `VirtualTryOnStatusBannerOverlay` | `screens/socialFinds/vton/` |
| `VtonImageOverlayHoc` | `screens/socialFinds/vton/` |
| `DeleteVtonDataBottomSheetScreen` | `screens/deletedata/` |

### Onboarding
| Screen | Path |
|---|---|
| `OnboardingQuestionnareConatiner` | `screens/onboarding/` |
| `UserNameHOC` | `screens/onboarding/` |
| `IOSConsentScreenHOC` | `screens/onboarding/` |
| `PrivacyPolicyAndConditionsScreen` | `screens/onboarding/` |
| `UnseenScreen` | `screens/onboarding/unseen/` |
| `UnseenIntroScreen` | `screens/onboarding/unseen/` |
| `UnseenCameraScreen` | `screens/onboarding/unseen/` |
| `UnseenUploadScreen` | `screens/onboarding/unseen/` |
| `UnseenLoaderScreen` | `screens/onboarding/unseen/` |
| `UnseenErrorScreen` | `screens/onboarding/unseen/` |

### User / Profile
| Screen | Path |
|---|---|
| `ProfileScreen` | `screens/user/` |
| `EditProfileScreen` | `screens/user/` |
| `UserMemoriesScreen` | `screens/profile/memoriessettings/` |
| `PermissionSettingsScreen` | `screens/profile/permissionsettings/` |

### Cart & Payment
| Screen | Path |
|---|---|
| `CheckoutScreen` | `screens/cart/` |
| `OrderPageNavigationBottomSheet` | `screens/cart/` |
| `PaymentScreen` | `screens/payment/` |
| `OffersBottomSheet` | `screens/offersbottomsheet/` |
| `OfferTnCDetailsScreen` | `screens/offerdetails/` |

### Orders
| Screen | Path |
|---|---|
| `MyOrderScreenHOC` | `screens/` (HOC) |
| `NoOrderScreenHoc` | `screens/` (HOC) |
| `OrderConfirmedScreen` | `screens/order/` |
| `ReviewScreen` | `screens/review/` |

### Misc Screens
| Screen | Path |
|---|---|
| `SupportScreen` | `screens/support/` |
| `InAppBrowser` | `screens/inAppBrowser/` |
| `MediaHandlerScreen` | `screens/mediaHandler/` |
| `WaitlistScreen` | `screens/waitlist/` |
| `UpdateScreen` / `UpdateHolderScreen` | `screens/updateApplication/` |
| `PermissionScreenBottomSheet` | `screens/notificationbottomsheet/` |
| `DeleteAccountScreenHoc` | `screens/` (HOC) |
| `ShareFeedbackFormScreenHoc` | `screens/` (HOC) |
| `PrivacyCenterScreenHoc` | `screens/` (HOC) |
| `TPLScreenHOC` | `screens/` (HOC) |

---

## Components (`src/components/`)

| Component | Purpose |
|---|---|
| `AppBottomSheet` / `CustomAppBottomSheet` | Base bottom sheet wrappers |
| `CustomKeyboardAvoidingView` | Keyboard-safe layout wrapper |
| `FadeInWrapper` | Fade-in animation wrapper |
| `VoiceWaveform` | Speech-to-text waveform UI |
| `TextInputBar` | App-level text input |
| `ButtonWithLinearGradient` | Gradient CTA button |
| `GlobalSnackbar` | App-wide snackbar notifications |
| `HeaderToast` | Top-of-screen toast messages |

---

## State Management (`src/store/` — 17 Redux slices)

| Slice | Owns |
|---|---|
| `authSlice` | Login state, tokens |
| `cartSlice` | Cart items, quantities |
| `chatSlice` | Chat messages, streaming state |
| `feedSlice` | Feed cards data |
| `homeSlice` | Home screen data |
| `productSlice` | Product detail data |
| `productQuantitySlice` | Per-product quantities |
| `styledropsSlice` | Style drops flow state |
| `vtonFrameSlice` | VTON generation state |
| `moodBoardSlice` | Mood board data |
| `onboardingSlice` | Onboarding progress |
| `ordersSlice` | Orders list |
| `navigationSlice` | Navigation state |
| `contextSlice` | App context/session |
| `uiSlice` | UI flags (modals, loaders) |
| `unseenSlice` | Unseen feature state |
| `appConfigSlice` | Remote app config |

---

## API Handlers (`src/api/handlers/`)

| Handler | Feature |
|---|---|
| `auth.ts` | Login, OTP, session |
| `cartApi.ts` | Cart operations |
| `chatStream.ts` | SSE streaming chat |
| `feedsApi.ts` | Feed card fetching |
| `productApi.ts` | Product details |
| `styledrops.ts` | Style drops API |
| `vtonApi.ts` | Virtual try-on API |
| `socialFindsApi.ts` | Social finds feed |
| `paymentApi.ts` | Payment flows |
| `myOrder.ts` | Order history |
| `conversationHistoryApi.ts` | Chat history |
| `homeApi.ts` | Home screen data |
| `moodBoardApi.ts` | Mood board data |
| `unseenApi.ts` | Unseen feature |
| `waitListApi.ts` | Waitlist |
| `neoBlobApi.ts` | Neo blob storage |
| `checkoutApi.ts` | Checkout flow |
| `user.ts` | Profile/user data |
| `otaApi.ts` | OTA updates |

---

## Navigation (`src/navigation/`)

| File | Purpose |
|---|---|
| `routes.ts` | All route name definitions |
| `navigation.d.ts` | TypeScript route param types |
| `screenHeaderRegistry.ts` | Per-screen header config |
| `AppNavContainer` | Root navigation container |
| `HomeNavContainer` | Home tab navigation |
| `TabBar` | Bottom tab bar |
| `AppErrorBoundary` | Navigation-level error boundary |

---

## Key Hooks (`src/hooks/`)

| Hook | Purpose |
|---|---|
| `useHomeScreen` | Home screen data & logic |
| `useLogout` | Logout + store reset |
| `useDeeplinkManager` | Deep link handling |
| `usePermission` | Device permission requests |
| `useSpeechToText` | Mic input handling |
| `useGlobalSnackbar` | Trigger snackbar |
| `useHeaderToast` | Trigger header toast |
| `useRemoteAppConfig` | Feature flags / remote config |
| `useUnseenEligibilityCheck` | Unseen feature gate |
| `useNeoBlob` | Blob storage access |

---

## Native Modules (`src/nativemodules/`)

| Module | Purpose |
|---|---|
| `NativePaymentsController` | Native payment SDK |
| `NativeSpeechToTextController` | On-device STT |
| `NativeOtpVerifyController` | OTP autofill |
| `NativeFdpEventController` | Analytics events |
| `NativeChatColdStorageController` | Persistent chat storage |
| `NativeJankTrackerController` | Frame drop tracking |
| `NativeOtaController` | OTA update trigger |
| `NativeColdStartController` | Cold start metrics |
| `NativeAppConfigsController` | Native app config |
| `NativePhoneHintController` | Phone number hint |
