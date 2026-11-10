"""Find which release a cached page copy reflects, using code checks only (no LLM judge).

Two rules, in order:
1. headline: the version shown in the page's own headline slot
   (PyPI "# name X", npm "X • Public", crates.io "name vX", GitHub "X ... Latest").
2. mention: otherwise, the newest known version that appears as a whole token anywhere
   in the copy. A copy cannot mention a version that did not exist when it was crawled,
   so this is the newest release the crawler had seen. Bare two-part numbers such as
   "3.10" are not accepted here, since they collide with Python versions and the like.
"""
from __future__ import annotations

import re

from .versions import Release

_AFTER = r"(?![0-9A-Za-z]|[.\-+][0-9A-Za-z])"
_TOKEN = re.compile(r"(?<![0-9A-Za-z.])v?(\d[0-9A-Za-z]*(?:[.\-+][0-9A-Za-z]+)*)")


def normalize(text: str) -> str:
    """Undo markdown escaping that splits versions, e.g. '19\\.3.1' -> '19.3.1'."""
    return text.replace("\\.", ".").replace("\\-", "-").replace("\\_", "_")


def _bare(v: str) -> str:
    return v[1:] if v[:1] == "v" and v[1:2].isdigit() else v


def token_re(version: str) -> re.Pattern:
    return re.compile(r"(?<![0-9A-Za-z.])v?" + re.escape(_bare(version)) + _AFTER)


def mentioned(text: str, timeline: list[Release]) -> list[Release]:
    text = normalize(text)
    toks = set(_TOKEN.findall(text))
    out = []
    for r in timeline:
        b = _bare(r.version)
        if b[:1].isdigit():
            if b in toks:
                out.append(r)
        elif token_re(r.version).search(text):  # tags like 'release-1.2' or 'next@15.0.1'
            out.append(r)
    return out


def specific(version: str) -> bool:
    """Distinctive enough to trust as a free-text mention."""
    b = _bare(version)
    return b.count(".") >= 2 or not re.fullmatch(r"[\d.]+", b)


HEADLINE = {
    "pypi": lambda v: re.compile(r"#\s*[\w.\-]+\s+" + re.escape(v) + _AFTER, re.I),
    "npm": lambda v: re.compile(re.escape(v) + _AFTER + r"\s*•\s*Public", re.I),
    "crates": lambda v: re.compile(r"#\s*[\w\-]+\s+v" + re.escape(v) + _AFTER, re.I),
    "github": lambda v: re.compile(r"(?<![0-9A-Za-z.])" + re.escape(v) + _AFTER + r"[^\n]{0,200}\]\([^)]*/releases/latest\)", re.S),
}


def headline_match(registry: str, name: str, version: str, text: str) -> bool:
    return bool(HEADLINE[registry](version).search(normalize(text)))


def reflected(text: str, timeline: list[Release], registry: str) -> tuple[Release | None, str]:
    text = normalize(text)
    hits = mentioned(text, timeline)
    if not hits:
        return None, "none"
    head = [r for r in hits if HEADLINE[registry](r.version).search(text)]
    if head:
        return max(head, key=lambda r: r.t), "headline"
    spec = [r for r in hits if specific(r.version)]
    if spec:
        return max(spec, key=lambda r: r.t), "mention"
    return None, "ambiguous"


def reflected_release(text: str, timeline: list[Release]) -> Release | None:
    """Newest mentioned version (rule 2 only). Kept for tests and audits."""
    hits = mentioned(text, timeline)
    return max(hits, key=lambda r: r.t) if hits else None
