"""Explainable identity resolution: an additive evidence-points model with contradictions.

Every point awarded or deducted is recorded with the evidence type, the matched text and the rule, so an
analyst can see exactly why a finding was rated Confirmed / Probable / Possible / Unlikely / Contradicted.
A name-only match can NEVER exceed 'Possible'."""
import json
import re
from datetime import date

from ..config import DATA_DIR
from ..research.names import fold, is_common_name, legal_form, split_legal_suffix, FORM_FAMILY
from .textutil import fold_map

GEO = {k: [fold(x) for x in v] for k, v in json.loads((DATA_DIR / "geo.json").read_text(encoding="utf-8")).items()}
_ALIAS2CC = {a: k for k, v in GEO.items() for a in v}
LEVELS = ["contradicted", "unlikely", "possible", "probable", "confirmed"]
LEVEL_LABEL = {"confirmed": "Confirmed — strong", "probable": "Probable", "possible": "Possible — needs review",
               "unlikely": "Unlikely", "contradicted": "Contradicted"}
LEVEL_RANK = {"contradicted": 0, "unlikely": 1, "possible": 2, "probable": 3, "confirmed": 4}
UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
CO_NUM_CTX = re.compile(r"(?:company|registration|registered|reg\.?|companies house|handelsregister|hrb|crn|number|no\.?|nr\.?)\s*(?:number|no\.?|nr\.?)?\s*[:#]?\s*([A-Z]{0,3}\s?\d{5,9})", re.I)


def country_code(s: str | None) -> str | None:
    if not s:
        return None
    f = fold(s)
    if len(f) == 2 and f.upper() in GEO:
        return f.upper()
    return _ALIAS2CC.get(f)


def _geo_hits(folded: str) -> dict[str, str]:
    hits = {}
    for cc, names in GEO.items():
        for n in names:
            if len(n) <= 2:
                continue  # 'us'/'uk' too ambiguous in folded text except explicit forms
            if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", folded):
                hits[cc] = n
                break
    if re.search(r"(?<!\w)u k(?!\w)|(?<!\w)uk(?!\w)", folded):
        hits.setdefault("GB", "uk")
    return hits


def _dob(identifiers: dict) -> tuple[int | None, date | None]:
    v = identifiers.get("dob") or identifiers.get("year_of_birth")
    d = str(v).strip() if v else ""
    if not d:
        return None, None
    m = re.match(r"^(\d{4})(?:-(\d{2})-(\d{2}))?$", d)
    if not m:
        return None, None
    y = int(m.group(1))
    full = date(y, int(m.group(2)), int(m.group(3))) if m.group(2) else None
    return y, full


def _ages_near(folded: str, mention_spans: list[tuple[int, int]]) -> list[tuple[int, str]]:
    out = []
    for s, e in mention_spans:
        window = folded[e:e + 60]
        pre = folded[max(0, s - 40):s]
        for m in re.finditer(r"^\s(\d{2})\s|^\s+aged (\d{2})|^\s+\w*\s*\((\d{2})\)", window):
            v = next(g for g in m.groups() if g)
            out.append((int(v), m.group(0).strip()))
        for m in re.finditer(r"(\d{2}) year old\s*(?:\w+\s){0,3}$", pre):
            out.append((int(m.group(1)), m.group(0).strip()))
        for m in re.finditer(r"aged (\d{2})", window[:40]):
            out.append((int(m.group(1)), m.group(0)))
        # obituary / death-age phrasing close to the name: "X, ..., dies at 82", "X, who died aged 82"
        for m in re.finditer(r"(?:dies|died|is dead|dead|death) (?:at|aged) (?:the age of )?(\d{2})(?!\d)", folded[e:e + 90]):
            out.append((int(m.group(1)), m.group(0)))
    return [(a, t) for a, t in out if 16 <= a <= 105]


def _births_near(folded: str, mention_spans) -> list[tuple[int, str]]:
    out = []
    for s, e in mention_spans:
        w = folded[max(0, s - 60):e + 80]
        for m in re.finditer(r"(?:born|b|nee|geboren|ne|nacido|nato)\s(?:in\s|on\s)?(?:\d{1,2}\s\w+\s)?(19\d\d|20[0-1]\d)", w):
            out.append((int(m.group(1)), m.group(0)))
    return out


