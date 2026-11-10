"""Analysis: copy -> reflected release -> crawl-age bracket -> lag curves -> ranker eval.

python -m stale_map.analyze   (no network; reads data/, writes results/ and data/traces/)
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import random
import re
from collections import defaultdict
from datetime import datetime, timezone

from . import infer, ranker
from .config import CUTOFF, CUTOFF_ISO, HOLDOUT_MOD
from .extract import headline_match, normalize, reflected, token_re
from .mcp import structured
from .registries import RULE
from .versions import Release, display_timeline

D = pathlib.Path("data")
R = pathlib.Path("results")
DAY = 86400.0
REDIRECT = re.compile(r"^\s*#?\s*30[12] (Moved|Found)", re.I)
CHALLENGE = re.compile(r"(just a moment|verify you are human|checking your browser|enable javascript and cookies|captcha)", re.I)


SOURCE = "slim"  # analysis reads data/slim/*.gz (shipped); set STALE_MAP_SOURCE=raw to read data/raw


def _open(path: pathlib.Path):
    import gzip
    import os
    src = os.environ.get("STALE_MAP_SOURCE", SOURCE)
    if src == "slim":
        path = D / "slim" / (path.name + ".gz")
        return gzip.open(path, "rt").read() if path.exists() else None
    return path.read_text() if path.exists() else None


def load_calls(path):
    txt = _open(path)
    if txt is None:
        return []
    return [json.loads(line) for line in txt.splitlines() if line.strip()]


def results_by_url(calls):
    out = {}
    for c in calls:
        s = structured(c) if "response" in c else None
        if not s:
            continue
        for x in s.get("results", []):
            out[x["url"]] = (c, x)
        for e in s.get("errors") or []:
            u = e.get("url") if isinstance(e, dict) else None
            if u and u not in out:
                out[u] = (c, {"url": u, "error": e})
    return out


def text_of(x):
    parts = [x.get("title") or "", x.get("full_content") or "", " ".join(x.get("excerpts") or [])]
    return "\n".join(parts)


def acquired_ts(x):
    a = x.get("acquired_at")
    if not a:
        return None
    return datetime.fromisoformat(a.replace("Z", "+00:00")).timestamp()


def snippet(text, version, width=90):
    text = normalize(text)
    m = token_re(version).search(text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", text[max(0, m.start() - width): m.end() + width])


def percentile_ranks(vals: dict[str, float]) -> dict[str, float]:
    order = sorted(vals, key=lambda k: vals[k])
    n = len(order)
    return {k: (i + 0.5) / n for i, k in enumerate(order)}


def page_rows(mode="cached"):
    targets = json.loads((D / "targets.json").read_text())
    truth = {}
    for f in (D / "registry").glob("*.json"):
        truth[f.stem] = json.loads(f.read_text())
    res = results_by_url(load_calls(D / "raw" / f"fetch_{mode}.jsonl"))
    pops = defaultdict(dict)
    for t in targets:
        pops[t["registry"]][t["id"]] = t["popularity"] or 0
    pct = {r: percentile_ranks(v) for r, v in pops.items()}
    rows, traces = [], []
    for t in targets:
        pid = f"{t['registry']}:{t['id']}"
        row = {"pid": pid, "registry": t["registry"], "url": t["url"], "popularity": t["popularity"],
               "pop_pct": pct[t["registry"]][t["id"]], "holdout": ranker.is_holdout(pid, HOLDOUT_MOD)}
        tr = truth.get(t["registry"], {}).get(t["id"])
        if t["url"] not in res:
            row["status"] = "not_fetched"
            rows.append(row)
            continue
        call, x = res[t["url"]]
        t_obs = call["t_start"]
        row["t_obs"] = t_obs
        if "error" in x:
            row["status"] = "fetch_error"
            rows.append(row)
            continue
        if not tr:
            row["status"] = "no_truth"
            rows.append(row)
            continue
        rels = [Release(v, ts) for v, ts in tr["releases"]]
        full_tl = display_timeline(rels, RULE[t["registry"]])
        if full_tl and tr["latest_reported"] and full_tl[-1].version != tr["latest_reported"]:
            row["status"] = "display_rule_mismatch"  # page headline not predictable from release times
            rows.append(row)
            continue
        tl = [r for r in full_tl if r.t <= t_obs]
        text = text_of(x)
        acq = acquired_ts(x)
        row.update({"acquired_at": x.get("acquired_at"), "publish_date": x.get("publish_date"),
                    "content_len": len(x.get("full_content") or "")})
        shown, method = reflected(text, tl, t["registry"]) if tl else (None, "none")
        row["method"] = method
        if shown is None:
            row["status"] = ("redirect_stub" if REDIRECT.search(x.get("title") or "") else
                             "challenge_page" if CHALLENGE.search(text) else
                             "ambiguous_version" if method == "ambiguous" else "no_version_found")
            rows.append(row)
            traces.append({"pid": pid, "url": t["url"], "status": row["status"], "acquired_at": x.get("acquired_at"),
                           "title": x.get("title"), "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "head": re.sub(r"\s+", " ", (x.get("full_content") or "")[:300])})
            continue
        if method != "headline":
            # Free-text mentions can be roadmap text ("v1.0.0 coming soon"); keep only headline reads.
            row["status"] = "mention_only"
            rows.append(row)
            continue
        b = infer.bracket(tl, shown, t_obs)
        row.update({"status": "ok", "shown": b.shown, "newest": b.newest_version, "stale": b.stale,
                    "missed": b.missed, "age_lo_h": round(b.age_lo_h, 3), "age_hi_h": round(b.age_hi_h, 3),
                    "newest_age_h": round(b.newest_age_h, 3),
                    "headline_ok": headline_match(t["registry"], t["id"], b.shown, text)})
        if acq is not None:
            # acquired_at is a UTC date: crawl in [acq, acq + 1 day). Does it overlap the version bracket?
            row["acq_age_h"] = round((t_obs - acq) / 3600, 2)
            row["acq_consistent"] = (acq < b.crawl_before) and (acq + DAY > b.crawl_after)
        row["_points"] = infer.release_points(tl, shown, t_obs)
        row["_tl_before_cutoff"] = [r.t for r in tl if r.t <= CUTOFF]
        rows.append(row)
        traces.append({"pid": pid, "url": t["url"], "t_obs_utc": datetime.fromtimestamp(t_obs, timezone.utc).isoformat(),
                       "shown": b.shown, "newest": b.newest_version, "stale": b.stale,
                       "acquired_at": x.get("acquired_at"), "publish_date": x.get("publish_date"),
                       "title": x.get("title"), "evidence": snippet(text, b.shown),
                       "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "extract_id": (structured(call) or {}).get("extract_id")})
    return rows, traces


def site_stats(rows):
    out = {}
    for reg in sorted({r["registry"] for r in rows}):
        rs = [r for r in rows if r["registry"] == reg]
        ok = [r for r in rs if r.get("status") == "ok"]
        st = [r for r in ok if r["stale"]]
        lo = [r["age_lo_h"] for r in ok]
        acq = [r["acq_age_h"] for r in ok if r.get("acq_age_h") is not None]
        out[reg] = {
            "targets": len(rs), "fetched": sum(1 for r in rs if r.get("status") != "not_fetched"),
            "parsed": len(ok), "stale": len(st),
            "stale_share": len(st) / len(ok) if ok else None,
            "status_counts": dict(sorted(defaultdict(int, {s: sum(1 for r in rs if r.get("status") == s) for s in {r.get("status") for r in rs}}).items())),
            "crawl_age_lo_h_median": infer.quantile(lo, 0.5), "crawl_age_lo_h_p90": infer.quantile(lo, 0.9),
            "stale_age_lo_h_median": infer.quantile([r["age_lo_h"] for r in st], 0.5),
            "acquired_age_h_median": infer.quantile(acq, 0.5), "acquired_age_h_p90": infer.quantile(acq, 0.9),
            "acq_consistent": sum(1 for r in ok if r.get("acq_consistent")),
            "acq_checked": sum(1 for r in ok if "acq_consistent" in r),
            "headline_ok": sum(1 for r in ok if r.get("headline_ok")),
            "missed_median_stale": infer.quantile([r["missed"] for r in st], 0.5),
        }
    return out


def to_pages(rows):
    pages = []
    for r in rows:
        if r.get("status") != "ok":
            continue
        acq = r.get("acquired_at")
        crawl_t = (datetime.fromisoformat(acq.replace("Z", "+00:00")).timestamp() + DAY / 2) if acq else None
        pages.append(ranker.Page(pid=r["pid"], registry=r["registry"], popularity=r["pop_pct"],
                                 tl_times_before_cutoff=r["_tl_before_cutoff"], t_obs=r["t_obs"],
                                 crawl_t=crawl_t, stale=r["stale"]))
    return pages


def bootstrap_diff(pages, a, b, budget, n=1000, seed=1):
    """Bootstrap over pages: CI for catch-rate(a) - catch-rate(b) at a budget share."""
    pages = [p for p in pages if p.crawl_t is not None]
    sc = ranker.scores(pages, CUTOFF)
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        smp = [rnd.choice(pages) for _ in pages]
        ids = [f"{p.pid}#{i}" for i, p in enumerate(smp)]
        stale = {i for i, p in zip(ids, smp) if p.stale}
        if not stale:
            continue
        k = max(1, round(budget * len(smp)))
        vals = []
        for name in (a, b):
            if name == "uniform":
                vals.append(k / len(smp))
                continue
            s = {i: sc[name][p.pid] for i, p in zip(ids, smp)}
            vals.append(ranker.catch_rate(ranker.rank(s), stale, k))
        diffs.append(vals[0] - vals[1])
    diffs.sort()
    return {"mean": sum(diffs) / len(diffs), "ci95": [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]]}


def pilot():
    """Re-read the openai pilot calls with the same extractor and the PyPI timeline."""
    txt = _open(D / "raw" / "pilot_openai.json")
    tr = json.loads((D / "registry" / "pypi.json").read_text()).get("openai") if (D / "registry" / "pypi.json").exists() else None
    if not txt or not tr:
        return None
    rels = [Release(v, ts) for v, ts in tr["releases"]]
    tl = display_timeline(rels, "max_stable")
    out = {"calls": []}
    for c in json.loads(txt):
        s = structured(c)
        t_obs = c["t_start"]
        tlo = [r for r in tl if r.t <= t_obs]
        newest = tlo[-1]
        row = {"allow_live_fetch": c["args"]["allow_live_fetch"], "t_obs_utc": datetime.fromtimestamp(t_obs, timezone.utc).isoformat(timespec="seconds"),
               "newest": newest.version, "newest_released_utc": datetime.fromtimestamp(newest.t, timezone.utc).isoformat(timespec="seconds"),
               "errors": s.get("errors"), "warnings": s.get("warnings"), "results": []}
        for x in s["results"]:
            text = text_of(x)
            reg = "github" if "github.com" in x["url"] else "pypi"
            shown, method = reflected(text, tlo, reg)
            row["results"].append({"url": x["url"], "shown": shown.version if shown else None, "method": method,
                                   "acquired_at": x.get("acquired_at"), "publish_date": x.get("publish_date"),
                                   "evidence": snippet(text, shown.version) if shown else ""})
        out["calls"].append(row)
    return out


def pilot_search():
    """The one web_search call: newest openai version mentioned in each top-10 result's excerpts."""
    txt = _open(D / "raw" / "pilot_search_openai.json")
    tr = json.loads((D / "registry" / "pypi.json").read_text()).get("openai")
    if not txt or not tr:
        return None
    from .extract import reflected_release
    c = json.loads(txt)[0]
    tl = [r for r in display_timeline([Release(v, ts) for v, ts in tr["releases"]], "max_stable") if r.t <= c["t_start"]]
    out = {"t_obs_utc": datetime.fromtimestamp(c["t_start"], timezone.utc).isoformat(timespec="seconds"),
           "objective": c["args"]["objective"], "queries": c["args"]["search_queries"], "newest": tl[-1].version, "results": []}
    for i, x in enumerate(structured(c)["results"][:10], 1):
        r = reflected_release(text_of(x), tl)
        out["results"].append({"rank": i, "url": x["url"], "newest_mentioned": r.version if r else None})
    return out


