"""Minimal client for Parallel's free, no-key MCP server (https://mcp.parallel.ai/mcp).

Only the read-only tools `web_fetch` and `web_search` are allowed. `send_feedback`
and every other tool is refused on purpose.
"""
from __future__ import annotations

import json
import time

from . import polite

URL = "https://mcp.parallel.ai/mcp"
ALLOWED_TOOLS = {"web_fetch", "web_search"}


class ToolNotAllowed(Exception):
    pass


def parse_sse(body: str) -> list[dict]:
    """Parse an MCP streamable-HTTP response (SSE or plain JSON) into JSON-RPC messages."""
    body = body.strip()
    if body.startswith("{"):
        return [json.loads(body)]
    out = []
    for block in body.split("\n\n"):
        data = "".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
        if data:
            out.append(json.loads(data))
    return out


class ParallelMCP:
    def __init__(self):
        self.sid: str | None = None
        self.next_id = 1

    def _post(self, msg: dict) -> tuple[dict, list[dict]]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        status, headers, body = polite.request(URL, data=json.dumps(msg).encode(), headers=h, timeout=180)
        if status not in (200, 202):
            raise RuntimeError(f"MCP HTTP {status}: {body[:300]!r}")
        sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        if sid:
            self.sid = sid
        return headers, parse_sse(body.decode()) if body else []

    def init(self):
        _, msgs = self._post({"jsonrpc": "2.0", "id": self._id(), "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "stale-map", "version": "0.1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return msgs

    def _id(self):
        self.next_id += 1
        return self.next_id

    def call(self, tool: str, args: dict) -> dict:
        if tool not in ALLOWED_TOOLS:
            raise ToolNotAllowed(tool)
        if self.sid is None:
            self.init()
        t0 = time.time()
        _, msgs = self._post({"jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
                              "params": {"name": tool, "arguments": args}})
        t1 = time.time()
        res = next((m for m in msgs if "result" in m or "error" in m), None)
        return {"tool": tool, "args": args, "t_start": t0, "t_end": t1, "response": res}

    def web_fetch(self, urls: list[str], objective: str, allow_live_fetch: bool, full_content: bool = True) -> dict:
        assert len(urls) <= 20
        return self.call("web_fetch", {"urls": urls, "objective": objective,
                                       "allow_live_fetch": allow_live_fetch, "full_content": full_content})

    def web_search(self, objective: str, queries: list[str]) -> dict:
        return self.call("web_search", {"objective": objective, "search_queries": queries})


def structured(result: dict) -> dict | None:
    """Return structuredContent (or JSON text content) of a tools/call result."""
    r = (result.get("response") or {}).get("result") or {}
    if r.get("structuredContent"):
        return r["structuredContent"]
    for c in r.get("content", []):
        if c.get("type") == "text":
            try:
                return json.loads(c["text"])
            except Exception:
                return {"text": c["text"]}
    return None
