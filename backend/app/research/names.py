"""Name normalisation and variant expansion (rule-based; transparent)."""
import json
import re
import unicodedata

from ..config import DATA_DIR

LEGAL_SUFFIXES = {
    "ltd": "limited", "limited": "ltd", "plc": "public limited company", "llp": "limited liability partnership",
    "llc": "limited liability company", "inc": "incorporated", "incorporated": "inc", "corp": "corporation",
    "corporation": "corp", "co": "company", "ag": "aktiengesellschaft", "gmbh": "gesellschaft mit beschrankter haftung",
    "sa": "societe anonyme", "sas": "", "sarl": "", "spa": "societa per azioni", "srl": "", "bv": "besloten vennootschap",
    "nv": "naamloze vennootschap", "se": "societas europaea", "oy": "", "ab": "aktiebolag", "as": "", "asa": "",
    "pty": "", "pte": "", "kg": "kommanditgesellschaft", "ug": "", "lp": "limited partnership", "sl": "", "lda": "",
    "holdings": "", "holding": "", "group": "",
}
FORM_FAMILY = {  # legal form tokens that denote a distinct legal form (for contradictions)
    "ltd": "uk_ltd", "limited": "uk_ltd", "plc": "plc", "llp": "llp", "llc": "llc", "inc": "us_inc",
    "incorporated": "us_inc", "corp": "us_inc", "corporation": "us_inc", "ag": "ag", "aktiengesellschaft": "ag",
    "gmbh": "gmbh", "sa": "sa", "sas": "sas", "sarl": "sarl", "spa": "spa", "srl": "srl", "bv": "bv", "nv": "nv",
    "se": "se", "ab": "ab", "pty": "pty", "pte": "pte", "kg": "kg", "lp": "lp",
}
TRANSLIT = [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("ł", "l"),
            ("đ", "d"), ("ı", "i")]
PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "del", "della", "du", "la", "le", "al", "el", "bin", "ibn", "bint", "abu"}

_common = json.loads((DATA_DIR / "common_names.json").read_text(encoding="utf-8"))
COMMON_GIVEN = set(_common["given"])
COMMON_SURNAME = set(_common["surname"])


def fold(s: str) -> str:
    """Lower-case, strip diacritics, collapse punctuation to spaces."""
    s = (s or "").lower()
    for a, b in (("ß", "ss"), ("ł", "l"), ("đ", "d"), ("ø", "o"), ("æ", "ae"), ("ı", "i")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def translit_variant(s: str) -> str:
    low = s.lower()
    for a, b in TRANSLIT:
        low = low.replace(a, b)
    return fold(low)


def tokens(s: str) -> list[str]:
    return fold(s).split()


def split_legal_suffix(name: str) -> tuple[str, list[str]]:
    toks = tokens(name)
    suf = []
    while toks and toks[-1] in LEGAL_SUFFIXES and len(toks) > 1:
        suf.insert(0, toks.pop())
    return " ".join(toks), suf


def legal_form(name: str) -> str | None:
    _, suf = split_legal_suffix(name)
    for s in suf:
        if s in FORM_FAMILY:
            return FORM_FAMILY[s]
    return None


def is_common_name(name: str) -> bool:
    t = [x for x in tokens(name) if x not in PARTICLES]
    if len(t) < 2:
        return len(t) == 1  # a single token is inherently ambiguous
    return t[0] in COMMON_GIVEN and t[-1] in COMMON_SURNAME


def expand_individual(name: str, aliases: list[str]) -> list[dict]:
    out: list[dict] = []
    seen = set()

    def add(v: str, kind: str, searchable: bool = True):
        k = fold(v)
        if k and k not in seen and len(k) >= 3:
            seen.add(k)
            out.append({"value": v.strip(), "kind": kind, "searchable": searchable})

    add(name, "exact")
    add(fold(name), "diacritics-folded", searchable=False)
    tv = translit_variant(name)
    if tv != fold(name):
        add(tv.title(), "transliteration")
    t = name.split()
    if len(t) >= 3:  # drop middle names: "John Paul Smith" -> "John Smith"
        add(f"{t[0]} {t[-1]}", "middle-name-dropped")
    if len(t) >= 2:
        add(f"{t[-1]} {' '.join(t[:-1])}", "name-order-swapped", searchable=False)
        add(f"{t[0][0]}. {t[-1]}", "initial", searchable=False)
        add(f"{t[-1]}, {t[0]}", "surname-first", searchable=False)
    for a in aliases:
        add(a, "alias")
    return out


def expand_entity(name: str, aliases: list[str]) -> list[dict]:
    out: list[dict] = []
    seen = set()

    def add(v: str, kind: str, searchable: bool = True):
        k = fold(v)
        if k and k not in seen and len(k) >= 2:
            seen.add(k)
            out.append({"value": v.strip(), "kind": kind, "searchable": searchable})

    add(name, "exact")
    core, suf = split_legal_suffix(name)
    if suf and len(core) >= 3:
        add(_title_like(name, core), "legal-suffix-stripped")
        for s in suf:
            exp = LEGAL_SUFFIXES.get(s)
            if exp:
                add(f"{_title_like(name, core)} {exp.title()}", "legal-suffix-expanded", searchable=False)
    tv = translit_variant(name)
    if tv != fold(name):
        add(tv.title(), "transliteration")
    amp = name.replace("&", "and") if "&" in name else (name.replace(" and ", " & ") if " and " in name else None)
    if amp:
        add(amp, "ampersand-variant", searchable=False)
    for a in aliases:
        add(a, "alias")
    return out


def _title_like(original: str, core_folded: str) -> str:
    # Reconstruct the core name using original casing where possible
    n = len(core_folded.split())
    return " ".join(original.split()[:n])
