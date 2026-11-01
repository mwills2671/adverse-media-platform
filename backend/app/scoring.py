"""Relevance, triage, material-finding (RED) rules and overall status. Pure functions; fully traceable."""
from .analysis.identity import LEVEL_RANK
from .analysis.rules import MITIGATING
from .analysis.taxonomy import SEV_RANK

STATUS_RANK = {"RED": 3, "AMBER": 2, "GREEN": 1, "FAILED": 0}


def classify(f: dict, policy: dict, subject_type: str) -> dict:
    """Mutates and returns finding dict f with relevant/bucket/material and reasons."""
    R = policy["red_rules"]
    reasons: list[str] = []
    idl = f["identity"]["level"]
    cats = f["categories"]
    relevant = True
    if f["implication"] == "not_mentioned":
        relevant = False
        reasons.append("Subject name not found in accessible text (headline/snippet/article)")
    elif not cats:
        relevant = False
        reasons.append("No enabled risk category in proximity to the subject mention")
    elif f["implication"] == "bystander":
        relevant = False
        reasons.append(f"Subject appears in a non-implicated role ({f.get('role') or 'bystander'})")
    if relevant and f.get("not_material") and max(SEV_RANK[c["severity"]] for c in cats) < SEV_RANK["high"]:
        relevant = False
        reasons.append("Not material: " + ", ".join(x.replace("_", " ") for x in f["not_material"]))
    if relevant:
        reasons.append("Subject mentioned in proximity to: " + ", ".join(c["label"] for c in cats[:4]))
    f["relevant"] = relevant

    if not relevant:
        bucket = "low"
    elif f["event_status"] in MITIGATING:
        bucket = "mitigating"
        reasons.append(f"Mitigating outcome reported: {f['event_status']}")
    elif idl in ("unlikely", "contradicted"):
        bucket = "low"
        reasons.append(f"Identity {f['identity']['label']}: {f['identity']['reason']}")
    else:
        bucket = "review"
    f["bucket"] = bucket
    f["relevance_reasons"] = reasons
    f["common_name_unresolved"] = bool(relevant and f["identity"].get("common_name") and idl == "unlikely"
                                       and f["event_status"] not in MITIGATING)

    # ---- material (RED) rule trace ----
    trace = []

    def rule(ok, text):
        trace.append({"ok": bool(ok), "rule": text})
        return bool(ok)

    sev = max((SEV_RANK[c["severity"]] for c in cats), default=0)
    sources = f.get("independent_sources", 1)
    checks = [
        rule(bucket == "review", "Relevant, unresolved and not mitigated"),
        rule(sev >= SEV_RANK[R["red_min_severity"]], f"Category severity ≥ {R['red_min_severity']}"),
        rule(LEVEL_RANK.get(idl, 0) >= LEVEL_RANK[R["red_min_identity"]], f"Identity ≥ {R['red_min_identity']} (is {idl})"),
        rule(f["implication"] == "direct" or not R.get("require_direct_implication", True), "Subject directly implicated"),
        rule(subject_type != "entity" or f.get("party") == "direct", "Entity is the direct party (not a connected person/subsidiary)"),
        rule(f["event_status"] in R["red_statuses"] or (f["event_status"] == "allegation" and sources >= R["allegation_red_min_sources"]),
             f"Event status qualifies ({f['event_status']}; allegations need ≥{R['allegation_red_min_sources']} independent sources)"),
        rule(f["tier"] <= R["red_max_tier"] or sources >= R["red_min_corroboration"],
             f"Source tier ≤ {R['red_max_tier']} or ≥ {R['red_min_corroboration']} independent sources (tier {f['tier']}, {sources} sources)"),
    ]
    f["material"] = all(checks)
    f["material_reasons"] = trace
    return f


def coverage(runs: list[dict], policy: dict) -> dict:
    C = policy["coverage"]
    core = [r for r in runs if r["id"] in C["core_providers"]]
    succeeded = [r["id"] for r in core if r["status"] in ("ok", "partial")]
    failed = [r["id"] for r in core if r["status"] not in ("ok", "partial")]
    missing_required = [p for p in C["required_core"] if p not in succeeded]
    incomplete = len(succeeded) < C["min_core_ok"] or bool(missing_required)
    notes = []
    if failed:
        notes.append("Core provider(s) unavailable: " + ", ".join(failed))
    if missing_required:
        notes.append("Required provider failed: " + ", ".join(missing_required))
    if len(succeeded) < C["min_core_ok"]:
        notes.append(f"Only {len(succeeded)} of {len(core)} core providers succeeded (minimum {C['min_core_ok']})")
    partial = [r["id"] for r in runs if r["status"] == "partial"]
    if partial:
        notes.append("Partial results (some queries failed): " + ", ".join(partial))
    return {"core_total": len(core), "core_ok": len(succeeded), "core_succeeded": succeeded, "core_failed": failed,
            "incomplete": incomplete, "failed": len(succeeded) == 0, "notes": notes,
            "keyed_disabled": [r["id"] for r in runs if r["status"] == "disabled-no-key"]}


def overall(findings: list[dict], cov: dict) -> tuple[str, list[str]]:
    reasons = []
    if cov["failed"]:
        return "FAILED", ["Screening failed: no core research provider returned results — cannot be cleared"]
    material = [f for f in findings if f["material"]]
    review = [f for f in findings if f["bucket"] == "review"]
    common = [f for f in findings if f.get("common_name_unresolved")]
    if material:
        status = "RED"
        reasons.append(f"{len(material)} material adverse finding(s) meet all RED rules")
    elif review or common or cov["incomplete"]:
        status = "AMBER"
        if review:
            reasons.append(f"{len(review)} finding(s) require analyst review")
        if common:
            reasons.append(f"Identity unresolved due to common name ({len(common)} potentially adverse result(s)); "
                           "add identifiers (DOB, nationality, associates) to resolve")
    else:
        status = "GREEN"
        reasons.append("No relevant unresolved adverse media identified in the sources searched")
    if cov["incomplete"]:
        reasons.append("Incomplete screening: " + "; ".join(cov["notes"]))
    elif cov.get("notes"):
        reasons.append("Coverage note (minimum coverage still met): " + "; ".join(cov["notes"]))
    mit = [f for f in findings if f["bucket"] == "mitigating"]
    if mit:
        reasons.append(f"{len(mit)} mitigating/resolved matter(s) noted")
    return status, reasons
