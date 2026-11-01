"""Consolidated summary: one overall narrative for the results page and PDF.

Rule-based by default (deterministic, built only from stored findings and coverage). When LLM_API_KEY is set an
LLM may rewrite the narrative, but ONLY from the facts we pass it, and the output is verified: every sentence must
cite a supplied fact number, and every year/number it states must occur in the supplied facts. Any failure falls
back to the rule-based text."""
import json
import re
from collections import Counter

import httpx

from .analysis.rules import STATUS_LABEL
from .config import settings

VERDICT_LABEL = {"GREEN": "No relevant adverse media", "AMBER": "Analyst review required",
                 "RED": "Material adverse media", "FAILED": "Screening failed — cannot be cleared"}


def _src(f: dict) -> str:
    return f.get("source_name") or f.get("domain") or "a source"


def _year(f: dict) -> str:
    return (f.get("published_at") or "")[:4] if (f.get("published_at") or "")[:4].isdigit() else "date unknown"


def one_line(status: str, findings: list[dict], cov: dict, lookback: int) -> str:
    material = [f for f in findings if f["material"]]
    review = [f for f in findings if f["bucket"] == "review"]
    common = [f for f in findings if f.get("common_name_unresolved")]
    win = f"the last {lookback} years" if lookback else "all dates"
    if status == "FAILED":
        return "No core media source returned results, so the subject cannot be cleared."
    if material:
        f = material[0]
        cat = (f["categories"][0]["label"] if f["categories"] else "adverse media").lower()
        st = STATUS_LABEL.get(f["event_status"], f["event_status"]).lower()
        more = f" (+{len(material) - 1} more)" if len(material) > 1 else ""
        return f"Material finding: {cat} — {st}, reported by {_src(f)} ({_year(f)}){more}."
    if review:
        themes = Counter(c["label"].lower() for f in review for c in f["categories"][:1])
        top = ", ".join(t for t, _ in themes.most_common(2)) or "possible adverse media"
        return f"{len(review)} item(s) in {win} need analyst review — mainly {top}."
    if common:
        return f"Possible adverse media for a common name; identity unresolved ({len(common)} item(s)) — add identifiers."
    if cov.get("incomplete"):
        return "Nothing relevant found, but source coverage was incomplete, so the result cannot be GREEN."
    return f"No relevant adverse media found in {win} across Google News and Bing News."


