"""Deterministic, explainable analysis rules: subject mentions, event status, implication, dates, quotes."""
import re
from datetime import date

from rapidfuzz import fuzz

from ..research.names import LEGAL_SUFFIXES, fold, split_legal_suffix, tokens
from .textutil import fold_map, orig_span, pattern_regex, sentences

# ---- event status phrase rules (folded-text patterns); order = precedence ----
STATUS_RULES: list[tuple[str, list[str]]] = [
    ("reversal", ["overturned", "quashed", "exonerated", "conviction was reversed", "conviction reversed", "cleared on appeal",
                  "wrongly convicted", "wrongful conviction", "verdict was reversed", "annulled the conviction"]),
    ("acquittal", [r"re:(?<!\w)found\s(?:\w+\s){1,6}?not\sguilty(?!\w)", "acquitted", "acquittal", "found not guilty", "not guilty verdict", "cleared of", "freigesprochen*", "acquitte*",
                   "absuelto*", "assolto*", "absolvido*", "vrijgesproken"]),
    ("dismissal", ["charges dropped", "dropped the charges", "dropped charges", "charges were dropped", "case dismissed",
                   "dismissed the case", "case was dismissed", "charges were dismissed", "dismissed the charges", "no further action",
                   "investigation closed", "closed the investigation", "closed its investigation", "case discontinued",
                   "discontinued the case", "proceedings discontinued", "charges withdrawn", "withdrew the charges", "withdrew all charges",
                   r"re:(?<!\w)(?:dropp|withdr)\w*\s(?:all\s)?(?:the\s)?(?:\w+\s){0,3}?(?:charges|case|prosecution)(?!\w)",
                   r"re:(?<!\w)(?:charges|case|prosecution)\s(?:\w+\s){0,5}?(?:was|were|has\sbeen|have\sbeen)\s(?:dropped|dismissed|discontinued|withdrawn)(?!\w)",
                   "eingestellt", "non lieu", "archiviat*", "sobresei*"]),
    ("conviction", ["convicted", "conviction", "found guilty", "pleaded guilty", "pled guilty", "pleads guilty", "plead guilty",
                    "guilty plea", "sentenced", "jailed", "imprisoned", "prison sentence", "years in prison", "years in jail",
                    "behind bars", "verurteilt", "condamne*", "condenado*", "condannat*", "veroordeeld"]),
    ("settlement", ["settled with", "settlement with", "agreed to settle", "settled charges", "agreed to pay", "without admitting",
                    "neither admitting", "deferred prosecution agreement", "consent order", "consent judgment"]),
    ("enforcement_action", ["fined", "fine of", "penalty of", "penalised", "penalized", "monetary penalty", "civil penalty",
                            "banned from", "censured", "final notice", "cease and desist", "disqualified", "disqualification order",
                            "disqualification undertaking", "licence revoked", "license revoked", "struck off", "prohibition order",
                            "ordered to pay", "asset freeze", "assets frozen", "sanctioned by", "geldbusse*", "geldstrafe*",
                            "amende*", "multa*", "sanzion*", "boete*"]),
    ("regulatory_finding", ["found to have breached", "breached the", "found that", "failings", "failed to comply", "findings against",
                            "the regulator found", "concluded that", "systemic failures", "serious failings"]),
    ("formal_charge", ["charged with", "charged over", "charged in", "been charged", "were charged", "charges against", "indicted",
                       "indictment", "faces charges", "facing charges", "prosecuted", "prosecution of", "stand trial", "on trial",
                       "trial of", "angeklagt", "anklage*", "inculpe*", "mis en examen", "imputad*", "rinviat* a giudizio",
                       "acusad*", "aangeklaagd"]),
    ("civil_regulatory_proceeding", ["sued", "lawsuit", "civil action", "civil suit", "complaint filed", "filed a complaint",
                                     "filed a lawsuit", "legal action", "class action", "proceedings against", "tribunal",
                                     "enforcement proceedings", "regulatory proceedings", "litigation release", "complaint against"]),
    ("investigation", ["investigat*", "probe", "probed", "probing", "inquiry", "enquiry", "raided", "raid on", "under scrutiny",
                       "arrested", "arrest of", "detained", "questioned by police", "searched the offices", "ermittl*",
                       "enquete*", "investigacion*", "indagin*", "indagat*", "onderzoek*"]),
    ("appeal", ["appealed", "appealing", "lodged an appeal", "on appeal", "appeal against", "court of appeal", "berufung", "revision"]),
    ("allegation", ["alleged*", "allegation*", "accused", "accusation*", "accuses", "claims that", "reportedly", "suspected",
                    "suspicion of", "whistleblower", "mutmasslich*", "presume*", "presunt*", "vermeend*"]),
]
STATUS_ORDER = [s for s, _ in STATUS_RULES]
STATUS_LABEL = {"allegation": "Allegation", "investigation": "Investigation", "formal_charge": "Formal charge",
                "civil_regulatory_proceeding": "Civil or regulatory proceeding", "regulatory_finding": "Regulatory finding",
                "enforcement_action": "Enforcement action", "conviction": "Conviction", "settlement": "Settlement",
                "acquittal": "Acquittal", "dismissal": "Dismissal", "appeal": "Appeal", "reversal": "Reversal / exoneration",
                "unknown": "Unknown"}
