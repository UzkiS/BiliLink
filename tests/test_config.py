"""运行时配置：读取来源与校验规则。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from bililink.config import Settings


def test_defaults_are_secure() -> None:
    settings = Settings()

    assert settings.forwarded_allow_ips == "127.0.0.1"
    assert settings.docs_enabled is False
    assert settings.reload is False
    assert settings.sessdata is None


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILILINK_PORT", "8080")
    monkeypatch.setenv("BILILINK_LOG_LEVEL", "debug")
    monkeypatch.setenv("BILILINK_CDN_HOSTS", '["mirror.example.com:8443"]')
    monkeypatch.setenv("BILILINK_CDN_OVERSEAS_HOSTS", "[]")
    monkeypatch.setenv("BILILINK_WEB_ENABLED", "false")
    monkeypatch.setenv("PORT", "9999")

    settings = Settings()

    assert settings.port == 8080
    assert settings.log_level == "DEBUG"
    assert settings.cdn_hosts == ("mirror.example.com:8443",)
    assert settings.cdn_overseas_hosts == ()
    assert settings.web_enabled is False


def test_reads_dotenv_in_working_directory(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("BILILINK_RATE_LIMIT=5/second\n", encoding="utf-8")

    assert Settings().rate_limit == "5/second"


def test_environment_variables_override_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("BILILINK_PORT=1111\n", encoding="utf-8")
    monkeypatch.setenv("BILILINK_PORT", "2222")

    assert Settings().port == 2222


def test_unknown_dotenv_entries_fail_fast(tmp_path: Path) -> None:
    # 拼写错误（SESDATA）不能被静默忽略，否则服务会在无提示的情况下以游客身份运行。
    (tmp_path / ".env").write_text("BILILINK_SESDATA=typo\n", encoding="utf-8")

    with pytest.raises(ValidationError, match=r"(?i)BILILINK_SESDATA"):
        Settings()


def test_unknown_environment_variables_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # 经 docker --env-file 传入的配置是环境变量，拼写错误同样不能被静默忽略。
    monkeypatch.setenv("BILILINK_SESDATA", "typo")

    with pytest.raises(ValidationError, match="未知的配置项：BILILINK_SESDATA"):
        Settings()


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILILINK_SESSDATA", "")

    assert Settings().sessdata is None


def test_sessdata_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILILINK_SESSDATA", "top-secret")

    settings = Settings()

    assert settings.sessdata is not None
    assert settings.sessdata.get_secret_value() == "top-secret"
    assert "top-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BILILINK_RATE_LIMIT", "ten per minute"),
        ("BILILINK_RATE_LIMIT", "10/minute;100/hour"),
        ("BILILINK_PORT", "0"),
        ("BILILINK_REQUEST_TIMEOUT", "0"),
        ("BILILINK_CDN_HOSTS", '["https://mirror.example.com"]'),
        ("BILILINK_CDN_OVERSEAS_HOSTS", '["mirror.example.com/path"]'),
        ("BILILINK_LOG_LEVEL", "verbose"),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_every_setting_is_documented() -> None:
    undocumented = [name for name, field in Settings.model_fields.items() if not field.description]

    assert not undocumented
