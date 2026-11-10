"""Pick the live-refetch subset: up to 40 stale and 10 fresh pages per registry (seeded)."""
import csv
import json
import pathlib
import random

rows = [r for r in csv.DictReader(open("results/pages.csv")) if r["status"] == "ok"]
rnd = random.Random(11)
ids = []
for reg in sorted({r["registry"] for r in rows}):
    st = [r["pid"] for r in rows if r["registry"] == reg and r["stale"] == "True"]
    fr = [r["pid"] for r in rows if r["registry"] == reg and r["stale"] == "False"]
    rnd.shuffle(st)
    rnd.shuffle(fr)
    ids += st[:40] + fr[:10]
pathlib.Path("data/live_ids.json").write_text(json.dumps(sorted(ids), indent=0))
print(len(ids))