MITIGATING = {"reversal", "acquittal", "dismissal"}
_STATUS_RX = [(s, re.compile("|".join(p[3:] if p.startswith("re:") else pattern_regex(p) for p in pats))) for s, pats in STATUS_RULES]

# Roles that, when attached to the subject's mention, indicate a non-implicated appearance. Deliberately excludes
# office-holders (MP, minister, director, trustee, auditor...) because those people are frequently the accused.
BYSTANDER_ROLES = ["lawyer", "lawyers", "attorney", "solicitor", "barrister", "counsel", "defence counsel", "defense attorney",
                   "prosecutor", "prosecutors", "judge", "justice", "magistrate", "juror", "journalist", "reporter",
                   "correspondent", "editor", "columnist", "witness", "whistleblower", "whistle blower",
                   "spokesman", "spokeswoman", "spokesperson", "analyst", "professor", "lecturer", "academic", "commentator",
                   "expert", "investigator", "detective", "inspector", "police officer", "liquidator", "receiver",
                   "campaigner", "researcher"]
_ROLE = "(?:" + "|".join(pattern_regex(r) for r in BYSTANDER_ROLES) + ")"
_PRE = r"(?:\s(?:aged\s)?\d{1,3})?(?:\s(?:who\sis|who\swas|is|was|now))?"
# role immediately before the name ("journalist X", "Judge X", "fraud expert X")
ROLE_BEFORE_RX = re.compile(_ROLE + r"\s?$")
# appositive after the name ("X, 54, a financial crime expert"; "X gave evidence as a prosecution witness")
ROLE_AFTER_RX = re.compile(r"^" + _PRE + r"\s(?:a|an|the)(?:\s\w+){0,3}?\s" + _ROLE
                           + r"|^(?:\s\w+){0,8}?\sas\s(?:a|an|the)(?:\s\w+){0,2}?\s" + _ROLE)
# subject is the grammatical patient of an adverse act -> implicated, whatever their profession
IMPLICATED_AFTER_RX = re.compile(r"^(?:\s\w+){0,8}?\s(?:was|were|has\sbeen|had\sbeen|have\sbeen|is|is\sbeing|will\sbe|being)"
                                 r"(?:\s\w+){0,2}?\s(?:charged|convicted|jailed|arrested|sentenced|fined|banned|struck\soff|"
                                 r"disqualified|found\sguilty|accused|indicted|sued|investigated|sanctioned|suspended|censured|"
                                 r"prosecuted|imprisoned|detained|extradited|expelled)(?!\w)")
VICTIM_AFTER_RX = re.compile(r"^(?:\s\w+){0,8}?\s(?:was|were|became|is|has\sbeen|had\sbeen|fell)(?:\s\w+){0,3}?\s"
                             r"(?:victim|victims|defrauded|scammed|duped|swindled|targeted|conned|tricked|prey)(?!\w)"
                             r"|^(?:\s\w+){0,6}?\slost\s(?:\w+\s){0,2}?(?:money|savings|life\ssavings)")
VICTIM_BEFORE_RX = re.compile(r"(?:victim|victims)(?:\sof)?\s?$")
IMPERSONATION_RX = re.compile("|".join(pattern_regex(p) for p in ["impersonat*", "cloned firm", "clone firm",
                                                                    "fraudsters posing as", "scammers posing as"]))
_ROLE_RX = re.compile(_ROLE)  # kept for backwards compatibility


