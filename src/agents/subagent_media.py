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

THE BUG REPORT EMAIL THE USER ALSO ATTACHED (verbatim):
---
{email_text}
---

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
                       "contradicts_email_claim": "<see CONTRADICTION DETECTION below>"}},
  "one_line_summary": "Single sentence that captures the bug evidence from this image."
}}

CONTRADICTION DETECTION (very important)
Compare what the email describes to what the image actually shows, and set `contradicts_email_claim` AGGRESSIVELY. Set it to a one-sentence description of the mismatch in any of these cases:

  • The image shows a different SLAP screen / feature than the one the email is about.
    Example: email is about "Checkout / Proceed to Pay crash" but the image shows "Phone login / OTP" — contradicts_email_claim should say "Email reports a checkout-flow crash but the attached image is the phone-login screen with an OTP error — different feature areas."

  • The image shows no anomaly / a normal happy-path state while the email claims something is broken.
  • The image shows a different platform than the email states (e.g. email says Android, image shows iOS — or vice versa).
  • The image's visible error message or symptom does not match the symptom the email describes.

Only set `contradicts_email_claim` to null when the image evidence clearly supports or is plausibly relevant to what the email is describing. When in doubt, FLAG IT — a triage analyst can override a false flag, but a missed contradiction wastes engineering time on the wrong bug.

Reply with ONLY a JSON object of the form:

{{
  "findings":         [ <one entry per attachment, in the same order> ],
  "combined_summary": "1-3 sentence aggregate across ALL attachments — what the images jointly tell us about the bug, and whether they agree with the email"
}}

No markdown fences, no commentary outside the JSON."""


def _list_images_in_folder(folder: Path) -> list:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def process_attachments(image_paths: list, email_text: str = "") -> MediaResult:
    """
    Analyze a list of image paths (absolute or relative). Returns MediaResult
    with per-image findings + a combined summary the host agent folds into
    the bug description before parsing.

    `email_text` is the verbatim bug-report email body. The sub-agent uses
    it to detect contradictions between what the reporter wrote and what
    the screenshots actually show. Pass an empty string only when no email
    body exists.

    If image_paths is empty, returns an empty MediaResult immediately.
    """
    if not image_paths:
        return MediaResult(findings=[], combined_summary="")

    abs_paths = [str(Path(p).resolve()) for p in image_paths]
    image_list_str = "\n".join(f"  - {p}" for p in abs_paths)

    prompt = PROMPT_TEMPLATE.format(
        knowledge_path  = str(SLAP_KNOWLEDGE),
        reference_dir   = str(REFERENCE_SCREENS),
        email_text      = (email_text or "(no email body provided)").strip(),
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
    """Convenience wrapper: find images + email.txt inside a bug folder and process."""
    images   = _list_images_in_folder(bug_folder)
    email_p  = bug_folder / "email.txt"
    email_t  = email_p.read_text(encoding="utf-8") if email_p.exists() else ""
    return process_attachments(images, email_text=email_t)
