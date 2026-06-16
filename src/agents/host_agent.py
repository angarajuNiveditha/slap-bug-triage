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
            media = process_attachments(image_paths)
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

        return HostResult(
            bug        = bug,
            media      = media,
            embeddings = emb,
            dedup      = dup,
            similarity = similarity,
            severity   = severity,
            draft      = draft,
        )
