"""Provider registry.

v2 policy: adverse-media search uses ONLY Google News and Bing News (keyless). Official-record lookups (GOV.UK,
US DOJ, US SEC litigation) also run because they are keyless primary sources; Companies House runs only when
its key is configured. GDELT and the keyed news/web providers (NewsAPI, GNews, Brave, Serper, Bing Web,
CourtListener) are kept in code but are OFF by default and hidden from the UI. They can be re-enabled by an
operator with AMS_EXTRA_PROVIDERS=gdelt,newsapi,... (a keyed provider still also needs its key).
Providers that are not active are never run and never produce "disabled / no key" rows."""
import os

from .bing_news import BingNews
from .gdelt import Gdelt
from .google_news import GoogleNews
from .keyed import Brave, BingWeb, CompaniesHouse, CourtListener, GNews, NewsAPI, Serper
from .official import DOJ, GovUK, SECLitigation

ALL_PROVIDERS = [GoogleNews(), BingNews(), GovUK(), DOJ(), SECLitigation(), CompaniesHouse(), Gdelt(),
                 CourtListener(), NewsAPI(), GNews(), Brave(), Serper(), BingWeb()]
MEDIA_PROVIDERS = ("google_news", "bing_news")
DEFAULT_ON = ("google_news", "bing_news", "govuk", "doj", "sec_litigation", "companies_house")


def _extra() -> set[str]:
    return {x.strip() for x in os.environ.get("AMS_EXTRA_PROVIDERS", "").split(",") if x.strip()}


def active_providers() -> list:
    """Providers that will actually run: default-on (or operator-enabled) AND configured (key present if needed)."""
    on = set(DEFAULT_ON) | _extra()
    return [p for p in ALL_PROVIDERS if p.id in on and p.enabled()[0]]


def provider_catalog() -> list[dict]:
    """Only active providers are exposed to the UI — no disabled/no-key clutter."""
    return [{"id": p.id, "name": p.name, "kind": p.kind, "core": p.id in MEDIA_PROVIDERS, "enabled": True, "status": "enabled",
             "media": p.id in MEDIA_PROVIDERS, "coverage_note": p.coverage_note} for p in active_providers()]
