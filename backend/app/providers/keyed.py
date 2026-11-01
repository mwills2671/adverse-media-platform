"""Optional providers that need an API key. Disabled (status 'disabled-no-key') unless the env var is set."""
import json
from urllib.parse import urlparse

from ..config import settings
from ..research.queries import english_groups, name_clause, or_clause
from .base import Provider, ProviderError, RawItem, get_text, quote


def _dom(u: str) -> str:
    return urlparse(u).netloc.lower().removeprefix("www.")


def _risk_queries(ctx, max_groups=2):
    nc = name_clause(ctx.search_names[:2])
    return [{"q": f"{nc} {or_clause(t[:8])}"} for g, t in list(english_groups(ctx.taxonomy).items())[:max_groups]]


class CompaniesHouse(Provider):
    id = "companies_house"
    name = "UK Companies House API"
    kind = "official-register"
    requires_key = "companies_house"
    coverage_note = "UK Companies House disqualified-officers search (official register). Requires free API key."

    def plan(self, ctx):
        names = [ctx.name] if ctx.subject_type == "individual" else list(ctx.identifiers.get("associated_people") or [])[:4]
        return [{"q": n} for n in names if n]

    async def run_query(self, client, q, ctx):
        import base64
        auth = base64.b64encode((settings.keys["companies_house"] + ":").encode()).decode()
        text = await get_text(client, "https://api.company-information.service.gov.uk/search/disqualified-officers",
                              params={"q": q["q"], "items_per_page": "20"}, headers={"Authorization": f"Basic {auth}"},
                              timeout=self.timeout_s)
        data = json.loads(text)
        out = []
        for r in data.get("items", []) or []:
            link = r.get("links", {}).get("self", "")
            out.append(RawItem(
                url="https://find-and-update.company-information.service.gov.uk" + link, provider=self.id,
                title=f"Disqualified officer record: {r.get('title')}", source_name="Companies House",
                source_domain="company-information.service.gov.uk", published_at=None,
                snippet=f"{r.get('title')} — {r.get('description') or ''} {r.get('snippet') or ''} {r.get('address_snippet') or ''}".strip()[:500],
                language="en", query=q["q"], official=True,
                extra={"date_of_birth": r.get("date_of_birth"), "register": "disqualified_officers",
                       "official_text": f"{r.get('title')} disqualified director. {r.get('description') or ''}"}))
        return out


class CourtListener(Provider):
    id = "courtlistener"
    name = "CourtListener (US court opinions)"
    kind = "court"
    requires_key = "courtlistener"
    coverage_note = "US federal/state court opinions via CourtListener v4 search. Requires free API token."

    def plan(self, ctx):
        return [{"q": quote(n)} for n in ctx.search_names[:2]]

    async def run_query(self, client, q, ctx):
        text = await get_text(client, "https://www.courtlistener.com/api/rest/v4/search/",
                              params={"q": q["q"], "type": "o", "order_by": "score desc"},
                              headers={"Authorization": f"Token {settings.keys['courtlistener']}"}, timeout=self.timeout_s)
        data = json.loads(text)
        out = []
        for r in (data.get("results") or [])[:20]:
            snip = " ".join((o.get("snippet") or "") for o in (r.get("opinions") or [])[:2])
            out.append(RawItem(url="https://www.courtlistener.com" + (r.get("absolute_url") or ""), provider=self.id,
                               title=r.get("caseName") or "Court opinion", source_name=r.get("court") or "CourtListener",
                               source_domain="courtlistener.com", published_at=(r.get("dateFiled") or "")[:10] or None,
                               snippet=snip[:600], language="en", query=q["q"], official=True))
        return out


