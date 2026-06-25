#!/usr/bin/env python3
"""
build_repo_skills.py — Generate per-repo skill files from cloned code.

For each repo listed in slap_context/architecture/repos.json that we have
a local clone of (under data/repos/<repo>/), extract:

  - README.md content (first ~3 KB if present)
  - Top-level directory layout
  - Detected stack (from build files: package.json, build.gradle, pom.xml,
    setup.py, pyproject.toml, requirements.txt)
  - Last N commits on the prod branch (subject + author + date)
  - Key entry-point files
  - File extension breakdown (so we know what languages live where)
  - Source-file count per top-level dir (for routing intuition)

Write the result to slap_context/architecture/repos/<repo>.md.

These per-repo skills are the *actual* "what's in this code" files — not
hand-curated prose. They get included alongside the team-level skill files
when the classifier's Claude fallback needs to disambiguate.

Usage:
    python3 build_repo_skills.py            # process all cloned repos
    python3 build_repo_skills.py dropsense  # process just one
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)


REPO_ROOT      = Path(__file__).parent
CLONES_DIR     = REPO_ROOT / "data" / "repos"
MANIFEST       = REPO_ROOT / "slap_context" / "architecture" / "repos.json"
SKILLS_OUTPUT  = REPO_ROOT / "slap_context" / "architecture" / "repos"

README_MAX_BYTES = 3_500
TOP_DIRS_LIMIT   = 25
N_RECENT_COMMITS = 15

# Files that signal which language/build system a repo uses
BUILD_FILE_SIGNALS = {
    "package.json":       "Node.js / JavaScript (npm)",
    "pnpm-lock.yaml":     "Node.js (pnpm)",
    "yarn.lock":          "Node.js (yarn)",
    "build.gradle":       "Java / Kotlin (Gradle)",
    "build.gradle.kts":   "Kotlin (Gradle)",
    "pom.xml":            "Java (Maven)",
    "setup.py":           "Python (setuptools)",
    "pyproject.toml":     "Python (PEP 517)",
    "requirements.txt":   "Python (pip)",
    "Pipfile":            "Python (pipenv)",
    "poetry.lock":        "Python (poetry)",
    "go.mod":             "Go (modules)",
    "Cargo.toml":         "Rust (cargo)",
    "Podfile":            "iOS / CocoaPods",
    "metro.config.js":    "React Native (Metro bundler)",
    "app.json":           "React Native / Expo manifest",
    "Dockerfile":         "containerised service",
}

# File extensions to count for the language breakdown
RELEVANT_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".java", ".kt", ".py", ".go",
    ".swift", ".m", ".mm", ".h", ".rb", ".scala", ".rs", ".sql",
    ".sh", ".dart", ".vue", ".svelte",
}

# Dirs we always ignore when walking the tree
IGNORE_DIRS = {
    ".git", "node_modules", "build", "dist", "__pycache__",
    ".gradle", ".idea", ".vscode", ".pytest_cache", "venv", ".venv",
    "Pods", "DerivedData", "target", "out", "coverage",
}


def list_top_dirs(repo_path: Path) -> list:
    """Top-level visible dirs in the repo (skipping hidden + ignored)."""
    out = []
    for p in sorted(repo_path.iterdir()):
        if p.is_dir() and not p.name.startswith(".") and p.name not in IGNORE_DIRS:
            out.append(p.name)
    return out


def find_readme(repo_path: Path) -> Path | None:
    for cand in ["README.md", "README.MD", "readme.md", "README.rst", "README.txt", "README"]:
        p = repo_path / cand
        if p.exists():
            return p
    return None


def detected_stack(repo_path: Path) -> list:
    """Return a list of (build_file_seen, language_label) tuples."""
    found = []
    for fname, label in BUILD_FILE_SIGNALS.items():
        if (repo_path / fname).exists():
            found.append((fname, label))
    return found


def language_breakdown(repo_path: Path, max_files_per_ext: int = 999999) -> list:
    """Walk repo, count files per relevant extension. Limit per extension
    to avoid runaway counts on synthetic dirs."""
    counts: Counter = Counter()
    n_total = 0
    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo_path)
        if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts):
            continue
        ext = p.suffix.lower()
        if ext in RELEVANT_EXTS and counts[ext] < max_files_per_ext:
            counts[ext] += 1
            n_total += 1
    return n_total, sorted(counts.items(), key=lambda kv: -kv[1])


def src_file_count_per_dir(repo_path: Path, top_dirs: list) -> list:
    """For each top-level dir, count source files inside (helpful for
    routing — bigger dirs are probably the main code paths)."""
    out = []
    for d in top_dirs:
        dpath = repo_path / d
        if not dpath.exists():
            continue
        n = 0
        for p in dpath.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(dpath)
            if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts):
                continue
            if p.suffix.lower() in RELEVANT_EXTS:
                n += 1
        out.append((d, n))
    return sorted(out, key=lambda kv: -kv[1])


def recent_commits(repo_path: Path, n: int = N_RECENT_COMMITS) -> list:
    """Last N commits on the current HEAD: (date, author, subject) tuples."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_path), "log",
             f"-n{n}", "--pretty=format:%ad|%an|%s", "--date=short"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                out.append(tuple(parts))
        return out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []


