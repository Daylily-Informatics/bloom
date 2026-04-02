from __future__ import annotations

import asyncio

from bloom_lims.api.rate_limiting import RateLimitMiddleware, RateLimiter


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _run_request(path: str, middleware: RateLimitMiddleware):
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "path": path,
        "method": "GET",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    await middleware(scope, receive, send)
    return messages


def _status(messages: list[dict]) -> int:
    return next(msg["status"] for msg in messages if msg["type"] == "http.response.start")


def test_rate_limit_middleware_limits_untrusted_paths():
    limiter = RateLimiter(requests_per_minute=1, requests_per_hour=1000, burst_size=1)
    limiter.requests_per_minute = 1
    limiter.requests_per_hour = 1000
    limiter.burst_size = 1
    limiter.reset()

    allowed_1, _info_1 = limiter.is_allowed("127.0.0.1")
    allowed_2, info_2 = limiter.is_allowed("127.0.0.1")

    assert allowed_1 is True
    assert allowed_2 is False
    assert info_2["rate_limited"] is True


def test_rate_limit_middleware_skips_atlas_external_paths():
    middleware = RateLimitMiddleware(
        _ok_app,
        requests_per_minute=1,
        requests_per_hour=1000,
    )

    first = asyncio.run(_run_request("/api/v1/external/atlas/beta/tubes", middleware))
    second = asyncio.run(_run_request("/api/v1/external/atlas/beta/materials", middleware))

    assert _status(first) == 200
    assert _status(second) == 200
