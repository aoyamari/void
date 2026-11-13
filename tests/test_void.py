import json
from datetime import date

from void import build, dao
from void.rpc import ViewError
from void.survival import Entity, analyse, births_deaths, kaplan_meier, lifetime_months
from void.thesis import score

END = date(2026, 11, 13)


def ent(i, birth, last, act=1):
    return Entity(str(i), date.fromisoformat(birth), date.fromisoformat(last), act)


def test_lifetime_dead_vs_censored():
    dead = ent(1, "2024-01-01", "2024-07-01")
    alive = ent(2, "2024-01-01", "2026-11-01")
    assert lifetime_months(dead, END, 90) == (5, True)
    m, d = lifetime_months(alive, END, 90)
    assert not d and m == 34


def test_kaplan_meier_simple():
    # 10 entities: 5 die in month 0, 5 alive (censored) at ~10 months
    es = [ent(i, "2026-01-01", "2026-01-10") for i in range(5)]
    es += [ent(i + 5, "2026-01-01", "2026-11-10") for i in range(5)]
    c = kaplan_meier(es, END, 90, horizon=12, min_at_risk=1)
    assert c[0]["survival"] == 1.0
    assert c[1]["survival"] == 0.5
    assert c[10]["survival"] == 0.5  # censored entities never count as deaths


def test_km_respects_min_at_risk():
    es = [ent(i, "2026-01-01", "2026-11-10") for i in range(5)]
    assert kaplan_meier(es, END, 90, min_at_risk=10) == []


def test_births_deaths_flags_unknown_quarters():
    es = [ent(1, "2025-01-15", "2025-02-01"), ent(2, "2026-10-01", "2026-10-02")]
    rows = {r["quarter"]: r for r in births_deaths(es, END, 90)}
    assert rows["2025-Q1"]["births"] == 1 and rows["2025-Q1"]["deaths"] == 1
    assert rows["2025-Q1"]["deaths_final"] is True
    assert rows["2026-Q4"]["deaths_final"] is False


def test_thesis_scores():
    thesis = json.load(open("thesis.json"))
    es = []
    # 2022 cohort: 20 born, 15 die after 2 months
    es += [ent(f"a{i}", "2022-03-01", "2022-05-01") for i in range(15)]
    es += [ent(f"b{i}", "2022-03-01", "2026-11-01") for i in range(5)]
    # 2024 cohort: 20 born, 5 die
    es += [ent(f"c{i}", "2024-03-01", "2024-05-01") for i in range(5)]
    es += [ent(f"d{i}", "2024-03-01", "2026-11-01") for i in range(15)]
    a = analyse(es, END, 90, min_at_risk=5)
    res = {r["id"]: r for r in score(thesis, a, es)}
    assert res["newer-cohorts-survive-longer"]["status"] == "holds"
    assert res["not-just-a-graveyard"]["status"] == "holds"
    assert res["not-one-hit-wonders"]["status"] in ("holds", "killed")


class FakeRpc:
    url = "fake"

    def __init__(self):
        self.daos = {"a.sputnik-dao.near": [1_640_995_200_000_000_000, 1_700_000_000_000_000_000],
                     "b.sputnik-dao.near": [],
                     "c.sputnik-dao.near": None}

    def view(self, account, method, args=None):
        if method == "get_number_daos":
            return len(self.daos)
        if method == "get_daos":
            return list(self.daos)[args["from_index"]: args["from_index"] + args["limit"]]
        times = self.daos[account]
        if times is None:
            raise ViewError("MethodNotFound")
        if method == "get_last_proposal_id":
            return len(times)
        if method == "get_proposals":
            f, n = args["from_index"], args["limit"]
            return [{"id": i, "proposer": "x.near", "kind": {"Transfer": {}},
                     "status": "Approved", "submission_time": str(t)}
                    for i, t in enumerate(times)][f:f + n]


def test_dao_pipeline(tmp_path):
    rpc = FakeRpc()
    names = dao.list_daos(rpc)
    assert len(names) == 3
    recs = [dao.fetch_dao(rpc, n, tmp_path) for n in names]
    out = dao.to_entity_rows(recs)
    assert out["census"] == {"daos_created": 3, "stillborn": 1, "unreadable": 1,
                             "below_threshold": 0, "min_proposals": 1}
    row = out["entities"][0]
    assert row["birth"] == "2022-01-01" and row["activity"] == 2
    # cache makes the second run incremental
    again = dao.fetch_dao(rpc, "a.sputnik-dao.near", tmp_path)
    assert len(again["proposals"]) == 2


def test_build_end_to_end(tmp_path):
    rows = [{"id": f"d{i}", "birth": "2023-01-01", "last": "2026-11-01" if i % 2 else "2023-03-01",
             "activity": i} for i in range(40)]
    (tmp_path / "daos.json").write_text(json.dumps({
        "entities": rows, "census": {"daos_created": 50},
        "source": {"fetched_at": "2026-11-13T00:00:00+00:00"}}))
    p = build.run(tmp_path, tmp_path / "site")
    data = json.loads(p.read_text())
    ch = data["chapters"]["daos"]
    assert ch["total"] == 40 and ch["alive"] == 20
    assert len(ch["claims"]) == 4
