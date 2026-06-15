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
import re
import subprocess
from typing import Any

CLAUDE_BIN      = "claude"
DEFAULT_TIMEOUT = 180   # seconds — large-context similarity calls can take ~30s

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


class ClaudeCallError(RuntimeError):
    """Raised when the `claude -p` subprocess fails or returns unparseable output."""


def call_claude(
    prompt: str,
    expect_json: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """
    Run `claude -p <prompt> --output-format json` and return the result.

    Args:
        prompt:       The full prompt text to send.
        expect_json:  If True, parse Claude's response as JSON (strip code
                      fences first). If False, return the raw text.
        timeout:      Max seconds to wait for the subprocess.

    Returns:
        Parsed JSON object (dict/list) when expect_json=True, else str.

    Raises:
        ClaudeCallError when the subprocess fails or output is unparseable.
    """
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--output-format", "json"],
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
