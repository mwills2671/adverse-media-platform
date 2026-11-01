"""Authentication, sessions, CSRF, login rate limiting and RBAC."""
import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import SessionRow, User

COOKIE = "ams_session"
ROLES = ("admin", "analyst", "readonly")
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def password_policy_error(pw: str) -> str | None:
    if len(pw) < 12:
        return "Password must be at least 12 characters."
    classes = sum([any(c.islower() for c in pw), any(c.isupper() for c in pw), any(c.isdigit() for c in pw),
                   any(not c.isalnum() for c in pw)])
    if classes < 3:
        return "Password must contain at least three of: lower case, upper case, digit, symbol."
    return None


def _token_hash(tok: str) -> str:
    return hashlib.sha256((settings.secret_key + tok).encode()).hexdigest()


class RateLimiter:
    """Sliding window per key (IP)."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        t = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and t - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(t)
            return True


login_limiter = RateLimiter(limit=10, window_s=300)
screen_limiter = RateLimiter(limit=30, window_s=3600)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def create_session(db: Session, user: User) -> tuple[str, str]:
    tok = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.execute(delete(SessionRow).where(SessionRow.expires_at < datetime.now(timezone.utc)))
    db.add(SessionRow(token_hash=_token_hash(tok), user_id=user.id, csrf_token=csrf,
                      expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)))
    db.commit()
    return tok, csrf


def destroy_session(db: Session, tok: str | None) -> None:
    if tok:
        db.execute(delete(SessionRow).where(SessionRow.token_hash == _token_hash(tok)))
        db.commit()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def current_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, SessionRow]:
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Not authenticated")
    row = db.get(SessionRow, _token_hash(tok))
    if not row or _aware(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")
    user = db.get(User, row.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account disabled")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, row.csrf_token):
            raise HTTPException(403, "CSRF token missing or invalid")
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if origin.split("://", 1)[-1] != host:
                raise HTTPException(403, "Cross-origin request rejected")
    return user, row


def current_user(sess=Depends(current_session)) -> User:
    return sess[0]


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Insufficient role")
        return user
    return dep


def seed_admin(db: Session) -> None:
    import logging
    log = logging.getLogger("ams")
    if db.execute(select(User).limit(1)).scalar_one_or_none():
        return
    pw = settings.admin_password
    if not pw:
        if settings.is_production:
            log.error("No users exist and ADMIN_PASSWORD is not set; cannot seed admin.")
            return
        pw = "LocalDev-" + secrets.token_urlsafe(12)
        path = settings.static_dir.parent.parent / ".admin_password.local"
        try:
            path.write_text(pw)
            path.chmod(0o600)
            log.warning("Seeded local admin; password written to %s", path)
        except OSError:
            log.warning("Seeded local admin but could not write password file")
    db.add(User(username=settings.admin_username, password_hash=hash_password(pw), role="admin"))
    db.commit()
