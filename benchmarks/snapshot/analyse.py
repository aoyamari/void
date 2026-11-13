"""Apply VOID's own survival + thesis code to Snapshot spaces.

Run from the repo root after fetch_snapshot.py has written
benchmarks/snapshot/snapshot_proposals.jsonl:

    python benchmarks/snapshot/analyse.py

Entity = Snapshot space; birth = first proposal; last = latest proposal;
dead = no proposal for more than 90 days before the observation end.
Proposals that Snapshot flagged are excluded.
"""
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from void.survival import METHOD_VERSION, Entity, analyse  # noqa: E402
from void.thesis import score  # noqa: E402

HERE = Path(__file__).resolve().parent
END = date(2026, 11, 13)  # same day the NEAR DAO data was fetched
thesis = json.loads((ROOT / "thesis.json").read_text())

spaces, flagged = defaultdict(list), 0
for line in open(HERE / "snapshot_proposals.jsonl"):
    p = json.loads(line)
    if p["flagged"]:
        flagged += 1
        continue
    if p["space"]:
        spaces[p["space"]].append(p["created"])


def d(t):
    return datetime.fromtimestamp(t, timezone.utc).date()


out = {"method_version": METHOD_VERSION, "observation_end": END.isoformat(), "flagged_proposals_excluded": flagged,
       "total_proposals_kept": sum(len(v) for v in spaces.values()), "variants": {}}
for minp in (1, 2, 5):
    ents = [Entity(s, d(min(ts)), d(max(ts)), len(ts)) for s, ts in spaces.items()
            if len(ts) >= minp and d(min(ts)) <= END]
    a = analyse(ents, END, thesis.get("death_gap_days", 90))
    out["variants"][f"min_proposals_{minp}"] = {
        "spaces": a["total"], "alive": a["alive"], "s12": a["overall"]["s12"],
        "s24": a["overall"]["s24"], "median_months": a["overall"]["median_months"],
        "cohort_s12": {k: v["s12"] for k, v in a["cohorts"].items()},
        "cohort_n": {k: v["n"] for k, v in a["cohorts"].items()},
        "claims": {c["id"]: {"status": c["status"], "evidence": c["evidence"]}
                   for c in score(thesis, a, ents)}}
(HERE / "results.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: {x: v[x] for x in ("spaces", "alive", "s12", "median_months")}
                  for k, v in out["variants"].items()}, indent=1))
