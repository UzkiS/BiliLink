"""运行时配置：所有配置项、默认值与校验规则的唯一事实源。

配置从环境变量（前缀 ``BILILINK_``）或当前工作目录下的 ``.env`` 文件读取。
仓库根目录的 ``.env.example`` 由 :func:`render_env_example` 生成，不要手动编辑。
"""

import json
import os
from typing import Annotated, Literal, Self

from limits import parse_many
from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "BILILINK_"

type LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
type Hostname = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9.-]+(:\d+)?$")]


class Settings(BaseSettings):
    """BiliLink 的全部运行时配置；字段的 ``description`` 同时是 ``.env.example`` 中的说明。"""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        frozen=True,
    )

    host: str = Field(
        default="0.0.0.0",  # noqa: S104 - 这是对外提供服务的 HTTP 服务，容器内也必须监听所有网卡
        description="监听地址",
    )
    port: int = Field(default=5000, ge=1, le=65535, description="监听端口")
    forwarded_allow_ips: str = Field(
        default="127.0.0.1",
        description=(
            "受信任的反向代理 IP（逗号分隔，支持 CIDR）。"
            "只有来自这些地址的 X-Forwarded-For 才会被当作客户端 IP 用于限流；"
            "部署在反向代理之后必须正确设置，直接对外暴露时切勿设为 *"
        ),
    )
    rate_limit: str = Field(
        default="10/minute",
        description="每个客户端 IP 的限流规则，如 10/minute、100/hour（limits 库的限流字符串语法）",
    )
    sessdata: SecretStr | None = Field(
        default=None,
        description="B 站登录 Cookie 中的 SESSDATA；留空则以游客身份请求，可获取的画质较低",
    )
    request_timeout: float = Field(default=10.0, gt=0, description="请求 B 站接口的超时时间（秒）")
    cdn_hosts: tuple[Hostname, ...] = Field(
        default=(
            "upos-sz-mirrorcos.bilivideo.com",
            "upos-sz-mirrorali.bilivideo.com",
            "upos-sz-mirror08c.bilivideo.com",
        ),
        description=(
            "中国大陆访问者（以及内网等无法判断地区的访问者）改写视频直链时使用的 CDN 镜像域名"
            "（JSON 数组），每次随机选择一个；设为 [] 则保留 B 站返回的原始域名"
        ),
    )
    cdn_overseas_hosts: tuple[Hostname, ...] = Field(
        default=(
            "upos-sz-mirroraliov.bilivideo.com",
            "upos-sz-mirrorcosov.bilivideo.com",
        ),
        description=(
            "中国大陆以外的访问者改写视频直链时使用的 CDN 镜像域名，规则同 BILILINK_CDN_HOSTS；"
            "设为与 BILILINK_CDN_HOSTS 相同即不再按地区区分"
        ),
    )
    log_level: LogLevel = Field(
        default="INFO", description="日志级别：DEBUG、INFO、WARNING、ERROR 或 CRITICAL"
    )
    docs_enabled: bool = Field(
        default=False, description="是否开放 /docs 与 /openapi.json 接口文档"
    )
    reload: bool = Field(default=False, description="代码变更时自动重启，仅用于本地开发")

    @field_validator("rate_limit")
    @classmethod
    def _validate_rate_limit(cls, value: str) -> str:
        # 语法错误时 parse_many 抛出 ValueError；limits 允许用分号写多条规则，但限流器只执行一条。
        if len(parse_many(value)) != 1:
            msg = "只支持一条限流规则"
            raise ValueError(msg)
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _reject_unknown_environment_variables(self) -> Self:
        # pydantic-settings 只拒绝 .env 文件中的未知项；环境变量中的拼写错误
        # （如经 docker --env-file 传入的 BILILINK_SESDATA）同样要让启动失败，而不是被静默忽略。
        known = {f"{ENV_PREFIX}{name}".upper() for name in type(self).model_fields}
        unknown = sorted(
            name
            for name in os.environ
            if name.upper().startswith(ENV_PREFIX) and name.upper() not in known
        )
        if unknown:
            msg = f"未知的配置项：{'、'.join(unknown)}"
            raise ValueError(msg)
        return self


def render_env_example() -> str:
    """根据 :class:`Settings` 生成 ``.env.example`` 的完整内容。

    所有配置项都以注释形式给出默认值：使用者只需取消注释并修改需要调整的项，
    未设置的项始终跟随代码中的默认值，避免复制后的 ``.env`` 与新版本默认值脱节。
    """
    lines = [
        "# 由 `uv run poe env-example` 根据 src/bililink/config.py 自动生成，请勿手动编辑。",
        "# 使用方法：复制为 .env，只取消注释并修改需要调整的项。",
    ]
    for name, field in Settings.model_fields.items():
        lines += [
            "",
            f"# {field.description}",
            f"# {ENV_PREFIX}{name.upper()}={_format_env_value(field.default)}",
        ]
    return "\n".join(lines) + "\n"


def _format_env_value(value: object) -> str:
    """把默认值格式化为 pydantic-settings 能解析的环境变量写法。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple):
        return json.dumps(value)
    return str(value)
