"""业务异常与错误响应格式。

每种异常自带对应的 HTTP 状态码，由 :mod:`bililink.app` 统一转换为 :class:`ErrorResponse`。
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import ClassVar

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """所有错误响应的统一 JSON 格式。"""

    error: str


class BiliLinkError(Exception):
    """可以直接转换为 HTTP 错误响应的业务异常基类。"""

    status_code: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.headers = dict(headers or {})


class NotFoundError(BiliLinkError):
    """视频、分 P 或直播间不存在，或当前无法观看（如地区限制、直播间未开播）。"""

    status_code = HTTPStatus.NOT_FOUND


class UpstreamError(BiliLinkError):
    """B 站接口不可达、返回错误，或返回了无法识别的数据。"""

    status_code = HTTPStatus.BAD_GATEWAY


class RateLimitedError(BiliLinkError):
    """客户端超出限流配额。"""

    status_code = HTTPStatus.TOO_MANY_REQUESTS

    def __init__(self, *, retry_after: int) -> None:
        super().__init__("请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
