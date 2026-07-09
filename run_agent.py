#!/usr/bin/env python3
"""
run_agent.py — Agent-driven SLAP Bug Triage (no Anthropic API key required).

Same 8-step pipeline as main.py but the Claude API calls are replaced by:
  - src/agent_parser.py   → rule-based structured field extraction
  - src/agent_scorer.py   → keyword + heuristic severity scoring
  - src/tfidf_similarity.py → TF-IDF cosine similarity (scikit-learn, no GPU)

Everything else (Jira REST fetch, ADF ticket building, JSON output) is unchanged.

Usage:
  python3 run_agent.py                          # all .txt files in data/
  python3 run_agent.py data/bug_01_p0_*.txt     # specific file(s)
"""

import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.rule_based.agent_parser import parse_bug_report
from src.rule_based.agent_scorer import score_severity
from src.shared.agent_ticket_builder import build_ticket
from src.shared.jira_client import JiraClient
from src.rule_based.tfidf_similarity import SimilarityEngine


BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Jira fetch + index — done once for all files
# ---------------------------------------------------------------------------

def build_shared_index() -> tuple[JiraClient, SimilarityEngine]:
    print("=" * 60)
    print("  SLAP Bug Triage — Agent Pipeline (no API key)")
    print("=" * 60)

    print("\n[Step 0] Verifying Jira credentials...")
    jira = JiraClient()
    me = jira.whoami()
    print(f"  Connected as: {me.get('displayName')} ({me.get('emailAddress')})")

    print("\n[Step 3] Fetching recent bugs from Jira FLIPPI project...")
    issues = jira.fetch_recent_bugs(limit=300)

    print("\n[Step 4] Building TF-IDF similarity index...")
    engine = SimilarityEngine()
    engine.build_index(issues)

    return jira, engine


# ---------------------------------------------------------------------------
# Single-file pipeline
# ---------------------------------------------------------------------------

def triage_file(input_path: Path, engine: SimilarityEngine) -> dict:
    print(f"\n{'─' * 60}")
    print(f"  Processing: {input_path.name}")
    print(f"{'─' * 60}")

    # Step 1 — Read
    print(f"\n[Step 1] Reading {input_path.name}...")
    raw_text = input_path.read_text(encoding="utf-8")
    print(f"  {len(raw_text)} characters")

    # Step 2 — Parse (agent does this)
    print("\n[Step 2] Parsing bug report (agent)...")
    bug = parse_bug_report(raw_text)
    print(f"  Title:    {bug.title}")
    print(f"  Platform: {bug.platform}  |  Version: {bug.app_version}")
    print(f"  Component: {bug.component_hint}  |  Repro: {bug.reproducibility}")
    print(f"  Reporter: {bug.reporter_name} <{bug.reporter_email}>")

    # Step 5 — Similarity
    print("\n[Step 5] Finding similar bugs...")
    query = f"{bug.title}\n{bug.description}\n{bug.actual_result}"
    sim   = engine.find_similar(query)

    print(f"  Top matches: {len(sim.top_matches)}")
    for m in sim.top_matches:
        flag = " ← DUPLICATE CANDIDATE" if m.is_duplicate_candidate else ""
        print(f"    {m.key} (sim={m.similarity:.3f}, {m.priority}): {m.summary[:55]}{flag}")
        print(f"      {m.url}")
    if sim.duplicate_of:
        dup_match = next((m for m in sim.top_matches if m.key == sim.duplicate_of), None)
        dup_url   = dup_match.url if dup_match else ""
        print(f"\n  POSSIBLE DUPLICATE of {sim.duplicate_of} "
              f"(confidence {sim.duplicate_confidence:.0%})")
        if dup_url:
            print(f"  → {dup_url}")
    if sim.suggested_owner:
        print(f"  Suggested owner: {sim.suggested_owner}")
        print(f"  Reason: {sim.owner_reason}")

    # Step 6 — Score severity (agent does this)
    print("\n[Step 6] Scoring severity (agent)...")
    severity = score_severity(bug, sim.top_matches)
    print(f"  Priority: {severity.priority}  |  Severity: {severity.severity}")
    print(f"  Scoring path: {severity.scoring_path}")
    print(f"  Justification: {severity.justification}")

    # Step 7 — Build ticket
    print("\n[Step 7] Building Jira ticket draft...")
    draft = build_ticket(bug, severity, sim)

    # Step 8 — Assemble output dict
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"ticket_{input_path.stem}_{timestamp}.json"

    output = {
        "generated_at": datetime.now().isoformat(),
        "input_file":   str(input_path),
        "pipeline":     "agent (no API key)",
        "parsed_bug": {
            "title":          bug.title,
            "platform":       bug.platform,
            "app_version":    bug.app_version,
            "component_hint": bug.component_hint,
            "reproducibility":bug.reproducibility,
            "reporter":       f"{bug.reporter_name} <{bug.reporter_email}>",
        },
        "jira_ticket_draft": draft.jira_payload,
        "triage_notes":      draft.triage_notes,
    }

    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[Step 8] Written → {output_path.name}")

    # Console summary
    team_label  = draft.triage_notes.get("team", "bugs")
    jira_comp   = draft.triage_notes.get("jira_component", "unclassified")
    print(f"\n  {'─'*40}")
    print(f"  Title    : {bug.title}")
    print(f"  Priority : {severity.priority}  |  Severity: {severity.severity}")
    print(f"  Team     : {team_label}  →  Jira component: {jira_comp}")
    print(f"  Owner    : {sim.suggested_owner or 'TBD'}")
    if sim.duplicate_of:
        print(f"  DUPLICATE of: {sim.duplicate_of} ({sim.duplicate_confidence:.0%} confidence)")
    print(f"  {'─'*40}")

    return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Determine which files to process
    if len(sys.argv) > 1:
        input_files = [Path(p) for p in sys.argv[1:]]
    else:
        input_files = sorted(BASE_DIR.glob("data/*.txt"))

    if not input_files:
        print("No .txt files found.")
        sys.exit(1)

    print(f"\nWill process {len(input_files)} file(s):")
    for f in input_files:
        print(f"  {f.name}")

    # Build shared Jira index once
    jira, engine = build_shared_index()

    # Triage each file
    results = []
    for f in input_files:
        if not f.exists():
            print(f"\nSkipping {f} — file not found.")
            continue
        result = triage_file(f, engine)
        results.append(result)

    print(f"\n{'=' * 60}")
    print(f"  Done — {len(results)} ticket draft(s) written to output/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
