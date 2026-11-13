"""Cohort survival math (Kaplan-Meier with right-censoring).

An *entity* is anything that is born and may later go quiet: a DAO, a contract.
Each entity has a birth date and a last-activity date. An entity is *dead* when
its last activity is more than `death_gap_days` before the observation end. A
living entity is right-censored: we only know it has survived *at least* this
long, so it still counts in the risk set but never as a death.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class Entity:
    id: str
    birth: date
    last: date
    activity: float = 0.0  # proposals, calls... used only for ranking tombstones


def is_dead(e: Entity, end: date, gap_days: int) -> bool:
    return (end - e.last).days > gap_days


def lifetime_months(e: Entity, end: date, gap_days: int) -> tuple[int, bool]:
    """Return (whole months observed, died?)."""
    dead = is_dead(e, end, gap_days)
    stop = e.last if dead else end
    months = int(max(0, (stop - e.birth).days) // DAYS_PER_MONTH)
    return months, dead


def kaplan_meier(entities: Iterable[Entity], end: date, gap_days: int,
                 horizon: int = 60, min_at_risk: int = 10) -> list[dict]:
    """Survival curve S(k) for k = 0..horizon months.

    Points are dropped once fewer than `min_at_risk` entities are still under
    observation, so the tail of a young cohort is never reported from noise.
    """
    obs = [lifetime_months(e, end, gap_days) for e in entities]
    if not obs:
        return []
    deaths: dict[int, int] = {}
    exits: dict[int, int] = {}
    for m, d in obs:
        exits[m] = exits.get(m, 0) + 1
        if d:
            deaths[m] = deaths.get(m, 0) + 1
    at_risk = len(obs)
    s = 1.0
    curve = []
    for k in range(horizon + 1):
        if at_risk < min_at_risk:
            break
        # survival *through* month k: deaths that happened at month k remove
        # the entity before it reaches k+1
        curve.append({"month": k, "survival": round(s, 4), "at_risk": at_risk})
        d = deaths.get(k, 0)
        if at_risk:
            s *= 1 - d / at_risk
        at_risk -= exits.get(k, 0)
    return curve


def survival_at(curve: list[dict], month: int) -> float | None:
    for p in curve:
        if p["month"] == month:
            return p["survival"]
    return None


def median_lifetime(curve: list[dict]) -> int | None:
    for p in curve:
        if p["survival"] <= 0.5:
            return p["month"]
    return None


def quarter(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def births_deaths(entities: list[Entity], end: date, gap_days: int) -> list[dict]:
    """Births and deaths per calendar quarter. A death is dated at the last
    activity. Quarters whose deaths can't be known yet (inside the gap window)
    are flagged `deaths_final = False`."""
    rows: dict[str, dict] = {}
    for e in entities:
        q = quarter(e.birth)
        rows.setdefault(q, {"quarter": q, "births": 0, "deaths": 0})["births"] += 1
        if is_dead(e, end, gap_days):
            q = quarter(e.last)
            rows.setdefault(q, {"quarter": q, "births": 0, "deaths": 0})["deaths"] += 1
    known_until = end - timedelta(days=gap_days)
    for r in rows.values():
        y, qn = r["quarter"].split("-Q")
        q_end_month = int(qn) * 3
        q_end = date(int(y) + (q_end_month == 12), (q_end_month % 12) + 1, 1) - timedelta(days=1)
        r["deaths_final"] = q_end <= known_until
    return sorted(rows.values(), key=lambda r: r["quarter"])


def cohort_key(d: date) -> str:
    return str(d.year)


def analyse(entities: list[Entity], end: date, gap_days: int = 90,
            horizon: int = 60, min_at_risk: int = 10, top_n: int = 12) -> dict:
    cohorts: dict[str, list[Entity]] = {}
    for e in entities:
        cohorts.setdefault(cohort_key(e.birth), []).append(e)

    curves = {}
    for key in sorted(cohorts):
        c = kaplan_meier(cohorts[key], end, gap_days, horizon, min_at_risk)
        if c:
            curves[key] = {"n": len(cohorts[key]), "curve": c,
                           "s12": survival_at(c, 12), "s24": survival_at(c, 24),
                           "median_months": median_lifetime(c)}
    overall = kaplan_meier(entities, end, gap_days, horizon, min_at_risk)

    alive = [e for e in entities if not is_dead(e, end, gap_days)]
    dead = [e for e in entities if is_dead(e, end, gap_days)]
    return {
        "observation_end": end.isoformat(),
        "death_gap_days": gap_days,
        "total": len(entities),
        "alive": len(alive),
        "dead": len(dead),
        "overall": {"curve": overall, "s12": survival_at(overall, 12),
                    "s24": survival_at(overall, 24),
                    "median_months": median_lifetime(overall)},
        "cohorts": curves,
        "births_deaths": births_deaths(entities, end, gap_days),
        "tombstones": [_row(e) for e in sorted(dead, key=lambda e: -e.activity)[:top_n]],
        "elders": [_row(e) for e in sorted(alive, key=lambda e: e.birth)[:top_n]],
    }


def _row(e: Entity) -> dict:
    return {"id": e.id, "born": e.birth.isoformat(), "last": e.last.isoformat(),
            "activity": e.activity}
