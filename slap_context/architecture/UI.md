# UI team — architecture skill

**Team:** UI
**Jira component:** `UI` (id 14383)
**Stack:** React Native (Android + iOS)

## Repos owned

| Repo | Role | Prod branch | Freshness |
|---|---|---|---|
| `spaghetti` | Primary SLAP mobile app | `develop` | warm |
| `mozzarella` | Shared RN component / design-system library | `develop` | warm |

> Code at github.fkinternal.com/<org>/{spaghetti,mozzarella}

## Surface area UI owns

- All React Native screens: onboarding, homepage, chat, cart, checkout (UI shell), profile, settings
- Client-side state: Redux store, RN context providers, MMKV persistence layer
- Visual rendering — layout, spacing, alignment, overlap, image cropping
- Touch interaction — gestures, taps, swipes, scrolling, pull-to-refresh, "not clickable" complaints
- Form validation visuals: character limits, name input, OTP input UX
- Animation / flicker / frozen-state issues
- Native build issues: CocoaPods, Xcode, gradle, pbxproj, RN bridge crashes
- UI controls failing: "Show all reviews", "View more", "View all offers"
- "Not opening any" specific page (when no navigation event reaches the route)
- Onboarding-page DESIGN bugs (`[RN] Onboarding Page Design Changes`) — distinct from onboarding-FLOW logic which lives in Backend

## What is NOT UI

- Anything where the BUG is "wrong data returned" but the rendering is fine → Backend or DS
- VTON / Styledrops / Vibes / Cosmos surfaces' *underlying feature* bugs → Backend-Labs
  - But platform-prefixed (`[iOS]`, `[Android]`, `[RN]`) visual/touch bugs on a BE_Labs surface ARE UI
- Recommendation quality / ranking — DS

## Client-side persistence (relevant to cache / auth-bleed bugs)

User profile state in SLAP is persisted via **MMKV**. The auth slice owns clearing it on logout (see `mozzarella/src/store/resetStore.ts` + `authSlice`).

**Known failure mode:** incomplete reset of the profile sub-store on logout → next user logs in and sees previous user's address. *This is a UI bug*, not Backend, when the cache is client-side.

If a bug looks like a cache/auth-bleed and the description mentions logout / login flow / addresses showing across accounts, this team is the likely owner unless the bug explicitly mentions a server-side cache, session token, or backend service name.

## Title-prefix heuristic

Bugs filed with titles prefixed `[iOS]`, `[Android]`, `[RN]`, `[Native]`, `iOS_`, `Android_` are virtually always UI, even when the surface they're filed against (Styledrops, VTON, Vibes) belongs to a different team. UI owns the React Native rendering layer for all those surfaces.
