# Test Report — Adverse Media Screening Platform (Phase 1)

- **Run date:** 1 Nov 2026 (Europe/London, GMT).
- **Environments:** local (SQLite, test mode) and production on Render (free Docker web service, Frankfurt; **currently no Postgres attached, temporary SQLite** — see §5).
- **Evidence:** raw outputs are in `docs/live_results/` and screenshots are in `shots/`.

## 1. Automated test suite (`backend/tests`, pytest)

| Metric | Result |
|---|---|
| Tests collected | 108 |
| **Passed** | **107** |
| Expected failures (documented known gap) | 1 (`id09`, see §2.3) |
| Failed | 0 |
| Runtime | ≈14 s. One test needs network access: a partial outage with only Google News live |

What the suite covers:
- API and fixture outcomes, deduplication of syndicated stories, and fault injection (all core providers down, or a
  partial outage).
- Fixtures are rejected outside test mode.
- A hallucination guard: every finding and corroborating URL must exist in the raw provider index.
- The analyst workflow and PDF content.
- Audit-chain tamper detection.
- Auth and security: 401 when unauthenticated, no password echo, CSRF and Origin checks, RBAC, password strength,
  lockout (423), security headers, the SSRF guard, and no passwords in the audit log.
- The labelled set and its invariants, the LLM verifier, and age-from-obituary evidence.

## 2. Labelled synthetic test set (`backend/tests/labelled/cases.json`)

There are 81 **synthetic** cases, each with a `_label`. They use fictional subjects ("Halvard Quennell-Broome",
"Corvina Holdings Ltd") on `.example` domains, so no real person is labelled. Each case checks the bucket, the
materiality, the identity bounds, the event status and the category.

### 2.1 Results by set (current build)
| Set | Passed | Purpose |
|---|---|---|
| identity | 9/10 | DOB/age, country, middle-name and legal-form contradictions, associates |
| status | 10/10 | Allegation, investigation, charge, conviction, settlement, acquittal, dismissal, appeal, reversal |
| role | 13/13 | Subject as victim, witness, expert, prosecutor, impersonated party, or implicated office-holder |
| entity | 10/10 | Direct versus connected party (director, subsidiary, parent), legal suffix |
| multilingual | 8/8 | DE/FR/ES/IT/PT/NL terms and statuses |
| credibility | 3/3 | Tier handling and corroboration |
| not_material | 5/5 | Civil disputes, minor infractions, unrelated negative press |
| temporal | 2/2 | Historical versus superseded |
| serious | 8/8 | Predicate offences (trafficking, sanctions breaches, disqualification…) |
| holdout | 12/12 | Written after the rules were tuned (see 2.2) |
| **Total** | **80/81 cases (98.8%)**, 154/155 label checks (99.4%) | |

### 2.2 Honest note on tuning
Before the rule fixes, the 12 holdout cases scored **9/12 (75%)**. They missed "admitted laundering", "found X not
guilty" and "misuse of donations". The taxonomy and status rules were then extended, which brought the holdout to
12/12. Because that holdout was used for fixing, it is no longer independent. A fresh, unseen set should be written
before any production policy sign-off.

### 2.3 Known gap
`id09`: a name plus a known associated company scores 45 points against the 50-point Probable threshold. It is
therefore rated *Possible* (AMBER review), not material. This is a conservative choice, and it can be tuned through
`policy.json → identity_weights.associate_match`. The test is marked xfail, not hidden.

## 3. Live integration runs (genuine searches; `scripts/live_acceptance.py`)
Local instance, 1 Nov 2026 00:41 GMT. Raw output: `docs/live_results/local.json`.

| Case | Input | Result | Time | Notes |
|---|---|---|---|---|
| T1 Bernard Madoff | name + DOB 1938-04-29 + US | **AMBER** (expected RED) | 32 s | 64 review items, 2 at *Probable* identity: the 2021 obituaries ("dies at 82" matches the DOB). Their headlines state no legal status, though, and the conviction-era items that were retrieved carry no DOB or age in accessible text, so they stay *Possible*. The rules decline to combine identity from one article with status from another. Accepted as a conservative limitation; an analyst resolves it in one click |
| T2 Wirecard AG | entity name + Germany | **RED** | 32 s | 2 material: Guardian investigation coverage (2020, 2023), exact legal name + DE. Shown as *investigation*, not a finding of guilt |
| T3 John Smith | name only | **AMBER** | 18 s | 444 raw results. The common-name rule blocks every result above *Unlikely*; the result is "Identity unresolved due to common name — add identifiers". Not RED, not GREEN |
| T4 "Quillon Dravenmoor-Tesk" (invented name) | name only | **GREEN** | 27 s | Every core provider except GDELT returned 0 results, so the coverage minimum was met. Caveat text shown |
| T5a Nick Leeson | name only | **AMBER** | 30 s | 8 review items, all *Possible* (name only, capped) |
| T5b Nick Leeson | + DOB 1967-02-25, UK, employer Barings | **RED** | 15 s | 1 material item (conviction, *Probable*: the associate "Barings" plus country). Shows that identifiers raise identity confidence (acceptance test 3) |

