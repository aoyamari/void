"""Score the pre-registered thesis claims against an analysis result.

Each claim returns: holds | killed | insufficient, plus the evidence numbers.
"""
from __future__ import annotations

from datetime import date, timedelta

from .survival import Entity, is_dead, survival_at


def cohort_improvement(a: dict, ents: list[Entity], p: dict) -> dict:
    m = p.get("month", 12)
    scored = {k: survival_at(v["curve"], m) for k, v in a["cohorts"].items()}
    scored = {k: v for k, v in scored.items() if v is not None}
    if len(scored) < 2:
        return {"status": "insufficient", "evidence": f"fewer than 2 cohorts with {m}-month data"}
    first, last = min(scored), max(scored)
    ok = scored[last] >= scored[first]
    return {"status": "holds" if ok else "killed",
            "evidence": f"{last} cohort {scored[last]:.0%} vs {first} cohort {scored[first]:.0%} alive at {m} months",
            "values": scored}


def survivor_share(a: dict, ents: list[Entity], p: dict) -> dict:
    end = date.fromisoformat(a["observation_end"])
    cutoff = end - timedelta(days=int(p.get("min_age_months", 12) * 30.4375))
    old = [e for e in ents if e.birth <= cutoff]
    if len(old) < 10:
        return {"status": "insufficient", "evidence": "fewer than 10 entities old enough"}
    alive = sum(1 for e in old if not is_dead(e, end, a["death_gap_days"]))
    share = alive / len(old)
    t = p.get("threshold", 0.10)
    return {"status": "holds" if share >= t else "killed",
            "evidence": f"{alive:,} of {len(old):,} ({share:.1%}) still alive; kill line {t:.0%}",
            "values": {"alive": alive, "old": len(old), "share": round(share, 4)}}


def net_formation(a: dict, ents: list[Entity], p: dict) -> dict:
    end = date.fromisoformat(a["observation_end"])
    win_end = end - timedelta(days=a["death_gap_days"])
    win_start = win_end - timedelta(days=365)
    births = sum(1 for e in ents if win_start <= e.birth < win_end)
    deaths = sum(1 for e in ents if is_dead(e, end, a["death_gap_days"]) and win_start <= e.last < win_end)
    if births + deaths < 10:
        return {"status": "insufficient", "evidence": "too few births and deaths in window"}
    return {"status": "holds" if births >= deaths else "killed",
            "evidence": f"{births:,} born vs {deaths:,} died between {win_start} and {win_end}",
            "values": {"births": births, "deaths": deaths,
                       "window": [win_start.isoformat(), win_end.isoformat()]}}


def median_lifetime(a: dict, ents: list[Entity], p: dict) -> dict:
    med = a["overall"]["median_months"]
    t = p.get("threshold_months", 6)
    if med is None:
        curve = a["overall"]["curve"]
        if not curve:
            return {"status": "insufficient", "evidence": "no survival curve"}
        return {"status": "holds", "evidence": f"survival never fell below 50% within {curve[-1]['month']} months"}
    return {"status": "holds" if med >= t else "killed",
            "evidence": f"median lifetime {med} months; kill line {t} months",
            "values": {"median_months": med}}


METRICS = {f.__name__: f for f in (cohort_improvement, survivor_share, net_formation, median_lifetime)}


def score(thesis: dict, analysis: dict, ents: list[Entity]) -> list[dict]:
    out = []
    for c in thesis["claims"]:
        r = METRICS[c["metric"]](analysis, ents, c.get("params", {}))
        out.append({k: c[k] for k in ("id", "title", "claim", "kill")} | r)
    return out