def build(meta: dict, findings: list[dict], cov: dict, status: str, lookback: int, window_start: str | None,
          related: list[dict] | None = None) -> dict:
    name, n_var = meta["subject_name"], meta.get("n_variants", 1)
    material = [f for f in findings if f["material"]]
    review = [f for f in findings if f["bucket"] == "review"]
    mit = [f for f in findings if f["bucket"] == "mitigating"]
    old = [f for f in findings if f["bucket"] == "outside_window"]
    undated = [f for f in findings if f["bucket"] in ("review", "mitigating") and not (f.get("published_at") or "")[:4].isdigit()]
    paras = []
    window_txt = f"from {window_start} to today ({lookback}-year look-back)" if window_start else "with no date limit"
    paras.append(f"We searched Google News and Bing News (plus keyless official-record sources) for “{name}”"
                 f"{f' and {n_var - 1} name variant(s)' if n_var > 1 else ''}, {window_txt}. {meta.get('n_raw', 0)} results were grouped into "
                 f"{meta.get('n_clusters', 0)} distinct stories and {meta.get('n_fetched', 0)} articles were read in full.")
    facts = []
    top = (material or review)[:3]
    if top:
        bits = []
        for f in top:
            cat = (f["categories"][0]["label"] if f["categories"] else "adverse media").lower()
            st = STATUS_LABEL.get(f["event_status"], f["event_status"]).lower()
            facts.append({"n": len(facts) + 1, "title": f["title"][:200], "source": _src(f), "year": _year(f),
                          "category": cat, "status": st, "material": f["material"]})
            bits.append(f"{cat} ({st}; {_src(f)}, {_year(f)}) [{len(facts)}]")
        lead = (f"{len(material)} finding(s) meet every RED rule" if material else f"{len(review)} finding(s) need analyst review")
        paras.append(f"{lead}. The most significant: " + "; ".join(bits) + ". "
                     "Allegations and investigations are not findings of guilt.")
    else:
        paras.append("No relevant, unresolved adverse media about the subject was identified in the window searched.")
    tail = []
    if mit:
        tail.append(f"{len(mit)} matter(s) were reported as resolved or mitigated (e.g. acquitted, dismissed, settled)")
    if old:
        tail.append(f"{len(old)} relevant item(s) predate the {lookback}-year window and were excluded from the rating")
    if undated:
        tail.append(f"{len(undated)} item(s) had no publication date and were kept in scope")
    if tail:
        paras.append("; ".join(tail).capitalize() + ".")
    if cov.get("incomplete") or cov.get("partial"):
        paras.append("Coverage warning: " + "; ".join(cov.get("notes") or ["some source queries failed"]) +
                     ". See the Sources tab — the result is not a clean clearance.")
    if related:
        types = Counter(r.get("role") for r in related)
        own = sum(types[k] for k in ("shareholder", "intermediary", "ubo", "owner", "parent"))
        mgmt = sum(types[k] for k in ("board_member", "executive", "director"))
        paras.append(f"Background search found {len(related)} possible related part(ies) — {own} owner/shareholder "
                     f"link(s) and {mgmt} board/management name(s). These are unverified leads from public sources and need "
                     "analyst confirmation; screen them from the Related parties tab.")
    themes = Counter(c["label"] for f in material + review for c in f["categories"][:2]).most_common(5)
    return {"verdict": status, "label": VERDICT_LABEL.get(status, status), "one_line": one_line(status, findings, cov, lookback),
            "paragraphs": paras, "themes": [{"label": t, "count": n} for t, n in themes], "facts": facts,
            "window": {"lookback_years": lookback, "start": window_start, "outside_window": len(old), "undated": len(undated)},
            "coverage_warning": bool(cov.get("incomplete") or cov.get("partial") or cov.get("failed")),
            "mode": "rule-based"}


SYSTEM = ("You write a neutral 3-5 sentence AML adverse-media summary. Use ONLY the facts provided. Every sentence must "
          "end with one or more citations like [1] referring to fact numbers, or [0] for the scope/coverage facts. Do not "
          "add names, numbers, dates or allegations that are not in the facts. Say 'alleged' for allegations. "
          'Return JSON {"text": "..."}')


def verify_llm(text: str, payload: dict) -> bool:
    src = json.dumps(payload, ensure_ascii=False)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if not sents or len(text) > 1500:
        return False
    valid = {0} | {f["n"] for f in payload["facts"]}
    for s in sents:
        cites = [int(x) for x in re.findall(r"\[(\d+)\]", s)]
        if not cites or any(c not in valid for c in cites):
            return False
    for num in re.findall(r"\d+(?:[.,]\d+)?", re.sub(r"\[\d+\]", "", text)):
        if not re.search(rf"(?<![\d.,]){re.escape(num)}(?![\d])", src):
            return False
    return True


async def llm_rewrite(client: httpx.AsyncClient, summary: dict, subject: str) -> dict:
    if not settings.llm_api_key:
        return summary
    payload = {"subject": subject, "verdict": summary["verdict"], "scope": summary["paragraphs"][0],
               "facts": summary["facts"], "other": summary["paragraphs"][2:]}
    body = {"model": settings.llm_model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)}]}
    try:
        r = await client.post(settings.llm_base_url.rstrip("/") + "/chat/completions", json=body, timeout=30,
                              headers={"Authorization": f"Bearer {settings.llm_api_key}"})
        r.raise_for_status()
        text = json.loads(re.sub(r"^```(?:json)?|```$", "", r.json()["choices"][0]["message"]["content"].strip()))["text"]
    except Exception:
        return summary
    if not isinstance(text, str) or not verify_llm(text, payload):
        return summary | {"llm_note": "LLM summary rejected by verifier — rule-based summary shown"}
    return summary | {"llm_text": text, "mode": "llm-verified"}
