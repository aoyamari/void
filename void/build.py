"""Turn raw chapter outputs into site/data.json for the dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .survival import Entity, analyse
from .thesis import bottom_line, score

ROOT = Path(__file__).resolve().parent.parent
SENSITIVITY_GAPS = (60, 90, 180)
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
    keep = [r for r in raw["entities"] if r["birth"][:7] > first_month]
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

    contracts = data_dir / "contracts.json"
    if contracts.exists():
        raw = json.loads(contracts.read_text())
        end = date.fromisoformat(raw["observation_end"][:10])
        out["chapters"]["contracts"] = chapter(raw, end, thesis, "peak monthly callers")
        print(f"[build] contracts: {len(raw['entities'])} entities")

    if not out["chapters"]:
        raise SystemExit("no data yet: run `python -m void dao` (and/or `contracts`) first")
    site_dir.mkdir(parents=True, exist_ok=True)
    path = site_dir / "data.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    inject_summary(site_dir / "index.html", static_summary(out))
    print(f"[build] -> {path}")
    return path
