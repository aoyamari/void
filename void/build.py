"""Turn raw chapter outputs into site/data.json for the dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .survival import Entity, analyse
from .thesis import bottom_line, score

ROOT = Path(__file__).resolve().parent.parent
SENSITIVITY_GAPS = (60, 90, 180)
# Token factories of memecoin launchpads. Their tokens are contracts, but not
# products, so the contracts chapter also reports them separately.
LAUNCHPAD_SUFFIXES = (".gra-fun.near", ".meme-cooking.near", ".aidols.near", ".tkn.near")


def breakdown(rows: list[dict], end: date, gap: int) -> list[dict]:
    groups = {"Apps and infrastructure": [r for r in rows if not r["id"].endswith(LAUNCHPAD_SUFFIXES)],
              "Launchpad tokens": [r for r in rows if r["id"].endswith(LAUNCHPAD_SUFFIXES)]}
    out = []
    for name, rs in groups.items():
        a = analyse(load_entities(rs), end, gap)
        out.append({"group": name, "total": a["total"], "alive": a["alive"],
                    "s12": a["overall"]["s12"], "median_months": a["overall"]["median_months"],
                    "observed_months": a["overall"]["curve"][-1]["month"] if a["overall"]["curve"] else None})
    return out
MARK = ("<!--void:summary-->", "<!--/void:summary-->")


def static_summary(out: dict) -> str:
    """Plain-HTML summary so link previews and no-JS readers see the result."""
    c = next(iter(out["chapters"].values()))
    b = c["bottom_line"]
    return (f"<p><b>Bottom line: {b['headline']}.</b> {b['meaning']} "
            f"{c['total']:,} projects ever active, {c['alive']:,} still alive; "
            f"{b['holds']} of {b['total']} pre-registered claims hold. {b['evidence']}</p>")


def inject_summary(index: Path, html: str) -> None:
    if not index.exists():
        return
    s = index.read_text()
    a, z = s.find(MARK[0]), s.find(MARK[1])
    if a < 0 or z < 0:
        return
    index.write_text(s[:a + len(MARK[0])] + html + s[z:])


def load_entities(rows: list[dict]) -> list[Entity]:
    return [Entity(r["id"], date.fromisoformat(r["birth"]), date.fromisoformat(r["last"]),
                   float(r.get("activity", 0))) for r in rows]


def drop_left_truncated(raw: dict) -> dict:
    """With a start_date window, anything already active in the window's first
    month was most likely born earlier, so its age is unknown. Keep only
    entities first seen after that month."""
    start = raw.get("census", {}).get("start_date")
    if not start:
        return raw
    first_month = start[:7]
    # also drop contracts whose first in-window deploy came after they were
    # already in use: that deploy was an upgrade of an older contract
    keep = [r for r in raw["entities"] if r["birth"][:7] > first_month
            and str(r.get("first_deploy", r["birth"]))[:7] <= r["birth"][:7]]
    census = dict(raw["census"], preexisting_excluded=len(raw["entities"]) - len(keep),
                  window_start=start)
    return dict(raw, entities=keep, census=census)


def chapter(raw: dict, end: date, thesis: dict, unit: str) -> dict:
    raw = drop_left_truncated(raw)
    ents = load_entities(raw["entities"])
    a = analyse(ents, end, thesis.get("death_gap_days", 90))
    a["claims"] = score(thesis, a, ents)
    a["bottom_line"] = bottom_line(a["claims"])
    # does the verdict depend on the 90-day death definition?
    sens = []
    for gap in SENSITIVITY_GAPS:
        alt = analyse(ents, end, gap)
        sens.append({"gap_days": gap, "alive": alt["alive"],
                     "statuses": {c["id"]: c["status"] for c in score(thesis, alt, ents)}})
    a["sensitivity"] = sens
    a["census"] = raw.get("census", {})
    a["source"] = raw.get("source", {})
    a["unit"] = unit
    return a


def run(data_dir: Path, site_dir: Path, thesis_path: Path = ROOT / "thesis.json") -> Path:
    thesis = json.loads(thesis_path.read_text())
    out = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "thesis": {k: thesis.get(k) for k in ("thesis", "written", "death_gap_days", "death_gap_why")},
           "chapters": {}}

    daos = data_dir / "daos.json"
    if daos.exists():
        raw = json.loads(daos.read_text())
        end = date.fromisoformat(raw["source"]["fetched_at"][:10])
        out["chapters"]["daos"] = chapter(raw, end, thesis, "proposals")
        print(f"[build] DAOs: {len(raw['entities'])} entities")

    bench = ROOT / "benchmarks" / "snapshot"
    if "daos" in out["chapters"] and (bench / "results.json").exists():
        snap = json.loads((bench / "results.json").read_text())["variants"]
        near = json.loads((bench / "near_same_filters.json").read_text())
        rows = []
        for k in ("min_proposals_1", "min_proposals_2", "min_proposals_5"):
            s, n = snap[k], near[k]
            rows.append({"min_proposals": int(k.rsplit("_", 1)[1]),
                         "near": {"n": n["daos"], "alive": n["alive"], "s12": n["s12"],
                                  "median_months": n["median_months"]},
                         "snapshot": {"n": s["spaces"], "alive": s["alive"], "s12": s["s12"],
                                      "median_months": s["median_months"]}})
        out["chapters"]["daos"]["benchmark"] = {"name": "Ethereum and EVM chains, off-chain voting",
                                                "rows": rows}

    contracts = data_dir / "contracts.json"
    if contracts.exists():
        raw = json.loads(contracts.read_text())
        end = date.fromisoformat(raw["observation_end"][:10])
        out["chapters"]["contracts"] = chapter(raw, end, thesis, "peak monthly callers")
        out["chapters"]["contracts"]["breakdown"] = breakdown(
            drop_left_truncated(raw)["entities"], end, thesis.get("death_gap_days", 90))
        print(f"[build] contracts: {len(raw['entities'])} entities")

    if not out["chapters"]:
        raise SystemExit("no data yet: run `python -m void dao` (and/or `contracts`) first")
    site_dir.mkdir(parents=True, exist_ok=True)
    path = site_dir / "data.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    inject_summary(site_dir / "index.html", static_summary(out))
    print(f"[build] -> {path}")
    return path
