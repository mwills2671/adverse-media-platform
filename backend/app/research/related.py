"""Related-party discovery for ENTITY subjects: directors, board members, executives, shareholders, intermediary
shareholders (ownership chain) and possible UBOs.

Design rules (non-negotiable):
* Keyless, public, robots.txt-respecting sources only: the subject's own website (link-following limited to
  governance/shareholder pages), Wikipedia article pages (/wiki/…; the search API is robots-disallowed so it is NOT
  used), Wikidata entity JSON (/wiki/Special:EntityData/Q….json, robots-allowed) reached via the article's sitelink,
  Google News / Bing News RSS snippets and directly fetchable news articles, and Companies House when a key is set.
* No hallucination: every candidate name must appear verbatim (after case/diacritic folding) in text that was
  actually fetched in this run, and every candidate carries the URL + the verbatim line/sentence it came from.
  Optional LLM extraction is verified the same way and dropped if it cannot be grounded.
* Nothing is asserted: every candidate is "Unverified — analyst confirmation required". Confidence reflects source
  type (company's own site / official register = high, Wikidata/Wikipedia infobox = medium, sentence patterns in
  encyclopaedia or news text = low) and is raised one level when >=2 independent hosts agree.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from ..config import DATA_DIR, settings
from . import fetcher
from .names import fold, split_legal_suffix

ROLES = ("director", "board_member", "executive", "shareholder", "intermediary", "ubo", "owner", "founder",
         "parent", "related_person", "other")
ROLE_LABEL = {"director": "Director", "board_member": "Board member", "executive": "Executive / management",
              "shareholder": "Shareholder", "intermediary": "Intermediary shareholder", "ubo": "UBO (possible)",
              "owner": "Owner", "founder": "Founder", "parent": "Parent company", "related_person": "Related person",
              "other": "Other"}
CONF_ORDER = {"low": 0, "medium": 1, "high": 2}
UNVERIFIED = "Unverified — analyst confirmation required"

_geo = json.loads((DATA_DIR / "geo.json").read_text(encoding="utf-8"))
GEO_WORDS = {w for v in _geo.values() for w in v} | {"azerbaijani", "georgian", "turkish", "german", "russian", "american",
                                                     "türkiye", "turkiye", "europe", "european", "asia", "dubai", "tashkent",
                                                     "uzbekistan", "montenegro", "aschheim", "bavaria", "munich"}
ORG_SUFFIX = re.compile(
    r"\b(ltd|limited|llc|l\.l\.c|llp|plc|gmbh|ag|sa|s\.a|sas|sarl|spa|srl|bv|b\.v|nv|n\.v|se|jsc|ojsc|cjsc|pjsc|ojs[cс]|"
    r"inc|incorporated|corp|corporation|company|co|holding|holdings|group|bank|fund|trust|foundation|capital|partners|"
    r"investments?|ventures|enterprises|asset management|management|kg|ab|asa|oy|pte|pty|lp|mmc|qsc|ooo|zao|oao|"
    r"s\.p\.a|international|industries|insurance|finance|financial)\b\.?$", re.I)
ORG_WORD = re.compile(r"\b(ltd|limited|llc|llp|plc|gmbh|ag|jsc|ojsc|cjsc|inc|corp|holding|holdings|group|bank|fund|trust|"
                      r"foundation|capital|company|investments?|partners|financial|insurance|mmc|ooo)\b", re.I)
NAV_WORDS = {w.lower() for w in """home about contact board bank services products news careers career menu search login log
online banking corporate private business personal cards card loans loan deposits deposit investor investors relations
report reports annual policy privacy terms cookies cookie company holding group office offices branches branch atms atm
our we us team management executive supervisory governance shareholders shareholder structure committee committees
internal audit compliance media press center centre more read all back next previous download documents sustainability
esg vacancies tariffs rates calculator mobile app apps internet security fraud help faq support customers customer
digital payments payment transfers transfer exchange currency trade finance leasing insurance mortgage credit debit
youtube facebook twitter instagram linkedin telegram whatsapp english русский azərbaycan deutsch français español
chief officers officer chairman chairwoman chair member members independent deputy director directors president vice head
ceo cfo coo cro cto cio general manager managers secretary financial risk operating technology information
department division unit strategy marketing human resources legal treasury operations retail sme small medium
the of and for in on at to by with from a an is are was were be update date latest copyright reserved rights
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
september october november december founded established""".split()}
PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "del", "della", "du", "la", "le", "al", "el", "bin", "ibn",
             "bint", "abu", "y", "dos", "das", "zu", "ter", "ten", "oglu", "oğlu", "qizi", "qızı", "kyzy", "uly"}
ROLE_RX = re.compile(
    r"(chairman|chairwoman|chairperson|chair\b|vice[- ]chair\w*|deputy chair\w*|chief executive( officer)?|\bceo\b|\bcfo\b|"
    r"\bcoo\b|\bcro\b|\bcto\b|\bcio\b|\bcco\b|chief [a-z]+ officer|managing director|general director|director general|"
    r"executive director|non-executive director|independent (non-executive )?(director|member)|\bdirector\b|"
    r"\bpresident\b|vice[- ]president|co-?founder|\bfounder\b|\bowner\b|board member|member of the [a-z ]*board|"
    r"head of the [a-z ]*board|\bdeputy ceo\b|deputy chief executive|managing partner|company secretary|general counsel|"
    r"supervisory board|executive board|management board|board of directors|\bvorstand|aufsichtsrat|geschäftsführer|"
    r"président|directeur général|administrateur|\bmember\b|\bpartner\b|\btreasurer\b|chief officer)", re.I)
PCT_LINE = re.compile(r"^[≈~<>]?\s*(?:approx\.?\s*)?(\d{1,3}(?:[.,]\d{1,4})?)\s*%$")
PCT_INLINE = re.compile(r"(\d{1,3}(?:[.,]\d{1,4})?)\s?%")
SHAREHOLDER_PAGE = re.compile(r"sharehold|ownership|owner|s[əe]hmdar|aktion[äa]r|actionna|accionist|capital structure", re.I)
LINK_SCORES = [
    (re.compile(r"sharehold|ownership|s[əe]hmdar|aktion[äa]r|actionna|accionist|beneficial|capital-structure", re.I), 6),
    (re.compile(r"supervisory|board|directors|executive|management[- ]board|management[- ]team|leadership|officers|"
                r"m[uü]+sahid|idar[əe][- ]?heyet|direktor|vorstand|aufsichtsrat|gouvernance|r[əe]hb[əe]rlik|our[- ]team", re.I), 4),
    (re.compile(r"governance|corporate-governance|structure|who-we-are", re.I), 3),
    (re.compile(r"about|investor|company|corporate|haqq", re.I), 1),
]
PAGE_KIND = [
    ("shareholders", re.compile(r"sharehold|ownership|s[əe]hmdar|aktion[äa]r|actionna", re.I)),
    ("supervisory", re.compile(r"supervisory|m[uü]+sahid|aufsichtsrat|board of directors|non-executive|conseil", re.I)),
    ("executive", re.compile(r"executive|management board|idar[əe][- ]?heyet|vorstand|management|leadership|officers|"
                             r"direktor", re.I)),
]
OWN_KW = re.compile(
    r"\b(owned by|owner|owners|ownership|shareholders?|stake|stakes|beneficial(ly)? own\w*|ultimate(ly)?\s+(owned|controlled|"
    r"beneficial|shareholders?|owners?)|controlled by|controlling (interest|shareholder|stake)|holds? (a )?\d|"
    r"subsidiary of|parent company|majority[- ]owned|wholly[- ]owned|founded by|co-?founded by|belongs to)\b", re.I)
SPECULATIVE = re.compile(r"\b(could|may|might|would|considering|considers|plans? to|planning|talks|eyes|eyeing|mulls?|"
                         r"reportedly|rumou?r\w*|bid for|offer for|become a shareholder|buy shares)\b", re.I)
RELATIVE_CTX = re.compile(r"(daughters?|sons?|children|wife|husband|father|mother|brother|sister|nephew|niece|"
                          r"son-in-law|daughter-in-law|relatives?|cousin|uncle|aunt)\s+of\b[^.;]{0,45}$", re.I)
TITLE_CTX = re.compile(r"\b(president|prime minister|minister|king|emir|sheikh|governor|senator|first lady)\s*,?\s*$", re.I)
HOLDING_CTX = re.compile(r"\b(stake|interest|holdings?|subsidiar\w*|owns?|acquired|invest\w*|shares)\s+(of\s+|in\s+)?"
                         r"(the\s+)?[^.;]{0,25}$|\bholdings are\b[^.;]*$|\bsubsidiaries (are|include)\b[^.;]*$", re.I)
FOUNDER_CTX = re.compile(r"\b(co-?)?founded by\b[^.;]{0,40}$", re.I)
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
STOP_SPAN = {"the", "it", "its", "this", "these", "in", "on", "since", "after", "before", "according", "however", "critics",
             "company", "group", "bank", "holding", "board", "ceo", "chairman", "president", "mr", "mrs", "ms", "dr", "sir",
             "following", "during", "today", "under", "while", "although", "both", "as", "also", "his", "her", "their",
             "for", "from", "with", "and", "or", "but", "first", "last", "new", "former", "current", "deputy"}


# ----------------------------------------------------------------------------------------------------------------- utils
def _clean(s: str) -> str:
    s = re.sub(r"\[\s*\d+\s*\]|\[\s*[a-z]\s*\]|\[citation needed\]", "", s or "")
    return re.sub(r"\s+", " ", s).strip(" \t\n,;:|·•–—-")


def _tok_ok(t: str, first: bool) -> bool:
    if t.lower() in PARTICLES and not first:
        return True
    if not t[:1].isalpha() or not t[:1].isupper():
        return False
    core = t.replace("-", "").replace("'", "").replace("’", "").replace(".", "")
    return core.isalpha()


def is_person_name(s: str) -> bool:
    s = _clean(s)
    if not 4 <= len(s) <= 60 or any(c.isdigit() for c in s) or s.endswith(":"):
        return False
    toks = s.split()
    if not 2 <= len(toks) <= 5:
        return False
    if not all(_tok_ok(t, i == 0) for i, t in enumerate(toks)):
        return False
    low = [fold(t) for t in toks if t.lower() not in PARTICLES]
    if any(t in NAV_WORDS or t in GEO_WORDS for t in low):
        return False
    if ORG_WORD.search(s):
        return False
    if all(len(t) <= 2 for t in low):
        return False
    return True


def is_org_name(s: str) -> bool:
    s = _clean(s)
    if not 3 <= len(s) <= 90 or s.endswith(":"):
        return False
    toks = s.split()
    if not 1 <= len(toks) <= 9 or not (toks[0][:1].isupper() or toks[0][:1].isdigit()):
        return False
    if re.match(r"(?i)^(other|others|free float|total|treasury|public|minority|individuals)\b", s):
        return False
    return bool(ORG_SUFFIX.search(s) or ORG_WORD.search(s))


def party_type_of(name: str) -> str:
    if re.search(r"\bfamil(y|ies)\b", name, re.I):
        return "family"
    return "entity" if is_org_name(name) else "individual"


def _pct(s: str | None) -> str | None:
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return (f"{v:g}") if 0 < v <= 100 else None


def role_from_text(role_text: str, page_kind: str | None = None) -> str:
    r = (role_text or "").lower()
    if re.search(r"supervisory|non-executive|board of directors|independent|aufsichtsrat|administrateur", r):
        return "board_member"
    if re.search(r"executive board|management board|chief|ceo|cfo|coo|cro|cto|managing director|general director|"
                 r"director general|deputy|president|head of|vorstand|geschäftsführer|directeur|officer", r):
        return "executive"
    if re.search(r"co-?founder|founder", r):
        return "founder"
    if re.search(r"\bowner\b", r):
        return "owner"
    if re.search(r"sharehold", r):
        return "shareholder"
    if re.search(r"chair|member|board", r):
        if page_kind == "executive":
            return "executive"
        return "board_member"
    if re.search(r"director", r):
        return "director"
    if page_kind == "supervisory":
        return "board_member"
    if page_kind == "executive":
        return "executive"
    return "other"


def html_lines(html: str) -> tuple[list[str], str, list[tuple[str, str]]]:
    """Line-preserving extraction (management pages are lists of short name/role lines, which the article extractor
    drops). Returns (lines, page title, links[(href, anchor text)])."""
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.title.get_text(" ") if soup.title else "")
    h1 = soup.find("h1")
    if h1:
        title = (title + " | " + _clean(h1.get_text(" "))).strip(" |")
    links = [(a.get("href") or "", _clean(a.get_text(" "))) for a in soup.find_all("a")]
    for t in soup(["script", "style", "noscript", "svg", "iframe", "form", "template"]):
        t.decompose()
    for t in soup(["nav", "header", "footer"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in lines if ln], title, links


def page_kind_of(url: str, title: str) -> str | None:
    hay = f"{urlparse(url).path} {title}"
    for k, rx in PAGE_KIND:
        if rx.search(hay):
            return k
    return None


def _cand(name, role, *, url, source, method, quote_, conf, role_detail=None, pct=None, via=None, depth=1,
          partial=False, ptype=None, published=None) -> dict:
    name = _clean(name)
    return {"name": name, "party_type": ptype or party_type_of(name), "role": role, "role_detail": role_detail,
            "ownership_pct": pct, "via": via, "depth": depth, "confidence": conf, "partial_name": partial,
            "evidence": [{"url": url, "source": source, "method": method, "quote": _clean(quote_)[:400],
                          **({"published": published} if published else {})}]}


# ------------------------------------------------------------------------------------- extraction: website line pairs
def extract_people_lines(lines: list[str], url: str, page_kind: str | None, source: str, title: str = "") -> list[dict]:
    out = []
    used = set()
    headings = {fold(x) for x in re.split(r"\s*\|\s*", title) if x}
    for i, ln in enumerate(lines):
        if i in used or not is_person_name(ln):
            continue
        role_line = None
        for j in (i + 1, i - 1, i + 2):
            if 0 <= j < len(lines) and j not in used and len(lines[j]) <= 160 and ROLE_RX.search(lines[j]) \
                    and not is_person_name(lines[j]) and fold(lines[j]) not in headings:
                role_line = (j, lines[j])
                break
        if not role_line:
            continue
        j, rl = role_line
        role = role_from_text(rl, page_kind)
        if role == "other" and page_kind is None:
            continue
        used.update({i, j})
        out.append(_cand(ln, role, url=url, source=source, method="company website: name/role lines",
                         quote_=f"{ln} — {rl}", conf="high", role_detail=_clean(rl)[:200]))
    return out


def extract_shareholder_lines(lines: list[str], url: str, source: str, ubo_threshold: float = 25.0) -> list[dict]:
    out = []
    idx = [i for i, ln in enumerate(lines) if PCT_LINE.match(ln)]
    if not idx:
        # inline "Name ..... 53.97%" rows
        for ln in lines:
            m = re.match(r"^(.{3,90}?)\s*[–—:\-|]?\s*[≈~]?\s*(\d{1,3}(?:[.,]\d{1,4})?)\s*%$", ln)
            if m and (is_org_name(m.group(1)) or is_person_name(m.group(1))):
                out.append(_sh(m.group(1), _pct(m.group(2)), url, source, ln, ubo_threshold))
        return [c for c in out if c]

    def party(j):
        return 0 <= j < len(lines) and not PCT_LINE.match(lines[j]) and (is_org_name(lines[j]) or is_person_name(lines[j]))
    # orientation: "Name / 53%" or "53% / Name" — pick whichever pairs up more rows (ties: name first)
    nf, pf = sum(party(i - 1) for i in idx), sum(party(i + 1) for i in idx)
    first = idx[0]
    name_first = nf > pf if nf != pf else (party(first - 1) and not party(first + 1)) or (party(first - 1) and party(first + 1))
    used: set[int] = set()
    for i in idx:
        j = i - 1 if name_first else i + 1
        if not party(j) or j in used:
            j = i + 1 if name_first else i - 1
            if not party(j) or j in used:
                continue
        used.add(j)
        c = _sh(lines[j], _pct(PCT_LINE.match(lines[i]).group(1)), url, source, f"{lines[i]} {lines[j]}" if not name_first
                else f"{lines[j]} {lines[i]}", ubo_threshold)
        if c:
            out.append(c)
    return out


def _sh(name, pct, url, source, quote_, thr):
    name = _clean(name)
    if not pct:
        return None
    pt = "entity" if is_org_name(name) else "individual"
    if pt == "entity":
        role, detail = "intermediary", "Corporate shareholder — possible intermediary in the ownership chain"
    elif float(pct) >= thr:
        role, detail = "ubo", f"Individual shareholder ≥{thr:g}% — possible UBO (direct holding reported)"
    else:
        role, detail = "shareholder", "Individual shareholder"
    return _cand(name, role, url=url, source=source, method="company website: shareholder list", quote_=quote_,
                 conf="high", role_detail=detail, pct=pct, ptype=pt)


# ----------------------------------------------------------------------------------- extraction: ownership sentences
_CAP_TOKEN = r"[A-ZÀ-ÖØ-ÞĀ-ŽƏ][\w’'\-]*\.?"
_SPAN = re.compile(rf"{_CAP_TOKEN}(?:\s+(?:(?:{'|'.join(sorted(PARTICLES))})\s+)?{_CAP_TOKEN}){{0,5}}")
_FAMILY = re.compile(rf"\b({_CAP_TOKEN})(?:\s*,\s*({_CAP_TOKEN}))?(?:\s+and\s+({_CAP_TOKEN}))?\s+famil(?:y|ies)\b")


def _subject_keys(names: list[str]) -> list[str]:
    keys = set()
    for n in names:
        f = fold(n)
        if f:
            keys.add(f)
        core, _ = split_legal_suffix(n)
        if core and len(core) >= 4:
            keys.add(core)
    return sorted(keys, key=len, reverse=True)


def _mentions(text_f: str, keys: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}(?:s)?\b", text_f) for k in keys)  # fold() turns "X's" into "Xs"


def _titlecase(s: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-zÀ-ž][\w’'-]*", s) if len(w) > 3]
    return len(words) >= 3 and sum(w[0].isupper() for w in words) / len(words) >= 0.7


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\[\s*\d+\s*\]", "", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])|\n+", text)
    return [p.strip() for p in parts if 20 <= len(p.strip()) <= 700]


def extract_ownership_sentences(text: str, *, subject_names: list[str], url: str, source: str, own_article: bool,
                                conf: str = "low", exclude: list[str] | None = None, via: str | None = None,
                                depth: int = 1, published: str | None = None) -> list[dict]:
    """Owners/shareholders/founders/relatives named in ownership sentences.
    own_article=True: the text is ABOUT the subject (e.g. its own Wikipedia article), so sentences need not repeat the
    name. Otherwise a sentence must mention the subject. Holdings OF the subject ("X owns a stake in Y") are skipped."""
    keys = _subject_keys(subject_names)
    excl = set(keys) | {fold(e) for e in (exclude or [])} | {split_legal_suffix(e)[0] for e in (exclude or [])}
    out = []
    for sent in _split_sentences(text):
        if not OWN_KW.search(sent):
            continue
        sf = fold(sent)
        if not own_article and not _mentions(sf, keys):
            continue
        if not own_article and SPECULATIVE.search(sent):
            continue  # "could take a stake", "in talks to buy" — not an ownership fact
        rel_sentence = bool(re.search(r"\b(daughters?|sons?|wife|husband|father|mother|brother|sister|famil(y|ies)|children)\b", sent, re.I))
        ultimate = bool(re.search(r"\bultimate|beneficial", sent, re.I))
        fams = set()
        for m in _FAMILY.finditer(sent):
            for g in m.groups():
                if g and fold(g) not in GEO_WORDS and fold(g) not in STOP_SPAN:
                    fams.add(g)
                    out.append(_cand(f"{g} family", "ubo" if ultimate else "owner", url=url, source=source,
                                     method="ownership sentence (family)", quote_=sent, conf=conf, via=via, depth=depth,
                                     ptype="family", published=published,
                                     role_detail="Family named as owner — identify individual members"))
        for m in _SPAN.finditer(sent):
            span = m.group(0).strip().rstrip(".")
            if not own_article and re.search(r"(’s|'s)$", span):
                continue  # "China's Alipay" style possessives in news
            span = re.sub(r"(’s|'s)$", "", span)
            toks = span.split()
            while toks and fold(toks[0]) in STOP_SPAN:
                toks.pop(0)
            if not toks:
                continue
            span = " ".join(toks)
            sp_f = fold(span)
            if not sp_f or sp_f in GEO_WORDS or sp_f in MONTHS or sp_f in STOP_SPAN or sp_f in NAV_WORDS:
                continue
            if any(sp_f == e or (len(e) > 3 and e in sp_f) or (len(sp_f) > 3 and sp_f in e) for e in excl if e):
                continue
            if any(sp_f == fold(f) for f in fams):
                continue  # surname already captured as a family
            if all(fold(t) in GEO_WORDS or fold(t) in STOP_SPAN for t in toks):
                continue
            before = sent[:m.start()]
            if re.search(r"\((née|nee|born)\s*$", before, re.I) or before.rstrip().endswith("(née"):
                continue
            after = sent[m.end():m.end() + 40]
            if re.match(r"^\s*famil(y|ies)", after, re.I):
                continue
            if HOLDING_CTX.search(before[-60:]):
                continue  # this is something the owner HOLDS, not an owner
            if re.match(r"^\s*(\(|,)?\s*(a |the )?(subsidiary|unit|holding|stake)", after, re.I) and not own_article:
                continue
            pt = "entity" if is_org_name(span) else "individual"
            single = len(toks) == 1
            if pt == "individual" and not single and not is_person_name(span):
                continue
            if single and (len(span) < 3 or not span[0].isupper() or span.isupper() or not rel_sentence or not own_article):
                continue  # lone given names only from family/relative sentences in an article about the owner
            if RELATIVE_CTX.search(before) or TITLE_CTX.search(before):
                role, detail = "related_person", "Named as a relative/reference person in an ownership sentence (possible PEP link)"
            elif FOUNDER_CTX.search(before):
                role, detail = "founder", "Named as founder"
            else:
                role = "ubo" if ultimate else ("intermediary" if pt == "entity" else "owner")
                detail = "Named as ultimate/beneficial owner" if ultimate else "Named as owner/shareholder"
            pm = PCT_INLINE.search(after[:25])
            out.append(_cand(span, role, url=url, source=source, method="ownership sentence", quote_=sent, conf=conf,
                             role_detail=detail + (" — given name only; complete before screening" if single else ""),
                             pct=_pct(pm.group(1)) if pm else None, via=via, depth=depth, partial=single, ptype=pt,
                             published=published))
    return out


def extract_parent_mentions(text: str, *, subject_names: list[str], url: str, source: str, conf="low",
                            published=None) -> list[dict]:
    """In text NOT about the subject: '<Org> … holdings are … <Subject> (71.7%)', '<Org>-owned <Subject>',
    '<Subject>, a subsidiary of <Org>', '<Org> owns N% of <Subject>'."""
    keys = _subject_keys(subject_names)
    out = []
    org = rf"({_CAP_TOKEN}(?:\s+{_CAP_TOKEN}){{0,5}})"
    for sent in _split_sentences(text):
        sf = fold(sent)
        if not _mentions(sf, keys):
            continue
        for k in keys:
            ks = re.escape(k).replace(r"\ ", r"[\s\-]+")
            pats = [
                (rf"{org}[’']s?\s+(?:major\s+|main\s+|core\s+)?holdings\s+(?:are|include)[^.]*?\b{ks}\b\s*\(\s*(\d{{1,3}}(?:[.,]\d+)?)\s*%",
                 "holdings list"),
                (rf"{org}\s+(?:owns|holds|controls)\s+(?:a\s+|an\s+)?(?:(\d{{1,3}}(?:[.,]\d+)?)\s*%\s*)?(?:stake\s+|interest\s+)?(?:of|in)\s+{ks}\b",
                 "owns stake"),
                (rf"\b{ks}\b\s*,?\s*(?:a|the)?\s*(?:wholly[- ]owned\s+|majority[- ]owned\s+)?(?:subsidiary|unit|part)\s+of\s+{org}",
                 "subsidiary of"),
                (rf"{org}[- ](?:owned|controlled)\s+{ks}\b", "X-owned"),
                (rf"\b{ks}\b\s*,?\s*(?:which\s+)?(?:is\s+|was\s+)?(?:majority[- ]|wholly[- ]|ultimately\s+)?(?:owned|controlled)\s+by\s+(?:the\s+)?{org}",
                 "owned by"),
            ]
            for rx, kind in pats:
                for m in re.finditer(rx, fold_keep_case(sent), re.I):
                    name = m.group(1)
                    pct = m.group(2) if m.lastindex and m.lastindex >= 2 else None
                    nm = re.sub(r"^(The|Its|In)\s+", "", name).strip()
                    if fold(nm) in keys or fold(nm) in GEO_WORDS or not nm[:1].isupper():
                        continue
                    out.append(_cand(nm, "parent" if party_type_of(nm) == "entity" else "owner", url=url, source=source,
                                     method=f"parent/owner pattern ({kind})", quote_=sent, conf=conf, pct=_pct(pct),
                                     role_detail="Reported parent / corporate shareholder — possible intermediary",
                                     published=published))
    return out


def fold_keep_case(s: str) -> str:
    """Keep case but normalise apostrophes/hyphens so regexes over folded keys line up reasonably."""
    return s.replace("’", "'")


# ------------------------------------------------------------------------------------- news sentence patterns (roles)
def extract_news_roles(text: str, *, subject_names: list[str], url: str, source: str, published=None) -> list[dict]:
    keys = _subject_keys(subject_names)
    out = []
    person = rf"((?-i:{_CAP_TOKEN}(?:\s+{_CAP_TOKEN}){{1,3}}))"
    role = (r"((?i:(?:former |ex-|then[- ])?(?:deputy |vice[- ])?(?:chairman|chairwoman|chair|ceo|cfo|coo|cro|chief executive(?: officer)?|"
            r"chief [a-z]+ officer|managing director|general director|president|member of the (?:executive |supervisory |management )?board|"
            r"head of the (?:executive |supervisory )?board|director)(?: of the (?:executive |supervisory |management )?board)?))")
    for sent in _split_sentences(text):
        sf = fold(sent)
        if not _mentions(sf, keys):
            continue
        s2 = fold_keep_case(sent)
        for k in keys:
            ks = "(?i:" + re.escape(k).replace(r"\ ", r"[\s\-]+") + ")"
            pats = [rf"{role}\s+(?:of|at)\s+\b{ks}\b(?:'s?\s+(?:executive |supervisory |management )?board)?\s*,?\s+{person}",
                    rf"\b{ks}\b(?:'s?)?\s+((?:(?:supervisory|executive|management)\s+board\s+)?{role[1:-1]})\s*,?\s+{person}",
                    rf"{person}\s*,\s*(?:the\s+)?{role}\s+(?:of|at)\s+(?:the\s+)?\b{ks}\b(?!\s+[A-Z][a-z])",
                    rf"{person}\s*,\s*\b{ks}\b(?:'s|’s)?\s+{role}"]
            for n, rx in enumerate(pats):
                for m in re.finditer(rx, s2, re.I):
                    if n in (0, 1):
                        r_, p_ = m.group(1), m.groups()[-1]
                    else:
                        p_, r_ = m.group(1), m.groups()[-1]
                    # different entity guard: '<Subject> Georgia …'
                    tail = s2[m.start():m.end()]
                    if re.search(rf"\b{ks}\s+(?!Executive|Supervisory|Management|Board|Chairman|CEO|Deputy)([A-Z][a-z]+)\b", tail, re.I) \
                            and re.search(rf"\b{ks}\s+([A-Z][a-z]+)", tail) and fold(re.search(rf"\b{ks}\s+([A-Z][a-z]+)", tail).group(1)) in GEO_WORDS:
                        continue
                    p_ = re.sub(r"(’s|'s)$", "", p_.strip())
                    if not is_person_name(p_):
                        continue
                    out.append(_cand(p_, role_from_text(r_), url=url, source=source, method="news: role pattern",
                                     quote_=sent, conf="low", role_detail=_clean(r_), published=published))
    return out


# ----------------------------------------------------------------------------------------------- Wikipedia / Wikidata
def parse_wikipedia(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    canon = soup.find("link", rel="canonical")
    title = (canon.get("href", "").rsplit("/wiki/", 1)[-1] if canon else "").replace("_", " ")
    from urllib.parse import unquote
    title = unquote(title)
    qid = None
    a = soup.select_one("#t-wikibase a, a[href*='wikidata.org/wiki/Special:EntityPage/Q']")
    if a:
        m = re.search(r"(Q\d+)", a.get("href", ""))
        qid = m.group(1) if m else None
    infobox = {}
    ib = soup.select_one("table.infobox")
    if ib:
        for tr in ib.select("tr"):
            th, td = tr.find("th"), tr.find("td")
            if not th or not td:
                continue
            for s in td.select("sup"):
                s.decompose()
            for br in td.find_all("br"):
                br.replace_with("\n")
            for li in td.find_all("li"):
                li.insert_after("\n")
            val = td.get_text("", strip=False)
            infobox[_clean(th.get_text(" ")).lower()] = [_clean(x) for x in val.split("\n") if _clean(x)]
    content = soup.select_one("#mw-content-text") or soup
    disamb = bool(soup.select_one("#disambigbox, .dmbox-disambig")) or "may refer to" in content.get_text(" ")[:3000]
    for s in content.select("sup.reference, table, .navbox, .reflist, style"):
        s.decompose()
    paras = [p.get_text("", strip=False).strip() for p in content.select("p")]
    text = "\n".join(p for p in paras if p)
    return {"title": title, "qid": qid, "infobox": infobox, "text": text, "disambiguation": disamb}


IB_FIELDS = {"key people": None, "owner": "owner", "owners": "owner", "owner(s)": "owner", "parent": "parent",
             "founder": "founder", "founders": "founder", "chairman": "board_member", "ceo": "executive"}


def infobox_candidates(ib: dict, url: str) -> list[dict]:
    out = []
    for field, vals in ib.items():
        if field not in IB_FIELDS:
            continue
        merged: list[str] = []
        for v in vals:  # "(chairman ...)" / ", CEO" often arrive as separate text nodes
            v = v.strip()
            if merged and (v.startswith("(") or v.startswith(",") or (v[:1].islower() and not is_person_name(v))):
                merged[-1] = f"{merged[-1]} {v}" if v.startswith("(") else f"{merged[-1]}{v if v.startswith(',') else ', ' + v}"
            elif v:
                merged.append(v)
        for v in merged:
            m = re.match(r"^(.+?)\s*(?:\((.+?)\)|,\s*(.+)|\s[–—-]\s(.+))?$", v)
            if not m:
                continue
            name = _clean(m.group(1))
            detail = _clean(next((g for g in m.groups()[1:] if g), "") or "")
            pm = PCT_INLINE.search(detail)
            if not name or len(name) > 90 or fold(name) in GEO_WORDS:
                continue
            fixed = IB_FIELDS[field]
            if fixed is None:
                if not is_person_name(name):
                    continue
                role = role_from_text(detail) if detail else "executive"
                if role == "other":
                    role = "executive"
            else:
                role = fixed if not (fixed == "owner" and is_org_name(name)) else "intermediary"
            out.append(_cand(name, role, url=url, source="Wikipedia (infobox)", method=f"infobox field '{field}'",
                             quote_=f"{field.capitalize()}: {v}", conf="medium",
                             role_detail=(detail or field.capitalize())[:200], pct=_pct(pm.group(1)) if pm else None,
                             ptype=None if not fixed or fixed in ("parent",) or is_org_name(name) else "individual"))
    return out


WD_PROPS = {"P169": ("executive", "Chief executive officer"), "P488": ("board_member", "Chairperson"),
            "P3320": ("board_member", "Board member"), "P1037": ("executive", "Director / manager"),
            "P127": ("owner", "Owned by"), "P749": ("parent", "Parent organisation"), "P112": ("founder", "Founded by")}


def wikidata_claims(entity: dict) -> tuple[list[dict], list[str]]:
    claims = entity.get("claims", {})
    refs = []
    for prop, (role, label) in WD_PROPS.items():
        for c in claims.get(prop, []):
            dv = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not isinstance(dv, dict) or "id" not in dv:
                continue
            q = c.get("qualifiers", {})
            end = q.get("P582", [{}])[0].get("datavalue", {}).get("value", {}).get("time") if q.get("P582") else None
            pct = None
            if q.get("P1107"):
                try:
                    pct = _pct(str(round(float(q["P1107"][0]["datavalue"]["value"]["amount"]) * 100, 4)))
                except Exception:
                    pct = None
            refs.append({"id": dv["id"], "role": role, "label": label, "end": end[1:5] if end else None, "pct": pct})
    sites = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P856", []) if c.get("mainsnak", {}).get("datavalue")]
    return refs, sites


# ------------------------------------------------------------------------------------------------------ the crawler
class Discovery:
    def __init__(self, client: httpx.AsyncClient, subject: str, aliases: list[str], identifiers: dict, policy: dict):
        self.c = client
        self.subject = subject
        self.names = [subject] + [a for a in aliases if a]
        self.ids = identifiers or {}
        self.cfg = policy.get("related_parties", {}) or {}
        self.deadline = time.monotonic() + float(self.cfg.get("timeout_s", 45))
        self.sources: list[dict] = []  # what was consulted and how it went
        self.texts: list[tuple[str, str, str]] = []  # (url, source, text) for grounding / LLM
        self.cands: list[dict] = []
        self.pages = 0

    def _log(self, source, url, status, note=None, found=0):
        self.sources.append({"source": source, "url": url, "status": status, "note": note, "found": found})

    def left(self) -> float:
        return self.deadline - time.monotonic()

    async def _json(self, url: str, timeout=8):
        await fetcher.check_url(url)
        if not await fetcher.robots_allowed(self.c, url):
            raise fetcher.FetchBlocked("robots.txt disallows")
        r = await self.c.get(url, headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
                             timeout=timeout, follow_redirects=True)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json()

    # ---- Wikipedia + Wikidata
    async def wikipedia(self, title: str, *, own: bool, via: str | None = None, depth: int = 1) -> dict | None:
        url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
        r = await fetcher.fetch_html(self.c, url, timeout=8, max_bytes=3_000_000)
        if not r["ok"]:
            self._log("Wikipedia", url, "not found" if "404" in (r["note"] or "") else "failed", r["note"])
            return None
        w = parse_wikipedia(r["html"])
        w["url"] = r["final_url"]
        if w["disambiguation"]:
            self._log("Wikipedia", url, "skipped", "disambiguation page")
            return None
        return w

    async def run_wikipedia(self) -> list[str]:
        """Subject's own article (exact title or suffix-stripped title), infobox + ownership sentences + Wikidata."""
        sites = []
        tried = []
        for n in self.names[:2]:
            for t in (n, split_legal_suffix(n)[0].title() if split_legal_suffix(n)[0] != fold(n) else None):
                if t and t.lower() not in [x.lower() for x in tried]:
                    tried.append(t)
        art = None
        for t in tried[:3]:
            w = await self.wikipedia(t, own=True)
            if not w:
                continue
            core = split_legal_suffix(self.subject)[0]
            if max(fuzz.token_set_ratio(fold(w["title"]), fold(self.subject)), fuzz.token_set_ratio(fold(w["title"]), core)) >= 85:
                art = w
                break
            # Redirected elsewhere: use only sentences that relate that article to the subject
            found = extract_parent_mentions(w["text"], subject_names=self.names, url=w["url"], source=f"Wikipedia: {w['title']}")
            for f in found:
                f["role_detail"] = f"Article '{w['title']}' (redirect target) reports the relationship"
            if " ".join(w["title"].split()) and _mentions(fold(w["text"]), _subject_keys(self.names)):
                own_text_cands = self._owner_article_cands(w, via=w["title"])
                found.append(_cand(w["title"], "parent", url=w["url"], source=f"Wikipedia: {w['title']}",
                                   method="Wikipedia redirect target that mentions the subject", conf="low",
                                   quote_=next((s for s in _split_sentences(w["text"]) if _mentions(fold(s), _subject_keys(self.names))), w["title"]),
                                   role_detail="Wikipedia redirects the subject's name to this article"))
                found += own_text_cands
            self._log("Wikipedia", w["url"], "redirected", f"resolved to '{w['title']}'", len(found))
            self.cands += found
            self.texts.append((w["url"], "Wikipedia", w["text"]))
        if not art:
            if not any(s["source"] == "Wikipedia" and s["status"] == "redirected" for s in self.sources):
                self._log("Wikipedia", None, "no article", "No English Wikipedia article under the subject's name "
                          "(the Wikipedia search API is robots-disallowed, so only exact titles are tried)")
            return sites
        self.texts.append((art["url"], "Wikipedia", art["text"]))
        found = infobox_candidates(art["infobox"], art["url"])
        found += extract_ownership_sentences(art["text"], subject_names=self.names + [art["title"]], url=art["url"],
                                             source=f"Wikipedia: {art['title']}", own_article=True, conf="low")
        self._log("Wikipedia", art["url"], "ok", f"article '{art['title']}'", len(found))
        self.cands += found
        for v in art["infobox"].get("website", []):
            sites.append(v if v.startswith("http") else "https://" + v)
        if art["qid"]:
            sites += await self.run_wikidata(art["qid"])
        return sites

    async def run_wikidata(self, qid: str) -> list[str]:
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        try:
            ent = (await self._json(url))["entities"][qid]
        except Exception as e:
            self._log("Wikidata", url, "failed", f"{type(e).__name__}: {e}"[:150])
            return []
        refs, sites = wikidata_claims(ent)
        ids = list(dict.fromkeys(r["id"] for r in refs))[:20]
        labels = {}

        async def lab(i):
            try:
                e = (await self._json(f"https://www.wikidata.org/wiki/Special:EntityData/{i}.json"))["entities"][i]
                labels[i] = (e.get("labels", {}).get("en") or next(iter(e.get("labels", {}).values()), {})).get("value")
                labels[i + "_human"] = any(c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") == "Q5"
                                           for c in e.get("claims", {}).get("P31", []))
            except Exception:
                labels[i] = None
        await asyncio.gather(*(lab(i) for i in ids))
        found = []
        for r in refs:
            name = labels.get(r["id"])
            if not name:
                continue
            human = labels.get(r["id"] + "_human")
            role = r["role"]
            if role == "owner" and not human:
                role = "intermediary"
            detail = r["label"] + (f" (ended {r['end']})" if r["end"] else "")
            found.append(_cand(name, role, url=f"https://www.wikidata.org/wiki/{qid}", source="Wikidata",
                               method=f"Wikidata {r['label']} ({'former' if r['end'] else 'current/undated'})",
                               quote_=f"{qid} {r['label']}: {name} ({r['id']}){' until ' + r['end'] if r['end'] else ''}",
                               conf="low" if r["end"] else "medium", role_detail=detail, pct=r["pct"],
                               ptype="individual" if human else ("entity" if human is False else None)))
        self._log("Wikidata", f"https://www.wikidata.org/wiki/{qid}", "ok", None, len(found))
        self.cands += found
        return sites

    def _owner_article_cands(self, w: dict, via: str, depth: int = 2) -> list[dict]:
        return extract_ownership_sentences(w["text"], subject_names=[w["title"]], url=w["url"],
                                           source=f"Wikipedia: {w['title']}", own_article=True, conf="low",
                                           exclude=self.names, via=via, depth=depth)

    async def run_chain(self):
        """Second hop: for corporate owners/parents found so far, look for their own Wikipedia article and extract
        THEIR owners (depth 2). An article is only used if it mentions the subject (guards against same-name pages)."""
        if not self.cfg.get("chain_depth", 2) >= 2:
            return
        seen = set()
        targets = [c for c in self.cands if c["party_type"] == "entity" and c["role"] in ("intermediary", "parent", "owner")
                   and c["depth"] == 1]
        for c in targets[:6]:
            words = c["name"].split()
            ncore = max(1, len(split_legal_suffix(c["name"])[0].split()))
            core = " ".join(words[:ncore])
            nolegal = re.sub(r"\s+(?:Ltd\.?|LLC|Limited|Inc\.?|PLC|AG|GmbH|SA|S\.A\.|OJSC|CJSC|JSC|LLP|BV|NV)$", "", c["name"])
            generic = re.sub(r"\b(?:Financial|Finance|Investments?|International|Capital|Group)\b\s*", "", nolegal, flags=re.I).strip()
            for t in dict.fromkeys(x for x in (c["name"], nolegal, generic, core) if x and len(x) > 2):
                if self.left() < 5 or fold(t) in seen:
                    continue
                seen.add(fold(t))
                w = await self.wikipedia(t, own=False)
                if not w:
                    continue
                if not _mentions(fold(w["text"]), _subject_keys(self.names)):
                    self._log("Wikipedia (chain)", w["url"], "rejected", f"'{w['title']}' does not mention the subject")
                    continue
                self.texts.append((w["url"], "Wikipedia", w["text"]))
                found = self._owner_article_cands(w, via=c["name"])
                found += extract_parent_mentions(w["text"], subject_names=self.names, url=w["url"],
                                                 source=f"Wikipedia: {w['title']}")
                found += infobox_candidates({k: v for k, v in w["infobox"].items() if k in ("owner", "owners", "founder", "founders", "parent")},
                                            w["url"])
                for f in found:
                    if f["via"] is None and fold(f["name"]) != fold(w["title"]):
                        f["via"], f["depth"] = c["name"], 2
                self._log("Wikipedia (chain)", w["url"], "ok", f"owner article for '{c['name']}'", len(found))
                self.cands += found
                break

    # ---- official website
    def _pick_sites(self, sites: list[str]) -> list[str]:
        sites = [s for s in dict.fromkeys(sites) if s]
        if self.ids.get("website"):
            w = self.ids["website"]
            sites.insert(0, w if w.startswith("http") else "https://" + w)
        jur = fold(self.ids.get("jurisdiction") or "")
        tld = None
        for code, words in _geo.items():
            if jur and (jur == code.lower() or jur in words):
                tld = code.lower()
        if tld:
            sites.sort(key=lambda s: 0 if urlparse(s).hostname and urlparse(s).hostname.endswith("." + tld) else 1)
        return list(dict.fromkeys(sites))[:2]

    async def guess_sites(self) -> list[str]:
        """No website known: try <name>.<ccTLD of jurisdiction> and <name>.com, and accept a guess only if the
        home page itself names the subject (so a same-name domain is not silently used)."""
        core = split_legal_suffix(self.subject)[0].replace(" ", "")
        if not core or len(core) < 4:
            return []
        jur = fold(self.ids.get("jurisdiction") or "")
        tlds = [c.lower() for c, words in _geo.items() if jur and (jur == c.lower() or jur in words)]
        tlds = [{"gb": "co.uk"}.get(t, t) for t in tlds] + ["com"]
        out = []
        for t in dict.fromkeys(tlds):
            url = f"https://www.{core}.{t}/"
            r = await fetcher.fetch_html(self.c, url, timeout=6)
            if r["ok"]:
                lines, title, _ = html_lines(r["html"])
                if _mentions(fold(title + " " + " ".join(lines[:400])), _subject_keys(self.names)):
                    self._log("Company website", url, "guessed", "domain guessed from the name; home page names the subject")
                    out.append(url)
                    break
                self._log("Company website", url, "rejected", "guessed domain does not name the subject")
        return out

    async def run_website(self, sites: list[str]):
        sites = self._pick_sites(sites)
        if not sites:
            sites = await self.guess_sites()
        if not sites:
            self._log("Company website", None, "not available", "No website identifier, Wikipedia infobox or Wikidata P856")
            return
        maxp = int(self.cfg.get("max_pages", 10))
        for site in sites:
            host = (urlparse(site).hostname or "").removeprefix("www.")
            seen, queue, got, done_paths = set(), [(10, site)], 0, set()
            while queue and self.pages < maxp and self.left() > 6:
                queue.sort(key=lambda x: -x[0])
                _, url = queue.pop(0)
                norm = re.sub(r"^/[a-z]{2}/", "/", urlparse(url).path.rstrip("/"))
                if url in seen or (norm and norm in done_paths):
                    continue
                seen.add(url)
                r = await fetcher.fetch_html(self.c, url, timeout=8)
                if not r["ok"]:
                    self._log("Company website", url, "failed", r["note"])
                    continue
                self.pages += 1
                if url != site:
                    done_paths.add(norm)
                lines, title, links = html_lines(r["html"])
                kind = page_kind_of(r["final_url"], title)
                src = f"Company website ({host})"
                found = []
                if kind == "shareholders" or SHAREHOLDER_PAGE.search(title):
                    found += extract_shareholder_lines(lines, r["final_url"], src, float(self.cfg.get("ubo_threshold_pct", 25)))
                if kind in ("supervisory", "executive") or url != site:
                    found += extract_people_lines(lines, r["final_url"], kind, src, title)
                self.texts.append((r["final_url"], src, "\n".join(lines)))
                if found or url == site:
                    self._log("Company website", r["final_url"], "ok", f"{kind or 'page'}: {title[:80]}", len(found))
                got += len(found)
                self.cands += found
                for href, txt in links:
                    u = urljoin(r["final_url"], href).split("#")[0]
                    pu = urlparse(u)
                    if pu.scheme not in ("http", "https") or (pu.hostname or "").removeprefix("www.") != host or u in seen:
                        continue
                    if re.search(r"\.(pdf|jpg|png|zip|docx?|xlsx?)$", pu.path, re.I):
                        continue
                    score = max((sc for rx, sc in LINK_SCORES if rx.search(pu.path) or rx.search(txt)), default=0)
                    if score >= 3:
                        if kind:
                            score += 2  # links found on governance pages are the most likely siblings
                        m = re.match(r"^/([a-z]{2})/(.*)$", pu.path)
                        if m and m.group(1) != "en":
                            queue.append((score + 0.2, pu._replace(path=f"/en/{m.group(2)}").geturl()))
                        queue.append((score, u))
            if got:
                break

    # ---- news
    async def run_news(self, ctx_names: list[str]):
        from ..providers.bing_news import BROWSER_UA, unwrap_bing
        from ..providers.google_news import parse_rss_date, strip_tags
        import xml.etree.ElementTree as ET
        from urllib.parse import quote_plus
        n = ctx_names[0]
        qs = [f'"{n}" shareholders', f'"{n}" "owned by"', f'"{n}" stake', f'"{n}" CEO', f'"{n}" chairman', f'"{n}" board']
        items = []

        async def bing(q):
            try:
                r = await self.c.get(f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss&setlang=en-GB",
                                     headers={"User-Agent": BROWSER_UA}, timeout=10, follow_redirects=True)
                if "<rss" not in r.text[:500]:
                    return
                for it in ET.fromstring(r.text).iter("item"):
                    items.append({"url": unwrap_bing((it.findtext("link") or "").strip()), "title": it.findtext("title") or "",
                                  "snippet": strip_tags(it.findtext("description") or ""),
                                  "published": parse_rss_date(it.findtext("pubDate")), "via": "Bing News"})
            except Exception:
                pass

        async def google():
            q = f'"{n}" (shareholder OR shareholders OR "owned by" OR stake OR subsidiary OR CEO OR chairman OR board)'
            try:
                r = await self.c.get("https://news.google.com/rss/search", params={"q": q, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
                                     headers={"User-Agent": settings.user_agent}, timeout=10, follow_redirects=True)
                for it in ET.fromstring(r.text).iter("item"):
                    items.append({"url": (it.findtext("link") or "").strip(), "title": it.findtext("title") or "",
                                  "snippet": "", "published": parse_rss_date(it.findtext("pubDate")), "via": "Google News"})
            except Exception:
                pass
        await asyncio.gather(google(), *(bing(q) for q in qs))
        found = []
        seen = set()
        uniq = []
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            uniq.append(it)
            title = strip_tags(it["title"])
            if it["via"] == "Google News":
                title = re.sub(r"\s+[-–—]\s+[^-–—]{2,60}$", "", title)  # drop " - Publisher"
            txt = f"{title}. {it['snippet']}"
            src = f"{it['via']} result: {urlparse(it['url']).netloc.removeprefix('www.')}"
            found += extract_news_roles(txt, subject_names=self.names, url=it["url"], source=src, published=it["published"])
            found += extract_parent_mentions(txt, subject_names=self.names, url=it["url"], source=src, published=it["published"])
            self.texts.append((it["url"], src, txt))
        # fetch a few directly-linked (Bing) articles for full sentences
        arts = [u for u in uniq if u["via"] == "Bing News" and "bing.com" not in u["url"]][: int(self.cfg.get("max_news_articles", 8))]
        sem = asyncio.Semaphore(4)

        async def art(it):
            async with sem:
                if self.left() < 4:
                    return []
                r = await fetcher.fetch_article(self.c, it["url"], timeout=7)
                if not r.get("ok"):
                    return []
                src = f"News article: {urlparse(it['url']).netloc.removeprefix('www.')}"
                self.texts.append((it["url"], src, r["text"]))
                return (extract_news_roles(r["text"], subject_names=self.names, url=it["url"], source=src, published=it["published"])
                        + [c for c in extract_ownership_sentences(r["text"], subject_names=self.names, url=it["url"], source=src,
                                                                  own_article=False, published=it["published"])
                           if not c["partial_name"] and c["party_type"] != "individual" or is_person_name(c["name"])]
                        + extract_parent_mentions(r["text"], subject_names=self.names, url=it["url"], source=src, published=it["published"]))
        for res in await asyncio.gather(*(art(a) for a in arts)):
            found += res
        found = self._fix_headline_names(found)
        self._log("News (Google News / Bing News RSS)", None, "ok" if uniq else "no results",
                  f"{len(uniq)} ownership/management news results; {len(arts)} articles fetched", len(found))
        self.cands += found

    def _fix_headline_names(self, found: list[dict]) -> list[dict]:
        """Headlines Are Written In Title Case, so 'CEO Markus Braun Denies Charges' over-captures. For candidates
        whose evidence is a title-case sentence, keep only the longest 2+ token prefix of the name that also appears
        in ordinary (sentence-case) text we fetched; otherwise drop the candidate."""
        plain = " \n ".join(t for _, _, t in self.texts if not _titlecase(t[:300]))
        out = []
        for c in found:
            q = (c["evidence"][0].get("quote") if c.get("evidence") else "") or ""
            if c["party_type"] != "individual" or not _titlecase(q):
                out.append(c)
                continue
            toks = c["name"].split()
            keep = None
            for k in range(len(toks), 1, -1):
                cand = " ".join(toks[:k])
                if re.search(rf"\b{re.escape(cand)}\b", plain):
                    keep = cand
                    break
            if keep:
                c["name"] = keep
                out.append(c)
        return out

    # ---- Companies House (only when keyed)
    async def run_companies_house(self):
        from ..config import settings as st
        key = st.keys.get("companies_house")
        num = self.ids.get("registration_number") or self.ids.get("company_number")
        if not key or not num:
            return
        base = f"https://api.company-information.service.gov.uk/company/{quote(str(num))}"
        found = []
        try:
            for path, role in (("/officers?items_per_page=100", None), ("/persons-with-significant-control", "ubo")):
                r = await self.c.get(base + path, auth=(key, ""), timeout=10)
                if r.status_code >= 400:
                    self._log("Companies House", base + path, "failed", f"HTTP {r.status_code}")
                    continue
                for it in r.json().get("items", []):
                    if it.get("resigned_on") or it.get("ceased_on"):
                        continue
                    nm = it.get("name") or ""
                    if "," in nm:  # "SURNAME, Forename"
                        a, b = nm.split(",", 1)
                        nm = f"{b.strip()} {a.strip().title()}"
                    rl = role or ("director" if "director" in (it.get("officer_role") or "") else "executive")
                    nat = ", ".join(it.get("natures_of_control") or [])
                    found.append(_cand(nm, rl, url="https://find-and-update.company-information.service.gov.uk/company/" + str(num),
                                       source="Companies House", method="official register", quote_=f"{it.get('name')} — {it.get('officer_role') or nat}",
                                       conf="high", role_detail=(it.get("officer_role") or nat)[:200],
                                       ptype="entity" if "corporate" in (it.get("kind") or "") else "individual"))
            self._log("Companies House", base, "ok", None, len(found))
        except Exception as e:
            self._log("Companies House", base, "failed", type(e).__name__)
        self.cands += found

    async def run(self) -> dict:
        t0 = time.monotonic()
        sites_task = asyncio.create_task(self.run_wikipedia())
        news_task = asyncio.create_task(self.run_news(self.names))
        ch_task = asyncio.create_task(self.run_companies_house())
        try:
            sites = await asyncio.wait_for(sites_task, timeout=max(5, self.left() - 20))
        except Exception:
            sites = []
            self._log("Wikipedia/Wikidata", None, "timeout")
        try:
            await asyncio.wait_for(self.run_website(sites), timeout=max(5, self.left() - 8))
        except Exception:
            self._log("Company website", None, "timeout", "page budget/time exhausted")
        for t in (news_task, ch_task):
            try:
                await asyncio.wait_for(t, timeout=max(2, self.left()))
            except Exception:
                self._log("News/registry", None, "timeout")
        try:
            await asyncio.wait_for(self.run_chain(), timeout=max(3, self.left()))
        except Exception:
            self._log("Wikipedia (chain)", None, "timeout")
        if settings.llm_enabled and self.left() > 5:
            await self.run_llm()
        merged = merge(ground(self.cands, self.texts))
        return {"candidates": merged, "sources": self.sources, "elapsed_s": round(time.monotonic() - t0, 1),
                "manual_links": manual_links(self.subject, self.ids)}

    async def run_llm(self):
        from ..analysis import llm
        snippets = []
        for url, src, txt in self.texts:
            for s in _split_sentences(txt):
                if OWN_KW.search(s) or ROLE_RX.search(s):
                    snippets.append({"url": url, "source": src, "text": s[:400]})
        snippets = snippets[:40]
        if not snippets:
            return
        try:
            res = await llm.extract_related(self.c, self.subject, snippets)
        except Exception:
            return
        for r in res or []:
            i = r.get("i")
            if not isinstance(i, int) or not 0 <= i < len(snippets):
                continue
            sn = snippets[i]
            name, role = (r.get("name") or "").strip(), r.get("role") if r.get("role") in ROLES else "other"
            if not name or fold(name) not in fold(sn["text"]):
                continue  # grounding: the LLM's name must appear verbatim in the cited snippet
            self.cands.append(_cand(name, role, url=sn["url"], source=sn["source"], method="LLM extraction (verified verbatim)",
                                    quote_=sn["text"], conf="low", role_detail=(r.get("detail") or "")[:200],
                                    pct=_pct(str(r.get("pct"))) if r.get("pct") and str(r.get("pct")) in sn["text"] else None))


def ground(cands: list[dict], texts: list[tuple[str, str, str]]) -> list[dict]:
    """Drop any candidate whose name does not occur (folded) in fetched text — Wikidata labels are grounded by the
    entity JSON itself, family names by their surname."""
    corpus = {}
    for url, _, t in texts:
        corpus[url] = corpus.get(url, "") + " " + fold(t)
    out = []
    for c in cands:
        ev = c["evidence"][0]
        nm = fold(c["name"].replace(" family", "")) if c["party_type"] == "family" else fold(c["name"])
        if ev["source"] == "Wikidata" or ev["method"] == "official register":
            out.append(c)
            continue
        hay = corpus.get(ev["url"], "") + " " + fold(ev["quote"])
        if nm and re.search(rf"\b{re.escape(nm)}\b", hay):
            out.append(c)
    return out


def _key(name: str) -> str:
    core, _ = split_legal_suffix(name)
    return core or fold(name)


def merge(cands: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in cands:
        hit = None
        for o in out:
            a, b = _key(o["name"]), _key(c["name"])
            if a == b or (min(len(a), len(b)) > 5 and fuzz.token_sort_ratio(a, b) >= 92):
                hit = o
                break
        if not hit:
            out.append(dict(c, evidence=list(c["evidence"]), roles=[c["role"]]))
            continue
        hit["evidence"] += [e for e in c["evidence"] if (e["url"], e["quote"]) not in {(x["url"], x["quote"]) for x in hit["evidence"]}]
        if c["role"] not in hit["roles"]:
            hit["roles"].append(c["role"])
        if CONF_ORDER[c["confidence"]] > CONF_ORDER[hit["confidence"]]:
            for k in ("role", "role_detail", "party_type", "confidence"):
                hit[k] = c[k]
        if not hit.get("ownership_pct") and c.get("ownership_pct"):
            hit["ownership_pct"] = c["ownership_pct"]
        if hit["partial_name"] and not c["partial_name"]:
            hit["partial_name"], hit["name"] = False, c["name"]
        if c["depth"] < hit["depth"]:
            hit["depth"], hit["via"] = c["depth"], c["via"]
    for o in out:
        hosts = {(urlparse(e["url"]).hostname or "").removeprefix("www.") for e in o["evidence"]}
        if len(hosts) >= 2 and o["confidence"] != "high":
            o["confidence"] = {"low": "medium", "medium": "high"}[o["confidence"]]
            o["corroborated"] = True
        def _ev_rank(e):
            src = e.get("source") or ""
            return (0 if src.startswith(("Company website", "Companies House")) else 1 if src.startswith("Wiki")
                    else 2 if src.startswith("News article") else 3)
        o["evidence"] = sorted(o["evidence"], key=_ev_rank)[:6]
    prio = {"ubo": 0, "owner": 1, "intermediary": 2, "parent": 2, "shareholder": 3, "board_member": 4, "executive": 5,
            "director": 5, "founder": 6, "related_person": 7, "other": 8}
    out.sort(key=lambda o: (o["depth"], prio.get(o["role"], 9), -CONF_ORDER[o["confidence"]], o["name"]))
    return out[:60]


def manual_links(subject: str, ids: dict) -> list[dict]:
    q = quote(subject)
    out = [{"name": "OpenCorporates (manual search — automated access not permitted)", "url": f"https://opencorporates.com/companies?q={q}"},
           {"name": "OpenOwnership register (manual)", "url": f"https://register.openownership.org/search?q={q}"},
           {"name": "GLEIF LEI search (manual)", "url": f"https://search.gleif.org/#/search/simpleSearch={q}"}]
    jur = fold(ids.get("jurisdiction") or "")
    if jur in ("united kingdom", "uk", "gb", "england", "scotland", "wales"):
        out.insert(0, {"name": "Companies House (manual)", "url": f"https://find-and-update.company-information.service.gov.uk/search?q={q}"})
    return out


async def discover(client: httpx.AsyncClient, subject: str, aliases: list[str], identifiers: dict, policy: dict) -> dict:
    d = Discovery(client, subject, aliases, identifiers, policy)
    try:
        return await d.run()
    except Exception as e:  # never break the screening
        return {"candidates": merge(ground(d.cands, d.texts)), "sources": d.sources + [{"source": "discovery", "status": "error",
                "note": type(e).__name__}], "manual_links": manual_links(subject, identifiers)}
