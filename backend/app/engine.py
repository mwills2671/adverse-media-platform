"""Screening pipeline (8 stages). Runs as an in-process asyncio task; progress is persisted to the DB so the
browser can poll it. Every finding is derived from a real provider response — the engine never creates items.
Fault injection is honoured ONLY when the screening was created in test mode (never in production)."""
import asyncio
import hashlib
import json
import random
import string
import time
import traceback
from datetime import date, datetime, timezone

import httpx

from . import audit, narrative, scoring, summary as summary_mod
from .analysis import identity as ident
from .analysis import llm as llm_mod
from .analysis.rules import MITIGATING, analyse_text, build_excerpt, extract_dates, temporal
from .analysis.taxonomy import SEV_RANK, match_categories, not_material
from .config import settings
from .db import SessionLocal
from .models import Finding, RelatedParty, Screening, now
from .providers.base import RawItem, SearchContext
from .providers.linkouts import link_outs
from .providers.registry import active_providers
from .research import credibility, dedupe, fetcher, related as related_mod
from .research.names import expand_entity, expand_individual, fold
from .settings_store import get_policy, get_taxonomy

STAGES = ["Normalising input & expanding name variants", "Planning queries", "Searching sources",
          "De-duplicating & clustering", "Retrieving accessible article text", "Analysing relevance, identity & events",
          "Scoring & triage", "Writing narrative & finalising"]
_tasks: set[asyncio.Task] = set()
_slots: asyncio.Semaphore | None = None  # at most N screenings run at once (free-tier CPU/RAM)


def _sem() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(3)
    return _slots


def new_id() -> str:
    return f"AMS-{datetime.now(timezone.utc):%Y%m%d}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _stage(db, s: Screening, i: int):
    s.stage_index = i + 1
    s.stage = STAGES[i]
    db.commit()


def start(screening_id: str, fixtures: list[RawItem] | None = None) -> asyncio.Task:
    async def queued():
        async with _sem():
            await run(screening_id, fixtures)
    t = asyncio.create_task(queued())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


def variants_for(subject_type: str, name: str, identifiers: dict) -> list[dict]:
    aliases = [a for a in (identifiers.get("aliases") or []) if a]
    if subject_type == "entity":
        aliases += [a for a in (identifiers.get("trading_names") or []) + (identifiers.get("previous_names") or []) if a]
        return expand_entity(name, aliases)
    return expand_individual(name, aliases)


def tier_of(it: RawItem):
    # Labelled test fixtures use the reserved ".example" TLD (RFC 2606) and may declare a tier; real domains never can.
    if (it.source_domain or "").endswith(".example") and it.extra.get("fixture_tier"):
        return int(it.extra["fixture_tier"]), "TEST FIXTURE (declared tier)"
    return credibility.tier_for(it.source_domain, it.official)


