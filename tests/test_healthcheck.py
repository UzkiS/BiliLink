"""容器健康检查命令。"""

import httpx2
import pytest

from bililink.healthcheck import main

type Call = tuple[str, dict[str, object]]


def stub_get(monkeypatch: pytest.MonkeyPatch, response: httpx2.Response | Exception) -> list[Call]:
    calls: list[Call] = []

    def fake_get(url: httpx2.URL, **kwargs: object) -> httpx2.Response:
        calls.append((str(url), kwargs))
        if isinstance(response, Exception):
            raise response
        response.request = httpx2.Request("GET", url)
        return response

    monkeypatch.setattr(httpx2, "get", fake_get)
    return calls


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("0.0.0.0", "http://127.0.0.1:8080/healthz"),  # noqa: S104 - 验证监听所有网卡时改用回环地址
        ("::", "http://[::1]:8080/healthz"),
        ("10.1.2.3", "http://10.1.2.3:8080/healthz"),
        ("bililink.internal", "http://bililink.internal:8080/healthz"),
    ],
)
def test_healthy_service_exits_zero(monkeypatch: pytest.MonkeyPatch, host: str, url: str) -> None:
    monkeypatch.setenv("BILILINK_HOST", host)
    monkeypatch.setenv("BILILINK_PORT", "8080")
    calls = stub_get(monkeypatch, httpx2.Response(200, json={"status": "ok"}))

    assert main() == 0
    [(requested, kwargs)] = calls
    assert requested == url
    assert kwargs["trust_env"] is False  # 不经过 HTTP(S)_PROXY 等代理


@pytest.mark.parametrize(
    "response", [httpx2.Response(503), httpx2.ConnectError("connection refused")]
)
def test_unhealthy_service_exits_one(
    monkeypatch: pytest.MonkeyPatch, response: httpx2.Response | Exception
) -> None:
    stub_get(monkeypatch, response)

    assert main() == 1
