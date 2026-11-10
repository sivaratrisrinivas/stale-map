# Stale Map

How old is the copy of a page that an agent reads through a search index? Package registries make this measurable from the outside. PyPI, npm, crates.io and GitHub Releases record the exact second every release goes out, so they act as a free, exact change clock. This repo uses that clock to measure how far behind Parallel's index is on 468 registry pages, and to score recrawl policies against it.

This is a **pilot**: one snapshot on one morning, using only Parallel's free public MCP. It's offered as data that might be useful, not as a verdict on Parallel's index, which may already track all of this internally.

This project is not affiliated with or endorsed by Parallel Web Systems.

## The one-release version

openai 3.48.0 went up on PyPI at 9 Nov, 9:43 PM IST. At 10 Nov, 9:57 AM IST, Parallel's `web_fetch` copy of `pypi.org/project/openai/` still showed **3.46.0** (`acquired_at` 2026-11-05). It showed the same with `allow_live_fetch: true`, and `errors` and `warnings` were both empty. In the same call, `github.com/openai/openai-python/releases` showed **v3.48.0** (`acquired_at` 2026-11-10).

A `web_search` for the latest openai SDK (10 Nov, 10:32 AM IST) returned 10 results. 1 of them mentioned 3.48.0 (rank 1: github.com). PyPI results: rank 2 pypi.org/rss/project/openai/releases.xml → newest version in excerpt 3.46.0; rank 4 pypi.org/project/openai → newest version in excerpt 3.46.0.

## Results (10 Nov, 10:01 AM IST to 10 Nov, 10:15 AM IST)

- Sample: 500 popular pages (150 PyPI, 150 npm, 100 crates.io, 100 GitHub Releases), each with at least one release in the 30 days before 9 Nov, 10:00 AM IST. 468 could be read with a code check. The rest are listed under Exclusions below.
- 242 of 468 copies (52%) were missing at least one release.
- Lag curve, for releases in the last 30 days: under 48 h old, 13 of 94 were reflected. 7 to 14 days old: 194 of 320. 14 to 30 days old: 647 of 812.
- Validation: the version bracket (crawled after release N and before N+1, from registry timestamps alone) agreed with Parallel's own `acquired_at` date on 468 of 468 pages.

| site | pages read | stale copies | median crawl age | p90 crawl age | median lag of stale copies (at least) | acquired_at agrees |
|---|---|---|---|---|---|---|
| crates.io | 96 of 100 | 49 (51%) | 15.2 days | 250.2 days | 18.8 days | 96/96 |
| GitHub Releases | 75 of 100 | 25 (33%) | 3.2 days | 13.2 days | 4.6 days | 75/75 |
| npm | 149 of 150 | 95 (64%) | 25.2 days | 317.4 days | 28.3 days | 149/149 |
| PyPI | 148 of 150 | 73 (49%) | 5.2 days | 64.8 days | 11.2 days | 148/148 |

"Crawl age" is observation time minus `acquired_at`, which is a UTC date, so it's accurate to within a day. "Lag of stale copies" is a lower bound: the time since the first release the copy is missing.

### Recrawl ranking on a held-out day

Every feature is frozen at 9 Nov, 10:00 AM IST. The label is whether the copy was stale at observation, about 24 hours later. Nothing is fitted on labels. The 90-day rate window and the 0.5 prior were set before collection. Pages evaluated: 468, of which 242 were stale.

| policy | catch @ 10% budget | catch @ 25% budget | catch @ 50% budget | budget to catch 90% |
|---|---|---|---|---|
| Uniform (random) | 10% | 25% | 50% | 90% |
| Popularity | 5% | 14% | 41% | 91% |
| Change rate (Poisson) | 12% | 29% | 53% | 90% |
| Most recent release | 16% | 36% | 64% | 84% |
| Poisson + crawl age | 19% | 48% | 83% | 61% |
| Change clock (this repo) | 19% | 48% | 95% | 47% |
| Perfect ranking | 19% | 48% | 97% | 47% |

- **Outside view**, where crawl times are unknown: popularity does worse than random. The classic Poisson change-rate order (Cho & Garcia-Molina) is only a little better than random: at a 50% budget, the bootstrap 95% CI against uniform is -1 to +8 points, which includes zero. "Most recent release first" is the best outside-view policy, beating change rate by +6 to +17 points at a 50% budget.
- **Index-owner view**, where crawl times are known, as `acquired_at` exposes them: the change clock needs 47% of the budget to catch 90% of stale pages, about the same as a perfect ranking (47%). Poisson with crawl age needs 61%. At a 50% budget, the bootstrap 95% CI of change clock minus Poisson-with-crawl-age is +7 to +15 points.
- Only 17 of the 242 stale pages went stale during the held-out day itself. Everything else was already visible in public timestamps before it began. For registry-style pages, recrawl is mostly a lookup, not a forecast.
- Robustness: on the hash-held-out third (158 pages, 81 stale), the budget to catch 90% is 47% for the change clock, 53% for Poisson with crawl age and 87% for most-recent-release. Within each registry, the change clock needs crates.io 47%, GitHub Releases 33%, npm 60%, PyPI 45%, against crates.io 70%, GitHub Releases 51%, npm 64%, PyPI 58% for Poisson with crawl age. So the gain doesn't come from simply ranking one site above another.

### Live fetch

I refetched 185 readable pages (up to 40 stale and 10 fresh per registry, seeded) with `allow_live_fetch: true`. 11 of 145 stale copies came back current, and 134 of the 185 were stale on the live call. 172 of 185 live responses carried the same `acquired_at` as the cached copy.

| site | pages | stale (cached) | stale (live) | fixed by live |
|---|---|---|---|---|
| crates.io | 50 | 40 | 40 | 0 |
| GitHub Releases | 35 | 25 | 25 | 0 |
| npm | 50 | 40 | 35 | 5 |
| PyPI | 50 | 40 | 34 | 6 |

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

- **Pilot.** This is one snapshot from about 15 minutes of calls, with 468 pages. Free-tier behaviour may differ from the paid API.
- **PyPI bot checks are a possible confound.** PyPI sometimes serves crawlers a challenge, and live fetch falls back to the cached copy by default, so stale PyPI copies could come from that and not from scheduling. One thing cuts against it being the whole story: with `allow_live_fetch: true`, 172 of 185 responses on all four sites, crates.io and GitHub included, came back with the cached copy's `acquired_at`. From the outside I can't tell whether that was a failed fetch, a policy choice, or something else.
- **Narrow slice of the web.** Registry pages change on a public clock, so they are easy to measure, not typical.
- **Sampling bias.** The sample is popular pages that had shipped recently. It over-weights fast movers, so these stale shares are not index-wide rates.
- **Day granularity.** `acquired_at` is a date. The change-clock policy uses the middle of that day as the crawl time.
- **Not affiliated.** This project is not affiliated with or endorsed by Parallel Web Systems.

## Exclusions

- crates.io: 4 fetch error
- GitHub Releases: 9 display rule mismatch, 1 mention only, 15 no version found
- npm: 1 display rule mismatch
- PyPI: 2 redirect stub
- Status meanings: *fetch error*: the MCP returned `cache_miss` for the URL. *redirect stub*: the cached copy is a `301 Moved Permanently` page. *display rule mismatch*: our headline rule disagrees with the registry's own latest (for example, an npm `latest` tag pointing at an older major). *no version found*: no known stable version in a headline slot, usually GitHub repos with non-semver tags such as `b12242`, `r187` or `pkg@1.2.3`. *mention only*: the version appeared only in free text, which we don't trust.
