"""Build the static results page from results/summary.json. Every number on the page is read from it."""
import csv
import html
import json
import pathlib
import shutil
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = json.loads((ROOT / "results/summary.json").read_text())
IST = timezone(timedelta(hours=5, minutes=30))
REG_NAME = {"pypi": "PyPI", "npm": "npm", "crates": "crates.io", "github": "GitHub Releases"}
COLORS = {"pypi": "#3b6ea8", "npm": "#c0392b", "crates": "#d68910", "github": "#2e7d4f", "all": "#222"}


def ist(iso):
    return datetime.fromisoformat(iso).astimezone(IST).strftime("%-d %b, %-I:%M %p IST")


def pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def hours(h):
    if h is None:
        return "n/a"
    if h < 48:
        return f"{h:.0f} h"
    return f"{h / 24:.1f} days"


def lag_svg():
    W, Hh, L, B, T, Rr = 760, 300, 48, 46, 16, 120
    bins = S["lag_curves"]["all"]
    n = len(bins)
    xw = (W - L - Rr) / n
    out = [f'<svg viewBox="0 0 {W} {Hh}" role="img" aria-label="Share of releases reflected by hours since release">']
    for g in (0, .25, .5, .75, 1):
        y = T + (Hh - T - B) * (1 - g)
        out.append(f'<line x1="{L}" x2="{W - Rr}" y1="{y}" y2="{y}" stroke="#e5e5e5"/><text x="{L - 6}" y="{y + 4}" text-anchor="end" class="ax">{int(g * 100)}%</text>')
    for i, b in enumerate(bins):
        x = L + xw * (i + .5)
        lab = f'{b["lo_h"]}–{b["hi_h"]}h' if b["hi_h"] <= 48 else f'{b["lo_h"] // 24}–{b["hi_h"] // 24}d'
        out.append(f'<text x="{x}" y="{Hh - B + 16}" text-anchor="middle" class="ax">{lab}</text>')
    out.append(f'<text x="{(W - Rr + L) / 2}" y="{Hh - 6}" text-anchor="middle" class="ax">time since the release was published</text>')
    for k, li in enumerate(["all"] + [r for r in ["pypi", "npm", "crates", "github"] if r in S["lag_curves"]]):
        pts = []
        for i, b in enumerate(S["lag_curves"][li]):
            if b["share"] is None or b["n"] < 3:
                continue
            x = L + xw * (i + .5)
            y = T + (Hh - T - B) * (1 - b["share"])
            pts.append((x, y, b))
        if not pts:
            continue
        sw = 3 if li == "all" else 1.8
        dash = "" if li == "all" else ""
        out.append(f'<polyline fill="none" stroke="{COLORS[li]}" stroke-width="{sw}" {dash} points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)}"/>')
        for x, y, b in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.5 if li == "all" else 2.5}" fill="{COLORS[li]}"><title>{REG_NAME.get(li, "All")}: {b["reflected"]}/{b["n"]} releases reflected</title></circle>')
        out.append(f'<text x="{W - Rr + 10}" y="{T + 14 + k * 18}" fill="{COLORS[li]}" class="lg">{REG_NAME.get(li, "All registries")}</text>')
    out.append("</svg>")
    return "\n".join(out)


POL = [("uniform", "Uniform (random)", "#9aa5b1", "5,4"), ("popularity", "Popularity", "#b07aa1", ""),
       ("change_rate", "Change rate (Poisson)", "#d68910", ""), ("recency", "Most recent release", "#3b6ea8", ""),
       ("age_poisson", "Poisson + crawl age", "#7f8c8d", ""), ("change_clock", "Change clock (this repo)", "#2e7d4f", ""),
       ("oracle", "Perfect ranking", "#222", "2,3")]


