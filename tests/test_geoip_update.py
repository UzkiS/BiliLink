"""运行时 IP 段维护：热更新、失败回退、缓存与应用生命周期。"""

import asyncio
import logging
from collections.abc import Callable
from ipaddress import ip_address, ip_network
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from bililink.app import create_app
from bililink.config import Settings
from bililink.geoip import APNIC_DELEGATED_URL, MainlandChinaNetworks, render_data_file
from bililink.geoip_update import GeoIPUpdater
from fakes import FakeBilibili
from test_geoip import DELEGATED

pytestmark = pytest.mark.anyio


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():  # noqa: ASYNC110 - 等待后台更新的公开行为，无专用通知接口
            await asyncio.sleep(0.001)


def initial_networks() -> MainlandChinaNetworks:
    return MainlandChinaNetworks([ip_network("114.114.114.0/24"), ip_network("240f::/20")])


def make_updater(
    networks: MainlandChinaNetworks,
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    interval: float = 3600,
    cache_file: Path | None = None,
) -> GeoIPUpdater:
    return GeoIPUpdater(
        networks,
        interval=interval,
        timeout=2,
        cache_file=cache_file,
        transport=httpx2.MockTransport(handler),
    )


async def test_updates_both_address_families_without_writing_packaged_data() -> None:
    requests: list[httpx2.Request] = []
    networks = initial_networks()

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, text=DELEGATED)

    async with make_updater(networks, respond).running():
        await wait_until(lambda: ip_address("1.0.1.1") in networks)

    assert ip_address("240e::1") in networks
    assert ip_address("114.114.114.114") not in networks
    assert ip_address("240f::1") not in networks
    [request] = requests
    assert str(request.url) == APNIC_DELEGATED_URL
    assert "cookie" not in request.headers


