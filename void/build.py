"""Turn raw chapter outputs into site/data.json for the dashboard."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from .survival import Entity, analyse
from .thesis import score

ROOT = Path(__file__).resolve().parent.parent


def load_entities(rows: list[dict]) -> list[Entity]:
    return [Entity(r["id"], date.fromisoformat(r["birth"]), date.fromisoformat(r["last"]),
                   float(r.get("activity", 0))) for r in rows]


def chapter(raw: dict, end: date, thesis: dict, unit: str) -> dict:
    ents = load_entities(raw["entities"])
    a = analyse(ents, end, thesis.get("death_gap_days", 90))
    a["claims"] = score(thesis, a, ents)
    a["census"] = raw.get("census", {})
    a["source"] = raw.get("source", {})
    a["unit"] = unit
    return a


def run(data_dir: Path, site_dir: Path, thesis_path: Path = ROOT / "thesis.json") -> Path:
    thesis = json.loads(thesis_path.read_text())
    out = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "thesis": {k: thesis[k] for k in ("thesis", "written", "death_gap_days")},
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
    print(f"[build] -> {path}")
    return path
