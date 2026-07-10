"""
src/db.py — Local ticket store + append-only CSV event log.

Backs the "Publish" button in the Streamlit UI. When the reviewer clicks
Publish on a triaged draft, we mint a BUGT-N key, insert the ticket into
the tickets table, and append an INSERT event to the CSV log. When the
reviewer changes a ticket's status from the dashboard, we UPDATE the row
and append a STATUS_UPDATE event.

Two CSV artifacts sit alongside the DB for redundancy:

  data/tickets_events.csv    — append-only log of every mutation.
                               One row per (INSERT | STATUS_UPDATE), with
                               the timestamp + payload as JSON. Never
                               rewritten, so a corrupted DB can be
                               replayed from this alone.

  data/tickets_snapshot.csv  — full snapshot of the tickets table,
                               rewritten after every mutation. Fast to
                               scan visually or import into a spreadsheet.

Backend: MySQL via SQLAlchemy + pymysql, driven by `DATABASE_URL` in .env.
Default is `mysql+pymysql://root@localhost/slap_triage`. Swap to a
different DSN (e.g. sqlite:///data/tickets.db) if the mentor's laptop
doesn't have MySQL --- the code path is identical.

Public API:
    init_db()                 — idempotent schema creation
    insert_ticket(fields)     — insert + return new BUGT-N key
    update_status(key, s)     — change status, log event, refresh snapshot
    list_tickets()            — all tickets as dicts, newest first
    STATUSES                  — the allowed status values (Open, In Progress, Done, Closed)
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session


# ── Configuration ──────────────────────────────────────────────────────────

_DEFAULT_DSN = "mysql+pymysql://root@localhost/slap_triage"

DATA_DIR         = Path(__file__).parent.parent.parent / "data"
EVENT_LOG_PATH   = DATA_DIR / "tickets_events.csv"
SNAPSHOT_PATH    = DATA_DIR / "tickets_snapshot.csv"
ATTACHMENTS_ROOT = DATA_DIR / "tickets_attachments"

STATUSES        = ["Open", "In Progress", "Done", "Closed"]
DEFAULT_STATUS  = "Open"


# ── Schema ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    # Numeric primary key = order of creation (drives BUGT-N minting).
    id           = Column(Integer, primary_key=True, autoincrement=True)

    # Human-facing key. BUGT-N where N == id at insert time. Unique.
    key          = Column(String(20), unique=True, nullable=False, index=True)

    # Ticket fields the reviewer sees in the dashboard.
    summary      = Column(String(500), nullable=False)
    description  = Column(Text)
    status       = Column(String(20), nullable=False, default=DEFAULT_STATUS)
    component    = Column(String(50))            # Backend / UI / DS / ...
    priority     = Column(String(8))             # P0 / P1 / P2
    assignee     = Column(String(200))
    reporter     = Column(String(200))
    duplicate_of = Column(String(20))            # BUGT-N or FLIPPI-N

    # Media attachments serialised as a JSON list of file paths, e.g.
    # '["data/bug_with_media/foo/screenshot.png","..."]'. Kept in one
    # column because we don't need to query on individual attachments.
    media_paths  = Column(Text)

    # Local time (not UTC) --- matches Jira Atlassian-cloud presentation.
    created      = Column(DateTime, nullable=False)
    updated      = Column(DateTime, nullable=False)

    # Cached mpnet embedding of (summary + description) as a JSON list
    # of 768 float32s. Computed at insert time so the local ticket store
    # can participate in the similarity engine's dedup search alongside
    # the Jira embedding index. NULL for tickets inserted before this
    # column existed --- backfilled lazily by backfill_missing_embeddings()
    # on the first search after upgrade.
    embedding    = Column(Text)


# ── Engine (lazy, module-level singleton) ──────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        dsn = os.environ.get("DATABASE_URL", _DEFAULT_DSN)
        _engine = create_engine(
            dsn,
            pool_pre_ping=True,   # detect stale connections after long idle
            pool_recycle=3600,    # MySQL default wait_timeout is 8h; recycle sooner
            future=True,
        )
    return _engine


def init_db() -> None:
    """Create the tickets table if it doesn't exist. Idempotent --- safe
    to call at import time or on every request."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    # Additive migration: add the `embedding` column to a pre-existing
    # tickets table (upgrade from a version that didn't have it).
    # SQLAlchemy's create_all() only creates missing tables, not columns.
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "tickets" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("tickets")}
        if "embedding" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tickets ADD COLUMN embedding TEXT"))


