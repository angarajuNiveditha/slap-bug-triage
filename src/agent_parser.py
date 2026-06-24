"""
agent_parser.py — Rule-based bug report parser (no API key required).

Replaces src/parser.py. Parsing logic encodes the same structured
extraction Claude would perform, implemented as deterministic regex
and heuristic rules over the email format used by SLAP bug reporters.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class BugReport:
    title: str
    description: str
    steps_to_reproduce: list
    expected_result: str
    actual_result: str
    impact: str
    platform: str
    app_version: Optional[str]
    component_hint: str
    reproducibility: str
    reporter_email: Optional[str]
    reporter_name: Optional[str]
    raw_text: str


def parse_bug_report(raw_text: str) -> BugReport:
    text = raw_text.strip()
    lines = text.splitlines()

    reporter_email = _extract_email(text)
    reporter_name  = _extract_name(text, reporter_email)
    title          = _extract_title(text, lines)
    platform       = _extract_platform(text)
    app_version    = _extract_version(text)
    steps          = _extract_steps(text)
    expected       = _extract_labeled_field(text, ["Expected Result", "Expected"])
    actual         = _extract_labeled_field(text, ["Actual Result", "Actual"])
    impact         = _extract_labeled_field(text, ["Impact"])
    component      = _extract_component(text, title)
    repro          = _extract_reproducibility(text)
    description    = _build_description(text, lines)

    return BugReport(
        title=title,
        description=description,
        steps_to_reproduce=steps,
        expected_result=expected,
        actual_result=actual,
        impact=impact,
        platform=platform,
        app_version=app_version,
        component_hint=component,
        reproducibility=repro,
        reporter_email=reporter_email,
        reporter_name=reporter_name,
        raw_text=raw_text,
    )


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def _extract_email(text: str) -> Optional[str]:
    m = re.search(r'^From:\s*(.+)$', text, re.MULTILINE | re.IGNORECASE)
    if m:
        e = re.search(r'[\w.+\-]+@[\w.\-]+\.\w+', m.group(1))
        if e:
            return e.group()
    return None


def _extract_name(text: str, email: Optional[str]) -> Optional[str]:
    # "Regards,\nFirst Last" or "Thanks,\nFirst Last"
    for pat in [
        r'(?:Regards|Thanks|Cheers|Best)[,\s]*\n\s*([A-Z][a-z]+(?: [A-Z][a-z]+)+)',
        r'^-\s*([A-Z][a-z]+(?: [A-Z][a-z]+)+)\s*$',
    ]:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    if email:
        parts = re.split(r'[._]', email.split('@')[0])
        return ' '.join(p.capitalize() for p in parts if p)
    return None


def _extract_title(text: str, lines: list) -> str:
    for line in lines:
        if re.match(r'^Subject:', line, re.IGNORECASE):
            subj = re.sub(r'^Subject:\s*', '', line, flags=re.IGNORECASE).strip()
            subj = re.sub(r'^(Re|Fwd|FW):\s*', '', subj, flags=re.IGNORECASE).strip()
            subj = re.sub(r'\[(URGENT|SLAP|BUG|CRITICAL)\]\s*', '', subj, flags=re.IGNORECASE).strip()
            # Ensure a module prefix like [Chat]
            if not subj.startswith('['):
                prefix = _module_prefix(subj)
                subj = f"{prefix}: {subj}"
            return subj
    # Fall back to first body line
    for line in lines:
        if line.strip() and not re.match(r'^(From|To|Subject|Date):', line, re.IGNORECASE):
            return f"{_module_prefix(line)}: {line.strip()[:80]}"
    return '[SLAP]: Bug report'


def _module_prefix(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ['checkout', 'proceed to pay']):
        return '[Checkout]'
    if any(w in t for w in ['cart', 'add to cart']):
        return '[Cart]'
    if any(w in t for w in ['payment', 'pay']):
        return '[Payments]'
    if any(w in t for w in ['login', 'auth', 'verify', 'otp', 'credential']):
        return '[Auth]'
    if any(w in t for w in ['image', 'thumbnail', 'photo']):
        return '[UI/Images]'
    if any(w in t for w in ['search', 'recommend', 'suggest', 'product result']):
        return '[Search/AI]'
    if any(w in t for w in ['chat', 'ai', 'freeze', 'spinner', 'response']):
        return '[Chat/AI]'
    if any(w in t for w in ['dedup', 'duplicate', 'journey', 'feed']):
        return '[Feed/Search]'
    if any(w in t for w in ['secret', 'grayskull', 'edison', 'config']):
        return '[Backend/Infra]'
    return '[SLAP]'


def _extract_platform(text: str) -> str:
    m = re.search(r'Platform:\s*([\w,/ ]+)', text, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        if 'android' in val and ('ios' in val or 'web' in val):
            return 'Android, iOS, Web'
        if 'android' in val:
            return 'Android'
        if 'ios' in val:
            return 'iOS'
        if 'web' in val:
            return 'Web'

    has_android = bool(re.search(r'\bandroid\b', text, re.IGNORECASE))
    has_ios     = bool(re.search(r'\bios\b', text, re.IGNORECASE))
    has_web     = bool(re.search(r'\bweb\b', text, re.IGNORECASE))
    platforms   = [p for flag, p in [(has_android, 'Android'), (has_ios, 'iOS'), (has_web, 'Web')] if flag]

    if len(platforms) > 1:
        return ', '.join(platforms)
    if platforms:
        return platforms[0]
    return 'Unknown'


def _extract_version(text: str) -> Optional[str]:
    for pat in [
        r'(?:App\s*Version|Version):\s*v?(\d+\.\d+(?:\.\d+)?)',
        r'\bv(\d+\.\d+\.\d+)\b',
        r'\bversion\s+(\d+\.\d+(?:\.\d+)?)\b',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_steps(text: str) -> list:
    # Find the Steps section header
    m = re.search(
        r'(?:Steps to Reproduce|Steps|Reproduction Steps)[:\s]*\n([\s\S]+?)(?=\n\s*\n\s*[A-Z]|\Z)',
        text, re.IGNORECASE
    )
    if m:
        block = m.group(1)
        steps = []
        for line in block.splitlines():
            line = line.strip()
            if re.match(r'^(\d+[\.\)]|[-•*])\s+', line):
                clean = re.sub(r'^(\d+[\.\)]|[-•*])\s+', '', line).strip()
                if clean:
                    steps.append(clean)
            elif steps and not line:
                break
        if steps:
            return steps

    # Fallback: numbered lines anywhere in the text
    steps = []
    in_steps = False
    for line in text.splitlines():
        if re.search(r'steps?\s*(to\s*)?(reproduce|repro)', line, re.IGNORECASE):
            in_steps = True
            continue
        if in_steps:
            stripped = line.strip()
            if re.match(r'^\d+[\.\)]\s+', stripped):
                steps.append(re.sub(r'^\d+[\.\)]\s+', '', stripped))
            elif not stripped and steps:
                break
    return steps


def _extract_labeled_field(text: str, labels: list) -> str:
    for label in labels:
        pat = (
            rf'(?:^|\n)\**\s*{re.escape(label)}(?:\s+Result)?\s*[:\*]+\s*\**\n?'
            rf'([\s\S]+?)(?=\n\s*\n|\n\s*(?:Actual|Expected|Impact|Environment|Repro|Steps|Regards|Thanks|$))'
        )
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            content = re.sub(r'\*+', '', m.group(1)).strip()
            if content:
                return content
    return "Not provided."


def _extract_component(text: str, title: str) -> str:
    """
    Classify into one of the 6 FLIPPI team components.
    Returns the Jira component name (or 'bugs' when unclassifiable).

    Team → Jira component:
      Immersive  → immersive   (native AR, VTO SDK, ANRs)
      BE_Labs    → Backend-Labs (VTON, Feed ML, Social Finds, Review Synth, Machine Identity)
      DS         → DS           (NPS, model quality, product-page analytics, ranking)
      UI         → UI           (React Native, iOS/Android visual, login screen, cold start)
      BE_Flippi  → Backend      (chat AI, search, cart, checkout, price, session, auth, infra)
      unclassified → bugs       (needs manual routing — no Jira component set)
    """
    c = (text + ' ' + title).lower()

    # --- Immersive: native AR / VTO SDK (not VTON the feature, the native SDK layer) ---
    if any(w in c for w in [
        'native ar', 'ar crashing', 'ar library', 'vto sdk', 'drishyamukh',
        '\banr\b', 'augmented reality', '[native]', 'ar to support',
    ]):
        return 'immersive'

    # --- UI: React Native / iOS / Android frontend layer ---
    # Checked BEFORE Backend-Labs / DS / Backend because platform-prefixed
    # bugs ("[iOS] Styledrops_App is crashing", "[RN] Onboarding design")
    # are tagged UI in Jira even when their surface area belongs to another
    # team. Only Immersive (native AR / VTO SDK) is checked earlier — those
    # are deeper than the React Native layer.
    if any(w in c for w in [
        # Original
        'login screen flash', 'cold start', 'cold storage', 'pbxproj',
        '[rn][', 'react native', 'native locationmodule', 'category pills',
        'alignment', 'user input not stacking', 'submit profile',
        'profile for new user', 'screen flashes', 'ios ui', 'ios: login',
        'image not loading', 'broken image', 'product images not loading',
        'broken image icon', 'image never loads', 'no retry', 'no placeholder',
        # Platform prefixes — heavily used in real Jira titles
        '[ios]', '[android]', '[native]', '[rn]', '[ios ]',
        'ios_', 'ios:', 'android_',
        # App-on-platform crashes (UI/native layer crashes, distinct from
        # "checkout crashed" backend symptoms — the platform prefix or
        # native-app phrasing identifies these as UI)
        'app is crashing', 'crashing while', 'crashing after',
        'app crashing for', 'app crashing on',
        # Visual / layout / spacing — the dominant UI bug pattern
        'extra space', 'white space', 'extra white', 'huge space',
        'horizontal extra', 'between two words',
        'overlapping', 'overlap', 'overlapped', 'overlaping',
        'spacing', 'not properly spaced', 'spaced',
        'not aligned', 'aligned correctly', "don't stay aligned",
        'looking little odd', 'looks off', 'looks odd', 'looks off for',
        'design looks', 'design issues', 'design changes',
        'patchwork design',
        # Element visibility / hidden
        'not visible', 'completely visible', 'hidden',
        'is hidden', 'visibility',
        # Click / tap / gesture (touch interaction belongs to UI layer)
        'not clickable', 'is not clickable', 'unclickable',
        'not tappable', 'tappable',
        'swipe', 'gesture', 'swipe down', 'swipe to',
        'scroll', 'scrolling', 'pull-to-refresh',
        'touch target', 'restricted input touch',
        'click doesn’t work', 'click doesnt work',
        'product itself is not clickable', 'not clickable inside',
        # UI components / containers — keep specific phrases. Bare
        # "bottom sheet" / "menu" / "icon" appear in BE_Labs bugs too
        # (Social Finds bottomsheets, Styledrops menus) so we only fire
        # UI when the phrasing is clearly about the UI behaviour.
        'inside bottomsheet', 'bottomsheet handling',
        'popup', 'dropdown', 'drop-down',
        'keyboard', 'hamburger menu',
        'textbox', 'text input', 'textinput', 'textinputbar',
        'input bar', 'input field', 'name input',
        'icons', 'iconography',
        # Native build / iOS / Android specifics
        'cocoapods', 'xcode', 'objectversion', 'gradle',
        # Animation / visual state
        'animation', 'frozen animation', 'animations',
        'flashing', 'flickers', 'flickering',
        # Image / cropping (visual side, distinct from "image not loading"
        # which we already have)
        'image cropping', 'image cropper', 'cropper', 'crop tool',
        'pixelated', 'getting pixelated', 'getting clipped',
        'images getting cropped',
        # UI text/copy issues — visual presentation of text on the UI
        'text overlapping', 'text on ui', 'text is overlapping',
        'extra space below', 'space below the answers',
        'space between two', 'strange symbols',
        'lower case', 'letter case', 'in title case',
        # UI behaviour quality
        'ui feeling', 'ui feels', 'ui got messed', 'ui issue',
        'ui bug', 'ui validation', 'ui is broken',
        'choppy', 'clunky',
        # Visual progress / step indicators (onboarding UI)
        'step icons', 'progress indicator', 'progress indicators',
        'missing visual', 'visual progress',
        # Hamburger / settings / labels
        'incorrect labels', 'labels are',
        # Common phrasings of "show all" / "see all" UI controls
        'show all review', 'view all bottom sheet', 'view more reviews',
        'view all offers',
        # Image visibility on cards (UI rendering, not data)
        # NB: "product image are missing in the styledrops" is REMOVED from
        # UI — it's a BE_Labs ownership question (Styledrops feature owns
        # its product cards' data), not a UI rendering one.
        'product images are not visible', 'images are not completely visible',
        # OTP input UX (form rather than auth itself)
        'otp input field lacks', 'otp field',
        # Open / navigation issues — keep specific to avoid eating deeplink
        # / link-routing bugs that are Backend (not UI)
        'not opening any',
        # Onboarding UI design (vs Backend onboarding flow)
        'onboarding page design', 'onboarding step icons',
        'onboarding step', 'onboarding flow design',
    ]):
        return 'UI'

    # --- BE_Labs: experimental ML features, Feed ML, VTON, Social Finds, Review Synth ---
    if any(w in c for w in [
        # Original features
        'vton', 'virtual try', 'social finds', 'review synth', 'review synthesis',
        'decoded looks', 'complete your look', 'style drops', 'q2p',
        'machine identity', 'draping', 'vton usage', 'gender mismatch',
        'vton onboarding', 'personaaddedat', 'dao related',
        # Real Jira titles use "Styledrops" / "styledrops" / "[StyleDrops]"
        # (no whitespace) — the original 'style drops' did NOT catch these.
        'styledrops', 'style_drops', '[styledrops]',
        # Vibes Player feature (visible in slap_context/SLAP_KNOWLEDGE.md)
        'vibe ', 'vibes', 'vibe api', 'vibes api', 'vibes player',
        # AI-generation / rendering quirks specific to BE_Labs surfaces
        'ai generation', 'ai rendering', 'avatar generation', 'enhanced image',
        # Internal infra dashboards/services owned by BE_Labs
        'cosmos', 'moodboard', 'frame status', 'frames status',
        # Reel / send-content social ingestion
        'sending reel', 'send reel', 'after sending reel',
        # Other Styledrops-context vocabulary
        'liked drop', 'liked drops', 'drops are showing', 'drop ready',
        'generating your drops', 'your drops',
        # Specific phrases that route BE_Labs even when they mention edison
        # (edison alone is Backend infra; in styledrops/vibes context it's BE_Labs)
        'styledrops edison', 'notifying edison',
    ]):
        return 'Backend-Labs'

    # --- DS: data science, model quality, NPS, product page analytics ---
    if any(w in c for w in [
        # Original
        'nps', '%positive', 'product page discrepancy', 'product title discrepancy',
        'discrepancy in product title', 'model quality', 'data science',
        'ranking quality', 'recommendation quality',
        # Result quality / relevance (most common DS phrasing in real bugs)
        'wrong result', 'showing wrong result', "results weren't shown",
        'results not shown', 'wrong response', 'no results',
        'got only', 'only 2 results',
        'relevance', 'relevant', 'irrelevant',
        # Summary/suggestion mismatches
        'summary not matching', 'suggestion not matching',
        'summary and suggestion', 'wrong summary',
        'old query', 'old products', 'stale results',
        'product suggestion is missing', 'product suggestions is',
        'product suggestions are', 'product suggestion missing',
        # Model behaviour / quality
        'failed to answer', 'model failed', 'bot is failed',
        'general intelligence', 'grounding',
        'inappropriate', 'unsafe request',
        'prompt still needs',
        # Content presentation owned by DS (text wrap, tables, scope mismatches)
        'text cut off', 'showing tables', 'tabular', 'tables',
        'hyperlink instead', 'bad state message',
        'scanning the inventory',
        # Scope/range mismatch
        'above price range but results are for below',
        'changed the context', 'context to',
        'gender neutral, results',
        # Specific DS-owned response failures
        'developed by google',
    ]):
        return 'DS'

    # --- BE_Flippi: core backend — chat, search, cart, checkout, auth, infra ---
    if any(w in c for w in [
        # Original
        'checkout', 'proceed to pay', 'cart', 'payment', 'add to cart',
        'search', 'recommendation', 'product listing', 'price', 'delivery',
        'session', 'login', 'auth', 'otp', 'failed to verify', 'onboarding',
        'grayskull', 'secret', 'edison', 'spinner', 'freeze', 'thinking...',
        'chat', 'ai chat', 'feed', 'dedup', 'journey continuation',
        'sources widget', 'profile update', 'signup', 'order', 'bot',
        'summary without products', 'reasons to buy', 'product card',
        # Modest additions for the 16 Backend bugs that fell through to "bugs"
        'log level', 'logs', 'stability and reliability',
        'conversation', 'conversation title', 'conversation id',
        'recent conversations',
        're-arch', 'rearch', 'product compare', 'da flow',
        'product compare card',
    ]):
        return 'Backend'

    # --- bugs: unclassifiable — needs manual team routing ---
    return 'bugs'


def _extract_reproducibility(text: str) -> str:
    m = re.search(r'Reproducibility[:\s]+(.+?)(?:\.|$|\n)', text, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        if '100' in val or 'every time' in val or 'always' in val or 'consistent' in val:
            return '100%'
        if 'intermittent' in val or 'sometimes' in val or 'occasional' in val:
            return 'intermittent'
        if 'conditional' in val:
            return 'conditional'
        pct = re.search(r'~?(\d+)%', val)
        if pct:
            return f"~{pct.group(1)}%"
    tl = text.lower()
    if '100% reproducible' in tl or 'every single time' in tl or '100% consistent' in tl:
        return '100%'
    if re.search(r'\b100%\b', tl):
        return '100%'
    if 'every time' in tl or 'always' in tl:
        return '100%'
    if 'intermittent' in tl:
        return 'intermittent'
    return 'unknown'


def _build_description(text: str, lines: list) -> str:
    body_lines = []
    past_headers = False
    for line in lines:
        if re.match(r'^(From|To|Subject|Date):', line, re.IGNORECASE):
            past_headers = True
            continue
        if not past_headers:
            continue
        stripped = line.strip()
        if not stripped:
            if body_lines:
                break
            continue
        # Skip section headers and bullet lines
        if re.match(r'^(Steps|Expected|Actual|Impact|Environment|Reproducibility|Additional)', stripped, re.IGNORECASE):
            break
        body_lines.append(re.sub(r'\*+', '', stripped))
        if len(body_lines) >= 6:
            break

    raw = ' '.join(body_lines)
    if not raw:
        return "See full bug report for details."
    sentences = re.split(r'(?<=[.!?])\s+', raw)
    desc = ' '.join(sentences[:3])
    return desc[:450] + ('...' if len(desc) > 450 else '')
