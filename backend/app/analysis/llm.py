"""Optional LLM analysis layer (OpenAI-compatible /chat/completions), with a strict verifier.

Disabled unless LLM_API_KEY is set. Only the short excerpt (<=1,200 chars) and headline are sent — never full
articles, never supplied identifiers beyond the name. The verifier rejects any output whose quotes are not
verbatim substrings of the excerpt, or whose categories/statuses are outside the controlled vocabularies.
Identity confidence is never decided by the LLM. On any failure the rule-based result stands."""
import json
import re

import httpx

from ..config import settings
from .rules import STATUS_ORDER

SYSTEM = (
    "You are an AML adverse-media analyst assistant. You will receive a headline and a short excerpt from a news or "
    "official source and a subject name. Use ONLY the provided text. Do not use outside knowledge. Return strict JSON: "
    '{"relevant": bool, "categories": [taxonomy ids], "event_status": one of STATUS, "implication": "direct"|"connected"|'
    '"bystander"|"victim"|"not_mentioned", "summary": "<=40 words, neutral, says allegation vs proven", '
    '"quotes": ["verbatim substrings of the excerpt supporting your answer, <=200 chars each, max 3"]}. '
    "If uncertain, set relevant=false or event_status=unknown. Never invent facts.")


def enabled() -> bool:
    return bool(settings.llm_api_key)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify(out: dict, excerpt: str, taxonomy_ids: set[str]) -> tuple[dict, list[str]]:
    problems = []
    clean = {}
    ex = _norm(excerpt)
    quotes = [q for q in (out.get("quotes") or []) if isinstance(q, str)]
    good_q = [q for q in quotes if _norm(q) and _norm(q) in ex]
    if len(good_q) < len(quotes):
        problems.append(f"{len(quotes) - len(good_q)} quote(s) not found verbatim in excerpt — rejected")
    clean["quotes"] = good_q[:3]
    cats = [c for c in (out.get("categories") or []) if c in taxonomy_ids]
    if len(cats) < len(out.get("categories") or []):
        problems.append("unknown taxonomy ids dropped")
    clean["categories"] = cats
    st = out.get("event_status")
    clean["event_status"] = st if st in STATUS_ORDER or st == "unknown" else "unknown"
    if st != clean["event_status"]:
        problems.append("invalid event_status")
    imp = out.get("implication")
    clean["implication"] = imp if imp in ("direct", "connected", "bystander", "victim", "not_mentioned") else None
    clean["relevant"] = bool(out.get("relevant"))
    clean["summary"] = str(out.get("summary") or "")[:400]
    # an answer that claims relevance must be grounded in at least one verified quote
    clean["grounded"] = bool(good_q)
    if clean["relevant"] and not good_q:
        problems.append("relevance claimed without a verified supporting quote — ignored")
    return clean, problems


async def analyse(client: httpx.AsyncClient, subject: str, title: str, excerpt: str, taxonomy_ids: set[str]) -> dict | None:
    if not enabled():
        return None
    body = {"model": settings.llm_model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM.replace("STATUS", "|".join(STATUS_ORDER + ["unknown"]))},
                         {"role": "user", "content": json.dumps({"subject": subject, "headline": title, "excerpt": excerpt,
                                                                 "taxonomy_ids": sorted(taxonomy_ids)})}]}
    try:
        r = await client.post(settings.llm_base_url.rstrip("/") + "/chat/completions", json=body, timeout=30,
                              headers={"Authorization": f"Bearer {settings.llm_api_key}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        out = json.loads(re.sub(r"^```(?:json)?|```$", "", content.strip()))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}", "model": settings.llm_model}
    clean, problems = verify(out, (title or "") + " " + excerpt, taxonomy_ids)
    return {"ok": True, "model": settings.llm_model, "result": clean, "verifier_problems": problems}


REL_SYSTEM = (
    "You extract people and companies that own, control or manage a subject company. You receive numbered snippets "
    "(i, text). Use ONLY the snippets, never outside knowledge. Return strict JSON {\"parties\": [{\"i\": snippet number, "
    "\"name\": exact name as written in that snippet, \"role\": one of ROLES, \"pct\": ownership percentage exactly as "
    "written or null, \"detail\": <=15 words}]}. Do not include companies the subject owns. If unsure, omit.")


async def extract_related(client: httpx.AsyncClient, subject: str, snippets: list[dict]) -> list[dict]:
    """Optional LLM pass over ownership/management sentences. The caller re-verifies every name (and %) verbatim
    against the cited snippet, so the model can only point at text that exists."""
    if not enabled():
        return []
    from ..research.related import ROLES
    body = {"model": settings.llm_model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": REL_SYSTEM.replace("ROLES", "|".join(ROLES))},
                         {"role": "user", "content": json.dumps({"subject": subject,
                                                                 "snippets": [{"i": i, "text": s["text"]} for i, s in enumerate(snippets)]})}]}
    try:
        r = await client.post(settings.llm_base_url.rstrip("/") + "/chat/completions", json=body, timeout=40,
                              headers={"Authorization": f"Bearer {settings.llm_api_key}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        out = json.loads(re.sub(r"^```(?:json)?|```$", "", content.strip()))
        parties = out.get("parties") if isinstance(out, dict) else None
        return [p for p in (parties or []) if isinstance(p, dict)][:60]
    except Exception:
        return []
