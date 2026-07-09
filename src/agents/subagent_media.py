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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable, Optional

from ..shared.claude_cli    import call_claude
from ..shared.genvoy_client import GeminiUnavailable, gemini_describe_image, is_configured as gemini_configured

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


# ── Image prompts ──────────────────────────────────────────────────────────
#
# Two-stage image flow (preferred):
#
#   Stage 1 — Gemini (vision)
#     Per-image, parallel. Free-prose description of what's visible on the
#     screen (text, UI elements, anomalies, device hints). No SLAP context
#     needed — Gemini just reports what it sees. ~2-3s per image, parallel.
#
#   Stage 2 — Claude (reasoning)
#     One call. Reads SLAP_KNOWLEDGE.md + reference_screens/ via the Read
#     tool, takes the Gemini descriptions as inline text, and emits the
#     structured MediaFinding JSON (screen label, triage signals, contra-
#     diction detection). Claude never has to load the actual image bytes
#     here — the vision pass already extracted everything visual.
#
# Fallback — single Claude call with image access (the legacy path,
# `IMAGE_PROMPT_TEMPLATE` below). Used when Gemini is unavailable
# (env vars unset, JWT expired, network unreachable off-corp, etc.).
#
# The host doesn't see any of this — `process_attachments()` returns the
# same MediaResult shape either way.

VISION_PROMPT = """You are looking at a screenshot from a mobile app (Flipkart's SLAP — a conversational shopping app). Describe what you see in plain prose. Be thorough — your output is passed to a downstream agent that does NOT see the image, so visual details matter.

Cover:
1. ALL visible text on the screen — labels, buttons, prices, headers, error messages, system status, placeholder text. Quote them verbatim wherever possible.
2. UI elements present (input fields, buttons, lists, cards, modals, images, navigation bars, chat bubbles) and the state of each (normal, loading, empty, disabled, error).
3. Visual anomalies — anything that looks broken, missing, clipped, misaligned, mis-rendered, wrongly coloured, overlapping, or out of place.
4. Device / platform hints — status-bar style, notch / home indicator, system font, navigation pattern. Note any visible OS version or app build number.
5. Apparent purpose of the screen (chat, search, product details, cart, checkout, login, profile, etc.) — best guess only, don't over-commit if unsure.

Reply in plain prose. No JSON, no markdown headers, no bullet lists — just descriptive sentences."""


REASONING_PROMPT_TEMPLATE = """You are the SLAP media-processor sub-agent's reasoning stage. A vision model has already inspected each bug-report attachment and produced a plain-prose description; YOUR job is to map those descriptions onto the SLAP screen catalog and emit structured triage findings.

You have access via the Read tool to:
  1. SLAP knowledge document : {knowledge_path}  (READ THIS FIRST — screen catalog, vocabulary, visual triage cues)
  2. Canonical reference screens : {reference_dir}/   (each filename is a screen label; use Glob to browse if you need to confirm which screen a description matches)

THE BUG REPORT EMAIL THE USER ALSO ATTACHED (verbatim):
---
{email_text}
---

VISION DESCRIPTIONS — one block per attachment, in order:
{vision_blocks}

For EACH attachment, produce a JSON object with this exact shape:

{{
  "image_path":       "<path of the image (matches the 'Attachment N: <path>' header in the vision block)>",
  "screen":           "<SLAP screen name from the catalog, or 'unknown'>",
  "state":            "normal | loading | error | empty | unknown",
  "visible_text":     ["literal strings extracted from the vision description"],
  "error_indicators": ["specific error messages or visual error states"],
  "ui_anomalies":     ["specific things that look wrong, missing, or out of place"],
  "device_hints":     {{"platform": "Android | iOS | unknown", "os_visible": "..." | null, "app_version_visible": "..." | null}},
  "triage_signals":   {{"likely_component": "Backend | Backend-Labs | DS | UI | immersive | bugs",
                       "severity_hint":    "P0 | P1 | P2 | P3",
                       "contradicts_email_claim": "<see CONTRADICTION DETECTION below>"}},
  "one_line_summary": "Single sentence that captures the bug evidence from this image."
}}

CONTRADICTION DETECTION (very important)
Compare what the email describes to what the vision description actually shows, and set `contradicts_email_claim` AGGRESSIVELY. Set it to a one-sentence description of the mismatch in any of these cases:

  • The image shows a different SLAP screen / feature than the one the email is about.
    Example: email is about "Checkout / Proceed to Pay crash" but the image shows "Phone login / OTP" — contradicts_email_claim should say "Email reports a checkout-flow crash but the attached image is the phone-login screen with an OTP error — different feature areas."

  • The image shows no anomaly / a normal happy-path state while the email claims something is broken.
  • The image shows a different platform than the email states (e.g. email says Android, image shows iOS — or vice versa).
  • The image's visible error message or symptom does not match the symptom the email describes.

Only set `contradicts_email_claim` to null when the image evidence clearly supports or is plausibly relevant to what the email is describing. When in doubt, FLAG IT — a triage analyst can override a false flag, but a missed contradiction wastes engineering time on the wrong bug.

Reply with ONLY a JSON object of the form:

{{
  "findings":         [ <one entry per attachment, in the same order as the vision blocks above> ],
  "combined_summary": "1-3 sentence aggregate across ALL attachments — what the images jointly tell us about the bug, and whether they agree with the email"
}}

No markdown fences, no commentary outside the JSON."""


