"""v2 features: related-party extraction (grounded, no hallucination), look-back window, consolidated summary,
related-parties API (manual add, edit, one-click linked child screening, audit), provider set."""
from conftest import login, wait_done, ADMIN_PW  # noqa: F401

from app import scoring, summary
from app.providers.registry import active_providers, provider_catalog
from app.research import related as rel

# Fictional subject / people — extraction must work from page structure, never from hard-coded names.
SITE = """<html><head><title>Corporate governance | Zorvath Bank</title></head><body>
<nav><a href="/en/about/management">Management board</a></nav>
<h1>Supervisory Board</h1>
<div><p>Teodor Valkrin</p><p>Chairman of the Supervisory Board</p></div>
<div><p>Mirela Ostrovska</p><p>Member of the Supervisory Board</p></div>
<h2>Shareholders</h2>
<ul><li>Kestrel Holding Ltd</li><li>61.20%</li><li>Ardent Ventures LLC</li><li>27.50%</li>
<li>Teodor Valkrin</li><li>11.30%</li></ul>
<footer>Copyright</footer></body></html>"""


def test_website_people_and_shareholders_extracted_with_evidence():
    lines, title, _ = rel.html_lines(SITE)
    url = "https://zorvath.example/en/governance"
    people = rel.extract_people_lines(lines, url, rel.page_kind_of(url, title), "Company website", title)
    names = {c["name"]: c for c in people}
    assert {"Teodor Valkrin", "Mirela Ostrovska"} <= set(names)
    assert names["Teodor Valkrin"]["role"] == "board_member" and names["Teodor Valkrin"]["confidence"] == "high"
    assert names["Teodor Valkrin"]["evidence"][0]["url"] == url
    sh = {c["name"]: c for c in rel.extract_shareholder_lines(lines, url, "Company website", 25)}
    assert sh["Kestrel Holding Ltd"]["role"] == "intermediary" and sh["Kestrel Holding Ltd"]["ownership_pct"] == "61.2"
    assert sh["Ardent Ventures LLC"]["party_type"] == "entity"
    assert sh["Teodor Valkrin"]["role"] == "shareholder"      # 11.3% < 25% UBO threshold
    # headings are never paired as roles
    assert "Supervisory Board" not in names and "Shareholders" not in sh


def test_ownership_sentences_skip_holdings_and_speculation():
    text = ("Zorvath Bank is majority owned by Kestrel Holding Ltd. "
            "Zorvath Bank owns a 40% stake in Brightwater Insurance. "
            "Analysts said Pemberton Capital could become a shareholder in Zorvath Bank.")
    c = rel.extract_ownership_sentences(text, subject_names=["Zorvath Bank"], url="https://news.example/a", source="News",
                                        own_article=False) + \
        rel.extract_parent_mentions(text, subject_names=["Zorvath Bank"], url="https://news.example/a", source="News")
    names = {x["name"] for x in c}
    assert "Kestrel Holding Ltd" in names
    assert "Brightwater Insurance" not in names     # a holding OF the subject, not an owner
    assert "Pemberton Capital" not in names         # speculative
    assert all(x["evidence"][0]["quote"] for x in c)


def test_news_roles_and_headline_case():
    t = "Zorvath Bank chief executive Arlen Dumitrescu said results improved. Become Zorvath Bank CEO Today"
    c = rel.extract_news_roles(t, subject_names=["Zorvath Bank"], url="https://news.example/b", source="News article")
    names = {x["name"] for x in c}
    assert "Arlen Dumitrescu" in names and not any(n.startswith("Become") for n in names)


def test_grounding_drops_names_not_in_fetched_text():
    good = rel._cand("Teodor Valkrin", "board_member", url="u1", source="LLM", method="llm", quote_="x", conf="low")
    bad = rel._cand("Invented Person", "board_member", url="u1", source="LLM", method="llm", quote_="x", conf="low")
    out = rel.ground([good, bad], [("u1", "t", "Teodor Valkrin chairs the board")])
    assert [c["name"] for c in out] == ["Teodor Valkrin"]


def test_infobox_continuations_merged():
    ib = {"key people": ["Hanna Lindqvist", "(Chairwoman)", "Pavel Orsini", ", CEO"], "owner": ["Kestrel Holding Ltd (61%)"]}
    c = {x["name"]: x for x in rel.infobox_candidates(ib, "https://en.wikipedia.org/wiki/Zorvath")}
    assert c["Hanna Lindqvist"]["role"] == "board_member" and c["Pavel Orsini"]["role"] == "executive"
    assert c["Kestrel Holding Ltd"]["role"] == "intermediary"


def test_merge_dedupes_and_ranks_evidence():
    a = rel._cand("Teodor Valkrin", "board_member", url="n", source="News article", method="m", quote_="q", conf="low")
    b = rel._cand("Teodor Valkrin", "board_member", url="w", source="Company website", method="m", quote_="q", conf="high")
    m = rel.merge([a, b])
    assert len(m) == 1 and m[0]["confidence"] == "high" and m[0]["evidence"][0]["source"] == "Company website"


