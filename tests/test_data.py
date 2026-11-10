"""Checks on the shipped data: the pilot reproduces, and every parsed page passed the code checks."""
import csv
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results/summary.json"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="run `make check` first")


def test_openai_pilot_reproduces():
    s = json.loads(SUMMARY.read_text())
    calls = s["pilot"]["calls"]
    assert {c["allow_live_fetch"] for c in calls} == {False, True}
    for c in calls:
        assert c["newest"] == "3.48.0" and c["errors"] == [] and not c["warnings"]
        by = {("pypi" if "pypi.org" in r["url"] else "gh"): r for r in c["results"]}
        assert by["pypi"]["shown"] == "3.46.0" and by["pypi"]["acquired_at"].startswith("2026-11-05")
        assert by["gh"]["shown"] == "3.48.0"


def test_every_parsed_page_has_headline_evidence():
    rows = list(csv.DictReader((ROOT / "results/pages.csv").open()))
    ok = [r for r in rows if r["status"] == "ok"]
    assert len(ok) >= 400
    assert all(r["method"] == "headline" and r["headline_ok"] == "True" for r in ok)


def test_stale_flag_matches_versions():
    rows = [r for r in csv.DictReader((ROOT / "results/pages.csv").open()) if r["status"] == "ok"]
    for r in rows:
        assert (r["stale"] == "True") == (r["shown"] != r["newest"]) == (int(r["missed"]) > 0)