async def test_replaces_data_again_on_next_interval() -> None:
    networks = initial_networks()
    requests = 0

    def respond(_request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        contents = DELEGATED if requests == 1 else DELEGATED.replace("1.0.1.0", "1.0.2.0")
        return httpx2.Response(200, text=contents)

    async with make_updater(networks, respond, interval=0.01).running():
        await wait_until(lambda: ip_address("1.0.1.1") in networks)
        await wait_until(lambda: ip_address("1.0.2.1") in networks)

    assert requests >= 2
    assert ip_address("1.0.1.1") not in networks


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "http",
        "incomplete",
        "empty",
        "malformed",
        "missing_ipv6",
    ],
)
async def test_failed_update_keeps_data_and_retries(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    networks = initial_networks()
    requests = 0
    malformed = {
        "incomplete": DELEGATED.replace("|8|19830613|", "|9|19830613|"),
        "empty": "2|apnic|20260926|0|19830613|20260925|+1000\n",
        "malformed": "bad\nrow\n",
        "missing_ipv6": DELEGATED.replace("apnic|CN|ipv6", "apnic|HK|ipv6"),
    }

    def respond(_request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        if requests > 1:
            return httpx2.Response(200, text=DELEGATED)
        if failure == "timeout":
            msg = "超时"
            raise httpx2.ReadTimeout(msg)
        if failure == "http":
            return httpx2.Response(503)
        return httpx2.Response(200, text=malformed[failure])

    async with make_updater(networks, respond, interval=0.1).running():
        await wait_until(lambda: "IP 段自动更新失败" in caplog.text)
        assert ip_address("114.114.114.114") in networks
        assert ip_address("1.0.1.1") not in networks
        await wait_until(lambda: ip_address("1.0.1.1") in networks)


async def test_disabled_updater_does_not_access_network() -> None:
    networks = initial_networks()

    def unexpected(_request: httpx2.Request) -> httpx2.Response:
        pytest.fail("关闭自动更新时不应访问网络")

    async with make_updater(networks, unexpected, interval=0).running():
        assert ip_address("114.114.114.114") in networks


async def test_successful_update_saves_cache_and_next_start_reads_it(tmp_path: Path) -> None:
    cache = tmp_path / "cache" / "cn_networks.txt"
    contents = render_data_file(DELEGATED)

    async with make_updater(
        initial_networks(),
        lambda _request: httpx2.Response(200, text=DELEGATED),
        cache_file=cache,
    ).running():
        await wait_until(cache.exists)

    assert cache.read_text(encoding="utf-8") == contents
    assert sorted(path.name for path in cache.parent.iterdir()) == [cache.name]
    networks = initial_networks()
    async with make_updater(
        networks,
        lambda _request: httpx2.Response(503),
        interval=0,
        cache_file=cache,
    ).running():
        assert ip_address("1.0.1.1") in networks
        assert ip_address("114.114.114.114") not in networks


async def test_missing_cache_uses_packaged_data(tmp_path: Path) -> None:
    networks = initial_networks()
    async with make_updater(
        networks,
        lambda _request: httpx2.Response(503),
        interval=0,
        cache_file=tmp_path / "missing.txt",
    ).running():
        assert ip_address("114.114.114.114") in networks


@pytest.mark.parametrize("contents", [b"invalid\n", b"\xff", None])
async def test_unreadable_cache_keeps_packaged_data(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, contents: bytes | None
) -> None:
    cache = tmp_path / "cache.txt"
    if contents is None:
        cache.mkdir()
    else:
        cache.write_bytes(contents)
    networks = initial_networks()
    async with make_updater(
        networks, lambda _request: httpx2.Response(503), interval=0, cache_file=cache
    ).running():
        assert ip_address("114.114.114.114") in networks

    assert "IP 段缓存读取失败" in caplog.text


async def test_cache_write_failure_still_updates_memory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = tmp_path / "cache.txt"
    cache.mkdir()
    networks = initial_networks()
    async with make_updater(
        networks, lambda _request: httpx2.Response(200, text=DELEGATED), cache_file=cache
    ).running():
        await wait_until(lambda: "IP 段缓存写入失败" in caplog.text)
        assert ip_address("1.0.1.1") in networks

    assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == [cache]


async def test_failed_download_preserves_last_successful_cache(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = tmp_path / "cache.txt"
    contents = render_data_file(DELEGATED)
    cache.write_text(contents, encoding="utf-8")
    networks = initial_networks()
    async with make_updater(
        networks, lambda _request: httpx2.Response(503), cache_file=cache
    ).running():
        await wait_until(lambda: "IP 段自动更新失败" in caplog.text)
        assert ip_address("1.0.1.1") in networks

    assert cache.read_text(encoding="utf-8") == contents


async def test_app_starts_without_waiting_and_uses_new_data_for_cdn_selection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def respond(request: httpx2.Request) -> httpx2.Response:
        assert "cookie" not in request.headers
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx2.Response(200, text=DELEGATED.replace("1.0.1.0", "8.8.8.0"))

    bilibili = FakeBilibili()
    app = create_app(
        Settings(
            geoip_update_interval=0.1,
            sessdata=SecretStr("secret-sessdata"),
            cdn_hosts=("mainland.example.com",),
            cdn_overseas_hosts=("overseas.example.com",),
        ),
        transport=bilibili.transport,
        geoip_transport=httpx2.MockTransport(respond),
    )
    caplog.set_level(logging.INFO, logger="bililink.geoip_update")
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app, client=("8.8.8.8", 50000)),
            base_url="http://test",
        ) as client,
    ):
        await asyncio.wait_for(started.wait(), timeout=3)
        assert (await client.get("/healthz")).status_code == 200
        before = await client.get("/BV1ex411J7GE")
        assert "overseas.example.com" in before.headers["location"]
        release.set()
        await wait_until(lambda: "中国大陆 IP 段已自动更新" in caplog.text)
        after = await client.get("/BV1ex411J7GE")
        assert "mainland.example.com" in after.headers["location"]
        release.clear()
        started.clear()
        await asyncio.wait_for(started.wait(), timeout=3)

    assert cancelled.is_set()
