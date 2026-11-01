# MVP Plan — Adverse Media Screening Platform

## 1. Goal of Phase 1
A genuinely working, login-protected web app where an AML/KYC analyst enters a name (individual or entity), optionally adds identifiers, clicks **Screen**, and receives a structured, source-linked, colour-coded result they can review, decide on, and export to PDF — with honest disclosure of what was and was not searched.

## 2. Phase scope

| Phase | Scope |
|---|---|
| **1 (this build)** | Individual/entity switch; name-only or enriched screening; live keyless providers (Google News RSS ×9 locales, GDELT DOC 2.0, Bing News RSS, GOV.UK Search API, US DOJ press releases API, SEC litigation releases RSS); optional keyed providers (Companies House, CourtListener, NewsAPI, GNews, Brave, Serper); name-variant expansion; multilingual risk terms (EN/FR/DE/ES/IT/PT/NL/AR); robots-respecting excerpt fetch; dedupe & syndication clustering; configurable taxonomy; rule-based event-status/mitigation/implication extraction; explainable identity matching; source tiers; deterministic GREEN/AMBER/RED with coverage gating; optional LLM-assisted structured analysis with verifier; analyst decisions, escalation, notes, override, reopen; history & filters; hash-chained audit log; PDF report; RBAC; admin config; retention/anonymise. |
| **2** | Advanced identity resolution (NER model, transliteration library e.g. ICU for Cyrillic/Arabic/CJK scripts), more providers (licensed news archives: Factiva / LexisNexis / Refinitiv World-Check media, Dow Jones RiskCenter; national regulators’ APIs; EU/other court registries), full multilingual NLP, ML false-positive reduction trained on analyst dispositions, richer workflows (four-eyes approval), field-level encryption, SSO (Entra ID/SAML), improved analytics. |
| **3** | Bulk screening (CSV/API), scheduled rescreening & continuous monitoring with alerts, public screening API, integration with KYC/CLM platforms, management dashboards, queue-based workers. |

## 3. Providers

| Provider | Type | Key needed | Default | Notes / limits |
|---|---|---|---|---|
| Google News RSS | News aggregator | No | **Core**, on | 9 locales (en-GB, en-US, fr-FR, de-DE, es-ES, it-IT, pt-BR, nl-NL, ar-AE). ~100 items/query, recent-biased. Links are Google redirect URLs; publisher domain taken from the feed `<source url>`; resolved where the URL format allows. Article text not fetched for unresolved Google links (snippet + title only). |
| GDELT DOC 2.0 | Global news index | No | **Core**, on | Max 1 request / 5 s (global limiter), rolling ~3-month window in `artlist` mode by default (`timespan` configurable). Frequently returns HTTP 429 from shared cloud IPs — reported as failed/partial, never silent. |
| Bing News RSS | News search | No | **Core**, on | `bing.com/news/search?format=rss`. May return an empty non-RSS page to datacenter IPs → reported as failed. Use governed by Microsoft terms. |
| GOV.UK Search API | UK government publications | No | **Core**, on | Press releases/notices from HMRC, Insolvency Service (director disqualifications), SFO, OFSI, CPS, NCA, Companies House etc. Tier 1. |
| US DOJ press releases API | Law enforcement | No | on | `justice.gov/api/v1/press_releases.json` title filter. Tier 1. |
| SEC litigation releases RSS | Regulator | No | on | Only the most recent releases in the feed — filtered for the subject name. Tier 1. Coverage disclosed as "recent only". |
| UK Companies House API | Official register | **Yes** (free) `COMPANIES_HOUSE_API_KEY` | disabled without key | Company search, officer search, disqualified officers. Identity corroboration & disqualification findings. |
| CourtListener | US court opinions | **Yes** (free) `COURTLISTENER_API_TOKEN` | disabled without key | v4 search API requires a token. |
| NewsAPI.org | News API | `NEWSAPI_KEY` | disabled without key | Free dev plan not licensed for production. |
| GNews.io | News API | `GNEWS_API_KEY` | disabled without key | |
| Brave Search API | Web search | `BRAVE_API_KEY` | disabled without key | |
| Serper (Google SERP) | Web search | `SERPER_API_KEY` | disabled without key | |
| Bing Web Search API | Web search | `BING_SEARCH_KEY` | disabled | Microsoft retired the Bing Search APIs in Aug 2025; code kept for completeness, reported as disabled. |
| FCA Register / Warning List | Regulator | — | **link-out only** | Not machine-searched (FCA Register API requires registration; site search not used). Shown as a link for manual check. |
| OpenSanctions | Sanctions/PEP reference | — | **link-out only, separate** | NOT adverse media; never mixed into findings. |
| OFAC recent actions | Sanctions | — | link-out only | Sanctions screening is a separate future module. |

"Core" providers drive the coverage gate (see §5.4).

## 4. Methodology
1. Normalise name; build variants (exact; diacritics folded; transliteration folds ü→ue/ß→ss; name order swap; first-initial form; legal suffix stripped/expanded for entities; user aliases, previous & trading names).
2. Query planner: for each provider, `"<name variant>"` AND risk-term group (financial crime / regulatory / predicate / integrity), plus one localised query per non-English locale using that language's risk terms, plus (where cheap) a plain exact-name query.
3. Merge, normalise URLs (strip tracking params, `www.`, fragments; decode Bing `apiclick` URLs), cluster syndicated copies (title 3-gram shingles, Jaccard ≥ 0.6, or identical normalised URL). Earliest / highest-tier item = original; rest = corroborating coverage.
4. Fetch accessible article text for up to N (default 25) highest-priority non-Google-redirect originals: robots.txt checked, SSRF guarded, 8 s, 1.5 MB, HTML only; extract the sentences that mention the subject and/or risk terms → ≤ 1,200-char excerpt stored. Full text is discarded after analysis.
5. Analyse each cluster (rules always; LLM optional + verifier).
6. Score, triage and derive overall status.

