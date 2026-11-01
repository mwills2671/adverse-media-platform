"""Official / public-authority providers with open APIs (no key):
GOV.UK Search API, US DOJ press releases API, SEC litigation releases RSS."""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..research.names import fold
from .base import Provider, ProviderError, RawItem, get_text, quote
from .google_news import parse_rss_date, strip_tags


def _mentions(text: str, names: list[str]) -> bool:
    t = " " + fold(text) + " "
    return any(" " + fold(n) + " " in t for n in names if fold(n))


class GovUK(Provider):
    id = "govuk"
    name = "GOV.UK Search API"
    kind = "government"
    core = False
    coverage_note = ("GOV.UK site search API: UK government press releases, notices and decisions (HMRC, Insolvency "
                     "Service director disqualifications, SFO, OFSI, CPS, NCA, Companies House). Title/description level.")

    def plan(self, ctx):
        return [{"q": quote(n)} for n in ctx.search_names[:2]]

    async def run_query(self, client, q, ctx):
        params = {"q": q["q"], "count": "25", "order": "-public_timestamp",
                  "fields": "title,description,link,public_timestamp,organisations,format"}
        try:
            data = json.loads(await get_text(client, "https://www.gov.uk/api/search.json", params=params, timeout=self.timeout_s))
        except json.JSONDecodeError as e:
            raise ProviderError(f"bad JSON ({e})")
        out = []
        names = ctx.search_names
        for r in data.get("results", []):
            title, desc = r.get("title") or "", r.get("description") or ""
            if not _mentions(title + " " + desc, names):
                continue  # GOV.UK search is fuzzy; keep only exact name mentions
            orgs = ", ".join(o.get("title", "") for o in (r.get("organisations") or []) if isinstance(o, dict))
            link = r.get("link") or ""
            url = link if link.startswith("http") else "https://www.gov.uk" + link
            out.append(RawItem(url=url, title=title, provider=self.id, source_name=orgs or "GOV.UK",
                               source_domain="gov.uk", published_at=(r.get("public_timestamp") or "")[:10] or None,
                               snippet=desc[:600], language="en", query=q["q"], official=True,
                               extra={"format": r.get("format")}))
        return out


class DOJ(Provider):
    id = "doj"
    name = "US DOJ press releases API"
    kind = "law-enforcement"
    coverage_note = "US Department of Justice press releases (justice.gov API), matched on title only."

    def plan(self, ctx):
        names = [v["value"] for v in ctx.variants if v["kind"] in ("exact", "legal-suffix-stripped", "alias", "middle-name-dropped")]
        return [{"q": n} for n in names[:2]]

    async def run_query(self, client, q, ctx):
        params = {"parameters[title]": q["q"], "pagesize": "25", "sort": "date", "direction": "DESC"}
        try:
            data = json.loads(await get_text(client, "https://www.justice.gov/api/v1/press_releases.json", params=params,
                                             timeout=self.timeout_s))
        except json.JSONDecodeError as e:
            raise ProviderError(f"bad JSON ({e})")
        out = []
        for r in data.get("results", []) or []:
            title = r.get("title") or ""
            if not _mentions(title, [q["q"]]):
                continue
            date = None
            try:
                date = datetime.fromtimestamp(int(r.get("date")), tz=timezone.utc).date().isoformat()
            except Exception:
                pass
            body = strip_tags(r.get("body") or "")
            out.append(RawItem(url=r.get("url") or "", title=title, provider=self.id, source_name="U.S. Department of Justice",
                               source_domain="justice.gov", published_at=date, snippet=(r.get("teaser") or "")[:400],
                               language="en", query=q["q"], official=True, extra={"official_text": body[:20000]}))
        return out


class SECLitigation(Provider):
    id = "sec_litigation"
    name = "SEC litigation releases RSS"
    kind = "regulator"
    coverage_note = "US SEC litigation releases RSS — most recent releases only (not a historical search)."

    def plan(self, ctx):
        return [{"q": "feed"}]

    async def run_query(self, client, q, ctx):
        xml = await get_text(client, "https://www.sec.gov/enforcement-litigation/litigation-releases/rss", timeout=self.timeout_s)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise ProviderError(f"unparseable RSS ({e})")
        out = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            desc = strip_tags(it.findtext("description") or "")
            if not _mentions(title + " " + desc, ctx.search_names):
                continue
            link = (it.findtext("link") or "").strip()
            if link.startswith("/"):
                link = "https://www.sec.gov" + link
            out.append(RawItem(url=link, title=title, provider=self.id, source_name="U.S. SEC", source_domain="sec.gov",
                               published_at=parse_rss_date(it.findtext("pubDate")), snippet=desc[:600], language="en",
                               query="recent litigation releases", official=True))
        return out
