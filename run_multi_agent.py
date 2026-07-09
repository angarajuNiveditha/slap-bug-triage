#!/usr/bin/env python3
"""
run_multi_agent.py — Multi-agent SLAP bug triage (Claude Code headless).

Replaces the old run_claude_agent.py. Uses the host_agent (Astral) to
coordinate parser / embeddings / dedup / triage sub-agents, plus the
media sub-agent when image attachments are present.

USAGE
-----
  python3 run_multi_agent.py                              # all bugs in data/
  python3 run_multi_agent.py data/bug_01_p0_checkout_crash.txt
  python3 run_multi_agent.py data/bug_with_media/bug_99_*  # any folder with email.txt + images

A bug can be EITHER:
  • a single .txt file (no media), OR
  • a folder containing an `email.txt` plus image attachments (.png, .jpg, ...).

Outputs land in output_claude/ (gitignored).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.agents.host_agent import HostAgent
from src.agents.subagent_media import MEDIA_EXTENSIONS
from src.shared.jira_client import JiraClient


BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output_claude"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Discover bug inputs ─────────────────────────────────────────────────────

def discover_inputs(paths: list) -> list:
    """
    Each input can be a .txt file (no media) or a folder containing email.txt
    plus images. Returns a list of (label, email_text, image_paths) tuples.
    """
    bugs = []
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix.lower() == ".txt":
            bugs.append((p.stem, p.read_text(encoding="utf-8"), []))
        elif p.is_dir():
            email = p / "email.txt"
            if not email.exists():
                print(f"  ✗ {p}: no email.txt — skipping")
                continue
            media = sorted(
                f for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
            )
            bugs.append((p.name, email.read_text(encoding="utf-8"), [str(i) for i in media]))
        else:
            print(f"  ✗ {p}: not a .txt or a directory — skipping")
    return bugs


# ── Per-bug pipeline ────────────────────────────────────────────────────────

def triage_bug(label: str, email_text: str, image_paths: list, host: HostAgent) -> dict:
    print(f"\n{'─'*60}\n  {label}  ({len(image_paths)} attachment(s))\n{'─'*60}")

    result = host.triage(email_text, image_paths=image_paths)

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"ticket_{label}_{timestamp}.json"

    output = {
        "generated_at":       datetime.now().isoformat(),
        "input_label":        label,
        "pipeline":           "multi-agent (Astral)",
        "attachment_count":   len(image_paths),
        "parsed_bug": {
            "title":           result.bug.title,
            "platform":        result.bug.platform,
            "app_version":     result.bug.app_version,
            "component_hint":  result.bug.component_hint,
            "reproducibility": result.bug.reproducibility,
            "reporter":        f"{result.bug.reporter_name} <{result.bug.reporter_email}>",
        },
        "jira_ticket_draft": result.draft.jira_payload,
        "triage_notes":      result.draft.triage_notes,
    }
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Console summary
    sev = result.severity; sim = result.similarity; bug = result.bug
    print(f"\n  Priority : {sev.priority}  |  Severity: {sev.severity}")
    print(f"  Team     : {result.draft.triage_notes.get('team')}  →  Component: {result.draft.triage_notes.get('jira_component')}")
    print(f"  Owner    : {sim.suggested_owner or 'TBD'}")
    if sim.duplicate_of:
        print(f"  DUPLICATE of: {sim.duplicate_of} ({sim.duplicate_confidence:.0%})")
    if result.media.findings:
        print(f"  Media: {len(result.media.findings)} image(s) processed")
        for f in result.media.findings:
            print(f"    • {f.screen} ({f.state}) — {f.one_line_summary}")
    print(f"  Written  : output_claude/{output_path.name}")
    return output


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    # Discover inputs from argv, or fall back to default data/ scan.
    if len(sys.argv) > 1:
        bugs = discover_inputs(sys.argv[1:])
    else:
        candidates = sorted(BASE_DIR.glob("data/*.txt"))
        candidates += [d for d in (BASE_DIR / "data").glob("bug_with_media/*") if d.is_dir()]
        bugs = discover_inputs([str(c) for c in candidates])

    if not bugs:
        print("No inputs found.")
        sys.exit(1)

    print("=" * 60)
    print("  SLAP Bug Triage — Multi-Agent Pipeline (Astral)")
    print("=" * 60)
    print(f"\n  {len(bugs)} bug(s) to triage")

    print("\n[setup] Verifying Jira credentials...")
    jira = JiraClient()
    me   = jira.whoami()
    print(f"  Connected as: {me.get('displayName')} <{me.get('emailAddress')}>")

    print("\n[setup] Fetching 300 historical FLIPPI bugs...")
    issues = jira.fetch_recent_bugs(limit=300)

    print("[setup] Building embeddings index in host agent...")
    host = HostAgent()
    host.build_index(issues)

    ok, fail = 0, 0
    for label, text, images in bugs:
        try:
            triage_bug(label, text, images, host)
            ok += 1
        except Exception as e:
            print(f"\n  ✗ {label} FAILED: {type(e).__name__}: {e}")
            fail += 1

    print(f"\n{'='*60}\n  Done — {ok} succeeded, {fail} failed\n{'='*60}")


if __name__ == "__main__":
    main()
