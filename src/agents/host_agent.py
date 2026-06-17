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

VAGUE_TEXT_THRESHOLD = 350   # chars of raw email body, lower = considered vague
_PLACEHOLDER_VALUES  = {"", "not provided.", "not provided", "unknown", "none", "n/a"}


def _is_placeholder(value: str) -> bool:
    return (value or "").strip().lower() in _PLACEHOLDER_VALUES


def detect_quality_issues(bug: BugReport, media: "MediaResult") -> list:
    """
    Return a list of {type, severity, message, suggested_action} dicts when
    the report's quality is too low for a confident triage call:

    - vague_report:        short text + missing key fields (steps / impact / actual)
    - media_contradicts_text: any image whose findings disagree with the email body

    These get folded into triage_notes.quality_issues and surfaced in the UI
    so the reporter can refile with the missing detail before the draft is
    treated as authoritative.
    """
    issues: list = []

    # 1. Vague report — multiple structural signals must all be weak before we flag
    missing = []
    if len((bug.raw_text or "").strip()) < VAGUE_TEXT_THRESHOLD:
        missing.append("the report body is under ~350 characters")
    if not bug.steps_to_reproduce:
        missing.append("no steps to reproduce were provided")
    if _is_placeholder(bug.impact):
        missing.append("no impact statement was provided")
    if _is_placeholder(bug.actual_result):
        missing.append("no actual result was described")
    if _is_placeholder(bug.expected_result):
        missing.append("no expected result was described")
    if _is_placeholder(bug.platform):
        missing.append("no platform was specified")
    if _is_placeholder(bug.reproducibility):
        missing.append("reproducibility was not stated")

    if len(missing) >= 2:
        issues.append({
            "type":             "vague_report",
            "severity":         "warning",
            "message":          "The report is missing details needed for confident triage: " + "; ".join(missing) + ".",
            "suggested_action": (
                "Please refile this bug with clear steps to reproduce, expected vs actual "
                "behaviour, the platform/version, and a user-impact statement."
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
                    "screen":           f.screen,
                    "state":            f.state,
                    "ui_anomalies":     f.ui_anomalies,
                    "error_indicators": f.error_indicators,
                    "device_hints":     f.device_hints,
                    "triage_signals":   f.triage_signals,
                    "one_line_summary": f.one_line_summary,
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
