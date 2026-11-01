"""Risk taxonomy matcher (multilingual phrase patterns over diacritic-folded text)."""
import re
from functools import lru_cache
import json

from .textutil import pattern_regex

SEV_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@lru_cache(maxsize=8)
def _compiled(tax_json: str):
    tax = json.loads(tax_json)
    cats = []
    for c in tax["categories"]:
        pats = [p for lang in c["patterns"].values() for p in lang]
        rx = re.compile("|".join(pattern_regex(p) for p in pats)) if pats else None
        cats.append((c, rx))
    nm = {k: re.compile("|".join(pattern_regex(p) for p in v)) for k, v in tax.get("not_material", {}).items()}
    return cats, nm


def compile_taxonomy(tax: dict):
    return _compiled(json.dumps(tax, sort_keys=True))


def match_categories(folded: str, tax: dict, enabled_only: bool = True) -> list[dict]:
    cats, _ = compile_taxonomy(tax)
    out = []
    for c, rx in cats:
        if rx is None or (enabled_only and (not c.get("enabled", True) or c.get("weight", 1) <= 0)):
            continue
        hits = [(m.start(), m.end(), m.group(0)) for m in rx.finditer(folded)]
        if hits:
            out.append({"id": c["id"], "label": c["label"], "group": c["group"], "severity": c["severity"],
                        "weight": c.get("weight", 1), "hits": hits})
    return out


def not_material(folded: str, tax: dict) -> list[str]:
    _, nm = compile_taxonomy(tax)
    return [k for k, rx in nm.items() if rx.search(folded)]
