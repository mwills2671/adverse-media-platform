from ..config import KEY_ENV
from .bing_news import BingNews
from .gdelt import Gdelt
from .google_news import GoogleNews
from .keyed import Brave, BingWeb, CompaniesHouse, CourtListener, GNews, NewsAPI, Serper
from .official import DOJ, GovUK, SECLitigation

ALL_PROVIDERS = [GoogleNews(), Gdelt(), BingNews(), GovUK(), DOJ(), SECLitigation(), CompaniesHouse(),
                 CourtListener(), NewsAPI(), GNews(), Brave(), Serper(), BingWeb()]


def provider_catalog() -> list[dict]:
    out = []
    for p in ALL_PROVIDERS:
        ok, why = p.enabled()
        out.append({"id": p.id, "name": p.name, "kind": p.kind, "core": p.core, "enabled": ok,
                    "status": "enabled" if ok else why, "requires_key": KEY_ENV.get(p.requires_key) if p.requires_key else None,
                    "coverage_note": p.coverage_note})
    return out
