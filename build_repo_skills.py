#!/usr/bin/env python3
"""
build_repo_skills.py — Generate per-repo skill files from cloned code.

For each repo listed in slap_context/architecture/repos.json that we have
a local clone of (under data/repos/<repo>/), extract:

  - README.md content (first ~3 KB if present)
  - Top-level directory layout
  - Detected stack (from build files)
  - Last N commits on the prod branch
  - File extension breakdown
  - Source-file count per top-level dir
  - CODE MINING (added):
      * Service class names (Java: *Service.java; Python: 'class *Service')
      * Exception class names — the module's real error taxonomy
      * HTTP entry-point classes (Controller / Handler / Endpoint / Resource
        for Java; @app.route / @router.get style decorators for Python)
      * Enum class names — real status / state vocabulary
      * DTO / Request / Response class counts — data-contract surface
      * Spring routes: @GetMapping / @PostMapping / @RequestMapping paths
      * Config file inventory (application*.yml / .properties)

Write the result to slap_context/architecture/repos/<repo>.md.

These per-repo skills are the *actual* "what's in this code" files — not
hand-curated prose. They get included alongside the team-level skill files
when the classifier's Claude fallback needs to disambiguate.

Usage:
    python3 build_repo_skills.py            # process all cloned repos except HAND_AUTHORED
    python3 build_repo_skills.py dropsense  # process just one (bypasses HAND_AUTHORED)
"""

from __future__ import annotations

import argparse
import json
import re
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

README_MAX_BYTES     = 3_500
TOP_DIRS_LIMIT       = 25
N_RECENT_COMMITS     = 15
SYMBOLS_PER_DIR_LIMIT = 20    # keep the per-dir mined list tight

# Repos with hand-authored skill files that are richer than anything
# build_repo_skills.py can produce. Bulk-run skips these; passing the
# name explicitly on the CLI still regenerates them (so you can
# deliberately overwrite if you want to).
HAND_AUTHORED = {"spaghetti", "mozzarella"}

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


# ── Code mining ────────────────────────────────────────────────────────────
#
# Everything below inspects the actual .java / .py files inside the clone.
# All functions are best-effort and swallow errors — a repo that has
# neither Java nor Python still produces a skill file, it just has fewer
# sections.


def _files_by_glob(dpath: Path, patterns: list) -> list:
    """Union of files matching any of the glob patterns, recursive."""
    out: set = set()
    for pat in patterns:
        for p in dpath.rglob(pat):
            rel = p.relative_to(dpath)
            if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts):
                continue
            out.add(p)
    return sorted(out)


def _grep(patterns: list, path: Path, includes: list, timeout: int = 30) -> str:
    """Wrapper around system `grep` — much faster than pure-Python rglob+read
    on big Java trees. Returns stdout as text (empty on any error)."""
    if not path.exists():
        return ""
    cmd = ["grep", "-r", "-h"]
    for pat in patterns:
        cmd.extend(["-e", pat])
    for inc in includes:
        cmd.append(f"--include={inc}")
    cmd.append(str(path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def extract_java_symbols_per_dir(repo_path: Path, top_dirs: list) -> dict:
    """For each top-level dir, mine class-name inventories from .java files.

    Returns: {dir_name: {"services":[...], "exceptions":[...], "endpoints":[...],
                          "enums":[...], "dto_count": N}}
    """
    result: dict = {}
    enum_re = re.compile(r"public\s+enum\s+(\w+)")
    for d in top_dirs:
        dpath = repo_path / d
        if not dpath.exists():
            continue

        services   = sorted({f.stem for f in _files_by_glob(dpath, ["*Service.java"])})
        exceptions = sorted({f.stem for f in _files_by_glob(dpath, ["*Exception.java"])})
        endpoints  = sorted({f.stem for f in _files_by_glob(
            dpath, ["*Controller.java", "*Handler.java", "*Endpoint.java", "*Resource.java"],
        )})
        dtos       = _files_by_glob(dpath, ["*Dto.java", "*DTO.java",
                                            "*Request.java", "*Response.java"])
        # Enum names — one grep run for the whole dir
        enum_names = set()
        for line in _grep(["public enum "], dpath, ["*.java"]).splitlines():
            m = enum_re.search(line)
            if m:
                enum_names.add(m.group(1))

        # Skip dirs that have literally nothing mineable
        if not (services or exceptions or endpoints or dtos or enum_names):
            continue

        result[d] = {
            "services":   services[:SYMBOLS_PER_DIR_LIMIT],
            "exceptions": exceptions[:SYMBOLS_PER_DIR_LIMIT],
            "endpoints":  endpoints[:SYMBOLS_PER_DIR_LIMIT],
            "enums":      sorted(enum_names)[:SYMBOLS_PER_DIR_LIMIT],
            "dto_count":  len(dtos),
            "service_total":   len(services),
            "exception_total": len(exceptions),
            "endpoint_total":  len(endpoints),
            "enum_total":      len(enum_names),
        }
    return result


def extract_spring_routes(repo_path: Path) -> list:
    """Grep for @RequestMapping-family annotations and extract (verb, path)."""
    route_re = re.compile(
        r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)'
        r'\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']'
    )
    routes: set = set()
    stdout = _grep(
        [r"@GetMapping", r"@PostMapping", r"@PutMapping",
         r"@DeleteMapping", r"@PatchMapping", r"@RequestMapping"],
        repo_path, ["*.java"], timeout=45,
    )
    for line in stdout.splitlines():
        m = route_re.search(line)
        if m:
            verb, path = m.group(1), m.group(2).strip()
            if path:
                routes.add((verb.replace("Mapping", "").upper(), path))
    return sorted(routes, key=lambda t: t[1])


