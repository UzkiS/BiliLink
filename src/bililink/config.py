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
            "受信任的反向代理地址（逗号分隔，支持 CIDR）。只有来自这些地址的请求，"
            "才会采用 X-Forwarded-For 中的客户端 IP 来限流和判断观看者地区；"
            "部署在反向代理之后必须设为代理的地址，服务直接对外暴露时切勿设为 *"
        ),
    )
    rate_limit: str = Field(
        default="10/minute",
        description=(
            "每个客户端 IP（IPv6 按 /64 网段）的请求次数上限，写作“次数/时间单位”，"
            "如 10/minute、100/hour，单位可用 second、minute、hour、day；"
            "只统计视频链接、直播链接与网页查询视频的请求"
        ),
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
            "中国大陆观看者（以及内网等无法判断地区的观看者）使用的视频 CDN 镜像域名，"
            "JSON 数组，每次随机选择一个；设为 [] 则使用 B 站返回的原始地址"
        ),
    )
    cdn_overseas_hosts: tuple[Hostname, ...] = Field(
        default=(
            "upos-sz-mirroraliov.bilivideo.com",
            "upos-sz-mirrorcosov.bilivideo.com",
        ),
        description=(
            "中国大陆以外的观看者使用的视频 CDN 镜像域名，格式同 BILILINK_CDN_HOSTS；"
            "设为与 BILILINK_CDN_HOSTS 相同即不再按地区区分"
        ),
    )
    geoip_update_interval: float = Field(
        default=86400.0,
        ge=0,
        description=(
            "判断观看者地区所用的中国大陆 IP 段的自动更新间隔（秒）：启动后立即在后台"
            "从 APNIC 下载，之后按此间隔更新，失败时继续使用已有数据；设为 0 则只使用内置数据"
        ),
    )
    geoip_update_timeout: float = Field(
        default=60.0, gt=0, description="从 APNIC 下载 IP 段数据的超时时间（秒）"
    )
    log_level: LogLevel = Field(
        default="INFO", description="日志级别：DEBUG、INFO、WARNING、ERROR 或 CRITICAL"
    )
    web_enabled: bool = Field(default=True, description="是否开放网页界面（/）及其使用的 /api 接口")
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
        "# BiliLink 配置：每一项都以注释形式给出默认值。",
        "# 复制为 .env 后，只取消注释并修改需要调整的项。",
        "# 未设置的项使用默认值，升级后跟随新版本的默认值。",
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