def subject_role(fs: str, m: dict) -> str | None:
    """Non-implicated role of the subject at this mention (or None). Pure function over folded sentence text."""
    before, after = fs[max(0, m["start"] - 40):m["start"]], fs[m["end"]:m["end"] + 90]
    if IMPLICATED_AFTER_RX.search(after):
        return None
    if VICTIM_AFTER_RX.search(after) or VICTIM_BEFORE_RX.search(before):
        return "victim"
    r = ROLE_BEFORE_RX.search(before) or ROLE_AFTER_RX.search(after)
    if r:
        return _ROLE_RX.search(r.group(0)).group(0)
    if IMPERSONATION_RX.search(fs):
        return "victim (impersonation)"
    return None


CONNECTED_RX = re.compile("|".join(pattern_regex(p) for p in [
    "former", "ex", "chief executive", "ceo", "cfo", "coo", "chief financial officer", "chief operating officer", "director of",
    "executive", "executives", "employee*", "manager*", "board member*", "founder", "co founder", "chairman", "subsidiary",
    "subsidiaries", "unit of", "affiliate", "partner of", "partners", "customer*", "client*", "supplier*", "auditor",
    "auditors", "owned by", "shareholder*", "investor*", "staff", "boss", "head of", "vorstand*", "chef"]))
YEAR_RX = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
DATE_RX = re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})\s+(19\d\d|20\d\d)\b|\b({MONTHS})\s+(\d{{1,2}}),?\s+(19\d\d|20\d\d)\b", re.I)


def name_patterns(subject_type: str, name: str, variants: list[dict]) -> list[tuple[str, str, re.Pattern]]:
    """(kind, label, regex) for each acceptable mention form, most specific first."""
    out = []
    seen = set()

    def add(kind, label, rx):
        if rx not in seen:
            seen.add(rx)
            out.append((kind, label, re.compile(rx)))

    def lit(f):
        return r"(?<!\w)" + re.escape(f).replace(r"\ ", " ") + r"(?!\w)"

    for v in variants:
        f = fold(v["value"])
        if not f:
            continue
        k = v["kind"]
        toks = f.split()
        if subject_type == "individual":
            if k in ("exact", "alias", "transliteration", "middle-name-dropped", "diacritics-folded") and len(toks) >= 2:
                add("exact", v["value"], lit(f))
                first, last = toks[0], toks[-1]
                add("exact_with_middle", v["value"], rf"(?<!\w){re.escape(first)}((?: \w{{1,15}}){{1,2}}) {re.escape(last)}(?!\w)")
            elif k in ("name-order-swapped", "surname-first"):
                add("variant", v["value"], lit(f))
        else:
            if k in ("exact", "legal-suffix-expanded", "ampersand-variant"):
                add("exact_legal", v["value"], lit(f))
            elif k in ("alias", "transliteration", "diacritics-folded"):
                add("exact", v["value"], lit(f))
            elif k == "legal-suffix-stripped":
                add("core", v["value"], lit(f))
    if subject_type == "individual":
        toks = [t for t in tokens(name)]
        if len(toks) >= 2:
            add("initial_surname", name, rf"(?<!\w){re.escape(toks[0][0])} {re.escape(toks[-1])}(?!\w)")
            add("surname_only", toks[-1], rf"(?<!\w){re.escape(toks[-1])}(?!\w)")
    else:
        core, _ = split_legal_suffix(name)
        if core:
            add("core", core, r"(?<!\w)" + re.escape(core).replace(r"\ ", " ") + r"(?!\w)")
    return out


def find_mentions(folded: str, pats) -> list[dict]:
    found = []
    taken: list[tuple[int, int]] = []
    for kind, label, rx in pats:
        for m in rx.finditer(folded):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            info = {"kind": kind, "start": m.start(), "end": m.end(), "text": m.group(0)}
            if kind == "exact_with_middle":
                info["middle"] = m.group(1).strip()
            found.append(info)
            taken.append((m.start(), m.end()))
    return found


def fuzzy_mention(folded: str, name: str, threshold: int = 90) -> dict | None:
    """Fallback fuzzy window match (spelling variants). Only used if no exact/variant mention."""
    nt = fold(name).split()
    words = folded.split()
    n = len(nt)
    if n == 0 or len(words) > 20000:
        return None
    best = None
    target = " ".join(nt)
    for i in range(0, max(0, len(words) - n + 1)):
        win = " ".join(words[i:i + n])
        if win[0] != target[0]:
            continue
        sc = fuzz.ratio(win, target)
        if sc >= threshold and (best is None or sc > best[0]):
            best = (sc, win)
    if best:
        return {"kind": "fuzzy", "text": best[1], "score": round(best[0], 1)}
    return None


def statuses_in(folded: str) -> list[tuple[str, str]]:
    out = []
    for s, rx in _STATUS_RX:
        m = rx.search(folded)
        if m:
            out.append((s, m.group(0)))
    return out


