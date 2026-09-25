"""业务规则：分 P 选择、CDN 改写、直播编码选择与重定向目标校验。"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pytest

from bililink.errors import NotFoundError, UpstreamError
from bililink.resolver import Resolver
from fakes import LIVE_ROOM_PLAY_INFO, PLAYURL, FakeBilibili, load_fixture

pytestmark = pytest.mark.anyio

CDN_HOSTS = ("mirror-a.example.com", "mirror-b.example.com")
ORIGINAL_VIDEO_URL = load_fixture("playurl.json")["data"]["durl"][0]["url"]


@asynccontextmanager
async def make_resolver(
    bilibili: FakeBilibili, cdn_hosts: Sequence[str] = CDN_HOSTS
) -> AsyncIterator[Resolver]:
    async with bilibili.client() as client:
        yield Resolver(client, cdn_hosts=cdn_hosts)


async def test_resolve_video_uses_cid_of_requested_page(bilibili: FakeBilibili) -> None:
    async with make_resolver(bilibili) as resolver:
        await resolver.resolve_video("BV1ex411J7GE", 3)

    [request] = bilibili.requests_to(PLAYURL)
    assert request.url.params["cid"] == "35039678"


async def test_resolve_video_rewrites_host_to_a_cdn_mirror(bilibili: FakeBilibili) -> None:
    async with make_resolver(bilibili) as resolver:
        url = await resolver.resolve_video("BV1ex411J7GE", 2)

    resolved, original = urlsplit(url), urlsplit(ORIGINAL_VIDEO_URL)
    assert resolved.netloc in CDN_HOSTS
    assert resolved._replace(netloc=original.netloc) == original


async def test_resolve_video_keeps_original_host_without_cdn_hosts(
    bilibili: FakeBilibili,
) -> None:
    async with make_resolver(bilibili, cdn_hosts=()) as resolver:
        url = await resolver.resolve_video("BV1ex411J7GE", 2)

    assert url == ORIGINAL_VIDEO_URL


async def test_resolve_video_rejects_missing_page(bilibili: FakeBilibili) -> None:
    async with make_resolver(bilibili) as resolver:
        with pytest.raises(NotFoundError, match="视频 BV1ex411J7GE 没有第 4 P（共 3 P）"):
            await resolver.resolve_video("BV1ex411J7GE", 4)

    assert not bilibili.requests_to(PLAYURL)


@pytest.mark.parametrize("url", ["ftp://example.com/video.mp4", "/relative/video.mp4", ""])
async def test_resolve_video_rejects_invalid_url(bilibili: FakeBilibili, url: str) -> None:
    payload = load_fixture("playurl.json")
    payload["data"]["durl"][0]["url"] = url
    bilibili.respond_json(PLAYURL, payload)

    async with make_resolver(bilibili, cdn_hosts=()) as resolver:
        with pytest.raises(UpstreamError, match="无效的播放地址"):
            await resolver.resolve_video("BV1ex411J7GE", 2)


async def test_resolve_live_returns_hls_url_of_avc_stream(bilibili: FakeBilibili) -> None:
    async with make_resolver(bilibili) as resolver:
        url = await resolver.resolve_live(6)

    assert url == (
        "https://d1--cn-gotcha104.bilivideo.com/live-bvc/496286/live_50329118_9516950_2500.m3u8"
        "?expires=1790000000&len=0&oi=0&pt=h5&qn=10000&trid=placeholder&sign=placeholder"
    )


async def test_resolve_live_prefers_avc_regardless_of_order(bilibili: FakeBilibili) -> None:
    payload = load_fixture("live_room_online.json")
    payload["data"]["playurl_info"]["playurl"]["stream"][0]["format"][0]["codec"].reverse()
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, payload)

    async with make_resolver(bilibili) as resolver:
        url = await resolver.resolve_live(6)

    assert "_2500.m3u8" in url


async def test_resolve_live_falls_back_to_first_codec_without_avc(
    bilibili: FakeBilibili,
) -> None:
    payload = load_fixture("live_room_online.json")
    live_format = payload["data"]["playurl_info"]["playurl"]["stream"][0]["format"][0]
    live_format["codec"] = [c for c in live_format["codec"] if c["codec_name"] == "hevc"]
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, payload)

    async with make_resolver(bilibili) as resolver:
        url = await resolver.resolve_live(6)

    assert "_minihevc.m3u8" in url


async def test_resolve_live_rejects_offline_room(bilibili: FakeBilibili) -> None:
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, load_fixture("live_room_offline.json"))

    async with make_resolver(bilibili) as resolver:
        with pytest.raises(NotFoundError, match="直播间 1 当前未开播"):
            await resolver.resolve_live(1)


async def test_resolve_live_rejects_invalid_url(bilibili: FakeBilibili) -> None:
    payload = load_fixture("live_room_online.json")
    for stream in payload["data"]["playurl_info"]["playurl"]["stream"]:
        for live_format in stream["format"]:
            for codec in live_format["codec"]:
                for url_info in codec["url_info"]:
                    url_info["host"] = ""
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, payload)

    async with make_resolver(bilibili) as resolver:
        with pytest.raises(UpstreamError, match="无效的播放地址"):
            await resolver.resolve_live(6)
