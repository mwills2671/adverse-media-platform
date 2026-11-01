"""HTTP API. Every state-changing action is RBAC-checked, CSRF-protected and written to the hash-chained audit log."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, engine, report, settings_store
from ..analysis.rules import STATUS_LABEL, STATUS_ORDER
from ..config import settings
from ..db import get_db
from ..models import AuditEntry, Finding, Screening, User, now
from ..providers.registry import provider_catalog
from ..security import (COOKIE, ROLES, client_ip, create_session, current_session, current_user, destroy_session,
                        hash_password, login_limiter, password_policy_error, require, screen_limiter, verify_password)
from .serial import finding_out, screening_out, screening_summary

router = APIRouter(prefix="/api")
WRITE = require("admin", "analyst")
ADMIN = require("admin")
DISPOSITIONS = {"cleared_no_adverse_media": "Cleared — no relevant adverse media",
                "cleared_false_positive": "Cleared — matches were false positives",
                "accepted_risk_documented": "Adverse media noted — risk accepted and documented",
                "escalated_edd": "Escalated — enhanced due diligence required",
                "escalated_mlro": "Escalated to MLRO / financial crime team"}
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not login_limiter.allow(ip):
        raise HTTPException(429, "Too many login attempts — try again later")
    u = db.execute(select(User).where(User.username == body.username.strip())).scalar_one_or_none()
    if u and u.locked_until and (u.locked_until if u.locked_until.tzinfo else u.locked_until.replace(tzinfo=timezone.utc)) > datetime.now(timezone.utc):
        raise HTTPException(423, "Account temporarily locked after repeated failures")
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        if u:
            u.failed_logins += 1
            if u.failed_logins >= 5:
                u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                u.failed_logins = 0
            db.commit()
        audit.append(db, body.username.strip()[:64] or "?", "auth.login_failed", None, {"ip_prefix": ip.rsplit(".", 1)[0]})
        raise HTTPException(401, "Invalid username or password")
    u.failed_logins = 0
    u.last_login_at = now()
    db.commit()
    tok, csrf = create_session(db, u)
    response.set_cookie(COOKIE, tok, httponly=True, secure=settings.is_production, samesite="strict",
                        max_age=settings.session_hours * 3600, path="/")
    audit.append(db, u.username, "auth.login", None, {})
    return {"user": {"username": u.username, "role": u.role}, "csrf": csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response, sess=Depends(current_session), db: Session = Depends(get_db)):
    destroy_session(db, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    audit.append(db, sess[0].username, "auth.logout", None, {})
    return {"ok": True}


@router.get("/auth/me")
def me(sess=Depends(current_session)):
    u, row = sess
    return {"user": {"username": u.username, "role": u.role}, "csrf": row.csrf_token}


class PwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(body: PwIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password incorrect")
    err = password_policy_error(body.new_password)
    if err:
        raise HTTPException(400, err)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    audit.append(db, user.username, "auth.password_changed", None, {})
    return {"ok": True}


# ------------------------------------------------------------------ meta
@router.get("/meta")
def meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tax = settings_store.get_taxonomy(db)
    return {"providers": provider_catalog(), "test_mode": settings.test_mode, "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model if settings.llm_enabled else None, "app_env": settings.app_env,
            "ephemeral_storage": settings.is_production and settings.database_url.startswith("sqlite"),
            "taxonomy": {"groups": tax["groups"], "categories": [{k: c[k] for k in ("id", "group", "label", "severity", "weight", "enabled")}
                                                                 for c in tax["categories"]]},
            "statuses": [{"id": s, "label": STATUS_LABEL[s]} for s in STATUS_ORDER + ["unknown"]],
            "dispositions": DISPOSITIONS, "stages": engine.STAGES,
            "fixture_sets": sorted(p.stem for p in FIXTURE_DIR.glob("*.json")) if settings.test_mode else []}


# ------------------------------------------------------------------ screenings
class ScreenIn(BaseModel):
    subject_type: str = Field(pattern="^(individual|entity)$")
    name: str = Field(min_length=2, max_length=200)
    identifiers: dict = Field(default_factory=dict)
    test_fixture_set: str | None = None  # TEST MODE ONLY
    fault_injection: dict | None = None  # TEST MODE ONLY


ALLOWED_IDS = {"individual": {"aliases", "dob", "nationality", "country_of_residence", "country_of_birth", "occupation",
                              "employer", "associated_entities", "associated_people", "address"},
               "entity": {"aliases", "trading_names", "previous_names", "registration_number", "jurisdiction", "country",
                          "registered_address", "directors", "ubos", "parent_company", "sector", "website", "associated_people"}}


def _clean_ids(t: str, ids: dict) -> dict:
    out = {}
    for k, v in (ids or {}).items():
        if k not in ALLOWED_IDS[t] or v in (None, "", []):
            continue
        if isinstance(v, list):
            v = [str(x).strip()[:200] for x in v if str(x).strip()][:20]
        else:
            v = str(v).strip()[:300]
        if k == "dob" and v and not re.match(r"^\d{4}(-\d{2}-\d{2})?$", v):
            raise HTTPException(422, "Date of birth must be YYYY or YYYY-MM-DD")
        out[k] = v
    return out


@router.post("/screenings")
async def create_screening(body: ScreenIn, request: Request, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    if not screen_limiter.allow(user.username):
        raise HTTPException(429, "Screening rate limit reached — try again later")
    name = re.sub(r"\s+", " ", body.name).strip()
    ids = _clean_ids(body.subject_type, body.identifiers)
    test = bool(settings.test_mode and (body.test_fixture_set or body.fault_injection))
    if (body.test_fixture_set or body.fault_injection) and not settings.test_mode:
        raise HTTPException(400, "Test fixtures and fault injection are only available in test mode")
    fixtures = None
    if test and body.test_fixture_set:
        p = FIXTURE_DIR / f"{re.sub(r'[^a-z0-9_]', '', body.test_fixture_set)}.json"
        if not p.exists():
            raise HTTPException(404, "Unknown fixture set")
        from ..providers.base import RawItem
        fixtures = [RawItem(**it) for it in json.loads(p.read_text())["items"]]
    if test and body.fault_injection:
        ids["_fault_injection"] = {k: str(v)[:100] for k, v in body.fault_injection.items()}
    s = Screening(id=engine.new_id(), subject_type=body.subject_type, subject_name=name, identifiers=ids, created_by=user.username,
                  test_mode=test, stage="Queued")
    db.add(s)
    db.commit()
    audit.append(db, user.username, "screening.created", s.id,
                 {"subject_type": s.subject_type, "identifier_fields": sorted(k for k in ids if not k.startswith("_")),
                  "test_mode": test, "fixture_set": body.test_fixture_set if test else None,
                  "fault_injection": sorted((body.fault_injection or {}).keys()) if test else None})
    engine.start(s.id, fixtures)
    return {"id": s.id}


@router.get("/screenings")
def list_screenings(q: str = "", status: str = "", review_state: str = "", subject_type: str = "", date_from: str = "",
                    date_to: str = "", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Screening)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Screening.subject_name.ilike(like), Screening.id.ilike(like)))
    if status:
        stmt = stmt.where(Screening.final_status == status.upper())
    if review_state:
        stmt = stmt.where(Screening.review_state == review_state)
    if subject_type:
        stmt = stmt.where(Screening.subject_type == subject_type)
    if date_from:
        stmt = stmt.where(Screening.created_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(Screening.created_at < datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(Screening.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"total": total, "page": page, "items": [screening_summary(s) for s in rows]}


def _get(db, sid) -> Screening:
    s = db.get(Screening, sid)
    if not s:
        raise HTTPException(404, "Screening not found")
    return s


@router.get("/screenings/{sid}")
def get_screening(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return screening_out(_get(db, sid))


@router.get("/screenings/{sid}/progress")
def progress(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _get(db, sid)
    return {"id": s.id, "job_status": s.job_status, "stage": s.stage, "stage_index": s.stage_index, "stages": engine.STAGES,
            "provider_runs": [{k: r.get(k) for k in ("id", "name", "status", "results", "error", "core", "duration_ms")}
                              for r in (s.provider_runs or [])], "auto_status": s.auto_status}


class OverrideIn(BaseModel):
    status: str = Field(pattern="^(GREEN|AMBER|RED)$")
    reason: str = Field(min_length=10, max_length=4000)


def _final(s: Screening) -> str:
    return s.override_status or s.auto_status


@router.post("/screenings/{sid}/override")
def override(sid: str, body: OverrideIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = _get(db, sid)
    if s.job_status != "completed" and s.auto_status != "FAILED":
        raise HTTPException(409, "Screening not finished")
    if s.auto_status == "FAILED" and body.status == "GREEN":
        raise HTTPException(409, "A failed screening cannot be overridden to GREEN — re-run the screening")
    if s.review_state == "closed":
        raise HTTPException(409, "Reopen the case before changing the outcome")
    prev = _final(s)
    s.override_status, s.override_reason, s.override_by, s.override_at = body.status, body.reason.strip(), user.username, now()
    s.final_status = body.status
    db.commit()
    audit.append(db, user.username, "screening.override", s.id, {"from": prev, "to": body.status, "auto_status": s.auto_status,
                                                                 "reason": body.reason.strip()})
    return screening_summary(s)


class CloseIn(BaseModel):
    disposition: str
    notes: str = Field(default="", max_length=8000)


@router.post("/screenings/{sid}/close")
def close(sid: str, body: CloseIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = _get(db, sid)
    if body.disposition not in DISPOSITIONS:
        raise HTTPException(422, "Unknown disposition")
    if s.job_status not in ("completed", "failed"):
        raise HTTPException(409, "Screening not finished")
    pending = [f.id for f in s.findings if f.bucket == "review" and not f.decision]
    if pending:
        raise HTTPException(409, f"{len(pending)} 'requires review' finding(s) have no analyst decision yet")
    if _final(s) == "FAILED" and body.disposition.startswith("cleared"):
        raise HTTPException(409, "A failed screening cannot be cleared — re-run it")
    if s.incomplete and body.disposition.startswith("cleared") and not s.override_status:
        raise HTTPException(409, "Incomplete screening: record an override with reasoning before clearing, or re-run")
    s.review_state, s.disposition, s.reviewed_by, s.reviewed_at = "closed", body.disposition, user.username, now()
    if body.notes.strip():
        s.analyst_notes = body.notes.strip()
    db.commit()
    audit.append(db, user.username, "screening.closed", s.id, {"disposition": body.disposition, "final_status": _final(s)})
    return screening_summary(s)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=4000)


@router.post("/screenings/{sid}/reopen")
def reopen(sid: str, body: ReasonIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = _get(db, sid)
    if s.review_state != "closed":
        raise HTTPException(409, "Case is not closed")
    s.review_state = "reopened"
    db.commit()
    audit.append(db, user.username, "screening.reopened", s.id, {"reason": body.reason.strip(), "previous_disposition": s.disposition})
    return screening_summary(s)


class NotesIn(BaseModel):
    notes: str = Field(max_length=8000)


@router.post("/screenings/{sid}/notes")
def notes(sid: str, body: NotesIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = _get(db, sid)
    s.analyst_notes = body.notes
    db.commit()
    audit.append(db, user.username, "screening.notes_updated", s.id, {"length": len(body.notes)})
    return {"ok": True}


@router.post("/screenings/{sid}/rerun")
async def rerun(sid: str, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = _get(db, sid)
    if s.anonymised_at:
        raise HTTPException(409, "Anonymised screenings cannot be re-run")
    if s.test_mode:
        raise HTTPException(409, "Test-mode screenings cannot be re-run")
    if not screen_limiter.allow(user.username):
        raise HTTPException(429, "Screening rate limit reached")
    n = Screening(id=engine.new_id(), subject_type=s.subject_type, subject_name=s.subject_name, identifiers=s.identifiers,
                  created_by=user.username, stage="Queued")
    db.add(n)
    db.commit()
    audit.append(db, user.username, "screening.created", n.id, {"rerun_of": s.id, "subject_type": s.subject_type})
    engine.start(n.id)
    return {"id": n.id}


@router.get("/screenings/{sid}/report.pdf")
def report_pdf(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _get(db, sid)
    if s.job_status not in ("completed", "failed"):
        raise HTTPException(409, "Screening not finished")
    pdf = report.build_pdf(screening_out(s), user.username)
    audit.append(db, user.username, "report.exported", s.id, {"bytes": len(pdf), "result_hash": s.result_hash})
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{s.id}.pdf"', "Cache-Control": "no-store"})


# ------------------------------------------------------------------ findings
def _finding(db, fid) -> Finding:
    f = db.get(Finding, fid)
    if not f:
        raise HTTPException(404, "Finding not found")
    if f.screening.review_state == "closed":
        raise HTTPException(409, "Case is closed — reopen it first")
    return f


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(true_match|false_positive|unresolved)$")
    reason: str = Field(min_length=3, max_length=4000)


@router.post("/findings/{fid}/decision")
def decide(fid: int, body: DecisionIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    f = _finding(db, fid)
    prev = f.decision
    f.decision, f.decision_reason, f.decided_by, f.decided_at = body.decision, body.reason.strip(), user.username, now()
    db.commit()
    audit.append(db, user.username, "finding.decision", f.screening_id,
                 {"finding_id": f.id, "from": prev, "to": body.decision, "reason": body.reason.strip(), "url": f.url})
    return finding_out(f)


class BulkDecisionIn(DecisionIn):
    finding_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/screenings/{sid}/bulk-decision")
def bulk_decide(sid: str, body: BulkDecisionIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    """Apply one decision to many non-material findings. Material (RED-rule) findings must be decided individually."""
    s = _get(db, sid)
    if s.review_state == "closed":
        raise HTTPException(409, "Case is closed — reopen it first")
    ids = set(body.finding_ids)
    rows = [f for f in s.findings if f.id in ids]
    if len(rows) != len(ids):
        raise HTTPException(404, "Some findings do not belong to this screening")
    if any(f.material for f in rows):
        raise HTTPException(409, "Material findings must be reviewed and decided individually")
    t = now()
    for f in rows:
        f.decision, f.decision_reason, f.decided_by, f.decided_at = body.decision, body.reason.strip(), user.username, t
    db.commit()
    audit.append(db, user.username, "finding.bulk_decision", sid,
                 {"finding_ids": sorted(ids), "count": len(rows), "to": body.decision, "reason": body.reason.strip()})
    return {"updated": len(rows)}


class EscIn(BaseModel):
    escalated: bool
    reason: str = Field(default="", max_length=4000)


@router.post("/findings/{fid}/escalate")
def escalate(fid: int, body: EscIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    f = _finding(db, fid)
    f.escalated = body.escalated
    db.commit()
    audit.append(db, user.username, "finding.escalated" if body.escalated else "finding.deescalated", f.screening_id,
                 {"finding_id": f.id, "reason": body.reason.strip()})
    return finding_out(f)


@router.post("/findings/{fid}/notes")
def finding_notes(fid: int, body: NotesIn, user: User = Depends(WRITE), db: Session = Depends(get_db)):
    f = _finding(db, fid)
    f.notes = body.notes
    db.commit()
    audit.append(db, user.username, "finding.notes_updated", f.screening_id, {"finding_id": f.id, "length": len(body.notes)})
    return finding_out(f)


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_list(screening_id: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               user: User = Depends(require("admin", "analyst")), db: Session = Depends(get_db)):
    stmt = select(AuditEntry)
    if screening_id:
        stmt = stmt.where(AuditEntry.screening_id == screening_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(AuditEntry.seq.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"total": total, "items": [{"seq": r.seq, "ts": r.ts, "actor": r.actor, "action": r.action, "screening_id": r.screening_id,
                                       "details": r.details, "hash": r.hash, "prev_hash": r.prev_hash} for r in rows]}


@router.get("/audit/verify")
def audit_verify(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return audit.verify(db)


# ------------------------------------------------------------------ admin
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str
    role: str = Field(pattern="^(admin|analyst|readonly)$")


@router.get("/admin/users")
def users(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "role": u.role, "active": u.active, "created_at": u.created_at.isoformat(),
             "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}
            for u in db.execute(select(User).order_by(User.id)).scalars()]


@router.post("/admin/users")
def create_user(body: UserIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    err = password_policy_error(body.password)
    if err:
        raise HTTPException(400, err)
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise HTTPException(409, "Username exists")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    audit.append(db, user.username, "admin.user_created", None, {"username": u.username, "role": u.role})
    return {"id": u.id}


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|analyst|readonly)$")
    active: bool | None = None
    password: str | None = None


@router.patch("/admin/users/{uid}")
def patch_user(uid: int, body: UserPatch, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id and (body.active is False or (body.role and body.role != "admin")):
        raise HTTPException(409, "You cannot demote or disable your own account")
    changes = {}
    if body.role:
        u.role = changes["role"] = body.role
    if body.active is not None:
        u.active = changes["active"] = body.active
    if body.password:
        err = password_policy_error(body.password)
        if err:
            raise HTTPException(400, err)
        u.password_hash = hash_password(body.password)
        changes["password"] = "reset"
    db.commit()
    audit.append(db, user.username, "admin.user_updated", None, {"username": u.username, **changes})
    return {"ok": True}


@router.get("/admin/policy")
def get_policy(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"policy": settings_store.get_policy(db), "defaults": settings_store.default("policy")}


@router.put("/admin/policy")
def put_policy(body: dict, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    allowed = {"coverage", "red_rules", "identity_weights", "identity_levels", "fetch", "historical_years", "retention_days", "gdelt_timespan"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(422, f"Unknown policy keys: {sorted(bad)}")
    merged = settings_store.default("policy")
    settings_store._deep_update(merged, body)
    if merged["coverage"]["min_core_ok"] < 1:
        raise HTTPException(422, "min_core_ok must be ≥ 1 (failed research can never be GREEN)")
    if not 30 <= int(merged["retention_days"]) <= 3650:
        raise HTTPException(422, "retention_days must be between 30 and 3650")
    settings_store.save(db, "policy", body, user.username)
    audit.append(db, user.username, "admin.policy_updated", None, {"keys": sorted(body)})
    return {"ok": True}


@router.put("/admin/taxonomy")
def put_taxonomy(body: dict, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    ids = {c["id"] for c in settings_store.default("taxonomy")["categories"]}
    clean = {}
    for cid, o in body.items():
        if cid not in ids or not isinstance(o, dict):
            raise HTTPException(422, f"Unknown category {cid}")
        e = {}
        if "enabled" in o:
            e["enabled"] = bool(o["enabled"])
        if "weight" in o:
            w = float(o["weight"])
            if not 0 <= w <= 3:
                raise HTTPException(422, "weight must be 0–3")
            e["weight"] = w
        if "severity" in o:
            if o["severity"] not in ("low", "medium", "high", "critical"):
                raise HTTPException(422, "bad severity")
            e["severity"] = o["severity"]
        clean[cid] = e
    settings_store.save(db, "taxonomy_overrides", clean, user.username)
    audit.append(db, user.username, "admin.taxonomy_updated", None, {"categories": sorted(clean)})
    return {"ok": True}


def anonymise_screening(db: Session, s: Screening):
    for f in list(s.findings):
        db.delete(f)
    s.subject_name = "[anonymised]"
    s.identifiers = {}
    s.name_variants = []
    s.queries = []
    s.narrative = None
    s.analyst_notes = None
    s.override_reason = "[anonymised]" if s.override_reason else None
    s.coverage = {k: v for k, v in (s.coverage or {}).items() if k != "link_outs"}
    s.metrics = {k: v for k, v in (s.metrics or {}).items() if k != "raw_index"}
    s.provider_runs = [{k: r.get(k) for k in ("id", "name", "status", "results", "core")} for r in (s.provider_runs or [])]
    s.anonymised_at = now()


@router.post("/screenings/{sid}/anonymise")
def anonymise(sid: str, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    s = _get(db, sid)
    anonymise_screening(db, s)
    db.commit()
    audit.append(db, user.username, "screening.anonymised", s.id, {"reason": "admin request (erasure / minimisation)"})
    return {"ok": True}


@router.delete("/screenings/{sid}")
def delete(sid: str, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    s = _get(db, sid)
    db.delete(s)
    db.commit()
    audit.append(db, user.username, "screening.deleted", sid, {})
    return {"ok": True}


@router.post("/admin/retention/run")
def retention(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    days = int(settings_store.get_policy(db)["retention_days"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(select(Screening).where(Screening.created_at < cutoff, Screening.anonymised_at.is_(None))).scalars().all()
    for s in rows:
        anonymise_screening(db, s)
    db.commit()
    audit.append(db, user.username, "admin.retention_run", None, {"retention_days": days, "anonymised": len(rows)})
    return {"anonymised": len(rows), "retention_days": days}
