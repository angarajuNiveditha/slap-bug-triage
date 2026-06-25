#!/usr/bin/env python3
"""
validate_claude_component.py — Measure Claude's component-classification
accuracy on the same 564-bug corpus we measured LogReg against.

Methodology mirrors the LogReg validator:
- Iterate every bug in data/embedding_index.npz
- Send its title+description to Claude via a focused prompt
- Compare Claude's predicted component to the actual Jira label
- Report overall + per-class precision/recall/F1

The prompt is intentionally focused (only asks for component, not the
whole BugReport) so we measure Claude at its best on this single task.
If Claude can't beat 66.8% with a focused prompt + the same routing
ladder LogReg learned from, it won't beat it in the heavier full-parser
prompt either.

Runs N_WORKERS calls in parallel via threads (each Claude call is a
separate subprocess, no shared state).

Usage:
    python3 validate_claude_component.py
    python3 validate_claude_component.py --workers 2
    python3 validate_claude_component.py --limit 100         # quick sanity run
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from src.claude_cli          import call_claude
from src.embedding_classifier import EmbeddingClassifier, DEFAULT_INDEX_PATH


# A focused prompt — Claude's only job is to pick one of the six labels.
# The team descriptions mirror the production parser prompt so this is a
# fair "if we ask Claude to do component classification alone" test.
PROMPT_TEMPLATE = """You are the SLAP triage component classifier. Pick ONE component for the bug below.

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
   • Edison in BE_Labs context ("styledrops edison", "notifying edison")
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

VALID_COMPONENTS = {"Backend", "Backend-Labs", "DS", "UI", "immersive", "bugs"}


def classify_one(text: str) -> tuple[str, float]:
    """Return (predicted_component_or_None, seconds_taken)."""
    t = time.time()
    prompt = PROMPT_TEMPLATE.format(text=(text or "")[:3500])
    try:
        response = call_claude(prompt, expect_json=True, timeout=60)
        elapsed = time.time() - t
        if isinstance(response, dict):
            comp = str(response.get("component", "")).strip()
            if comp in VALID_COMPONENTS:
                return comp, elapsed
        return None, elapsed
    except Exception:
        return None, time.time() - t


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3, help="Parallel Claude calls")
    parser.add_argument("--limit",   type=int, default=0,  help="Cap on bugs (0 = all)")
    args = parser.parse_args()

    print(f"Loading index from {DEFAULT_INDEX_PATH}...")
    clf = EmbeddingClassifier()
    if clf.texts is None:
        raise SystemExit("Index has no `texts` field — rebuild with `python3 build_embedding_index.py`.")

    n = clf.n if args.limit == 0 else min(args.limit, clf.n)
    actuals = [str(clf.labels[i]) for i in range(n)]
    texts   = [str(clf.texts[i])  for i in range(n)]

    print(f"Running Claude component classifier on {n} bugs with {args.workers} parallel workers...")
    print(f"Expected runtime: ~{n*5/args.workers/60:.1f} min (assuming ~5s per call).")
    print()

    predictions:  list = [None] * n
    call_times:   list = [None] * n
    progress_lock = Lock()
    done = {"count": 0}
    t_start = time.time()

    def worker(i: int):
        comp, dt = classify_one(texts[i])
        with progress_lock:
            predictions[i] = comp
            call_times[i]  = dt
            done["count"]  += 1
            if done["count"] % 25 == 0 or done["count"] == n:
                elapsed = time.time() - t_start
                eta = elapsed / done["count"] * (n - done["count"])
                print(f"  {done['count']:4d}/{n} done   "
                      f"elapsed {elapsed/60:.1f}m   eta {eta/60:.1f}m   "
                      f"avg {elapsed/done['count']:.1f}s/call")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(worker, range(n)))

    total_elapsed = time.time() - t_start
    print()
    print(f"All done in {total_elapsed/60:.1f} min.")
    print()

    # ── Scoring ────────────────────────────────────────────────────────────
    n_correct = sum(1 for a, p in zip(actuals, predictions) if a == p)
    n_committed = sum(1 for p in predictions if p is not None)
    n_failed = sum(1 for p in predictions if p is None)
    n_bugs_fallback = sum(1 for p in predictions if p == "bugs")

    classes = sorted({a for a in actuals})
    per_class = {c: {"tp": 0, "fn": 0, "fp": 0, "n": 0} for c in classes}
    confusion: dict[str, dict[str, int]] = {a: defaultdict(int) for a in classes}

    for a, p in zip(actuals, predictions):
        if p is None:
            continue
        per_class[a]["n"] += 1
        confusion[a][p] += 1
        if a == p:
            per_class[a]["tp"] += 1
        else:
            per_class[a]["fn"] += 1
            if p in per_class:
                per_class[p]["fp"] += 1

    print("═" * 76)
    print(f"  Claude component-classifier — leave-one-bug-out is not needed (no fitting)")
    print(f"  Corpus: same {n} bugs as the LogReg validator")
    print("═" * 76)
    print()
    print(f"  Accuracy:                   {n_correct}/{n} = {n_correct/n:.1%}")
    print(f"  Routed to 'bugs':           {n_bugs_fallback} ({n_bugs_fallback/n:.1%})")
    print(f"  Failed calls (no response): {n_failed}")
    print(f"  Average latency per call:   {np.median([t for t in call_times if t]):.2f}s (median)")
    print()

    print("  Per-class metrics")
    print(f"    {'class':14s}  {'support':>7s}   {'precision':>10s} {'recall':>8s} {'F1':>6s}")
    for c in classes:
        st = per_class[c]
        tp, fp, fn = st["tp"], st["fp"], st["fn"]
        p_score  = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r_score  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1       = 2 * p_score * r_score / (p_score + r_score) if (p_score + r_score) > 0 else 0.0
        print(f"    {c:14s}  {st['n']:7d}   {p_score:>10.1%} {r_score:>8.1%} {f1:>6.2f}")
    print()

    # Confusion matrix
    all_pred = sorted({p for row in confusion.values() for p in row})
    col_w = max(8, max((len(c) for c in all_pred), default=8))
    print("  Confusion matrix — rows = actual, cols = predicted")
    print("    " + " " * 14 + "  " + " ".join(c[:col_w].rjust(col_w) for c in all_pred))
    for actual in classes:
        row = confusion[actual]
        cells = " ".join(str(row.get(p, 0)).rjust(col_w) for p in all_pred)
        print(f"    {actual:14s}  {cells}")
    print()

    print("─" * 76)
    print("  Head-to-head with LogReg (from validate_embedding_classifier.py):")
    print(f"    Claude (focused prompt):    {n_correct/n:.1%}")
    print(f"    LogReg on embeddings:        66.8%")
    print(f"    Rule-based regex:            27.7%")
    print("─" * 76)


if __name__ == "__main__":
    main()
