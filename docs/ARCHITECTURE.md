# Architecture — Adverse Media Screening Platform (Phase 1 MVP)

## 1. Decision summary

| Concern | Choice | Why |
|---|---|---|
| Frontend | **React 18 + TypeScript + Vite + Tailwind CSS** single-page app (SPA) | Same component model as Next.js, but builds to static files that the API server can serve. No Node runtime in production, one container, one origin (no CORS, simpler cookie/CSRF security). |
| Backend | **Python 3.12 + FastAPI** (uvicorn) | Async I/O for many concurrent provider calls; strong NLP / fuzzy-matching ecosystem (RapidFuzz); typed request validation (Pydantic). |
| Background jobs | In-process asyncio task per screening, progress persisted to DB, browser polls `/api/screenings/{id}` | Phase 1 volumes (single analyst team) do not justify a queue. Each stage and provider result is written to the DB as it completes, so a restart leaves a visible "failed / incomplete" screening — never a silent GREEN. Phase 3 moves this to a worker + queue (Render Background Worker + Key Value). |
| Database | **PostgreSQL** on Render (via `DATABASE_URL`), **SQLite** fallback locally | SQLAlchemy 2.0 ORM, portable JSON columns. |
| PDF | **ReportLab** (pure Python, no system libs) | Installs cleanly in `python:3.12-slim`; deterministic server-side rendering. |
| Deployment | **One Docker web service** (multi-stage build: Node builds SPA → Python image serves API + static SPA) + **Render Postgres**, region Frankfurt | Satisfies "normal public HTTPS web app protected by login", usable from a locked-down laptop with only a browser. |

Next.js was considered; it would need either a second Node service (two deploys, cross-origin cookies) or a Node runtime inside the Python container. A Vite SPA served by FastAPI keeps the same architecture (React/TS/Tailwind front end, FastAPI back end, Postgres) with fewer moving parts.

## 2. Module layout

```
backend/app/
  main.py               FastAPI app, security headers, static SPA serving, startup (DB init, admin seed)
  config.py             Settings from env vars (no secrets in code)
  db.py, models.py      SQLAlchemy engine/session + ORM models
  security.py           scrypt password hashing, sessions, CSRF, login rate limiting, RBAC dependencies
  audit.py              Append-only SHA-256 hash-chained audit log + verification
  settings_store.py     Taxonomy / policy / retention config (JSON defaults in data/, overrides in DB)
  engine.py             Screening orchestrator (8 stages, provider fan-out, persistence)
  scoring.py            Deterministic finding relevance + overall GREEN/AMBER/RED model
  narrative.py          Deterministic analyst-conclusion template (LLM-assisted optional)
  report.py             PDF report (ReportLab)
  providers/            Pluggable research providers (one module per source family)
    base.py             Provider interface, RawItem, ProviderRun (status, counts, error, duration), retry/timeout
    google_news.py      Google News RSS, 9 locales
    gdelt.py            GDELT DOC 2.0 (global 1 req / 5 s limiter, 429 tolerant)
    bing_news.py        Bing News RSS
    govuk.py            GOV.UK Search API (HMRC, Insolvency Service, SFO, OFSI, CPS... press releases)
    doj.py              US DOJ press releases API
    sec.py              SEC litigation releases RSS (recent window only)
    companies_house.py  UK Companies House (key required): company/officer search, disqualified officers
    courtlistener.py    CourtListener opinions search (free token required)
    keyed_news.py       NewsAPI, GNews, Brave Search, Serper (keys required, disabled otherwise)
    linkouts.py         Non-searched link-outs (FCA Register / Warning List, OpenSanctions — reference only)
  research/
    names.py            Name normalisation, variants (diacritics, order, initials, transliteration, legal suffixes)
    queries.py          Query planner (name variants × taxonomy risk-term groups × languages)
    fetcher.py          SSRF-safe, robots-respecting article fetcher (short excerpts only)
    dedupe.py           URL normalisation + title shingle Jaccard clustering (original vs corroborating)
    credibility.py      Source tiers (domain list + heuristics)
  analysis/
    taxonomy.py         Risk-category matcher (multilingual phrase patterns)
    rules.py            Rule-based extractor: event status, mitigation, dates, implication role, quotes
    identity.py         Explainable identity-match evidence scoring
    llm.py              Optional OpenAI-compatible LLM layer + verifier (falls back to rules)
  api/                  Routers: auth, screenings, findings, admin, audit, reports
  data/                 taxonomy.json, policy.json, domains.json, common_names.json
frontend/               Vite React TS Tailwind SPA (src/pages, src/components)
backend/tests/          pytest unit + integration tests, labelled fixtures (TEST FIXTURES ONLY)
```