def get_remote_url(repo_path: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        url = r.stdout.strip()
        # Strip any embedded tokens out of the URL for the skill file
        import re
        return re.sub(r"https://[^@]*@", "https://", url)
    except Exception:
        return ""


def make_skill(repo_meta: dict, repo_path: Path) -> str:
    """Compose the full Markdown skill file for one repo."""
    name = repo_meta["name"]
    team = repo_meta["team"]
    stack_label = repo_meta["stack"]
    prod_branch = repo_meta["prod_branch"]
    purpose = repo_meta["purpose"]
    features = repo_meta.get("owns_features", [])

    top_dirs = list_top_dirs(repo_path)
    top_dirs_for_display = top_dirs[:TOP_DIRS_LIMIT]
    stack_files = detected_stack(repo_path)
    n_files, ext_counts = language_breakdown(repo_path)
    dir_file_counts = src_file_count_per_dir(repo_path, top_dirs)
    commits = recent_commits(repo_path)
    remote_url = get_remote_url(repo_path)

    readme_path = find_readme(repo_path)
    readme_excerpt = ""
    if readme_path:
        try:
            readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
            readme_excerpt = readme_text[:README_MAX_BYTES].strip()
            if len(readme_text) > README_MAX_BYTES:
                readme_excerpt += "\n\n... (truncated)"
        except Exception:
            readme_excerpt = ""

    # ── Compose markdown ───────────────────────────────────────────────
    lines = []
    lines.append(f"# `{name}` — repo skill (auto-generated)\n")
    lines.append(f"_Last refreshed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n")

    lines.append("## At a glance\n")
    lines.append(f"- **Owner team**: {team}")
    lines.append(f"- **Declared stack** (from repos.json): {stack_label}")
    lines.append(f"- **Production branch**: `{prod_branch}`")
    if remote_url:
        lines.append(f"- **Remote**: {remote_url}")
    lines.append(f"- **Source files** (filtered to relevant extensions): {n_files}")
    lines.append("")

    lines.append("**Stated purpose** (from manifest):")
    lines.append(f"> {purpose}")
    lines.append("")

    if features:
        lines.append("**Owns these features:**")
        for f in features:
            lines.append(f"- {f}")
        lines.append("")

    if stack_files:
        lines.append("## Build / dependency files present\n")
        for fname, label in stack_files:
            lines.append(f"- `{fname}` → {label}")
        lines.append("")

    if ext_counts:
        lines.append("## Language breakdown\n")
        lines.append("Source-file counts by extension (top 8):\n")
        for ext, n in ext_counts[:8]:
            lines.append(f"- `{ext}`: {n} files")
        lines.append("")

    if dir_file_counts:
        lines.append("## Top-level directories (by source-file count)\n")
        for d, n in dir_file_counts[:15]:
            lines.append(f"- `{d}/` — {n} source files")
        lines.append("")
        if len(dir_file_counts) > 15:
            lines.append(f"_(plus {len(dir_file_counts) - 15} more dirs)_\n")

    if commits:
        lines.append(f"## Recent commits ({len(commits)} most recent)\n")
        lines.append("| Date | Author | Subject |")
        lines.append("|---|---|---|")
        for date, author, subject in commits:
            # Escape pipe chars in subject so the markdown table doesn't break
            subj_escaped = subject.replace("|", "\\|")
            lines.append(f"| {date} | {author} | {subj_escaped[:120]} |")
        lines.append("")

    if readme_excerpt:
        lines.append("## README excerpt (first ~3 KB)\n")
        # Quote-wrap the README so it doesn't accidentally include code fences
        # that mess up the outer markdown.
        for ln in readme_excerpt.splitlines():
            lines.append(f"> {ln}" if ln else ">")
        lines.append("")

    lines.append("---\n")
    lines.append(
        "_This file is auto-generated by `build_repo_skills.py` from the live clone. "
        "Re-run that script to refresh._\n"
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repos", nargs="*",
        help="Specific repo names to process (default: all cloned)",
    )
    args = parser.parse_args()

    SKILLS_OUTPUT.mkdir(parents=True, exist_ok=True)

    with MANIFEST.open() as f:
        manifest = json.load(f)
    by_name = {r["name"]: r for r in manifest["repos"]}

    if args.repos:
        targets = args.repos
    else:
        targets = [d.name for d in CLONES_DIR.iterdir() if d.is_dir()]

    n_done = 0
    for name in targets:
        meta = by_name.get(name)
        if not meta:
            print(f"  ✗ {name}: not in manifest, skipping")
            continue
        repo_path = CLONES_DIR / name
        if not repo_path.exists():
            print(f"  ✗ {name}: not cloned (expected at {repo_path}), skipping")
            continue
        skill_md = make_skill(meta, repo_path)
        out = SKILLS_OUTPUT / f"{name}.md"
        out.write_text(skill_md, encoding="utf-8")
        print(f"  ✓ {name} → {out} ({len(skill_md)} bytes)")
        n_done += 1

    print()
    print(f"Generated {n_done} repo skill files in {SKILLS_OUTPUT}/")


if __name__ == "__main__":
    main()