def score_identity(subject_type: str, name: str, identifiers: dict, analysis: dict, pub: str | None, policy: dict,
                   official_extra: dict | None = None) -> dict:
    W = policy["identity_weights"]
    L = policy["identity_levels"]
    folded = analysis["folded"]
    mentions = analysis["mentions"]
    ev: list[dict] = []
    contra: list[dict] = []
    corroborating: set[str] = set()
    strong_types: set[str] = set()

    def add(kind, pts, detail, text=None, corroborates=None, strong=False):
        ev.append({"type": kind, "points": pts, "detail": detail, "matched": text})
        if corroborates:
            corroborating.add(corroborates)
            if strong:
                strong_types.add(corroborates)

    def contradict(kind, pts, detail, text=None, strong=False):
        contra.append({"type": kind, "points": pts, "detail": detail, "matched": text, "strong": strong})

    kinds = {m["kind"] for m in mentions}
    spans = [(m["start"], m["end"]) for m in mentions if "start" in m]
    # ---- name evidence (exactly one name rule applies; best wins) ----
    if subject_type == "entity":
        if "exact_legal" in kinds:
            add("name", W["name_exact_entity"], "Exact legal name (incl. suffix) found", next(m["text"] for m in mentions if m["kind"] == "exact_legal"))
            add("legal_suffix", W["suffix_match"], "Legal suffix matches supplied name")
        elif "exact" in kinds:
            add("name", W["alias_exact"], "Exact alias / trading name found", next(m["text"] for m in mentions if m["kind"] == "exact"))
        elif "core" in kinds:
            add("name", W["name_exact"], "Name found without legal suffix", next(m["text"] for m in mentions if m["kind"] == "core"))
        elif "fuzzy" in kinds:
            m = next(m for m in mentions if m["kind"] == "fuzzy")
            add("name", W["name_fuzzy"], f"Fuzzy name match (score {m['score']})", m["text"])
        # legal form contradiction: core name followed by a different legal-form token
        sup_form = legal_form(name)
        core, _ = split_legal_suffix(name)
        if sup_form and core:
            for m in re.finditer(rf"(?<!\w){re.escape(core)} (\w+)(?: (\w+))?", folded):
                for tok in (m.group(1), m.group(2)):
                    fam = FORM_FAMILY.get(tok or "")
                    if fam and fam != sup_form:
                        contradict("legal_form", W["contra_legal_form"], f"Text refers to '{core} {tok}' (different legal form)", m.group(0))
                        break
                if contra and contra[-1]["type"] == "legal_form":
                    break
    else:
        if "exact" in kinds:
            add("name", W["name_exact"], "Exact full name found", next(m["text"] for m in mentions if m["kind"] == "exact"))
        elif "exact_with_middle" in kinds:
            m = next(m for m in mentions if m["kind"] == "exact_with_middle")
            add("name", W["name_fuzzy"], "First and last name found with middle name/initial", m["text"])
        elif "variant" in kinds or "fuzzy" in kinds:
            m = next(m for m in mentions if m["kind"] in ("variant", "fuzzy"))
            add("name", W["name_fuzzy"], "Name variant / fuzzy match" + (f" (score {m.get('score')})" if m.get("score") else ""), m["text"])
        elif kinds & {"initial_surname", "surname_only"}:
            m = next(m for m in mentions if m["kind"] in ("initial_surname", "surname_only"))
            add("name", W["name_partial"], "Partial name only (surname / initial)", m["text"])
        # middle-name contradiction
        sup_toks = fold(name).split()
        sup_mid = sup_toks[1:-1]
        for m in mentions:
            if m["kind"] == "exact_with_middle" and sup_mid:
                txt_mid = m["middle"].split()
                if txt_mid and txt_mid[0][0] != sup_mid[0][0]:
                    contradict("middle_name", W["contra_middle_name"], f"Text middle name '{m['middle']}' differs from supplied", m["text"])
                    break
        # DOB / age
        yob, dob = _dob(identifiers)
        if yob:
            births = _births_near(folded, spans)
            ages = _ages_near(folded, spans)
            pub_year = int(pub[:4]) if pub and pub[:4].isdigit() else None
            matched = False
            for by, txt in births:
                if by == yob:
                    add("dob", W["birth_year_match"], f"Birth year {by} matches", txt, "dob", True)
                    matched = True
                    break
                contradict("dob", W["contra_age"], f"Birth year {by} stated; supplied {yob}", txt, True)
                break
            if not matched and ages and pub_year:
                a, txt = ages[0]
                expected = pub_year - yob
                if abs(a - expected) <= 1 or (dob and abs(a - (expected - 1)) <= 1):
                    add("age", W["age_consistent"], f"Age {a} consistent with DOB at publication ({pub_year})", txt, "dob", True)
                else:
                    contradict("age", W["contra_age"], f"Age {a} stated in {pub_year}; supplied DOB implies ~{expected}", txt, True)
        if official_extra and official_extra.get("date_of_birth") and yob:
            ody = official_extra["date_of_birth"].get("year") if isinstance(official_extra["date_of_birth"], dict) else None
            if ody == yob:
                add("dob", W["birth_year_match"], f"Official register birth year {ody} matches", str(ody), "dob", True)
            elif ody:
                contradict("dob", W["contra_age"], f"Official register birth year {ody} differs from supplied {yob}", str(ody), True)

    # ---- country ----
    sup_cc = []
    for k in ("nationality", "country_of_residence", "country_of_birth", "jurisdiction", "country"):
        v = identifiers.get(k)
        for x in (v if isinstance(v, list) else [v]):
            cc = country_code(x) if x else None
            if cc and cc not in sup_cc:
                sup_cc.append(cc)
    if sup_cc:
        hits = _geo_hits(folded)
        pts = 0
        for cc in sup_cc:
            if cc in hits and pts < W["country_cap"]:
                add("country", W["country_match"], f"Supplied country {cc} referenced", hits[cc], "country")
                pts += W["country_match"]
        if hits and not any(cc in hits for cc in sup_cc) and len(hits) <= 2:
            contradict("geography", W["contra_geography"], f"Text locates subject in {', '.join(hits)} only; supplied {', '.join(sup_cc)}",
                       ", ".join(hits.values()))
    # ---- associates (directors / associated people / entities / employer / parent) ----
    assoc = []
    for k in ("directors", "associated_people", "associated_entities", "employer", "parent_company", "ubos"):
        v = identifiers.get(k)
        assoc += [x for x in (v if isinstance(v, list) else [v]) if x]
    apts = 0
    for a in assoc:
        fa = fold(a)
        toks = fa.split()
        if len(fa) < 4:
            continue
        found = re.search(rf"(?<!\w){re.escape(fa)}(?!\w)", folded)
        if not found and len(toks) >= 2:
            found = re.search(rf"(?<!\w){re.escape(toks[0])}(?: \w+)? {re.escape(toks[-1])}(?!\w)", folded)
        if found and apts < W["associate_cap"]:
            add("associate", W["associate_match"], f"Known associate '{a}' mentioned", found.group(0), "associate")
            apts += W["associate_match"]
    # ---- occupation ----
    occ = identifiers.get("occupation")
    if occ and fold(occ) and re.search(rf"(?<!\w){re.escape(fold(occ))}(?!\w)", folded):
        add("occupation", 10, f"Occupation '{occ}' mentioned", fold(occ), "occupation")
    # ---- entity registration number / address ----
    reg = re.sub(r"\s", "", (identifiers.get("registration_number") or "")).upper()
    if reg:
        raw = analysis["doc"].upper().replace(" ", "")
        if len(reg) >= 5 and reg in raw:
            add("reg_number", W["reg_number_match"], f"Registration number {reg} found", reg, "reg_number", True)
        else:
            for m in CO_NUM_CTX.finditer(analysis["doc"]):
                other = re.sub(r"\s", "", m.group(1)).upper()
                if other and other != reg and other.lstrip("0") != reg.lstrip("0"):
                    contradict("reg_number", W["contra_reg_number"], f"Different registration number {other} stated", m.group(0), True)
                    break
    addr = identifiers.get("address") or identifiers.get("registered_address")
    if addr:
        pc = UK_POSTCODE.search(addr)
        if pc:
            pcs = (pc.group(1) + pc.group(2)).upper()
            if pcs in analysis["doc"].upper().replace(" ", ""):
                add("address", W["address_match"], f"Postcode {pc.group(0).upper()} found", pc.group(0).upper(), "address", True)
        else:
            street = fold(addr.split(",")[0])
            if len(street) >= 8 and street in folded:
                add("address", W["address_match"], "Address line found", street, "address", True)

    common = subject_type == "individual" and is_common_name(name)
    if common:
        add("common_name", W["common_name_penalty"], "Very common name — stricter threshold applied")
    total = sum(e["points"] for e in ev) + sum(c["points"] for c in contra)
    has_name = any(e["type"] == "name" for e in ev)
    partial_only = has_name and all(e["points"] <= W["name_partial"] for e in ev if e["type"] == "name")
    strong_contra = any(c["strong"] for c in contra)
    if not has_name:
        level = "unlikely"
        reason = "Subject name not found in accessible text"
    elif strong_contra or (contra and total < L["possible_min"]):
        level = "contradicted"
        reason = "Identifier contradiction: " + "; ".join(c["detail"] for c in contra)
    elif total >= L["confirmed_min"] and len(corroborating) >= 2 and strong_types and not contra:
        level = "confirmed"
        reason = f"{total} points with corroborating identifiers ({', '.join(sorted(corroborating))})"
    elif total >= L["probable_min"] and corroborating:
        level = "probable"
        reason = f"{total} points; corroborated by {', '.join(sorted(corroborating))}"
    elif partial_only or (common and not corroborating):
        level = "unlikely"
        reason = ("Partial name only" if partial_only else "Very common name with no corroborating identifier")
    elif total >= L["possible_min"] or has_name:
        level = "possible"
        reason = "Name match only — no corroborating identifier" if not corroborating else f"{total} points — below Probable threshold"
    else:
        level = "unlikely"
        reason = f"{total} points"
    return {"level": level, "label": LEVEL_LABEL[level], "points": total, "reason": reason, "evidence": ev,
            "contradictions": contra, "corroborating": sorted(corroborating), "common_name": common}