def main():
    R.mkdir(exist_ok=True)
    (D / "traces").mkdir(exist_ok=True)
    rows, traces = page_rows("cached")
    live_rows, live_traces = page_rows("live") if load_calls(D / "raw" / "fetch_live.jsonl") else ([], [])
    pts = [p for r in rows if r.get("status") == "ok" for p in r["_points"]]
    curves = {"all": infer.lag_curve(pts)}
    for reg in sorted({r["registry"] for r in rows}):
        curves[reg] = infer.lag_curve([p for r in rows if r.get("status") == "ok" and r["registry"] == reg for p in r["_points"]])
    pages = to_pages(rows)
    hold = [p for p in pages if ranker.is_holdout(p.pid, HOLDOUT_MOD)]
    ev = ranker.evaluate(pages, CUTOFF)
    ev["bootstrap_50pct"] = {
        "change_clock_minus_age_poisson": bootstrap_diff(pages, "change_clock", "age_poisson", 0.5),
        "change_clock_minus_recency": bootstrap_diff(pages, "change_clock", "recency", 0.5),
        "recency_minus_change_rate": bootstrap_diff(pages, "recency", "change_rate", 0.5),
        "change_rate_minus_uniform": bootstrap_diff(pages, "change_rate", "uniform", 0.5),
    }
    ev_hold = ranker.evaluate(hold, CUTOFF)  # robustness: the hash-held-out third only
    within = {}
    for reg in sorted({p.registry for p in pages}):
        rp = [p for p in pages if p.registry == reg]
        if sum(p.stale for p in rp) >= 3:
            within[reg] = ranker.evaluate(rp, CUTOFF)
    live = None
    if live_rows:
        cached = {r["pid"]: r for r in rows}
        pairs = [(cached[r["pid"]], r) for r in live_rows if r.get("status") == "ok" and cached.get(r["pid"], {}).get("status") == "ok"]
        live = {"n_pairs": len(pairs),
                "cached_stale": sum(1 for c, _ in pairs if c["stale"]),
                "live_stale": sum(1 for _, lv in pairs if lv["stale"]),
                "fixed_by_live": sum(1 for c, lv in pairs if c["stale"] and not lv["stale"]),
                "same_acquired_at": sum(1 for c, lv in pairs if c.get("acquired_at") == lv.get("acquired_at")),
                "by_registry": {}}
        for reg in sorted({c["registry"] for c, _ in pairs}):
            ps = [(c, lv) for c, lv in pairs if c["registry"] == reg]
            live["by_registry"][reg] = {"n": len(ps), "cached_stale": sum(1 for c, _ in ps if c["stale"]),
                                        "live_stale": sum(1 for _, lv in ps if lv["stale"]),
                                        "fixed_by_live": sum(1 for c, lv in ps if c["stale"] and not lv["stale"])}
    obs = [r["t_obs"] for r in rows if r.get("t_obs")]
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff_utc": CUTOFF_ISO,
        "observed_utc": [datetime.fromtimestamp(min(obs), timezone.utc).isoformat(timespec="seconds"),
                         datetime.fromtimestamp(max(obs), timezone.utc).isoformat(timespec="seconds")] if obs else None,
        "n_targets": len(rows), "n_parsed": len(pages), "n_stale": sum(p.stale for p in pages),
        "n_release_points": len(pts),
        "sites": site_stats(rows), "lag_curves": curves, "ranker_heldout_day": ev, "ranker_hash_holdout_third": ev_hold, "ranker_within_registry": within,
        "live_vs_cached": live, "pilot": pilot(), "pilot_search": pilot_search(), "n_hash_holdout": len(hold),
    }
    (R / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    cols = ["pid", "registry", "url", "status", "shown", "newest", "stale", "missed", "age_lo_h", "age_hi_h",
            "newest_age_h", "method", "acquired_at", "acq_age_h", "acq_consistent", "headline_ok", "pop_pct", "holdout"]
    with (R / "pages.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with (D / "traces" / "cached.jsonl").open("w") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    if live_traces:
        with (D / "traces" / "live.jsonl").open("w") as f:
            for t in live_traces:
                f.write(json.dumps(t) + "\n")
    print(json.dumps({k: summary[k] for k in ["n_targets", "n_parsed", "n_stale", "observed_utc"]}))
    for reg, s in summary["sites"].items():
        print(reg, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()})
    print(json.dumps({k: v for k, v in ev.items() if k != "curve"}, indent=1)); print("hash-holdout", json.dumps(ev_hold["budget_for_90pct"]), ev_hold["n_pages"])


if __name__ == "__main__":
    main()
