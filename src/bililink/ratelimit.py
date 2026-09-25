"""按客户端 IP 限流。

计数保存在进程内存中，多进程或多实例部署时各自独立计数。
客户端 IP 取自 ASGI scope，即 uvicorn 按 ``forwarded_allow_ips`` 处理过代理头之后的结果。
"""

import math
import time

from limits import parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter
from starlette.requests import Request

from bililink.errors import RateLimitedError

# 拿不到客户端地址时（如经 Unix socket 接入）所有请求共享同一份配额。
_UNKNOWN_CLIENT = "unknown"


class RateLimiter:
    """滑动窗口限流器：任意一个窗口长度内的请求数都不会超过配额。"""

    def __init__(self, limit: str) -> None:
        self._limit = parse(limit)
        self._strategy = MovingWindowRateLimiter(MemoryStorage())

    async def hit(self, request: Request) -> None:
        """记录一次请求；超出配额时抛出 :class:`~bililink.errors.RateLimitedError`。"""
        client = request.client.host if request.client else _UNKNOWN_CLIENT
        if await self._strategy.hit(self._limit, client):
            return
        stats = await self._strategy.get_window_stats(self._limit, client)
        raise RateLimitedError(retry_after=max(1, math.ceil(stats.reset_time - time.time())))
