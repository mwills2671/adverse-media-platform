"""Deterministic analyst narrative (template-based; every sentence traceable to stored data)."""
from .analysis.rules import STATUS_LABEL


def build(s: dict, findings: list[dict], cov: dict, status: str, reasons: list[str]) -> str:
    who = s["subject_name"]
    t = "entity" if s["subject_type"] == "entity" else "individual"
    srch = ", ".join(cov["core_succeeded"]) or "none"
    lines = [f"Adverse media screening of the {t} '{who}' on {s['date']} (screening {s['id']})."]
    def sent(x: str) -> str:
        x = x.strip()
        return x if x.endswith((".", "!", "?")) else x + "."
    lines.append(f"Automated outcome: {status}. " + " ".join(sent(r) for r in reasons[:3]))
    lines.append(f"Core sources searched successfully: {srch} ({cov['core_ok']}/{cov['core_total']}). "
                 f"{s['n_raw']} raw results were retrieved, clustered into {s['n_clusters']} distinct stories.")
    mat = [f for f in findings if f["material"]]
    rev = [f for f in findings if f["bucket"] == "review"]
    mit = [f for f in findings if f["bucket"] == "mitigating"]
    if mat:
        top = mat[0]
        lines.append(f"The most significant finding concerns {top['categories'][0]['label'].lower()} "
                     f"({STATUS_LABEL.get(top['event_status'], top['event_status']).lower()}) reported by "
                     f"{top.get('source_name') or top.get('domain')} (credibility tier {top['tier']}) "
                     f"with identity confidence '{top['identity']['label']}'.")
    if rev:
        from collections import Counter
        lv = Counter(f["identity"].get("level", f["identity"]["label"]) for f in rev)
        order = ["confirmed", "probable", "possible", "unlikely", "contradicted"]
        parts = [f"{lv[k]} {k}" for k in order if lv.get(k)] + [f"{n} {k}" for k, n in lv.items() if k not in order]
        lines.append(f"{len(rev)} finding(s) require analyst review (identity match: {', '.join(parts)}).")
    if mit:
        lines.append(f"{len(mit)} report(s) describe mitigating outcomes (e.g. acquittal, dismissal, reversal).")
    allegations = [f for f in rev if f["event_status"] in ("allegation", "investigation", "unknown")]
    if allegations:
        lines.append("Some matters are allegations or investigations only and are not findings of guilt.")
    lines.append("This automated assessment supports, and does not replace, analyst judgement. It reflects only the "
                 "sources searched on the screening date; sources not searched are listed in the report.")
    return " ".join(lines)
