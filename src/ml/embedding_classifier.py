"""
embedding_classifier.py — Embedding-based component classifier.

Replaces the keyword-regex `_extract_component` in agent_parser.py with
something that actually learns from labelled history.

Pipeline:
  1. Build phase (one-time, ~3 minutes on 2000 bugs):
     - Fetch FLIPPI bugs that have a component populated (server-side
       filter via JiraClient.fetch_training_corpus).
     - Embed each bug's "title + description" with
       sentence-transformers/all-mpnet-base-v2. Runs locally, no API key.
     - Save the embedding matrix + labels to disk as a single .npz.

  2. Predict phase (~50ms per new bug):
     - Load cached embeddings + labels.
     - Embed the new bug.
     - Compute cosine similarity against all training vectors.
     - Adaptive k-NN:
       * If the top-1 similarity is ≥ HIGH_CONFIDENCE_THRESHOLD, use k=1
         (trust the very-close match).
       * Otherwise compute a distance-weighted vote over top-K matches.
     - If the winning class's weighted-vote share is below
       CONFIDENCE_THRESHOLD, return "bugs" instead of guessing.

Confidence is the share of total weighted vote captured by the winning
class. A 0.85 confidence on "Backend" means the winning class got 85% of
the weighted vote — high confidence. A 0.40 confidence means the top-K
were split and the model isn't sure; we route to manual triage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


# ── Tuning knobs ────────────────────────────────────────────────────────────

EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"

TOP_K = 5                       # neighbours considered for the weighted vote
HIGH_CONFIDENCE_THRESHOLD = 0.85  # cosine sim above which we trust top-1 alone
CONFIDENCE_THRESHOLD = 0.40       # below this → route to "bugs" (low confidence)

# Hybrid mode: LogReg is the primary classifier. When LogReg's top-class
# probability is below this threshold we fall back to a focused Claude call
# to handle the borderline case. In LOO validation Claude (65.1%) and LogReg
# (66.8%) were within noise; Claude was specifically better on BE_Labs and
# Backend recall. The fallback captures that benefit without paying Claude's
# ~6.6s latency on the bugs LogReg is confident about.
#
# Raised from 0.50 → 0.60 to favour accuracy over speed — more bugs in the
# 0.50–0.60 "somewhat confident" band now go to Claude+skills instead of
# taking LogReg's answer. The fast/fallback split at 0.60 hasn't been
# re-measured against the LOO harness yet; expect roughly 55/45 (from
# 64/36 at 0.50) as a working guess, with a small overall accuracy bump
# on the shifted bugs at the cost of ~600ms extra average latency.
HYBRID_CLAUDE_FALLBACK_THRESHOLD = 0.60

# Architecture skill files — loaded for the top-3 candidate teams when
# LogReg confidence is borderline. Lets Claude reason over real team
# ownership / repo structure instead of the generic prompt boilerplate.
_ARCHITECTURE_DIR = Path(__file__).parent.parent.parent / "slap_context" / "architecture"
_REPO_SKILLS_DIR  = _ARCHITECTURE_DIR / "repos"
_REPOS_MANIFEST   = _ARCHITECTURE_DIR / "repos.json"

# Maps component label (as the classifier predicts) → architecture skill file.
# Files are read at first use and cached for the process lifetime; if a file
# is missing the loader returns "" so the prompt still works.
_SKILL_FILES = {
    "Backend":      "Backend.md",
    "Backend-Labs": "Backend-Labs.md",
    "DS":           "DS.md",
    "UI":           "UI.md",
    "immersive":    "immersive.md",
}

_skill_cache:        dict[str, str]       = {}
_repo_skill_cache:   dict[str, str]       = {}
_team_to_repos:      Optional[dict[str, list[str]]] = None


def _load_team_to_repos() -> dict:
    """Lazy-load the team → [repo, repo, ...] map from repos.json. Cached."""
    global _team_to_repos
    if _team_to_repos is not None:
        return _team_to_repos
    try:
        import json
        with _REPOS_MANIFEST.open() as f:
            data = json.load(f)
        out: dict = {}
        for r in data.get("repos", []):
            out.setdefault(r["team"], []).append(r["name"])
        _team_to_repos = out
    except Exception:
        _team_to_repos = {}
    return _team_to_repos


def _load_skill(component: str) -> str:
    """Return the team-level skill file for `component`, cached."""
    if component in _skill_cache:
        return _skill_cache[component]
    name = _SKILL_FILES.get(component)
    if not name:
        _skill_cache[component] = ""
        return ""
    path = _ARCHITECTURE_DIR / name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    _skill_cache[component] = text
    return text


def _load_repo_skill(repo_name: str) -> str:
    """Return the per-repo skill file for `repo_name`, if a clone has been
    indexed by `build_repo_skills.py`. Empty string when unavailable."""
    if repo_name in _repo_skill_cache:
        return _repo_skill_cache[repo_name]
    path = _REPO_SKILLS_DIR / f"{repo_name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    _repo_skill_cache[repo_name] = text
    return text


def _load_top_skills(top_candidates: list, k: int = 3) -> str:
    """Load skills for the top-k candidate components. For each component
    we include:
      1. The team-level skill file (Backend.md, UI.md, etc.)
      2. The per-repo skill file for each cloned repo owned by that team
         (auto-generated by build_repo_skills.py from the actual code).
    Per-repo files are skipped silently if not present.
    """
    team_repos = _load_team_to_repos()
    seen: set = set()
    chunks: list[str] = []
    for c in top_candidates:
        if c in seen or c == "bugs":
            continue
        seen.add(c)
        team_skill = _load_skill(c)
        if team_skill:
            chunks.append(f"━━━━━━━━━━ TEAM SKILL: {c} ━━━━━━━━━━\n{team_skill}")
            # Append every per-repo skill we have for this team.
            for repo_name in team_repos.get(c, []):
                rs = _load_repo_skill(repo_name)
                if rs:
                    chunks.append(f"────── repo: {c} / {repo_name} ──────\n{rs}")
        if len(chunks) >= k * 4:   # rough cap so prompt doesn't explode
            break
    return "\n\n".join(chunks) if chunks else "(no architecture skill files available)"


# Same focused prompt the validate_claude_component.py script measured at 65.1%.
_CLAUDE_COMPONENT_PROMPT = """You are the SLAP triage component classifier. Pick ONE component for the bug below.

