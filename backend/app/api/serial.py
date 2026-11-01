from sqlalchemy import select
from sqlalchemy.orm import object_session

from ..models import Finding, RelatedParty, Screening

RAG_RANK = {"RED": 4, "AMBER": 3, "FAILED": 2, "GREEN": 1}
ROLE_LABEL = {"director": "Director", "board_member": "Board member", "executive": "Executive / management",
              "shareholder": "Shareholder", "intermediary": "Intermediate shareholder", "ubo": "UBO (reported)",
              "owner": "Owner", "parent": "Parent company", "founder": "Founder", "related_person": "Related person",
              "other": "Other"}


def _dt(d):
    return d.isoformat() if d else None


def finding_out(f: Finding) -> dict:
    return {"id": f.id, "rank": f.rank, "url": f.url, "title": f.title, "source_name": f.source_name, "domain": f.domain,
            "published_at": f.published_at, "provider": f.provider, "providers": f.providers, "language": f.language,
            "excerpt": f.excerpt, "text_source": f.text_source, "fetch_note": f.fetch_note, "quotes": f.quotes,
            "corroborating": f.corroborating, "independent_sources": f.independent_sources, "categories": f.categories,
            "primary_category": f.primary_category, "category_group": f.category_group, "severity": f.severity,
            "event_status": f.event_status, "statuses_detected": f.statuses_detected, "mitigation": f.mitigation,
            "event_date": f.event_date, "temporal": f.temporal, "implication": f.implication,
            "implication_note": f.implication_note, "party": f.party, "party_note": f.party_note,
            "identity_level": f.identity_level, "identity_points": f.identity_points, "identity_evidence": f.identity_evidence,
            "contradictions": f.contradictions, "credibility_tier": f.credibility_tier, "credibility_note": f.credibility_note,
            "relevant": f.relevant, "relevance_reasons": f.relevance_reasons, "material": f.material,
            "material_reasons": f.material_reasons, "bucket": f.bucket, "summary": f.summary, "analysis_mode": f.analysis_mode,
            "llm": f.llm, "decision": f.decision, "decision_reason": f.decision_reason, "decided_by": f.decided_by,
            "decided_at": _dt(f.decided_at), "escalated": f.escalated, "notes": f.notes}


def screening_summary(s: Screening) -> dict:
    return {"id": s.id, "subject_type": s.subject_type, "subject_name": s.subject_name, "job_status": s.job_status,
            "stage": s.stage, "stage_index": s.stage_index, "auto_status": s.auto_status, "final_status": s.final_status,
            "override_status": s.override_status, "incomplete": s.incomplete, "review_state": s.review_state,
            "disposition": s.disposition, "created_by": s.created_by, "created_at": _dt(s.created_at),
            "completed_at": _dt(s.completed_at), "duration_s": s.duration_s, "test_mode": s.test_mode,
            "anonymised": bool(s.anonymised_at), "parent_id": ((s.identifiers or {}).get("_parent") or {}).get("screening_id"),
            "counts": {k: (s.metrics or {}).get(k, 0) for k in ("review", "mitigating", "low", "material", "outside_window")}}


def screening_out(s: Screening, with_findings: bool = True) -> dict:
    d = screening_summary(s)
    m = dict(s.metrics or {})
    m.pop("raw_index", None)
    d |= {"identifiers": {k: v for k, v in (s.identifiers or {}).items() if not k.startswith("_")},
          "provider_runs": s.provider_runs, "coverage": s.coverage, "name_variants": s.name_variants, "queries": s.queries,
          "auto_reasons": s.auto_reasons, "override_reason": s.override_reason, "override_by": s.override_by,
          "override_at": _dt(s.override_at), "narrative": s.narrative, "narrative_mode": s.narrative_mode,
          "analysis_mode": s.analysis_mode, "metrics": m, "analyst_notes": s.analyst_notes, "reviewed_by": s.reviewed_by,
          "reviewed_at": _dt(s.reviewed_at), "result_hash": s.result_hash, "anonymised_at": _dt(s.anonymised_at),
          "error": "Internal error — see server logs" if s.error else None,
          "lookback_years": (s.identifiers or {}).get("_lookback_years", m.get("lookback_years")),
          "parent": (s.identifiers or {}).get("_parent")}
    rb = related_block(s)
    d["related_parties"], d["related_summary"] = rb["items"], rb["summary"]
    if with_findings:
        d["findings"] = [finding_out(f) for f in s.findings]
    return d


def related_out(r: RelatedParty, child: Screening | None) -> dict:
    return {"id": r.id, "name": r.name, "party_type": r.party_type, "role": r.role, "role_label": ROLE_LABEL.get(r.role, r.role),
            "role_detail": r.role_detail, "ownership_pct": r.ownership_pct, "via": r.via, "depth": r.depth,
            "confidence": r.confidence, "evidence": r.evidence or [], "partial_name": r.partial_name, "origin": r.origin,
            "state": r.state, "note": r.note, "added_by": r.added_by, "created_at": _dt(r.created_at),
            "verification": "Manually added by analyst" if r.origin == "manual" else
            "Unverified — extracted from public sources; requires analyst confirmation",
            "child_screening_id": r.child_screening_id,
            "child": None if not child else {"id": child.id, "job_status": child.job_status, "final_status": child.final_status,
                                             "auto_status": child.auto_status, "stage": child.stage}}


def related_block(s: Screening) -> dict:
    db = object_session(s)
    rows = list(s.related_parties)
    ids = [r.child_screening_id for r in rows if r.child_screening_id]
    kids = {c.id: c for c in db.execute(select(Screening).where(Screening.id.in_(ids))).scalars()} if ids and db else {}
    out = [related_out(r, kids.get(r.child_screening_id)) for r in rows]
    done = [o["child"] for o in out if o["child"] and o["child"]["job_status"] in ("completed", "failed") and o["state"] != "dismissed"]
    highest = max((c["final_status"] for c in done if c["final_status"]), key=lambda x: RAG_RANK.get(x, 0), default=None)
    hits = [{"name": o["name"], "role": o["role_label"], "status": o["child"]["final_status"], "screening_id": o["child"]["id"]}
            for o in out if o["child"] and o["child"]["final_status"] in ("RED", "AMBER", "FAILED") and o["state"] != "dismissed"]
    subj = s.final_status or s.auto_status
    note = None
    if hits:
        note = (f"Subject rated {subj}; related-party screening found {len(hits)} non-green result(s) (highest {highest}): " +
                ", ".join(f"{h['name']} ({h['role']}, {h['status']})" for h in hits[:6]) +
                ". Consider these in the decision.")
    elif done:
        note = f"Subject rated {subj}; {len(done)} related part(ies) screened — all GREEN."
    return {"items": out, "summary": {"total": len(out), "screened": len(ids), "completed": len(done), "highest": highest,
                                      "hits": hits, "overall_note": note,
                                      "pending": sum(1 for o in out if o["child"] and o["child"]["job_status"] not in ("completed", "failed"))}}
