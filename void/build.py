"""Turn raw chapter outputs into site/data.json for the dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .survival import METHOD_VERSION, Entity, analyse
from .thesis import births_deaths_note, bottom_line, combined_line, score

ROOT = Path(__file__).resolve().parent.parent
SENSITIVITY_GAPS = (60, 90, 180)
# Token factories of memecoin launchpads. Their tokens are contracts, but not
# products, so the contracts chapter also reports them separately.
LAUNCHPAD_SUFFIXES = (".gra-fun.near", ".meme-cooking.near", ".aidols.near", ".tkn.near", ".token0.near")


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
    html = []
    if out.get("combined"):
        html.append(f"<p><b>Across both chapters: {out['combined']['headline']}.</b></p>")
    for name, c in out["chapters"].items():
        b = c["bottom_line"]
        label = {"daos": "DAOs", "contracts": "Contracts"}[name]
        html.append(f"<p><b>{label}: {b['headline']}.</b> {b['meaning']} "
                    f"{c['total']:,} active, {c['alive']:,} still alive; "
                    f"{b['holds']} of {b['total']} pre-registered claims hold. {b['evidence']}</p>")
    return "".join(html)


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

    bench = ROOT / "benchmarks" / "snapshot" / "results.json"
    if "daos" in out["chapters"] and bench.exists():
        snap = json.loads(bench.read_text())
        if snap.get("method_version") == METHOD_VERSION:
            raw = json.loads(daos.read_text())
            end = date.fromisoformat(snap["observation_end"])
            rows = []
            for minp in (1, 2, 5):
                ents = [e for e in load_entities(raw["entities"]) if e.activity >= minp]
                a = analyse(ents, end, thesis.get("death_gap_days", 90))
                sv = snap["variants"][f"min_proposals_{minp}"]
                rows.append({"min_proposals": minp,
                             "near": {"n": a["total"], "alive": a["alive"], "s12": a["overall"]["s12"],
                                      "median_months": a["overall"]["median_months"]},
                             "snapshot": {"n": sv["spaces"], "alive": sv["alive"], "s12": sv["s12"],
                                          "median_months": sv["median_months"]}})
            out["chapters"]["daos"]["benchmark"] = {"name": "Ethereum and EVM chains, off-chain voting",
                                                    "rows": rows}
        else:
            print("[build] Snapshot benchmark skipped: computed with an older survival method; "
                  "re-run benchmarks/snapshot/analyse.py")

    contracts = data_dir / "contracts.json"
    if contracts.exists():
        raw = json.loads(contracts.read_text())
        end = date.fromisoformat(raw["observation_end"][:10])
        out["chapters"]["contracts"] = chapter(raw, end, thesis, "peak monthly callers")
        out["chapters"]["contracts"]["breakdown"] = breakdown(
            drop_left_truncated(raw)["entities"], end, thesis.get("death_gap_days", 90))
        print(f"[build] contracts: {len(raw['entities'])} entities")

    for ch in out["chapters"].values():
        ch["births_deaths_note"] = births_deaths_note(ch["births_deaths"])
    named = {{"daos": "DAOs", "contracts": "Contracts"}[k]: v for k, v in out["chapters"].items()}
    out["combined"] = combined_line(named)
    out["method_version"] = METHOD_VERSION

    if not out["chapters"]:
        raise SystemExit("no data yet: run `python -m void dao` (and/or `contracts`) first")
    site_dir.mkdir(parents=True, exist_ok=True)
    path = site_dir / "data.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    inject_summary(site_dir / "index.html", static_summary(out))
    print(f"[build] -> {path}")
    return path