def test_only_google_and_bing_media_by_default():
    ids = {p.id for p in active_providers()}
    assert {"google_news", "bing_news"} <= ids
    assert not ids & {"gdelt", "newsapi", "gnews", "brave", "serper", "bing_web", "courtlistener"}
    assert "companies_house" not in ids   # no key in tests
    assert all(p["enabled"] for p in provider_catalog())   # never list disabled / no-key rows


def test_outside_window_bucket():
    f = {"published_at": "2014-05-01", "bucket": "review", "material": True, "relevant": True}
    assert scoring.outside_window(f, "2021-11-01") == "2014"
    assert scoring.outside_window({"published_at": "2024-01-01"}, "2021-11-01") is None
    assert scoring.outside_window({"published_at": None}, "2021-11-01") is None


def test_summary_llm_verifier_rejects_uncited_or_new_numbers():
    payload = {"facts": [{"n": 1, "text": "Fined 5 million in 2023"}], "paragraphs": ["x"]}
    assert summary.verify_llm("The subject was fined 5 million in 2023 [1].", payload)
    assert not summary.verify_llm("The subject was fined 9 million [1].", payload)
    assert not summary.verify_llm("The subject was fined.", payload)


# ---------------------------------------------------------------- API
HQB = {"subject_type": "individual", "name": "Halvard Quennell-Broome", "identifiers": {"dob": "1971-03-14"}}


def _screen(s, body):
    r = s.post("/api/screenings", json=body)
    assert r.status_code == 200, r.text
    return wait_done(s, r.json()["id"])


def test_related_party_manual_add_screen_and_link(admin):
    parent = _screen(admin, HQB | {"test_fixture_set": "clean_individual"})
    sid = parent["id"]
    assert parent["related_parties"] == [] and parent["related_summary"]["highest"] is None
    r = admin.post(f"/api/screenings/{sid}/related-parties", json={"name": "Quennell Holdings Ltd", "party_type": "entity",
                                                                    "role": "shareholder", "ownership_pct": "40%"})
    assert r.status_code == 200, r.text
    ent = r.json()
    assert ent["confidence"] == "manual" and ent["ownership_pct"] == "40"
    assert admin.post(f"/api/screenings/{sid}/related-parties", json={"name": "X Y", "role": "nonsense"}).status_code == 422
    assert admin.post(f"/api/screenings/{sid}/related-parties", json={"name": "X Y", "ownership_pct": "140"}).status_code == 422
    p = admin.post(f"/api/screenings/{sid}/related-parties", json={"name": "Mirela", "role": "director"}).json()
    assert admin.post(f"/api/related-parties/{p['id']}/screen", json={}).status_code == 409   # single token name
    assert admin.patch(f"/api/related-parties/{p['id']}", json={"name": "Mirela Ostrovska"}).status_code == 200
    r = admin.post(f"/api/related-parties/{p['id']}/screen", json={"test_fixture_set": "mixed_individual"})
    assert r.status_code == 200, r.text
    child = wait_done(admin, r.json()["id"])
    assert child["parent"]["screening_id"] == sid and child["subject_type"] == "individual"
    assert child["identifiers"]["associated_entities"] == [parent["subject_name"]]
    d = admin.get(f"/api/screenings/{sid}").json()
    row = next(x for x in d["related_parties"] if x["id"] == p["id"])
    assert row["child"]["id"] == child["id"] and row["child"]["final_status"] == child["final_status"]
    rs = d["related_summary"]
    assert rs["highest"] == child["final_status"] and d["final_status"] == "GREEN"   # subject RAG kept separate
    if child["final_status"] != "GREEN":
        assert rs["hits"] and "related-party" in rs["overall_note"]
    lst = admin.get(f"/api/screenings/{sid}/related-parties").json()
    assert len(lst["items"]) == 2
    acts = [a["action"] for a in admin.get("/api/audit", params={"screening_id": sid}).json()["items"]]
    assert {"related_party.added", "related_party.updated", "related_party.screened"} <= set(acts)
    # PDF includes the related-party section
    pdf = admin.get(f"/api/screenings/{sid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_related_party_rbac(client, admin):
    parent = _screen(admin, HQB | {"test_fixture_set": "clean_individual"})
    admin.post("/api/admin/users", json={"username": "ro_rp", "password": "Str0ng-Passw0rd-123!", "role": "readonly"})
    ro = login(client, "ro_rp", "Str0ng-Passw0rd-123!")
    assert ro.post(f"/api/screenings/{parent['id']}/related-parties", json={"name": "A B"}).status_code == 403
    assert ro.get(f"/api/screenings/{parent['id']}/related-parties").status_code == 200


def test_shareholder_list_percent_first_layout():
    lines = ["Shareholders", "≈60,10%", "Kestrel Holding Ltd", "≈25,40%", "Ardent Ventures LLC", "≈9.5%", "Teodor Valkrin",
             "5%", "Other shareholders holding shares in free float on the exchange"]
    sh = {c["name"]: c["ownership_pct"] for c in rel.extract_shareholder_lines(lines, "u", "Company website", 25)}
    assert sh == {"Kestrel Holding Ltd": "60.1", "Ardent Ventures LLC": "25.4", "Teodor Valkrin": "9.5"}
