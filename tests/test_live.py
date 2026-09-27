"""真实 B 站接口测试：验证上游接口仍然符合本项目的假设，及早发现 B 站的接口变更。

这些测试访问真实网络，默认不运行：本地用 ``uv run poe test-live`` 运行，CI 每天定时运行一次。
只断言稳定的事实（知名稿件可以解析、镜像节点可以访问、错误码含义不变），不依赖直播间此刻是否开播。
"""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx2
import pytest

from bililink.bilibili import BilibiliClient
from bililink.config import Settings
from bililink.errors import NotFoundError
from bililink.geoip import load_mainland_china_networks
from bililink.resolver import Resolver

pytestmark = [pytest.mark.live, pytest.mark.anyio]

VIDEO = "BV1GJ411x7h7"  # Never Gonna Give You Up，长期稳定的单 P 稿件
MULTI_PAGE_VIDEO = "BV1ex411J7GE"  # 长期稳定的多 P 稿件
LIVE_ROOM = 6  # B 站官方直播间的短号
SETTINGS = Settings()


@pytest.fixture
async def client() -> AsyncIterator[BilibiliClient]:
    async with BilibiliClient(sessdata=None, timeout=SETTINGS.request_timeout) as client:
        yield client


@pytest.fixture
def resolver(client: BilibiliClient) -> Resolver:
    return Resolver(
        client,
        cdn_hosts=SETTINGS.cdn_hosts,
        cdn_overseas_hosts=SETTINGS.cdn_overseas_hosts,
        mainland_networks=load_mainland_china_networks(),
    )


@pytest.mark.parametrize("host", [*SETTINGS.cdn_hosts, *SETTINGS.cdn_overseas_hosts])
async def test_default_cdn_mirrors_serve_video(client: BilibiliClient, host: str) -> None:
    resolver = Resolver(
        client,
        cdn_hosts=(host,),
        cdn_overseas_hosts=(host,),
        mainland_networks=load_mainland_china_networks(),
    )
    url = await resolver.resolve_video(VIDEO, 1, None)

    assert urlsplit(url).netloc == host
    # CDN 会拒绝部分非浏览器 User-Agent，这里使用浏览器 UA。
    headers = {"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1023"}
    async with httpx2.AsyncClient(headers=headers, timeout=15) as http:
        try:
            response = await http.get(url)
        except httpx2.TimeoutException:
            # 跨境访问（如在海外的 CI 上访问中国大陆镜像）偶尔超时，这是网络波动而不是镜像下线；
            # 镜像下线表现为域名无法解析或返回 403、404，这些情况仍会让测试失败。
            pytest.skip(f"{host} 连接超时，可能是跨境网络波动")
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"


async def test_multi_page_video_resolves_each_page(resolver: Resolver) -> None:
    first = await resolver.resolve_video(MULTI_PAGE_VIDEO, 1, None)
    second = await resolver.resolve_video(MULTI_PAGE_VIDEO, 2, None)

    assert urlsplit(first).path != urlsplit(second).path


async def test_video_info_lists_every_page(client: BilibiliClient) -> None:
    info = await client.get_video_info(MULTI_PAGE_VIDEO)

    assert info.title
    assert info.pic.startswith("https://")
    assert [page.page for page in info.pages] == list(range(1, len(info.pages) + 1))
    assert len(info.pages) > 1
    assert all(page.part and page.duration > 0 for page in info.pages)


@pytest.mark.parametrize(
    "bvid",
    [
        "BV1xx411c7m1",  # 不存在的稿件：-404
        "BV1zzzzzzzzz",  # 格式合法但不对应任何稿件：-400
    ],
)
async def test_invalid_videos_are_not_found(
    client: BilibiliClient, resolver: Resolver, bvid: str
) -> None:
    with pytest.raises(NotFoundError):
        await resolver.resolve_video(bvid, 1, None)
    with pytest.raises(NotFoundError):
        await client.get_video_info(bvid)


async def test_live_room_resolves_to_hls_when_online(
    client: BilibiliClient, resolver: Resolver
) -> None:
    room = await client.get_live_room_play_info(LIVE_ROOM)  # 能解析即说明响应结构未变
    if room.playurl_info is None:
        pytest.skip(f"直播间 {LIVE_ROOM} 当前未开播")

    url = await resolver.resolve_live(LIVE_ROOM)

    assert urlsplit(url).path.endswith(".m3u8")


async def test_nonexistent_live_room_is_not_found(client: BilibiliClient) -> None:
    with pytest.raises(NotFoundError):
        await client.get_live_room_play_info(999_999_999_999)
