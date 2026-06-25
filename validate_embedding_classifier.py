#!/usr/bin/env python3
"""
validate_embedding_classifier.py — Leave-one-out accuracy + latency report.

Compares four classifiers on the same corpus:
  1. Rule-based regex baseline (the existing _extract_component)
  2. Embedding k-NN (this iteration's first model)
  3. Logistic regression over embeddings
  4. Ensemble: average of k-NN probabilities and LogReg probabilities

Uses leave-one-out cross-validation throughout so every prediction is
honest: the bug being scored cannot appear in the training data used to
predict it.

Also measures per-prediction latency for an end-to-end fresh bug — the
real-world cost of running the classifier on an unseen bug, including
the sentence-transformer embedding pass.

Usage:
    python3 validate_embedding_classifier.py
"""

from __future__ import annotations

import time
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from sklearn.linear_model     import LogisticRegression
from sklearn.model_selection  import LeaveOneOut, cross_val_predict

from src.embedding_classifier import (
    EmbeddingClassifier,
    DEFAULT_INDEX_PATH,
    COMPONENT_TO_LABEL,
    CONFIDENCE_THRESHOLD,
    _get_model,
)
from src.agent_parser import _extract_component as rb_extract_component

# Map the rule-based classifier's team-label vocabulary to the Jira-component
# vocabulary used by the embedding labels, so the two sets are comparable.
TEAM_TO_COMPONENT = {
    "BE_Flippi":  "Backend",
    "BE_Labs":    "Backend-Labs",
    "DS":         "DS",
    "UI":         "UI",
    "Immersive":  "immersive",
    "bugs":       "bugs",
}


def _eval_predictions(actuals: list, predictions: list, classes: list) -> dict:
    """Compute overall + per-class metrics + confusion matrix for one classifier."""
    n = len(actuals)
    correct = sum(1 for a, p in zip(actuals, predictions) if a == p)
    bugs_fallback = sum(1 for p in predictions if p == "bugs")

    per_class = {c: {"tp": 0, "fn": 0, "fp": 0, "n_actual": 0} for c in classes}
    confusion: dict[str, dict[str, int]] = {a: defaultdict(int) for a in classes}

    for a, p in zip(actuals, predictions):
        per_class[a]["n_actual"] += 1
        confusion[a][p] += 1
        if a == p:
            per_class[a]["tp"] += 1
        else:
            per_class[a]["fn"] += 1
            if p in per_class:
                per_class[p]["fp"] += 1

    return {
        "n":             n,
        "correct":       correct,
        "accuracy":      correct / n if n else 0.0,
        "bugs_fallback": bugs_fallback,
        "per_class":     per_class,
        "confusion":     confusion,
    }