def analyse_cluster(cluster: list[RawItem], subject_type: str, name: str, variants: list[dict], identifiers: dict,
                    taxonomy: dict, policy: dict, fetched: dict | None = None, today: date | None = None) -> dict:
    """Deterministic analysis of one story cluster. Pure function (used directly by the fixture tests)."""
    orig = cluster[0]
    tier, tier_note = tier_of(orig)
    fetched = fetched or {}
    text_source, body, fetch_note = "snippet", orig.snippet or "", None
    pub = orig.published_at
    fx = fetched.get(orig.url)
    if orig.extra.get("official_text"):
        text_source, body = "official-record", orig.extra["official_text"]
    elif fx and fx.get("ok"):
        text_source, body = "article", fx["text"]
        pub = pub or fx.get("published")
    elif fx:
        fetch_note = fx.get("note")
    elif orig.extra.get("google_link") and not orig.extra.get("resolved"):
        fetch_note = "Publisher URL not resolvable offline (Google News redirect) — headline/snippet only"
    tax_fn = lambda folded: match_categories(folded, taxonomy)
    a = analyse_text(body, orig.title, subject_type, name, variants, tax_fn)
    # categories only from sentences that mention the subject (proximity)
    cat_ids = []
    for s in a["risk_sentences"]:
        for c in s["categories"]:
            if c not in cat_ids:
                cat_ids.append(c)
    by_id = {c["id"]: c for c in taxonomy["categories"]}
    cats = []
    for cid in cat_ids:
        c = by_id[cid]
        term = next((s["cat_terms"][cid] for s in a["risk_sentences"] if cid in s["cat_terms"]), None)
        cats.append({"id": cid, "label": c["label"], "group": c["group"], "severity": c["severity"], "weight": c.get("weight", 1),
                     "term": term})
    cats.sort(key=lambda c: (-SEV_RANK[c["severity"]] * c["weight"], c["label"]))
    # statuses: from subject sentences first, else none
    found = []
    for s in a["risk_sentences"]:
        for st, term in s["statuses"]:
            if st not in [x[0] for x in found]:
                found.append((st, term))
    from .analysis.rules import primary_status
    status = primary_status(found)
    nm_ctx = []
    for s in a["risk_sentences"]:
        for k in not_material(fold(s["text"]), taxonomy):
            if k not in nm_ctx:
                nm_ctx.append(k)
    roles = [s["role"] for s in a["risk_sentences"] if s["role"]]
    dates = extract_dates(" ".join(s["text"] for s in a["risk_sentences"]) or a["doc"])
    tmp = temporal(pub, dates["years"], policy["historical_years"], today)
    idr = ident.score_identity(subject_type, name, identifiers, a, pub, policy, orig.extra)
    # corroboration
    seen_urls = {dedupe.normalise_url(orig.url)}
    corr = []
    domains = {(orig.source_domain or orig.source_name or "").lower()}
    for it in cluster[1:]:
        nu = dedupe.normalise_url(it.url)
        if nu in seen_urls:
            continue
        seen_urls.add(nu)
        corr.append({"url": it.url, "title": it.title, "source": it.source_name, "domain": it.source_domain,
                     "published_at": it.published_at, "provider": it.provider, "tier": tier_of(it)[0]})
        domains.add((it.source_domain or it.source_name or "").lower())
    excerpt = build_excerpt(a, policy["fetch"]["excerpt_chars"]) if text_source != "snippet" else (orig.snippet or "")[:policy["fetch"]["excerpt_chars"]]
    party_note = None
    if subject_type == "entity" and a["party"] == "connected":
        party_note = "Conduct appears attributed to a connected person/company (e.g. former executive, subsidiary, client)"
    imp_note = {"direct": "Subject mentioned in the same sentence as a risk term",
                "bystander": f"Subject appears as {', '.join(sorted(set(roles)))}" if roles else "Subject in non-implicated role",
                "mentioned_no_conduct": "Subject mentioned but no risk term in the same sentence",
                "not_mentioned": "Subject not found in accessible text"}.get(a["implication"])
    f = {"url": orig.url, "title": orig.title, "source_name": orig.source_name, "domain": orig.source_domain,
         "published_at": pub, "provider": orig.provider, "providers": sorted({i.provider for i in cluster}),
         "language": orig.language, "excerpt": excerpt, "text_source": text_source, "fetch_note": fetch_note,
         "quotes": [dict(q, source=text_source) for q in a["quotes"]], "corroborating": corr[:20],
         "independent_sources": len({d for d in domains if d}), "categories": cats, "event_status": status,
         "statuses_detected": [{"status": s, "term": t} for s, t in found],
         "mitigation": [s for s, _ in found if s in MITIGATING], "event_years": dates["years"],
         "event_date": (dates["dates"][0] if dates["dates"] else (str(tmp["reference_year"]) if tmp["reference_year"] else None)),
         "temporal": tmp, "implication": a["implication"], "implication_note": imp_note, "role": roles[0] if roles else None,
         "party": a["party"], "party_note": party_note, "identity": idr, "tier": tier, "tier_note": tier_note,
         "not_material": nm_ctx, "analysis_mode": "rule-based", "llm": None}
    if a["implication"] == "mentioned_no_conduct" and not cats:
        f["implication"] = "mentioned_no_conduct"
    return f


