# SLAP Knowledge Document

Extracted from the SLAP-2026 Figma design file. This document gives the media
sub-agent enough domain context to interpret bug-report attachments
(screenshots, screen recordings) in **SLAP-specific language** instead of
generic e-commerce vocabulary.

When in doubt about an image, refer to the labeled screens under
`slap_context/reference_screens/` for the canonical look of each surface.

---

## 1. What SLAP is

**SLAP** ("Shop Like A Pro") is Flipkart's conversational, AI-powered shopping
app. Instead of browsing a catalog, the user **chats** with an AI assistant
that asks clarifying questions, surfaces curated product picks, lets them try
items on virtually, tracks prices, and learns their style preferences.

Distinctive product pillars visible in the design:

| Pillar | What it does |
|---|---|
| **Conversational chat** | The home interaction. User asks questions in natural language; SLAP responds with curated recommendations, follow-up questions, and emoji-rich, friendly summaries (TL;DR style). |
| **Virtual Try-On (VTO/VTON)** | "Try on me" / "Try-on fits" — user uploads a photo and SLAP drapes new clothes / fashion items on them. |
| **Looks & Style Drops** | Outfit-level recommendations: "Buy the Top in this look", "Today's Style Drop", "Insta Finds", "Style Arena", "Decoded Looks". |
| **Price intelligence** | Real-time price tracking — "Price history", "Price trends", "Market Comparison" (vs Amazon/Myntra/Chroma/Zara), "Price is currently high/low/typical", price-drop alerts. |
| **Memories & preferences** | Persistent personalization — onboarding preference quiz, conversation memory, "Suggestions based on your recent conversations", privacy-preserving profile. |
| **Buy with confidence** | Trust/specs panel on product pages — "Why you should get this", "Stand out features", "Key Specifications", "What to watch out for", "Know before you go". |

---

## 2. SLAP vocabulary (recognize these on screen)

When the media sub-agent sees any of these strings in a screenshot, it
should treat them as SLAP-specific UI elements, not generic terms.

### Chat interface
- **"Ask SLAP"** / **"Ask Anything"** / **"Ask about this"** — the AI input prompt
- **"Ask more"** / **"Follow up questions"** — chat continuation
- **"Pull to Chat"** — gesture / entry point
- **"TL;DR:"** — AI-generated summary tag
- **"Hi Rishi 👋"** / **"Hi <name>,"** — personalized greeting (means user is logged in and the persona has loaded)
- **"How can I help you Today?"** / **"Let's find you something great today"** — chat greeting / landing copy
- **"🌟 Top Picks for You:"** — curated AI recommendations heading
- **"Maybe Later"** / **"Not sure"** — conversational deflection options
- Emoji-heavy responses (👉 🌟 ❄️ 💡 💸 🌡️ 🧠 🤷‍♂️ ✏️) are normal — not a rendering bug

### Product cards & detail pages
- **"View N reviews"** / **"90% Positive"** — review summary widget
- **"Buy with confidence"** — trust panel
- **"Why you should get this"** / **"Stand out features"** — product strengths
- **"What to watch out for"** — balanced concerns
- **"Know before you go"** — pre-purchase hints
- **"Key Specifications"** / **"View all specifications"** — spec table
- **"Top Seller in Fashion"** / **"Most viewed on Flipkart"** / **"Rated product of the year"** — badges
- **"FREE | Delivery by T"** / **"Free delivery"** / **"Fulfilled by Flipkart"** — delivery info
- **"[Product Tile]"** — placeholder card seen during loading
- **"Add to cart"** / **"Buy now"** / **"Buy at ₹X with offers"** — CTAs
- **"Find dupes"** — find similar alternatives feature
- **"Compare"** — multi-product compare

### Price / market intelligence
- **"Price history"** / **"Price trends"** / **"See Trend"** — historical pricing
- **"Price is currently high"** / **"low"** / **"typical"** — current-vs-history flag
- **"6 month low"** / **"6 month high"** / **"30 Day"** — price ranges
- **"↓ N%"** / **"↓ ₹N Drop"** — price drop indicators
- **"Market Comparison"** + brand names (Amazon, Myntra, Chroma, Zara) + **"N% cheaper"** — competitor compare
- **"MRP"** / **"Best Price"** / **"FSP"** / **"typical price"** / **"usual price"** — price labels
- **"Alert set for the price below"** / **"Edit price alert"** — price tracking

