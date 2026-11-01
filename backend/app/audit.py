"""Tamper-evident, append-only audit log.

Each entry stores prev_hash and hash = SHA-256(prev_hash + canonical_json(entry)), where the canonical
entry is {ts, actor, action, screening_id, details} serialised with sorted keys and no whitespace.
Altering, deleting or re-ordering any historical row breaks the chain, which /api/audit/verify detects.
Audit details deliberately reference screening IDs rather than subject names so that anonymisation
of a screening never requires rewriting audit history.
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditEntry

GENESIS = "0" * 64
_lock = threading.Lock()


def canonical(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, entry: dict) -> str:
    return hashlib.sha256((prev_hash + canonical(entry)).encode("utf-8")).hexdigest()


def append(db: Session, actor: str, action: str, screening_id: str | None = None, details: dict | None = None) -> AuditEntry:
    with _lock:
        if db.bind and db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
        last = db.execute(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)).scalar_one_or_none()
        prev = last.hash if last else GENESIS
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="microseconds"), "actor": actor,
                 "action": action, "screening_id": screening_id, "details": json.loads(canonical(details or {}))}
        row = AuditEntry(ts=entry["ts"], actor=actor, action=action, screening_id=screening_id,
                         details=entry["details"], prev_hash=prev, hash=compute_hash(prev, entry))
        db.add(row)
        db.commit()
        return row


def verify(db: Session) -> dict:
    prev = GENESIS
    n = 0
    for row in db.execute(select(AuditEntry).order_by(AuditEntry.seq)).scalars():
        entry = {"ts": row.ts, "actor": row.actor, "action": row.action, "screening_id": row.screening_id,
                 "details": row.details}
        if row.prev_hash != prev:
            return {"valid": False, "entries": n, "broken_at": row.seq, "reason": "prev_hash does not match previous entry"}
        if compute_hash(prev, entry) != row.hash:
            return {"valid": False, "entries": n, "broken_at": row.seq, "reason": "entry content does not match its hash"}
        prev = row.hash
        n += 1
    return {"valid": True, "entries": n, "head": prev}
