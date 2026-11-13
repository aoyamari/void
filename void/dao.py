"""Chapter 1: the DAO graveyard.

Every Sputnik DAO on NEAR is created by a factory contract. We list them all,
pull every proposal's submission time with plain RPC view calls (no API key,
no indexer), and turn each DAO into an Entity:

  birth = first proposal, last = latest proposal, activity = proposal count.

DAOs that never received a single proposal are "stillborn" and reported
separately (we cannot date them without an indexer).

Raw proposals are cached under data/raw/daos/, so re-runs only fetch new ones.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .rpc import Rpc, ViewError

FACTORY = "sputnik-dao.near"
PAGE = 100


def list_daos(rpc: Rpc, factory: str = FACTORY) -> list[str]:
    try:
        total = int(rpc.view(factory, "get_number_daos"))
        daos: list[str] = []
        while len(daos) < total:
            page = rpc.view(factory, "get_daos", {"from_index": len(daos), "limit": PAGE})
            if not page:
                break
            daos.extend(page)
        return daos
    except ViewError:
        return list(rpc.view(factory, "get_dao_list"))


def slim(p: dict) -> dict:
    kind = p.get("kind")
    kind = next(iter(kind)) if isinstance(kind, dict) else str(kind)
    return {"id": p["id"], "proposer": p.get("proposer"), "kind": kind,
            "status": p.get("status"), "t": int(p["submission_time"])}


def fetch_dao(rpc: Rpc, dao: str, cache_dir: Path) -> dict:
    path = cache_dir / f"{dao}.json"
    cached = json.loads(path.read_text()) if path.exists() else {"dao": dao, "proposals": []}
    try:
        last_id = int(rpc.view(dao, "get_last_proposal_id"))
    except ViewError as e:
        cached["error"] = str(e)[:200]
        return cached
    have = {p["id"] for p in cached["proposals"]}
    start = max(have) + 1 if have else 0
    # Statuses change after submission (InProgress -> Approved), so the most
    # recent page is always refreshed.
    start = max(0, min(start, last_id - PAGE))
    fresh: dict[int, dict] = {p["id"]: p for p in cached["proposals"]}
    for from_index in range(start, last_id, PAGE):
        page = rpc.view(dao, "get_proposals", {"from_index": from_index, "limit": PAGE})
        for p in page or []:
            fresh[p["id"]] = slim(p)
    cached["proposals"] = sorted(fresh.values(), key=lambda p: p["id"])
    cached["last_proposal_id"] = last_id
    cached.pop("error", None)
    path.write_text(json.dumps(cached))
    return cached


def ns_to_date(ns: int):
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).date()


def to_entity_rows(records: list[dict], min_proposals: int = 1) -> dict:
    """Turn cached DAO records into entity rows + census counts."""
    rows, stillborn, unreadable, below = [], 0, 0, 0
    for rec in records:
        if rec.get("error"):
            unreadable += 1
            continue
        props = rec.get("proposals", [])
        if not props:
            stillborn += 1
            continue
        if len(props) < min_proposals:
            below += 1
            continue
        times = [p["t"] for p in props]
        rows.append({
            "id": rec["dao"],
            "birth": ns_to_date(min(times)).isoformat(),
            "last": ns_to_date(max(times)).isoformat(),
            "activity": len(props),
            "proposers": len({p["proposer"] for p in props}),
            "approved": sum(1 for p in props if p.get("status") == "Approved"),
        })
    return {"entities": rows, "census": {
        "daos_created": len(records), "stillborn": stillborn,
        "unreadable": unreadable, "below_threshold": below,
        "min_proposals": min_proposals}}


def run(data_dir: Path, rpc_url: str | None = None, factory: str = FACTORY,
        workers: int = 8, limit: int | None = None, min_proposals: int = 1) -> Path:
    rpc = Rpc(rpc_url) if rpc_url else Rpc()
    cache = data_dir / "raw" / "daos"
    cache.mkdir(parents=True, exist_ok=True)
    daos = list_daos(rpc, factory)
    if limit:
        daos = daos[:limit]
    print(f"[dao] {len(daos)} DAOs from {factory}")
    records = []
    with ThreadPoolExecutor(workers) as pool:
        futs = {pool.submit(fetch_dao, rpc, d, cache): d for d in daos}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                records.append(f.result())
            except ViewError as e:
                records.append({"dao": futs[f], "error": str(e)[:200], "proposals": []})
            if i % 200 == 0:
                print(f"[dao] {i}/{len(daos)}")
    out = to_entity_rows(records, min_proposals)
    out["source"] = {"factory": factory, "rpc": rpc.url,
                     "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = data_dir / "daos.json"
    path.write_text(json.dumps(out, indent=1))
    c = out["census"]
    print(f"[dao] {len(out['entities'])} dated, {c['stillborn']} stillborn, "
          f"{c['unreadable']} unreadable -> {path}")
    return path
