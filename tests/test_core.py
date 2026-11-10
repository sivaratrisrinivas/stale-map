import math

import pytest

from stale_map import infer, ranker
from stale_map.extract import headline_match, reflected_release, token_re
from stale_map.mcp import ALLOWED_TOOLS, ParallelMCP, ToolNotAllowed, parse_sse
from stale_map.polite import Throttle, backoff_delays
from stale_map.versions import Release, display_timeline, is_stable, parse_key, shown_at

H = 3600.0


def tl(*pairs):
    return [Release(v, t * H) for v, t in pairs]


# ---- versions -------------------------------------------------------------

def test_semver_and_pep440_ordering():
    assert parse_key("1.10.0") > parse_key("1.9.9")
    assert parse_key("2.0.0-beta.1") < parse_key("2.0.0")
    assert parse_key("3.48.0") > parse_key("3.46.0")
    assert parse_key("2.33.0.20261006") > parse_key("2.33.0.20250101")
    assert not is_stable("1.0.0rc1") and not is_stable("2.0.0-alpha.3") and is_stable("1.2.3")


def test_max_stable_timeline_ignores_backports_and_prereleases():
    rels = tl(("2.0.0", 0), ("2.1.0", 10), ("1.9.5", 20), ("3.0.0rc1", 30), ("2.2.0", 40))
    assert [r.version for r in display_timeline(rels, "max_stable")] == ["2.0.0", "2.1.0", "2.2.0"]
    assert [r.version for r in display_timeline(rels, "newest")] == ["2.0.0", "2.1.0", "1.9.5", "3.0.0rc1", "2.2.0"]
    assert shown_at(display_timeline(rels, "max_stable"), 25 * H).version == "2.1.0"


# ---- extraction (code checks, no LLM) --------------------------------------

def test_token_boundaries():
    assert token_re("3.46.0").search("# openai 3.46.0\n")
    assert token_re("3.46.0").search("tag v3.46.0 released")
    assert not token_re("3.46.0").search("version 3.46.01")
    assert not token_re("3.46.0").search("3.46.0rc1")
    assert not token_re("1.0").search("1.0.5")
    assert not token_re("6.0").search("16.0")


def test_reflected_release_is_newest_mentioned():
    t = tl(("3.45.0", 0), ("3.46.0", 10), ("3.47.0", 20), ("3.48.0", 30))
    text = "# openai 3.46.0 ... Release history 3.46.0 3.45.0"
    assert reflected_release(text, t).version == "3.46.0"
    assert reflected_release("nothing here", t) is None


def test_headline_patterns():
    assert headline_match("pypi", "openai", "3.46.0", "# openai 3.46.0\nThe official")
    assert headline_match("npm", "react", "19.3.1", "19\\.3.1 • Public • Published 25 days ago".replace("\\", ""))
    assert headline_match("crates", "serde", "1.0.229", "# serde v1.0.229")


# ---- inference -------------------------------------------------------------

def test_bracket_for_the_openai_pilot_shape():
    # releases at hours 0, 10, 20, 30; copy shows 3.46.0; observed at hour 42
    t = tl(("3.45.0", 0), ("3.46.0", 10), ("3.47.0", 20), ("3.48.0", 30))
    b = infer.bracket(t, t[1], 42 * H)
    assert b.stale and b.missed == 2
    assert b.crawl_after == 10 * H and b.crawl_before == 20 * H
    assert b.age_lo_h == pytest.approx(22) and b.age_hi_h == pytest.approx(32)
    assert b.newest_version == "3.48.0" and b.newest_age_h == pytest.approx(12)


def test_bracket_fresh_page_and_future_release_ignored():
    t = tl(("1.0.0", 0), ("1.1.0", 50))
    b = infer.bracket(t, t[0], 40 * H)  # 1.1.0 not yet released at observation
    assert not b.stale and b.age_lo_h == 0 and b.age_hi_h == pytest.approx(40)


def test_release_points_and_lag_curve():
    t = tl(("a1.0.0", 0), ("1.0.1", 30), ("1.0.2", 39))
    pts = infer.release_points(t, t[1], 40 * H)
    assert pts == [(40.0, True), (10.0, True), (1.0, False)]
    c = infer.lag_curve(pts, bins=[0, 6, 24, 48])
    assert [x["n"] for x in c] == [1, 1, 1] and c[0]["share"] == 0 and c[1]["share"] == 1


