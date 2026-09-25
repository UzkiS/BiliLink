"""HTTP 接口契约：路由、状态码、重定向目标与统一的错误响应格式。"""

import logging
from urllib.parse import urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from bililink import __version__
from bililink.app import create_app
from bililink.bilibili import BVID_PATTERN
from bililink.config import Settings
from fakes import (
    LIVE_ROOM_PLAY_INFO,
    PAGELIST,
    PLAYURL,
    ClientFactory,
    FakeBilibili,
    error_payload,
    load_fixture,
)


def test_video_redirects_to_mp4_on_cdn_mirror(client: TestClient, bilibili: FakeBilibili) -> None:
    response = client.get("/BV1ex411J7GE")

    assert response.status_code == 307
    location = urlsplit(response.headers["location"])
    assert location.netloc in Settings().cdn_hosts
    assert location.path.endswith(".mp4")
    [request] = bilibili.requests_to(PLAYURL)
    assert request.url.params["cid"] == "66445301"


def test_video_page_parameter_selects_page(client: TestClient, bilibili: FakeBilibili) -> None:
    response = client.get("/BV1ex411J7GE", params={"p": 2})

    assert response.status_code == 307
    [request] = bilibili.requests_to(PLAYURL)
    assert request.url.params["cid"] == "35039663"


@pytest.mark.parametrize(
    ("page", "error"),
    [
        ("0", "请求参数无效：p 必须大于等于 1"),
        ("-1", "请求参数无效：p 必须大于等于 1"),
        ("abc", "请求参数无效：p 必须是整数"),
    ],
)
def test_invalid_page_parameter_returns_422(
    client: TestClient, bilibili: FakeBilibili, page: str, error: str
) -> None:
    response = client.get("/BV1ex411J7GE", params={"p": page})

    assert response.status_code == 422
    assert response.json() == {"error": error}
    assert not bilibili.requests


def test_missing_page_returns_404(client: TestClient) -> None:
    response = client.get("/BV1ex411J7GE", params={"p": 4})

    assert response.status_code == 404
    assert response.json() == {"error": "视频 BV1ex411J7GE 没有第 4 P（共 3 P）"}


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/favicon.ico",
        "/BV1ex411J7G",  # 少一位
        "/BV1ex411J7GEE",  # 多一位
        "/BV1ex411J7G0",  # 含 base58 之外的字符
        "/video/BV1ex411J7GE",
        "/BV1ex411J7GE/",  # 尾部斜杠不会被重定向
        "/live/abc",
        "/live/6/",
        "/live/6/extra",
    ],
)
def test_unknown_paths_return_404_without_calling_bilibili(
    client: TestClient, bilibili: FakeBilibili, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"error": "路径不存在"}
    assert "location" not in response.headers
    assert not bilibili.requests


def test_upstream_not_found_returns_404(client: TestClient, bilibili: FakeBilibili) -> None:
    bilibili.respond_json(PAGELIST, error_payload(-404, "啥都木有"))

    response = client.get("/BV1ex411J7GE")

    assert response.status_code == 404
    assert response.json() == {"error": "啥都木有（B 站错误码 -404）"}


def test_rejected_bvid_returns_404_without_warning(
    client: TestClient, bilibili: FakeBilibili, caplog: pytest.LogCaptureFixture
) -> None:
    bilibili.respond_json(PAGELIST, error_payload(-400, "请求错误"))

    with caplog.at_level(logging.WARNING, logger="bililink"):
        response = client.get("/BV1zzzzzzzzz")

    assert response.status_code == 404
    assert response.json() == {"error": "请求错误（B 站错误码 -400）"}
    assert not caplog.messages


def test_upstream_failure_returns_502_and_logs_warning(
    client: TestClient, bilibili: FakeBilibili, caplog: pytest.LogCaptureFixture
) -> None:
    bilibili.respond_with(PAGELIST, lambda _: httpx2.Response(412, html="<!DOCTYPE html>"))

    with caplog.at_level(logging.WARNING, logger="bililink"):
        response = client.get("/BV1ex411J7GE")

    assert response.status_code == 502
    assert response.json() == {"error": "B 站接口返回 HTTP 412"}
    [message] = caplog.messages
    assert message.startswith(
        "GET /BV1ex411J7GE 失败：B 站接口返回 HTTP 412（原因：HTTPStatusError("
    )


