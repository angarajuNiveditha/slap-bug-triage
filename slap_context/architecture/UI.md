# UI — Team, Modules & Routing Guide

**Team:** UI
**Manager:** Yatin Grover *(RN + Native both report to Yatin)*
**Jira component:** `UI` (id `14383`)
**Stack:** React Native (Android + iOS)
**Repos:**
| Repo | Role | Prod branch |
|---|---|---|
| `spaghetti` | Primary SLAP mobile app (RN) — hosts most user-facing screens, navigation, client-side state | `develop` |
| `mozzarella` | Shared RN component / design-system library | `develop` |

For detailed screen and component inventories see `slap_context/architecture/repos/spaghetti.md` and `mozzarella.md` — those are hand-authored and describe individual screen files, common component patterns, and routing signals at the file level.

UI owns everything the user *sees* and *touches* on the SLAP app: the RN screens, the native modules (iOS Swift/ObjC, Android Kotlin/Java), the design system, and the client-side state that backs them.

---

## Common Bug Routing Signals

> Symptoms extracted from real UI-labelled bugs in the 564-bug FLIPPI corpus. Match on the failure being about *rendering / interaction / native platform*, not about data.

| Symptom / phrase | Owning repo / area |
|---|---|
| `[iOS]`, `[Android]`, `[Native]`, `[RN]` prefix anywhere in the title | **Always UI**, regardless of feature area (Styledrops, VTON, chat) |
| "iOS CocoaPods install fails" / "objectVersion 70 on Xcode 16" | `spaghetti/ios/` (native build) |
| "Adding Cold storage module to pbxproj" | `spaghetti/ios/` (Xcode config) |
| "Add native LocationModule for lat/long" | `spaghetti/ios/` (native module bridge) |
| "iOS: Login screen flashes twice on cold start" | `spaghetti/screens/` (RN + native init race) |
| "TextInputBar is breaking on clicking ask more" | `mozzarella/TextInputBar` |
| "AnimatedInputBar", "Chat Screen input bar styling" | `mozzarella` chat-input components |
| "Swipe down gesture not dismissing feeds" | `spaghetti` navigation / gesture handler |
| "Native System Gesture Conflict" | `spaghetti/ios` or `spaghetti/android` native |
| "Hamburger Menu — Incorrect labels" | `spaghetti/screens/HamburgerMenu` |
| "OTP input field lacks forced sequencing" | `mozzarella` OTP input |
| "Onboarding flow skipped after app reinstall or data clear" | `spaghetti/screens/OnboardingScreen` |
| "Missing Visual Progress Indicators (step icons)" | `spaghetti/screens/Onboarding` |
| "Frozen Animation on Progress Page" | `spaghetti` animation layer |
| "Inaccurate Crop Tool UI" | `spaghetti` VTON upload flow |
| "Misleading User Cancelled Toast" | `spaghetti` toast layer |
| "Inconsistent iconography on Suggested Chat cards" | `mozzarella` chat-card components |
| "Support Bottom Sheet: email mismatch" | `spaghetti/screens/SupportBottomSheet` |
| "Login page elements not properly spaced" / "Excessive white space" | `spaghetti/screens/Login` (layout) |
| "Text and buttons hidden / overlapping" | `spaghetti` layout bugs |
| "Keyboard should open by default for new chat" | `spaghetti/screens/Chat` (keyboard behavior) |
| "Removed ConversationId handling for JOURNEY_CONTINUE" | `spaghetti` chat state |
| "User not getting logged out for invalid RT" | `spaghetti` auth flow (client-side) |
| "App configs not reflecting globally (`[Native][Android]`)" | `spaghetti/android` native config |
| "[RN] Styledrops liked drop empty state" | `spaghetti/screens/StyleDrops` |
| "[RN] Swipe gesture for accounts and Chat history" | `spaghetti` gesture handling |
| "[RN] Onboarding Page Design Changes" | `spaghetti/screens/Onboarding` |
| "[RN] The whole card in My Order Page should be tappable" | `spaghetti/screens/MyOrders` |
| "Restricted Input Touch Target (Name field narrow)" | `mozzarella` form input |
| "Failed to submit profile for new user" *(client-side flow)* | `spaghetti/screens/ProfileSetup` |
| "SLAP throwing error saying User Cancelled" | `spaghetti` toast + navigation |

---

## Boundary rules

### UI ↔ Backend

> **If the failure is rendering / touch / gesture / animation / layout / native build / client-state → UI.**
> **If the failure is "the API returned wrong data" / 5xx / timeout / auth denied → Backend.**

Same feature can produce both kinds of bugs:
- "Checkout button doesn't respond to tap" → **UI** (touch handler in `spaghetti/screens/Checkout`)
- "Checkout API 500" → **Backend** (`edison/checkout/CheckoutService`)

### UI ↔ Backend-Labs (the title-prefix rule)

