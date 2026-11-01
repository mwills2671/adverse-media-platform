"""FastAPI application: API + security headers + pre-built SPA."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import audit
from .api.routes import router
from .config import settings
from .db import Base, SessionLocal, engine
from .models import Screening, now
from .security import seed_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ams")
# Request URLs contain screened subjects' names (personal data): keep them out of platform logs (UK GDPR data minimisation).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="Adverse Media Screening", docs_url=None if settings.is_production else "/api/docs",
              redoc_url=None, openapi_url=None if settings.is_production else "/api/openapi.json")
app.include_router(router)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h.setdefault("Content-Security-Policy", CSP)
    if settings.is_production:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api"):
        h["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_admin(db)
        # Jobs cannot survive a restart: mark them FAILED (never GREEN) so analysts re-run them.
        stuck = db.execute(select(Screening).where(Screening.job_status.in_(("queued", "running")))).scalars().all()
        for s in stuck:
            s.job_status, s.auto_status, s.final_status = "failed", "FAILED", "FAILED"
            s.auto_reasons = ["Screening was interrupted by a server restart before completing — re-run required."]
            s.incomplete = True
            s.completed_at = now()
        db.commit()
        for s in stuck:
            audit.append(db, "system", "screening.failed", s.id, {"reason": "interrupted by restart"})
    log.info("Started (env=%s, db=%s, test_mode=%s, llm=%s)", settings.app_env, engine.dialect.name, settings.test_mode,
             settings.llm_enabled)


_static = settings.static_dir
if (_static / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    f = (_static / path).resolve()
    if path and f.is_file() and _static.resolve() in f.parents:
        return FileResponse(f)
    idx = _static / "index.html"
    if idx.exists():
        return FileResponse(idx, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Frontend not built"}, status_code=503)
