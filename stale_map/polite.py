"""Polite HTTP: one shared throttle per host, exponential backoff, a fixed User-Agent.

Same habits as page-canary: never hammer a host, back off on 429/5xx, give up quietly.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

UA = "stale-map/0.1 (freshness research pilot; https://github.com/sivaratrisrinivas)"

# Minimum seconds between requests to the same host.
MIN_INTERVAL = {
    "mcp.parallel.ai": 8.0,
    "crates.io": 1.1,  # crates.io asks for at most 1 req/s
    "pypi.org": 0.3,
    "registry.npmjs.org": 0.2,
    "api.npmjs.org": 0.5,
    "api.github.com": 0.8,
}
DEFAULT_INTERVAL = 1.0


class Throttle:
    def __init__(self, intervals: dict[str, float] | None = None, clock=time.monotonic, sleep=time.sleep):
        self.intervals = intervals if intervals is not None else MIN_INTERVAL
        self.last: dict[str, float] = {}
        self.clock = clock
        self.sleep = sleep

    def wait(self, host: str) -> float:
        gap = self.intervals.get(host, DEFAULT_INTERVAL)
        now = self.clock()
        prev = self.last.get(host)
        slept = 0.0
        if prev is not None and now - prev < gap:
            slept = gap - (now - prev)
            self.sleep(slept)
        self.last[host] = self.clock()
        return slept


THROTTLE = Throttle()


def backoff_delays(retries: int, base: float = 2.0, cap: float = 120.0, jitter=random.random) -> list[float]:
    return [min(cap, base * (2 ** i)) * (0.75 + 0.5 * jitter()) for i in range(retries)]


def request(url: str, data: bytes | None = None, headers: dict | None = None, retries: int = 5,
            timeout: float = 90.0) -> tuple[int, dict, bytes]:
    host = urlparse(url).netloc
    h = {"User-Agent": UA}
    h.update(headers or {})
    delays = backoff_delays(retries)
    for attempt in range(retries + 1):
        THROTTLE.wait(host)
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                ra = e.headers.get("Retry-After")
                d = float(ra) if ra and ra.isdigit() else delays[attempt]
                time.sleep(d)
                continue
            return e.code, dict(e.headers or {}), e.read() or b""
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(delays[attempt])
                continue
            raise
    raise RuntimeError("unreachable")


def get_json(url: str, headers: dict | None = None):
    status, _, body = request(url, headers=headers)
    if status != 200:
        return None
    return json.loads(body)
