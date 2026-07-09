"""
repo_context.py — Repo-aware context system for SLAP code repos.

Prototype-level shim for the production architecture (per-repo K8s indexers
writing to a namespaced Vector One index). Same conceptual shape, much
lighter implementation:

    Production               Prototype equivalent
    ──────────────────────   ────────────────────────────────────
    K8s indexer workers      One Python script, all repos local
    Vector One (shared)      Per-repo .npz + sqlite for symbols
    Cryptex-managed token    GITHUB_FK_TOKEN env var
    GitHub webhook push      Manual `python3 reindex_repos.py`
    tree-sitter + LSP        File-tree walk + Python AST + regex
    Per-repo agent           One RepoContextEngine instance / repo
    Agentic search fallback  `git grep` over local clone

The prototype is gated on the github.fkinternal.com token. Until that's
configured, this module exposes only the metadata layer (repos.json) and
helper functions that don't require code access. The clone/index pieces
are stubbed with clear TODOs.

Wire-up checklist (when GITHUB_FK_TOKEN is available):
    1. Add `GITHUB_FK_TOKEN=...` to .env
    2. Run `python3 reindex_repos.py` (creates data/repos/<repo>/...)
    3. EmbeddingClassifier loads the per-repo indexes alongside the
       bug-similarity index
    4. Classifier's Claude fallback can now grep across repos for
       borderline cases
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


GITHUB_BASE_URL = "https://github.fkinternal.com"
GITHUB_TOKEN_ENV = "GITHUB_FK_TOKEN"
REPOS_MANIFEST_PATH = Path(__file__).parent.parent / "slap_context" / "architecture" / "repos.json"
REPOS_CACHE_DIR     = Path(__file__).parent.parent / "data" / "repos"


@dataclass
class RepoMeta:
    name:          str
    team:          str
    stack:         str
    prod_branch:   str
    freshness:     str        # "warm" or "lazy"
    purpose:       str
    owns_features: list


# ── Manifest loader ─────────────────────────────────────────────────────

_manifest_cache: Optional[dict] = None


def load_manifest() -> dict:
    """Load repos.json. Caches in-process so we don't re-read on every call."""
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache
    with REPOS_MANIFEST_PATH.open() as f:
        _manifest_cache = json.load(f)
    return _manifest_cache


def all_repos() -> list[RepoMeta]:
    """Return the full list of SLAP repos with their metadata."""
    return [
        RepoMeta(
            name          = r["name"],
            team          = r["team"],
            stack         = r["stack"],
            prod_branch   = r["prod_branch"],
            freshness     = r["freshness"],
            purpose       = r["purpose"],
            owns_features = r.get("owns_features", []),
        )
        for r in load_manifest()["repos"]
    ]


def repos_for_team(team: str) -> list[RepoMeta]:
    """Return all repos owned by `team` (matched against the `team` field in repos.json)."""
    return [r for r in all_repos() if r.team == team]


# ── Token / availability check ──────────────────────────────────────────

def github_token() -> Optional[str]:
    """Return the GitHub Enterprise token if configured, else None."""
    return os.environ.get(GITHUB_TOKEN_ENV)


def has_repo_access() -> bool:
    """Quick check: do we have what we need to clone from github.fkinternal.com?"""
    return github_token() is not None


# ── Clone + index (prototype-level stubs) ───────────────────────────────

