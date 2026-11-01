"""URL normalisation and syndication clustering.

Two items are the same story when their normalised URLs match, or when their normalised-title word
3-gram shingles have Jaccard similarity >= 0.6 (or normalised titles are identical). Within a cluster the
original is the most authoritative (lowest tier) then earliest-published item; others are recorded as
corroborating coverage. Independent sources = distinct publisher domains in the cluster.
"""
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .names import fold

TRACKING = re.compile(r"^(utm_|fbclid|gclid|ocid|cmpid|ref|referrer|rss|mc_|igshid|guccounter|smid|ito)")


def normalise_url(u: str) -> str:
    try:
        p = urlparse(u.strip())
    except Exception:
        return u
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k.lower())]
    host = (p.netloc or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("amp.")
    path = re.sub(r"/(amp|amp\.html)$", "", p.path or "/").rstrip("/") or "/"
    return urlunparse(("https", host, path, "", urlencode(q), ""))


def title_key(t: str) -> str:
    t = re.sub(r"\s[-|–—]\s[^-|–—]{2,60}$", "", t or "")  # drop " - Publisher" suffix
    return fold(t)


def shingles(t: str, n: int = 3) -> set:
    w = title_key(t).split()
    if len(w) < n:
        return {" ".join(w)} if w else set()
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster(items: list, tier_fn) -> list[list]:
    """items: RawItem list. Returns list of clusters (lists), each sorted original-first."""
    clusters: list[dict] = []
    by_url: dict[str, int] = {}
    for it in items:
        if not it.url or not it.title:
            continue
        nu = normalise_url(it.url)
        sh = shingles(it.title)
        tk = title_key(it.title)
        idx = by_url.get(nu)
        if idx is None:
            for i, c in enumerate(clusters):
                if tk and (tk == c["tk"] or jaccard(sh, c["sh"]) >= 0.6):
                    idx = i
                    break
        if idx is None:
            clusters.append({"items": [it], "sh": sh, "tk": tk})
            idx = len(clusters) - 1
        else:
            if all(normalise_url(x.url) != nu or x.provider != it.provider for x in clusters[idx]["items"]):
                clusters[idx]["items"].append(it)
        by_url[nu] = idx

    out = []
    for c in clusters:
        its = c["items"]
        its.sort(key=lambda x: (tier_fn(x)[0], 0 if not x.extra.get("google_link") or x.extra.get("resolved") else 1,
                                x.published_at or "9999"))
        out.append(its)
    return out