## 5. Scoring model (deterministic heuristic; documented; not a probability)

### 5.1 Identity evidence points (`analysis/identity.py`, weights in `policy.json → identity_weights`)
| Evidence | Points |
|---|---|
| Exact full name (or exact legal name incl. suffix) in text | +30 (+35 entity) |
| Fuzzy name match (Jaro-Winkler / token-set ≥ 0.90, diacritic folded, order-insensitive, initials) | +20 |
| Alias / previous / trading name exact | +25 |
| Surname-only / partial match | +5 |
| Year of birth stated & matches | +30 |
| Age stated & consistent with DOB at publication (±1) | +25 |
| Supplied country (nationality / residence / birth / jurisdiction / incorporation) mentioned | +10 each, cap +20 |
| Known associated person / director / UBO mentioned | +15 each, cap +30 |
| Company registration number found | +40 |
| Registered address postcode / street found | +20 |
| Legal suffix matches | +5 |
| **Contradiction**: different age / birth year | −40 (strong) |
| **Contradiction**: different company number | −40 (strong) |
| **Contradiction**: different middle name | −20 |
| **Contradiction**: different legal form (e.g. *Inc* vs *AG*) | −10 |
| **Contradiction**: text locates subject only in other countries | −10 |
| Very common name (built-in list + short surname heuristics) | −10 and stricter cap |

Levels: **Contradicted** (any strong contradiction, or net < 20 with a contradiction) · **Confirmed – strong** (net ≥ 80, ≥ 2 corroborating identifier types including one strong identifier — DOB/age, company number or address — and no contradictions) · **Probable** (net ≥ 50 and ≥ 1 corroborating identifier) · **Possible – needs review** (name match only; *name-only can never exceed this*) · **Unlikely** (partial name only, or very common name with no corroborating identifier).

### 5.2 Adverse relevance & triage (`scoring.py`)
A cluster is *relevant adverse media* when the subject name (or variant) appears in accessible text, at least one **enabled** taxonomy category matches in proximity to the subject mention, no "not-material" context dominates (civil-only dispute, minor traffic/parking infraction, sport, entertainment), and the subject is not merely a bystander (lawyer, prosecutor, judge, journalist/byline, victim, witness, commentator).

Buckets: **Requires review** (relevant, identity ≥ Possible, unresolved) · **Mitigating / resolved** (relevant + acquittal/dismissal/reversal/charges dropped/cleared) · **Low relevance / likely false positive** (everything else; collapsed in UI with reasons).

### 5.3 Material finding (RED trigger) — `policy.json → red_rules`
All must hold: relevant; category enabled with weight > 0 and severity ≥ `red_min_severity` (default *high*); identity ≥ `red_min_identity` (default *Probable*); implication *direct* and, for entities, party *direct*; not mitigated; event status in `red_statuses` (conviction, regulatory finding, enforcement action, formal charge, settlement, civil/regulatory proceeding, investigation, appeal) **or** allegation with ≥ `allegation_red_min_sources` (default 3) independent sources; source tier ≤ `red_max_tier` (default 2) **or** ≥ `red_min_corroboration` (default 2) independent sources.

### 5.4 Overall status
* **SCREENING FAILED** — zero core providers succeeded or the job crashed.
* **RED** — ≥ 1 material finding (incomplete-coverage banner still shown if applicable).
* **AMBER** — any *Requires review* finding; or unresolved common-name adverse hits; or coverage incomplete (core OK < `min_core_ok` (2), or a `required_core` provider (Google News) failed) → "Incomplete screening" banner.
* **GREEN** — coverage adequate and no relevant unresolved findings. Always carries the disclaimer that the result reflects the sources searched on the screening date.

Analyst override of the overall status requires the analyst/admin role and a written reason; the automated status is retained alongside.

## 6. Integration requirements / API keys
| Key | Purpose | Cost | Without it |
|---|---|---|---|
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | LLM-assisted structured analysis & narrative (OpenAI-compatible, e.g. xAI `https://api.x.ai/v1`, OpenAI) | Pay-per-token | Rule-based analysis only (always available). |
| `COMPANIES_HOUSE_API_KEY` | UK register search, officers, disqualified officers | Free (developer.company-information.service.gov.uk) | Provider shown as *disabled – no key*. |
| `COURTLISTENER_API_TOKEN` | US court opinions | Free account | Disabled. |
| `NEWSAPI_KEY`, `GNEWS_API_KEY`, `BRAVE_API_KEY`, `SERPER_API_KEY` | Extra news/web coverage | Freemium/paid | Disabled. |
| Licensed archives (Factiva, LexisNexis, Dow Jones) | Deep historical, paywalled coverage | Commercial | Not in scope; biggest coverage gap. |

## 7. Limitations / coverage disclosure (shown in UI and PDF)
* Searches only the providers listed as *ok/partial* on the result; no claim is made about any other source. Not exhaustive.
* Free news indexes are recency-biased (Google News, GDELT ≈ 3 months by default, SEC feed = latest releases only). Historical matters may be missed.
* Paywalled, login-protected or robots-disallowed content is never fetched; analysis then relies on the headline/snippet.
* Google News links are aggregator redirect URLs; the publisher domain is shown from the feed.
* Non-Latin-script names are only matched as supplied (no full transliteration engine in Phase 1).
* Rule-based NLP can mis-classify event status; every finding shows its verbatim evidence for the analyst to check.
* Adverse media screening is **not** sanctions or PEP screening.
* Automated output is decision support; a human analyst must review before any customer decision.
