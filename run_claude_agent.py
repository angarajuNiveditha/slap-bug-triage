#!/usr/bin/env python3
"""
run_claude_agent.py — Claude Code headless pipeline (no Anthropic API key).

Same 8-step pipeline as run_agent.py, but the rule-based stages are replaced
by Claude Code subprocess calls (via `claude -p`):

  - src/claude_parser.py     — email → BugReport            (was agent_parser)
  - src/claude_similarity.py — bugs index + new bug → SimilarityResult
                                                            (was tfidf_similarity)
  - src/claude_scorer.py     — bug + similar → SeverityResult (was agent_scorer)

Everything else — Jira fetch (read-only), ADF ticket builder, output JSON
shape — is reused unchanged from the existing modules. Outputs land in
`output_claude/` so they don't collide with the rule-based pipeline's
`output/` folder.

Requirements:
  - Claude Code CLI installed and authenticated on this machine.
  - Jira credentials in .env (JIRA_EMAIL, JIRA_TOKEN, JIRA_BASE_URL, JIRA_PROJECT).

Usage:
  python3 run_claude_agent.py                                  # all data/*.txt
  python3 run_claude_agent.py data/bug_01_p0_checkout_crash.txt
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.agent_ticket_builder import build_ticket
from src.claude_parser import parse_bug_report
from src.claude_scorer import score_severity
from src.claude_similarity import SimilarityEngine
from src.jira_client import JiraClient


BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output_claude"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Jira fetch + cache — done once for all files
# ---------------------------------------------------------------------------

def build_shared_index() -> tuple[JiraClient, SimilarityEngine]:
    print("=" * 60)
    print("  SLAP Bug Triage — Claude Code Pipeline (no API key)")
    print("=" * 60)

    print("\n[Step 0] Verifying Jira credentials...")
    jira = JiraClient()
    me   = jira.whoami()
    print(f"  Connected as: {me.get('displayName')} ({me.get('emailAddress')})")

    print("\n[Step 3] Fetching recent bugs from Jira FLIPPI project...")
    issues = jira.fetch_recent_bugs(limit=300)

    print("\n[Step 4] Caching historical bugs for Claude similarity prompts...")
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

    # Step 2 — Parse (Claude)
    print("\n[Step 2] Parsing bug report (Claude)...")
    bug = parse_bug_report(raw_text)
    print(f"  Title:     {bug.title}")
    print(f"  Platform:  {bug.platform}  |  Version: {bug.app_version}")
    print(f"  Component: {bug.component_hint}  |  Repro: {bug.reproducibility}")
    print(f"  Reporter:  {bug.reporter_name} <{bug.reporter_email}>")

    # Step 5 — Similarity (Claude)
    print("\n[Step 5] Finding similar bugs (Claude)...")
    sim = engine.find_similar(bug)
    print(f"  Top matches: {len(sim.top_matches)}")
    for m in sim.top_matches:
        flag = " ← DUPLICATE CANDIDATE" if m.is_duplicate_candidate else ""
        print(f"    {m.key} (sim={m.similarity:.3f}, {m.priority}): {m.summary[:55]}{flag}")
        print(f"      {m.url}")
    if sim.duplicate_of:
        print(f"\n  POSSIBLE DUPLICATE of {sim.duplicate_of} "
              f"(confidence {sim.duplicate_confidence:.0%})")
    if sim.suggested_owner:
        print(f"  Suggested owner: {sim.suggested_owner}")
        print(f"  Reason: {sim.owner_reason}")

    # Step 6 — Score severity (Claude)
    print("\n[Step 6] Scoring severity (Claude)...")
    severity = score_severity(bug, sim.top_matches)
    print(f"  Priority: {severity.priority}  |  Severity: {severity.severity}")
    print(f"  Scoring path: {severity.scoring_path}")
    print(f"  Justification: {severity.justification}")

    # Step 7 — Build ticket (existing builder, reused)
    print("\n[Step 7] Building Jira ticket draft...")
    draft = build_ticket(bug, severity, sim)

    # Step 8 — Assemble output dict
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"ticket_{input_path.stem}_{timestamp}.json"

    output = {
        "generated_at": datetime.now().isoformat(),
        "input_file":   str(input_path),
        "pipeline":     "claude-code-headless",
        "parsed_bug": {
            "title":           bug.title,
            "platform":        bug.platform,
            "app_version":     bug.app_version,
            "component_hint":  bug.component_hint,
            "reproducibility": bug.reproducibility,
            "reporter":        f"{bug.reporter_name} <{bug.reporter_email}>",
        },
        "jira_ticket_draft": draft.jira_payload,
        "triage_notes":      draft.triage_notes,
    }

    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[Step 8] Written → output_claude/{output_path.name}")

    # Console summary
    team_label = draft.triage_notes.get("team", "bugs")
    jira_comp  = draft.triage_notes.get("jira_component", "unclassified")
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

    jira, engine = build_shared_index()

    results = []
    for f in input_files:
        if not f.exists():
            print(f"\nSkipping {f} — file not found.")
            continue
        try:
            result = triage_file(f, engine)
            results.append(result)
        except Exception as e:
            print(f"\n  ✗ {f.name} failed: {type(e).__name__}: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Done — {len(results)} / {len(input_files)} ticket draft(s) written to output_claude/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
