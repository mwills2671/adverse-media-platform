"""Pluggable provider interface.

Every provider returns a ProviderRun describing exactly what happened (status, counts, errors, duration).
Statuses: ok | partial (some queries failed) | failed | disabled-no-key | disabled | link-out.
Items are only ever created from real provider responses; nothing is synthesised.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from ..config import KEY_ENV, settings


@dataclass
class RawItem:
    url: str
    title: str
    provider: str
    source_name: str | None = None
    source_domain: str | None = None
    published_at: str | None = None  # ISO date (YYYY-MM-DD or full ISO)
    snippet: str = ""
    language: str | None = None
    query: str | None = None
    official: bool = False  # item comes from an official register / authority API
    extra: dict = field(default_factory=dict)


@dataclass
class ProviderRun:
    id: str
    name: str
    kind: str
    status: str = "pending"
    queries: int = 0
    queries_failed: int = 0
    results: int = 0
    error: str | None = None
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    coverage_note: str = ""
    core: bool = False
    link: str | None = None

    def dict(self) -> dict:
        return asdict(self)


class ProviderError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class Provider:
    id: str = "base"
    name: str = "Base"
    kind: str = "news"
    coverage_note: str = ""
    requires_key: str | None = None  # settings.keys entry name
    core: bool = False
    timeout_s: float = 15.0
    retries: int = 1
    concurrency: int = 4

    def enabled(self) -> tuple[bool, str | None]:
        if self.requires_key and not settings.keys.get(self.requires_key):
            return False, "disabled-no-key"
        return True, None

    def plan(self, ctx: "SearchContext") -> list[Any]:
        """Return the list of query descriptors this provider will run."""
        raise NotImplementedError

    async def run_query(self, client: httpx.AsyncClient, q: Any, ctx: "SearchContext") -> list[RawItem]:
        raise NotImplementedError

    async def search(self, client: httpx.AsyncClient, ctx: "SearchContext") -> tuple[ProviderRun, list[RawItem]]:
        run = ProviderRun(id=self.id, name=self.name, kind=self.kind, coverage_note=self.coverage_note, core=self.core)
        ok, why = self.enabled()
        if not ok:
            run.status = why or "disabled"
            run.error = (f"Not searched: requires {KEY_ENV.get(self.requires_key, self.requires_key)}" if why == "disabled-no-key"
                         else "Not searched: provider disabled")
            return run, []
        t0 = time.monotonic()
        queries = self.plan(ctx)
        run.queries = len(queries)
        items: list[RawItem] = []
        sem = asyncio.Semaphore(self.concurrency)

        async def one(q):
            async with sem:
                last: Exception | None = None
                for attempt in range(self.retries + 1):
                    try:
                        fault = ctx.fault_injection.get(self.id) if ctx.fault_injection else None
                        if fault:  # TEST MODE ONLY (guarded in engine): simulate an outage
                            raise ProviderError(f"[test fault injection] {fault}")
                        return await asyncio.wait_for(self.run_query(client, q, ctx), timeout=self.timeout_s + 5)
                    except asyncio.TimeoutError:
                        last = ProviderError("timeout")
                    except ProviderError as e:
                        last = e
                        if e.status in (400, 401, 403, 404):
                            break
                    except Exception as e:  # network errors etc.
                        last = e
                    if attempt < self.retries:
                        await asyncio.sleep(1.5 * (attempt + 1))
                run.queries_failed += 1
                msg = f"{type(last).__name__}: {last}" if last else "unknown error"
                if len(run.errors) < 5:
                    run.errors.append(msg[:300])
                return []

        for res in await asyncio.gather(*(one(q) for q in queries)):
            items.extend(res)
        run.results = len(items)
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        if run.queries and run.queries_failed == run.queries:
            run.status = "failed"
        elif run.queries_failed:
            run.status = "partial"
        else:
            run.status = "ok"
        run.error = "; ".join(run.errors[:3]) or None
        return run, items


@dataclass
class SearchContext:
    subject_type: str
    name: str
    variants: list[dict]
    identifiers: dict
    taxonomy: dict
    policy: dict
    fault_injection: dict | None = None
    lookback_years: int = 5  # 0 = no date window

    @property
    def window_start(self) -> str | None:
        """ISO date of the start of the adverse-media date window (None = unlimited)."""
        if not self.lookback_years:
            return None
        from datetime import date
        t = date.today()
        try:
            return t.replace(year=t.year - self.lookback_years).isoformat()
        except ValueError:  # 29 Feb
            return t.replace(year=t.year - self.lookback_years, day=28).isoformat()

    @property
    def search_names(self) -> list[str]:
        return [v["value"] for v in self.variants if v.get("searchable")][:4]


async def get_text(client: httpx.AsyncClient, url: str, *, headers: dict | None = None, params: dict | None = None,
                   timeout: float = 15.0) -> str:
    h = {"User-Agent": settings.user_agent, "Accept": "*/*", "Accept-Language": "en-GB,en;q=0.8"}
    if headers:
        h.update(headers)
    r = await client.get(url, headers=h, params=params, timeout=timeout, follow_redirects=True)
    if r.status_code >= 400:
        raise ProviderError(f"HTTP {r.status_code}", r.status_code)
    return r.text


def quote(s: str) -> str:
    return '"' + s.replace('"', "").strip() + '"'
