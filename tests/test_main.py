"""命令行入口：uvicorn 的启动参数全部来自 Settings。"""

from pathlib import Path
from typing import Any

import pytest
import uvicorn
from uvicorn.config import LOGGING_CONFIG

import bililink
from bililink.__main__ import build_log_config, main


def run_main(monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict[str, Any]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    main()

    [call] = calls
    return call


def test_main_starts_uvicorn_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILILINK_HOST", "127.0.0.1")
    monkeypatch.setenv("BILILINK_PORT", "8080")
    monkeypatch.setenv("BILILINK_FORWARDED_ALLOW_IPS", "10.0.0.0/8")
    monkeypatch.setenv("BILILINK_LOG_LEVEL", "debug")

    app, kwargs = run_main(monkeypatch)

    assert app == "bililink.app:create_app"
    assert kwargs["factory"] is True
    assert (kwargs["host"], kwargs["port"]) == ("127.0.0.1", 8080)
    assert kwargs["reload"] is False
    assert kwargs["reload_dirs"] is None
    assert kwargs["proxy_headers"] is True
    assert kwargs["forwarded_allow_ips"] == "10.0.0.0/8"
    assert kwargs["log_level"] == "debug"
    assert kwargs["log_config"]["loggers"]["bililink"]["level"] == "DEBUG"


def test_reload_watches_only_package_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILILINK_RELOAD", "true")

    _, kwargs = run_main(monkeypatch)

    assert kwargs["reload"] is True
    assert kwargs["reload_dirs"] == [str(Path(bililink.__file__).parent)]


def test_log_config_routes_app_logs_to_uvicorn_handler() -> None:
    config = build_log_config("INFO")

    app_logger = config["loggers"]["bililink"]
    assert app_logger["propagate"] is False
    assert set(app_logger["handlers"]) <= set(config["handlers"])
    assert "bililink" not in LOGGING_CONFIG["loggers"]
