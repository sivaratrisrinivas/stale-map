# Stale Map

How old is the copy of a page that an agent reads through a search index? Package registries make this measurable from the outside. PyPI, npm, crates.io and GitHub Releases record the exact second every release goes out, so they act as a free, exact change clock. This repo uses that clock to measure how far behind Parallel's index is on {{n_parsed}} registry pages, and to score recrawl policies against it.

This is a **pilot**: one snapshot on one morning, using only Parallel's free public MCP. It's offered as data that might be useful, not as a verdict on Parallel's index, which may already track all of this internally.

## The one-release version

openai {{p_new}} went up on PyPI at {{p_rel}}. At {{p_obs}}, Parallel's `web_fetch` copy of `pypi.org/project/openai/` still showed **{{p_shown}}** (`acquired_at` {{p_acq}}). It showed the same with `allow_live_fetch: true`, and `errors` and `warnings` were both empty. In the same call, `github.com/openai/openai-python/releases` showed **v{{p_gh}}** (`acquired_at` {{p_gh_acq}}).

{{search_md}}

## Results ({{obs}})

- Sample: {{n_targets}} popular pages (150 PyPI, 150 npm, 100 crates.io, 100 GitHub Releases), each with at least one release in the 30 days before {{cutoff}}. {{n_parsed}} could be read with a code check. The rest are listed under Exclusions below.
- {{n_stale}} of {{n_parsed}} copies ({{stale_pct}}) were missing at least one release.
- Lag curve, for releases in the last 30 days: under 48 h old, {{r2}} of {{n2}} were reflected. 7 to 14 days old: {{rw}} of {{nw}}. 14 to 30 days old: {{rm}} of {{nm}}.
- Validation: the version bracket (crawled after release N and before N+1, from registry timestamps alone) agreed with Parallel's own `acquired_at` date on {{acq_ok}} of {{acq_n}} pages.

{{site_md}}

"Crawl age" is observation time minus `acquired_at`, which is a UTC date, so it's accurate to within a day. "Lag of stale copies" is a lower bound: the time since the first release the copy is missing.

### Recrawl ranking on a held-out day

Every feature is frozen at {{cutoff}}. The label is whether the copy was stale at observation, about 24 hours later. Nothing is fitted on labels. The 90-day rate window and the 0.5 prior were set before collection. Pages evaluated: {{n_eval}}, of which {{n_eval_stale}} were stale.

{{rank_md}}

- **Outside view**, where crawl times are unknown: popularity does worse than random. The classic Poisson change-rate order (Cho & Garcia-Molina) is only a little better than random: at a 50% budget, the bootstrap 95% CI against uniform is {{ci_cru}} points, which includes zero. "Most recent release first" is the best outside-view policy, beating change rate by {{ci_rcr}} points at a 50% budget.
- **Index-owner view**, where crawl times are known, as `acquired_at` exposes them: the change clock needs {{need_cc}} of the budget to catch 90% of stale pages, about the same as a perfect ranking ({{need_or}}). Poisson with crawl age needs {{need_ap}}. At a 50% budget, the bootstrap 95% CI of change clock minus Poisson-with-crawl-age is {{ci_ap}} points.
- Only {{day_only}} of the {{n_eval_stale}} stale pages went stale during the held-out day itself. Everything else was already visible in public timestamps before it began. For registry-style pages, recrawl is mostly a lookup, not a forecast.
- Robustness: on the hash-held-out third ({{hold_n}} pages, {{hold_stale}} stale), the budget to catch 90% is {{hold_cc}} for the change clock, {{hold_ap}} for Poisson with crawl age and {{hold_rc}} for most-recent-release. Within each registry, the change clock needs {{within_cc}}, against {{within_ap}} for Poisson with crawl age. So the gain doesn't come from simply ranking one site above another.

### Live fetch

{{live_md}}

## Practical tip

For registry domains, Parallel's Extract API has the knob already. Set `advanced_settings.fetch_policy.max_age_seconds` (minimum 600) and `disable_cache_fallback: true`, so a failed live fetch returns an error instead of an old copy. This comes from Parallel's docs (Advanced Extract Settings). **I didn't test it**, because this study used no API key. On the free MCP, read `acquired_at` and check the registry JSON (`pypi.org/pypi/<name>/json`, `registry.npmjs.org/<name>`) before trusting a "latest version" answer.

## Method

1. `scripts/build_targets.py`: picks popular pages per registry (top-pypi-packages 30-day downloads, npm-high-impact plus npm download counts, crates.io recent downloads, and GitHub stars) that had a headline-changing release in the 30 days before the cutoff.
2. `stale_map/collect.py fetch`: calls Parallel's free MCP `web_fetch` with `full_content: true`, `allow_live_fetch: false`, 20 URLs per call, one call every 8 seconds or more, with exponential backoff. The tool allowlist has only `web_fetch` and `web_search`. `send_feedback` is refused in code and tested.
3. `stale_map/collect.py truth`: pulls release timestamps from the registry JSON APIs and the GitHub API. It never fetches the HTML pages themselves.
4. `stale_map/extract.py`: reads the headline version with a regex per site: PyPI `# name X`, npm `X • Public`, crates.io `# name vX`, and the GitHub release linked to `/releases/latest`. There is no LLM judge. "Headline" means the highest stable release, matching what PyPI, npm and crates.io show and what GitHub badges "Latest". Pages where that rule disagrees with the registry's own "latest" are excluded.
5. `stale_map/infer.py`: computes the version bracket, crawl-age bounds and lag curve. `stale_map/ranker.py` holds the policies and the catch rate at each budget (recall@budget, as in Bingo).

`make test` runs the unit and data tests. `make check` rescores everything from `data/slim/` with no network. A GitHub Actions workflow that does both is in `ci/github-actions.yml`. It is not yet in `.github/workflows/`, because the token that pushed this repo has no `workflow` scope.

**Data shipped:** `data/targets.json`, `data/registry/*.json` (release timestamps), `data/slim/*.jsonl.gz`, `data/traces/*.jsonl` and `results/`. `data/slim` holds the MCP responses cut down to lines that contain a version token, with all metadata kept. Analysis gives identical results on the slim and raw data. Raw full-page copies are not committed because they contain whole third-party pages.

## Caveats

- **Pilot.** This is one snapshot from about 15 minutes of calls, with {{n_parsed}} pages. Free-tier behaviour may differ from the paid API.
- **PyPI bot checks are a possible confound.** PyPI sometimes serves crawlers a challenge, and live fetch falls back to the cached copy by default, so stale PyPI copies could come from that and not from scheduling. One thing cuts against it being the whole story: with `allow_live_fetch: true`, {{live_same}} of {{live_n}} responses on all four sites, crates.io and GitHub included, came back with the cached copy's `acquired_at`. From the outside I can't tell whether that was a failed fetch, a policy choice, or something else.
- **Narrow slice of the web.** Registry pages change on a public clock, so they are easy to measure, not typical.
- **Sampling bias.** The sample is popular pages that had shipped recently. It over-weights fast movers, so these stale shares are not index-wide rates.
- **Day granularity.** `acquired_at` is a date. The change-clock policy uses the middle of that day as the crawl time.

## Exclusions

{{excl_md}}
