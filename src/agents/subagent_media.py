"""
subagent_media.py — Media-attachment sub-agent (images + videos).

Takes a list of attachment paths and dispatches internally:

  - Images (.png .jpg .jpeg .webp .gif)
      Single Claude call analyses all images at once. Each image
      becomes one MediaFinding.

  - Videos (.mp4 .mov .webm .avi .mkv)
      Per-video pre-processing extracts keyframes via ffmpeg (scene
      detection, capped at MAX_KEYFRAMES, with even-spacing fallback).
      Each video gets its own Claude call so the prompt can reason
      about the frames as a SEQUENCE, not as independent stills. Audio
      transcription is intentionally NOT done in this iteration.

Videos longer than MAX_VIDEO_DURATION_SECONDS are not pre-processed —
they become a "rejected" MediaFinding with a clear one_line_summary
so the reviewer sees the cap was hit instead of getting silent failure.

Output type — MediaFinding — is the same for both kinds (the `kind`
field distinguishes them). Downstream stages (parser/embeddings/dedup/
triage) read the combined_summary from MediaResult and never care
about the attachment type.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..claude_cli import call_claude

PROJECT_ROOT      = Path(__file__).resolve().parent.parent.parent
SLAP_CONTEXT_DIR  = PROJECT_ROOT / "slap_context"
SLAP_KNOWLEDGE    = SLAP_CONTEXT_DIR / "SLAP_KNOWLEDGE.md"
REFERENCE_SCREENS = SLAP_CONTEXT_DIR / "reference_screens"

IMAGE_EXTENSIONS  = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXTENSIONS  = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"}
MEDIA_EXTENSIONS  = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

MAX_VIDEO_DURATION_SECONDS = 60
MAX_KEYFRAMES              = 8
SCENE_DETECT_THRESHOLD     = 0.30   # 0.0–1.0; 0.3 picks up screen transitions, dialog opens, etc.


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class MediaFinding:
    image_path:       str                                   # original attachment path (image or video)
    screen:           str
    state:            str
    visible_text:     list = field(default_factory=list)
    error_indicators: list = field(default_factory=list)
    ui_anomalies:     list = field(default_factory=list)
    device_hints:     dict = field(default_factory=dict)
    triage_signals:   dict = field(default_factory=dict)
    one_line_summary: str = ""
    # Optional fields populated for videos:
    kind:             str = "image"                          # "image" | "video"
    frame_count:      int = 0
    duration_seconds: float = 0.0
    screen_sequence:  list = field(default_factory=list)
    action_observed:  str = ""
    failure_moment:   Optional[str] = None
    frames:           list = field(default_factory=list)     # paths to extracted keyframes (for UI display)


@dataclass
class MediaResult:
    findings:         list                                   # list[MediaFinding]
    combined_summary: str                                    # folded into bug description
    raw_response:     Optional[dict] = None


# ── Type helpers ───────────────────────────────────────────────────────────

def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _list_media_in_folder(folder: Path) -> list:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    )


# ── ffmpeg helpers ─────────────────────────────────────────────────────────

def _ffmpeg_path() -> str:
    """
    Lazy lookup of the ffmpeg binary shipped with `imageio-ffmpeg`. We don't
    rely on a system ffmpeg because corp endpoint security has been deleting
    fresh brew-installed binaries; the imageio bundle lives inside the
    site-packages dir, which the agents don't touch.
    """
    try:
        import imageio_ffmpeg
    except ImportError as e:
        raise RuntimeError(
            "imageio-ffmpeg is required to process video attachments. "
            "Run: pip install imageio-ffmpeg"
        ) from e
    return imageio_ffmpeg.get_ffmpeg_exe()


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


def _probe_video_duration(video_path: str) -> float:
    """Return duration in seconds by parsing ffmpeg's stderr."""
    proc = subprocess.run(
        [_ffmpeg_path(), "-i", str(video_path)],
        capture_output=True, text=True,
    )
    m = _DURATION_RE.search(proc.stderr or "")
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return float(h) * 3600 + float(mn) * 60 + float(s)