def _print_per_class(name: str, per_class: dict, classes: list) -> None:
    print(f"  Per-class metrics — {name}")
    print(f"    {'class':14s}  {'support':>7s}   {'precision':>10s} {'recall':>8s} {'F1':>6s}")
    for c in classes:
        st = per_class[c]
        tp, fp, fn = st["tp"], st["fp"], st["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        print(f"    {c:14s}  {st['n_actual']:7d}   {precision:>10.1%} {recall:>8.1%} {f1:>6.2f}")
    print()


def main() -> None:
    print(f"Loading index from {DEFAULT_INDEX_PATH}...")
    clf = EmbeddingClassifier()

    n = clf.n
    # All classes the embedding classifier knows about (not including "bugs",
    # which is a low-confidence fallback, not a real label).
    classes = sorted({lbl for lbl in COMPONENT_TO_LABEL.values() if lbl})

    if clf.texts is None:
        raise SystemExit(
            "This index doesn't have texts stored — rebuild with "
            "`python3 build_embedding_index.py` first."
        )

    actuals = [str(clf.labels[i]) for i in range(n)]

    # ── 1. Rule-based baseline ─────────────────────────────────────────────
    print(f"[1/4] Rule-based regex baseline on {n} bugs...")
    t0 = time.time()
    rb_preds = []
    for i in range(n):
        txt = str(clf.texts[i])
        title = txt.split("\n", 1)[0]
        rb_label = rb_extract_component(txt, title)
        rb_preds.append(TEAM_TO_COMPONENT.get(rb_label, "bugs"))
    rb_time = time.time() - t0
    print(f"      done in {rb_time:.2f}s ({rb_time/n*1000:.2f}ms per bug)")

    # ── 2. Embedding k-NN LOO ──────────────────────────────────────────────
    print(f"[2/4] Embedding k-NN (leave-one-out)...")
    t0 = time.time()
    knn_preds: list = []
    knn_method_counts: dict[str, int] = defaultdict(int)
    for i in range(n):
        r = clf.predict_leave_one_out(exclude_index=i)
        knn_preds.append(r.component)
        knn_method_counts[r.method] += 1
    knn_time = time.time() - t0
    print(f"      done in {knn_time:.2f}s ({knn_time/n*1000:.2f}ms per bug, excludes embedding step)")

    # ── 3. Logistic regression LOO ─────────────────────────────────────────
    print(f"[3/4] Logistic regression (leave-one-out)...")
    t0 = time.time()
    logreg = LogisticRegression(
        class_weight = "balanced",
        max_iter     = 2000,
        C            = 1.0,
        n_jobs       = -1,
    )
    # cross_val_predict with LeaveOneOut returns the prediction for each row
    # using a model trained on all other rows. Same idea as the k-NN LOO.
    lr_proba = cross_val_predict(
        logreg, clf.embeddings, np.array(actuals),
        cv     = LeaveOneOut(),
        method = "predict_proba",
        n_jobs = -1,
    )
    # logreg.classes_ isn't populated when we use cross_val_predict (each fold
    # has its own model). Fit once on the full data just to learn the class order.
    logreg.fit(clf.embeddings, np.array(actuals))
    lr_classes = list(logreg.classes_)
    lr_preds = [lr_classes[i] for i in np.argmax(lr_proba, axis=1)]
    lr_time = time.time() - t0
    print(f"      done in {lr_time:.2f}s ({lr_time/n*1000:.2f}ms per bug)")

    # ── 4. Ensemble: average k-NN probas + LogReg probas ───────────────────
    print(f"[4/4] Ensemble (k-NN probas + LogReg probas, averaged)...")
    t0 = time.time()
    ensemble_preds = []
    for i in range(n):
        knn_proba = clf.predict_proba_loo(exclude_index=i, all_classes=lr_classes)
        avg = (knn_proba + lr_proba[i]) / 2.0
        winner_idx = int(np.argmax(avg))
        winner = lr_classes[winner_idx]
        winner_share = float(avg[winner_idx])
        if winner_share < CONFIDENCE_THRESHOLD:
            ensemble_preds.append("bugs")
        else:
            ensemble_preds.append(winner)
    ens_time = time.time() - t0
    print(f"      done in {ens_time:.2f}s ({ens_time/n*1000:.2f}ms per bug)")
    print()

    # ── Score each ─────────────────────────────────────────────────────────
    res_rb  = _eval_predictions(actuals, rb_preds,       classes)
    res_knn = _eval_predictions(actuals, knn_preds,      classes)
    res_lr  = _eval_predictions(actuals, lr_preds,       classes)
    res_ens = _eval_predictions(actuals, ensemble_preds, classes)

    # ── Headline ──────────────────────────────────────────────────────────
    print("═" * 76)
    print(f"  Leave-one-out accuracy on {n} labelled bugs")
    print("═" * 76)
    line = "  {:<32s}  {:>12s}   {:>11s}"
    print(line.format("Classifier", "Accuracy", "bugs fallback"))
    print(f"  {'-'*32}  {'-'*12}   {'-'*11}")
    print(line.format("Rule-based regex baseline", f"{res_rb['accuracy']:.1%}",
                      f"{res_rb['bugs_fallback']/n:.1%}"))
    print(line.format("Embedding k-NN (threshold=0.40)", f"{res_knn['accuracy']:.1%}",
                      f"{res_knn['bugs_fallback']/n:.1%}"))
    print(line.format("Logistic regression",              f"{res_lr['accuracy']:.1%}",
                      f"{res_lr['bugs_fallback']/n:.1%}"))
    print(line.format("Ensemble (k-NN + LogReg)",         f"{res_ens['accuracy']:.1%}",
                      f"{res_ens['bugs_fallback']/n:.1%}"))
    print()

    # ── Per-class breakdown for the winning ensemble ──────────────────────
    _print_per_class("Embedding k-NN",          res_knn["per_class"], classes)
    _print_per_class("Logistic regression",     res_lr["per_class"],  classes)
    _print_per_class("Ensemble (k-NN+LogReg)",  res_ens["per_class"], classes)

    # ── Confusion matrix for the ensemble (best classifier) ───────────────
    print("  Confusion matrix — Ensemble (rows = actual, cols = predicted)")
    all_pred = sorted({p for row in res_ens["confusion"].values() for p in row})
    col_w = max(8, max((len(c) for c in all_pred), default=8))
    header_cells = " ".join(c[:col_w].rjust(col_w) for c in all_pred)
    print("    " + " " * 14 + "  " + header_cells)
    for actual in classes:
        row = res_ens["confusion"][actual]
        cells = " ".join(str(row.get(p, 0)).rjust(col_w) for p in all_pred)
        print(f"    {actual:14s}  {cells}")
    print()

    # ── End-to-end latency on a fresh bug ─────────────────────────────────
    print("─" * 76)
    print("  End-to-end latency on a FRESH bug (includes embedding step)")
    print("─" * 76)

    # Load the model once so it's not part of the timed path.
    model = _get_model()
    sample_text = str(clf.texts[0])

    # Warm-up call so torch JIT / GPU dispatch doesn't show up in the average.
    _ = model.encode([sample_text], normalize_embeddings=True)

    N_TRIALS = 20
    times_embed = []
    times_total = []
    for _ in range(N_TRIALS):
        t = time.time()
        q = model.encode([sample_text], normalize_embeddings=True).astype(np.float32)[0]
        t_embed = time.time() - t

        t = time.time()
        sims = clf.embeddings @ q
        top_idx = np.argpartition(-sims, kth=4)[:5]
        # ensemble step
        knn_p = np.zeros(len(lr_classes))
        for j, idx in enumerate(top_idx):
            label = str(clf.labels[idx])
            if label in lr_classes:
                w = max(float(sims[idx]), 0.0) ** 2
                knn_p[lr_classes.index(label)] += w
        if knn_p.sum() > 0:
            knn_p /= knn_p.sum()
        lr_p = logreg.predict_proba(q.reshape(1, -1))[0]
        avg = (knn_p + lr_p) / 2.0
        _winner = lr_classes[int(np.argmax(avg))]
        t_predict = time.time() - t

        times_embed.append(t_embed)
        times_total.append(t_embed + t_predict)

    embed_ms = 1000 * np.median(times_embed)
    total_ms = 1000 * np.median(times_total)
    print(f"  Embedding the bug:                {embed_ms:.1f}ms (median of {N_TRIALS} trials)")
    print(f"  Full ensemble prediction:         {total_ms:.1f}ms (median of {N_TRIALS} trials)")
    print()
    print(f"  Comparison:")
    print(f"    Rule-based regex (per bug):     ~{rb_time/n*1000:.2f}ms")
    print(f"    Embedding ensemble (per bug):   ~{total_ms:.1f}ms")
    print(f"    Multi-agent LLM parser (per bug): ~10–20s (current pipeline)")
    print()
    print("═" * 76)


if __name__ == "__main__":
    main()
