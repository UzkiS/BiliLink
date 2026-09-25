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
from bililink.resolver import Resolver

pytestmark = [pytest.mark.live, pytest.mark.anyio]

VIDEO = "BV1GJ411x7h7"  # Never Gonna Give You Up，长期稳定的单 P 稿件
MULTI_PAGE_VIDEO = "BV1ex411J7GE"  # 长期稳定的多 P 稿件
LIVE_ROOM = 6  # B 站官方直播间的短号


@pytest.fixture
async def client() -> AsyncIterator[BilibiliClient]:
    async with BilibiliClient(sessdata=None, timeout=Settings().request_timeout) as client:
        yield client


@pytest.fixture
def resolver(client: BilibiliClient) -> Resolver:
    return Resolver(client, cdn_hosts=Settings().cdn_hosts)


async def test_video_resolves_to_mp4_served_by_cdn_mirror(resolver: Resolver) -> None:
    url = await resolver.resolve_video(VIDEO, 1)

    assert urlsplit(url).netloc in Settings().cdn_hosts
    # 镜像节点必须真的能提供该文件；CDN 会拒绝部分非浏览器 User-Agent，这里使用浏览器 UA。
    headers = {"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1023"}
    async with httpx2.AsyncClient(headers=headers, timeout=10) as http:
        response = await http.get(url)
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"


async def test_multi_page_video_resolves_each_page(resolver: Resolver) -> None:
    first = await resolver.resolve_video(MULTI_PAGE_VIDEO, 1)
    second = await resolver.resolve_video(MULTI_PAGE_VIDEO, 2)

    assert urlsplit(first).path != urlsplit(second).path


@pytest.mark.parametrize(
    "bvid",
    [
        "BV1xx411c7m1",  # 不存在的稿件：-404
        "BV1zzzzzzzzz",  # 格式合法但不对应任何稿件：-400
    ],
)
async def test_invalid_videos_are_not_found(resolver: Resolver, bvid: str) -> None:
    with pytest.raises(NotFoundError):
        await resolver.resolve_video(bvid, 1)


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
