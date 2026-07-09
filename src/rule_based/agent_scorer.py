"""
agent_scorer.py — Multi-layer severity scorer (no API key required).

Priority is decided by four layers applied in order, first confident signal wins:

  Layer 1 — Keyword signals   (fast, specific, handles exact phrasing)
  Layer 2 — Template scoring  (TF-IDF over priority templates, handles paraphrases)
  Layer 3 — Weighted similar-bug voting (semantic inheritance from Jira history)
  Layer 4 — Impact-text fallback (last resort keyword scan on impact field)

Priority ladder:
  P0 — crash / checkout-payment blocked / security-secrets / all-users outage
  P1 — wrong AI results / price mismatch / ANR / majority-user impact
  P2 — partial UX degradation / images broken / workaround exists
  P3 — vague / low-scope / cosmetic / edge-case
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .agent_parser import BugReport


@dataclass
class SeverityResult:
    priority: str
    priority_id: str
    severity: str
    justification: str
    scoring_path: str   # which layer decided the priority — useful for debugging


PRIORITY_ID_MAP = {
    "P0": "10000",
    "P1": "10001",
    "P2": "10002",
    "P3": "10003",
    "P4": "10004",
}

SEVERITY_FOR_PRIORITY = {
    "P0": "Blocker",
    "P1": "Critical",
    "P2": "Major",
    "P3": "Minor",
    "P4": "Cosmetic",
}

# ---------------------------------------------------------------------------
# Layer 1 — Keyword signal lists
# ---------------------------------------------------------------------------

# Crash patterns require active-voice context (avoids "no crash logs" FP)
P0_HARD = [
    r'app crash(?:es|ed)\b',
    r'crash(?:es)? to (?:home|desktop|background)',
    r'crash(?:es)? (?:immediately|silently|on )',
    r'\bforce[ -]kill\b',
    r'\bproceed to pay\b',
    r'revenue[ -]blocking',
    r'\bzero users can\b',
    r'\ball android orders\b',
    r'\ball users affected\b',
    r'\ball users\b',                    # Fix 2: unqualified "all users"
    r'\ball \w+ users\b',               # Fix 2: "all male users", "all iOS users"
    r'\bgrayskull\b',
    r'secrets management',
    r'security concern',
    r'production failure',
    r'complete outage',
    r'login outage',
]
P0_SOFT = [
    r'\brevenue\b',
    r'checkout broken',
    r'payment broken',
    r'entirely broken',
    r'blocked for all',
    r'primary conversion',
    r'cannot purchase',
    r'\bblocked\b',
    r'60% of our user',
]
P1_HARD = [
    r'wrong product recommendation',
    r'wrong recommendation',
    r'incorrect recommendation',
    r'price constraint',
    r'outside.*budget',
    r'exceeds.*stated.*price',
    r'ignoring.*price',                  # Fix 3 complement: "ignoring price"
    r'ignores.*budget',
    r'multiple user complaints',
    r'user complaints',
    r'support tickets',
    r'core value proposition',
    r'trust in the ai',
    r'\banr\b',                          # Fix 1: Application Not Responding
    r'application not responding',       # Fix 1: written out form
    r'app (?:hangs|freezes|becomes unresponsive)',  # Fix 1: paraphrases of ANR
    r'\ball \w+ users\b',               # Fix 2: "all male users" etc. → at least P1
    r'every user',
    r'every session',
    r'every account',
    r'\d+% of.*users',                   # Fix 2: "30% of users" → P1 scope signal
    r'\d+% of our',
]
P1_SOFT = [
    'wrong results',
    'price mismatch',
    'incorrect results',
    'significant user',
    'significant impact',
    'majority',
    'affects all platforms',
    'login fails',
    'login failing',
]
P2_SIGNALS = [
    'image not loading',
    'broken image',
    'slow network',
    '2g',
    '3g',
    'weak 4g',
    'tier 2',
    'tier 3',
    'placeholder',
    'workaround',
    'visual issue',
    'subset of users',
    'partial',
    'unprofessional',
    'network throttling',
]
P3_SIGNALS = [
    'vague',
    'not sure',
    'something wrong',
    'something is wrong',
    'not working properly',
    'very frustrating',
    'please look into it',
    'didnt get',
    'weird',
    'minor',
]


# ---------------------------------------------------------------------------
# Layer 2 — Template scorer (handles paraphrases via TF-IDF)
# ---------------------------------------------------------------------------

class PriorityTemplateScorer:
    """
    Fits a TF-IDF matrix over per-priority template sentences at import time.
    For a new bug corpus, returns the priority whose templates score highest
    in cosine similarity — catches paraphrases that exact keywords miss.

    Templates are written to cover common *ways of saying* the same thing,
    not just the most obvious phrasing.
    """

    TEMPLATES: dict[str, list[str]] = {
        "P0": [
            # Crash / checkout / payment blocked
            "app crashes force closes users cannot complete purchase",
            "checkout payment flow completely broken blocked all users",
            "users cannot buy anything revenue blocked zero purchases",
            "app crashes to home screen force kill restart needed",
            "crash immediately on key action payment checkout fails",
            # Security / infra
            "secrets credentials exposed security vulnerability production",
            "grayskull secrets management infra failure production broken",
            "authentication completely broken login impossible platform outage",
            # Scope: everyone affected
            "every user affected complete outage no one can use the app",
            "all users locked out cannot access the app whatsoever",
            "entire user base impacted all sessions failing consistently",
        ],
        "P1": [
            # AI/recommendations wrong
            "ai ignores price budget constraint recommends expensive wrong products",
            "search returns completely wrong irrelevant incorrect recommendations",
            "price filter ignored budget not respected ai suggests costly items",
            "ai completely fails to understand user query wrong answers every time",
            "recommendations do not match what user asked for wrong category",
            # ANR / freeze
            "application not responding anr hangs freezes key feature blocked",
            "app hangs becomes unresponsive native crash on important feature",
            "anr android not responding virtual try on ar native crash",
            # Trust / majority impact
            "users losing trust ai assistant significant degradation majority sessions",
            "significant impact most users affected high frequency occurrence",
            "feature broken for large portion of users frequent failure",
            # Gender / personalization wrong
            "wrong gender profile shown personalization incorrect wrong recommendations",
            "male users see female content wrong persona gender mismatch profile",
            "personalization logic error wrong user segment shown incorrect content",
            # Price / data wrong
            "price shown wrong mismatch between platforms incorrect amount",
            "data discrepancy metrics wrong values different between systems",
            "nps score wrong percentage positive incorrect product page data",
        ],
        "P2": [
            # Images / visual
            "images not loading slow network no retry broken placeholder missing",
            "product images fail to load poor network conditions 2g 3g",
            "visual bug cosmetic issue broken layout image icon not showing",
            "no fallback for image loading network failure graceful degradation missing",
            # Partial / workaround
            "partial functionality degraded workaround exists subset of users",
            "some users affected tier 2 tier 3 cities network quality poor",
            "intermittent issue occasional failure sometimes works fine",
            "performance degraded slow but functional workaround available",
            # UI visual
            "login screen flashes animation broken cold start visual glitch",
            "screen flickers briefly before correct state app startup issue",
        ],
        "P3": [
            "minor cosmetic issue alignment spacing low priority edge case",
            "vague unclear report no steps to reproduce insufficient information",
            "occasionally happens rarely affects few users low frequency glitch",
            "not sure something looks off cannot reproduce consistently",
            "nice to have low urgency no user impact just aesthetics",
        ],
    }

    # Minimum cosine similarity to trust a template match
    THRESHOLDS = {"P0": 0.28, "P1": 0.22, "P2": 0.18, "P3": 0.15}

    def __init__(self):
        self._texts:  list[str] = []
        self._labels: list[str] = []
        for priority, sentences in self.TEMPLATES.items():
            for s in sentences:
                self._texts.append(s)
                self._labels.append(priority)

        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words='english',
            sublinear_tf=True,
        )
        self._matrix = self._vectorizer.fit_transform(self._texts)

    def score(self, corpus: str) -> tuple[Optional[str], float]:
        """
        Return (priority, confidence) if template similarity exceeds the
        per-priority threshold, else (None, 0.0).
        """
        q_vec  = self._vectorizer.transform([corpus])
        sims   = cosine_similarity(q_vec, self._matrix).flatten()

        best_per: dict[str, float] = {}
        for idx, label in enumerate(self._labels):
            if sims[idx] > best_per.get(label, 0.0):
                best_per[label] = float(sims[idx])

        # Pick priority ordered P0 → P3; return first one above its threshold
        for priority in ("P0", "P1", "P2", "P3"):
            score = best_per.get(priority, 0.0)
            if score >= self.THRESHOLDS[priority]:
                return priority, round(score, 3)

        return None, 0.0


# Singleton — fitted once at import time (instant for ~40 sentences)
_TEMPLATE_SCORER = PriorityTemplateScorer()


# ---------------------------------------------------------------------------
# Layer 3 — Weighted similar-bug priority voting
# ---------------------------------------------------------------------------

_PRIORITY_NUM = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
_NUM_PRIORITY = {0: "P0", 1: "P1", 2: "P2", 3: "P3", 4: "P4"}

def _weighted_priority_from_similar(similar_bugs: list) -> Optional[str]:
    """
    Fix 4: cast weighted priority votes from similar bugs with sim > 0.20.
    Each similar bug contributes its numeric priority (P0=0 … P4=4)
    weighted by its similarity score. Returns the weighted-average priority,
    or None if there isn't enough signal (total weight < 0.25).

    This catches cases where multiple moderately-similar P1 bugs all point
    to a P1 classification even though no single keyword matched.
    """
    weighted_sum = 0.0
    total_weight = 0.0

    for m in similar_bugs:
        if m.similarity >= 0.20:
            num = _PRIORITY_NUM.get(m.priority, 2)
            weighted_sum += m.similarity * num
            total_weight += m.similarity

    if total_weight < 0.25:
        return None

    avg = weighted_sum / total_weight
    bucket = min(3, max(0, round(avg)))
    return _NUM_PRIORITY[bucket]


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

def score_severity(bug: BugReport, similar_bugs: list) -> SeverityResult:
    corpus = ' '.join(filter(None, [
        bug.title, bug.description, bug.impact,
        bug.actual_result, bug.raw_text,
    ])).lower()

    # ── Layer 1: keyword signals ──────────────────────────────────────────
    p0_hard_hits = [kw for kw in P0_HARD if re.search(kw, corpus)]
    p0_soft_hits = [kw for kw in P0_SOFT if re.search(kw, corpus)]
    p1_hard_hits = [kw for kw in P1_HARD if re.search(kw, corpus)]
    p1_soft_hits = [kw for kw in P1_SOFT if kw in corpus]
    p2_hits      = [kw for kw in P2_SIGNALS if kw in corpus]
    p3_hits      = [kw for kw in P3_SIGNALS if kw in corpus]

    is_100_repro = bug.reproducibility == '100%'
    is_vague     = len(bug.raw_text.strip()) < 350 and not bug.steps_to_reproduce

    top_sim        = similar_bugs[0] if similar_bugs else None
    is_dup         = bool(top_sim and top_sim.is_duplicate_candidate)
    inherited_prio = top_sim.priority if is_dup else None

    # ── Layer 2: template similarity ─────────────────────────────────────
    tmpl_priority, tmpl_score = _TEMPLATE_SCORER.score(corpus)

    # ── Layer 3: weighted similar-bug voting ─────────────────────────────
    sim_priority = _weighted_priority_from_similar(similar_bugs)

    # ── Decision tree ─────────────────────────────────────────────────────
    priority     = None
    scoring_path = ""

    # P0: hard keyword (any single hit = P0)
    if not priority and (p0_hard_hits or (p0_soft_hits and is_100_repro)):
        priority     = 'P0'
        scoring_path = f"L1-keyword: {(p0_hard_hits or p0_soft_hits)[0]}"
        just         = _justify_p0(bug, p0_hard_hits or p0_soft_hits, top_sim, is_dup)

    # P0: duplicate of a P0 ticket
    if not priority and inherited_prio == 'P0':
        priority     = 'P0'
        scoring_path = f"L1-duplicate: {top_sim.key}"
        just         = _justify_inherited(bug, top_sim, 'P0')

    # P0: template match with high confidence
    if not priority and tmpl_priority == 'P0':
        priority     = 'P0'
        scoring_path = f"L2-template: P0 (score={tmpl_score})"
        just         = f"Template similarity score {tmpl_score:.2f} matches P0 patterns. " + \
                       _justify_p0(bug, [], top_sim, is_dup)

    # P1: hard keyword OR 2+ soft keywords
    if not priority and (p1_hard_hits or len(p1_soft_hits) >= 2):
        priority     = 'P1'
        scoring_path = f"L1-keyword: {(p1_hard_hits or p1_soft_hits)[0]}"
        just         = _justify_p1(bug, p1_hard_hits or p1_soft_hits, top_sim, is_dup)

    # P1: single soft keyword (not vague)
    if not priority and p1_soft_hits and not is_vague:
        priority     = 'P1'
        scoring_path = f"L1-soft: {p1_soft_hits[0]}"
        just         = _justify_p1(bug, p1_soft_hits, top_sim, is_dup)

    # P1: template match
    if not priority and tmpl_priority == 'P1':
        priority     = 'P1'
        scoring_path = f"L2-template: P1 (score={tmpl_score})"
        just         = f"Template similarity score {tmpl_score:.2f} matches P1 patterns (paraphrase detected). " + \
                       _justify_p1(bug, [], top_sim, is_dup)

    # P1: duplicate of P1 ticket (not vague)
    if not priority and inherited_prio == 'P1' and not is_vague:
        priority     = 'P1'
        scoring_path = f"L1-duplicate: {top_sim.key}"
        just         = _justify_inherited(bug, top_sim, 'P1')

    # P2: keyword signal
    if not priority and p2_hits:
        priority     = 'P2'
        scoring_path = f"L1-keyword: {p2_hits[0]}"
        just         = _justify_p2(bug, p2_hits, top_sim)

    # P2/P1: weighted similar-bug vote (Fix 4)
    if not priority and sim_priority and not is_vague:
        priority     = sim_priority
        scoring_path = f"L3-similar-weighted: {sim_priority}"
        just         = _justify_similar_weighted(sim_priority, bug, similar_bugs)

    # P3: vague or low-signal keywords
    if not priority and (is_vague or p3_hits):
        priority     = 'P3'
        scoring_path = "L1-vague" if is_vague else f"L1-keyword: {p3_hits[0]}"
        just         = _justify_p3(bug, is_vague, p3_hits)

    # Last resort: impact-text scan
    if not priority:
        impact_lower = (bug.impact or '').lower()
        if any(w in impact_lower for w in ['blocking', 'revenue', 'all users', 'zero']):
            priority = 'P0'
        elif any(w in impact_lower for w in ['significant', 'majority', 'trust', 'multiple']):
            priority = 'P1'
        elif any(w in impact_lower for w in ['subset', 'some users', 'workaround', 'may']):
            priority = 'P2'
        else:
            priority = 'P2'
        scoring_path = "L4-impact-fallback"
        just         = _justify_fallback(priority, bug, top_sim)

    return SeverityResult(
        priority=priority,
        priority_id=PRIORITY_ID_MAP[priority],
        severity=SEVERITY_FOR_PRIORITY[priority],
        justification=just,
        scoring_path=scoring_path,
    )


# ---------------------------------------------------------------------------
# Justification builders
# ---------------------------------------------------------------------------

def _is_crash_trigger(triggers: list) -> bool:
    return any(re.search(r'crash', kw) or re.search(r'force.kill', kw) for kw in triggers)


def _justify_p0(bug: BugReport, triggers: list, top, is_dup: bool) -> str:
    parts = []
    if _is_crash_trigger(triggers):
        parts.append(
            f"100%-reproducible crash on {bug.platform or 'the affected platform'} "
            "directly blocks the core conversion flow — users cannot complete checkout."
        )
    elif any(re.search(r'grayskull|secrets management|security concern', kw) for kw in triggers):
        parts.append(
            "Security / secrets-management issue in production. "
            "FLIPPI policy: any secrets/infra risk is P0 regardless of user-facing scope."
        )
    elif any(re.search(r'proceed to pay|checkout broken|revenue', kw) for kw in triggers):
        parts.append(
            "Payment / checkout flow completely blocked — "
            "direct revenue impact affecting all users on the platform."
        )
    elif any(re.search(r'login outage|complete outage', kw) for kw in triggers):
        parts.append("Complete login outage: affected users are locked out entirely.")
    elif any(re.search(r'all \w* users|all users', kw) for kw in triggers):
        parts.append(
            "Broad user scope — all affected users cannot use a core feature. "
            "Classified P0 due to scope × impact combination."
        )
    else:
        parts.append("Multiple P0 signals: core user flow is broken with broad scope.")
    if is_dup and top:
        parts.append(f"Matches existing P0 ticket {top.key}: \"{top.summary[:70]}\".")
    return ' '.join(parts)


def _justify_p1(bug: BugReport, triggers: list, top, is_dup: bool) -> str:
    parts = []
    trigger_str = ' '.join(triggers)
    if any(re.search(p, trigger_str) for p in [r'recommendation', r'price', r'budget', r'ignor']):
        parts.append(
            "AI recommendations are ignoring price constraints, directly eroding user "
            "trust in the core SLAP value proposition."
        )
    elif any(re.search(p, trigger_str) for p in [r'anr', r'not responding', r'hangs', r'freezes']):
        parts.append(
            f"ANR / unresponsive app on {bug.platform or 'affected platform'} "
            "blocks a key feature — P1 for native-layer failures on important flows."
        )
    elif 'login' in trigger_str:
        parts.append(
            "Login failures affecting a subset of credentials — users locked out, "
            "but not a full platform outage."
        )
    elif any(re.search(p, trigger_str) for p in [r'gender', r'persona', r'personali']):
        parts.append(
            "Personalization logic error: wrong user segment served, "
            "affecting all users of the impacted feature."
        )
    elif any(re.search(p, trigger_str) for p in [r'nps', r'discrepancy', r'%positive']):
        parts.append(
            "Data discrepancy in product-page metrics — NPS / %Positive values "
            "differ from FK main app, affecting ranking and user trust signals."
        )
    else:
        parts.append(
            f"Significant user-facing degradation ({bug.reproducibility} reproducibility). "
            "Impacts core AI or browsing flow across the majority of sessions."
        )
    if is_dup and top:
        parts.append(f"Closely matches {top.key} ({top.priority}): \"{top.summary[:70]}\".")
    elif top and top.similarity > 0.20:
        parts.append(
            f"Most similar historical bug: {top.key} ({top.priority}) — "
            f"\"{top.summary[:60]}\" (sim={top.similarity:.2f})."
        )
    return ' '.join(parts)


def _justify_p2(bug: BugReport, triggers: list, top) -> str:
    parts = []
    if any(kw in triggers for kw in ['image not loading', 'broken image']):
        parts.append(
            "Product images fail to load on poor networks (2G/3G), degrading UI "
            "but not blocking purchases — a workaround (text + price visible) exists."
        )
    else:
        parts.append(
            "Partial UX degradation; a workaround or fallback exists. "
            "Primarily affects a subset of users (slow-network / Tier-2/3 cities)."
        )
    if top and top.similarity > 0.15:
        parts.append(
            f"Similar historical bug: {top.key} ({top.priority}) — "
            f"\"{top.summary[:60]}\" (sim={top.similarity:.2f})."
        )
    return ' '.join(parts)


def _justify_p3(bug: BugReport, is_vague: bool, triggers: list) -> str:
    if is_vague:
        return (
            "Report lacks steps to reproduce, platform details, and measurable impact. "
            "Assigned P3 pending further information from the reporter. "
            "Re-triage once more context is provided."
        )
    return (
        "Low-severity signal words detected. "
        "Limited scope or cosmetic issue; no clear revenue or user-flow impact stated."
    )


def _justify_inherited(bug: BugReport, top, priority: str) -> str:
    return (
        f"Duplicate or very close match of {top.key} ({top.priority}): "
        f"\"{top.summary[:80]}\" (similarity {top.similarity:.2f}). "
        f"Inheriting {priority} from the matched ticket — "
        "engineer should verify and link rather than file a new ticket."
    )


def _justify_similar_weighted(priority: str, bug: BugReport, similar_bugs: list) -> str:
    contributors = [m for m in similar_bugs if m.similarity >= 0.20]
    names = ', '.join(f"{m.key} ({m.priority}, sim={m.similarity:.2f})" for m in contributors[:3])
    return (
        f"Weighted priority vote from {len(contributors)} similar historical bug(s): {names}. "
        f"Similarity-weighted average resolves to {priority}. "
        "No strong keyword or template signal — human review recommended."
    )


def _justify_fallback(priority: str, bug: BugReport, top) -> str:
    base = f"Assigned {priority} based on impact field keywords."
    if top:
        base += (
            f" Most similar historical bug: {top.key} ({top.priority}) — "
            f"\"{top.summary[:60]}\" (sim={top.similarity:.2f})."
        )
    return base