# ── Embedding helpers ──────────────────────────────────────────────────────
#
# Reuse the same mpnet encoder the classifier + Jira similarity index use,
# so a local ticket's embedding is directly comparable via cosine to any
# vector in data/embedding_index.npz. The encoder lives in
# embedding_classifier._get_model() as a module-level singleton, so the
# first call has a ~5-10s cold load and every subsequent call is instant.

def _encode_text_to_json(text: str) -> str | None:
    """Encode `text` with mpnet (L2-normalised, 768 dim) and return a
    JSON string of the vector. Returns None on empty/whitespace text or
    if the encoder can't be loaded (offline first-run, etc.).

    Not called on the request-serving hot path --- only at insert time
    and during backfill. Safe to fail: the returned None just means the
    ticket won't participate in the similarity search until we can
    encode it later."""
    if not text or not text.strip():
        return None
    try:
        from .embedding_classifier import _get_model
        import numpy as np
        model = _get_model()
        vec = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]
        return json.dumps(vec.tolist())
    except Exception:
        return None


def _search_text_for(summary: str, description: str) -> str:
    """The text we embed for a ticket. Matches the format that
    build_embedding_index.py uses for the 564-bug Jira corpus --- title
    then description, one blank line between --- so cosine distances
    are directly comparable across the two corpora."""
    parts = [(summary or "").strip(), (description or "").strip()]
    return "\n".join(p for p in parts if p)


def backfill_missing_embeddings() -> int:
    """Encode + store the embedding for any ticket rows where it's NULL.
    Returns the number of rows backfilled. Safe to call from search-time
    code paths; idempotent."""
    init_db()
    engine = _get_engine()
    with Session(engine) as session:
        pending = session.query(Ticket).filter(Ticket.embedding.is_(None)).all()
        if not pending:
            return 0
        n = 0
        for t in pending:
            emb_json = _encode_text_to_json(_search_text_for(t.summary, t.description))
            if emb_json is None:
                continue     # encoder unavailable, try again next time
            t.embedding = emb_json
            n += 1
        session.commit()
    return n


def local_similar(query_embedding, top_k: int) -> list[dict]:
    """Cosine search over the local ticket store.

    `query_embedding` is a 1-D numpy array of shape (768,), L2-normalised
    (i.e. produced by the same mpnet encoder). Returns a list of dicts
    with the shape:

        {
          "key":       "BUGT-3",
          "summary":   "...",
          "priority":  "P1",
          "assignee":  "Divya",
          "component": "Backend",
          "status":    "Open",
          "similarity": 0.87,
        }

    Sorted by similarity DESC, capped at `top_k`. Returns [] when the
    store is empty or no embeddings could be loaded."""
    import numpy as np

    # Make sure old rows have embeddings before we compare.
    backfill_missing_embeddings()

    init_db()
    engine = _get_engine()
    with Session(engine) as session:
        rows = (
            session.query(Ticket)
            .filter(Ticket.embedding.isnot(None))
            .all()
        )
        if not rows:
            return []
        matrix = np.array(
            [json.loads(t.embedding) for t in rows],
            dtype=np.float32,
        )
        sims = matrix @ query_embedding    # (N,) --- L2-normalised → cosine

        n     = min(top_k, len(rows))
        order = np.argsort(-sims)[:n]

        return [{
            "key":        rows[i].key,
            "summary":    rows[i].summary,
            "description": rows[i].description or "",
            "priority":   rows[i].priority or "",
            "assignee":   rows[i].assignee,
            "component":  rows[i].component or "",
            "status":     rows[i].status,
            "similarity": float(sims[i]),
        } for i in order]


# ── Public API ─────────────────────────────────────────────────────────────

