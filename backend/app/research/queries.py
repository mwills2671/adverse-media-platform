"""Query planner: name variants x taxonomy risk-term groups x languages."""
from ..providers.base import quote

GROUP_ORDER = ["financial_crime", "regulatory", "predicate", "integrity"]


def english_groups(taxonomy: dict, max_terms: int = 12) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for g in GROUP_ORDER:
        terms: list[str] = []
        for c in taxonomy["categories"]:
            if c["group"] == g and c.get("enabled", True) and c.get("weight", 1) > 0:
                for t in c.get("query_terms", [])[:2]:
                    if t not in terms:
                        terms.append(t)
        if terms:
            out[g] = terms[:max_terms]
    return out


def language_terms(taxonomy: dict, lang: str, max_terms: int = 10) -> list[str]:
    terms: list[str] = []
    for c in taxonomy["categories"]:
        if not c.get("enabled", True) or c.get("weight", 1) <= 0:
            continue
        pats = c.get("patterns", {}).get(lang) or []
        if pats:
            t = pats[0].rstrip("*")
            if len(t) >= 3 and t not in terms:
                terms.append(t)
    return terms[:max_terms]


def or_clause(terms: list[str]) -> str:
    parts = [quote(t) if " " in t else t for t in terms]
    return "(" + " OR ".join(parts) + ")" if len(parts) > 1 else parts[0]


def name_clause(names: list[str]) -> str:
    q = [quote(n) for n in names]
    return q[0] if len(q) == 1 else "(" + " OR ".join(q) + ")"
