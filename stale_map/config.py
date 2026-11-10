"""Frozen study parameters. Set before any Parallel call for the main run."""
from datetime import datetime, timezone

# Features for the recrawl ranker may only use registry data up to this instant.
# The 'held-out day' is everything after it, up to the observation time.
CUTOFF_ISO = "2026-11-09T04:30:00+00:00"  # 10:00 AM IST, 9 Nov 2026
CUTOFF = datetime.fromisoformat(CUTOFF_ISO).timestamp()

# Sampling frame: popular pages that had at least one release in the 30 days before the cutoff.
ACTIVE_WINDOW_DAYS = 30

TARGET_COUNTS = {"pypi": 150, "npm": 150, "crates": 100, "github": 100}

OBJECTIVE = "latest version number and its release date shown on this page"

# Held-out split by page hash (for anything fitted, e.g. per-site crawl age).
HOLDOUT_MOD = 3  # sha1(page_id) % 3 == 0 -> held-out pages

UTC = timezone.utc
