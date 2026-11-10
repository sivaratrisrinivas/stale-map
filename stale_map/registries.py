"""Ground truth: exact release times from registry APIs (JSON only, never the HTML pages)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime

from . import polite
from .versions import Release


def iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def pypi(name: str) -> dict | None:
    d = polite.get_json(f"https://pypi.org/pypi/{name}/json")
    if not d:
        return None
    rels = []
    for v, files in d.get("releases", {}).items():
        files = [f for f in files if not f.get("yanked")]
        if files:
            rels.append(Release(v, min(iso(f["upload_time_iso_8601"]) for f in files)))
    return {"releases": rels, "latest_reported": d["info"]["version"]}


def npm(name: str) -> dict | None:
    d = polite.get_json(f"https://registry.npmjs.org/{name.replace('/', '%2F')}",
                        headers={"Accept": "application/json"})
    if not d or "time" not in d:
        return None
    vs = set(d.get("versions", {}))
    rels = [Release(v, iso(t)) for v, t in d["time"].items() if v in vs]
    return {"releases": rels, "latest_reported": d.get("dist-tags", {}).get("latest")}


def crates(name: str) -> dict | None:
    d = polite.get_json(f"https://crates.io/api/v1/crates/{name}")
    if not d:
        return None
    rels = [Release(v["num"], iso(v["created_at"])) for v in d.get("versions", []) if not v.get("yanked")]
    c = d.get("crate", {})
    return {"releases": rels, "latest_reported": c.get("default_version") or c.get("max_stable_version"),
            "recent_downloads": c.get("recent_downloads")}


def gh_api(path: str):
    """Call the GitHub API through the authenticated gh CLI (never prints the token)."""
    p = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return json.loads(p.stdout)


def github_releases(repo: str) -> dict | None:
    d = gh_api(f"repos/{repo}/releases?per_page=100")
    if d is None:
        return None
    rels = [Release(r["tag_name"], iso(r["published_at"])) for r in d
            if not r.get("draft") and r.get("published_at")]
    latest = gh_api(f"repos/{repo}/releases/latest")  # the release GitHub badges as "Latest"
    return {"releases": rels, "latest_reported": (latest or {}).get("tag_name")}


FETCHERS = {"pypi": pypi, "npm": npm, "crates": crates, "github": github_releases}

PAGE_URL = {
    "pypi": "https://pypi.org/project/{}/",
    "npm": "https://www.npmjs.com/package/{}",
    "crates": "https://crates.io/crates/{}",
    "github": "https://github.com/{}/releases",
}

# GitHub badges one release "Latest" (by default the highest stable release); the page headline
# is that release. Pages where this rule disagrees with GitHub's own /releases/latest are excluded.
RULE = {"pypi": "max_stable", "npm": "max_stable", "crates": "max_stable", "github": "max_stable"}
