"""Version ordering and the 'display timeline' of a registry page.

A registry page does not always show the newest upload. PyPI and crates.io show the
highest stable version; npm shows the `latest` dist-tag; a GitHub releases page lists
newest-first by publish time. The display timeline is the sequence of
(time, version) at which the version shown at the top of the page changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_key(v: str):
    """Sortable key, or None if unparseable."""
    m = _SEMVER.match(v)
    if m:
        pre = m.group(4)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, _pre_key(pre))
    try:
        pv = Version(v)
    except InvalidVersion:
        return None
    rel = tuple(pv.release) + (0,) * (3 - len(pv.release))
    return rel[:3] + (0 if (pv.is_prerelease or pv.is_devrelease) else 1, (str(pv),)) + rel[3:]


def _pre_key(pre: str | None):
    if not pre:
        return ()
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))


def is_stable(v: str) -> bool:
    m = _SEMVER.match(v)
    if m:
        return m.group(4) is None
    try:
        pv = Version(v)
    except InvalidVersion:
        return False
    return not (pv.is_prerelease or pv.is_devrelease)


@dataclass(frozen=True)
class Release:
    version: str
    t: float  # unix seconds (UTC)


def display_timeline(releases: list[Release], rule: str) -> list[Release]:
    """Times at which the headline version of the page changed.

    rule = "max_stable": headline = highest stable version released so far (PyPI, crates.io, npm-approx).
    rule = "newest": headline = most recently published release (GitHub releases page).
    """
    rs = sorted(releases, key=lambda r: r.t)
    out: list[Release] = []
    if rule == "newest":
        return rs
    best = None
    for r in rs:
        if not is_stable(r.version):
            continue
        k = parse_key(r.version)
        if k is None:
            continue
        if best is None or k > best:
            best = k
            out.append(r)
    return out


def shown_at(timeline: list[Release], t: float) -> Release | None:
    """Headline release at time t (last timeline entry with time <= t)."""
    cur = None
    for r in timeline:
        if r.t <= t:
            cur = r
        else:
            break
    return cur
