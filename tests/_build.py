"""
One-shot helper to populate the tests/ folder.

For each test in MAPPING:
  1. Copy data/<source>.txt → tests/<test_name>.txt
  2. Find the matching output JSON in output/
  3. Extract triage_notes and write tests/<test_name>.md
     (Markdown with clickable Jira links)

Run from project root:  python3 tests/_build.py
"""

import json
import shutil
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
DATA    = ROOT / "data"
OUTPUT  = ROOT / "output"
TESTS   = ROOT / "tests"

# (source stem in data/, new test name, one-line description)
MAPPING = [
    ("bug_report",                     "test_00_baseline_cart_freeze",        "Original cart-freeze sample (baseline for duplicate detection)."),
    ("bug_01_p0_checkout_crash",       "test_01_p0_checkout_crash",           "P0 — 100%-repro checkout crash on Android, revenue-blocking."),
    ("bug_02_p1_search_wrong_results", "test_02_p1_wrong_ai_recommendations", "P1 — AI ignores price constraints and returns wrong recommendations."),
    ("bug_03_p2_image_not_loading",    "test_03_p2_images_slow_network",      "P2 — product images fail to load on 2G/3G networks."),
    ("bug_04_duplicate_of_bug_report", "test_04_duplicate_of_baseline",       "Duplicate detection — same cart-freeze as the baseline."),
    ("bug_05_vague_minimal_info",      "test_05_p3_vague_report",             "P3 — vague report with no steps, falls back to low priority."),
    ("bug_dup_FLIPPI3044_secrets",     "test_06_dup_FLIPPI3044_secrets",      "Duplicate against real FLIPPI-3044 (Grayskull secrets, P0)."),
    ("bug_dup_FLIPPI2905_dedup",       "test_07_dup_FLIPPI2905_dedup",        "Duplicate against real FLIPPI-2905 (product family dedup, P0)."),
    ("bug_dup_FLIPPI2902_auth",        "test_08_dup_FLIPPI2902_auth",         "Duplicate against real FLIPPI-2902 (auth verify failure, P3)."),
    ("bug_comp_immersive",             "test_09_component_immersive_anr",     "Component routing — ANR in VTO SDK should go to Immersive."),
    ("bug_comp_belabs",                "test_10_component_belabs_vton",       "Component routing — VTON gender mismatch should go to BE_Labs."),
    ("bug_comp_ds",                    "test_11_component_ds_nps",            "Component routing — NPS discrepancy should go to DS."),
    ("bug_comp_ui",                    "test_12_component_ui_ios",            "Component routing — iOS cold-start flash should go to UI."),
    ("bug_comp_belippi",               "test_13_component_belippi_price",     "Component routing — price-filter ignored should go to BE_Flippi."),
    ("bug_comp_unclassified",          "test_14_component_unclassified",      "Component routing — vague bug should fall through to 'bugs'."),
]


def find_output_json(source_stem: str) -> Path:
    """Find the output/ticket_<source_stem>_<timestamp>.json file."""
    matches = sorted(OUTPUT.glob(f"ticket_{source_stem}_*.json"))
    if not matches:
        raise FileNotFoundError(f"No output JSON found for {source_stem}")
    return matches[-1]  # latest if multiple


def format_priority_badge(scoring_path: str) -> str:
    """Pull a short layer label out of the scoring_path field."""
    if not scoring_path:
        return ""
    return scoring_path.split(":")[0].strip()


