"""Build the page sample: popular pages per registry with a release in the 30 days before the cutoff.

Writes data/targets.json. Uses only registry JSON APIs and the gh CLI. No Parallel calls.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from stale_map import polite, registries  # noqa: E402
from stale_map.config import ACTIVE_WINDOW_DAYS, CUTOFF, TARGET_COUNTS  # noqa: E402
from stale_map.versions import display_timeline  # noqa: E402

LO = CUTOFF - ACTIVE_WINDOW_DAYS * 86400
OUT = pathlib.Path("data/targets.json")


def active(rels, rule):
    tl = [r for r in display_timeline(rels, rule) if r.t <= CUTOFF]
    return any(LO < r.t <= CUTOFF for r in tl)


def pick(registry, candidates):
    """candidates: list of (id, popularity) in popularity order."""
    got = []
    for pid, pop in candidates:
        if len(got) >= TARGET_COUNTS[registry]:
            break
        d = registries.FETCHERS[registry](pid)
        if not d or not d["releases"]:
            continue
        if active(d["releases"], registries.RULE[registry]):
            got.append({"registry": registry, "id": pid, "popularity": pop,
                        "url": registries.PAGE_URL[registry].format(pid)})
            print(registry, len(got), pid, flush=True)
    return got


def pypi_candidates():
    d = polite.get_json("https://hugovk.dev/top-pypi-packages/top-pypi-packages-30-days.min.json")
    return [(r["project"], r["download_count"]) for r in d["rows"][:1500]]


def npm_candidates():
    src = pathlib.Path("data/npm-top-download.js").read_text()
    names = re.findall(r"'([^']+)'", src)[:1500]
    pops = {}
    plain = [n for n in names if not n.startswith("@")]
    for i in range(0, len(plain), 128):
        chunk = plain[i:i + 128]
        d = polite.get_json("https://api.npmjs.org/downloads/point/last-month/" + ",".join(chunk)) or {}
        for k, v in d.items():
            if v:
                pops[k] = v.get("downloads", 0)
    return sorted(((n, pops[n]) for n in plain if n in pops), key=lambda x: -x[1])


def crates_candidates():
    out = []
    for page in range(1, 9):
        d = polite.get_json(f"https://crates.io/api/v1/crates?sort=recent-downloads&per_page=100&page={page}")
        for c in d["crates"]:
            # Cheap pre-filter from the listing; exact check happens in pick().
            if c.get("updated_at", "") >= "2026-10":
                out.append((c["id"], c["recent_downloads"]))
    return out


def github_candidates():
    out, seen = [], set()
    for page in range(1, 11):
        d = registries.gh_api(f"search/repositories?q=stars:%3E5000+pushed:%3E2026-10-01&sort=stars&order=desc&per_page=100&page={page}")
        for r in (d or {}).get("items", []):
            if r["full_name"] not in seen and not r.get("archived"):
                seen.add(r["full_name"])
                out.append((r["full_name"], r["stargazers_count"]))
    return out


if __name__ == "__main__":
    which = sys.argv[1:] or ["pypi", "npm", "crates", "github"]
    targets = json.loads(OUT.read_text()) if OUT.exists() else []
    targets = [t for t in targets if t["registry"] not in which]
    for reg in which:
        cands = globals()[f"{reg}_candidates"]()
        print(reg, "candidates", len(cands), flush=True)
        targets += pick(reg, cands)
        OUT.write_text(json.dumps(targets, indent=1))
    print("total", len(targets))