### Try-on / VTON
- **"Try on me"** / **"Try-on fits"** — entry CTA
- **"Try-ons, generated"** — output screen showing dressed photo
- **"Out of try on"** — exit/cancel state
- **"Your photos are never shared and only used for draping new looks on you"** — privacy disclaimer
- **"Looks detail page"** — full outfit view
- **"Buy the Top in this look"** — sub-item purchase from a look
- **"Decoded Looks"** / **"Socialfinds"** — discovery feature

### Personalization & onboarding
- **"Help us know you better"** — onboarding header
- **"Packing for a coastal getaway! What is the first thing in your bag?"** — preference quiz question
- **"Your preferences are never shared and only used for personalising SLAP experience for you"** — privacy disclaimer
- **"Suggestions based on your recent conversations"** — context-aware recs
- **"No memories saved here"** / **"Delete memory"** — memory/personalization controls
- **"Just Getting Started?"** — onboarding nudge

### Auth / login
- **"Hey! What's your number?"** / **"Use the number linked to your Flipkart account"** — phone login prompt
- **"+91 …"** — Indian phone OTP flow
- **"I didn't receive a code"** / **"Resend"** — OTP recovery
- **"Be assured, we won't spam you"** — notification opt-in disclaimer

### Notifications & nudges
- **"Notification Nudge"** — bottomsheet asking to enable push
- **"Enable notifications"** — system prompt wrapper
- **"Setting alert"** — alert configuration
- **"Email copied"** — clipboard toast
- **"Add items worth ₹N"** — minimum-cart threshold nudge

### Discovery sections
- **"Top Picks"** / **"Inspiration"** / **"Today's Style drop"** / **"Insta Finds"** / **"Style Arena"** — landing-feed sections
- **"Home decor ideas"** / **"Kitchen essentials"** / **"Skin Care"** — category chips
- **"View all"** / **"View more"** — pagination

---

## 3. Screen catalog (with reference image filenames)

Each screen below has a labeled PNG under `slap_context/reference_screens/`.
Use these as visual anchors when interpreting bug screenshots.

| Reference file | Screen | What it is / what bugs land here |
|---|---|---|
| `log_in_with_phone.png` | **Phone login / OTP** | Auth bugs — "Failed to verify" errors, OTP not received, +91 country code issues. |
| `home_page.png` | **Home / landing** | Greeting, chat entry, Top Picks, Style Drops. General entry-point bugs, persona-not-loaded ("Hi ,"). |
| `chat_view.png` | **Chat View (Query Input Max Height)** | The main chat surface. "Thinking…" stuck, wrong AI response, follow-up missing. |
| `da_query_results.png` | **Query Results** | AI-generated product recommendations after a chat query. Wrong products, empty results, broken summary. |
| `pdp.png` | **Product Detail Page (PDP)** | Single-product view with reviews / specs / price / "Buy with confidence" panel. Price discrepancy, missing reviews, broken images. |
| `cart.png` | **Cart (collapsed)** | Mini cart / cart icon view. |
| `cart_full_view.png` | **Cart (full)** | Full cart with items, prices, "Add items worth ₹N" nudges, "Proceed to Pay" entry. |
| `my_orders.png` | **My orders** | Order history / status. |
| `my_accounts.png` | **My accounts** | Profile / preferences / settings entry. |
| `feed.png` | **Feed** | Style-drop / discovery feed. |
| `looks_detail_page.png` | **Looks detail page** | Outfit-level view; "Buy the Top in this look". |
| `try_ons_generated.png` | **Try-ons, generated** | VTON output — user dressed in selected garment. Wrong gender persona, broken drape, VTO SDK ANRs land here. |
| `price_history.png` | **Price history / trends** | Historical price graph + Market Comparison. Wrong values, missing graph. |
| `offers.png` | **Offers** | Active offers / coupons. |
| `notification_nudge.png` | **Notification nudge bottomsheet** | Push-notification opt-in flow. |
| `feedback.png` | **Feedback** | User feedback form. |

### Other screens identified in the file (no reference PNG yet — can be added later)

- Onboarding / persona setup (preference quiz)
- T&C
- Need help
- Privacy centre
- Delete memory / No memories saved here
- Edit price alert / Set alert approach 1 / 2
- Single review / Ratings / Scrolled review view
- Address / Address present / Edit name
- Compare market price
- Nearby Support (Brand Authorised / Doorstep)
- Vibes Player Experience
- Gift card
- Switch tab states
- MEL PP (My Engaged Looks Product Page — fashion-specific PDP variant)
- "Lower than usual" / "Higher than usual" / "Highwer than usual" bottomsheets (price-vs-norm flags)
- "Trigger type 1/3/4/5/7" — internal naming for alert / nudge triggers

