"""Turn 'which release does the copy show' into crawl-age bounds and staleness."""
from __future__ import annotations

from dataclasses import dataclass

from .versions import Release

H = 3600.0


@dataclass
class Bracket:
    shown: str
    stale: bool
    missed: int            # display-changing releases the copy does not reflect
    crawl_after: float     # copy was crawled at or after this time (release N)
    crawl_before: float    # ... and before this time (release N+1, or observation time)
    age_lo_h: float        # crawl age at observation, lower bound (hours)
    age_hi_h: float        # crawl age at observation, upper bound (hours)
    newest_version: str
    newest_age_h: float    # hours since the newest release at observation


def bracket(timeline: list[Release], shown: Release, t_obs: float) -> Bracket:
    tl = [r for r in timeline if r.t <= t_obs]
    idx = next(i for i, r in enumerate(tl) if r.version == shown.version)
    nxt = tl[idx + 1] if idx + 1 < len(tl) else None
    newest = tl[-1]
    return Bracket(
        shown=shown.version,
        stale=nxt is not None,
        missed=len(tl) - 1 - idx,
        crawl_after=shown.t,
        crawl_before=nxt.t if nxt else t_obs,
        age_lo_h=(t_obs - nxt.t) / H if nxt else 0.0,
        age_hi_h=(t_obs - shown.t) / H,
        newest_version=newest.version,
        newest_age_h=(t_obs - newest.t) / H,
    )


def release_points(timeline: list[Release], shown: Release, t_obs: float, max_age_h: float = 30 * 24):
    """One (hours since release, reflected?) point per release within max_age_h of observation."""
    tl = [r for r in timeline if r.t <= t_obs]
    idx = next(i for i, r in enumerate(tl) if r.version == shown.version)
    pts = []
    for i, r in enumerate(tl):
        age = (t_obs - r.t) / H
        if age <= max_age_h:
            pts.append((age, i <= idx))
    return pts


BINS_H = [0, 6, 12, 24, 48, 96, 168, 336, 720]


def lag_curve(points, bins=BINS_H):
    """Share of releases reflected in the copy, by hours since release."""
    out = []
    for lo, hi in zip(bins, bins[1:]):
        sel = [ok for a, ok in points if lo <= a < hi]
        out.append({"lo_h": lo, "hi_h": hi, "n": len(sel),
                    "reflected": sum(sel), "share": (sum(sel) / len(sel)) if sel else None})
    return out


def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