def test_quantile():
    assert infer.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert infer.quantile([], 0.5) is None


# ---- ranker ----------------------------------------------------------------

def test_catch_rate_and_rank_ties_are_deterministic():
    assert ranker.catch_rate(["a", "b", "c"], {"b", "z"}, 2) == 0.5
    s = {"a": 1.0, "b": 1.0, "c": 0.0}
    assert ranker.rank(s, seed=3) == ranker.rank(s, seed=3)
    assert ranker.rank(s)[-1] == "c"


def test_change_rate_counts_only_before_cutoff():
    cutoff = 1000 * H
    times = [cutoff - 10 * H, cutoff - 20 * H, cutoff + 5 * H]
    assert ranker.change_rate(times, cutoff, window_days=90, prior=0) == pytest.approx(2 / (90 * 24))


def test_change_clock_uses_releases_between_crawl_and_cutoff_only():
    cutoff = 1000 * H
    crawl = cutoff - 48 * H
    # a release after the crawl but before the cutoff -> certainly stale
    a = ranker.Page("a", "pypi", 0.5, [cutoff - 500 * H, cutoff - 10 * H], t_obs=cutoff + 24 * H, crawl_t=crawl)
    assert ranker.p_change_clock(a, cutoff) == 1.0
    # no release since the crawl -> only the unseen window after the cutoff counts
    b = ranker.Page("b", "pypi", 0.5, [cutoff - 500 * H], t_obs=cutoff + 24 * H, crawl_t=crawl)
    lam = ranker.change_rate(b.tl_times_before_cutoff, cutoff)
    assert ranker.p_change_clock(b, cutoff) == pytest.approx(1 - math.exp(-lam * 24))
    # classic Poisson uses the full crawl age instead
    assert ranker.p_age_poisson(b, cutoff) == pytest.approx(1 - math.exp(-lam * 72))
    # a crawl after the cutoff shrinks the unseen window
    c = ranker.Page("c", "pypi", 0.5, [cutoff - 500 * H], t_obs=cutoff + 24 * H, crawl_t=cutoff + 20 * H)
    assert ranker.p_change_clock(c, cutoff) == pytest.approx(1 - math.exp(-lam * 4))


def test_evaluate_on_synthetic_data_clock_beats_uniform_and_oracle_is_ceiling():
    import random
    rnd = random.Random(4)
    cutoff = 10000 * H
    pages = []
    for i in range(300):
        lam = rnd.choice([0.002, 0.02, 0.2])
        times = sorted(cutoff - rnd.uniform(0, 2000) * H for _ in range(max(1, int(lam * 2000))))
        crawl = cutoff - rnd.uniform(0, 400) * H
        stale = any(t > crawl for t in times) or rnd.random() < 0.05
        pages.append(ranker.Page(f"p{i}", "pypi", rnd.random(), times, cutoff + 24 * H, crawl, stale))
    ev = ranker.evaluate(pages, cutoff)
    for b, row in ev["budgets"].items():
        assert row["change_clock"] >= row["uniform"]
        for k in ranker.OUTSIDE + ranker.OWNER:
            assert row[k] <= row["oracle"] + 1e-9
    assert ev["budget_for_90pct"]["change_clock"] <= ev["budget_for_90pct"]["uniform"]
    assert ev["curve"]["change_clock"][0] == 0 and ev["curve"]["change_clock"][-1] == 1


# ---- MCP safety and politeness --------------------------------------------

def test_send_feedback_is_refused_before_any_network_call():
    assert "send_feedback" not in ALLOWED_TOOLS
    m = ParallelMCP()
    with pytest.raises(ToolNotAllowed):
        m.call("send_feedback", {"text": "x"})
    assert m.sid is None  # never initialised a session


def test_parse_sse():
    body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert parse_sse(body) == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}]
    assert parse_sse('{"a":1}') == [{"a": 1}]


def test_throttle_spaces_requests_per_host():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    th = Throttle({"h": 8.0}, clock=lambda: now[0], sleep=sleep)
    th.wait("h")
    now[0] += 3
    th.wait("h")
    th.wait("other")
    assert slept == [5.0]


def test_backoff_grows_and_caps():
    d = backoff_delays(8, base=2, cap=60, jitter=lambda: 0.5)
    assert d[0] == 2 and d[1] == 4 and max(d) == 60
