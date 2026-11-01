"""Run the labelled synthetic cases through the real (pure) analysis + scoring code and compare with labels."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import scoring  # noqa: E402
from app.analysis.identity import LEVEL_RANK  # noqa: E402
from app.engine import analyse_cluster, variants_for  # noqa: E402
from app.providers.base import RawItem  # noqa: E402
from app.settings_store import default  # noqa: E402

CASES = Path(__file__).parent / "labelled" / "cases.json"
TODAY = date(2026, 10, 31)


def evaluate(case, policy=None, taxonomy=None):
    policy = policy or default("policy")
    taxonomy = taxonomy or default("taxonomy")
    it = case["item"]
    raw = RawItem(url=it["url"], title=it["title"], provider="test_fixtures", source_name=it["source_name"],
                  source_domain=it["source_domain"], published_at=it["published_at"], snippet=it["snippet"],
                  language=it["language"], extra=dict(it["extra"]))
    v = variants_for(case["subject_type"], case["name"], case["identifiers"])
    f = analyse_cluster([raw], case["subject_type"], case["name"], v, case["identifiers"], taxonomy, policy, today=TODAY)
    scoring.classify(f, policy, case["subject_type"])
    return f


def check(case, f):
    e, fails = case["expected"], []
    lvl = f["identity"]["level"]
    if "bucket" in e and f["bucket"] != e["bucket"]:
        fails.append(f"bucket {f['bucket']} != {e['bucket']}")
    if "material" in e and bool(f["material"]) != e["material"]:
        fails.append(f"material {f['material']} != {e['material']}")
    if "identity_min" in e and LEVEL_RANK[lvl] < LEVEL_RANK[e["identity_min"]]:
        fails.append(f"identity {lvl} < {e['identity_min']}")
    if "identity_max" in e and LEVEL_RANK[lvl] > LEVEL_RANK[e["identity_max"]]:
        fails.append(f"identity {lvl} > {e['identity_max']}")
    if "event_status" in e and f["event_status"] != e["event_status"]:
        fails.append(f"status {f['event_status']} != {e['event_status']}")
    if "category" in e and e["category"] not in [c["id"] for c in f["categories"]]:
        fails.append(f"category {e['category']} not in {[c['id'] for c in f['categories']]}")
    return fails


def run_all(verbose=True):
    cases = json.loads(CASES.read_text())["cases"]
    res, checks, checks_ok = [], 0, 0
    for c in cases:
        f = evaluate(c)
        fails = check(c, f)
        n = len(c["expected"])
        checks += n
        checks_ok += n - len(fails)
        res.append((c, f, fails))
        if verbose and fails:
            print(f"FAIL {c['id']:5} [{c['set']}] {c.get('note','')}: {'; '.join(fails)}  "
                  f"(impl={f['implication']} role={f.get('role')} id={f['identity']['level']}/{f['identity']['points']})")
    ok = sum(not r[2] for r in res)
    by_set = {}
    for c, _, fails in res:
        s = by_set.setdefault(c["set"], [0, 0]); s[1] += 1; s[0] += not fails
    if verbose:
        print(f"\nCases passed {ok}/{len(res)} ({100*ok/len(res):.1f}%); label checks {checks_ok}/{checks} ({100*checks_ok/checks:.1f}%)")
        for k, (a, b) in by_set.items():
            print(f"  {k:13} {a}/{b}")
    return ok, len(res), checks_ok, checks, by_set, res


if __name__ == "__main__":
    run_all()