# ── Legacy single-Claude-call image prompt (fallback path) ────────────────

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


def _noop_progress(_event: str, _message: str) -> None:
    """Default on_progress callback when the caller doesn't provide one."""


def _process_images(
    image_paths: list,
    email_text:  str,
    on_progress: Callable[[str, str], None] = _noop_progress,
) -> tuple:
    """
    Returns (findings: list[MediaFinding], combined_summary: str, raw: dict).

    Preferred path is two-stage: Gemini does per-image vision in parallel,
    Claude does the SLAP-aware reasoning over the resulting text. Falls
    back to a single Claude call (legacy path) if Gemini isn't reachable
    (env vars unset, JWT expired, off-corp network, etc.).

    Calls `on_progress(event, message)` at sub-stage boundaries so the
    host (and Streamlit UI) can render live progress. Event names are
    *unprefixed* — the host adds the `media:` prefix.
    """
    abs_paths = [str(Path(p).resolve()) for p in image_paths]
    n         = len(abs_paths)

    if gemini_configured():
        on_progress("vision:start", f"Gemini vision — describing {n} image(s) in parallel…")
        t0 = perf_counter()
        try:
            descriptions = _gemini_describe_images_parallel(abs_paths)
            dt = perf_counter() - t0
            print(f"  [media] Gemini described {n} image(s) in {dt:.1f}s; handing off to Claude for reasoning.")
            on_progress("vision:done", f"Gemini described {n} image(s) in {dt:.1f}s")
            return _process_images_gemini_then_claude(abs_paths, email_text, descriptions, on_progress)
        except GeminiUnavailable as e:
            print(f"  [media] Gemini unavailable ({e}); falling back to Claude vision.")
            on_progress("vision:fallback", f"Gemini unavailable ({e}) — falling back to Claude vision")

    on_progress("fallback:start", f"Claude vision + reasoning — single pass over {n} image(s)…")
    t0 = perf_counter()
    result = _process_images_claude_only(abs_paths, email_text)
    on_progress("fallback:done", f"Claude vision + reasoning complete ({perf_counter() - t0:.1f}s)")
    return result


def _gemini_describe_images_parallel(image_paths: list) -> dict:
    """
    Describe each image with Gemini in parallel. Returns {abs_path: description}.
    Raises GeminiUnavailable on the first failure — we'd rather fall back to
    the Claude vision path for the whole batch than ship a half-Gemini /
    half-Claude result.
    """
    descriptions: dict = {}
    workers = min(max(len(image_paths), 1), 4)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_path = {
            ex.submit(gemini_describe_image, p, VISION_PROMPT): p
            for p in image_paths
        }
        try:
            for fut in as_completed(future_to_path):
                path = future_to_path[fut]
                descriptions[path] = fut.result()
        except GeminiUnavailable:
            for f in future_to_path:
                f.cancel()
            raise
    return descriptions


def _process_images_gemini_then_claude(
    image_paths: list,
    email_text:  str,
    descriptions: dict,
    on_progress: Callable[[str, str], None] = _noop_progress,
) -> tuple:
    """
    Reasoning pass: feed the Gemini vision descriptions to Claude along
    with the SLAP knowledge doc + reference-screen directory, and emit the
    structured MediaFinding JSON.
    """
    on_progress(
        "reasoning:start",
        "Claude reasoning — mapping descriptions to SLAP screens + triage signals…",
    )
    t0 = perf_counter()
    vision_blocks = "\n\n".join(
        f"--- Attachment {i + 1}: {p} ---\n{descriptions[p]}"
        for i, p in enumerate(image_paths)
    )

    prompt = REASONING_PROMPT_TEMPLATE.format(
        knowledge_path = str(SLAP_KNOWLEDGE),
        reference_dir  = str(REFERENCE_SCREENS),
        email_text     = (email_text or "(no email body provided)").strip(),
        vision_blocks  = vision_blocks,
    )

    response = call_claude(
        prompt,
        expect_json   = True,
        timeout       = 240,
        add_dirs      = [str(SLAP_CONTEXT_DIR)],
        allowed_tools = ["Read", "Glob"],
    )
    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent (reasoning) returned non-object: {type(response).__name__}")

    findings = [
        MediaFinding(
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
        )
        for entry in (response.get("findings") or [])
    ]
    on_progress("reasoning:done", f"Claude reasoning complete ({perf_counter() - t0:.1f}s, {len(findings)} finding(s))")
    return findings, response.get("combined_summary", ""), response