---

## 4. Component → team routing (recap for the media agent)

When the media sub-agent identifies *which* SLAP screen is in a screenshot,
it implicitly routes the bug to a team. The mapping (same as the rest of the
triage pipeline):

| Screen seen in image | Likely team |
|---|---|
| Chat View, Query Results, Cart, Checkout, PDP, Login, Home, Offers, My Accounts, My Orders, Need Help | **BE_Flippi** (Backend) |
| Try-ons, Looks detail, Decoded Looks, Socialfinds, Style Drops, VTON onboarding | **BE_Labs** (Backend-Labs) |
| Price history, Price trends, Market Comparison, Review summaries, 90% Positive, NPS-related | **DS** |
| Login screen flash, image-loading bugs, React Native rendering issues, cold-start, layout breaks | **UI** |
| Native AR overlay, VTO SDK ANRs, "Out of try on" crashes, drishyamukh-related | **Immersive** |
| Anything that doesn't match the above clearly | **bugs** (manual routing) |

---

## 5. Visual cues that flip the triage decision

These are heuristics the media sub-agent should apply when reading any
screenshot. They convert visual signals into triage-relevant claims.

| Visual cue in screenshot | What it implies |
|---|---|
| App icon / status bar visible on a screenshot (not just the SLAP screen) | Real device capture (not designer mock); platform = whatever the status bar shows |
| **"Hi ,"** with no name | Persona / profile failed to load — Backend regression |
| **"[Product Tile]"** placeholder card visible | Loading state stuck — likely backend timeout or empty result set |
| Sources widget / "Top Picks" heading present but body empty | Retrieval pipeline returned no products — DS / BE_Flippi |
| Crash dialog / system overlay (Android "App keeps stopping", iOS crash sheet) | P0 — crash detected |
| Razorpay / payment-sheet error code on screen | P0 if checkout-blocking |
| "Thinking…" indicator with no follow-up message | Chat backend stuck — BE_Flippi (chat AI) |
| VTON image shows wrong gender persona on user | P1 — personalization wrong (BE_Labs) |
| Price field shows currency symbol with no number | P1 — price service failure |
| Image broken icon / blank product card image | P2 — UI / CDN issue |
| Login screen flashing or "Failed to verify" visible | P1 / P0 depending on scope (Auth — BE_Flippi) |
| Screen shows different content than the email text describes | **Contradiction signal** — note in the triage output so the human can resolve |

---

## 6. What the media sub-agent should output for each image

```json
{
  "image_id":          "screenshot1.png",
  "screen":            "PDP" | "Cart" | "Chat View" | "Try-ons, generated" | ...,
  "state":             "normal" | "loading" | "error" | "empty",
  "visible_text":      ["literal strings extracted from the image"],
  "error_indicators":  ["any error message text or visual error states"],
  "device_hints":      {"platform": "Android" | "iOS" | "unknown",
                        "os_visible": "..." | null,
                        "app_version_visible": "..." | null},
  "ui_anomalies":      ["specific things that look wrong"],
  "triage_signals": {
    "likely_component":         "Backend" | "Backend-Labs" | "DS" | "UI" | "immersive" | "bugs",
    "severity_hint":            "P0" | "P1" | "P2" | "P3",
    "contradicts_email_claim":  "string or null"
  },
  "one_line_summary":  "Used as the description-prefix folded into the rest of the triage pipeline"
}
```

The `one_line_summary` is the most important field — it gets folded into the
bug's text description so the parser/similarity/scoring stages have the
visual finding without needing to handle images themselves.

---

## 7. Honest limitations of this knowledge

- **Designs ≠ shipped app.** These references are Figma designs from the
  SLAP-2026 file. The shipped app may differ visually due to implementation
  drift, OS-level rendering, dark mode, A/B variants, etc.
- **Happy paths over-represented.** Designers focus on success states; many
  real-world error/empty/loading states are absent from this reference set.
  Real-app screenshots of error states will need to be added over time.
- **Brand / product names are placeholders.** Strings like "LG 1.5 Ton" or
  "Logitech MX Master 4" are mock content. The shipped app shows whatever
  the catalog returns.
- **No video / audio in this knowledge document.** This is v1 — text + images
  only. Audio transcription + video keyframe extraction will be added in
  later iterations of the media sub-agent.

---

_Source: SLAP-2026 Figma file (extracted 2026-06-16). 393 frames across the
"Work area" canvas, 198 unique screen names, 1,117 distinct text strings._
