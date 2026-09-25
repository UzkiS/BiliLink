"""pytest 公共夹具。"""

import os
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bililink.app import create_app
from bililink.config import ENV_PREFIX, Settings
from fakes import ClientFactory, FakeBilibili


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """清除 ``BILILINK_*`` 环境变量并切换到空目录，使本机的配置与 ``.env`` 不影响测试。"""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def bilibili() -> FakeBilibili:
    return FakeBilibili()


@pytest.fixture
def make_client(bilibili: FakeBilibili) -> Iterator[ClientFactory]:
    """按给定配置启动应用（含 lifespan）并返回测试客户端，B 站接口由 ``bilibili`` 替身提供。"""
    with ExitStack() as stack:

        def make(settings: Settings) -> TestClient:
            app = create_app(settings, transport=bilibili.transport)
            return stack.enter_context(TestClient(app, follow_redirects=False))

        yield make


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client(Settings())