Any bug on a BE-Labs feature (Styledrops, VTON, Social Finds, MoodBoard) that's title-prefixed `[iOS]`, `[Android]`, `[RN]`, or `[Native]` is **UI**, not BE-Labs. The feature backend can be BE-Labs's problem while the RN screen displaying it is UI's problem.

Examples:
- `[iOS] Styledrops_App is crashing after 5th drop` → **UI** (native crash on Styledrops screen)
- `Styledrops backend generating wrong products` → **BE-Labs**
- `[RN] Styledrops liked drop empty state` → **UI**

### UI ↔ DS

Content presentation is a shared boundary:
- "Text cut off in the paragraph" — if the text is rendered fine but the *content* is bad → DS. If the *rendering* is clipping words that should fit → UI.
- Usually DS if the bug talks about content, UI if the bug talks about rendering.

### UI ↔ Immersive

3D SDK / AR-VR / Beauty VTO / Camera Filters ownership sits with **Immersive** (also under Yatin), not UI. Bug clues that route to Immersive:
- "3D video not playing", "AR overlay misaligned", "VTO SDK crash", "Beauty filter mask wrong"

---

## Sub-team ownership (from Yatin's org chart)

Yatin manages the UI team with 2 SDE-3s:

| Engineer | Sub-area |
|---|---|
| **Varun** | React Native — the JS/TS layer, RN screens, Metro bundler, RN-side navigation |
| **Hyzam** | Native — Android (Kotlin/Java), iOS (Swift/Objective-C), native modules, native build issues (CocoaPods / Xcode / Gradle), native gesture handlers |

**Routing between the two**:
- Bug is in `spaghetti/src/` (TypeScript, .tsx, .ts) → **Varun**
- Bug is in `spaghetti/ios/` (.swift, .m, .mm, Podfile, pbxproj) → **Hyzam**
- Bug is in `spaghetti/android/` (.kt, .java, gradle) → **Hyzam**
- Bug is a native-JS-bridge issue (RN module failing) → **Hyzam** (native side) usually
- Bug says `[iOS]` or `[Android]` or `[Native]` → **Hyzam**
- Bug says `[RN]` or is unspecified → **Varun**

Historical assignees in the corpus (from `data/embedding_index_team_roster.json`): Kalpana lnm, Amareshwar Walia, Samiksha Khandelwal, Latika Aggarwal, Varun Sharma, and others with ≥2 bugs. These are current + past UI contributors; new assignments should default to Varun / Hyzam per the org chart.

---

## What lives WHERE (from the per-repo files)

- **`spaghetti`** — screens (`OnboardingScreen`, `HomeScreen`, `ChatScreen`, `CartScreen`, `Checkout*`, `VTOn*`, `SDCatalogScreen`, `MoodBoard`, `SocialFinds*`, `SupportBottomSheet`, etc.). Native iOS folder (`ios/`), native Android folder (`android/`).
- **`mozzarella`** — shared components (`TextInputBar`, `AnimatedInputBar`, `CartSummaryBar`, `FashionProductCardCarousel`, `AllUserReviewBottomSheet`, `NotificationScreenBottomSheet`, `SizeChartContent`, `SwatchSelectorScreen`, `PermissionScreen`, `OnboardingScreen`, and many more). Look at `mozzarella.md` for the full 284-line component inventory.

**Rule of thumb**: bugs about specific *screens* → `spaghetti`; bugs about *reusable components* (input bars, carousels, bottomsheets, form widgets, animations) → `mozzarella`.

---

## Client-side state (relevant to "data bleed across users" bugs)

User profile state in SLAP is persisted via **MMKV** on device. The auth slice (in `mozzarella/src/store/resetStore.ts` + `authSlice`) is responsible for clearing it on logout.

Known failure mode: incomplete reset of the profile sub-store on logout → next user logs in and sees previous user's address. **This is a UI bug**, not Backend, when the cache is client-side (i.e. the bug reproduces after logout→login on the same device but a fresh install fixes it, and network logs show the server returning the *right* data).

Contrast with the Backend server-side cache bug: the bug reproduces from a fresh install too, and the server API is returning the wrong data. See `Backend.md`'s "Server-side caching" section for the disambiguation.

---

## What is NOT UI

- API returned wrong data / 5xx / timeout → **Backend**
- Chat AI relevance / ranking / prompt / content quality → **DS**
- VTON persona logic bug / Styledrops generation bug / Social Finds pipeline → **Backend-Labs** (unless the bug title has `[iOS]`, `[Android]`, `[RN]`, `[Native]` — then it's UI)
- 3D SDK / AR-VR / Beauty VTO / Camera Filters / 3D videos playback engine → **Immersive**
- Server-side cache bleed (session token, `GET /profile` returning wrong data) → **Backend**

---

## Common title-prefix conventions

- `[iOS]`, `[Android]`, `[Native]`, `[RN]` — always UI, no exceptions
- `SLAP ||` — often UI (visual polish and layout tickets)
- `[Native][Android]`, `[Native][iOS]` — Hyzam
- `[RN]` — Varun
- `iOS_`, `Android_` prefixes — same as `[iOS]` / `[Android]`
