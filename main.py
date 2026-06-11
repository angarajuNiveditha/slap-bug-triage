#!/usr/bin/env python3
"""
main.py — SLAP Bug Triage Prototype Orchestrator

Pipeline:
  1. Read bug_report.txt
  2. Parse with Claude → structured BugReport
  3. Fetch recent FLIPPI bugs from Jira (read-only)
  4. Build local similarity index
  5. Find similar bugs → duplicate detection + owner routing
  6. Score severity with Claude
  7. Build Jira ticket draft (ADF JSON)
  8. Write output to output/ticket_draft.json

Production equivalent:
  Pulse (email in) → Synapse → Astral → Genvoy + Vector One + Jira MCP
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing src modules
load_dotenv()

from src.jira_client import JiraClient
from src.parser import parse_bug_report
from src.severity_scorer import score_severity
from src.similarity import SimilarityEngine
from src.ticket_builder import build_ticket


def main():
    # ------------------------------------------------------------------
    # CLI argument: optional input file path
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(description="SLAP Bug Triage Prototype")
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Path to bug report file (default: data/bug_report.txt)",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    base_dir = Path(__file__).parent
    input_path = Path(args.input) if args.input else base_dir / "data" / "bug_report.txt"
    output_dir = base_dir / "output"
    output_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("  SLAP Bug Triage Prototype")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 0 — Verify Jira token
    # ------------------------------------------------------------------
    print("\n[Step 0] Verifying Jira credentials...")
    jira = JiraClient()
    try:
        me = jira.whoami()
        print(f"  Connected as: {me.get('displayName')} ({me.get('emailAddress')})")
    except Exception as e:
        print(f"  ERROR: Could not connect to Jira: {e}")
        print("  Check JIRA_EMAIL and JIRA_TOKEN in your .env file.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 1 — Read bug report
    # ------------------------------------------------------------------
    print(f"\n[Step 1] Reading bug report from {input_path}...")
    if not input_path.exists():
        print(f"  ERROR: {input_path} not found.")
        sys.exit(1)
    raw_text = input_path.read_text(encoding="utf-8")
    print(f"  Read {len(raw_text)} characters.")

    # ------------------------------------------------------------------
    # Step 2 — Parse with Claude
    # ------------------------------------------------------------------
    print("\n[Step 2] Parsing bug report with Claude...")
    bug = parse_bug_report(raw_text)
    print(f"  Title:    {bug.title}")
    print(f"  Platform: {bug.platform}  |  Version: {bug.app_version}")
    print(f"  Component: {bug.component_hint}  |  Repro: {bug.reproducibility}")
    print(f"  Reporter: {bug.reporter_name} <{bug.reporter_email}>")

    # ------------------------------------------------------------------
    # Step 3 — Fetch recent FLIPPI bugs from Jira
    # ------------------------------------------------------------------
    print("\n[Step 3] Fetching recent bugs from Jira FLIPPI project...")
    issues = jira.fetch_recent_bugs(limit=300)

    # ------------------------------------------------------------------
    # Step 4 — Build similarity index
    # ------------------------------------------------------------------
    print("\n[Step 4] Building local similarity index...")
    engine = SimilarityEngine()
    engine.build_index(issues)

    # ------------------------------------------------------------------
    # Step 5 — Find similar bugs
    # ------------------------------------------------------------------
    print("\n[Step 5] Finding similar bugs (duplicate detection + owner routing)...")
    query_text = f"{bug.title}\n{bug.description}\n{bug.actual_result}"
    sim_result = engine.find_similar(query_text)

    print(f"  Top matches: {len(sim_result.top_matches)}")
    for m in sim_result.top_matches:
        dup_flag = " ← DUPLICATE CANDIDATE" if m.is_duplicate_candidate else ""
        print(f"    {m.key} (sim={m.similarity:.3f}, {m.priority}): {m.summary[:60]}{dup_flag}")

    if sim_result.duplicate_of:
        print(f"\n  ⚠ POSSIBLE DUPLICATE of {sim_result.duplicate_of} "
              f"(confidence {sim_result.duplicate_confidence:.0%})")
    if sim_result.suggested_owner:
        print(f"  Suggested owner: {sim_result.suggested_owner}")
        print(f"  Reason: {sim_result.owner_reason}")

    # ------------------------------------------------------------------
    # Step 6 — Score severity
    # ------------------------------------------------------------------
    print("\n[Step 6] Scoring severity with Claude...")
    severity = score_severity(bug, sim_result.top_matches)
    print(f"  Priority: {severity.priority}  |  Severity: {severity.severity}")
    print(f"  Justification: {severity.justification}")

    # ------------------------------------------------------------------
    # Step 7 — Build Jira ticket draft
    # ------------------------------------------------------------------
    print("\n[Step 7] Building Jira ticket draft (ADF JSON)...")
    draft = build_ticket(bug, severity, sim_result)

    # ------------------------------------------------------------------
    # Step 8 — Write output
    # ------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ticket_draft_{timestamp}.json"

    output = {
        "generated_at": datetime.now().isoformat(),
        "input_file": str(input_path),
        "parsed_bug": {
            "title": bug.title,
            "platform": bug.platform,
            "app_version": bug.app_version,
            "component_hint": bug.component_hint,
            "reproducibility": bug.reproducibility,
            "reporter": f"{bug.reporter_name} <{bug.reporter_email}>",
        },
        "jira_ticket_draft": draft.jira_payload,
        "triage_notes": draft.triage_notes,
    }

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[Step 8] Ticket draft written to: {output_path}")

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  TRIAGE SUMMARY")
    print("=" * 60)
    print(f"  Title    : {bug.title}")
    print(f"  Priority : {severity.priority}  |  Severity: {severity.severity}")
    print(f"  Component: {draft.jira_payload['fields'].get('components', [{'name': 'TBD'}])[0]['name']}")
    print(f"  Owner    : {sim_result.suggested_owner or 'TBD'}")
    if sim_result.duplicate_of:
        print(f"  ⚠ Duplicate of: {sim_result.duplicate_of} ({sim_result.duplicate_confidence:.0%} confidence)")
    print(f"\n  Full draft saved to: {output_path}")
    print("\n  NOTE: This is a DRAFT. A human must review and file the Jira ticket.")
    print("=" * 60)


if __name__ == "__main__":
    main()