def extract_python_symbols_per_dir(repo_path: Path, top_dirs: list) -> dict:
    """For each top-level dir, mine class names from .py files.

    Returns: {dir_name: {"classes":[...], "exceptions":[...]}}
    """
    result: dict = {}
    class_re     = re.compile(r"^\s*class\s+(\w+)")
    exception_re = re.compile(r"^\s*class\s+(\w*(?:Exception|Error))\s*[\(:]")
    for d in top_dirs:
        dpath = repo_path / d
        if not dpath.exists():
            continue

        classes    = set()
        exceptions = set()
        stdout = _grep([r"^class "], dpath, ["*.py"])
        for line in stdout.splitlines():
            m = class_re.search(line)
            if m:
                name = m.group(1)
                classes.add(name)
                if exception_re.search(line):
                    exceptions.add(name)

        if not classes:
            continue

        # Trim the exception set out of the general classes list so we
        # don't show the same names twice.
        classes = classes - exceptions

        result[d] = {
            "classes":         sorted(classes)[:SYMBOLS_PER_DIR_LIMIT],
            "exceptions":      sorted(exceptions)[:SYMBOLS_PER_DIR_LIMIT],
            "class_total":     len(classes),
            "exception_total": len(exceptions),
        }
    return result


def extract_python_routes(repo_path: Path) -> list:
    """Grep for common HTTP-framework decorators (Flask / FastAPI / etc.)
    and pull out (verb, path) tuples."""
    route_re = re.compile(
        r'@\w+\.(route|get|post|put|delete|patch)'
        r'\s*\(\s*["\']([^"\']+)["\']'
    )
    routes: set = set()
    stdout = _grep([r"@\w\+\.(route\|get\|post\|put\|delete\|patch)"],
                   repo_path, ["*.py"], timeout=30)
    for line in stdout.splitlines():
        m = route_re.search(line)
        if m:
            verb = m.group(1).upper()
            if verb == "ROUTE":
                verb = "ANY"
            routes.add((verb, m.group(2).strip()))
    return sorted(routes, key=lambda t: t[1])


