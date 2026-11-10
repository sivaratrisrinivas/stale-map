"""Shrink raw MCP responses to what the analysis needs, so the repo can ship them.

Raw copies hold whole third-party pages (READMEs, changelogs). The slim copy keeps only
lines that contain a version-like token, each cut to 400 characters, plus all metadata
(url, title, publish_date, acquired_at, errors, extract_id). Every headline pattern used
by the extractor sits on a single line, so analysis results are identical on slim data
(tests/test_slim.py and `make check` verify this).
"""
from __future__ import annotations

import gzip
import json
import pathlib
import re

from .extract import _TOKEN, normalize

RAW = pathlib.Path("data/raw")
SLIM = pathlib.Path("data/slim")


def slim_text(text: str | None, max_line: int = 400) -> str | None:
    if text is None:
        return None
    keep = [ln[:max_line] for ln in normalize(text).splitlines() if _TOKEN.search(ln)]
    return "\n".join(keep)


def slim_call(c: dict) -> dict:
    c = json.loads(json.dumps(c))
    res = (c.get("response") or {}).get("result") or {}
    sc = res.get("structuredContent")
    if sc is None:
        for item in res.get("content", []):
            if item.get("type") == "text":
                try:
                    sc = json.loads(item["text"])
                except Exception:
                    sc = None
    if sc is not None:
        for x in sc.get("results", []):
            x["full_content"] = slim_text(x.get("full_content"))
            x["excerpts"] = [slim_text(e) for e in (x.get("excerpts") or [])]
        res["structuredContent"] = sc
        res["content"] = []
    return c


def main():
    SLIM.mkdir(parents=True, exist_ok=True)
    for f in sorted(RAW.glob("*.jsonl")) + sorted(RAW.glob("pilot_*.json")):
        if f.suffix == ".jsonl":
            lines = [json.dumps(slim_call(json.loads(ln))) for ln in f.read_text().splitlines()]
            data = "\n".join(lines) + "\n"
        else:
            data = json.dumps([slim_call(c) for c in json.loads(f.read_text())])
        with gzip.open(SLIM / (f.name + ".gz"), "wt") as g:
            g.write(data)
        print(f.name, len(data), "->", (SLIM / (f.name + ".gz")).stat().st_size, "bytes gz")


if __name__ == "__main__":
    main()