## 3. Data model (key tables)

* **users** — id, username, password_hash (scrypt, per-user salt), role (`admin` | `analyst` | `readonly`), active, failed_logins, locked_until, created_at.
* **sessions** — token_hash (SHA-256 of random cookie token), user_id, csrf_token, created_at, expires_at.
* **screenings** — id (`AMS-YYYYMMDD-XXXXXX`), subject_type, subject_name, identifiers (JSON), job_status (queued/running/completed/failed), stage + stage index, provider_runs (JSON), coverage (JSON), auto_status, auto_reasons, final_status, override (by, reason, at), narrative, analysis_mode, disposition, analyst_notes, review_state (open/closed/reopened), reviewed_by/at, created_by/at, completed_at, test_mode, anonymised_at, result_hash.
* **findings** — screening_id, cluster original (url, title, source, domain, published_at, provider), corroborating (JSON list of {url,title,source,date}), excerpt (≤ ~1,200 chars), quotes (JSON: text + offsets), categories, primary_category, severity, event_status(+all detected), mitigation, event_date, temporal (current/historical), implication (direct/bystander/unclear), party (direct/connected), identity_level, identity_points, identity_evidence, contradictions, credibility_tier, relevance, triage bucket, summary, analysis_mode, analyst decision/reason/by/at, escalated.
* **audit_log** — seq, ts, actor, action, screening_id, details (JSON), prev_hash, hash = SHA-256(prev_hash + canonical JSON of entry). Append only (no update/delete API; anonymisation adds a new entry and never rewrites old entries' hashes; see DPIA notes).
* **app_config** — key → JSON (taxonomy overrides, policy thresholds, retention days).

## 4. Screening pipeline (stages shown in the UI)

1. **Validating subject** — Pydantic validation, normalisation, screening ID allocation, audit entry.
2. **Expanding names and aliases** — `names.py` variants: exact, diacritics-folded, name order swap ("Smith John"), initial forms ("J. Smith"), legal-suffix stripped / expanded (Ltd ↔ Limited, AG ↔ Aktiengesellschaft), user-supplied aliases/previous names, simple transliteration variants (e.g. ü→ue).
3. **Searching public information** — query planner combines the subject name with taxonomy risk-term groups (English + FR/DE/ES/IT/PT/NL/AR terms) and runs all enabled providers concurrently, each with timeout, retry with back-off, and its own status record.
4. **Retrieving candidate sources** — URL normalisation, Bing/Google redirect resolution where possible, de-duplication and syndication clustering; SSRF-safe, robots.txt-respecting fetch of article text for the top N candidates (short excerpt kept, full text discarded).
5. **Resolving identity** — `identity.py` evidence points.
6. **Classifying adverse findings** — `taxonomy.py` + `rules.py` (+ optional LLM, verified).
7. **Assessing risk and evidence** — `scoring.py` per finding relevance + triage; overall status.
8. **Preparing final results** — narrative, coverage statement, result hash, audit entry.

## 5. Scoring model (deterministic heuristic — not a probability)

See `docs/MVP_PLAN.md §5` and `backend/app/data/policy.json`. Identity confidence, event severity, source reliability and overall status are separate fields and are displayed separately.

## 6. Security architecture

* Session cookie `ams_session`: random 256-bit token, stored hashed server side, `HttpOnly; Secure (production); SameSite=Strict`, 8 h idle/absolute expiry.
* CSRF: synchroniser token bound to the session, returned by `/api/auth/me`, required in `X-CSRF-Token` header on every state-changing request; plus Origin check.
* Login rate limiting: per-IP sliding window and per-account lockout after repeated failures.
* RBAC: `admin` (users, policy, taxonomy, retention, delete/anonymise, overrides), `analyst` (screen, decide, notes, override with reason, reopen), `readonly` (view and export).
* Security headers: CSP (self only), HSTS (production), X-Frame-Options DENY, nosniff, Referrer-Policy no-referrer, Permissions-Policy.
* Article fetcher SSRF controls: http(s) only, DNS resolved and private/loopback/link-local/reserved ranges blocked on every hop, ≤ 3 redirects, text/html only, 1.5 MB cap, 8 s timeout, robots.txt honoured, identifying User-Agent.
* Secrets only via env vars; `.env`, `.admin_password`, DB files are git-ignored.
* Encryption: TLS in transit (Render-managed certificates); Render Postgres encrypts data at rest. Optional application-level field encryption (Phase 2) is described in DPIA checklist.

## 7. Deployment

`Dockerfile` (multi-stage) + `render.yaml` (documentation of the service/DB). Render web service (docker runtime, Frankfurt) with env vars: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `APP_ENV=production`, optional provider keys and `LLM_*`.

## 8. v2 additions (Nov 2026)
| Area | Module | Notes |
|---|---|---|
| Source set | `providers/registry.py` | `active_providers()` = Google News + Bing News (media) plus keyless official lookups (GOV.UK, DOJ, SEC); Companies House only with a key. Others kept in code, opt-in via `AMS_EXTRA_PROVIDERS`. `provider_catalog()` lists only active providers |
| Date window | `providers/base.SearchContext`, `scoring.classify`/`outside_window`, `engine.py` | `SearchContext(lookback_years)` → `window_start`. Relevant items older than the window go to bucket `outside_window` (rank 2) and are excluded from RAG. Per-screening `lookback_years` (0 = none, max 30) is stored in `identifiers._lookback_years` and audited |
| Consolidated summary | `summary.py` | Deterministic `build()` → verdict, label, one-line reason, paragraphs, numbered facts, themes, window, coverage flag. Optional `llm_rewrite()` is accepted only if `verify_llm()` passes (every sentence cites a fact; every number appears in the fact payload) |
| Related parties | `research/related.py`, `models.RelatedParty`, `api/routes.py` | `discover()` runs concurrently with stage 2–4 of an entity screening (timeout `related_parties.timeout_s`). Sources: company website (robots-checked governance/shareholder pages, table and sentence extraction with name/pct orientation detection), Wikipedia REST by exact title + infobox, ownership chain (`chain_depth`), Google/Bing News RSS headlines. `ground()` drops any name not present in fetched text. `merge()` de-duplicates and ranks. Rows persisted with origin `auto`/`manual`, state `candidate`/`confirmed`/`dismissed`, evidence JSON |
| Child screenings | `POST /related-parties/{id}/screen` | Creates a linked screening (`identifiers._parent`), inherits the window; individuals get the parent as an associated entity (identity evidence); entity children skip their own discovery. Refuses family/partial/single-token names (409) |
| Parent roll-up | `api/serial.related_block()` | `related_summary` = total, screened, completed, highest RAG (RED>AMBER>FAILED>GREEN), hits, overall note, pending. Kept separate from the subject's own `final_status`; included in the close-case audit and the PDF |
| Concurrency | `engine.py` | Global semaphore (3 concurrent screenings) so one-click child screenings queue rather than overload the free instance |
| UI | `pages/Screening.tsx`, `pages/RelatedParties.tsx`, `index.css` | Verdict banner, tabs, coverage chip, related-party table with Screen/Confirm/Dismiss/Add full name and manual add; gradient/dot-grid backgrounds (`.bg-app`, `.bg-login`), print falls back to white |

Endpoints added: `GET/POST /api/screenings/{sid}/related-parties`, `PATCH /api/related-parties/{rid}`,
`POST /api/related-parties/{rid}/screen`. Audit actions: `related_parties.discovered`, `related_party.added`,
`related_party.updated`, `related_party.screened`.
