"""后台维护 APNIC 数据：先使用内置数据，定期下载更新，失败时保留当前快照；数据只保存在内存中。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from ipaddress import IPv4Network, IPv6Network

import httpx2
from pydantic import BaseModel, Field, field_validator

from bililink.geoip import (
    APNIC_DELEGATED_URL,
    IPNetwork,
    MainlandChinaNetworks,
    render_data_file,
)

logger = logging.getLogger(__name__)


class _NetworkData(BaseModel):
    """下载数据的边界：拒绝空数据及缺少任一地址族的数据。"""

    networks: tuple[IPNetwork, ...] = Field(min_length=1)

    @field_validator("networks")
    @classmethod
    def _validate_address_families(cls, networks: tuple[IPNetwork, ...]) -> tuple[IPNetwork, ...]:
        if {type(network) for network in networks} != {IPv4Network, IPv6Network}:
            msg = "IP 段数据必须同时包含 IPv4 与 IPv6"
            raise ValueError(msg)
        return networks


def _parse_delegated(delegated: str) -> MainlandChinaNetworks:
    # 与随包数据文件经过同一套生成规则，再按数据文件的格式解析并校验。
    contents = render_data_file(delegated)
    data = _NetworkData.model_validate(
        {"networks": [line for line in contents.splitlines() if line and not line.startswith("#")]}
    )
    return MainlandChinaNetworks(data.networks)


class GeoIPUpdater:
    """定期下载并替换 IP 段；独立连接池不携带访问 B 站的登录 Cookie。"""

    def __init__(
        self,
        networks: MainlandChinaNetworks,
        *,
        interval: float,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._networks = networks
        self._interval = interval
        self._timeout = timeout
        self._transport = transport

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """启动后台更新；退出时取消任务、关闭连接池。"""
        if self._interval == 0:
            yield
            return

        async with httpx2.AsyncClient(
            timeout=self._timeout, follow_redirects=True, transport=self._transport
        ) as client:
            task = asyncio.create_task(self._run(client))
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _run(self, client: httpx2.AsyncClient) -> None:
        while True:
            try:
                await self._refresh(client)
            except Exception:
                # 后台任务一旦因异常退出，之后就再也不会更新，也不会留下任何日志；
                # 意外错误同样只记录堆栈，保留已有数据，下一轮继续重试。
                logger.exception("IP 段自动更新出现意外错误，保留已有数据")
            await asyncio.sleep(self._interval)

    async def _refresh(self, client: httpx2.AsyncClient) -> None:
        try:
            response = await client.get(APNIC_DELEGATED_URL)
            response.raise_for_status()
            # APNIC 全量数据较大，解析和构建索引放在线程中，避免阻塞媒体请求。
            networks = await asyncio.to_thread(_parse_delegated, response.text)
        except (httpx2.HTTPError, ValueError) as exc:
            logger.warning("IP 段自动更新失败，保留已有数据：%s", exc)
            return

        self._networks.replace(networks)
        logger.info("中国大陆 IP 段已自动更新")
