#!/usr/bin/env python3
"""
tests/_run_claude.py — Run the Claude Code pipeline on every test folder
and write a `<name>_claude.json` (triage_notes only) next to the existing
rule-based `<name>.json`.

Builds the Jira index ONCE and reuses it across all 15 tests to avoid
re-fetching 300 issues per file.

Run from project root:  python3 tests/_run_claude.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Make `src` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.host_agent import HostAgent                 # noqa: E402
from src.jira_client        import JiraClient               # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent


def main() -> None:
    txt_files = sorted(TESTS_DIR.glob("test */*.txt"))
    if not txt_files:
        print("No test .txt files found under tests/test */")
        sys.exit(1)

    print(f"Found {len(txt_files)} test .txt files")
    print("Each test runs the multi-agent pipeline (4 Claude calls).")
    print("Estimated total: 15-25 minutes.\n")

    # ─── Build the Jira index once ───────────────────────────────────────
    print("[setup] Fetching 300 historical FLIPPI bugs...")
    jira   = JiraClient()
    issues = jira.fetch_recent_bugs(limit=300)
    print("[setup] Building host-agent embeddings index...")
    host = HostAgent()
    host.build_index(issues)

    # ─── Process each test ───────────────────────────────────────────────
    successes: list[str] = []
    failures:  list[tuple[str, str]] = []

    for idx, txt_path in enumerate(txt_files, 1):
        rel = f"{txt_path.parent.name}/{txt_path.name}"
        print(f"\n[{idx}/{len(txt_files)}] {rel}")
        t0 = time.time()
        try:
            raw    = txt_path.read_text(encoding="utf-8")
            result = host.triage(raw)
            triage = result.draft.triage_notes

            out_path = txt_path.with_name(txt_path.stem + "_claude.json")
            out_path.write_text(
                json.dumps(triage, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            dt = time.time() - t0
            print(f"  ✓ {out_path.name}  ({dt:.1f}s)  "
                  f"→ {result.severity.priority} / team={triage.get('team')}")
            successes.append(rel)
        except Exception as e:
            dt = time.time() - t0
            print(f"  ✗ FAILED after {dt:.1f}s — {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append((rel, f"{type(e).__name__}: {e}"))

    # ─── Summary ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Done — {len(successes)} succeeded, {len(failures)} failed")
    print(f"{'=' * 60}")
    if failures:
        print("\nFailures:")
        for rel, msg in failures:
            print(f"  - {rel}: {msg}")


if __name__ == "__main__":
    main()