def _process_images_claude_only(image_paths: list, email_text: str) -> tuple:
    """
    Legacy single-Claude-call image path. Claude loads each image via the
    Read tool and produces the structured MediaFinding JSON directly. Used
    as the fallback when Gemini is unavailable.
    """
    image_list_str = "\n".join(f"  - {p}" for p in image_paths)

    prompt = IMAGE_PROMPT_TEMPLATE.format(
        knowledge_path  = str(SLAP_KNOWLEDGE),
        reference_dir   = str(REFERENCE_SCREENS),
        email_text      = (email_text or "(no email body provided)").strip(),
        bug_image_paths = image_list_str,
    )

    add_dirs = [str(SLAP_CONTEXT_DIR)]
    for p in image_paths:
        parent = str(Path(p).parent)
        if parent not in add_dirs:
            add_dirs.append(parent)

    response = call_claude(
        prompt,
        expect_json   = True,
        timeout       = 300,
        add_dirs      = add_dirs,
        allowed_tools = ["Read", "Glob"],
    )
    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent (images) returned non-object: {type(response).__name__}")

    findings = [
        MediaFinding(
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
        )
        for entry in (response.get("findings") or [])
    ]
    return findings, response.get("combined_summary", ""), response


# ── Video prompts ──────────────────────────────────────────────────────────
#
# Mirrors the image two-stage flow:
#
#   Stage 1 — Gemini (vision, per-frame, parallel)
#     Each ffmpeg-extracted keyframe gets `VIDEO_FRAME_VISION_PROMPT`. The
#     prompt is sequence-aware: each frame describes one moment in time
#     (interaction state, error visibility, scroll position) so Claude
#     can reason about WHAT THE USER DID.
#
#   Stage 2 — Claude (temporal reasoning, single call)
#     `VIDEO_REASONING_PROMPT_TEMPLATE` reads the ordered frame
#     descriptions as inline text, reads SLAP_KNOWLEDGE.md /
#     reference_screens via the Read tool, and emits ONE structured
#     MediaFinding describing the whole clip (screen_sequence,
#     action_observed, failure_moment, contradiction detection).
#
# Fallback — `VIDEO_PROMPT_TEMPLATE` below: single Claude call that Reads
# each frame PNG directly. Used when Gemini is unavailable.

VIDEO_FRAME_VISION_PROMPT = """You are looking at one keyframe from a screen recording of a Flipkart SLAP (conversational shopping app) bug. Describe what's visible in THIS frame in plain prose — your description will be combined with descriptions of the OTHER frames, in temporal order, so another agent can reason about what the user does over time.

Cover:
1. ALL visible text on the screen — labels, buttons, prices, headers, error messages. Quote verbatim where possible.
2. UI elements visible (input fields, buttons, lists, cards, modals, chat bubbles, video controls) and the state of each (normal, loading, empty, disabled, error).
3. Interaction state at this moment — tap location if visible, scroll position, gesture in progress, modal/sheet open, keyboard up.
4. Any visible anomaly — error toast, broken layout, missing content, frozen-looking UI, half-rendered element.
5. Device / platform hints — status-bar style, system font, navigation pattern. Note any visible OS or app version string.

Reply in plain prose. No JSON, no markdown, no bullet lists — just descriptive sentences focused on THIS frame."""


