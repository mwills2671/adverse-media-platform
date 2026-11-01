# DPIA Checklist (outline) — UK GDPR / Data Protection Act 2018

A Data Protection Impact Assessment **must be completed and signed off before production use** (screening of individuals for criminal allegations is likely high-risk processing: systematic evaluation, criminal-offence data, potentially large scale).

## 1. Description of processing
- [ ] Purpose: AML/CTF customer due diligence / EDD under the Money Laundering Regulations 2017 (MLR 2017), fraud prevention.
- [ ] Data subjects: prospective/existing customers, beneficial owners, directors, connected parties.
- [ ] Data: name, optional DOB, nationality, countries, aliases; public-source excerpts which may contain **criminal offence data** (allegations, charges, convictions) and possibly special-category data incidentally.
- [ ] Sources: listed public providers only (see coverage panel); no paywall/robots bypass.
- [ ] Recipients: internal compliance staff; exported PDFs placed on KYC file.

## 2. Lawful basis
- [ ] Article 6(1)(c) legal obligation (MLR 2017 CDD/EDD) and/or 6(1)(f) legitimate interests (LIA documented) or 6(1)(e) where applicable.
- [ ] **Article 10 / DPA 2018 s.10 & Schedule 1** condition for criminal offence data — e.g. Sch.1 Part 2 para 10 *preventing or detecting unlawful acts*, para 11 *protecting the public against dishonesty*, para 12 *regulatory requirements relating to unlawful acts and dishonesty*, para 14 *preventing fraud*, para 15 *suspicion of terrorist financing or money laundering*.
- [ ] **Appropriate Policy Document** (Sch.1 Part 4) in place.
- [ ] Special category data: Article 9 condition, or exclude/minimise.

## 3. Necessity and proportionality
- [ ] Data minimisation: only short excerpts (≤ ~1,200 chars), URL and metadata stored — never full articles.
- [ ] Retention period configured (Admin → Policy → retention days; default 1,825 days ≈ 5 years after relationship end per MLR reg. 40) and anonymise/delete function used.
- [ ] Accuracy: event status shown; allegations never presented as fact; contradicting/mitigating information surfaced; analyst can mark false positives.
- [ ] Transparency: privacy notice to customers mentions adverse media screening.
- [ ] Data subject rights: process for access (SAR), rectification, objection; note MLR/ s.15 & Sch.2 exemptions (e.g. crime and taxation) assessed case by case.

## 4. Automated decision-making (Article 22)
- [ ] The tool produces decision **support** only. No solely automated decision with legal/similarly significant effects. Every RED/AMBER requires analyst review; overrides recorded with reasons.

## 5. Security measures
- [ ] Authentication with salted scrypt password hashes, session cookies HttpOnly/Secure/SameSite, CSRF tokens, login rate limiting, RBAC.
- [ ] TLS in transit (Render-managed HTTPS); encryption at rest (Render Postgres); backups per Render plan.
- [ ] Tamper-evident hash-chained audit log; periodic chain verification.
- [ ] Secrets in environment variables only; least-privilege accounts; MFA/SSO in Phase 2.
- [ ] Optional application-level field encryption of subject identifiers (Phase 2).
- [ ] Processor due diligence: Render (hosting, EU region Frankfurt), LLM provider (if enabled — check data transfer, retention & training terms; consider disabling for personal data), news providers (queries containing names are sent to Google/Bing/GDELT/GOV.UK/DOJ/SEC — assess as disclosure to third parties; international transfer to US providers → IDTA/UK Addendum/ adequacy (UK-US data bridge) assessment).

## 6. Risks & mitigations to assess
| Risk | Mitigation |
|---|---|
| Misidentification (false positive) harms individual | Explainable identity scoring, name-only cap, common-name downgrade, human review mandatory |
| Outdated/superseded allegations | Event date vs publication date, mitigation detection, historical flag |
| Over-retention | Retention setting, anonymise function, audit |
| Unauthorised access | RBAC, sessions, rate limiting, audit |
| Third-party disclosure of subject names via search queries | Provider list disclosed; DPIA to accept or restrict providers |
| Incomplete coverage presented as clean | Coverage gate: failures → AMBER/FAILED, never silent GREEN |

## 7. Sign-off
- [ ] DPO consulted · [ ] Residual risk accepted by owner · [ ] ICO prior consultation if high residual risk (Art. 36) · [ ] Review date set.
