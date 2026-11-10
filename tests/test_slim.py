import json

from stale_map.extract import reflected
from stale_map.slim import slim_call, slim_text
from stale_map.versions import Release


def test_slim_keeps_headline_lines_only():
    page = "Skip to main content\n# openai 3.46.0\nThe official Python library\nRelease history\n3.45.0\nfooter"
    s = slim_text(page)
    assert "# openai 3.46.0" in s and "footer" not in s and "official" not in s


def test_slim_gives_same_reading_as_raw():
    tl = [Release("3.45.0", 0), Release("3.46.0", 10), Release("3.47.0", 20)]
    full = "nav\n# openai 3.46.0\nlong readme text 3.47.0 is not mentioned as headline\n" + "x" * 5000
    call = {"response": {"result": {"structuredContent": {"results": [
        {"url": "u", "title": "openai · PyPI", "full_content": full, "excerpts": [], "acquired_at": "2026-11-05T00:00:00Z"}]}}}}
    slim = slim_call(call)
    x = slim["response"]["result"]["structuredContent"]["results"][0]
    assert x["acquired_at"] == "2026-11-05T00:00:00Z"
    assert reflected(full, tl, "pypi") == reflected(x["full_content"], tl, "pypi")
    assert len(json.dumps(slim)) < len(json.dumps(call)) / 5