VIDEO_REASONING_PROMPT_TEMPLATE = """You are the SLAP media-processor sub-agent's reasoning stage. A vision model has already described each of the {frame_count} keyframes from a {duration:.1f}-second bug-report video; YOUR job is to reason over the SEQUENCE and emit one structured finding for the whole clip.

You have access via the Read tool to:
  1. SLAP knowledge document : {knowledge_path}  (READ FIRST — screen catalog, vocabulary, visual triage cues)
  2. Canonical reference screens : {reference_dir}/   (each filename is a screen label; use Glob to browse if you need to confirm a screen name)

THE BUG REPORT EMAIL THE USER ALSO ATTACHED (verbatim):
---
{email_text}
---

FRAME DESCRIPTIONS — one block per keyframe, in temporal order:
{frame_descriptions}

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

OUTPUT FORMAT (STRICT)
- The very first character of your response MUST be `{{` (the opening brace of the JSON object).
- Do NOT write any prose, analysis, or "Let me reason..." preamble before the JSON.
- Do NOT wrap the JSON in markdown fences (```json ... ```).
- Do NOT add any commentary after the closing `}}`.
- Reasoning, if any, belongs INSIDE the `action_observed` / `failure_moment` / `one_line_summary` fields — not outside the object."""


# ── Legacy single-Claude-call video prompt (fallback path) ─────────────────

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


def _process_one_video(
    video_path:  str,
    email_text:  str,
    on_progress: Callable[[str, str], None] = _noop_progress,
) -> MediaFinding:
    """
    Pre-process a single video (probe → extract keyframes), then run the
    two-stage Gemini-vision → Claude-reasoning flow over the keyframes.
    Falls back to a single Claude call (legacy path, frames read via the
    Read tool) when Gemini is unavailable.

    Returns one MediaFinding describing the whole video. Frames are
    extracted into a tempdir whose path is stored on the finding so the
    UI can display them later.

    Calls `on_progress(event, message)` at sub-stage boundaries. Event
    names are prefixed `video:` so the host's media wrapper turns them
    into `media:video:vision:start`, `media:video:reasoning:done`, etc.
    """
    video_path = str(Path(video_path).resolve())
    duration   = _probe_video_duration(video_path)

    # Reject videos that exceed the cap — no LLM call wasted, clear UX.
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

    # Extract keyframes into a long-lived tempdir (we DON'T context-manage
    # it — the UI may want to read those PNGs later in the same session).
    frames_dir  = Path(tempfile.mkdtemp(prefix="slap_video_frames_"))
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

    n = len(frame_paths)

    if gemini_configured():
        on_progress("video:vision:start", f"Gemini vision — describing {n} keyframe(s) in parallel…")
        t0 = perf_counter()
        try:
            descriptions = _gemini_describe_frames_parallel(frame_paths)
            dt = perf_counter() - t0
            print(f"  [media] Gemini described {n} keyframe(s) in {dt:.1f}s; handing off to Claude for sequence reasoning.")
            on_progress("video:vision:done", f"Gemini described {n} keyframe(s) in {dt:.1f}s")
            return _process_video_gemini_then_claude(
                video_path, duration, frame_paths, email_text, descriptions, on_progress,
            )
        except GeminiUnavailable as e:
            print(f"  [media] Gemini unavailable ({e}); falling back to Claude video vision.")
            on_progress("video:vision:fallback", f"Gemini unavailable ({e}) — falling back to Claude video vision")

    on_progress("video:fallback:start", f"Claude vision + reasoning — single pass over {n} keyframe(s)…")
    t0 = perf_counter()
    finding = _process_video_claude_only(video_path, duration, frame_paths, frames_dir, email_text)
    on_progress("video:fallback:done", f"Claude vision + reasoning complete ({perf_counter() - t0:.1f}s)")
    return finding


def _gemini_describe_frames_parallel(frame_paths: list) -> dict:
    """
    Describe each video keyframe with Gemini in parallel using the
    sequence-aware per-frame prompt. Returns {abs_path: description}.
    Raises GeminiUnavailable on the first failure — we'd rather fall back
    to the Claude-only path than ship a half-Gemini result.
    """
    descriptions: dict = {}
    workers = min(max(len(frame_paths), 1), 4)
    paths_str = [str(p) for p in frame_paths]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_path = {
            ex.submit(gemini_describe_image, p, VIDEO_FRAME_VISION_PROMPT): p
            for p in paths_str
        }
        try:
            for fut in as_completed(future_to_path):
                path = future_to_path[fut]
                descriptions[path] = fut.result()
        except GeminiUnavailable:
            for f in future_to_path:
                f.cancel()
            raise
    return descriptions


