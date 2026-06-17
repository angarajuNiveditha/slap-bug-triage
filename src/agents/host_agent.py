"""
host_agent.py — Astral. Coordinates the multi-agent triage pipeline.

Order of operations for a single bug:

  raw email text + optional image paths
        │
        ▼
  [ subagent_media   ]  (skipped if no images)
        │     ↳ one-line summary folded into email body
        ▼
  [ subagent_parser  ]  → BugReport
        │
        ▼
  [ Jira fetch (one-time, cached) ] — 300 historical bugs
        │
        ▼
  [ subagent_embeddings ] → ranked candidates + owner suggestion
        │
        ▼
  [ subagent_dedup   ] → duplicate_of + confidence (or None)
        │
        ▼
  [ subagent_triage  ] → SeverityResult
        │
        ▼
  build_ticket(...)  → TicketDraft (ADF + triage_notes)

The host returns a HostResult bundle containing every sub-agent's output
so the entry-point script (run_multi_agent.py / app.py) can render or
serialize it however it wants.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..agent_parser         import BugReport
from ..agent_scorer         import SeverityResult
from ..agent_ticket_builder import TicketDraft, build_ticket
from ..tfidf_similarity     import SimilarBug, SimilarityResult

from .subagent_dedup       import DedupResult, decide_duplicate
from .subagent_embeddings  import EmbeddingsEngine, EmbeddingsResult
from .subagent_media       import MediaResult, process_attachments
from .subagent_parser      import parse_bug_report
from .subagent_triage      import score_severity


@dataclass
class HostResult:
    bug:        BugReport
    media:     MediaResult
    embeddings: EmbeddingsResult
    dedup:      DedupResult
    similarity: SimilarityResult     # assembled (embeddings + dedup) for ticket builder
    severity:   SeverityResult
    draft:      TicketDraft


# ─── Quality checks ────────────────────────────────────────────────────────

VAGUE_TEXT_THRESHOLD = 300   # chars of raw email body — anything shorter is auto-vague

# Required sections in a properly-formatted bug report email, mapped to
# the case-insensitive substring patterns we'll accept as evidence of
# that section being present. We check the RAW email text (not parsed
# fields) because the parser sometimes infers values when the user
# omitted the section entirely.
REQUIRED_SECTION_PATTERNS = [
    ("Steps to Reproduce", ["steps to reproduce", "reproduction steps", "repro steps", "\nsteps:"]),
    ("Expected Result",    ["expected:", "expected result", "expected behavi"]),
    ("Actual Result",      ["actual:", "actual result", "actual behavi"]),
    ("Impact",             ["impact:", "user impact", "business impact"]),
    ("Reproducibility",    ["reproducibility:", "repro rate", "repro:", "frequency:"]),
    ("Environment",        ["environment:", "platform:", "app version:", "device:", "os version"]),
]

# Threshold: if at least this many required sections are missing, we ask
# the reporter to refile. The default tolerance is 2 — letting an
# otherwise-good email slip a single section by accident — while still
# catching reports that obviously skipped the format.
MAX_MISSING_SECTIONS = 2


def _section_present(raw_lower: str, patterns: list) -> bool:
    return any(p in raw_lower for p in patterns)


def detect_quality_issues(bug: BugReport, media: "MediaResult") -> list:
    """
    Return a list of {type, severity, message, suggested_action} dicts when
    the report's quality is too low for a confident triage call.

    Two kinds of issues:

    - vague_report — the raw email is missing required section headers
      (Impact, Reproducibility, Environment, etc.). We check the raw text
      rather than parsed fields because Claude will sometimes infer values
      for missing sections; the format check has to be on the raw input.

    - media_contradicts_text — any image whose media-agent findings
      disagree with the email body.

    These get folded into triage_notes.quality_issues and surfaced in the
    UI so the reporter refiles with the missing detail before the draft
    is treated as authoritative.
    """
    issues: list = []

    raw       = (bug.raw_text or "").strip()
    raw_lower = raw.lower()
    missing   = []

    # Very short reports are auto-vague (don't even check sections — there
    # isn't enough text to evaluate).
    if len(raw) < VAGUE_TEXT_THRESHOLD:
        missing.append(f"the report body is under ~{VAGUE_TEXT_THRESHOLD} characters")

    # Format compliance: each required section must be present in the raw email.
    for label, patterns in REQUIRED_SECTION_PATTERNS:
        if not _section_present(raw_lower, patterns):
            missing.append(f"no '{label}' section in the email")

    # If the parser failed to extract any reproduction steps (even though the
    # email may have had a 'Steps' header), count it as a missing detail.
    if bug.steps_to_reproduce == []:
        already_flagged_steps = any("Steps to Reproduce" in m for m in missing)
        if not already_flagged_steps:
            missing.append("no reproduction steps could be extracted")

    if len(missing) >= MAX_MISSING_SECTIONS:
        issues.append({
            "type":             "vague_report",
            "severity":         "warning",
            "message": (
                "The report is not following the expected format: "
                + "; ".join(missing) + "."
            ),
            "suggested_action": (
                "Please refile with explicit sections for Steps to Reproduce, "
                "Expected vs Actual, Impact, Reproducibility, and Environment "
                "(platform/version/device). All five are required for confident triage."
            ),
        })

    # 2. Image / text contradictions — trust the media sub-agent's semantic
    #    judgment (contradicts_email_claim). It already has the full email
    #    body + SLAP context + the image. A rule-based structural backup
    #    used to live here, but it false-fired on screens whose name didn't
    #    happen to contain the title's module-tag keyword (e.g. "15 Minutes
    #    — category-browse view" was correctly identified as a price bug
    #    but the screen string didn't include "price"). Removed.
    seen_contradictions: set = set()
    if media and media.findings:
        for f in media.findings:
            contra   = (f.triage_signals or {}).get("contradicts_email_claim")
            if not contra:
                continue
            img_name = Path(f.image_path).name if f.image_path else "attachment"
            key      = (img_name, f.screen or "")
            if key in seen_contradictions:
                continue
            issues.append({
                "type":             "media_contradicts_text",
                "severity":         "warning",
                "image":            img_name,
                "screen":           f.screen,
                "message":          f"Attachment '{img_name}' shows the '{f.screen}' screen, which contradicts the email: {contra}",
                "suggested_action": (
                    "Please refile with a description that matches what the screenshot actually shows, "
                    "or attach the correct screenshot for the bug you intended to report."
                ),
            })
            seen_contradictions.add(key)

    return issues


class HostAgent:
    """
    Stateful host. Build the embeddings index once with .build_index(...) then
    call .triage(...) per bug. Reuses the cached Jira corpus across calls.
    """

    def __init__(self) -> None:
        self.embeddings_engine = EmbeddingsEngine()
        self._indexed = False

    def build_index(self, issues: list) -> None:
        self.embeddings_engine.build_index(issues)
        self._indexed = True

    def triage(self, raw_text: str, image_paths: Optional[list] = None) -> HostResult:
        # ── Step 1: media (only if attachments) ─────────────────────────
        image_paths = list(image_paths or [])
        if image_paths:
            print(f"  [host] media sub-agent processing {len(image_paths)} image(s)...")
            # Pass the email text so the media sub-agent can compare what
            # the reporter wrote with what the images actually show.
            media = process_attachments(image_paths, email_text=raw_text)
        else:
            media = MediaResult(findings=[], combined_summary="")

        # ── Step 2: parser ──────────────────────────────────────────────
        print("  [host] parser sub-agent...")
        bug = parse_bug_report(raw_text, media_summary=media.combined_summary or None)

        # ── Step 3: embeddings ──────────────────────────────────────────
        if not self._indexed:
            raise RuntimeError(
                "HostAgent.build_index(issues) must be called before .triage()"
            )
        print("  [host] embeddings sub-agent (ranking similar bugs)...")
        emb = self.embeddings_engine.find_similar(bug)

        # ── Step 4: dedup ───────────────────────────────────────────────
        print("  [host] dedup sub-agent...")
        dup = decide_duplicate(bug, emb.top_matches)

        # ── Step 5: assemble SimilarityResult for downstream consumers ──
        matches_with_dup_flag: list[SimilarBug] = []
        for m in emb.top_matches:
            matches_with_dup_flag.append(SimilarBug(
                key=m.key,
                summary=m.summary,
                similarity=m.similarity,
                assignee=m.assignee,
                priority=m.priority,
                is_duplicate_candidate=(m.key == dup.duplicate_of),
                url=m.url,
            ))
        similarity = SimilarityResult(
            top_matches          = matches_with_dup_flag,
            suggested_owner      = emb.suggested_owner,
            owner_reason         = emb.owner_reason,
            duplicate_of         = dup.duplicate_of,
            duplicate_confidence = dup.duplicate_confidence,
        )

        # ── Step 6: triage / severity ───────────────────────────────────
        print("  [host] triage sub-agent...")
        severity = score_severity(bug, similarity.top_matches)

        # ── Step 7: build the Jira ticket draft ─────────────────────────
        print("  [host] building ticket draft...")
        draft = build_ticket(bug, severity, similarity)

        # ── Step 8: annotate triage_notes with the multi-agent extras ──
        draft.triage_notes["pipeline"] = "multi-agent (Astral)"
        if media.findings:
            draft.triage_notes["media_findings"] = [
                {
                    "image_path":       f.image_path,
                    "kind":             f.kind,
                    "screen":           f.screen,
                    "state":            f.state,
                    "visible_text":     f.visible_text,
                    "ui_anomalies":     f.ui_anomalies,
                    "error_indicators": f.error_indicators,
                    "device_hints":     f.device_hints,
                    "triage_signals":   f.triage_signals,
                    "one_line_summary": f.one_line_summary,
                    # Video-only fields (default-valued for images, so the
                    # JSON stays uniform).
                    "duration_seconds": f.duration_seconds,
                    "frame_count":      f.frame_count,
                    "screen_sequence":  f.screen_sequence,
                    "action_observed":  f.action_observed,
                    "failure_moment":   f.failure_moment,
                    "frames":           f.frames,
                }
                for f in media.findings
            ]
            draft.triage_notes["media_combined_summary"] = media.combined_summary
        if dup.duplicate_reasoning:
            draft.triage_notes["duplicate_reasoning"] = dup.duplicate_reasoning

        # ── Step 9: quality checks (vague report + media-vs-text conflict) ──
        quality_issues = detect_quality_issues(bug, media)
        if quality_issues:
            draft.triage_notes["quality_issues"] = quality_issues

        return HostResult(
            bug        = bug,
            media      = media,
            embeddings = emb,
            dedup      = dup,
            similarity = similarity,
            severity   = severity,
            draft      = draft,
        )
