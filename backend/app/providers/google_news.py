"""Google News RSS search (no key). Multiple locales/languages."""
import base64
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

from ..research.queries import english_groups, language_terms, name_clause, or_clause
from .base import Provider, ProviderError, RawItem, get_text

LOCALES = [  # (hl, gl, ceid, lang)
    ("en-GB", "GB", "GB:en", "en"), ("en-US", "US", "US:en", "en"), ("fr", "FR", "FR:fr", "fr"),
    ("de", "DE", "DE:de", "de"), ("es-419", "MX", "MX:es-419", "es"), ("it", "IT", "IT:it", "it"),
    ("pt-BR", "BR", "BR:pt-419", "pt"), ("nl", "NL", "NL:nl", "nl"), ("ar", "AE", "AE:ar", "ar"),
]


def strip_tags(s: str) -> str:
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).replace("\xa0", " ").strip()


def decode_google_url(link: str) -> str | None:
    """Resolve legacy Google News article IDs that embed the publisher URL. Newer opaque IDs cannot be
    resolved offline (that would require calling Google's private endpoints), so None is returned."""
    m = re.search(r"/articles/([A-Za-z0-9_-]+)", link or "")
    if not m:
        return None
    s = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return None
    i = raw.find(b"http")
    if i < 0 or b"AU_yqL" in raw:
        return None
    j = i
    while j < len(raw) and 0x21 <= raw[j] <= 0x7E:
        j += 1
    url = raw[i:j].decode("ascii", "ignore")
    return url if urlparse(url).netloc and "google." not in urlparse(url).netloc else None


def parse_rss_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        return None


class GoogleNews(Provider):
    id = "google_news"
    name = "Google News RSS"
    kind = "news-aggregator"
    core = True
    concurrency = 5
    coverage_note = ("Google News RSS search across 9 locales (en-GB, en-US, fr, de, es, it, pt, nl, ar). Returns up to "
                     "~100 recent-biased headlines per query; links are Google redirect URLs (publisher shown from feed).")

    def plan(self, ctx):
        names = ctx.search_names[:3]
        nc = name_clause(names)
        qs = [{"q": nc, "loc": LOCALES[0], "group": "name-only"}]
        for hl in LOCALES[:2]:
            for g, terms in english_groups(ctx.taxonomy).items():
                qs.append({"q": f"{nc} {or_clause(terms)}", "loc": hl, "group": g})
        for loc in LOCALES[2:]:
            terms = language_terms(ctx.taxonomy, loc[3])
            if terms:
                qs.append({"q": f"{nc} {or_clause(terms)}", "loc": loc, "group": f"lang-{loc[3]}"})
        return qs

    async def run_query(self, client, q, ctx):
        hl, gl, ceid, lang = q["loc"]
        url = f"https://news.google.com/rss/search?q={quote_plus(q['q'])}&hl={hl}&gl={gl}&ceid={ceid}"
        xml = await get_text(client, url, timeout=self.timeout_s)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise ProviderError(f"unparseable RSS ({e})")
        out = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            src = it.find("source")
            source_name = (src.text or "").strip() if src is not None else None
            source_url = src.get("url") if src is not None else None
            if source_name and title.endswith(" - " + source_name):
                title = title[: -(len(source_name) + 3)]
            link = (it.findtext("link") or "").strip()
            resolved = decode_google_url(link)
            out.append(RawItem(
                url=resolved or link, title=title, provider=self.id, source_name=source_name,
                source_domain=(urlparse(source_url).netloc.lower().removeprefix("www.") if source_url else None),
                published_at=parse_rss_date(it.findtext("pubDate")),
                snippet=strip_tags(it.findtext("description") or "")[:500], language=lang, query=q["q"],
                extra={"google_link": link, "resolved": bool(resolved), "locale": hl}))
        return out
