"""HTTP 路由：只做参数校验、依赖注入与响应转换，不包含业务逻辑。"""

from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import RedirectResponse
from starlette.convertors import StringConvertor, register_url_convertor

from bililink.bilibili import BVID_PATTERN
from bililink.errors import ErrorResponse
from bililink.ratelimit import RateLimiter
from bililink.resolver import Resolver

_REDIRECT_STATUS = HTTPStatus.TEMPORARY_REDIRECT


class _BvidConvertor(StringConvertor):
    """只匹配合法 BV 号的路径转换器：其他路径不会命中视频路由，直接得到 404。"""

    regex = BVID_PATTERN


register_url_convertor("bvid", _BvidConvertor())


def _get_resolver(request: Request) -> Resolver:
    resolver: Resolver = request.app.state.resolver
    return resolver


async def _enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    await limiter.hit(request)


ResolverDep = Annotated[Resolver, Depends(_get_resolver)]

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in (
        (HTTPStatus.NOT_FOUND, "视频或分 P 不存在或无法观看；直播间不存在或未开播"),
        (HTTPStatus.UNPROCESSABLE_ENTITY, "请求参数无效"),
        (HTTPStatus.TOO_MANY_REQUESTS, "超出限流配额，Retry-After 响应头给出需要等待的秒数"),
        (HTTPStatus.BAD_GATEWAY, "B 站接口不可用或返回异常"),
    )
}

health_router = APIRouter(tags=["运维"])
media_router = APIRouter(
    tags=["媒体"], dependencies=[Depends(_enforce_rate_limit)], responses=_ERROR_RESPONSES
)


@health_router.get("/healthz", summary="健康检查")
async def healthz() -> dict[str, str]:
    """服务存活时返回 ``{"status": "ok"}``；不访问 B 站，也不计入限流。"""
    return {"status": "ok"}


@media_router.get(
    "/live/{room_id:int}",
    summary="重定向到直播流",
    status_code=_REDIRECT_STATUS,
    response_class=RedirectResponse,
)
async def redirect_to_live(
    room_id: Annotated[int, Path(ge=1, description="直播间号，支持短号")],
    resolver: ResolverDep,
) -> RedirectResponse:
    """重定向到直播间的 HLS（m3u8）地址。"""
    return RedirectResponse(await resolver.resolve_live(room_id), status_code=_REDIRECT_STATUS)


@media_router.get(
    "/{bvid:bvid}",
    summary="重定向到视频文件",
    status_code=_REDIRECT_STATUS,
    response_class=RedirectResponse,
)
async def redirect_to_video(
    bvid: Annotated[
        str,
        Path(pattern=f"^{BVID_PATTERN}$", description="视频 BV 号", examples=["BV1GJ411x7h7"]),
    ],
    resolver: ResolverDep,
    p: Annotated[int, Query(ge=1, description="分 P 序号，从 1 开始")] = 1,
) -> RedirectResponse:
    """重定向到视频指定分 P 的 MP4 直链。"""
    return RedirectResponse(await resolver.resolve_video(bvid, p), status_code=_REDIRECT_STATUS)
