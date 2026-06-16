"""
subagent_media.py — Image-attachment sub-agent (v1: images only).

Takes a bug folder (or an explicit list of image paths), loads the SLAP
knowledge doc + reference screens, and asks Claude vision (via headless
`claude -p` with --add-dir + the Read tool) to identify each image,
extract visible text, spot anomalies, and produce a one-line summary
that the host agent folds into the bug description before parsing.

The sub-agent is invoked only when attachments are present — text-only
bugs skip it entirely.

Future iterations will add audio (Whisper transcription) and video
(keyframe extraction + audio transcript) without changing this contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..claude_cli import call_claude

PROJECT_ROOT     = Path(__file__).resolve().parent.parent.parent
SLAP_CONTEXT_DIR = PROJECT_ROOT / "slap_context"
SLAP_KNOWLEDGE   = SLAP_CONTEXT_DIR / "SLAP_KNOWLEDGE.md"
REFERENCE_SCREENS = SLAP_CONTEXT_DIR / "reference_screens"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass
class MediaFinding:
    image_path:       str
    screen:           str
    state:            str
    visible_text:     list = field(default_factory=list)
    error_indicators: list = field(default_factory=list)
    ui_anomalies:     list = field(default_factory=list)
    device_hints:     dict = field(default_factory=dict)
    triage_signals:   dict = field(default_factory=dict)
    one_line_summary: str = ""


@dataclass
class MediaResult:
    findings:         list                 # list[MediaFinding]
    combined_summary: str                  # folded into bug description
    raw_response:     Optional[dict] = None


PROMPT_TEMPLATE = """You are the SLAP media-processor sub-agent. You analyze image attachments from bug reports about Flipkart's SLAP conversational shopping app.

You have access to two things via the Read tool:

1. The SLAP knowledge document (terminology, screen catalog, visual cues that flip triage decisions). Read it FIRST:
     {knowledge_path}

2. Labeled canonical reference screens from the SLAP Figma file. Each filename is a screen label. Browse them as needed when you need to confirm which screen an attachment shows:
     {reference_dir}/

After reading the knowledge doc, analyze EACH of the following bug attachment image(s):
{bug_image_paths}

For EACH attachment, produce a JSON object with this exact shape:

{{
  "image_path":       "<path of the image you analyzed>",
  "screen":           "<SLAP screen name from the catalog, or 'unknown'>",
  "state":            "normal | loading | error | empty | unknown",
  "visible_text":     ["literal strings extracted from the image"],
  "error_indicators": ["specific error messages or visual error states"],
  "ui_anomalies":     ["specific things that look wrong, missing, or out of place"],
  "device_hints":     {{"platform": "Android | iOS | unknown", "os_visible": "..." | null, "app_version_visible": "..." | null}},
  "triage_signals":   {{"likely_component": "Backend | Backend-Labs | DS | UI | immersive | bugs",
                       "severity_hint":    "P0 | P1 | P2 | P3",
                       "contradicts_email_claim": "string or null"}},
  "one_line_summary": "Single sentence that captures the bug evidence from this image."
}}

Reply with ONLY a JSON object of the form:

{{
  "findings":         [ <one entry per attachment, in the same order> ],
  "combined_summary": "1-3 sentence aggregate across ALL attachments — what the images jointly tell us about the bug"
}}

No markdown fences, no commentary outside the JSON."""


def _list_images_in_folder(folder: Path) -> list:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def process_attachments(image_paths: list) -> MediaResult:
    """
    Analyze a list of image paths (absolute or relative). Returns MediaResult
    with per-image findings + a combined summary the host agent folds into
    the bug description before parsing.

    If image_paths is empty, returns an empty MediaResult immediately.
    """
    if not image_paths:
        return MediaResult(findings=[], combined_summary="")

    abs_paths = [str(Path(p).resolve()) for p in image_paths]
    image_list_str = "\n".join(f"  - {p}" for p in abs_paths)

    prompt = PROMPT_TEMPLATE.format(
        knowledge_path  = str(SLAP_KNOWLEDGE),
        reference_dir   = str(REFERENCE_SCREENS),
        bug_image_paths = image_list_str,
    )

    # Grant Claude access to: SLAP context + each image's parent folder.
    add_dirs = [str(SLAP_CONTEXT_DIR)]
    for p in abs_paths:
        parent = str(Path(p).parent)
        if parent not in add_dirs:
            add_dirs.append(parent)

    response = call_claude(
        prompt,
        expect_json=True,
        timeout=300,
        add_dirs=add_dirs,
        allowed_tools=["Read", "Glob"],
    )

    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent returned non-object: {type(response).__name__}")

    findings = []
    for entry in response.get("findings") or []:
        findings.append(MediaFinding(
            image_path       = entry.get("image_path", ""),
            screen           = entry.get("screen", "unknown"),
            state            = entry.get("state", "unknown"),
            visible_text     = entry.get("visible_text") or [],
            error_indicators = entry.get("error_indicators") or [],
            ui_anomalies     = entry.get("ui_anomalies") or [],
            device_hints     = entry.get("device_hints") or {},
            triage_signals   = entry.get("triage_signals") or {},
            one_line_summary = entry.get("one_line_summary", ""),
        ))

    return MediaResult(
        findings         = findings,
        combined_summary = response.get("combined_summary", ""),
        raw_response     = response,
    )


def process_bug_folder(bug_folder: Path) -> MediaResult:
    """Convenience wrapper: find images inside a bug folder and process them."""
    images = _list_images_in_folder(bug_folder)
    return process_attachments(images)
