#!/usr/bin/env python3
"""
validate_hybrid_classifier.py — Measure the *realistic* production accuracy.

The realistic hybrid pipeline (as wired into HostAgent today):
  1. LogReg predicts. If top-class probability ≥ HYBRID_CLAUDE_FALLBACK_THRESHOLD
     (0.50), use LogReg's verdict — fast, free, deterministic.
  2. Otherwise, call Claude with the skill-aware prompt: top-3 candidate teams'
     skill files + per-team repo skills loaded into context. Use Claude's
     verdict.

This validator measures that exact behaviour on the 564-bug labelled corpus.
LogReg is trained leave-one-out so each prediction is honest. Claude calls
fire only for the borderline cases — typically 15-30% of bugs.

Outputs a head-to-head:
  - Pure LogReg LOO accuracy (the 66.8% baseline)
  - Pure Claude without skills (the earlier 65.1% measurement)
  - **Hybrid LogReg + Claude+skills fallback** (this script's headline)

And per-class metrics + a breakdown of which path each bug took.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import numpy as np
from dotenv import load_dotenv
load_dotenv(override=True)

from sklearn.linear_model     import LogisticRegression
from sklearn.model_selection  import LeaveOneOut, cross_val_predict

from src.embedding_classifier import (
    EmbeddingClassifier,
    HYBRID_CLAUDE_FALLBACK_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    _classify_with_claude,
    _load_top_skills,
)


def main() -> None:
    print("Loading embedding index...")
    clf = EmbeddingClassifier()
    if clf.texts is None:
        raise SystemExit("Index lacks `texts` — rebuild with build_embedding_index.py")

    n = clf.n
    classes_sorted = sorted(set(clf.labels.tolist()))
    actuals = [str(clf.labels[i]) for i in range(n)]
    print(f"  {n} bugs, classes={classes_sorted}")
    print(f"  HYBRID_CLAUDE_FALLBACK_THRESHOLD = {HYBRID_CLAUDE_FALLBACK_THRESHOLD}")
    print(f"  CONFIDENCE_THRESHOLD             = {CONFIDENCE_THRESHOLD}")
    print()

    # ── Step 1: LogReg LOO probabilities ──────────────────────────────────
    print("[1/3] Computing LogReg leave-one-out probabilities...")
    t0 = time.time()
    logreg = LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0)
    lr_proba = cross_val_predict(
        logreg, clf.embeddings, np.array(actuals),
        cv     = LeaveOneOut(),
        method = "predict_proba",
    )
    logreg.fit(clf.embeddings, np.array(actuals))
    lr_classes = list(logreg.classes_)
    lr_top_idx = np.argmax(lr_proba, axis=1)
    lr_top_label = [lr_classes[i] for i in lr_top_idx]
    lr_top_prob  = lr_proba[np.arange(n), lr_top_idx]
    print(f"      done in {time.time()-t0:.2f}s")
    print()

    # ── Step 2: identify which bugs trigger the Claude fallback ──────────
    borderline_idx = [
        i for i in range(n)
        if lr_top_prob[i] < HYBRID_CLAUDE_FALLBACK_THRESHOLD
    ]
    print(f"[2/3] {len(borderline_idx)}/{n} bugs ({len(borderline_idx)/n:.1%}) "
          f"have LogReg confidence < {HYBRID_CLAUDE_FALLBACK_THRESHOLD} → "
          f"will go through Claude+skills fallback.")
    print()

    # ── Step 3: Claude+skills on the borderline subset, in parallel ──────
    print(f"[3/3] Calling Claude+skills on the {len(borderline_idx)} borderline bugs (3 workers)...")
    claude_verdicts: dict[int, str] = {}
    lock = Lock()
    progress = {"done": 0}
    t0 = time.time()

    def worker(i: int):
        text = str(clf.texts[i])
        # Build the top-3 candidates list from LogReg's probabilities for this bug
        bug_proba = lr_proba[i]
        ranked = sorted(zip(lr_classes, bug_proba), key=lambda kv: -kv[1])
        top_candidates = [c for c, _ in ranked[:3]]
        proba_dict = {c: float(p) for c, p in zip(lr_classes, bug_proba)}

        verdict = _classify_with_claude(
            text,
            top_candidates = top_candidates,
            probabilities  = proba_dict,
        )
        with lock:
            claude_verdicts[i] = verdict
            progress["done"] += 1
            if progress["done"] % 20 == 0 or progress["done"] == len(borderline_idx):
                elapsed = time.time() - t0
                eta = elapsed / progress["done"] * (len(borderline_idx) - progress["done"])
                print(f"      {progress['done']:4d}/{len(borderline_idx)}  "
                      f"elapsed {elapsed/60:.1f}m  eta {eta/60:.1f}m")

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(worker, borderline_idx))

    print(f"      done in {(time.time()-t0)/60:.1f}m")
    print()

    # ── Compose the hybrid predictions ────────────────────────────────────
    hybrid_preds: list = []
    paths: list = []         # which path each bug took: "logreg" or "claude"
    for i in range(n):
        if i in claude_verdicts and claude_verdicts[i] is not None:
            hybrid_preds.append(claude_verdicts[i])
            paths.append("claude")
        elif i in claude_verdicts and claude_verdicts[i] is None:
            # Claude was supposed to be consulted but the call failed →
            # fall back to LogReg's verdict (consistent with the production
            # predict() code path).
            hybrid_preds.append(lr_top_label[i])
            paths.append("claude-failed→logreg")
        else:
            hybrid_preds.append(lr_top_label[i])
            paths.append("logreg")

    # ── Score ─────────────────────────────────────────────────────────────
    def score(preds: list) -> dict:
        correct = sum(1 for a, p in zip(actuals, preds) if a == p)
        per_class: dict = {c: {"tp": 0, "fn": 0, "fp": 0, "n": 0} for c in classes_sorted}
        for a, p in zip(actuals, preds):
            per_class[a]["n"] += 1
            if a == p:
                per_class[a]["tp"] += 1
            else:
                per_class[a]["fn"] += 1
                if p in per_class:
                    per_class[p]["fp"] += 1
        return {
            "correct":   correct,
            "n":         len(preds),
            "accuracy":  correct / len(preds),
            "per_class": per_class,
        }

    lr_only      = score(lr_top_label)
    hybrid_score = score(hybrid_preds)

    # Also score Claude's accuracy in isolation, on just the bugs it was called on
    claude_pred_subset  = []
    claude_actual_subset = []
    for i in borderline_idx:
        if claude_verdicts.get(i) is not None:
            claude_pred_subset.append(claude_verdicts[i])
            claude_actual_subset.append(actuals[i])
    claude_subset_correct = sum(1 for a, p in zip(claude_actual_subset, claude_pred_subset) if a == p)

    # LogReg's accuracy on the same borderline subset (for direct comparison)
    lr_subset_correct = sum(
        1 for i in borderline_idx if lr_top_label[i] == actuals[i]
    )

    # ── Report ────────────────────────────────────────────────────────────
    print("═" * 76)
    print(f"  HYBRID-CLASSIFIER VALIDATION — {n} bugs leave-one-out")
    print("═" * 76)
    print()
    print("  Headline accuracies:")
    print(f"    Pure LogReg LOO:                       {lr_only['accuracy']:.1%}  ({lr_only['correct']}/{n})")
    print(f"    HYBRID (LogReg + Claude+skills):       {hybrid_score['accuracy']:.1%}  ({hybrid_score['correct']}/{n})")
    delta = hybrid_score['accuracy'] - lr_only['accuracy']
    print(f"    Δ from LogReg → Hybrid:                {delta:+.1%}")
    print()
    print("  Path breakdown:")
    path_counts = Counter(paths)
    for path, cnt in sorted(path_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {path:24s} {cnt:5d} ({cnt/n:.1%})")
    print()
    if borderline_idx:
        print("  Borderline subset (bugs LogReg wasn't confident about):")
        print(f"    Subset size:                            {len(borderline_idx)}")
        print(f"    LogReg-only accuracy on subset:         {lr_subset_correct/len(borderline_idx):.1%}")
        if claude_actual_subset:
            print(f"    Claude+skills accuracy on subset:       {claude_subset_correct/len(claude_actual_subset):.1%}  "
                  f"(over {len(claude_actual_subset)} successful Claude calls)")
            claude_delta = (claude_subset_correct/len(claude_actual_subset)) - (lr_subset_correct/len(borderline_idx))
            print(f"    Claude+skills lift over LogReg:         {claude_delta:+.1%}  ← the real impact of the skill files")
    print()

    # ── Per-class for the hybrid ──────────────────────────────────────────
    print("  Hybrid per-class metrics:")
    print(f"    {'class':14s}  {'support':>7s}   {'precision':>10s} {'recall':>8s} {'F1':>6s}")
    for c in classes_sorted:
        st = hybrid_score["per_class"][c]
        tp, fp, fn = st["tp"], st["fp"], st["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        print(f"    {c:14s}  {st['n']:7d}   {precision:>10.1%} {recall:>8.1%} {f1:>6.2f}")
    print()
    print("═" * 76)


if __name__ == "__main__":
    main()