Component options (priority order — first that fits wins):

immersive    — Native AR / VTO SDK / ANRs in native code / drishyamukh.

UI           — React Native / iOS / Android frontend:
   • Title prefixed [iOS], [Android], [RN], [Native][...]
   • Visual / layout / spacing / alignment / overlap
   • Click / tap / gesture / swipe / scroll issues
   • Keyboard, hamburger menu, dropdown, textbox issues
   • Image cropping / pixelation / clipping
   • Native build: CocoaPods, Xcode, gradle, pbxproj
   • Animation / flickering / frozen
   • "Show all / View more" UI controls broken

Backend-Labs — Experimental ML / personalization:
   • VTON / virtual try-on / draping / Q2P / Machine Identity
   • Social Finds, Review Synth, Decoded Looks
   • Style Drops (also "Styledrops" / "[StyleDrops]")
   • Vibes Player / Moodboard / Avatar generation / AI rendering
   • Cosmos dashboard / Frame status
   • Reels ingestion / Liked Drops / drop generation
   • Edison in BE_Labs context
   • IMPORTANT: a [iOS]/[Android]/[RN]-prefixed visual bug on a BE_Labs surface is UI, not BE_Labs.

DS           — Data science / model quality / content presentation:
   • NPS, %Positive, ranking quality, recommendation quality
   • Result relevance: "wrong results", "irrelevant", "summary not matching"
   • Model behaviour: "failed to answer", "grounding", "inappropriate"
   • Content presentation: "text cut off", "showing tables", "tabular"

Backend      — Core backend: chat AI, search, cart, checkout, payment, auth,
               OTP, sessions, login, signup, Grayskull, secrets, Edison
               (when not in Styledrops/Vibes context), infra, feed dedup,
               journey continuation, bot, conversation, log levels, product compare.

bugs         — Return "bugs" when you cannot confidently classify. Prefer "bugs" over a wrong guess.