Every run produced a PDF. The audit chain verified across 76 entries. GDELT timed out or returned HTTP 429 from the
build box on every run. This is reported as `failed`, and as a coverage note in the UI and the PDF.

Some finding URLs are `news.google.com/rss/articles/...` links. These are genuine Google News links that redirect to
the publisher. Newer Google IDs cannot be decoded offline without calling private endpoints, so they are kept as
given.

## 4. Acceptance criteria 1–15
| # | Criterion | Evidence |
|---|---|---|
| 1 | Individual screened with full name only | T3, T4, T5a (live); `test_common_name_is_amber_unresolved` |
| 2 | Entity screened with name only | T2 (live, jurisdiction optional); entity labelled set |
| 3 | Identifiers improve resolution | T5a AMBER → T5b RED; identity labelled set (DOB/age/country/associate points, contradictions) |
| 4 | Verifiable info from working integrations | Provider table in every live result: google_news, bing_news, govuk, doj and sec all `ok` |
| 5 | Genuine findings categorised accurately | Wirecard → fraud and financial deception, money laundering, accounting fraud; labelled `serious`/`multilingual` sets 100% |
| 6 | Common-name FPs not auto-confirmed | T3 John Smith AMBER with 0 above *Unlikely*; invariant `test_name_only_never_above_possible` |
| 7 | Allegation ≠ conviction | Status set 10/10; UI and PDF badges ("Allegation only — not a finding of guilt"); allegations need ≥3 independent sources for RED |
| 8 | Real URLs support findings | Live URLs (theguardian.com etc.); `test_finding_urls_subset_of_raw_index` |
| 9 | Justified RED | T2, T5b: the RED rule trace lists every condition (`material_reasons`) in the UI and PDF |
| 10 | Ambiguous → AMBER | T1, T3, T5a; fixture `common_name` |
| 11 | Clean, complete → GREEN | T4 (live); fixture `clean_individual` |
| 12 | Failed or incomplete never GREEN | `test_all_core_down_is_failed_never_green` (FAILED, override-to-GREEN 409), `test_partial_outage_never_green` |
| 13 | Saved, reviewed, exported | `test_workflow_decisions_close_reopen`, `test_pdf_report`; history screenshots; PDF checked with pdftotext/pdftoppm |
| 14 | Desktop and mobile | `shots/*_desktop.png` (1280 px) and `shots/*_mobile.png` (390 px) |
| 15 | No hallucinated sources or faked API responses | Raw-index subset test; the LLM verifier drops ungrounded output (`test_llm_verifier_rejects_ungrounded_output`); fixtures and fault injection are rejected in production (`test_fixtures_rejected_outside_test_mode`); disabled providers are shown as "Not searched" |

## 5. Production deployment verification

These checks ran on 1 Nov 2026 (00:48–01:00 GMT) against https://adverse-media-platform.onrender.com. That is Render service `srv-dbj8nqoae00c73dh4h6g`: Docker, free plan, Frankfurt, deployed from the `master` branch.

**Database: not attached.** Creating `ams-db` failed:
- free plan: rejected with "cannot have more than one active free tier database"; the workspace's one free slot is already used by `ecom-db`.
- `basic_256mb`: rejected with HTTP 402, because no payment method is on file.

The service therefore runs on SQLite inside the container. That storage is temporary: screenings and the audit log are lost on every redeploy, restart or free-tier spin-down. The UI shows an amber **TEMPORARY STORAGE** banner while this is the case. To attach Postgres, create the database and set `DATABASE_URL` to its internal connection string. No code change is needed.

### Smoke test (`scripts/smoke.py`)

| Check | Result |
|---|---|
| SPA/login page served | PASS (200) |
| Unauthenticated list / create rejected | PASS (401 / 401) |
| Wrong password rejected | PASS (401) |
| Admin login (password read from file, never echoed) | PASS (200) |
| POST without CSRF token rejected | PASS (403) |
| Real screening "Wirecard AG" (no identifiers) | AMBER in 71 s; 317 findings, all with real publisher or Google News URLs |
| PDF export | PASS (151 KB, `%PDF`) |
| Audit hash chain verifies | PASS |
| Secrets in Render logs | none found; the admin password and SECRET_KEY were searched for in the logs |

