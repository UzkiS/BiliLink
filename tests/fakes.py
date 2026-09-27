"""测试替身：用 ``httpx2.MockTransport`` 模拟 B 站接口，测试中不会发出任何真实网络请求。"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx2
from fastapi.testclient import TestClient

from bililink.bilibili import BilibiliClient
from bililink.config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"

PAGELIST = "/x/player/pagelist"
PLAYURL = "/x/player/playurl"
VIDEO_INFO = "/x/web-interface/view"
LIVE_ROOM_PLAY_INFO = "/xlive/web-room/v2/index/getRoomPlayInfo"

type Handler = Callable[[httpx2.Request], httpx2.Response]


class ClientFactory(Protocol):
    """``make_client`` 夹具：按给定配置启动应用，``client_ip`` 为测试客户端的来源地址。"""

    def __call__(self, settings: Settings, *, client_ip: str = ...) -> TestClient: ...


def load_fixture(name: str) -> dict[str, Any]:
    """读取 ``tests/fixtures`` 下的接口响应（录制自真实接口，已裁剪并脱敏）。"""
    payload: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return payload


def error_payload(code: int, message: str) -> dict[str, Any]:
    """构造 B 站业务错误响应：HTTP 200，``code`` 非 0 且没有 ``data``。"""
    return {"code": code, "message": message, "ttl": 1}


class FakeBilibili:
    """按请求路径返回预设响应的 B 站接口替身，并记录收到的全部请求。

    默认所有接口都返回正常的真实响应，测试只需覆盖自己关心的接口。
    """

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self._handlers: dict[str, Handler] = {}
        self.respond_json(PAGELIST, load_fixture("pagelist.json"))
        self.respond_json(PLAYURL, load_fixture("playurl.json"))
        self.respond_json(VIDEO_INFO, load_fixture("view.json"))
        self.respond_json(LIVE_ROOM_PLAY_INFO, load_fixture("live_room_online.json"))

    @property
    def transport(self) -> httpx2.MockTransport:
        """注入 :class:`BilibiliClient` 或 ``create_app`` 的网络层。"""
        return httpx2.MockTransport(self._handle)

    def client(self, *, sessdata: str | None = None) -> BilibiliClient:
        """创建连接到本替身的客户端。"""
        return BilibiliClient(sessdata=sessdata, timeout=5, transport=self.transport)

    def respond_json(self, path: str, payload: object, *, status_code: int = 200) -> None:
        """让 ``path`` 返回 JSON 响应。"""
        self.respond_with(path, lambda _request: httpx2.Response(status_code, json=payload))

    def respond_with(self, path: str, handler: Handler) -> None:
        """让 ``path`` 交由自定义函数处理，可返回任意响应或抛出网络异常。"""
        self._handlers[path] = handler

    def requests_to(self, path: str) -> list[httpx2.Request]:
        """返回发往 ``path`` 的全部请求。"""
        return [request for request in self.requests if request.url.path == path]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._handlers[request.url.path](request)
