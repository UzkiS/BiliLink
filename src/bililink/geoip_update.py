"""后台维护 APNIC 数据：先使用内置或缓存数据，更新失败时保留当前快照。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from tempfile import NamedTemporaryFile

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
    """下载与缓存的共同边界：拒绝空数据及缺少任一地址族的数据。"""

    networks: tuple[IPNetwork, ...] = Field(min_length=1)

    @field_validator("networks")
    @classmethod
    def _validate_address_families(cls, networks: tuple[IPNetwork, ...]) -> tuple[IPNetwork, ...]:
        if {type(network) for network in networks} != {IPv4Network, IPv6Network}:
            msg = "IP 段数据必须同时包含 IPv4 与 IPv6"
            raise ValueError(msg)
        return networks


def _parse_networks(contents: str) -> MainlandChinaNetworks:
    data = _NetworkData.model_validate(
        {"networks": [line for line in contents.splitlines() if line and not line.startswith("#")]}
    )
    return MainlandChinaNetworks(data.networks)


def _prepare_update(delegated: str) -> tuple[str, MainlandChinaNetworks]:
    contents = render_data_file(delegated)
    return contents, _parse_networks(contents)


def _write_cache(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件与目标同目录，原子替换保证重启或其他进程只会读到完整文件。
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
        temporary = Path(file.name)
    try:
        temporary.write_text(contents, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class GeoIPUpdater:
    """定期下载并替换 IP 段；独立连接池不携带访问 B 站的登录 Cookie。"""

    def __init__(
        self,
        networks: MainlandChinaNetworks,
        *,
        interval: float,
        timeout: float,
        cache_file: Path | None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._networks = networks
        self._interval = interval
        self._timeout = timeout
        self._cache_file = cache_file
        self._transport = transport

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """读取可用缓存并启动后台更新；退出时取消任务、关闭连接池。"""
        if self._cache_file is not None:
            try:
                contents = await asyncio.to_thread(self._cache_file.read_text, encoding="utf-8")
                cached = await asyncio.to_thread(_parse_networks, contents)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeError) as exc:
                logger.warning("IP 段缓存读取失败，继续使用内置数据：%s", exc)
            else:
                self._networks.replace(cached)

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
            await self._refresh(client)
            await asyncio.sleep(self._interval)

    async def _refresh(self, client: httpx2.AsyncClient) -> None:
        try:
            response = await client.get(APNIC_DELEGATED_URL)
            response.raise_for_status()
            # APNIC 全量数据较大，解析和构建索引放在线程中，避免阻塞媒体请求。
            contents, networks = await asyncio.to_thread(_prepare_update, response.text)
        except (httpx2.HTTPError, ValueError, IndexError) as exc:
            logger.warning("IP 段自动更新失败，保留已有数据：%s", exc)
            return

        self._networks.replace(networks)
        if self._cache_file is not None:
            try:
                await asyncio.to_thread(_write_cache, self._cache_file, contents)
            except OSError as exc:
                # 只读磁盘等缓存问题不影响本次已经成功更新的内存数据。
                logger.warning("IP 段缓存写入失败，内存数据已更新：%s", exc)
        logger.info("中国大陆 IP 段已自动更新")
