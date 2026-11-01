"""SSRF-safe, robots.txt-respecting article fetcher.

Controls: http/https only; every hop's host is DNS-resolved and rejected if any address is private,
loopback, link-local, multicast, reserved or otherwise non-global; at most 3 redirects; HTML/XHTML only;
response size capped; short timeout; identifying User-Agent; robots.txt honoured (cached per host).
Paywalled / login pages are not circumvented — whatever is publicly served is used, nothing more.
Only the extracted plain text is returned to the caller (kept in memory for analysis, never stored in full).
"""
import asyncio
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..config import settings

ROBOTS_UA = "AdverseMediaScreening"
_robots_cache: dict[str, tuple[float, RobotFileParser | None, bool]] = {}
BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", "localhost", ".onion")


class FetchBlocked(Exception):
    pass


def _ok_ip(a: str) -> bool:
    ip = ipaddress.ip_address(a.split("%")[0])
    if ip.is_global:
        return True
    return any(ip in ipaddress.ip_network(c, strict=False) for c in settings.ssrf_extra_allowed_cidrs)


async def _host_is_public(host: str) -> bool:
    if not host or host.endswith(BLOCKED_HOST_SUFFIXES):
        return False
    try:
        ipaddress.ip_address(host)
        return ipaddress.ip_address(host).is_global  # literal IPs must be genuinely public
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().run_in_executor(None, socket.getaddrinfo, host, None)
    except socket.gaierror:
        return False
    addrs = {i[4][0] for i in infos}
    return bool(addrs) and all(_ok_ip(a) for a in addrs)


async def check_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise FetchBlocked("scheme not allowed")
    if p.port and p.port not in (80, 443):
        raise FetchBlocked("non-standard port not allowed")
    if p.username or p.password:
        raise FetchBlocked("credentials in URL not allowed")
    if not await _host_is_public(p.hostname or ""):
        raise FetchBlocked("host resolves to a non-public address")


async def robots_allowed(client: httpx.AsyncClient, url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    hit = _robots_cache.get(base)
    if hit and time.time() - hit[0] < 3600:
        rp, allow_all = hit[1], hit[2]
    else:
        rp, allow_all = None, False
        try:
            await check_url(base + "/robots.txt")
            r = await client.get(base + "/robots.txt", headers={"User-Agent": settings.user_agent}, timeout=5,
                                 follow_redirects=False)
            if r.status_code in (401, 403) or r.status_code >= 500:
                allow_all = False
                rp = RobotFileParser()
                rp.parse(["User-agent: *", "Disallow: /"])
            elif r.status_code >= 400 or r.status_code in (301, 302, 303, 307, 308):
                allow_all = True
            else:
                rp = RobotFileParser()
                rp.parse(r.text[:200_000].splitlines())
        except Exception:
            rp = RobotFileParser()
            rp.parse(["User-agent: *", "Disallow: /"])  # cannot verify -> do not fetch
        _robots_cache[base] = (time.time(), rp, allow_all)
    if allow_all:
        return True
    return bool(rp and rp.can_fetch(ROBOTS_UA, url))


def extract_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "lxml")
    pub = None
    for attr in ("article:published_time", "og:published_time", "datePublished", "date", "pubdate", "DC.date.issued"):
        m = soup.find("meta", attrs={"property": attr}) or soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"itemprop": attr})
        if m and m.get("content"):
            mm = re.match(r"(\d{4}-\d{2}-\d{2})", m["content"])
            if mm:
                pub = mm.group(1)
                break
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]):
        t.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "h1", "h2", "li"])]
    paras = [p for p in paras if len(p) > 40]
    text = "\n".join(paras) if paras else soup.get_text(" ", strip=True)
    return re.sub(r"[ \t]+", " ", text)[:60_000], pub


async def fetch_html(client: httpx.AsyncClient, url: str, *, timeout: float = 8, max_bytes: int = 1_500_000,
                     accept: str = "text/html,application/xhtml+xml") -> dict:
    """Returns {ok, html, final_url, note}. Same SSRF / robots / size / no-bypass controls. Never raises."""
    cur = url
    try:
        for _hop in range(4):
            await check_url(cur)
            if not await robots_allowed(client, cur):
                return {"ok": False, "note": "robots.txt disallows automated access — headline/snippet only"}
            async with client.stream("GET", cur, headers={"User-Agent": settings.user_agent, "Accept": accept},
                                     timeout=timeout, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    if not loc:
                        return {"ok": False, "note": "redirect without location"}
                    cur = urljoin(cur, loc)
                    continue
                if r.status_code in (401, 402, 403):
                    return {"ok": False, "note": f"access restricted (HTTP {r.status_code}) — not bypassed"}
                if r.status_code >= 400:
                    return {"ok": False, "note": f"HTTP {r.status_code}"}
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype:
                    return {"ok": False, "note": f"unsupported content type ({ctype.split(';')[0] or 'unknown'})"}
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return {"ok": False, "note": "page exceeds size cap"}
                return {"ok": True, "html": buf.decode(r.encoding or "utf-8", errors="replace"), "final_url": cur, "note": None}
        return {"ok": False, "note": "too many redirects"}
    except FetchBlocked as e:
        return {"ok": False, "note": f"blocked by SSRF policy: {e}"}
    except httpx.TimeoutException:
        return {"ok": False, "note": "timeout"}
    except Exception as e:
        return {"ok": False, "note": f"fetch error: {type(e).__name__}"}


async def fetch_article(client: httpx.AsyncClient, url: str, *, timeout: float = 8, max_bytes: int = 1_500_000) -> dict:
    """Returns {ok, text, final_url, note, published}. Never raises."""
    r = await fetch_html(client, url, timeout=timeout, max_bytes=max_bytes)
    if not r["ok"]:
        return {"ok": False, "note": r["note"]}
    text, pub = extract_text(r["html"])
    low = text.lower()
    paywalled = len(text) < 600 and any(k in low for k in ("subscribe", "sign in", "log in", "subscription"))
    return {"ok": len(text) > 200 and not paywalled, "text": text, "final_url": r["final_url"], "published": pub,
            "note": "paywall/login page — not bypassed" if paywalled else None}
