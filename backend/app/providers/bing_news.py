"""Bing News RSS (no key)."""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote_plus, urlparse

from ..research.queries import english_groups, name_clause, or_clause
from .base import Provider, ProviderError, RawItem, get_text
from .google_news import parse_rss_date, strip_tags

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def unwrap_bing(link: str) -> str:
    p = urlparse(link)
    if "bing.com" in p.netloc and "apiclick" in p.path:
        u = parse_qs(p.query).get("url")
        if u:
            return u[0]
    return link


class BingNews(Provider):
    id = "bing_news"
    name = "Bing News RSS"
    kind = "news-search"
    core = True
    concurrency = 2
    coverage_note = ("Bing News RSS search (English risk-term groups; date window applied after retrieval). Bing may serve an empty non-RSS page to "
                     "cloud/datacenter IPs; that is reported as a failure, not as 'no results'.")

    def plan(self, ctx):
        # Bing News RSS returns an empty feed when names are OR-ed together, so query each name separately.
        out = []
        for i, n in enumerate(ctx.search_names[:2]):
            nc = name_clause([n])
            out.append({"q": nc, "group": "name-only"})
            groups = english_groups(ctx.taxonomy)
            for g, t in (groups.items() if i == 0 else list(groups.items())[:2]):
                out.append({"q": f"{nc} {or_clause(t[:8])}", "group": g})
        return out

    async def run_query(self, client, q, ctx):
        url = f"https://www.bing.com/news/search?q={quote_plus(q['q'])}&format=rss&setlang=en-GB"
        xml = await get_text(client, url, headers={"User-Agent": BROWSER_UA}, timeout=self.timeout_s)
        if "<rss" not in xml[:500]:
            raise ProviderError("Bing returned a non-RSS page (likely blocked from this network)")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise ProviderError(f"unparseable RSS ({e})")
        out = []
        ns_src = "{http://www.bing.com/schema/news}Source"
        for it in root.iter("item"):
            link = unwrap_bing((it.findtext("link") or "").strip())
            src = it.findtext(ns_src) or it.findtext("{https://www.bing.com/news/search?format=rss}Source")
            out.append(RawItem(url=link, title=(it.findtext("title") or "").strip(), provider=self.id,
                               source_name=src, source_domain=urlparse(link).netloc.lower().removeprefix("www."),
                               published_at=parse_rss_date(it.findtext("pubDate")),
                               snippet=strip_tags(it.findtext("description") or "")[:500], language="en", query=q["q"]))
        return out