class NewsAPI(Provider):
    id = "newsapi"
    name = "NewsAPI.org"
    kind = "news-api"
    requires_key = "newsapi"
    coverage_note = "NewsAPI.org /v2/everything (last ~30 days on free tier)."

    def plan(self, ctx):
        return _risk_queries(ctx)

    async def run_query(self, client, q, ctx):
        data = json.loads(await get_text(client, "https://newsapi.org/v2/everything",
                                         params={"q": q["q"], "pageSize": "50", "sortBy": "relevancy"},
                                         headers={"X-Api-Key": settings.keys["newsapi"]}, timeout=self.timeout_s))
        if data.get("status") != "ok":
            raise ProviderError(data.get("message") or "NewsAPI error")
        return [RawItem(url=a["url"], title=a.get("title") or "", provider=self.id, source_name=(a.get("source") or {}).get("name"),
                        source_domain=_dom(a["url"]), published_at=(a.get("publishedAt") or "")[:10] or None,
                        snippet=(a.get("description") or "")[:500], query=q["q"]) for a in data.get("articles", []) if a.get("url")]


class GNews(Provider):
    id = "gnews"
    name = "GNews.io"
    kind = "news-api"
    requires_key = "gnews"
    coverage_note = "GNews.io search API."

    def plan(self, ctx):
        return _risk_queries(ctx)

    async def run_query(self, client, q, ctx):
        data = json.loads(await get_text(client, "https://gnews.io/api/v4/search",
                                         params={"q": q["q"], "max": "25", "token": settings.keys["gnews"]}, timeout=self.timeout_s))
        return [RawItem(url=a["url"], title=a.get("title") or "", provider=self.id, source_name=(a.get("source") or {}).get("name"),
                        source_domain=_dom(a["url"]), published_at=(a.get("publishedAt") or "")[:10] or None,
                        snippet=(a.get("description") or "")[:500], query=q["q"]) for a in data.get("articles", []) if a.get("url")]


class Brave(Provider):
    id = "brave"
    name = "Brave Search API (news)"
    kind = "web-search"
    requires_key = "brave"
    coverage_note = "Brave Search news endpoint."

    def plan(self, ctx):
        return _risk_queries(ctx)

    async def run_query(self, client, q, ctx):
        data = json.loads(await get_text(client, "https://api.search.brave.com/res/v1/news/search",
                                         params={"q": q["q"], "count": "20"},
                                         headers={"X-Subscription-Token": settings.keys["brave"], "Accept": "application/json"},
                                         timeout=self.timeout_s))
        return [RawItem(url=r["url"], title=r.get("title") or "", provider=self.id, source_name=(r.get("meta_url") or {}).get("hostname"),
                        source_domain=_dom(r["url"]), published_at=(r.get("page_age") or "")[:10] or None,
                        snippet=(r.get("description") or "")[:500], query=q["q"]) for r in data.get("results", []) if r.get("url")]


class Serper(Provider):
    id = "serper"
    name = "Serper (Google News SERP)"
    kind = "web-search"
    requires_key = "serper"
    coverage_note = "Serper.dev Google News results."

    def plan(self, ctx):
        return _risk_queries(ctx)

    async def run_query(self, client, q, ctx):
        r = await client.post("https://google.serper.dev/news", json={"q": q["q"], "num": 20},
                              headers={"X-API-KEY": settings.keys["serper"]}, timeout=self.timeout_s)
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}", r.status_code)
        return [RawItem(url=a["link"], title=a.get("title") or "", provider=self.id, source_name=a.get("source"),
                        source_domain=_dom(a["link"]), published_at=None, snippet=(a.get("snippet") or "")[:500],
                        query=q["q"], extra={"date_text": a.get("date")}) for a in r.json().get("news", []) if a.get("link")]


class BingWeb(Provider):
    id = "bing_web"
    name = "Bing Web Search API"
    kind = "web-search"
    requires_key = "bing_web"
    coverage_note = "Microsoft retired the Bing Search APIs in August 2025; kept for completeness, disabled."

    def enabled(self):
        return False, "disabled"

    def plan(self, ctx):
        return []