def insert_ticket(fields: dict, source_attachment_paths: list = None) -> str:
    """Mint a new BUGT-N key, persist any attachments, insert the row,
    log an INSERT event, refresh the snapshot CSV. Returns the new key.

    Expected keys in `fields` (all optional except summary):
        summary, description, component, priority, assignee,
        reporter, duplicate_of, media_paths (list[str])

    `source_attachment_paths` (optional): list of file paths (typically
    tempdir paths from save_uploads_to_tmp) that should be copied under
    data/tickets_attachments/<key>/ before the row is inserted. If
    provided, the resulting persistent paths REPLACE any
    fields["media_paths"] passed in — callers should use one mechanism
    or the other, not both.
    """
    init_db()
    now    = datetime.now()        # local time by design (see file header)
    engine = _get_engine()

    with Session(engine) as session:
        key = _next_key(session)

        # If the caller handed us upload tempdir paths, copy them under the
        # ticket's persistent folder BEFORE writing the DB row. We want the
        # stored media_paths to point at files that actually exist on disk
        # long-term, not tempdir paths that vanish on OS cleanup.
        if source_attachment_paths:
            persistent = persist_attachments(key, source_attachment_paths)
            fields = {**fields, "media_paths": persistent}

        summary_val = (fields.get("summary") or "")[:500]
        desc_val    = fields.get("description") or ""

        # Compute the mpnet embedding synchronously so this ticket can
        # be found by future similarity searches immediately (no need
        # to wait for backfill). mpnet is warm from the triage that
        # just ran, so this costs ~7ms on the happy path.
        embedding_json = _encode_text_to_json(_search_text_for(summary_val, desc_val))

        ticket = Ticket(
            key          = key,
            summary      = summary_val,
            description  = desc_val,
            status       = DEFAULT_STATUS,
            component    = fields.get("component") or None,
            priority     = fields.get("priority") or None,
            assignee     = fields.get("assignee") or None,
            reporter     = fields.get("reporter") or None,
            duplicate_of = fields.get("duplicate_of") or None,
            media_paths  = json.dumps(fields.get("media_paths") or []),
            created      = now,
            updated      = now,
            embedding    = embedding_json,
        )
        session.add(ticket)
        session.commit()

        # Log AFTER the commit so we never log a phantom row.
        _append_event("INSERT", key, _ticket_to_dict(ticket), now)

    _rewrite_snapshot()
    return key


def update_status(key: str, new_status: str) -> None:
    """Change a ticket's status. Bumps `updated`, logs a STATUS_UPDATE
    event, refreshes the snapshot. Raises ValueError if the key is
    unknown or the status isn't in STATUSES."""
    if new_status not in STATUSES:
        raise ValueError(
            f"Invalid status {new_status!r}. Allowed: {STATUSES}"
        )

    init_db()
    now    = datetime.now()
    engine = _get_engine()

    with Session(engine) as session:
        ticket = session.query(Ticket).filter_by(key=key).first()
        if ticket is None:
            raise ValueError(f"No ticket with key {key!r}")
        old_status     = ticket.status
        ticket.status  = new_status
        ticket.updated = now
        session.commit()

        _append_event(
            "STATUS_UPDATE", key,
            {"from": old_status, "to": new_status},
            now,
        )

    _rewrite_snapshot()


def delete_ticket(key: str) -> None:
    """Permanently delete a ticket and refresh the snapshot. Raises ValueError
    if the key is unknown."""
    init_db()
    engine = _get_engine()
    with Session(engine) as session:
        ticket = session.query(Ticket).filter_by(key=key).first()
        if ticket is None:
            raise ValueError(f"No ticket with key {key!r}")
        session.delete(ticket)
        session.commit()
    _rewrite_snapshot()


def list_tickets() -> list[dict]:
    """Return every ticket as a dict, sorted by created DESC (newest first)."""
    init_db()
    engine = _get_engine()
    with Session(engine) as session:
        rows = (
            session.query(Ticket)
            .order_by(Ticket.created.desc())
            .all()
        )
        return [_ticket_to_dict(t) for t in rows]