def ranker_svg():
    ev = S["ranker_heldout_day"]
    c = ev["curve"]
    W, Hh, L, B, T, Rr = 760, 320, 48, 46, 14, 200
    out = [f'<svg viewBox="0 0 {W} {Hh}" role="img" aria-label="Share of stale pages caught by crawl budget">']
    X = lambda g: L + (W - L - Rr) * g
    Y = lambda v: T + (Hh - T - B) * (1 - v)
    for g in (0, .25, .5, .75, 1):
        out.append(f'<line x1="{L}" x2="{W - Rr}" y1="{Y(g)}" y2="{Y(g)}" stroke="#e5e5e5"/><text x="{L - 6}" y="{Y(g) + 4}" text-anchor="end" class="ax">{int(g * 100)}%</text>')
        out.append(f'<text x="{X(g)}" y="{Hh - B + 16}" text-anchor="middle" class="ax">{int(g * 100)}%</text>')
    out.append(f'<text x="{X(.5)}" y="{Hh - 6}" text-anchor="middle" class="ax">crawl budget (share of pages refetched)</text>')
    for k, (key, name, col, dash) in enumerate(POL):
        ys = c[key]
        pts = " ".join(f"{X(g):.1f},{Y(v):.1f}" for g, v in zip(c["budget"], ys) if v is not None)
        sw = 3 if key == "change_clock" else 1.6
        out.append(f'<polyline fill="none" stroke="{col}" stroke-width="{sw}" stroke-dasharray="{dash}" points="{pts}"/>')
        out.append(f'<text x="{W - Rr + 12}" y="{T + 14 + k * 19}" fill="{col}" class="lg">{name}</text>')
    out.append("</svg>")
    return "\n".join(out)


def site_table():
    rows = []
    for reg, s in S["sites"].items():
        rows.append(f"<tr><td>{REG_NAME[reg]}</td><td>{s['parsed']}</td><td>{s['stale']} ({pct(s['stale_share'])})</td>"
                    f"<td>{hours(s['acquired_age_h_median'])}</td><td>{hours(s['acquired_age_h_p90'])}</td>"
                    f"<td>{hours(s['stale_age_lo_h_median'])}</td><td>{s['acq_consistent']}/{s['acq_checked']}</td></tr>")
    return "\n".join(rows)


def ranker_table():
    ev = S["ranker_heldout_day"]
    bs = list(ev["budgets"])
    head = "".join(f"<th>catch @ {b}</th>" for b in bs) + "<th>budget for 90%</th>"
    body = []
    for key, name, _, _ in POL:
        need = ev["budget_for_90pct"].get(key)
        cells = "".join(f"<td>{pct(ev['budgets'][b][key])}</td>" for b in bs)
        nd = pct(need) if key != "oracle" else pct(0.9 * ev["n_stale"] / ev["n_pages"])
        body.append(f"<tr{' class=hl' if key == 'change_clock' else ''}><td>{name}</td>{cells}<td>{nd}</td></tr>")
    return f"<table><tr><th>policy</th>{head}</tr>{''.join(body)}</table>"


def pilot_block():
    p = S.get("pilot")
    if not p:
        return ""
    c0 = p["calls"][0]
    by = {}
    for c in p["calls"]:
        for r in c["results"]:
            by[(c["allow_live_fetch"], "pypi" if "pypi" in r["url"] else "gh")] = r
    pc, pl, gh = by.get((False, "pypi")), by.get((True, "pypi")), by.get((False, "gh"))
    return f"""
<div class="pilot">
 <div class="cell"><div class="k">PyPI says</div><div class="v">openai {c0['newest']}</div><div class="s">published {ist(c0['newest_released_utc'])}</div></div>
 <div class="cell bad"><div class="k">Parallel's copy of pypi.org/project/openai</div><div class="v">openai {pc['shown']}</div><div class="s">acquired_at {pc['acquired_at'][:10]} · same with allow_live_fetch=true ({pl['shown']}, acquired_at {pl['acquired_at'][:10]}) · errors: none · warnings: none</div></div>
 <div class="cell good"><div class="k">Same call, github.com/openai/openai-python/releases</div><div class="v">v{gh['shown']}</div><div class="s">acquired_at {gh['acquired_at'][:10]}</div></div>
</div>
<p class="note">Checked {ist(c0['t_obs_utc'])}, about {round((datetime.fromisoformat(c0['t_obs_utc']) - datetime.fromisoformat(c0['newest_released_utc'])).total_seconds() / 3600)} hours after the release.</p>"""


def lag_numbers():
    b = S["lag_curves"]["all"]
    first2d = [x for x in b if x["hi_h"] <= 48]
    wk = [x for x in b if 168 <= x["lo_h"] and x["hi_h"] <= 336]
    m = [x for x in b if x["lo_h"] >= 336]
    f = lambda xs: (sum(x["reflected"] for x in xs), sum(x["n"] for x in xs))
    return f(first2d), f(wk), f(m)


def search_line():
    ps = S.get("pilot_search")
    if not ps:
        return ""
    cur = [r for r in ps["results"] if r["newest_mentioned"] == ps["newest"]]
    pypi = [r for r in ps["results"] if "pypi.org" in r["url"]]
    parts = [f"A <code>web_search</code> for the latest openai SDK ({ist(ps['t_obs_utc'])}) returned {len(ps['results'])} results."]
    parts.append(f"{len(cur)} of them mentioned {ps['newest']}" + (f" (rank {', '.join(str(r['rank']) for r in cur)}: {', '.join(r['url'].split('/')[2] for r in cur)})." if cur else "."))
    if pypi:
        parts.append("PyPI results: " + "; ".join(f"rank {r['rank']} {r['url'].replace('https://', '')} → newest version in excerpt {r['newest_mentioned']}" for r in pypi) + ".")
    return " ".join(parts)


