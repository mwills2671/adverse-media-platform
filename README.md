# AI Adverse Media Screening Platform — Phase 1 MVP (v2)

Screens an **individual** or an **entity** against legally accessible public sources (news, government and
regulatory publications, and official registers). It resolves identity with an explainable evidence-points model and
classifies events with the financial-crime taxonomy and event status. It then gives an explainable
**GREEN / AMBER / RED** result with real source links, an analyst workflow, a tamper-evident audit trail and a PDF
report. Built for UK AML/KYC analysts, with UK GDPR / DPA 2018 in mind (see `docs/DPIA_CHECKLIST.md`).

> **Every result comes from a live search.** Nothing is simulated or hardcoded. Labelled synthetic fixtures exist
> only for tests, and the server only accepts them when `AMS_TEST_MODE=1`, which is ignored when `APP_ENV=production`.
> The screen and the PDF both show exactly which providers ran or failed. A screening whose research
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

### Sources (v2)
| Source | Key | Notes |
|---|---|---|
| Google News RSS (9 locales/languages) | none | **Core adverse-media source** |
| Bing News RSS | none | **Core adverse-media source** |
| GOV.UK Search API, US DOJ press releases, SEC litigation releases | none | Official-record lookups (primary sources, keyless) |
| Companies House | `COMPANIES_HOUSE_API_KEY` | Runs **only if the key is set**; otherwise it is not shown at all |
| LLM | `LLM_API_KEY` | Optional. Rewrites the consolidated summary; every sentence must cite a fact and every number must exist in the facts, otherwise the rule-based summary is kept |
| GDELT, NewsAPI, GNews, Brave, Serper, Bing Web, CourtListener | — | Code kept but **off by default and hidden**. An operator can re-enable with `AMS_EXTRA_PROVIDERS=gdelt,newsapi,…` (keyed ones still need their key) |
| OpenSanctions, FCA Register, OpenCorporates, GLEIF, OpenOwnership | — | **Link-outs only** (manual checks). Not machine-searched |

Inactive providers never produce "disabled / no key" rows anywhere (UI, PDF, API).

Coverage rule: GREEN requires both Google News and Bing News to succeed (`policy.json → coverage.min_core_ok = 2`).
Anything less is "incomplete" (AMBER + a "Coverage incomplete" chip on the verdict banner), or FAILED if nothing succeeded.

### Date window
Default look-back is **5 years** (`policy.json → lookback_years`, editable by admins; per screening via the
"Date window" selector, 1–20 years or "No date limit"). Relevant items published before the window start are moved
to an **Outside date window** bucket: shown for context, excluded from the RAG status. The window is shown on the
verdict banner, the Sources tab and the PDF.

### Results page (v2)
Full-width verdict banner (GREEN / AMBER / RED / FAILED, label, one-line reason, window and coverage chips), then tabs:
**Overview** (consolidated summary, triage, rating reasons) · **Findings** (review / mitigating / outside window / low,
filters, bulk decisions) · **Related parties** · **Sources** (provider runs, queries, manual link-outs, sanctions/PEP
reference) · **Audit / decision** (override, close, notes, case audit trail).

### Related-party background search (entities)
Runs alongside the media search for entity screenings, using keyless public sources that permit automated access:
the company's own website (governance / shareholders / management pages, robots.txt respected), Wikipedia (exact
article titles only, via the REST endpoint; `/w/` is robots-disallowed), and Google/Bing News RSS. Wikidata and
OpenCorporates are robots-blocked, so they are offered as manual links instead.
- Every lead carries **source URL(s), a verbatim quote, a confidence level** (high = company's own site, medium =
  Wikipedia infobox / several sources, low = single news mention or ownership chain) and is labelled **Unverified**.
- **No hallucination:** a name is kept only if it appears verbatim in the fetched text it cites (the grounding check
  runs after extraction). Extraction is rule-based; if `LLM_API_KEY` is set, an optional LLM pass may add
  leads, but only if the name occurs verbatim in the snippet it cites, and those are always low confidence.
- Ownership chains are followed up to `chain_depth` (default 2), e.g. a holding company's own Wikipedia article.
- Nothing is hard-coded for any company.
- Analysts can **add parties manually**, edit a name, confirm or dismiss, and **Screen** one with one click. That creates a
  linked child screening; its RAG appears in the table. The parent shows its own RAG and the **highest related-party
  RAG** separately, and the decision note and close-case audit record the related-party hits. All actions are audited and
  the parties are included in the PDF.

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
