"""
claude_cli.py — Thin wrapper around `claude -p` for non-interactive LLM calls.

Uses Claude Code's headless mode, which is already authenticated via your
signed-in account. No ANTHROPIC_API_KEY required.

Each call spawns a fresh `claude -p` subprocess with --output-format json.
The wrapper:
  1. Parses the outer JSON envelope.
  2. Strips ```json … ``` fences from the inner `result` text if present.
  3. Returns either parsed JSON (expect_json=True) or raw text.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Sequence


def _find_claude_bin() -> str:
    """
    Locate a working `claude` binary, in order of preference:

    1. CLAUDE_BIN environment variable (escape hatch — wins if set).
    2. `claude` resolvable on PATH and executable.
    3. Bundled CLI inside Claude Desktop's data directory
       (~/Library/Application Support/Claude/claude-code/<ver>/claude.app/...)
       — survives corp endpoint security that deletes Homebrew-installed
       binaries.
    4. Fall back to bare "claude" so subprocess raises a clear error.
    """
    override = os.environ.get("CLAUDE_BIN")
    if override:
        return override

    on_path = shutil.which("claude")
    if on_path and os.access(on_path, os.X_OK):
        return on_path

    bundled_root = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    if bundled_root.is_dir():
        for version_dir in sorted(bundled_root.iterdir(), reverse=True):
            candidate = version_dir / "claude.app" / "Contents" / "MacOS" / "claude"
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

    return "claude"


CLAUDE_BIN      = _find_claude_bin()
DEFAULT_TIMEOUT = 180   # seconds — large-context similarity calls can take ~30s

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


class ClaudeCallError(RuntimeError):
    """Raised when the `claude -p` subprocess fails or returns unparseable output."""


def call_claude(
    prompt: str,
    expect_json: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
    add_dirs: Optional[Sequence[str]] = None,
    allowed_tools: Optional[Sequence[str]] = None,
) -> Any:
    """
    Run `claude -p <prompt> --output-format json` and return the result.

    Args:
        prompt:        The full prompt text to send.
        expect_json:   If True, parse Claude's response as JSON (strip code
                       fences first). If False, return the raw text.
        timeout:       Max seconds to wait for the subprocess.
        add_dirs:      Optional list of directories to expose to Claude via
                       --add-dir (required for the media sub-agent so the
                       Read tool can load image attachments).
        allowed_tools: Optional list of tools to allow (e.g. ["Read"] when
                       processing images). When omitted Claude uses its
                       default allow-list.

    Returns:
        Parsed JSON object (dict/list) when expect_json=True, else str.

    Raises:
        ClaudeCallError when the subprocess fails or output is unparseable.
    """
    cmd: list[str] = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if add_dirs:
        for d in add_dirs:
            cmd.extend(["--add-dir", d])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeCallError(f"claude -p timed out after {timeout}s")
    except subprocess.CalledProcessError as e:
        raise ClaudeCallError(
            f"claude -p exited {e.returncode}: {(e.stderr or e.stdout or '').strip()[:500]}"
        )

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCallError(
            f"Could not parse Claude envelope as JSON: {e}\n{proc.stdout[:500]}"
        )

    if envelope.get("is_error"):
        raise ClaudeCallError(
            f"Claude reported error: {envelope.get('api_error_status') or envelope.get('result')}"
        )

    result_text = (envelope.get("result") or "").strip()

    if not expect_json:
        return result_text

    fenced = _FENCE_RE.match(result_text)
    if fenced:
        result_text = fenced.group(1).strip()

    try:
        return json.loads(result_text)
    except json.JSONDecodeError as e:
        raise ClaudeCallError(
            f"Could not parse Claude result as JSON: {e}\nRaw (first 500 chars): {result_text[:500]}"
        )
