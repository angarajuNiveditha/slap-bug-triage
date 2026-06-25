#!/usr/bin/env python3
"""
audit_backend_misclassifications.py — Manual-audit helper for the Backend class.

The hybrid validator showed Backend has F1=0.43, the worst of any class. This
script pulls every Backend-labelled bug LogReg LOO misclassified, with enough
context to manually decide WHY each one was wrong:

  - genuine model error (bug really is Backend, model failed)
  - label noise (bug is actually mis-labelled in Jira)
  - cross-team / ambiguous (defensible either way)

For each misclassified Backend bug, prints:
  - Jira key + title
  - Predicted class + full LogReg probability distribution
  - Top-3 nearest neighbours (their components)
  - First ~400 chars of the bug body

Writes both stdout and `audit_backend_misclassifications.md` for review.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
load_dotenv(override=True)

from sklearn.linear_model     import LogisticRegression
from sklearn.model_selection  import LeaveOneOut, cross_val_predict

from src.embedding_classifier import EmbeddingClassifier


def main() -> None:
    print("Loading index...")
    clf = EmbeddingClassifier()
    if clf.texts is None:
        raise SystemExit("Index lacks texts. Rebuild with build_embedding_index.py.")

    n = clf.n
    actuals = np.array([str(clf.labels[i]) for i in range(n)])

    print("Running LogReg leave-one-out...")
    t0 = time.time()
    logreg = LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0)
    lr_proba = cross_val_predict(
        logreg, clf.embeddings, actuals,
        cv=LeaveOneOut(), method="predict_proba",
    )
    logreg.fit(clf.embeddings, actuals)
    classes = list(logreg.classes_)
    predicted = np.array([classes[i] for i in np.argmax(lr_proba, axis=1)])
    print(f"  done in {time.time()-t0:.2f}s")
    print()

    # Identify misclassified Backend bugs
    backend_mask = actuals == "Backend"
    n_backend = int(backend_mask.sum())
    misclass_mask = backend_mask & (predicted != "Backend")
    misclass_idx = np.where(misclass_mask)[0]
    print(f"Backend bugs: {n_backend}")
    print(f"Correctly classified by LogReg: {int((backend_mask & (predicted == 'Backend')).sum())}")
    print(f"Misclassified: {len(misclass_idx)} ← these are the audit set")
    print()

    # Aggregate: what are misclassified Backend bugs being predicted as?
    where_they_went = Counter(predicted[misclass_idx])
    print("Where misclassified Backend bugs ended up:")
    for c, n_ in where_they_went.most_common():
        print(f"  Backend → {c}: {n_} ({n_/len(misclass_idx):.1%})")
    print()

    # Sort by LogReg confidence in the wrong class — i.e. the most confidently-wrong
    # predictions first (these are the hardest cases / clearest label-noise candidates).
    misclass_confidence = lr_proba[misclass_idx, np.argmax(lr_proba[misclass_idx], axis=1)]
    order = np.argsort(-misclass_confidence)
    sorted_misclass_idx = misclass_idx[order]

    # ── Write the audit document ───────────────────────────────────────
    out_path = Path("audit_backend_misclassifications.md")
    lines = []
    lines.append(f"# Backend misclassification audit\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"**{len(misclass_idx)} of {n_backend} Backend-labelled bugs** misclassified by LogReg LOO.\n")
    lines.append(f"## Where they went\n")
    for c, n_ in where_they_went.most_common():
        lines.append(f"- Backend → {c}: **{n_}** ({n_/len(misclass_idx):.1%})")
    lines.append("")
    lines.append("---\n")

    lines.append("## Per-bug audit list\n")
    lines.append("Sorted by LogReg confidence in the wrong class — most-confidently-wrong first.")
    lines.append("Each entry below has the title, the top-3 nearest historical neighbours, the")
    lines.append("full probability distribution, and the first ~400 chars of the body.\n")

    for rank, i in enumerate(sorted_misclass_idx, 1):
        key      = str(clf.keys[i])
        text     = str(clf.texts[i])
        title    = text.split("\n", 1)[0].strip()
        body     = text[len(title):].strip()[:450]
        pred     = predicted[i]
        proba    = lr_proba[i]

        # top-3 nearest neighbours from the embedding index (loo: exclude self)
        sims = clf.embeddings @ clf.embeddings[i]
        sims[i] = -np.inf
        top3_idx = np.argsort(-sims)[:3]
        neighbours = [
            (str(clf.keys[j]), str(clf.labels[j]), float(sims[j]))
            for j in top3_idx
        ]

        proba_str = " ".join(f"{c}={proba[ci]:.2f}" for ci, c in enumerate(classes))

        lines.append(f"### {rank}. `{key}` — Backend → predicted **{pred}**\n")
        lines.append(f"**Title:** {title}\n")
        lines.append(f"**Probabilities:** {proba_str}")
        lines.append("**Top-3 neighbours:**")
        for nk, nl, ns in neighbours:
            lines.append(f"- `{nk}` label=**{nl}** sim={ns:.3f}")
        lines.append("")
        lines.append("**Body excerpt:**")
        # Quote-wrap so markdown stays clean
        for ln in body.splitlines()[:8]:
            lines.append(f"> {ln}" if ln.strip() else ">")
        lines.append("")
        lines.append("**Audit verdict:** _(fill in: model-error / label-noise / cross-team-ambiguous)_")
        lines.append("")
        lines.append("---\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({len(lines)} lines, {out_path.stat().st_size} bytes)")
    print(f"Misclassified bug count: {len(misclass_idx)}")


if __name__ == "__main__":
    main()