def test_upstream_error_code_is_logged_without_cause(
    client: TestClient, bilibili: FakeBilibili, caplog: pytest.LogCaptureFixture
) -> None:
    bilibili.respond_json(PAGELIST, error_payload(-352, "风控校验失败"))

    with caplog.at_level(logging.WARNING, logger="bililink"):
        response = client.get("/BV1ex411J7GE")

    assert response.status_code == 502
    assert caplog.messages == [
        "GET /BV1ex411J7GE 失败：B 站接口返回错误：风控校验失败（错误码 -352）"
    ]


def test_live_redirects_to_hls_stream(client: TestClient, bilibili: FakeBilibili) -> None:
    response = client.get("/live/6")

    assert response.status_code == 307
    assert urlsplit(response.headers["location"]).path.endswith(".m3u8")
    [request] = bilibili.requests_to(LIVE_ROOM_PLAY_INFO)
    assert request.url.params["room_id"] == "6"


def test_offline_live_room_returns_404(client: TestClient, bilibili: FakeBilibili) -> None:
    bilibili.respond_json(LIVE_ROOM_PLAY_INFO, load_fixture("live_room_offline.json"))

    response = client.get("/live/1")

    assert response.status_code == 404
    assert response.json() == {"error": "直播间 1 当前未开播"}


def test_invalid_room_id_returns_422(client: TestClient, bilibili: FakeBilibili) -> None:
    response = client.get("/live/0")

    assert response.status_code == 422
    assert response.json() == {"error": "请求参数无效：room_id 必须大于等于 1"}
    assert not bilibili.requests


def test_unsupported_method_returns_405(client: TestClient) -> None:
    response = client.post("/BV1ex411J7GE")

    assert response.status_code == 405
    assert response.json() == {"error": "不支持该请求方法"}
    assert response.headers["allow"] == "GET"


def test_unexpected_error_returns_json_500(bilibili: FakeBilibili) -> None:
    def crash(_request: httpx2.Request) -> httpx2.Response:
        msg = "bug"
        raise RuntimeError(msg)

    bilibili.respond_with(PAGELIST, crash)
    app = create_app(Settings(), transport=bilibili.transport)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/BV1ex411J7GE")

    assert response.status_code == 500
    assert response.json() == {"error": "服务器内部错误"}


def test_settings_are_applied_to_bilibili_requests(
    make_client: ClientFactory, bilibili: FakeBilibili
) -> None:
    client = make_client(Settings(sessdata=SecretStr("secret-sessdata"), request_timeout=3))

    assert client.get("/BV1ex411J7GE").status_code == 307
    assert client.get("/live/6").status_code == 307

    assert {request.url.path for request in bilibili.requests} == {
        PAGELIST,
        PLAYURL,
        LIVE_ROOM_PLAY_INFO,
    }
    for request in bilibili.requests:
        assert request.headers["Cookie"] == "SESSDATA=secret-sessdata"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 3
        )


def test_rate_limit_is_shared_by_media_routes(make_client: ClientFactory) -> None:
    client = make_client(Settings(rate_limit="2/minute"))

    assert client.get("/BV1ex411J7GE").status_code == 307
    assert client.get("/live/6").status_code == 307
    response = client.get("/BV1ex411J7GE")

    assert response.status_code == 429
    assert response.json() == {"error": "请求过于频繁，请稍后再试"}
    assert 1 <= int(response.headers["retry-after"]) <= 60


def test_health_check_is_not_rate_limited(
    make_client: ClientFactory, bilibili: FakeBilibili
) -> None:
    client = make_client(Settings(rate_limit="1/minute"))

    for _ in range(3):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    assert not bilibili.requests


def test_docs_are_disabled_by_default(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_openapi_documents_routes_and_error_format(make_client: ClientFactory) -> None:
    client = make_client(Settings(docs_enabled=True))

    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == __version__
    assert set(schema["paths"]) == {"/healthz", "/live/{room_id}", "/{bvid}"}
    video_responses = schema["paths"]["/{bvid}"]["get"]["responses"]
    assert set(video_responses) == {"307", "404", "422", "429", "502"}
    assert video_responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    parameters = {p["name"]: p for p in schema["paths"]["/{bvid}"]["get"]["parameters"]}
    assert parameters["bvid"]["schema"]["pattern"] == f"^{BVID_PATTERN}$"


def test_create_app_reads_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch, bilibili: FakeBilibili
) -> None:
    monkeypatch.setenv("BILILINK_DOCS_ENABLED", "true")

    with TestClient(create_app(transport=bilibili.transport)) as client:
        assert client.get("/openapi.json").status_code == 200
