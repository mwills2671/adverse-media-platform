"""Tests 1-10 (offline part): labelled synthetic cases through the real analysis & scoring code."""
import json

import pytest

from app.analysis import llm
from labelled_harness import CASES, check, evaluate, run_all

CASE_LIST = json.loads(CASES.read_text())["cases"]
KNOWN_GAPS = {"id09"}  # documented in docs/TEST_REPORT.md: name + associate only reaches "possible" (45 < 50 points)


@pytest.mark.parametrize("case", CASE_LIST, ids=[c["id"] for c in CASE_LIST])
def test_labelled_case(case):
    f = evaluate(case)
    fails = check(case, f)
    if case["id"] in KNOWN_GAPS:
        pytest.xfail("; ".join(fails) or "known gap")
    assert not fails, fails


def test_pass_rate_threshold():
    ok, n, cok, cn, _, _ = run_all(verbose=False)
    assert n >= 60
    assert ok / n >= 0.95 and cok / cn >= 0.95


def test_name_only_never_above_possible():
    for c in CASE_LIST:
        if not c["identifiers"]:
            assert evaluate(c)["identity"]["level"] in ("contradicted", "unlikely", "possible"), c["id"]


def test_material_requires_probable_identity():
    for c in CASE_LIST:
        f = evaluate(c)
        if f["material"]:
            assert f["identity"]["level"] in ("probable", "confirmed"), c["id"]
            assert all(r["ok"] for r in f["material_reasons"]), c["id"]


def test_mitigated_never_material():
    for c in CASE_LIST:
        f = evaluate(c)
        if f["bucket"] == "mitigating":
            assert not f["material"], c["id"]


def test_fixture_tier_only_for_example_domains():
    from app.engine import tier_of
    from app.providers.base import RawItem
    real = RawItem(url="https://randomblog.com/x", title="t", provider="p", source_domain="randomblog.com", extra={"fixture_tier": 1})
    fake = RawItem(url="https://a.fixture.example/x", title="t", provider="p", source_domain="a.fixture.example", extra={"fixture_tier": 1})
    assert tier_of(fake)[0] == 1
    assert tier_of(real)[0] != 1  # a real domain can never self-declare a tier


# ---- test 14 (offline part): LLM verifier rejects hallucinated quotes / taxonomy / unsupported relevance ----
def test_llm_verifier_rejects_ungrounded_output():
    excerpt = "Halvard Quennell-Broome was convicted of fraud at Southwark Crown Court."
    out = {"quotes": ["was convicted of fraud", "admitted to laundering billions"], "categories": ["fraud", "made_up"],
           "event_status": "super_guilty", "implication": "direct", "relevant": True, "summary": "x"}
    clean, problems = llm.verify(out, excerpt, {"fraud"})
    assert clean["quotes"] == ["was convicted of fraud"]
    assert clean["categories"] == ["fraud"]
    assert clean["event_status"] == "unknown"
    assert clean["grounded"]
    clean2, p2 = llm.verify({"quotes": ["invented"], "relevant": True}, excerpt, {"fraud"})
    assert not clean2["grounded"] and any("relevance claimed" in p for p in p2)


def test_obituary_age_counts_as_dob_evidence():
    """Death-age phrasing near the name is age evidence (added after live Madoff run, 2026-10-31)."""
    from app.analysis.identity import _ages_near
    from app.research.names import fold
    t = fold("Halvard Quennell-Broome, disgraced fund manager, dies at 55")
    i = t.find("broome") + len("broome")
    assert _ages_near(t, [(0, i)]) == [(55, "dies at 55")]