def _extract_keyframes(video_path: str, out_dir: Path, max_frames: int = MAX_KEYFRAMES) -> list:
    """
    Extract up to max_frames keyframes from the video, in temporal order.

    Strategy:
      1. Scene-detection pass: keep frames where ≥30% of pixels change.
         Cap output count at max_frames.
      2. If scene-detection returned nothing (very static video), fall
         back to evenly-spaced sampling.

    Frames are written as PNG to out_dir/frame_NN.png.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%02d.png")

    # Pass 1: scene-change detection (preferred — captures the moments
    # that matter on a phone-screen recording).
    subprocess.run(
        [
            _ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", f"select='gt(scene,{SCENE_DETECT_THRESHOLD})',scale=512:-1",
            "-vsync", "vfr",
            "-frames:v", str(max_frames),
            pattern,
        ],
        capture_output=True,
    )
    frames = sorted(out_dir.glob("frame_*.png"))
    if frames:
        return frames

    # Pass 2: evenly-spaced fallback for static videos.
    duration = _probe_video_duration(str(video_path))
    if duration <= 0:
        return []
    n = min(max_frames, max(2, int(duration / 1.5)))     # ~1 frame per 1.5s
    fps = max(0.1, n / duration)
    subprocess.run(
        [
            _ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", f"fps={fps},scale=512:-1",
            "-frames:v", str(n),
            pattern,
        ],
        capture_output=True,
    )
    return sorted(out_dir.glob("frame_*.png"))


# ── Image prompt + processing (unchanged) ─────────────────────────────────

IMAGE_PROMPT_TEMPLATE = """You are the SLAP media-processor sub-agent. You analyze image attachments from bug reports about Flipkart's SLAP conversational shopping app.

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


def _process_images(image_paths: list, email_text: str) -> tuple:
    """
    Returns (findings: list[MediaFinding], combined_summary: str, raw: dict).
    """
    abs_paths = [str(Path(p).resolve()) for p in image_paths]
    image_list_str = "\n".join(f"  - {p}" for p in abs_paths)

    prompt = IMAGE_PROMPT_TEMPLATE.format(
        knowledge_path  = str(SLAP_KNOWLEDGE),
        reference_dir   = str(REFERENCE_SCREENS),
        email_text      = (email_text or "(no email body provided)").strip(),
        bug_image_paths = image_list_str,
    )

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
        raise ValueError(f"Media sub-agent (images) returned non-object: {type(response).__name__}")

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
            kind             = "image",
        ))
    return findings, response.get("combined_summary", ""), response


# ── Video prompt + processing ──────────────────────────────────────────────

VIDEO_PROMPT_TEMPLATE = """You are the SLAP media-processor sub-agent. You are analysing a BUG-REPORT VIDEO from Flipkart's SLAP conversational shopping app.

We pre-extracted {frame_count} keyframes in temporal order from a {duration:.1f}-second clip. Read each one with the Read tool:

{frames_listing}

You also have access via Read:
  - SLAP knowledge document : {knowledge_path}
  - Canonical reference screens : {reference_dir}/

THE BUG REPORT EMAIL THE USER ALSO ATTACHED (verbatim):
---
{email_text}
---

Reason about the SEQUENCE — what action does the user take, what screens appear, where is the failure moment (if any), what's the final state? Do NOT return one finding per frame; return ONE JSON object that describes the whole video:

{{
  "screen":           "<most-prominent SLAP screen, or 'multi-screen flow'>",
  "state":            "normal | loading | error | empty | unknown",
  "screen_sequence":  ["screen name at frame 1", "frame 2", ...],
  "action_observed":  "single-sentence narrative of what the user does in the clip",
  "failure_moment":   "frame N + description of the failure" or null,
  "visible_text":     ["literal strings extracted across the frames"],
  "error_indicators": ["specific error messages or visual error states observed in any frame"],
  "ui_anomalies":     ["specific things that look wrong, missing, or out of place"],
  "device_hints":     {{"platform": "Android | iOS | unknown", "os_visible": "..." | null, "app_version_visible": "..." | null}},
  "triage_signals":   {{"likely_component": "Backend | Backend-Labs | DS | UI | immersive | bugs",
                       "severity_hint":    "P0 | P1 | P2 | P3",
                       "contradicts_email_claim": "<see CONTRADICTION DETECTION below>"}},
  "one_line_summary": "Single sentence — the most useful description of the bug captured in this video."
}}

CONTRADICTION DETECTION (very important)
Set `contradicts_email_claim` AGGRESSIVELY when the video does not show what the email describes. Examples:
  • Email is about "Checkout crash" but the video shows the user browsing the chat home page.
  • Email claims P0 outage but the video shows the app working normally (no error frames).
  • Email says Android but video clearly shows iOS, or vice versa.

Set to null only when the video genuinely supports the email. When in doubt, FLAG IT — a missed contradiction wastes engineering time.

Reply with ONLY the JSON object — no markdown fences, no prose outside it."""


