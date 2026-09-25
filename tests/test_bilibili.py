"""B 站接口客户端：请求参数、响应解析与错误映射。"""

import re

import httpx2
import pytest

from bililink.errors import NotFoundError, UpstreamError
from fakes import LIVE_ROOM_PLAY_INFO, PAGELIST, PLAYURL, FakeBilibili, error_payload, load_fixture

pytestmark = pytest.mark.anyio


async def test_get_video_pages(bilibili: FakeBilibili) -> None:
    async with bilibili.client() as client:
        pages = await client.get_video_pages("BV1ex411J7GE")

    assert [(page.page, page.cid) for page in pages] == [
        (1, 66445301),
        (2, 35039663),
        (3, 35039678),
    ]
    [request] = bilibili.requests
    assert request.url.params["bvid"] == "BV1ex411J7GE"


async def test_sends_browser_headers_and_no_cookie_by_default(bilibili: FakeBilibili) -> None:
    async with bilibili.client() as client:
        await client.get_video_pages("BV1ex411J7GE")

    [request] = bilibili.requests
    assert request.headers["User-Agent"].startswith("Mozilla/5.0")
    assert request.headers["Referer"] == "https://www.bilibili.com/"
    assert "Cookie" not in request.headers


async def test_sends_sessdata_cookie_when_configured(bilibili: FakeBilibili) -> None:
    async with bilibili.client(sessdata="secret-sessdata") as client:
        await client.get_video_pages("BV1ex411J7GE")

    [request] = bilibili.requests
    assert request.headers["Cookie"] == "SESSDATA=secret-sessdata"


async def test_get_video_play_info_requests_html5_mp4(bilibili: FakeBilibili) -> None:
    async with bilibili.client() as client:
        info = await client.get_video_play_info("BV1ex411J7GE", 35039663)

    assert info.durl[0].url.startswith("https://cn-jstz-cu-01-03.bilivideo.com/upgcxcode/")
    [request] = bilibili.requests
    assert request.url.params["cid"] == "35039663"
    assert request.url.params["platform"] == "html5"


async def test_get_live_room_play_info(bilibili: FakeBilibili) -> None:
    async with bilibili.client() as client:
        info = await client.get_live_room_play_info(6)

    assert info.playurl_info is not None
    streams = info.playurl_info.playurl.stream
    assert [codec.codec_name for codec in streams[0].format[0].codec] == ["avc", "hevc"]
    [request] = bilibili.requests
    assert request.url.params["room_id"] == "6"


async def test_offline_live_room_has_no_play_url(bilibili: FakeBilibili) -> None:
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, load_fixture("live_room_offline.json"))

    async with bilibili.client() as client:
        info = await client.get_live_room_play_info(1)

    assert info.playurl_info is None


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (-404, "啥都木有"),
        (-403, "访问权限不足"),
        (-10403, "抱歉您所在地区不能观看！"),
        (60004, "房间不存在"),
        (62002, "稿件不可见"),
        (62004, "稿件审核中"),
        (62012, "仅UP主自己可见"),
    ],
)
async def test_not_found_codes_raise_not_found_error(
    bilibili: FakeBilibili, code: int, message: str
) -> None:
    bilibili.respond_json(PAGELIST, error_payload(code, message))

    async with bilibili.client() as client:
        with pytest.raises(NotFoundError, match=re.escape(f"{message}（B 站错误码 {code}）")):
            await client.get_video_pages("BV1ex411J7GE")


async def test_rejected_bvid_raises_not_found_error(bilibili: FakeBilibili) -> None:
    # 格式合法但不对应任何稿件的 BV 号（如 BV1zzzzzzzzz），pagelist 返回 -400。
    bilibili.respond_json(PAGELIST, error_payload(-400, "请求错误"))

    async with bilibili.client() as client:
        with pytest.raises(NotFoundError, match=re.escape("请求错误（B 站错误码 -400）")):
            await client.get_video_pages("BV1zzzzzzzzz")


async def test_other_error_codes_raise_upstream_error(bilibili: FakeBilibili) -> None:
    bilibili.respond_json(PAGELIST, error_payload(-352, "风控校验失败"))

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match=re.escape("风控校验失败（错误码 -352）")):
            await client.get_video_pages("BV1ex411J7GE")


async def test_bad_request_on_play_url_raises_upstream_error(bilibili: FakeBilibili) -> None:
    # playurl 的参数由本服务构造，-400 说明请求方式与接口不再匹配，属于上游变更。
    bilibili.respond_json(PLAYURL, error_payload(-400, "请求错误"))

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match=re.escape("请求错误（错误码 -400）")):
            await client.get_video_play_info("BV1ex411J7GE", 35039663)


async def test_http_error_status_raises_upstream_error(bilibili: FakeBilibili) -> None:
    # B 站风控拦截时返回 HTTP 412 与一个 HTML 页面。
    bilibili.respond_with(PAGELIST, lambda _: httpx2.Response(412, html="<!DOCTYPE html>"))

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match="HTTP 412"):
            await client.get_video_pages("BV1ex411J7GE")


@pytest.mark.parametrize(
    "error", [httpx2.ConnectError("connection refused"), httpx2.ReadTimeout("timed out")]
)
async def test_network_errors_raise_upstream_error(
    bilibili: FakeBilibili, error: httpx2.HTTPError
) -> None:
    def fail(_request: httpx2.Request) -> httpx2.Response:
        raise error

    bilibili.respond_with(PAGELIST, fail)

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match=type(error).__name__):
            await client.get_video_pages("BV1ex411J7GE")


@pytest.mark.parametrize("body", [b"not json", b'{"message": "missing code"}'])
async def test_unrecognized_response_raises_upstream_error(
    bilibili: FakeBilibili, body: bytes
) -> None:
    bilibili.respond_with(PAGELIST, lambda _: httpx2.Response(200, content=body))

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match="无法识别"):
            await client.get_video_pages("BV1ex411J7GE")


async def test_success_without_data_raises_upstream_error(bilibili: FakeBilibili) -> None:
    bilibili.respond_json(PAGELIST, {"code": 0, "message": "OK", "ttl": 1})

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match="不符合预期"):
            await client.get_video_pages("BV1ex411J7GE")


async def test_empty_video_file_list_raises_upstream_error(bilibili: FakeBilibili) -> None:
    payload = load_fixture("playurl.json")
    payload["data"]["durl"] = []
    bilibili.respond_json(PLAYURL, payload)

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match="不符合预期"):
            await client.get_video_play_info("BV1ex411J7GE", 35039663)


async def test_empty_live_stream_list_raises_upstream_error(bilibili: FakeBilibili) -> None:
    payload = load_fixture("live_room_online.json")
    payload["data"]["playurl_info"]["playurl"]["stream"] = []
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, payload)

    async with bilibili.client() as client:
        with pytest.raises(UpstreamError, match="不符合预期"):
            await client.get_live_room_play_info(6)