BUG REPORT:
---
{text}
---

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{"component": "Backend" | "Backend-Labs" | "DS" | "UI" | "immersive" | "bugs"}}
"""

_VALID_COMPONENTS = {"Backend", "Backend-Labs", "DS", "UI", "immersive", "bugs"}


# Skill-aware fallback prompt — used when we have the LogReg probability
# distribution and can hand Claude the architecture skill files for the
# top-3 candidate teams. This gives Claude real architectural context to
# reason over instead of the generic boilerplate ladder.
_CLAUDE_COMPONENT_PROMPT_WITH_SKILLS = """You are the SLAP triage component classifier. LogReg, an embedding-based classifier trained on labelled FLIPPI history, couldn't commit to a single team — it found the bug ambiguous between several. Your job is to break the tie by reasoning over each candidate team's architecture and the bug's symptoms.

You MUST pick one of the six valid components: Backend, Backend-Labs, DS, UI, immersive, or bugs.

LogReg's probability distribution (what the embedding model thought):
{probabilities}

Top-3 candidate teams' architecture context (these are real skill files describing what each team owns):

{skill_files}

Reasoning guidance:
1. Read the bug carefully — what's the actual failure mode?
2. For each top-3 candidate, ask: does this team's architecture skill describe ownership of this kind of failure?
3. Pay special attention to the disambiguation tables in the skill files (e.g. "How to tell DS from Backend when both mention search").
4. Prefer the team whose architecture skill MENTIONS the specific failure mode, not the one whose vocabulary happens to overlap with the bug text.
5. If two teams' skills both plausibly cover the bug, prefer the one with stronger semantic similarity in the LogReg distribution.
6. If after reasoning you're still unsure, return "bugs" — manual triage is better than a wrong guess.

BUG REPORT:
---
{text}
---

Reply with ONLY a single JSON object — no markdown fences, no prose:

{{
  "component":  "Backend" | "Backend-Labs" | "DS" | "UI" | "immersive" | "bugs",
  "reasoning":  "1-2 sentences. Reference which skill file's disambiguation rule decided it."
}}
"""


def _classify_with_claude(
    text:           str,
    top_candidates: Optional[list] = None,
    probabilities:  Optional[dict] = None,
) -> tuple:
    """Focused Claude component-only call used as the hybrid fallback.

    If `top_candidates` is provided (a list of component names in
    descending LogReg-confidence order), the skill files for the top-3
    candidates are injected into the prompt — Claude then reasons over
    real architecture context. If not, falls back to the generic prompt.

    Returns `(component, reasoning)`:
      - component:  one of the six valid names, or None if Claude
                    couldn't be reached / returned malformed output
      - reasoning:  Claude's 1-2 sentence explanation, or "" when the
                    generic (non-skill-aware) prompt was used (it
                    doesn't ask for reasoning) or when the call failed
    Never raises.
    """
    try:
        from .claude_cli import call_claude
        truncated = (text or "")[:3500]

        if top_candidates:
            # Format the probability distribution as a readable block.
            prob_lines = []
            for c, p in sorted((probabilities or {}).items(), key=lambda kv: -kv[1]):
                prob_lines.append(f"  {c:14s} {p:.3f}")
            prompt = _CLAUDE_COMPONENT_PROMPT_WITH_SKILLS.format(
                probabilities = "\n".join(prob_lines) if prob_lines else "(unavailable)",
                skill_files   = _load_top_skills(top_candidates, k=3),
                text          = truncated,
            )
        else:
            prompt = _CLAUDE_COMPONENT_PROMPT.format(text=truncated)

        response = call_claude(prompt, expect_json=True, timeout=90)
        if isinstance(response, dict):
            comp = str(response.get("component", "")).strip()
            reasoning = str(response.get("reasoning") or "").strip()
            if comp in _VALID_COMPONENTS:
                return comp, reasoning
    except Exception:
        pass
    return None, ""

DEFAULT_INDEX_PATH = Path(__file__).parent.parent.parent / "data" / "embedding_index.npz"


# Map raw Jira component names → the canonical class label we predict.
# Components that map to None are excluded from training (too rare or
# administrative).
COMPONENT_TO_LABEL = {
    "Backend":       "Backend",
    "Backend-Labs":  "Backend-Labs",
    "DS":            "DS",
    "UI":            "UI",
    "immersive":     "immersive",
    # Anything else (Design, Product, SLAP_PRODUCT, etc.) stays unlabelled.
}


# ── Result type ─────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    component:        str           # predicted component, or "bugs" if low confidence
    confidence:       float         # 0.0–1.0 — share of weighted vote / top class prob
    method:           str           # "logreg" / "claude-fallback" / "k=1-exact" / etc.
    top_neighbours:   list          # list of (key, label, similarity) tuples
    fell_back_to_bugs: bool         # True if we returned "bugs" because confidence too low
    probabilities:    Optional[dict] = None   # component -> probability, from LogReg.
                                              # None when LogReg isn't available (k-NN fallback).
    reasoning:        str = ""      # 1-2 sentence explanation, populated when the
                                    # Claude+skills fallback ran (LogReg fast path
                                    # leaves this empty — there's no narrative for
                                    # a high-confidence direct prediction)


# ── Embedder (lazy-loaded singleton) ────────────────────────────────────────

_model = None

def _get_model():
    global _model
    if _model is None:
        # Quiet down sentence-transformers' chatty TQDM bars during embedding.
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        from sentence_transformers import SentenceTransformer
        print(f"  [classifier] loading embedding model {EMBEDDING_MODEL}...")
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _bug_text(issue: dict) -> str:
    """Compose a single text string for embedding a Jira bug."""
    fields = issue.get("fields", {}) or {}

    # Synthetic correction issues store the full bug text in
    # fields.description as a plain string (not the ADF dict that real
    # Jira tickets use). Short-circuit those so we don't lose the body.
    desc = fields.get("description")
    if isinstance(desc, str) and desc.strip():
        summary = fields.get("summary") or ""
        if desc.startswith(summary):
            return desc
        return f"{summary}\n{desc}".strip()

    # Real Jira issues: hand off to JiraClient's ADF/HTML extractor.
    from .jira_client import JiraClient
    summary = fields.get("summary") or ""
    body    = JiraClient.extract_text(issue) or ""
    if body.startswith(summary):
        return body
    return f"{summary}\n{body}".strip()


# ── Index build (one-time) ──────────────────────────────────────────────────

def build_index(
    issues: list,
    out_path: Path = DEFAULT_INDEX_PATH,
) -> dict:
    """
    Embed every labelled issue and save the embeddings + metadata to disk.

    Returns a dict summary: counts per label and skipped reasons.
    """
    from .jira_client import JiraClient

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    texts:      list[str] = []
    labels:     list[str] = []
    keys:       list[str] = []
    assignees:  list[str] = []
    priorities: list[str] = []
    skipped: dict[str, int] = {"no_component": 0, "unmapped_component": 0, "no_text": 0}

    for issue in issues:
        comp = JiraClient.extract_component(issue)
        if not comp:
            skipped["no_component"] += 1
            continue
        label = COMPONENT_TO_LABEL.get(comp)
        if label is None:
            skipped["unmapped_component"] += 1
            continue
        text = _bug_text(issue)
        if not text.strip():
            skipped["no_text"] += 1
            continue
        texts.append(text)
        labels.append(label)
        keys.append(issue.get("key") or "")
        assignees.append(JiraClient.extract_assignee(issue) or "")
        priorities.append(JiraClient.extract_priority(issue) or "Unknown")

    if not texts:
        raise RuntimeError(
            "No usable training examples — every issue was skipped. "
            f"Skip reasons: {skipped}"
        )

    print(f"  [classifier] embedding {len(texts)} labelled bugs...")
    model = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,  # makes cosine = dot product
    ).astype(np.float32)

    np.savez_compressed(
        out_path,
        embeddings = embeddings,
        labels     = np.array(labels),
        keys       = np.array(keys),
        texts      = np.array(texts),         # for validation / debugging
        assignees  = np.array(assignees),     # for owner suggestion roster
        priorities = np.array(priorities),    # for triage similar-bug voting
    )

    # ── Train and persist the LogReg classifier alongside the index ────────
    # We use this at predict-time, not just for validation. LogReg with
    # class_weight='balanced' lifted small-class F1 by 10+ points in
    # leave-one-out testing; we want production to use it.
    print(f"  [classifier] training LogReg on {len(labels)} labelled bugs...")
    from sklearn.linear_model import LogisticRegression
    import pickle
    logreg = LogisticRegression(
        class_weight = "balanced",
        max_iter     = 2000,
        C            = 1.0,
    )
    logreg.fit(embeddings, np.array(labels))
    logreg_path = out_path.parent / (out_path.stem + "_logreg.pkl")
    with open(logreg_path, "wb") as f:
        pickle.dump(logreg, f)
    print(f"  [classifier] LogReg saved → {logreg_path}")

    # ── Team-roster derivation ─────────────────────────────────────────────
    # For each component, who has actually been assigned bugs on it?
    # This is the "who's on the team" data Jira doesn't expose directly —
    # we derive it from authoritative assignee history. Filtered to people
    # with at least MIN_ROSTER_BUGS assignments so one-off contributors
    # don't pollute the routing pool, and with known managers stripped so
    # the owner sub-agent doesn't suggest them for individual bugs.
    from collections import Counter
    from .team_config import MANAGER_NAMES
    MIN_ROSTER_BUGS = 2
    roster: dict[str, list] = {}
    for label, assignee in zip(labels, assignees):
        if not assignee:
            continue
        roster.setdefault(label, []).append(assignee)
    roster_filtered = {
        label: [
            {"name": name, "bug_count": count}
            for name, count in Counter(names).most_common()
            if count >= MIN_ROSTER_BUGS and name not in MANAGER_NAMES
        ]
        for label, names in roster.items()
    }
    roster_path = out_path.parent / (out_path.stem + "_team_roster.json")
    import json
    with open(roster_path, "w") as f:
        json.dump(roster_filtered, f, indent=2)
    print(f"  [classifier] team roster saved → {roster_path}")
    for label, members in roster_filtered.items():
        print(f"    {label}: {len(members)} engineers ({', '.join(m['name'] for m in members[:5])}{'...' if len(members) > 5 else ''})")

    # Quick per-class report
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    print(f"  [classifier] index saved → {out_path}")
    print(f"  [classifier] per-class counts: {counts}")
    print(f"  [classifier] skipped: {skipped}")

    return {
        "out_path": str(out_path),
        "n_total":  len(labels),
        "counts":   counts,
        "skipped":  skipped,
    }


# ── Index load + predict ────────────────────────────────────────────────────

class EmbeddingClassifier:
    """
    Loads a cached embedding index and predicts components for new bugs.
    Intended to be built once at startup and reused across many predict calls.
    """

    def __init__(self, index_path: Path = DEFAULT_INDEX_PATH) -> None:
        index_path = Path(index_path)
        if not index_path.exists():
            raise FileNotFoundError(
                f"No embedding index at {index_path}. "
                f"Run `python3 build_embedding_index.py` first."
            )
        data = np.load(index_path, allow_pickle=False)
        self.embeddings: np.ndarray = data["embeddings"]   # shape (N, dim)
        self.labels:     np.ndarray = data["labels"]       # shape (N,)
        self.keys:       np.ndarray = data["keys"]         # shape (N,)
        # Optional fields only present in newer indexes. Predict-time code
        # only needs labels + embeddings; the rest power similarity/owner.
        self.texts:      Optional[np.ndarray] = data["texts"]      if "texts"      in data.files else None
        self.assignees:  Optional[np.ndarray] = data["assignees"]  if "assignees"  in data.files else None
        self.priorities: Optional[np.ndarray] = data["priorities"] if "priorities" in data.files else None
        self.n, self.dim = self.embeddings.shape

        # Try to load the trained LogReg model alongside the index. If it
        # isn't there (older index), predict() falls back to weighted k-NN.
        self.logreg = None
        logreg_path = index_path.parent / (index_path.stem + "_logreg.pkl")
        if logreg_path.exists():
            import pickle
            with open(logreg_path, "rb") as f:
                self.logreg = pickle.load(f)

        # Load the team roster (component → list of {name, bug_count}).
        self.team_roster: dict = {}
        roster_path = index_path.parent / (index_path.stem + "_team_roster.json")
        if roster_path.exists():
            import json
            with open(roster_path) as f:
                self.team_roster = json.load(f)

        print(
            f"  [classifier] loaded index — {self.n} bugs, "
            f"dim={self.dim}, classes={sorted(set(self.labels.tolist()))}, "
            f"logreg={'yes' if self.logreg is not None else 'no'}, "
            f"roster_teams={list(self.team_roster.keys())}"
        )

    # ── Production prediction (LogReg with Claude fallback on borderline) ──
    def predict(self, text: str, use_claude_fallback: bool = True) -> ClassificationResult:
        """
        Classify a new (unseen) bug.

        Hybrid strategy:
          1. Embed + LogReg gives a probability distribution over components.
          2. If LogReg's top probability is ≥ HYBRID_CLAUDE_FALLBACK_THRESHOLD,
             return LogReg's verdict — fast path, ~7ms total.
          3. Otherwise call Claude with the focused component prompt — slow
             path (~6s) but captures Claude's small per-class edge on
             borderline cases (especially BE_Labs and Backend).
          4. If LogReg's confidence is below CONFIDENCE_THRESHOLD even after
             the fallback, route to "bugs" (manual triage).

        Setting use_claude_fallback=False forces the fast LogReg-only path.
        Useful for unit tests, batch jobs, or when network/Claude is down.
        """
        model = _get_model()
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]

        # Always compute neighbours so the caller has interpretable
        # "here's why" data alongside the LogReg verdict.
        sims = self.embeddings @ q
        top_idx = np.argpartition(-sims, kth=min(TOP_K, self.n - 1))[:TOP_K]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        top_neighbours = [
            (str(self.keys[i]), str(self.labels[i]), float(sims[i]))
            for i in top_idx
        ]

        if self.logreg is None:
            # No trained model yet — fall back to weighted k-NN.
            return self._predict_knn(q, top_neighbours)

        proba = self.logreg.predict_proba(q.reshape(1, -1))[0]
        classes = list(self.logreg.classes_)
        winner_idx = int(np.argmax(proba))
        winner = classes[winner_idx]
        confidence = float(proba[winner_idx])
        proba_dict = {c: float(p) for c, p in zip(classes, proba)}

        # ── Fast path: LogReg is confident ────────────────────────────────
        if confidence >= HYBRID_CLAUDE_FALLBACK_THRESHOLD or not use_claude_fallback:
            if confidence < CONFIDENCE_THRESHOLD:
                return ClassificationResult(
                    component         = "bugs",
                    confidence        = confidence,
                    method            = "logreg-low-conf",
                    top_neighbours    = top_neighbours,
                    fell_back_to_bugs = True,
                    probabilities     = proba_dict,
                )
            return ClassificationResult(
                component         = winner,
                confidence        = confidence,
                method            = "logreg",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = False,
                probabilities     = proba_dict,
            )

        # ── Slow path: LogReg is borderline → ask Claude with skill files ─
        # Pass the top-3 candidates so Claude gets architecture context
        # (the skill files for those teams) instead of generic boilerplate.
        top3_candidates = [c for c, _ in sorted(proba_dict.items(), key=lambda kv: -kv[1])[:3]]
        claude_verdict, claude_reasoning = _classify_with_claude(
            text,
            top_candidates = top3_candidates,
            probabilities  = proba_dict,
        )
        if claude_verdict is None:
            # Claude failed — use LogReg's verdict, mark provenance.
            if confidence < CONFIDENCE_THRESHOLD:
                return ClassificationResult(
                    component         = "bugs",
                    confidence        = confidence,
                    method            = "logreg-borderline-claude-failed",
                    top_neighbours    = top_neighbours,
                    fell_back_to_bugs = True,
                    probabilities     = proba_dict,
                )
            return ClassificationResult(
                component         = winner,
                confidence        = confidence,
                method            = f"logreg-claude-unreachable (logreg={winner}@{confidence:.2f})",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = False,
                probabilities     = proba_dict,
            )

        # Claude returned a verdict.
        return ClassificationResult(
            component         = claude_verdict,
            confidence        = confidence,    # the LogReg confidence that triggered the fallback
            method            = f"claude-fallback (logreg suggested {winner}@{confidence:.2f})",
            top_neighbours    = top_neighbours,
            fell_back_to_bugs = (claude_verdict == "bugs"),
            reasoning         = claude_reasoning,
            probabilities     = proba_dict,
        )

    def _predict_knn(self, q: np.ndarray, top_neighbours: list) -> ClassificationResult:
        """Weighted k-NN fallback when no LogReg model is available."""
        top1_sim   = top_neighbours[0][2]
        top1_label = top_neighbours[0][1]
        if top1_sim >= HIGH_CONFIDENCE_THRESHOLD:
            return ClassificationResult(
                component         = top1_label,
                confidence        = float(top1_sim),
                method            = "k=1-exact-knn-fallback",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = False,
            )
        votes: dict[str, float] = {}
        total_w = 0.0
        for _key, label, sim in top_neighbours:
            w = max(sim, 0.0) ** 2
            votes[label] = votes.get(label, 0.0) + w
            total_w += w
        if total_w == 0:
            return ClassificationResult("bugs", 0.0, "knn-no-positive", top_neighbours, True)
        winner = max(votes, key=lambda k: votes[k])
        share  = votes[winner] / total_w
        if share < CONFIDENCE_THRESHOLD:
            return ClassificationResult("bugs", share, "knn-low-conf", top_neighbours, True)
        return ClassificationResult(winner, share, "knn-weighted-vote", top_neighbours, False)

    def _predict_knn_legacy(self, text: str) -> ClassificationResult:
        """Legacy weighted-k-NN predict; kept only for the validator's
        head-to-head comparison. Production calls predict() instead."""
        model = _get_model()
        q = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]
        sims = self.embeddings @ q
        top_idx = np.argpartition(-sims, kth=min(TOP_K, self.n - 1))[:TOP_K]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        top_neighbours = [
            (str(self.keys[i]), str(self.labels[i]), float(sims[i]))
            for i in top_idx
        ]
        return self._predict_knn(q, top_neighbours)

    def predict_proba_loo(self, exclude_index: int, all_classes: list) -> np.ndarray:
        """
        Leave-one-out variant that returns a full probability vector over
        `all_classes`. Used by the ensemble validator to average against
        LogReg's predict_proba output.

        Probabilities come from normalising the weighted-vote shares.
        """
        sims = self.embeddings @ self.embeddings[exclude_index]
        sims[exclude_index] = -np.inf

        top_idx = np.argpartition(-sims, kth=min(TOP_K, self.n - 1))[:TOP_K]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        votes = {c: 0.0 for c in all_classes}
        total_w = 0.0
        for idx in top_idx:
            label = str(self.labels[idx])
            if label not in votes:
                continue
            w = max(float(sims[idx]), 0.0) ** 2
            votes[label] += w
            total_w += w

        if total_w == 0:
            return np.full(len(all_classes), 1.0 / len(all_classes))
        return np.array([votes[c] / total_w for c in all_classes])

    def predict_leave_one_out(self, exclude_index: int) -> ClassificationResult:
        """
        For validation: predict the label of training row `exclude_index`
        using the rest of the corpus. Same logic as `predict()` but masks
        the held-out row so it can't vote for itself.
        """
        q = self.embeddings[exclude_index]

        # Mask the held-out row by setting its similarity to -inf below.
        sims = self.embeddings @ q
        sims[exclude_index] = -np.inf

        top_idx = np.argpartition(-sims, kth=min(TOP_K, self.n - 1))[:TOP_K]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        top_neighbours = [
            (str(self.keys[i]), str(self.labels[i]), float(sims[i]))
            for i in top_idx
        ]

        top1_sim   = top_neighbours[0][2]
        top1_label = top_neighbours[0][1]
        if top1_sim >= HIGH_CONFIDENCE_THRESHOLD:
            return ClassificationResult(
                component         = top1_label,
                confidence        = float(top1_sim),
                method            = "k=1-exact",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = False,
            )

        votes: dict[str, float] = {}
        total_w = 0.0
        for _key, label, sim in top_neighbours:
            w = max(sim, 0.0) ** 2
            votes[label] = votes.get(label, 0.0) + w
            total_w += w

        if total_w == 0:
            return ClassificationResult(
                component         = "bugs",
                confidence        = 0.0,
                method            = "no-positive-neighbours",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = True,
            )

        winner_label = max(votes, key=lambda k: votes[k])
        winner_share = votes[winner_label] / total_w

        if winner_share < CONFIDENCE_THRESHOLD:
            return ClassificationResult(
                component         = "bugs",
                confidence        = float(winner_share),
                method            = f"k={TOP_K}-weighted-vote-low-conf",
                top_neighbours    = top_neighbours,
                fell_back_to_bugs = True,
            )

        return ClassificationResult(
            component         = winner_label,
            confidence        = float(winner_share),
            method            = f"k={TOP_K}-weighted-vote",
            top_neighbours    = top_neighbours,
            fell_back_to_bugs = False,
        )
