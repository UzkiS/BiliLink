"""按客户端 IP 的滑动窗口限流。"""

import pytest
from starlette.requests import Request

from bililink.errors import RateLimitedError
from bililink.ratelimit import RateLimiter

pytestmark = pytest.mark.anyio


def request_from(client_ip: str | None) -> Request:
    return Request({"type": "http", "client": (client_ip, 50000) if client_ip else None})


async def test_rejects_requests_over_the_limit_with_retry_after() -> None:
    limiter = RateLimiter("2/minute")
    await limiter.hit(request_from("203.0.113.1"))
    await limiter.hit(request_from("203.0.113.1"))

    with pytest.raises(RateLimitedError) as exc_info:
        await limiter.hit(request_from("203.0.113.1"))

    assert 1 <= int(exc_info.value.headers["Retry-After"]) <= 60


async def test_counts_each_client_separately() -> None:
    limiter = RateLimiter("1/minute")
    await limiter.hit(request_from("203.0.113.1"))

    await limiter.hit(request_from("203.0.113.2"))


async def test_requests_without_client_address_share_one_quota() -> None:
    limiter = RateLimiter("1/minute")
    await limiter.hit(request_from(None))

    with pytest.raises(RateLimitedError):
        await limiter.hit(request_from(None))
