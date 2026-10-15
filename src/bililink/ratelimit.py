"""按客户端 IP 限流。

计数保存在进程内存中，多进程或多实例部署时各自独立计数。
"""

import math
import time
from ipaddress import IPv6Address, IPv6Network

from limits import parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter

from bililink.errors import RateLimitedError
from bililink.geoip import IPAddress

# 拿不到客户端地址时（如经 Unix socket 接入）所有请求共享同一份配额。
_UNKNOWN_CLIENT = "unknown"
# 家庭宽带与移动网络通常给每个用户分配整个 /64 网段，系统还会定期更换临时地址；
# 按单个 IPv6 地址计数时，换一个地址就能绕过限流，因此 IPv6 按 /64 网段计数。
_IPV6_PREFIX_LENGTH = 64


class RateLimiter:
    """滑动窗口限流器：任意一个窗口长度内的请求数都不会超过配额。"""

    def __init__(self, limit: str) -> None:
        self._limit = parse(limit)
        self._strategy = MovingWindowRateLimiter(MemoryStorage())

    async def hit(self, client_ip: IPAddress | None) -> None:
        """记录一次请求；超出配额时抛出 :class:`~bililink.errors.RateLimitedError`。

        ``client_ip`` 是 uvicorn 按 ``forwarded_allow_ips`` 处理过代理头之后的访问者地址，
        拿不到时为 ``None``。
        """
        key = _client_key(client_ip)
        if await self._strategy.hit(self._limit, key):
            return
        stats = await self._strategy.get_window_stats(self._limit, key)
        raise RateLimitedError(retry_after=max(1, math.ceil(stats.reset_time - time.time())))


def _client_key(client_ip: IPAddress | None) -> str:
    if client_ip is None:
        return _UNKNOWN_CLIENT
    if isinstance(client_ip, IPv6Address):
        return str(IPv6Network((client_ip, _IPV6_PREFIX_LENGTH), strict=False))
    return str(client_ip)