def get_ticket(key: str) -> dict | None:
    """Fetch a single ticket by key (e.g. "BUGT-3") or None if not found.
    Used by the UI for cross-referencing (e.g. showing a "possible
    regression" warning when the current bug duplicates a Closed local
    ticket). Cheap — single indexed lookup."""
    if not key:
        return None
    init_db()
    engine = _get_engine()
    with Session(engine) as session:
        t = session.query(Ticket).filter_by(key=key).first()
        return _ticket_to_dict(t) if t else None


def persist_attachments(ticket_key: str, source_paths: list) -> list:
    """Copy uploaded attachments (typically living in a tempdir from
    save_uploads_to_tmp) into a persistent per-ticket folder under
    data/tickets_attachments/<ticket_key>/. Returns the list of new
    absolute paths, ready to be JSON-encoded into the media_paths
    column.

    Filenames are preserved; on collision within the same folder we
    prefix a numeric suffix. Missing / unreadable sources are skipped
    silently rather than failing the whole publish operation.
    """
    if not source_paths:
        return []
    dest_dir = ATTACHMENTS_ROOT / ticket_key
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for src in source_paths:
        src_path = Path(src)
        if not src_path.is_file():
            continue
        dst = dest_dir / src_path.name
        # Collision-safe: if a same-named file already exists, add
        # `_1`, `_2`, ... until we find a free name.
        counter = 1
        while dst.exists():
            dst = dest_dir / f"{src_path.stem}_{counter}{src_path.suffix}"
            counter += 1
        try:
            shutil.copy2(src_path, dst)
            saved.append(str(dst.resolve()))
        except OSError:
            # e.g. permission error / disk full — skip that one attachment
            continue
    return saved


# ── Internals ──────────────────────────────────────────────────────────────

def _next_key(session: Session) -> str:
    """Compute the next BUGT-N key. Scans the existing keys rather than
    relying on the auto-increment id so a manually-inserted key doesn't
    cause a collision."""
    existing = session.query(Ticket.key).all()
    max_n = 0
    for (k,) in existing:
        try:
            n = int(k.split("-", 1)[1])
            if n > max_n:
                max_n = n
        except (IndexError, ValueError):
            continue
    return f"BUGT-{max_n + 1}"


def _ticket_to_dict(t: Ticket) -> dict:
    """Convert a Ticket ORM row to a plain dict --- for JSON logging + UI."""
    return {
        "key":          t.key,
        "summary":      t.summary or "",
        "description":  t.description or "",
        "status":       t.status or DEFAULT_STATUS,
        "component":    t.component or "",
        "priority":     t.priority or "",
        "assignee":     t.assignee or "",
        "reporter":     t.reporter or "",
        "duplicate_of": t.duplicate_of or "",
        "media_paths":  json.loads(t.media_paths or "[]"),
        "created":      t.created.isoformat(timespec="seconds") if t.created else "",
        "updated":      t.updated.isoformat(timespec="seconds") if t.updated else "",
    }


# ── CSV artifacts ──────────────────────────────────────────────────────────

EVENT_COLUMNS = ["timestamp", "event", "key", "payload"]

SNAPSHOT_COLUMNS = [
    "key", "summary", "description", "status", "component", "priority",
    "assignee", "reporter", "duplicate_of", "media_paths",
    "created", "updated",
]


def _append_event(event: str, key: str, payload: dict, when: datetime) -> None:
    """Append a single row to the event log. Writes a header on the very
    first append (fresh install / after a wipe). Never rewrites --- this
    file is the ground-truth mutation history."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not EVENT_LOG_PATH.exists()
    with EVENT_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp": when.isoformat(timespec="seconds"),
            "event":     event,
            "key":       key,
            # default=str handles the datetime inside the INSERT payload
            "payload":   json.dumps(payload, default=str, ensure_ascii=False),
        })


def _rewrite_snapshot() -> None:
    """Rewrite the full snapshot CSV from the current DB state.
    Not incremental --- simpler and always-consistent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tickets = list_tickets()
    with SNAPSHOT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SNAPSHOT_COLUMNS)
        writer.writeheader()
        for t in tickets:
            row = dict(t)
            # Flatten media_paths for CSV: semicolon-separated to avoid
            # collisions with the comma delimiter.
            row["media_paths"] = ";".join(row["media_paths"])
            writer.writerow(row)