def find_config_files(repo_path: Path) -> list:
    """Locate Spring config files (relative paths only, no content)."""
    out = []
    for pattern in ("application.yml", "application.yaml",
                    "application-*.yml", "application-*.yaml",
                    "application.properties", "application-*.properties"):
        for p in repo_path.rglob(pattern):
            rel = p.relative_to(repo_path)
            if any(part in IGNORE_DIRS or part.startswith(".") for part in rel.parts):
                continue
            out.append(str(rel))
    return sorted(set(out))


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

    # Mine class-level symbols from the actual code so the skill file
    # has something reviewers can grep against, not just directory sizes.
    java_symbols   = extract_java_symbols_per_dir(repo_path, top_dirs)
    python_symbols = extract_python_symbols_per_dir(repo_path, top_dirs)
    spring_routes  = extract_spring_routes(repo_path)
    python_routes  = extract_python_routes(repo_path)
    config_files   = find_config_files(repo_path)

    # Precompute a lookup keyed by dir name for the enriched module map.
    dir_meta = {}
    for d, n in dir_file_counts[:15]:
        dir_meta[d] = {"files": n}
        if d in java_symbols:
            dir_meta[d]["java"] = java_symbols[d]
        if d in python_symbols:
            dir_meta[d]["py"] = python_symbols[d]

    if dir_meta:
        lines.append("## Module map — top directories with mined symbols\n")
        lines.append(
            "Symbols below are extracted from real class-file names / grep "
            "output on the current clone. Each list is capped to keep the "
            f"skill file readable (limit: {SYMBOLS_PER_DIR_LIMIT} per bucket)."
        )
        lines.append("")
        for d, meta in dir_meta.items():
            lines.append(f"### `{d}/` — {meta['files']} source files")
            java = meta.get("java")
            py   = meta.get("py")
            if java:
                if java["services"]:
                    total = java["service_total"]
                    shown = ", ".join(f"`{s}`" for s in java["services"])
                    more  = f" _(+{total - len(java['services'])} more)_" if total > len(java["services"]) else ""
                    lines.append(f"- **Services** ({total}): {shown}{more}")
                if java["endpoints"]:
                    total = java["endpoint_total"]
                    shown = ", ".join(f"`{s}`" for s in java["endpoints"])
                    more  = f" _(+{total - len(java['endpoints'])} more)_" if total > len(java["endpoints"]) else ""
                    lines.append(f"- **HTTP entry points** ({total}): {shown}{more}")
                if java["exceptions"]:
                    total = java["exception_total"]
                    shown = ", ".join(f"`{s}`" for s in java["exceptions"])
                    more  = f" _(+{total - len(java['exceptions'])} more)_" if total > len(java["exceptions"]) else ""
                    lines.append(f"- **Exceptions** ({total}): {shown}{more}")
                if java["enums"]:
                    total = java["enum_total"]
                    shown = ", ".join(f"`{s}`" for s in java["enums"])
                    more  = f" _(+{total - len(java['enums'])} more)_" if total > len(java["enums"]) else ""
                    lines.append(f"- **Enums** ({total}): {shown}{more}")
                if java["dto_count"]:
                    lines.append(f"- **Data contracts**: {java['dto_count']} DTO / Request / Response classes")
            if py:
                if py["classes"]:
                    total = py["class_total"]
                    shown = ", ".join(f"`{s}`" for s in py["classes"])
                    more  = f" _(+{total - len(py['classes'])} more)_" if total > len(py["classes"]) else ""
                    lines.append(f"- **Classes** ({total}): {shown}{more}")
                if py["exceptions"]:
                    total = py["exception_total"]
                    shown = ", ".join(f"`{s}`" for s in py["exceptions"])
                    more  = f" _(+{total - len(py['exceptions'])} more)_" if total > len(py["exceptions"]) else ""
                    lines.append(f"- **Exceptions** ({total}): {shown}{more}")
            lines.append("")
        if len(dir_file_counts) > 15:
            lines.append(f"_(plus {len(dir_file_counts) - 15} smaller dirs not shown)_\n")

    # HTTP routes across the whole repo — surfaces the actual API a service
    # exposes to callers, which is often the single most useful thing when
    # trying to understand what a Backend/BE-Labs repo is FOR.
    if spring_routes:
        lines.append(f"## HTTP routes ({len(spring_routes)} @*Mapping annotations found)\n")
        lines.append("| Verb | Path |")
        lines.append("|---|---|")
        for verb, path in spring_routes[:40]:
            lines.append(f"| `{verb}` | `{path}` |")
        if len(spring_routes) > 40:
            lines.append(f"| ... | _({len(spring_routes) - 40} more routes not shown)_ |")
        lines.append("")

    if python_routes:
        lines.append(f"## HTTP routes ({len(python_routes)} decorator-defined)\n")
        lines.append("| Verb | Path |")
        lines.append("|---|---|")
        for verb, path in python_routes[:40]:
            lines.append(f"| `{verb}` | `{path}` |")
        if len(python_routes) > 40:
            lines.append(f"| ... | _({len(python_routes) - 40} more routes not shown)_ |")
        lines.append("")

    if config_files:
        lines.append(f"## Config files present ({len(config_files)} Spring/YAML)\n")
        for c in config_files[:15]:
            lines.append(f"- `{c}`")
        if len(config_files) > 15:
            lines.append(f"- _(plus {len(config_files) - 15} more)_")
        lines.append("")

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

    explicit_targets = bool(args.repos)
    if explicit_targets:
        targets = args.repos
    else:
        targets = [d.name for d in CLONES_DIR.iterdir() if d.is_dir()]

    n_done    = 0
    n_skipped = 0
    for name in targets:
        # Skip hand-authored repos in bulk mode (spaghetti, mozzarella).
        # If the caller passed the name explicitly, honour that — this lets
        # you deliberately overwrite if you want to.
        if name in HAND_AUTHORED and not explicit_targets:
            print(f"  ⊘ {name}: hand-authored, skipping (pass explicitly to regenerate)")
            n_skipped += 1
            continue
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
