"""唯一事实源守护：由定义处派生或引用定义处的文件，必须与定义保持一致。"""

import re
import tomllib
from http import HTTPStatus
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from bililink.app import create_app
from bililink.bilibili import BVID_PATTERN
from bililink.config import Settings, render_env_example

ROOT = Path(__file__).parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_env_example_is_generated_from_settings() -> None:
    assert read(".env.example") == render_env_example(), (
        ".env.example 与 src/bililink/config.py 不一致，请运行 `uv run poe env-example`"
    )


def test_docker_image_uses_supported_uv_version() -> None:
    required = tomllib.loads(read("pyproject.toml"))["tool"]["uv"]["required-version"]
    [version] = re.findall(
        r"^FROM ghcr\.io/astral-sh/uv:([\d.]+)-", read("Dockerfile"), re.MULTILINE
    )

    assert Version(version) in SpecifierSet(required), (
        f"Dockerfile 中的 uv {version} 不满足 pyproject.toml 的 required-version（{required}）"
    )


@pytest.mark.parametrize("name", ["README.md", "compose.yaml"])
def test_examples_use_default_port(name: str) -> None:
    # 形如“地址:端口”“-p 端口:端口”，以及 compose.yaml 中的默认值写法 ${BILILINK_PORT:-端口}。
    ports = set(re.findall(r":-?(\d{4,5})\b", read(name)))

    assert ports == {str(Settings().port)}, f"{name} 中示例使用的端口应与默认端口一致"


def test_readme_documents_every_error_status() -> None:
    schema = create_app(Settings()).openapi()
    api_errors = {
        int(status)
        for operation in schema["paths"].values()
        for status in operation["get"]["responses"]
        if int(status) >= HTTPStatus.BAD_REQUEST
    }
    readme_errors = {int(s) for s in re.findall(r"^\| (\d{3}) \|", read("README.md"), re.MULTILINE)}

    assert readme_errors == api_errors, "README 的错误码表应与 routes.py 中声明的错误响应一致"


@pytest.mark.parametrize("name", ["README.md", "compose.yaml"])
def test_image_name_matches_repository(name: str) -> None:
    repository = tomllib.loads(read("pyproject.toml"))["project"]["urls"]["Repository"]
    image = f"ghcr.io/{repository.removeprefix('https://github.com/').lower()}"

    assert set(re.findall(r"ghcr\.io/[\w./-]+?(?=:)", read(name))) == {image}, (
        f"{name} 中的镜像地址应为 {image}（由 pyproject.toml 的仓库地址决定）"
    )


def test_web_page_uses_bvid_pattern() -> None:
    assert f'const BVID_PATTERN = "{BVID_PATTERN}";' in read("src/bililink/web/assets/app.js"), (
        "网页识别 BV 号所用的正则应与 bilibili.BVID_PATTERN 一致"
    )
