#!/usr/bin/env python3
"""
build_embedding_index.py — One-time index builder for the embedding classifier.

Fetches the last 15 months of component-labelled FLIPPI bugs from Jira,
embeds each bug with sentence-transformers/all-mpnet-base-v2, and caches
the embedding matrix + labels to data/embedding_index.npz.

Re-run this whenever you want a refreshed index (new Jira bugs, corrected
labels, etc.). The embedding classifier loads from the cached file at
predict time; it does not refetch.

Usage:
    python3 build_embedding_index.py                 # default 2000 bugs, 15 months
    python3 build_embedding_index.py --limit 3000    # bigger corpus
    python3 build_embedding_index.py --months 12     # tighter age filter
"""

from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

load_dotenv()

from src.jira_client          import JiraClient
from src.embedding_classifier import build_index, DEFAULT_INDEX_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit",   type=int, default=2000, help="Max bugs to fetch")
    parser.add_argument("--months",  type=int, default=15,   help="Max age in months")
    parser.add_argument("--out",     type=str, default=str(DEFAULT_INDEX_PATH))
    args = parser.parse_args()

    t0 = time.time()

    print("─" * 70)
    print(f"Step 1 — Fetching from Jira (limit={args.limit}, last {args.months} months)")
    print("─" * 70)
    jira = JiraClient()
    issues = jira.fetch_training_corpus(
        limit=args.limit,
        max_age_months=args.months,
    )
    t_fetch = time.time() - t0
    print(f"Fetched {len(issues)} issues in {t_fetch:.1f}s")
    print()

    # ── Step 1b: fold in human corrections from previous triage sessions ──
    # These are user-supplied overrides captured by app.py whenever the
    # reviewer changes Component in the Edit widgets. Each correction
    # becomes a synthetic Jira-shaped issue and joins the training pool.
    # This is the active-learning loop: corrections accumulated this week
    # become labelled training data next time we rebuild.
    import csv
    from pathlib import Path as _P
    corrections_path = _P("data/corrections.csv")
    n_corrections = 0
    if corrections_path.exists():
        with corrections_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                corrected = row.get("corrected_component", "").strip()
                title     = row.get("title", "").strip()
                text      = row.get("bug_text", "").strip()
                if not corrected or not text:
                    continue
                # Build a Jira-issue-shaped dict so build_index handles it
                # exactly like a real Jira fetch.
                synthetic = {
                    "key": f"CORRECTION-{row.get('bug_hash','')}",
                    "fields": {
                        "summary":      title or text.split("\n", 1)[0][:120],
                        "description":  text,
                        "components":   [{"name": corrected}],
                        "assignee":     None,
                        "priority":     {"name": "Unknown"},
                        "created":      row.get("timestamp", ""),
                    },
                }
                issues.append(synthetic)
                n_corrections += 1
        print(f"Folded {n_corrections} human corrections from {corrections_path}")
    else:
        print(f"No corrections.csv found at {corrections_path} — first build, fine.")
    print()

    print("─" * 70)
    print("Step 2 — Embedding")
    print("─" * 70)
    t1 = time.time()
    summary = build_index(issues, out_path=args.out)
    t_embed = time.time() - t1

    print()
    print("═" * 70)
    print(f"✓ Done in {time.time()-t0:.1f}s "
          f"(fetch {t_fetch:.1f}s, embed {t_embed:.1f}s)")
    print(f"  Indexed {summary['n_total']} bugs to {summary['out_path']}")
    print(f"  Per-class counts: {summary['counts']}")
    print(f"  Skipped: {summary['skipped']}")
    print("═" * 70)


if __name__ == "__main__":
    main()
