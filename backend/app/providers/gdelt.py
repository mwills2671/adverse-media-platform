"""GDELT DOC 2.0 API (no key). Strict global limiter: 1 request per 5 seconds; 429-tolerant."""
import asyncio
import json
import time
from urllib.parse import urlparse

from ..research.queries import english_groups
from .base import Provider, ProviderError, RawItem, get_text, quote

_lock = asyncio.Lock()
_last = 0.0
MIN_INTERVAL = 5.5


class Gdelt(Provider):
    id = "gdelt"
    name = "GDELT DOC 2.0"
    kind = "news-index"
    core = False
    concurrency = 1
    retries = 0
    timeout_s = 22
    coverage_note = ("GDELT global news index (100+ languages, machine-translated index). Rolling window "
                     "(default ~3 months) of articles; rate-limited to 1 request / 5 s; often throttled (HTTP 429).")

    def plan(self, ctx):
        names = [n for n in ctx.search_names[:2] if len(n) >= 4]
        nc = quote(names[0]) if len(names) == 1 else "(" + " OR ".join(quote(n) for n in names) + ")"
        groups = english_groups(ctx.taxonomy, max_terms=8)
        # One combined query: GDELT allows ~1 request / 5 s per client, so a single well-formed query keeps
        # latency bounded (worst case ≈ timeout + one 429 back-off) without losing the core vocabulary.
        terms = (groups.get("financial_crime", [])[:6] + groups.get("regulatory", [])[:3] +
                 groups.get("predicate", [])[:3] + groups.get("integrity", [])[:2])
        terms = [t for t in dict.fromkeys(terms) if len(t) >= 4][:10]
        return [{"q": f"{nc} (" + " OR ".join(quote(t) if " " in t else t for t in terms) + ")"}]

    async def run_query(self, client, q, ctx):
        global _last
        params = {"query": q["q"], "mode": "artlist", "format": "json", "maxrecords": "75", "sort": "datedesc"}
        ts = ctx.policy.get("gdelt_timespan")
        if ts:
            params["timespan"] = ts
        for attempt in range(2):
            async with _lock:
                wait = _last + MIN_INTERVAL - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    text = await get_text(client, "https://api.gdeltproject.org/api/v2/doc/doc", params=params,
                                          timeout=self.timeout_s)
                    break
                except ProviderError as e:
                    if e.status == 429 and attempt == 0:
                        await asyncio.sleep(5)
                        continue
                    raise ProviderError("HTTP 429 rate limited by GDELT" if e.status == 429 else str(e), None)
                finally:
                    _last = time.monotonic()
        text = text.strip()
        if not text:
            return []
        if not text.startswith("{"):
            raise ProviderError(f"GDELT error: {text[:160]}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(f"bad JSON ({e})")
        out = []
        for a in data.get("articles", []) or []:
            sd = a.get("seendate") or ""
            date = f"{sd[0:4]}-{sd[4:6]}-{sd[6:8]}" if len(sd) >= 8 else None
            out.append(RawItem(url=a.get("url", ""), title=(a.get("title") or "").strip(), provider=self.id,
                               source_name=a.get("domain"), source_domain=(a.get("domain") or urlparse(a.get("url", "")).netloc).lower().removeprefix("www."),
                               published_at=date, language=(a.get("language") or "")[:8] or None, query=q["q"],
                               extra={"sourcecountry": a.get("sourcecountry")}))
        return out