def readme_ctx():
    p = S["pilot"]["calls"]
    c0 = p[0]
    by = {("pypi" if "pypi" in r["url"] else "gh"): r for r in c0["results"]}
    site_md = ["| site | pages read | stale copies | median crawl age | p90 crawl age | median lag of stale copies (at least) | acquired_at agrees |",
               "|---|---|---|---|---|---|---|"]
    for reg, x in S["sites"].items():
        site_md.append(f"| {REG_NAME[reg]} | {x['parsed']} of {x['targets']} | {x['stale']} ({pct(x['stale_share'])}) | "
                       f"{hours(x['acquired_age_h_median'])} | {hours(x['acquired_age_h_p90'])} | {hours(x['stale_age_lo_h_median'])} | "
                       f"{x['acq_consistent']}/{x['acq_checked']} |")
    ev = S["ranker_heldout_day"]
    bs = list(ev["budgets"])
    rank_md = ["| policy | " + " | ".join(f"catch @ {b} budget" for b in bs) + " | budget to catch 90% |",
               "|---|" + "---|" * (len(bs) + 1)]
    for key, name, _, _ in POL:
        need = ev["budget_for_90pct"].get(key) if key != "oracle" else 0.9 * ev["n_stale"] / ev["n_pages"]
        rank_md.append(f"| {name} | " + " | ".join(pct(ev["budgets"][b][key]) for b in bs) + f" | {pct(need)} |")
    lv = S.get("live_vs_cached")
    if lv:
        live_md = (f"I refetched {lv['n_pairs']} readable pages (up to 40 stale and 10 fresh per registry, seeded) with `allow_live_fetch: true`. "
                   f"{lv['fixed_by_live']} of {lv['cached_stale']} stale copies came back current, and {lv['live_stale']} of the {lv['n_pairs']} were stale on the live call. "
                   f"{lv['same_acquired_at']} of {lv['n_pairs']} live responses carried the same `acquired_at` as the cached copy.\n\n"
                   "| site | pages | stale (cached) | stale (live) | fixed by live |\n|---|---|---|---|---|\n" +
                   "\n".join(f"| {REG_NAME[r]} | {v['n']} | {v['cached_stale']} | {v['live_stale']} | {v['fixed_by_live']} |" for r, v in lv["by_registry"].items()))
    else:
        live_md = "Not run."
    ex = []
    for reg, x in S["sites"].items():
        bad = {k: v for k, v in x["status_counts"].items() if k != "ok"}
        if bad:
            ex.append(f"- {REG_NAME[reg]}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in bad.items()))
    ex.append("- Status meanings: *fetch error*: the MCP returned `cache_miss` for the URL. *redirect stub*: the cached copy is a `301 Moved Permanently` page. "
              "*display rule mismatch*: our headline rule disagrees with the registry's own latest (for example, an npm `latest` tag pointing at an older major). "
              "*no version found*: no known stable version in a headline slot, usually GitHub repos with non-semver tags such as `b12242`, `r187` or `pkg@1.2.3`. "
              "*mention only*: the version appeared only in free text, which we don't trust.")
    h = S["ranker_hash_holdout_third"]
    wr = S["ranker_within_registry"]
    b50 = S["ranker_heldout_day"]["bootstrap_50pct"]
    lvx = S.get("live_vs_cached") or {}
    p_hours = round((datetime.fromisoformat(c0["t_obs_utc"]) - datetime.fromisoformat(c0["newest_released_utc"])).total_seconds() / 3600)
    return dict(p_hours=p_hours, hold_n=h["n_pages"], hold_stale=h["n_stale"], hold_cc=pct(h["budget_for_90pct"]["change_clock"]),
                hold_ap=pct(h["budget_for_90pct"]["age_poisson"]), hold_rc=pct(h["budget_for_90pct"]["recency"]),
                within_cc=", ".join(f"{REG_NAME[r]} {pct(v['budget_for_90pct']['change_clock'])}" for r, v in wr.items()),
                within_ap=", ".join(f"{REG_NAME[r]} {pct(v['budget_for_90pct']['age_poisson'])}" for r, v in wr.items()),
                ci_cru=" to ".join(f"{100 * x:+.0f}" for x in b50["change_rate_minus_uniform"]["ci95"]),
                ci_rcr=" to ".join(f"{100 * x:+.0f}" for x in b50["recency_minus_change_rate"]["ci95"]),
                live_same=lvx.get("same_acquired_at"), live_n=lvx.get("n_pairs"),
                search_line=search_line(), search_md=search_line().replace("<code>", "`").replace("</code>", "`"), p_new=c0["newest"], p_rel=ist(c0["newest_released_utc"]), p_obs=ist(c0["t_obs_utc"]), p_shown=by["pypi"]["shown"],
                p_acq=by["pypi"]["acquired_at"][:10], p_gh=by["gh"]["shown"], p_gh_acq=by["gh"]["acquired_at"][:10],
                site_md="\n".join(site_md), rank_md="\n".join(rank_md), live_md=live_md, excl_md="\n".join(ex))


def main():
    ev = S["ranker_heldout_day"]
    lv = S.get("live_vs_cached") or {}
    b50 = ev["bootstrap_50pct"]
    tot = {k: sum(s[k] for s in S["sites"].values()) for k in ["targets", "parsed", "stale", "acq_consistent", "acq_checked", "headline_ok"]}
    (r2, n2), (rw, nw), (rm, nm) = lag_numbers()
    need = ev["budget_for_90pct"]
    ctx = dict(
        pilot=pilot_block(), lag=lag_svg(), ranker=ranker_svg(), sites=site_table(), rtable=ranker_table(),
        n_targets=tot["targets"], n_parsed=tot["parsed"], n_stale=tot["stale"], stale_pct=pct(tot["stale"] / tot["parsed"]),
        acq_ok=tot["acq_consistent"], acq_n=tot["acq_checked"], head_ok=tot["headline_ok"], n_points=S["n_release_points"],
        r2=r2, n2=n2, rw=rw, nw=nw, rm=rm, nm=nm,
        obs=f"{ist(S['observed_utc'][0])} to {ist(S['observed_utc'][1])}", cutoff=ist(S["cutoff_utc"]),
        n_eval=ev["n_pages"], n_eval_stale=ev["n_stale"], day_only=ev["stale_only_after_cutoff"],
        need_cc=pct(need["change_clock"]), need_ap=pct(need["age_poisson"]), need_rc=pct(need["recency"]),
        need_cr=pct(need["change_rate"]), need_pop=pct(need["popularity"]), need_or=pct(0.9 * ev["n_stale"] / ev["n_pages"]),
        cc50=pct(ev["budgets"]["50%"]["change_clock"]), ap50=pct(ev["budgets"]["50%"]["age_poisson"]),
        ci_ap=" to ".join(f"{100 * x:+.0f}" for x in b50["change_clock_minus_age_poisson"]["ci95"]),
        live=(f"We refetched {lv.get('n_pairs')} of these pages with <code>allow_live_fetch: true</code>. {lv.get('fixed_by_live')} of the "
              f"{lv.get('cached_stale')} stale copies came back current, and {lv.get('same_acquired_at')} of {lv.get('n_pairs')} returned the same <code>acquired_at</code> as the cached copy."
              if lv else "Live refetch was not run."),
    )
    ctx.update(readme_ctx())
    tpl = (ROOT / "site/template.html").read_text()
    for k, v in ctx.items():
        tpl = tpl.replace("{{" + k + "}}", str(v))
    assert "{{" not in tpl, "unfilled placeholder: " + tpl[tpl.index("{{"):tpl.index("{{") + 30]
    dist = ROOT / "site/dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text(tpl)
    (dist / "data").mkdir(exist_ok=True)
    shutil.copy(ROOT / "results/summary.json", dist / "data/summary.json")
    shutil.copy(ROOT / "results/pages.csv", dist / "data/pages.csv")
    for f in (ROOT / "data/traces").glob("*.jsonl"):
        shutil.copy(f, dist / "data" / f.name)
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (dist / "vercel.json").write_text(json.dumps({"headers": [{"source": "/(.*)", "headers": [
        {"key": "X-Robots-Tag", "value": "noindex, nofollow"}]}]}, indent=1))
    md = (ROOT / "README.tpl.md").read_text()
    for k, v in ctx.items():
        md = md.replace("{{" + k + "}}", str(v))
    assert "{{" not in md, "unfilled README placeholder: " + md[md.index("{{"):md.index("{{") + 30]
    (ROOT / "README.md").write_text(md)
    print("wrote", dist / "index.html", "and README.md")


if __name__ == "__main__":
    main()