def primary_status(found: list[tuple[str, str]]) -> str:
    if not found:
        return "unknown"
    names = [s for s, _ in found]
    for s in STATUS_ORDER:
        if s in names:
            return s
    return "unknown"


def extract_dates(text: str) -> dict:
    years = sorted({int(y) for y in YEAR_RX.findall(text)})
    full = []
    for m in DATE_RX.finditer(text):
        full.append(m.group(0))
    return {"years": years[:20], "dates": full[:10]}


def analyse_text(text: str, title: str, subject_type: str, name: str, variants: list[dict], tax_cats_fn) -> dict:
    """Core rule-based pass over one document (title + snippet or article text).

    Returns mentions, subject sentences with categories/statuses, implication, quotes (verbatim, with offsets)."""
    full = (title or "").strip()
    body = (text or "").strip()
    doc = full + ("\n" + body if body and body != full else "")
    folded, mp = fold_map(doc)
    pats = name_patterns(subject_type, name, variants)
    mentions = find_mentions(folded, pats)
    strong = [m for m in mentions if m["kind"] not in ("surname_only", "initial_surname")]
    if not strong:
        fz = fuzzy_mention(folded, name)
        if fz:
            mentions.append(fz)
    sents = sentences(doc)
    subj_sents = []
    for (s, e, st) in sents:
        fs, _ = fold_map(st)
        sm = find_mentions(fs, pats)
        sm_strong = [m for m in sm if m["kind"] not in ("surname_only", "initial_surname")]
        cats = tax_cats_fn(fs)
        stats = statuses_in(fs)
        if sm:
            roles = [subject_role(fs, m) for m in sm]
            role = roles[0] if roles and all(roles) else None
            connected = bool(CONNECTED_RX.search(fs[max(0, sm[0]["start"] - 40):sm[0]["end"] + 40])) if subject_type == "entity" else False
            by_line = bool(re.match(r"^by\s", fs)) and len(fs) < 80
            subj_sents.append({"start": s, "end": e, "text": st, "mentions": sm, "strong": bool(sm_strong),
                               "categories": [c["id"] for c in cats], "cat_terms": {c["id"]: c["hits"][0][2] for c in cats},
                               "statuses": stats, "role": "journalist (byline)" if by_line else role,
                               "connected": connected})
    risk_sents = [x for x in subj_sents if x["categories"] or x["statuses"]]
    # implication
    if not mentions:
        implication = "not_mentioned"
    elif not risk_sents:
        implication = "mentioned_no_conduct"
    elif all(x["role"] for x in risk_sents):
        implication = "bystander"
    else:
        implication = "direct"
    party = "direct"
    if subject_type == "entity" and risk_sents and all(x["connected"] for x in risk_sents if not x["role"]):
        party = "connected"
    # quotes: verbatim sentences (original casing) that mention the subject and a risk term
    quotes = []
    for x in sorted(risk_sents, key=lambda r: (-len(r["categories"]) - len(r["statuses"]), r["start"]))[:3]:
        q = x["text"]
        start = x["start"]
        if len(q) > 320:
            q = q[:317].rsplit(" ", 1)[0] + "…"
        quotes.append({"text": q, "offset": start, "length": len(q.rstrip("…"))})
    # excerpt: subject sentences first, up to the cap
    return {"doc": doc, "folded": folded, "mentions": mentions, "subject_sentences": subj_sents, "risk_sentences": risk_sents,
            "implication": implication, "party": party, "quotes": quotes}


def build_excerpt(analysis: dict, cap: int = 1200) -> str:
    parts, n = [], 0
    for x in analysis["subject_sentences"]:
        t = x["text"]
        if n + len(t) + 1 > cap:
            break
        parts.append(t)
        n += len(t) + 1
    if not parts:
        parts = [analysis["doc"][:cap]]
    return " … ".join(parts)[:cap]


def temporal(pub: str | None, event_years: list[int], historical_years: int, today: date | None = None) -> dict:
    today = today or date.today()
    pub_year = int(pub[:4]) if pub and pub[:4].isdigit() else None
    ref = pub_year
    if event_years and pub_year:
        older = [y for y in event_years if y <= pub_year]
        ref = max(older) if older else pub_year
    age = (today.year - ref) if ref else None
    label = "unknown"
    if age is not None:
        label = "historical" if age > historical_years else "current"
    return {"publication_year": pub_year, "reference_year": ref, "age_years": age, "label": label,
            "reported_later": bool(pub_year and event_years and min(event_years) < pub_year - 2)}
