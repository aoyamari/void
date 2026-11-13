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
        out.append({k: c[k] for k in ("id", "title", "claim", "kill")} | {"why": c.get("why", "")} | r)
    return out


TREND = ("newer-cohorts-survive-longer", "births-outpace-deaths")
LEVEL = ("not-just-a-graveyard", "not-one-hit-wonders")

VERDICTS = {
    (True, True): ("Compounding: NEAR keeps what it builds",
                   "Both the direction and the level of builder retention support the long-term case."),
    (True, False): ("Improving, not yet compounding",
                    "The direction is right but the base is thin: this supports a growth bet on NEAR, "
                    "not yet a durability bet."),
    (False, True): ("Durable but stalling",
                    "What exists is sticky, but the pipeline of new survivors is weakening."),
    (False, False): ("Thesis killed: NEAR is renting builders",
                     "Neither the direction nor the level of builder retention supports the long-term case."),
    (None, True): ("Durable so far, direction not yet measurable",
                   "What exists is sticky, but there is not enough history to tell whether newer cohorts do better."),
    (None, False): ("Weak so far, direction not yet measurable",
                    "Retention is low, and there is not enough history to tell whether it is improving."),
    (True, None): ("Improving, level not yet measurable",
                   "The direction is right, but there is not enough history to judge how much survives."),
    (False, None): ("Weakening, level not yet measurable",
                    "The direction is wrong, and there is not enough history to judge how much survives."),
    (None, None): ("Not enough data yet", "Too little history to score this chapter."),
}


def bottom_line(claims: list[dict]) -> dict:
    """One overall verdict, derived only from the claim statuses."""
    s = {c["id"]: c["status"] for c in claims}

    def side(ids):
        st = [s.get(i) for i in ids]
        if any(x == "killed" for x in st):
            return False
        if any(x != "holds" for x in st):
            return None  # not enough data to call it either way
        return True

    trend, level = side(TREND), side(LEVEL)
    sides = {"trend": trend, "level": level}
    headline, meaning = VERDICTS[(trend, level)]
    holds = [c for c in claims if c["status"] == "holds"]
    killed = [c for c in claims if c["status"] == "killed"]
    parts = []
    if holds:
        parts.append("Holds: " + "; ".join(f"{c['title']} ({c['evidence']})" for c in holds) + ".")
    if killed:
        parts.append("Killed: " + "; ".join(f"{c['title']} ({c['evidence']})" for c in killed) + ".")
    return {"headline": headline, "meaning": meaning, "evidence": " ".join(parts), "sides": sides,
            "holds": len(holds), "killed": len(killed), "total": len(claims),
            "upgrade_if": [c["title"] for c in claims if c["status"] != "holds"],
            "downgrade_if": [c["kill"] for c in holds]}


def combined_line(chapters: dict) -> dict | None:
    """One read across chapters, derived only from each chapter's sides."""
    if len(chapters) < 2:
        return None
    trends = [c["bottom_line"]["sides"]["trend"] for c in chapters.values()]
    levels = [c["bottom_line"]["sides"]["level"] for c in chapters.values()]
    trend = False if False in trends else (True if True in trends else None)
    level = (True if all(x is True for x in levels) else
             False if all(x is False for x in levels) else "mixed")
    table = {
        (True, True): "Compounding: NEAR keeps what it builds",
        (True, "mixed"): "A growth bet, not yet a durability bet",
        (True, False): "A growth bet, not yet a durability bet",
        (None, True): "Durable so far; too early to call the direction",
        (None, "mixed"): "Mixed retention; too early to call the direction",
        (None, False): "Weak retention; too early to call the direction",
        (False, True): "Durable but stalling",
        (False, "mixed"): "Mixed retention, and the direction is worsening",
        (False, False): "Thesis killed: NEAR is renting builders",
    }
    word = {True: "improving", None: "not yet measurable", False: "worsening"}
    lvl = {True: "durable", None: "not yet measurable", False: "fragile"}
    parts = [f"{name}: {lvl[c['bottom_line']['sides']['level']]}, direction "
             f"{word[c['bottom_line']['sides']['trend']]} ({c['bottom_line']['headline']})"
             for name, c in chapters.items()]
    return {"headline": table[(trend, level)], "parts": parts}


def births_deaths_note(rows: list[dict]) -> str:
    final = [r for r in rows if r["deaths_final"]]
    if not final:
        return ""
    net = sum(r["births"] - r["deaths"] for r in final)
    best = max(final, key=lambda r: r["births"] - r["deaths"])
    worse = [r["quarter"] for r in final if r["deaths"] > r["births"]]
    out = []
    if net > 0 and best["births"] - best["deaths"] > net / 2:
        out.append(f"Over half of the net surplus comes from one quarter, {best['quarter']} "
                   f"({best['births']} born vs {best['deaths']} died).")
    if len(worse) > 3:
        out.append(f"More died than were born in {len(worse)} of {len(final)} quarters "
                   f"with final data, most recently {worse[-1]}.")
    elif worse:
        out.append("More died than were born in " + ", ".join(worse) + ".")
    return " ".join(out)
