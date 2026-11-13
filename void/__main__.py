"""VOID command line.

    python -m void dao          # chapter 1: Sputnik DAOs via NEAR RPC (no key)
    python -m void contracts    # chapter 2: contracts via BigQuery (GCP project)
    python -m void build        # analysis + thesis verdicts -> site/data.json
    python -m void all          # dao + build
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import build, dao

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(prog="void")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--site", type=Path, default=ROOT / "site")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dao", help="fetch every Sputnik DAO and its proposals")
    d.add_argument("--rpc", default=None, help="NEAR RPC URL (or env NEAR_RPC_URL)")
    d.add_argument("--factory", default=dao.FACTORY)
    d.add_argument("--workers", type=int, default=8)
    d.add_argument("--limit", type=int, default=None, help="only the first N DAOs (smoke test)")
    d.add_argument("--min-proposals", type=int, default=1)

    c = sub.add_parser("contracts", help="contract survival from BigQuery")
    c.add_argument("--start-date", default="2020-07-01")
    c.add_argument("--min-callers", type=int, default=3)
    c.add_argument("--launch-min-callers", type=int, default=25)
    c.add_argument("--max-gb", type=float, default=600.0)
    c.add_argument("--dry-run", action="store_true", help="only print scan size")
    c.add_argument("--check-schema", action="store_true")

    sub.add_parser("build", help="build site/data.json")
    sub.add_parser("rescore", help="recompute data/daos.json from data/raw cache (no RPC)")
    a = sub.add_parser("all", help="dao + build")
    a.add_argument("--rpc", default=None)

    args = ap.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    if args.cmd == "dao":
        dao.run(args.data, args.rpc, args.factory, args.workers, args.limit, args.min_proposals)
    elif args.cmd == "contracts":
        from . import contracts
        if args.check_schema:
            contracts.check_schema()
            return
        contracts.run(args.data, args.start_date, args.min_callers, args.launch_min_callers,
                      args.max_gb, args.dry_run)
    elif args.cmd == "rescore":
        dao.rescore(args.data)
    elif args.cmd == "build":
        build.run(args.data, args.site)
    elif args.cmd == "all":
        dao.run(args.data, args.rpc)
        build.run(args.data, args.site)


if __name__ == "__main__":
    main()
