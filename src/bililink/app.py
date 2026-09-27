"""应用组装：根据 :class:`~bililink.config.Settings` 创建 FastAPI 应用。"""

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from bililink import __version__
from bililink.bilibili import BilibiliClient
from bililink.config import Settings
from bililink.errors import BiliLinkError, ErrorResponse
from bililink.geoip import load_mainland_china_networks
from bililink.ratelimit import RateLimiter
from bililink.resolver import Resolver
from bililink.routes import health_router, media_router

logger = logging.getLogger(__name__)

# 路由层产生的错误（路径不存在、方法不允许）改用中文说明，其余保留原始信息。
_HTTP_ERROR_MESSAGES: dict[int, str] = {
    HTTPStatus.NOT_FOUND: "路径不存在",
    HTTPStatus.METHOD_NOT_ALLOWED: "不支持该请求方法",
}
# pydantic 校验错误类型的中文说明；未覆盖的类型保留 pydantic 的原始信息。
_VALIDATION_MESSAGES = {
    "int_parsing": "必须是整数",
    "greater_than_equal": "必须大于等于 {ge}",
}


def create_app(
    settings: Settings | None = None, *, transport: httpx2.AsyncBaseTransport | None = None
) -> FastAPI:
    """创建应用实例。

    Args:
        settings: 运行配置；省略时从环境变量与 ``.env`` 读取。
        transport: 访问 B 站所用的网络层；省略时使用真实网络，测试时注入 ``httpx2.MockTransport``。
    """
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sessdata = settings.sessdata.get_secret_value() if settings.sessdata else None
        async with BilibiliClient(
            sessdata=sessdata, timeout=settings.request_timeout, transport=transport
        ) as client:
            app.state.resolver = Resolver(
                client,
                cdn_hosts=settings.cdn_hosts,
                cdn_overseas_hosts=settings.cdn_overseas_hosts,
                mainland_networks=load_mainland_china_networks(),
            )
            yield

    app = FastAPI(
        title="BiliLink",
        summary="把 B 站视频 BV 号 / 直播间号重定向到可直接播放的媒体地址",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        # 不自动重定向尾部斜杠：Starlette 会用请求中的 Host 头拼接跳转地址，且跳转不经过限流。
        redirect_slashes=False,
        exception_handlers={
            BiliLinkError: _handle_bililink_error,
            HTTPException: _handle_http_exception,
            RequestValidationError: _handle_validation_error,
            Exception: _handle_unexpected_error,
        },
    )
    app.state.rate_limiter = RateLimiter(settings.rate_limit)
    app.include_router(health_router)
    app.include_router(media_router)
    return app


def _error_response(
    status_code: int, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(error=message).model_dump(), status_code=status_code, headers=headers
    )


async def _handle_bililink_error(request: Request, exc: BiliLinkError) -> JSONResponse:
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        cause = f"（原因：{exc.__cause__!r}）" if exc.__cause__ else ""
        logger.warning("%s %s 失败：%s%s", request.method, request.url.path, exc, cause)
    return _error_response(exc.status_code, str(exc), exc.headers)


async def _handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    message = _HTTP_ERROR_MESSAGES.get(exc.status_code, exc.detail)
    return _error_response(exc.status_code, message, exc.headers)


async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = "；".join(_describe_validation_error(error) for error in exc.errors())
    return _error_response(HTTPStatus.UNPROCESSABLE_ENTITY, f"请求参数无效：{details}")


def _describe_validation_error(error: Mapping[str, Any]) -> str:
    field = ".".join(str(part) for part in error["loc"][1:])
    template = _VALIDATION_MESSAGES.get(error["type"])
    reason = template.format(**error.get("ctx", {})) if template else error["msg"]
    return f"{field} {reason}"


async def _handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    # Starlette 调用本处理器后会继续抛出原异常，由 uvicorn 记录完整堆栈，这里不重复记录。
    return _error_response(HTTPStatus.INTERNAL_SERVER_ERROR, "服务器内部错误")