def clone_repo(repo: RepoMeta, dest: Path) -> bool:
    """
    Clone `repo` to `dest` at the configured prod_branch.

    Returns True on success, False on any failure (auth, network, missing
    branch). Never raises — caller decides what to do.
    """
    token = github_token()
    if not token:
        print(f"  [repo_context] no {GITHUB_TOKEN_ENV} configured — can't clone {repo.name}")
        return False

    # The Flipkart org name on github.fkinternal.com isn't in our manifest.
    # When the user supplies a token, they should also set GITHUB_FK_ORG.
    # Until then, this is a stub that documents the URL shape.
    org = os.environ.get("GITHUB_FK_ORG", "<org>")
    clone_url = f"https://x-access-token:{token}@github.fkinternal.com/{org}/{repo.name}.git"

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # Already cloned — fetch + checkout prod_branch
        cmds = [
            ["git", "-C", str(dest), "fetch", "origin", repo.prod_branch],
            ["git", "-C", str(dest), "checkout", repo.prod_branch],
            ["git", "-C", str(dest), "reset", "--hard", f"origin/{repo.prod_branch}"],
        ]
    else:
        cmds = [
            ["git", "clone", "--branch", repo.prod_branch, "--depth", "1", clone_url, str(dest)],
        ]
    try:
        for c in cmds:
            subprocess.run(c, check=True, capture_output=True, timeout=300)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [repo_context] clone/update failed for {repo.name}: {e}")
        return False


def structural_map(repo_path: Path) -> dict:
    """
    Build a lightweight structural map of a cloned repo. Production uses
    tree-sitter + LSP; the prototype just walks the file tree and lists
    top-level dirs / files. Good enough to seed Claude with "what's in this
    repo" without actually reading every file.

    Returns:
        {
          "n_files":   int,
          "top_dirs":  [str],
          "languages": [(ext, count)],
          "entry_points": [str],   # likely entry files (package.json, main.go, etc.)
        }
    """
    if not repo_path.exists():
        return {}

    n_files = 0
    by_ext: dict = {}
    top_dirs = []
    entry_points = []

    for p in repo_path.iterdir():
        if p.name.startswith("."):
            continue
        if p.is_dir():
            top_dirs.append(p.name)
        elif p.name in {"package.json", "build.gradle", "pom.xml", "setup.py", "pyproject.toml", "go.mod", "Cargo.toml"}:
            entry_points.append(p.name)

    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        # Skip noise
        rel = p.relative_to(repo_path)
        if any(part.startswith(".") or part in {"node_modules", "build", "dist", "__pycache__"} for part in rel.parts):
            continue
        n_files += 1
        ext = p.suffix.lower()
        if ext:
            by_ext[ext] = by_ext.get(ext, 0) + 1

    return {
        "n_files":      n_files,
        "top_dirs":     sorted(top_dirs)[:20],
        "languages":    sorted(by_ext.items(), key=lambda kv: -kv[1])[:8],
        "entry_points": entry_points,
    }


def grep_repo(repo_path: Path, query: str, max_results: int = 20) -> list:
    """
    Live agentic search over a local repo clone using ripgrep / git grep.

    This is the "always-correct" fallback path from the prod spec — even
    when no index exists for this repo, we can grep over a fresh clone.
    Returns a list of (file_path_relative, line_no, line_text) tuples.
    """
    if not repo_path.exists():
        return []

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "grep", "-n", "-i", "--max-count", "5", query],
            capture_output=True, timeout=30, text=True,
        )
        lines = result.stdout.splitlines()[:max_results]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []

    out = []
    for line in lines:
        # `git grep -n` output: path:line:content
        parts = line.split(":", 2)
        if len(parts) >= 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


# ── Status reporter for diagnostics ─────────────────────────────────────

def report_status() -> str:
    """Print a one-shot status of the repo-context system. Useful from CLI."""
    lines = []
    lines.append(f"GitHub Enterprise base URL: {GITHUB_BASE_URL}")
    lines.append(f"Token configured ({GITHUB_TOKEN_ENV}): {'yes' if has_repo_access() else 'no'}")
    lines.append(f"Repos in manifest: {len(all_repos())}")
    by_team: dict = {}
    for r in all_repos():
        by_team.setdefault(r.team, []).append(r.name)
    for team, repos in sorted(by_team.items()):
        lines.append(f"  {team}: {', '.join(repos)}")
    lines.append("")
    lines.append("Local clones:")
    if REPOS_CACHE_DIR.exists():
        for d in sorted(REPOS_CACHE_DIR.iterdir()):
            if d.is_dir():
                lines.append(f"  {d.name}: cloned")
    else:
        lines.append(f"  (none — {REPOS_CACHE_DIR} doesn't exist yet)")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report_status())
