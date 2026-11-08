"""Protection for the server: a limit on request body size and a rate limit per client address.

New Python concept used here, "ASGI middleware": FastAPI sits on top of ASGI. A middleware is a function that
wraps the whole app: every request passes through it before reaching a route, and it may answer by itself
(here: 413 too large, 429 too many requests) without the route ever running. It receives three things:
`scope` (who is asking, which path), `receive` (a function that yields the request body in chunks) and
`send` (a function that writes the response).

Both limits answer with the app's usual error envelope: {"error": {"code", "message"}}.

Limitations, stated honestly:
  * The counters live in this process's memory. With several worker processes each has its own counters,
    so the real limit is (workers x limit). With one uvicorn process it is exact. Restarting resets it.
  * Everyone behind the same public address (a campus Wi-Fi) shares one limit.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from typing import Callable

MAX_TRACKED_CLIENTS = 10_000        # memory cap: the table is cleaned when it grows past this


async def _send_json(send, status: int, code: str, message: str, extra: dict | None = None,
                     headers: list[tuple[bytes, bytes]] | None = None) -> None:
    body = {"error": {"code": code, "message": message, **(extra or {})}}
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
        + (headers or []),
    })
    await send({"type": "http.response.body", "body": payload})


class BodyLimitMiddleware:
    """Rejects requests whose body is larger than `max_bytes`.

    The Content-Length header is checked first (cheap, rejects before reading anything), but a client can lie
    or send the body in chunks, so the body is also counted while it is read. Bodies are small (a few KB), so
    the middleware reads the whole body itself, then replays it to the app."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        too_large = f"The request is larger than the {self.max_bytes // 1024} KB limit."
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await _send_json(send, 413, "payload_too_large", too_large)
                    return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            piece = message.get("body", b"")
            size += len(piece)
            if size > self.max_bytes:
                await _send_json(send, 413, "payload_too_large", too_large)
                return
            chunks.append(piece)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()          # afterwards: the real stream (reports a disconnect)

        await self.app(scope, replay, send)


class RateLimiter:
    """Sliding window: a client may make `limit` requests in any window of `seconds`.

    For each (client, rule) it keeps the times of its recent requests in a deque; old ones are dropped. If the
    deque already holds `limit` times, the request is refused, and the answer says when the oldest one expires."""

    def __init__(self, rules: list[tuple[str, int, int]], clock: Callable[[], float] = time.monotonic) -> None:
        self.rules = rules
        self.clock = clock
        self.hits: dict[tuple[str, str], deque[float]] = {}

    def rule_for(self, path: str) -> tuple[str, int, int] | None:
        for rule in self.rules:
            if path.startswith(rule[0]):
                return rule
        return None

    def check(self, client: str, path: str) -> int:
        """Returns 0 when the request is allowed (and counts it), otherwise the seconds to wait."""
        rule = self.rule_for(path)
        if rule is None:
            return 0
        prefix, limit, seconds = rule
        now = self.clock()
        if len(self.hits) > MAX_TRACKED_CLIENTS:
            self._forget_old(now)

        times = self.hits.setdefault((client, prefix), deque())
        while times and now - times[0] >= seconds:
            times.popleft()
        if len(times) >= limit:
            return max(1, math.ceil(seconds - (now - times[0])))
        times.append(now)
        return 0

    def _forget_old(self, now: float) -> None:
        longest = max(seconds for _, _, seconds in self.rules)
        for key in [k for k, times in self.hits.items() if not times or now - times[-1] >= longest]:
            del self.hits[key]
        if len(self.hits) > MAX_TRACKED_CLIENTS:       # still too many recent clients: start over
            self.hits.clear()


def client_address(scope, trust_proxy: bool, client_ip_header: str = "") -> str:
    """Who is asking. Behind one trusted proxy the proxy APPENDS the real address to X-Forwarded-For, so the
    LAST entry is the one to trust (earlier entries can be written by the client).

    `client_ip_header` (lowercase, e.g. "cf-connecting-ip") is for hosts behind Cloudflare, such as Render: there
    X-Forwarded-For ends with a Cloudflare address, so every visitor would look alike. Set it ONLY when the app
    is reachable solely through that CDN, otherwise a client could forge the header."""
    if client_ip_header:
        wanted = client_ip_header.encode()
        for name, value in scope["headers"]:
            if name == wanted:
                found = value.decode("latin-1").strip()
                if found:
                    return found
    if trust_proxy:
        for name, value in scope["headers"]:
            if name == b"x-forwarded-for":
                last = value.decode("latin-1").split(",")[-1].strip()
                if last:
                    return last
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    def __init__(self, app, limiter: RateLimiter, trust_proxy: bool = False, client_ip_header: str = "") -> None:
        self.app = app
        self.limiter = limiter
        self.trust_proxy = trust_proxy
        self.client_ip_header = client_ip_header

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        wait = self.limiter.check(client_address(scope, self.trust_proxy, self.client_ip_header), scope["path"])
        if wait:
            await _send_json(
                send, 429, "rate_limited",
                f"Too many requests. Try again in {wait} s.",
                {"retry_after": wait},
                [(b"retry-after", str(wait).encode())],
            )
            return
        await self.app(scope, receive, send)
