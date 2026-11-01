"""Folding with an offset map so matches on folded text can be mapped back to verbatim original spans."""
import re
import unicodedata

_SPECIAL = {"ß": "ss", "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ı": "i",
            "’": "", "'": "", "`": ""}


def fold_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    mp: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        rep = _SPECIAL.get(ch)
        if rep is None:
            d = unicodedata.normalize("NFKD", ch.lower())
            rep = "".join(c for c in d if not unicodedata.combining(c))
        for c in rep:
            if c.isalnum() or c == "_":
                out.append(c)
                mp.append(i)
                prev_space = False
            elif not prev_space:
                out.append(" ")
                mp.append(i)
                prev_space = True
    return "".join(out), mp


def orig_span(mp: list[int], start: int, end: int, text_len: int) -> tuple[int, int]:
    if not mp:
        return 0, 0
    s = mp[min(start, len(mp) - 1)]
    e = mp[end - 1] + 1 if end - 1 < len(mp) else text_len
    return s, e


_SENT = re.compile(r"(?<=[.!?。])\s+(?=[\"“‘(\[]?[A-ZÀ-ÖØ-ÞА-ЯΑ-Ω0-9\u0600-\u06FF])|\n+")


def sentences(text: str) -> list[tuple[int, int, str]]:
    out = []
    pos = 0
    for m in _SENT.finditer(text):
        seg = text[pos:m.start()]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append((pos + lead, m.start(), seg.strip()))
        pos = m.end()
    seg = text[pos:]
    if seg.strip():
        lead = len(seg) - len(seg.lstrip())
        out.append((pos + lead, len(text), seg.strip()))
    return out


def pattern_regex(p: str) -> str:
    """Taxonomy pattern -> regex over folded text. Trailing '*' = prefix match."""
    from ..research.names import fold
    star = p.endswith("*")
    body = fold(p.rstrip("*"))
    body = re.escape(body).replace(r"\ ", r"\s")
    return r"(?<![\w])" + body + (r"\w*" if star else r"(?![\w])")
