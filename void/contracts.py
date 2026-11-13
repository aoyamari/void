"""Chapter 2: the contract graveyard (BigQuery).

Needs a Google Cloud project with BigQuery enabled and local credentials:
    gcloud auth application-default login
    export GOOGLE_CLOUD_PROJECT=<your-project>

The query is dry-run first; it refuses to run if it would scan more than
--max-gb (BigQuery's free tier is 1 TB of scanned data per month).
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timezone
from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / "sql" / "contracts.sql"
TABLE = "bigquery-public-data.crypto_near_mainnet_us.receipt_actions"


def _client():
    try:
        from google.cloud import bigquery  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise SystemExit("pip install google-cloud-bigquery  (needed for chapter 2 only)") from e
    from google.cloud import bigquery
    return bigquery, bigquery.Client()


def check_schema() -> None:
    bq, client = _client()
    q = ("SELECT column_name, data_type FROM "
         "`bigquery-public-data.crypto_near_mainnet_us.INFORMATION_SCHEMA.COLUMNS` "
         "WHERE table_name = 'receipt_actions'")
    for row in client.query(q).result():
        print(f"{row.column_name:40s} {row.data_type}")


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def rows_to_entities(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        first = r["first_active"]
        last = r["last_active"]
        first = date.fromisoformat(str(first)[:10])
        last = month_end(date.fromisoformat(str(last)[:10]))
        out.append({"id": r["contract"], "birth": first.isoformat(), "last": last.isoformat(),
                    "activity": int(r["peak_callers"]), "active_months": int(r["active_months"]),
                    "total_calls": int(r["total_calls"]),
                    "first_deploy": str(r["first_deploy"])[:10]})
    return out


def run(data_dir: Path, start_date: str = "2020-07-01", min_callers: int = 3,
        launch_min_callers: int = 25, max_gb: float = 600.0, dry_only: bool = False) -> Path | None:
    bq, client = _client()
    params = [
        bq.ScalarQueryParameter("start_date", "DATE", start_date),
        bq.ScalarQueryParameter("min_callers", "INT64", min_callers),
        bq.ScalarQueryParameter("launch_min_callers", "INT64", launch_min_callers),
    ]
    sql = SQL.read_text()
    dry = client.query(sql, job_config=bq.QueryJobConfig(
        query_parameters=params, dry_run=True, use_query_cache=False))
    gb = dry.total_bytes_processed / 1e9
    print(f"[contracts] dry run: query will scan {gb:,.1f} GB")
    if dry_only:
        return None
    if gb > max_gb:
        raise SystemExit(f"refusing: {gb:,.0f} GB > --max-gb {max_gb}. Raise --start-date or --max-gb.")

    job = client.query(sql, job_config=bq.QueryJobConfig(
        query_parameters=params, maximum_bytes_billed=int(max_gb * 1e9)))
    rows = [dict(r) for r in job.result()]
    end_q = (f"SELECT MAX(block_date) AS d FROM `{TABLE}` "
             "WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)")
    data_end = list(client.query(end_q).result())[0]["d"]

    out = {"entities": rows_to_entities(rows),
           "census": {"contracts_launched": len(rows), "min_callers": min_callers,
                      "launch_min_callers": launch_min_callers, "start_date": start_date},
           "observation_end": str(data_end),
           "source": {"table": TABLE, "scanned_gb": round(gb, 1),
                      "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    path = data_dir / "contracts.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"[contracts] {len(rows)} launched contracts -> {path}")
    return path