def _process_one_video(video_path: str, email_text: str) -> MediaFinding:
    """
    Pre-process a single video (probe → extract keyframes), then call Claude
    on the keyframe sequence. Returns one MediaFinding describing the whole
    video. Frames are extracted into a tempdir whose path is stored on the
    finding so the UI can display them later.
    """
    video_path = str(Path(video_path).resolve())
    duration   = _probe_video_duration(video_path)

    # Reject videos that exceed the cap — no Claude call wasted, clear UX.
    if duration > MAX_VIDEO_DURATION_SECONDS:
        return MediaFinding(
            image_path=video_path,
            kind="video",
            duration_seconds=duration,
            screen="(video rejected)",
            state="rejected",
            one_line_summary=(
                f"Video is {duration:.1f}s long — exceeds the {MAX_VIDEO_DURATION_SECONDS}s "
                "cap. Please trim to the failure moment and refile."
            ),
            triage_signals={"contradicts_email_claim": None},
        )

    # Extract keyframes into a long-lived tempdir (we DON'T context-manage it
    # because the UI may want to read those PNGs later in the same session).
    frames_dir = Path(tempfile.mkdtemp(prefix="slap_video_frames_"))
    frame_paths = _extract_keyframes(video_path, frames_dir, MAX_KEYFRAMES)

    if not frame_paths:
        return MediaFinding(
            image_path=video_path,
            kind="video",
            duration_seconds=duration,
            screen="(extraction failed)",
            state="error",
            one_line_summary=(
                "Could not extract keyframes from the attached video — the file "
                "may be corrupt or in an unsupported format. Please re-upload "
                "as MP4 / MOV / WEBM."
            ),
            triage_signals={"contradicts_email_claim": None},
        )

    # Build the prompt with the frames in temporal order.
    frames_listing = "\n".join(
        f"  Frame {i+1} of {len(frame_paths)}: {p}"
        for i, p in enumerate(frame_paths)
    )

    prompt = VIDEO_PROMPT_TEMPLATE.format(
        frame_count    = len(frame_paths),
        duration       = duration,
        frames_listing = frames_listing,
        knowledge_path = str(SLAP_KNOWLEDGE),
        reference_dir  = str(REFERENCE_SCREENS),
        email_text     = (email_text or "(no email body provided)").strip(),
    )

    add_dirs = [str(SLAP_CONTEXT_DIR), str(frames_dir)]
    response = call_claude(
        prompt,
        expect_json=True,
        timeout=360,
        add_dirs=add_dirs,
        allowed_tools=["Read", "Glob"],
    )
    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent (video) returned non-object: {type(response).__name__}")

    return MediaFinding(
        image_path       = video_path,
        screen           = response.get("screen", "unknown"),
        state            = response.get("state", "unknown"),
        visible_text     = response.get("visible_text") or [],
        error_indicators = response.get("error_indicators") or [],
        ui_anomalies     = response.get("ui_anomalies") or [],
        device_hints     = response.get("device_hints") or {},
        triage_signals   = response.get("triage_signals") or {},
        one_line_summary = response.get("one_line_summary", ""),
        kind             = "video",
        frame_count      = len(frame_paths),
        duration_seconds = duration,
        screen_sequence  = response.get("screen_sequence") or [],
        action_observed  = response.get("action_observed", ""),
        failure_moment   = response.get("failure_moment"),
        frames           = [str(p) for p in frame_paths],
    )


# ── Public API ─────────────────────────────────────────────────────────────

def process_attachments(paths: list, email_text: str = "") -> MediaResult:
    """
    Analyse a list of attachment paths (images and/or videos) and return a
    MediaResult. Images are batched into one Claude call; each video gets
    its own call so the prompt can reason about the keyframe sequence.

    If `paths` is empty, returns an empty MediaResult immediately.
    """
    if not paths:
        return MediaResult(findings=[], combined_summary="")

    path_objs    = [Path(p) for p in paths]
    image_paths  = [str(p) for p in path_objs if _is_image(p)]
    video_paths  = [str(p) for p in path_objs if _is_video(p)]

    findings: list[MediaFinding] = []
    image_combined_summary       = ""
    raw_responses: list[dict]    = []

    if image_paths:
        image_findings, image_combined_summary, image_raw = _process_images(image_paths, email_text)
        findings.extend(image_findings)
        if image_raw:
            raw_responses.append(image_raw)

    for vp in video_paths:
        video_finding = _process_one_video(vp, email_text)
        findings.append(video_finding)

    # Build a unified combined_summary across images + videos. We use the
    # image batch's combined_summary (when present) and append each video's
    # one-line summary — gives the parser useful context without another
    # Claude round-trip.
    summary_parts: list[str] = []
    if image_combined_summary:
        summary_parts.append(image_combined_summary.strip())
    for f in findings:
        if f.kind == "video" and f.one_line_summary:
            summary_parts.append(f"[Video {Path(f.image_path).name}] {f.one_line_summary}")
    combined_summary = " ".join(p for p in summary_parts if p)

    return MediaResult(
        findings         = findings,
        combined_summary = combined_summary,
        raw_response     = raw_responses[0] if raw_responses else None,
    )


def process_bug_folder(bug_folder: Path) -> MediaResult:
    """Convenience wrapper: find images + videos + email.txt inside a folder."""
    media   = _list_media_in_folder(bug_folder)
    email_p = bug_folder / "email.txt"
    email_t = email_p.read_text(encoding="utf-8") if email_p.exists() else ""
    return process_attachments([str(p) for p in media], email_text=email_t)
