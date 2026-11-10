"""Collection: Parallel web_fetch (cached / live) for each target page, then registry ground truth.

Usage:
  python -m stale_map.collect fetch --live 0          # cached copies for all targets
  python -m stale_map.collect truth                   # registry release times
  python -m stale_map.collect fetch --live 1 --ids-file data/live_ids.json
Raw responses are appended to data/raw/*.jsonl and never edited.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import time

from . import registries
from .config import OBJECTIVE
from .mcp import ParallelMCP

RAW = pathlib.Path("data/raw")
TRUTH = pathlib.Path("data/registry")


def load_targets():
    return json.loads(pathlib.Path("data/targets.json").read_text())


def done_urls(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    s = set()
    for line in path.read_text().splitlines():
        s.update(json.loads(line)["args"]["urls"])
    return s


def fetch(live: bool, ids: list[str] | None, batch: int, max_calls: int):
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / ("fetch_live.jsonl" if live else "fetch_cached.jsonl")
    targets = load_targets()
    if ids is not None:
        idset = set(ids)
        targets = [t for t in targets if f"{t['registry']}:{t['id']}" in idset]
    seen = done_urls(out)
    todo = [t for t in targets if t["url"] not in seen]
    random.Random(7).shuffle(todo)
    todo.sort(key=lambda t: t["registry"])  # one registry per call, stable within
    m = ParallelMCP()
    calls = 0
    for reg in sorted({t["registry"] for t in todo}):
        rt = [t for t in todo if t["registry"] == reg]
        for i in range(0, len(rt), batch):
            if calls >= max_calls:
                return
            urls = [t["url"] for t in rt[i:i + batch]]
            try:
                r = m.web_fetch(urls, OBJECTIVE, allow_live_fetch=live)
            except Exception as e:  # keep going; record the failure
                r = {"tool": "web_fetch", "args": {"urls": urls, "allow_live_fetch": live},
                     "t_start": time.time(), "t_end": time.time(), "error": str(e)[:500]}
            with out.open("a") as f:
                f.write(json.dumps(r) + "\n")
            calls += 1
            print(reg, i + len(urls), "/", len(rt), round(r["t_end"] - r["t_start"], 1), "s",
                  "ERR" if "error" in r else "", flush=True)


def truth():
    TRUTH.mkdir(parents=True, exist_ok=True)
    targets = load_targets()
    for reg in sorted({t["registry"] for t in targets}):
        path = TRUTH / f"{reg}.json"
        have = json.loads(path.read_text()) if path.exists() else {}
        for t in targets:
            if t["registry"] != reg or t["id"] in have:
                continue
            d = registries.FETCHERS[reg](t["id"])
            if d is None:
                continue
            have[t["id"]] = {"fetched_at": time.time(), "latest_reported": d["latest_reported"],
                             "releases": [[r.version, r.t] for r in d["releases"]]}
            if len(have) % 25 == 0:
                path.write_text(json.dumps(have))
        path.write_text(json.dumps(have))
        print(reg, len(have), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "truth"])
    ap.add_argument("--live", type=int, default=0)
    ap.add_argument("--ids-file")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--max-calls", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "fetch":
        ids = json.loads(pathlib.Path(a.ids_file).read_text()) if a.ids_file else None
        fetch(bool(a.live), ids, a.batch, a.max_calls)
    else:
        truth()
