"""Source credibility tiers (separate from identity confidence and event severity)."""
import json

from ..config import DATA_DIR

_d = json.loads((DATA_DIR / "domains.json").read_text(encoding="utf-8"))
T1, T2, T3, T4 = set(_d["tier1"]), set(_d["tier2"]), set(_d["tier3"]), set(_d["tier4_hints"])
TIER_LABEL = {1: "Tier 1 — authoritative (regulator / court / government)", 2: "Tier 2 — established news organisation",
              3: "Tier 3 — trade / regional press", 4: "Tier 4 — unverified / blog / aggregator / press-release wire"}


def _match(domain: str, s: set) -> bool:
    parts = domain.split(".")
    return any(".".join(parts[i:]) in s for i in range(len(parts) - 1))


def tier_for(domain: str | None, official: bool = False) -> tuple[int, str]:
    d = (domain or "").lower().removeprefix("www.")
    if official:
        return 1, "Official authority/register API"
    if not d:
        return 4, "Unknown source"
    if _match(d, T4):
        return 4, "Aggregator / wire / user-generated (listed)"
    if _match(d, T1):
        return 1, "Listed authority domain"
    if d.endswith((".gov", ".gov.uk", ".police.uk", ".mil", ".judiciary.uk")) or ".gov." in d or ".gouv." in d or d.endswith(".europa.eu"):
        return 1, "Government domain (heuristic)"
    if _match(d, T2):
        return 2, "Listed established news organisation"
    if _match(d, T3):
        return 3, "Listed trade / regional publication"
    if d.endswith((".ac.uk", ".edu")):
        return 3, "Academic domain (heuristic)"
    return 4, "Unlisted domain (unverified)"