def render_md(test_name: str, description: str, triage: dict) -> str:
    """Render the triage_notes dict as a clean Markdown document."""
    lines: list[str] = []

    lines.append(f"# {test_name}")
    lines.append("")
    lines.append(f"_{description}_")
    lines.append("")
    lines.append(f"**Input file:** `{test_name}.txt`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Triage Notes")
    lines.append("")

    # ── Summary table ────────────────────────────────────────────────────
    team           = triage.get("team", "—")
    component      = triage.get("jira_component") or "_(none — needs manual routing)_"
    scoring_path   = triage.get("priority_scoring_path", "—")
    layer          = format_priority_badge(scoring_path)
    owner          = triage.get("owner_suggestion") or "_(no suggestion)_"
    owner_reason   = triage.get("owner_reason") or ""
    dup_key        = triage.get("duplicate_of")
    dup_conf       = triage.get("duplicate_confidence", 0.0)

    if dup_key:
        dup_cell = f"[{dup_key}](https://flipkart.atlassian.net/browse/{dup_key}) (confidence {dup_conf:.2f})"
    else:
        dup_cell = f"_(no duplicate)_ — top-match similarity {dup_conf:.2f}"

    # Pipes inside inline code break some markdown table renderers — escape them.
    scoring_path_cell = scoring_path.replace("|", "\\|")
    layer_cell        = layer.replace("|", "\\|")

    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Team** | {team} |")
    lines.append(f"| **Jira component** | {component} |")
    lines.append(f"| **Scoring layer** | `{layer_cell}` |")
    lines.append(f"| **Scoring path** | `{scoring_path_cell}` |")
    lines.append(f"| **Duplicate of** | {dup_cell} |")
    lines.append(f"| **Owner suggestion** | {owner} |")
    lines.append(f"| **Owner reason** | {owner_reason} |")
    lines.append("")

    # ── Severity justification ───────────────────────────────────────────
    just = triage.get("severity_justification", "")
    if just:
        lines.append("## Severity Justification")
        lines.append("")
        lines.append(f"> {just}")
        lines.append("")

    # ── Similar past bugs ────────────────────────────────────────────────
    similar = triage.get("similar_bugs", [])
    if similar:
        lines.append("## Similar Past Bugs")
        lines.append("")
        lines.append("| Jira Key | Priority | Similarity | Assignee | Summary |")
        lines.append("|---|---|---|---|---|")
        for s in similar:
            key       = s.get("key", "")
            url       = s.get("url") or f"https://flipkart.atlassian.net/browse/{key}"
            priority  = s.get("priority", "—")
            sim       = s.get("similarity", 0.0)
            assignee  = s.get("assignee") or "_(unassigned)_"
            summary   = (s.get("summary") or "").replace("|", "\\|")
            lines.append(f"| [{key}]({url}) | {priority} | {sim:.3f} | {assignee} | {summary} |")
        lines.append("")

    # ── Footer note ──────────────────────────────────────────────────────
    note = triage.get("note")
    if note:
        lines.append("---")
        lines.append("")
        lines.append(f"_{note}_")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    TESTS.mkdir(exist_ok=True)
    summary_rows: list[str] = []

    for source_stem, test_name, description in MAPPING:
        # Copy the input .txt
        src_txt = DATA / f"{source_stem}.txt"
        dst_txt = TESTS / f"{test_name}.txt"
        shutil.copyfile(src_txt, dst_txt)

        # Read the output JSON and extract triage_notes
        out_json = find_output_json(source_stem)
        with out_json.open() as f:
            payload = json.load(f)
        triage = payload.get("triage_notes", {})

        # Write the Markdown
        md = render_md(test_name, description, triage)
        (TESTS / f"{test_name}.md").write_text(md)

        # Write the raw triage_notes JSON (pretty-printed)
        (TESTS / f"{test_name}.json").write_text(
            json.dumps(triage, indent=2, ensure_ascii=False) + "\n"
        )

        # Index row
        team     = triage.get("team", "—")
        path_lbl = (triage.get("priority_scoring_path") or "—").split(":")[0].replace("|", "\\|")
        dup_key  = triage.get("duplicate_of")
        dup_lbl  = f"[{dup_key}](https://flipkart.atlassian.net/browse/{dup_key})" if dup_key else "—"
        summary_rows.append(
            f"| [{test_name}]({test_name}.md) | {description} | {team} | `{path_lbl}` | {dup_lbl} |"
        )

        print(f"  ✓ {test_name}")

    # Index README
    readme = [
        "# SLAP Bug Triage — Test Suite",
        "",
        "15 end-to-end tests run through the agent pipeline (`run_agent.py`).",
        "Each test has three files:",
        "",
        "- `<test_name>.txt`  — the raw bug report email fed in as input.",
        "- `<test_name>.md`   — only the `triage_notes` portion of the agent's output, formatted for reading.",
        "- `<test_name>.json` — same `triage_notes` content as raw pretty-printed JSON.",
        "",
        "All Jira ticket references in the `.md` files are clickable links to `flipkart.atlassian.net`.",
        "",
        "## Test index",
        "",
        "| Test | What it checks | Team routed | Scoring layer | Duplicate of |",
        "|---|---|---|---|---|",
        *summary_rows,
        "",
        "## How to re-run",
        "",
        "```bash",
        "python3 run_agent.py             # runs all data/*.txt",
        "python3 tests/_build.py          # regenerates this tests/ folder from output/",
        "```",
        "",
    ]
    (TESTS / "README.md").write_text("\n".join(readme))
    print(f"\n  ✓ tests/README.md written ({len(MAPPING)} tests)")


if __name__ == "__main__":
    main()