def summarise(f: dict, subject_type: str) -> str:
    if not f["relevant"]:
        return "; ".join(f["relevance_reasons"][:2])
    cat = f["categories"][0]["label"] if f["categories"] else "risk topic"
    from .analysis.rules import STATUS_LABEL
    st = STATUS_LABEL.get(f["event_status"], f["event_status"])
    when = f" ({f['event_date']})" if f.get("event_date") else ""
    caveat = " Allegation only — not a finding of guilt." if f["event_status"] in ("allegation", "investigation") else ""
    party = " Conduct attributed to a connected party." if f.get("party") == "connected" else ""
    return f"{st}: {cat.lower()}{when}, reported by {f.get('source_name') or f.get('domain') or 'source'}.{caveat}{party}"


def rank_key(f):
    b = {"review": 0, "mitigating": 1, "outside_window": 2, "low": 3}[f["bucket"]]
    sev = max((SEV_RANK[c["severity"]] for c in f["categories"]), default=0)
    return (0 if f["material"] else 1, b, -sev, -ident.LEVEL_RANK.get(f["identity"]["level"], 0), f["tier"],
            -(int((f.get("published_at") or "0000")[:4]) if (f.get("published_at") or "")[:4].isdigit() else 0))


def result_hash(s: Screening, findings: list[dict], runs: list[dict]) -> str:
    payload = {"id": s.id, "subject_type": s.subject_type, "status": s.auto_status, "reasons": s.auto_reasons,
               "providers": [{k: r[k] for k in ("id", "status", "results")} for r in runs],
               "findings": [{k: f[k] for k in ("url", "title", "bucket", "material", "event_status")} |
                            {"identity": f["identity"]["level"], "categories": [c["id"] for c in f["categories"]]} for f in findings]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def run(screening_id: str, fixtures: list[RawItem] | None = None):
    db = SessionLocal()
    t0 = time.monotonic()
    s = db.get(Screening, screening_id)
    try:
        s.job_status = "running"
        policy = get_policy(db)
        taxonomy = get_taxonomy(db)
        ids = s.identifiers or {}
        fault = (ids.get("_fault_injection") or None) if (s.test_mode and settings.test_mode) else None
        _stage(db, s, 0)
        variants = variants_for(s.subject_type, s.subject_name, ids)
        s.name_variants = variants
        lookback = ids.get("_lookback_years")
        lookback = int(policy.get("lookback_years", 5) if lookback in (None, "") else lookback)
        ctx = SearchContext(s.subject_type, s.subject_name, variants, {k: v for k, v in ids.items() if not k.startswith("_")},
                            taxonomy, policy, fault, lookback_years=lookback)
        window_start = ctx.window_start
        _stage(db, s, 1)
        providers = [] if fixtures is not None else active_providers()
        plans = []
        for p in providers:
            ok, _ = p.enabled()
            if ok:
                try:
                    plans += [{"provider": p.id, "query": (q.get("q") if isinstance(q, dict) else str(q)),
                               "locale": (q.get("loc") or [None])[0] if isinstance(q, dict) and q.get("loc") else None}
                              for q in p.plan(ctx)]
                except Exception:
                    pass
        s.queries = plans
        _stage(db, s, 2)
        raw: list[RawItem] = []
        runs: dict[str, dict] = {}
        limits = httpx.Limits(max_connections=30, max_keepalive_connections=10)
        disc_task = None
        rp_cfg = policy.get("related_parties") or {}
        async with httpx.AsyncClient(limits=limits, http2=False) as client:
            if fixtures is None and s.subject_type == "entity" and rp_cfg.get("enabled", True) and not ids.get("_skip_related"):
                # background search for directors/board/shareholders/UBOs runs concurrently with the media search
                disc_task = asyncio.create_task(related_mod.discover(
                    client, s.subject_name, [v["value"] for v in variants if v.get("kind") == "alias"],
                    ctx.identifiers, policy))
            if fixtures is not None:
                raw = list(fixtures)
                runs["test_fixtures"] = {"id": "test_fixtures", "name": "TEST FIXTURES (labelled, test mode only)", "kind": "fixture",
                                         "status": "ok", "queries": 1, "queries_failed": 0, "results": len(raw), "error": None,
                                         "errors": [], "duration_ms": 0, "coverage_note": "Controlled test fixtures", "core": True}
                s.provider_runs = list(runs.values())
                db.commit()
            else:
                for p in providers:
                    runs[p.id] = {"id": p.id, "name": p.name, "kind": p.kind, "status": "running", "core": p.core,
                                  "coverage_note": p.coverage_note, "results": 0}
                s.provider_runs = list(runs.values())
                db.commit()

                async def go(p):
                    try:
                        run_, items = await p.search(client, ctx)
                        d = run_.dict()
                    except Exception as e:  # provider bug must not crash the screening
                        d = {"id": p.id, "name": p.name, "kind": p.kind, "status": "failed", "core": p.core,
                             "error": f"internal error: {type(e).__name__}", "results": 0, "coverage_note": p.coverage_note}
                        items = []
                    runs[p.id] = d
                    s.provider_runs = [dict(v) for v in runs.values()]
                    db.commit()
                    return items

                for items in await asyncio.gather(*(go(p) for p in providers)):
                    raw.extend(items)
            run_list = list(runs.values())
            if fixtures is not None:
                cov = {"core_total": 1, "core_ok": 1, "core_succeeded": ["test_fixtures"], "core_failed": [], "incomplete": False,
                       "failed": False, "notes": ["TEST MODE: results come from labelled fixtures"], "keyed_disabled": []}
            else:
                cov = scoring.coverage(run_list, policy)
            s.coverage = cov | {"link_outs": link_outs(s.subject_name, s.subject_type)}
            _stage(db, s, 3)
            raw = [r for r in raw if r.url and r.url.startswith(("http://", "https://"))]
            clusters = dedupe.cluster(raw, tier_of)
            _stage(db, s, 4)
            # choose which clusters to fetch: name in headline/snippet + risk terms, fetchable URL
            fetched: dict[str, dict] = {}
            if fixtures is None:
                def prelim(c):
                    o = c[0]
                    txt = fold(o.title + " " + o.snippet)
                    nm = any(fold(v["value"]) in txt for v in variants)
                    cats = len(match_categories(txt, taxonomy))
                    return (nm * 3 + min(cats, 3) - tier_of(o)[0] * 0.25)
                cands = []
                for c in sorted(clusters, key=prelim, reverse=True):
                    o = c[0]
                    if o.official or o.extra.get("official_text"):
                        continue
                    fetchable = next((it for it in c if "news.google.com" not in it.url), None)
                    if fetchable:
                        if fetchable is not o:  # analyse from the fetchable member
                            c.remove(fetchable)
                            c.insert(0, fetchable)
                        cands.append(fetchable.url)
                    if len(cands) >= policy["fetch"]["max_articles"]:
                        break
                sem = asyncio.Semaphore(6)

                async def fx(u):
                    async with sem:
                        fetched[u] = await fetcher.fetch_article(client, u, timeout=policy["fetch"]["timeout_s"],
                                                                 max_bytes=policy["fetch"]["max_bytes"])
                try:
                    await asyncio.wait_for(asyncio.gather(*(fx(u) for u in cands)), timeout=60)
                except asyncio.TimeoutError:
                    pass
            discovery = None
            if disc_task is not None:
                try:
                    discovery = await asyncio.wait_for(disc_task, timeout=float(rp_cfg.get("timeout_s", 45)) + 15)
                except Exception as e:
                    discovery = {"candidates": [], "sources": [{"source": "discovery", "status": "error", "note": type(e).__name__}],
                                 "manual_links": related_mod.manual_links(s.subject_name, ctx.identifiers)}
            _stage(db, s, 5)
            findings = [analyse_cluster(c, s.subject_type, s.subject_name, variants, ctx.identifiers, taxonomy, policy, fetched)
                        for c in clusters]
            # optional LLM layer on the top candidates only (short excerpts)
            if llm_mod.enabled() and fixtures is None:
                tax_ids = {c["id"] for c in taxonomy["categories"] if c.get("enabled", True)}
                cand = [f for f in findings if f["implication"] != "not_mentioned"][:15]
                for f in cand:
                    res = await llm_mod.analyse(client, s.subject_name, f["title"], f["excerpt"] or "", tax_ids)
                    f["llm"] = res
                    if res and res.get("ok") and res["result"]["grounded"] and not res["verifier_problems"]:
                        r = res["result"]
                        if r["event_status"] != "unknown":
                            f["event_status"] = r["event_status"]
                        if r["implication"] in ("bystander", "victim"):
                            f["implication"] = "bystander"
                            f["role"] = r["implication"]
                        f["analysis_mode"] = "llm-verified"
                        f["llm_summary"] = r["summary"]
                s.analysis_mode = "llm-verified" if any(f["analysis_mode"] == "llm-verified" for f in findings) else "rule-based"
        _stage(db, s, 6)
        for f in findings:
            scoring.classify(f, policy | {"lookback_years": lookback}, s.subject_type, window_start)
            f["summary"] = f.get("llm_summary") or summarise(f, s.subject_type)
        findings.sort(key=rank_key)
        status, reasons = scoring.overall(findings, cov)
        s.auto_status = status
        s.auto_reasons = reasons
        s.incomplete = bool(cov.get("incomplete"))
        s.final_status = status
        _stage(db, s, 7)
        s.metrics = {"raw_results": len(raw), "clusters": len(clusters),
                     "fetched_ok": sum(1 for v in fetched.values() if v.get("ok")), "fetch_attempted": len(fetched),
                     "review": sum(f["bucket"] == "review" for f in findings),
                     "mitigating": sum(f["bucket"] == "mitigating" for f in findings),
                     "low": sum(f["bucket"] == "low" for f in findings), "material": sum(f["material"] for f in findings),
                     "outside_window": sum(f["bucket"] == "outside_window" for f in findings),
                     "lookback_years": lookback, "window_start": window_start,
                     "raw_index": [{"url": r.url, "provider": r.provider} for r in raw][:3000]}
        s.narrative = narrative.build({"subject_name": s.subject_name, "subject_type": s.subject_type, "id": s.id,
                                       "date": date.today().isoformat(), "n_raw": len(raw), "n_clusters": len(clusters)},
                                      findings, cov, status, reasons)
        cands = (discovery or {}).get("candidates") or []
        summ = summary_mod.build({"subject_name": s.subject_name, "n_variants": len(variants), "n_raw": len(raw),
                                  "n_clusters": len(clusters), "n_fetched": s.metrics["fetched_ok"]},
                                 findings, cov, status, lookback, window_start, cands)
        if fixtures is None and llm_mod.enabled():
            async with httpx.AsyncClient() as c2:
                summ = await summary_mod.llm_rewrite(c2, summ, s.subject_name)
        s.metrics = s.metrics | {"summary": summ}
        if discovery is not None:
            s.metrics = s.metrics | {"related_discovery": {"sources": discovery.get("sources", []),
                                                           "manual_links": discovery.get("manual_links", []),
                                                           "elapsed_s": discovery.get("elapsed_s"), "found": len(cands)}}
            for c in cands:
                db.add(RelatedParty(screening_id=s.id, name=c["name"][:300], party_type=c["party_type"], role=c["role"],
                                    role_detail=(c.get("role_detail") or "")[:300] or None,
                                    ownership_pct=(str(c["ownership_pct"]) if c.get("ownership_pct") not in (None, "") else None),
                                    via=c.get("via"), depth=c.get("depth", 1), confidence=c["confidence"],
                                    evidence=c["evidence"], partial_name=bool(c.get("partial_name")), origin="auto",
                                    state="candidate", note=("Also: " + ", ".join(r for r in c.get("roles", []) if r != c["role"]))
                                    if len(c.get("roles", [])) > 1 else None, added_by="system"))
        keep = [f for f in findings if f["implication"] != "not_mentioned" or f["bucket"] != "low"][:400]
        for i, f in enumerate(keep):
            db.add(Finding(screening_id=s.id, rank=i, url=f["url"], title=f["title"][:2000], source_name=(f["source_name"] or "")[:300],
                           domain=f["domain"], published_at=f["published_at"], provider=f["provider"], providers=f["providers"],
                           language=f["language"], excerpt=f["excerpt"], text_source=f["text_source"], fetch_note=f["fetch_note"],
                           quotes=f["quotes"], corroborating=f["corroborating"], independent_sources=f["independent_sources"],
                           categories=f["categories"], primary_category=f["categories"][0]["id"] if f["categories"] else None,
                           category_group=f["categories"][0]["group"] if f["categories"] else None,
                           severity=f["categories"][0]["severity"] if f["categories"] else None,
                           event_status=f["event_status"], statuses_detected=f["statuses_detected"], mitigation=f["mitigation"],
                           event_date=f["event_date"], temporal=f["temporal"]["label"], implication=f["implication"],
                           implication_note=f["implication_note"], party=f["party"], party_note=f["party_note"],
                           identity_level=f["identity"]["level"], identity_points=f["identity"]["points"],
                           identity_evidence=f["identity"]["evidence"] + [{"type": "_summary", "detail": f["identity"]["reason"],
                                                                         "points": 0, "matched": None}],
                           contradictions=f["identity"]["contradictions"], credibility_tier=f["tier"], credibility_note=f["tier_note"],
                           relevant=f["relevant"], relevance_reasons=f["relevance_reasons"], material=f["material"],
                           material_reasons=f["material_reasons"], bucket=f["bucket"], summary=f["summary"],
                           analysis_mode=f["analysis_mode"], llm=f["llm"]))
        s.metrics = s.metrics | {"stored_findings": len(keep), "not_mentioned_dropped": len(findings) - len(keep)}
        s.result_hash = result_hash(s, findings, list(runs.values()))
        s.job_status = "completed"
        if discovery is not None:
            audit.append(db, s.created_by, "related_parties.discovered", s.id,
                         {"found": len(cands), "sources": [f"{x.get('source')}: {x.get('status')}" for x in discovery.get("sources", [])][:30],
                          "note": "unverified candidates from public sources; require analyst confirmation"})
        s.completed_at = now()
        s.duration_s = round(time.monotonic() - t0, 1)
        db.commit()
        audit.append(db, s.created_by, "screening.completed", s.id,
                     {"auto_status": status, "incomplete": s.incomplete, "result_hash": s.result_hash,
                      "providers": {r["id"]: r["status"] for r in runs.values()}, "findings": len(keep),
                      "material": s.metrics["material"], "test_mode": s.test_mode})
    except Exception as e:
        db.rollback()
        s = db.get(Screening, screening_id)
        s.job_status = "failed"
        s.auto_status = "FAILED"
        s.final_status = "FAILED"
        s.auto_reasons = [f"Screening failed: internal error ({type(e).__name__}) — the subject cannot be cleared"]
        s.error = traceback.format_exc()[-2000:]
        s.completed_at = now()
        s.duration_s = round(time.monotonic() - t0, 1)
        db.commit()
        audit.append(db, s.created_by, "screening.failed", s.id, {"error": type(e).__name__})
    finally:
        db.close()