def _process_video_gemini_then_claude(
    video_path:   str,
    duration:     float,
    frame_paths:  list,
    email_text:   str,
    descriptions: dict,
    on_progress:  Callable[[str, str], None] = _noop_progress,
) -> MediaFinding:
    """
    Reasoning pass over the per-frame Gemini descriptions. Feeds the
    descriptions (in temporal order) + SLAP context to Claude and emits
    one MediaFinding for the whole video.
    """
    on_progress(
        "video:reasoning:start",
        f"Claude reasoning — analysing {len(frame_paths)}-frame sequence…",
    )
    t0 = perf_counter()

    paths_str = [str(p) for p in frame_paths]
    frame_blocks = "\n\n".join(
        f"--- Frame {i + 1} of {len(paths_str)} ({Path(p).name}) ---\n{descriptions[p]}"
        for i, p in enumerate(paths_str)
    )

    prompt = VIDEO_REASONING_PROMPT_TEMPLATE.format(
        frame_count        = len(paths_str),
        duration           = duration,
        knowledge_path     = str(SLAP_KNOWLEDGE),
        reference_dir      = str(REFERENCE_SCREENS),
        email_text         = (email_text or "(no email body provided)").strip(),
        frame_descriptions = frame_blocks,
    )

    response = call_claude(
        prompt,
        expect_json   = True,
        # Match the legacy single-Claude video path (360s). The reasoning
        # prompt carries 8 verbose frame descriptions inline + email body
        # + SLAP_KNOWLEDGE via Read, so it's at least as token-heavy as
        # the legacy path that Reads each PNG.
        timeout       = 360,
        add_dirs      = [str(SLAP_CONTEXT_DIR)],
        allowed_tools = ["Read", "Glob"],
    )
    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent (video reasoning) returned non-object: {type(response).__name__}")

    on_progress(
        "video:reasoning:done",
        f"Claude reasoning complete ({perf_counter() - t0:.1f}s)",
    )
    return _video_finding_from_response(response, video_path, duration, frame_paths)


def _process_video_claude_only(
    video_path:  str,
    duration:    float,
    frame_paths: list,
    frames_dir:  Path,
    email_text:  str,
) -> MediaFinding:
    """
    Legacy single-Claude-call video path. Claude reads each keyframe PNG
    via the Read tool and emits the structured finding directly. Used as
    the fallback when Gemini is unavailable.
    """
    frames_listing = "\n".join(
        f"  Frame {i + 1} of {len(frame_paths)}: {p}"
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

    response = call_claude(
        prompt,
        expect_json   = True,
        timeout       = 360,
        add_dirs      = [str(SLAP_CONTEXT_DIR), str(frames_dir)],
        allowed_tools = ["Read", "Glob"],
    )
    if not isinstance(response, dict):
        raise ValueError(f"Media sub-agent (video) returned non-object: {type(response).__name__}")

    return _video_finding_from_response(response, video_path, duration, frame_paths)


def _video_finding_from_response(
    response:    dict,
    video_path:  str,
    duration:    float,
    frame_paths: list,
) -> MediaFinding:
    """Map a Claude response dict (from either video path) to a MediaFinding."""
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

def process_attachments(
    paths:       list,
    email_text:  str = "",
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> MediaResult:
    """
    Analyse a list of attachment paths (images and/or videos) and return a
    MediaResult. Images go through the two-stage Gemini-vision → Claude-
    reasoning path (with a Claude-only fallback); each video gets its own
    Claude call so the prompt can reason about the keyframe sequence.

    `on_progress(event, message)` is called at sub-stage boundaries so the
    host (and Streamlit UI) can render live progress. Event names from
    here are unprefixed (e.g. "vision:start"); the host adds the "media:"
    prefix.

    If `paths` is empty, returns an empty MediaResult immediately.
    """
    if not paths:
        return MediaResult(findings=[], combined_summary="")

    cb = on_progress or _noop_progress

    path_objs    = [Path(p) for p in paths]
    image_paths  = [str(p) for p in path_objs if _is_image(p)]
    video_paths  = [str(p) for p in path_objs if _is_video(p)]

    findings: list[MediaFinding] = []
    image_combined_summary       = ""
    raw_responses: list[dict]    = []

    if image_paths:
        image_findings, image_combined_summary, image_raw = _process_images(
            image_paths, email_text, on_progress=cb,
        )
        findings.extend(image_findings)
        if image_raw:
            raw_responses.append(image_raw)

    for i, vp in enumerate(video_paths, start=1):
        cb("video:start", f"Video {i}/{len(video_paths)} ({Path(vp).name}) — keyframes + Gemini vision + Claude reasoning…")
        t0 = perf_counter()
        video_finding = _process_one_video(vp, email_text, on_progress=cb)
        findings.append(video_finding)
        cb("video:done", f"Video {i}/{len(video_paths)} analysed ({perf_counter() - t0:.1f}s)")

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
