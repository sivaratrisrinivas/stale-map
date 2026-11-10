"""Recrawl ranking: which pages to refetch first under a fixed crawl budget.

Held-out day: every feature uses registry data up to the cutoff only. The label is whether
the index copy was stale at observation, about a day after the cutoff. Nothing is fitted
on labels; the two constants (90-day window, 0.5 prior) were fixed before collection.

Outside view (no knowledge of when the index last crawled each page)
- uniform:      random order; expected catch rate = budget share
- popularity:   most-downloaded / most-starred first (within-registry percentile)
- change_rate:  Poisson change rate lambda from release history (Cho & Garcia-Molina);
                with the same unknown crawl age for every page this ranks by lambda
- recency:      most recent release before the cutoff first

Index-owner view (knows each page's crawl time; Parallel exposes it as `acquired_at`)
- age_poisson:  classic P(changed since crawl) = 1 - exp(-lambda * crawl_age)
- change_clock: reads the registry's own change clock. A release between the crawl and the
                cutoff means the copy is stale (P = 1); otherwise the Poisson term covers the
                part of the window the clock has not reported yet (cutoff -> observation).
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

H = 3600.0
WINDOW_DAYS = 90.0
PRIOR = 0.5


@dataclass
class Page:
    pid: str
    registry: str
    popularity: float                    # within-registry percentile, 0..1
    tl_times_before_cutoff: list[float]  # display-timeline release times <= cutoff
    t_obs: float
    crawl_t: float | None = None         # index crawl time (acquired_at midpoint), if known
    stale: bool | None = None            # label at observation


def is_holdout(pid: str, mod: int = 3) -> bool:
    return int(hashlib.sha1(pid.encode()).hexdigest(), 16) % mod == 0


def change_rate(times: list[float], cutoff: float, window_days: float = WINDOW_DAYS, prior: float = PRIOR) -> float:
    """Display-changing releases per hour over the window before the cutoff, with a small prior."""
    lo = cutoff - window_days * 86400
    n = sum(1 for t in times if lo < t <= cutoff)
    return (n + prior) / (window_days * 24.0)


def p_age_poisson(p: Page, cutoff: float) -> float:
    lam = change_rate(p.tl_times_before_cutoff, cutoff)
    age_h = max(0.0, (p.t_obs - p.crawl_t) / H)
    return 1 - math.exp(-lam * age_h)


def p_change_clock(p: Page, cutoff: float) -> float:
    lam = change_rate(p.tl_times_before_cutoff, cutoff)
    if any(t > p.crawl_t for t in p.tl_times_before_cutoff):
        return 1.0
    unknown_h = max(0.0, (p.t_obs - max(p.crawl_t, cutoff)) / H)
    return 1 - math.exp(-lam * unknown_h)


OUTSIDE = ["popularity", "change_rate", "recency"]
OWNER = ["age_poisson", "change_clock"]
POLICIES = ["uniform"] + OUTSIDE + OWNER


def scores(pages: list[Page], cutoff: float) -> dict[str, dict[str, float]]:
    out = {k: {} for k in OUTSIDE + OWNER}
    for p in pages:
        lam = change_rate(p.tl_times_before_cutoff, cutoff)
        out["popularity"][p.pid] = p.popularity
        out["change_rate"][p.pid] = lam
        out["recency"][p.pid] = max(p.tl_times_before_cutoff) if p.tl_times_before_cutoff else 0.0
        if p.crawl_t is not None:
            # tie-break the P=1 group by change rate
            out["age_poisson"][p.pid] = p_age_poisson(p, cutoff)
            out["change_clock"][p.pid] = p_change_clock(p, cutoff) + 1e-9 * lam
    return out


def catch_rate(order: list[str], stale: set[str], k: int) -> float:
    if not stale:
        return float("nan")
    return len(set(order[:k]) & stale) / len(stale)


def rank(score: dict[str, float], seed: int = 0) -> list[str]:
    rnd = random.Random(seed)
    ids = list(score)
    rnd.shuffle(ids)  # random tie-break, fixed seed
    return sorted(ids, key=lambda i: -score[i])


def evaluate(pages: list[Page], cutoff: float, budgets=(0.1, 0.25, 0.5)) -> dict:
    pages = [p for p in pages if p.crawl_t is not None]
    sc = scores(pages, cutoff)
    stale = {p.pid for p in pages if p.stale}
    n = len(pages)
    res = {"n_pages": n, "n_stale": len(stale), "budgets": {}}
    for b in budgets:
        k = max(1, round(b * n))
        row = {"k": k, "uniform": k / n, "oracle": min(1.0, k / len(stale)) if stale else float("nan")}
        for name in OUTSIDE + OWNER:
            row[name] = catch_rate(rank(sc[name]), stale, k)
        res["budgets"][f"{int(b * 100)}%"] = row
    # Budget needed to catch 90% of stale pages, per policy (share of pages crawled)
    need = {}
    for name in OUTSIDE + OWNER:
        order = rank(sc[name])
        got, k90 = 0, None
        for i, pid in enumerate(order, 1):
            got += pid in stale
            if stale and got >= 0.9 * len(stale):
                k90 = i
                break
        need[name] = k90 / n if k90 else None
    need["uniform"] = 0.9
    res["budget_for_90pct"] = need
    # Catch-rate curve over budgets 0..100% (recall@budget, Bingo-style)
    grid = [i / 20 for i in range(21)]
    res["curve"] = {"budget": grid, "uniform": grid,
                    "oracle": [min(1.0, round(g * n) / len(stale)) if stale else None for g in grid]}
    for name in OUTSIDE + OWNER:
        order = rank(sc[name])
        res["curve"][name] = [catch_rate(order, stale, round(g * n)) for g in grid]
    # Which stale pages only became stale during the held-out day (invisible to a clock frozen at the cutoff)?
    day_only = [p for p in pages if p.stale and not any(t > p.crawl_t for t in p.tl_times_before_cutoff)]
    res["stale_only_after_cutoff"] = len(day_only)
    return res
