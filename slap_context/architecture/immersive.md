# Immersive team — architecture skill

**Team:** Immersive
**Jira component:** `immersive` (id 14387)
**Stack:** Native iOS (Objective-C / Swift) + native Android (Java / Kotlin) + AR SDK

## Repos owned

> No SLAP-specific Immersive repo is listed in the current 11-repo manifest. Native VTO SDK / drishyamukh-core code lives in a separate Flipkart-wide native SDK repo (out of the 11 in scope here).

If a bug routes to Immersive, the codebase to inspect is the Flipkart native VTO SDK — **not** one of the manifest's 11 repos.

## Surface area Immersive owns

- **Native AR rendering layer** (objective-C / native Java / AR SDK)
- **VTO SDK** — the native portion of virtual try-on (the model service is FaceNet, in BE_Labs; the *AR rendering* is Immersive)
- **drishyamukh / drishyamukh-core** — native AR rendering primitives
- **ANRs in native code** — Application Not Responding crashes that originate in native (non-RN) code
- **Native crashes in the AR rendering path** — distinct from React Native crashes (those go to UI)

## What is NOT Immersive

- React Native crashes (`[RN]`, `[iOS]`, `[Android]` titles where the stack is RN) — UI
- VTON *model* outputs being wrong (e.g. wrong gender persona) — Backend-Labs (FaceNet)
- VTON UI flow (open, tap try-on, see result) — UI for the screen / interaction
- Any other ANR not in AR / native SDK code — depends on which service crashed

## Distinguishing Immersive from UI for VTON-related bugs

Both teams touch VTON. The split:

| Symptom | Likely owner |
|---|---|
| "AR camera crashes when I tap Try On" / ANR in native | Immersive |
| "[iOS] VTO screen layout broken" / "[Android] Try On button overlap" | UI |
| "VTON shows male model when I'm female" (model output wrong) | Backend-Labs (FaceNet) |
| "drishyamukh-core crashes" | Immersive |

## Note on training data

In the current 564-bug labelled corpus, Immersive has zero examples — the LogReg classifier won't predict Immersive at all. When the bug genuinely is Immersive (native AR / ANR), expect the classifier to route to UI or "bugs" and rely on human override.
