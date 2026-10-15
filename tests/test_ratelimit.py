"""按客户端 IP 的滑动窗口限流。"""

from ipaddress import ip_address

import pytest

from bililink.errors import RateLimitedError
from bililink.ratelimit import RateLimiter

pytestmark = pytest.mark.anyio


async def test_rejects_requests_over_the_limit_with_retry_after() -> None:
    limiter = RateLimiter("2/minute")
    client = ip_address("203.0.113.1")
    await limiter.hit(client)
    await limiter.hit(client)

    with pytest.raises(RateLimitedError) as exc_info:
        await limiter.hit(client)

    assert 1 <= int(exc_info.value.headers["Retry-After"]) <= 60


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("203.0.113.1", "203.0.113.2"),
        ("2001:db8:0:1::1", "2001:db8:0:2::1"),  # 不同的 /64 网段
    ],
)
async def test_counts_each_client_separately(first: str, second: str) -> None:
    limiter = RateLimiter("1/minute")
    await limiter.hit(ip_address(first))

    await limiter.hit(ip_address(second))


async def test_ipv6_addresses_in_one_64_prefix_share_one_quota() -> None:
    # 同一用户的 IPv6 地址通常位于同一个 /64 网段内，并会定期更换临时地址。
    limiter = RateLimiter("1/minute")
    await limiter.hit(ip_address("2001:db8::1"))

    with pytest.raises(RateLimitedError):
        await limiter.hit(ip_address("2001:db8::ffff:2"))


async def test_requests_without_client_address_share_one_quota() -> None:
    limiter = RateLimiter("1/minute")
    await limiter.hit(None)

    with pytest.raises(RateLimitedError):
        await limiter.hit(None)
