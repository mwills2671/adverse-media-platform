# AI Adverse Media Screening Platform — Phase 1 MVP

Screens an **individual** or an **entity** against legally accessible public sources (news, government and
regulatory publications, and official registers). It resolves identity with an explainable evidence-points model and
classifies events with the financial-crime taxonomy and event status. It then gives an explainable
**GREEN / AMBER / RED** result with real source links, an analyst workflow, a tamper-evident audit trail and a PDF
report. Built for UK AML/KYC analysts, with UK GDPR / DPA 2018 in mind (see `docs/DPIA_CHECKLIST.md`).

> **Every result comes from a live search.** Nothing is simulated or hardcoded. Labelled synthetic fixtures exist
> only for tests, and the server only accepts them when `AMS_TEST_MODE=1`, which is ignored when `APP_ENV=production`.
> The screen and the PDF both show exactly which providers ran, failed or were disabled. A screening whose research
> failed or is incomplete can never come out GREEN.

Docs: `docs/ARCHITECTURE.md` (stack and modules) · `docs/MVP_PLAN.md` (methodology, scoring, providers) ·
`docs/DPIA_CHECKLIST.md` · `docs/TEST_REPORT.md` (test evidence) · `shots/` (screenshots).

## Stack
- FastAPI (Python 3.12+) serves both the API and a prebuilt React 18 + TypeScript + Vite + Tailwind SPA.
- Data: PostgreSQL (SQLite locally).
- Libraries: SQLAlchemy 2, httpx (async), RapidFuzz, ReportLab.
- Packaging: one Docker image (`Dockerfile`), deployed on Render (`render.yaml` documents the setup).

## Local setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
(cd frontend && npm ci && npm run build)          # builds frontend/dist, served by FastAPI
cd backend && ../.venv/bin/uvicorn app.main:app --port 8077
# open http://localhost:8077 — in development an admin user is seeded and its random password is
# written to /workspace/amp/.admin_password.local (git-ignored, chmod 600). Set ADMIN_PASSWORD to choose your own.
```
Without `DATABASE_URL`, data is stored in `backend/ams_local.db` (SQLite, git-ignored).

## Environment variables
| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | prod: `production` | Enables secure cookies and HSTS, and ignores test mode |
| `DATABASE_URL` | prod | Postgres URL (`postgres://` is accepted and converted to psycopg3) |
| `SECRET_KEY` | prod | Session/CSRF signing key (random, at least 32 bytes) |
| `ADMIN_USERNAME` | no (default `admin`) | Seeded admin account |
| `ADMIN_PASSWORD` | prod (first start) | Seeded admin password (at least 12 characters). In production, nothing is seeded if it is unset |
| `SESSION_HOURS` | no (8) | Session lifetime |
| `CONTACT_EMAIL` | no | Contact in the User-Agent sent to providers (polite crawling) |
| `COMPANIES_HOUSE_API_KEY` | optional | UK Companies House: companies, officers and disqualified officers |
| `COURTLISTENER_API_TOKEN` | optional | US court opinions (CourtListener) |
| `NEWSAPI_KEY`, `GNEWS_API_KEY`, `BRAVE_API_KEY`, `SERPER_API_KEY`, `BING_SEARCH_KEY` | optional | Extra news and web search coverage |
| `LLM_API_KEY`, `LLM_BASE_URL` (default `https://api.x.ai/v1`), `LLM_MODEL` (default `grok-3-mini`) | optional | LLM-assisted summaries and classification (OpenAI-compatible chat API). The LLM output goes through a verifier |
| `AMS_TEST_MODE` | tests only | Allows labelled fixtures and fault injection. Ignored in production |
| `AMS_SSRF_ALLOW_CIDRS` | dev only | Extra CIDRs exempted from the SSRF guard (for sandboxes with fake DNS). Ignored in production |

### Providers and what degrades without keys
| Provider | Key | Notes |
|---|---|---|
| Google News RSS (9 locales/languages) | none | **Core, required** |
| GDELT DOC 2.0 | none | Core. Rate-limited, and often slow or timing out, which is reported |
| Bing News RSS | none | Core |
| GOV.UK Search API (SFO, FCA-adjacent, HMRC, Insolvency Service, OFSI, CPS press releases) | none | Core |
| US DOJ press releases API | none | Official |
| SEC litigation releases RSS | none | Official, recent window only |
| Companies House | `COMPANIES_HOUSE_API_KEY` (free) | Without it there are no UK register or disqualification checks, and the screen and PDF say so |
| CourtListener | `COURTLISTENER_API_TOKEN` (free) | Without it there is no US case-law search |
| NewsAPI / GNews / Brave / Serper / Bing Web | respective keys | Without them, coverage is the free RSS and official sources only |
| LLM | `LLM_API_KEY` | Without it, rule-based taxonomy and status classification with template summaries (fully deterministic) |
| OpenSanctions, FCA Register, etc. | — | **Link-outs only.** Not adverse media, and not sanctions or PEP screening |

Coverage rule: GREEN requires `google_news` plus at least 2 core providers to succeed. Anything less makes the
screening "incomplete" (AMBER), or FAILED if no provider succeeded.

## Tests
```bash
cd backend && ../.venv/bin/python -m pytest -q            # unit, API, security, labelled set (one test needs internet)
../.venv/bin/python tests/labelled_harness.py             # per-set accuracy table for the 81 synthetic labelled cases
python scripts/live_acceptance.py BASE USER PASSWORD_FILE out.json   # live screenings (genuine searches)
python scripts/smoke.py BASE USER PASSWORD_FILE                      # deployment smoke test
python scripts/screenshots.py ...                                     # Playwright screenshots at 1280 and 390 px
```
Scripts read passwords from a file and never print them.

## Deployment (Render)
1. Create a Render Postgres instance in Frankfurt.
2. Create a Docker web service from this repository in Frankfurt. Set `APP_ENV=production`, `DATABASE_URL` (the
   internal connection string), a random `SECRET_KEY`, and `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
3. Health check: `/api/health`.
4. After the first deploy, log in and create the analyst and readonly users in **Admin**.

`render.yaml` describes the same setup as a Blueprint.

## Security summary
- Passwords: scrypt hashing, login rate limiting, and account lockout after 5 failures.
- Sessions: `HttpOnly` + `SameSite=Strict` + `Secure` cookies, with CSRF tokens and an Origin check.
- Access: role-based (admin, analyst, readonly).
- Headers: strict CSP and other security headers.
- Outbound requests: an SSRF guard on article fetching, which respects robots.txt and never bypasses paywalls or
  logins.
- Audit and retention: a SHA-256 hash-chained audit log with a verify endpoint, plus configurable retention and
  deletion.
- Secrets live only in environment variables.