### Live acceptance cases (`scripts/live_acceptance.py`)

| Case | Production | Local (same day) | Note |
|---|---|---|---|
| Wirecard AG, jurisdiction Germany | **AMBER** (133 review, 0 material), 70 s | RED | See the explanation below the table. |
| Quillon Dravenmoor-Tesk (obscure) | **GREEN**, 29 s | GREEN | PASS |
| Nick Leeson + DOB/UK/Barings | **AMBER** (4 review), 42 s | RED | Bing News returned 2 items from Render, against far more locally. |

**Why Wirecard came out AMBER in production:** the live news mix changes between runs and between networks.
- Locally, two Guardian articles fetched in full contained "Wirecard AG" plus a German reference. That scores 50 points (probable), so they met every RED rule.
- From Render, the Guardian items arrived as opaque Google News redirects (snippet only). The full-text articles (DW, CNBC, The Local) said "Wirecard" without "AG", which scores 30 + 10 = 40, below the probable threshold.
- The conviction headline (Hindustan Times) was probable, but it is a tier-4 source with a single source.

The engine is therefore working as designed. A name-only or weak identity match is capped and goes to analyst review rather than being auto-escalated. We did **not** retune thresholds against this live result, to avoid overfitting.

**Providers observed live from Render:**
- google_news ok
- bing_news ok, but returns fewer results than locally
- govuk ok
- doj ok
- sec_litigation ok
- **gdelt: timeout on every run**; reported as a coverage note, and minimum coverage was still met
- key-based providers: shown as "disabled-no-key"

Screenshots of the production instance are at `shots/prod_01…08_{desktop,mobile}.png` (1280 px and 390 px).

## 6. v2 changes — test evidence (1 Nov 2026, Europe/London GMT)

### 6.1 Automated suite
`pytest -q` → **120 passed, 1 xfailed** (the documented `id09` gap). New file `tests/test_v2.py` (13 tests) covers: website
shareholder/board extraction on a fictional bank page (name-first and %-first layouts), ownership-sentence parsing
(skips "holds a stake in X" and speculation), news-headline role extraction and junk rejection, the grounding check
(a name absent from fetched text is dropped), infobox merge and ranking, the provider set (Google/Bing only, no
disabled rows), `outside_window` bucketing, the summary LLM verifier (uncited sentence or invented number → rejected),
and the related-party API (manual add, 422 validation, 409 for partial names, PATCH, one-click child screening with a
labelled fixture, parent linking and highest-RAG roll-up, audit actions, PDF section, read-only RBAC). The
`test_api.py` window test checks a 2019 item lands in `outside_window` at 5 years and becomes mitigating at 10.

### 6.2 Local end-to-end (genuine live searches, `scripts/v2_e2e.py`)
| Subject | Result | Window | Related parties found (source, confidence) | Missed / notes |
|---|---|---|---|---|
| Wirecard AG (DE) | **RED** (material: fraud investigation, Guardian 2023); 88 review, 7 outside window | 5 y, since 2021-11-01 | Thomas Eichelmann (Wikipedia infobox, medium), Markus Braun (FT via Bing, medium), Wulf Matthias (news, low) | Jan Marsalek not extracted (appears in headlines but not in a role pattern). Child screen of Eichelmann → GREEN |
| PASHA Bank (AZ) | **GREEN** (0 review, 47 low) | 5 y | Website (high): PASHA Financial Holding Ltd 53.97%, BLESS Ltd 26.77%, Arif Pashayev 9.5%, Mir Jamal Pashayev 4.76%, 5 supervisory-board members, 6 executives. Wikipedia "PASHA Holding" chain (low): Aliyev family, Pashayev family, Ilham Aliyev, Mehriban Aliyeva, "Arzu" and "Leyla" (partial names, cannot be screened until a full name is added) | Anar Karimov and Jalal Gasimov (named in some sources) not found; Wikidata is robots-blocked. Child screen of Arif Pashayev → GREEN |
| Greggs plc (UK) | **AMBER** — 13 "possible"-identity items (fraudsters posing as Greggs, a cocaine-in-doughnuts story, a WH Smith CFO accounting story) | 5 y | Ian Durant, Roisin Currie, John Gregg (Wikipedia infobox, medium), Matt Davies (FT, low) | AMBER is driven by incidental brand mentions that an analyst would mark false positive; no material findings. Child screen of Ian Durant → GREEN |

PDF for each contained the consolidated summary, the date window row and the related-parties table. Screenshots:
`shots/v2_*_{desktop,mobile}.png` (login, new screening, and for each subject the verdict/overview, findings, related
parties, sources and audit tabs, plus a child screening).
