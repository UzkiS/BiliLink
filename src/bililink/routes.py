"""HTTP 路由：只做参数校验、依赖注入与响应转换，不包含业务逻辑。"""

import base64
import hashlib
import re
from html import escape
from http import HTTPStatus
from importlib.metadata import metadata
from ipaddress import IPv6Address, ip_address
from os import stat_result
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.convertors import StringConvertor, register_url_convertor
from starlette.responses import Response
from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Scope

from bililink.bilibili import BVID_PATTERN
from bililink.errors import ErrorResponse
from bililink.geoip import IPAddress
from bililink.ratelimit import RateLimiter
from bililink.resolver import Resolver

_REDIRECT_STATUS = HTTPStatus.TEMPORARY_REDIRECT
_WEB_DIR = Path(__file__).with_name("web")


def _render_index_html() -> str:
    """网页界面的 HTML：填入仓库地址，取自包元数据（即 pyproject.toml 的 [project.urls]）。"""
    entries = metadata("bililink").get_all("Project-URL", [])
    repository = dict(entry.split(", ", 1) for entry in entries)["Repository"]
    html = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    return html.replace("{{ repository_url }}", escape(repository))


_INDEX_HTML = _render_index_html()
# 页面唯一的内联脚本必须在解析任何相对地址之前执行（见 index.html），CSP 按其内容哈希放行；
# 哈希在这里计算，修改脚本后无需手动同步。
[_INLINE_SCRIPT] = re.findall(r"<script>(.*?)</script>", _INDEX_HTML, flags=re.DOTALL)
_INLINE_SCRIPT_HASH = base64.b64encode(hashlib.sha256(_INLINE_SCRIPT.encode()).digest()).decode()

# 页面只加载本服务的脚本与样式；视频封面来自 B 站图床（*.hdslb.com），预览时要跨域读取
# B 站 CDN 上的视频与直播流，hls.js 经 blob: 地址播放。实测封面与 CDN 都不校验 Referer，
# 因此不必向 B 站透露本服务的地址。
# 内联脚本会在子路径部署时插入指向本服务的 <base>，因此 base-uri 允许同源地址。
_PAGE_HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; script-src 'self' 'sha256-{_INLINE_SCRIPT_HASH}'; "
        "style-src 'self'; img-src 'self' https://*.hdslb.com; connect-src 'self' https:; "
        "media-src 'self' https: blob:; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-cache",
}


class _BvidConvertor(StringConvertor):
    """只匹配合法 BV 号的路径转换器：其他路径不会命中视频路由，直接得到 404。"""

    regex = BVID_PATTERN


register_url_convertor("bvid", _BvidConvertor())


class _WebAssets(StaticFiles):
    """网页的脚本、样式等静态资源。"""

    def file_response(
        self,
        full_path: PathLike,
        stat_result: stat_result,
        scope: Scope,
        status_code: int = HTTPStatus.OK,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # 资源地址不带版本号：要求浏览器每次向服务器确认（未变化时只返回 304），
        # 升级后不会继续使用旧脚本。
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


web_assets = _WebAssets(directory=_WEB_DIR / "assets")
"""挂载到 ``/assets`` 的网页静态资源。"""


def _get_resolver(request: Request) -> Resolver:
    resolver: Resolver = request.app.state.resolver
    return resolver


def _get_client_ip(request: Request) -> IPAddress | None:
    """访问者的 IP 地址，即 uvicorn 按 ``forwarded_allow_ips`` 处理过代理头之后的结果。"""
    try:
        address = ip_address(request.client.host if request.client else "")
    except ValueError:  # 经 Unix socket 接入等拿不到 IP 地址的情况
        return None
    # 监听 IPv6 双栈地址时，IPv4 访问者的地址形如 ::ffff:1.2.3.4，还原为 IPv4 地址才能判断归属地。
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


async def _enforce_rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    await limiter.hit(request)


ResolverDep = Annotated[Resolver, Depends(_get_resolver)]
ClientIPDep = Annotated[IPAddress | None, Depends(_get_client_ip)]
BvidPath = Annotated[
    str,
    PathParam(pattern=f"^{BVID_PATTERN}$", description="视频 BV 号", examples=["BV1GJ411x7h7"]),
]


def _error_responses(*errors: tuple[HTTPStatus, str]) -> dict[int | str, dict[str, Any]]:
    return {
        status: {"model": ErrorResponse, "description": description}
        for status, description in errors
    }


_INVALID_REQUEST = (HTTPStatus.UNPROCESSABLE_ENTITY, "请求参数无效")
_RATE_LIMITED = (HTTPStatus.TOO_MANY_REQUESTS, "超出限流配额，Retry-After 响应头给出需要等待的秒数")
_UPSTREAM_FAILED = (HTTPStatus.BAD_GATEWAY, "B 站接口不可用或返回异常")

health_router = APIRouter(tags=["运维"])
media_router = APIRouter(
    tags=["媒体"],
    dependencies=[Depends(_enforce_rate_limit)],
    responses=_error_responses(
        (HTTPStatus.NOT_FOUND, "视频或分 P 不存在或无法观看；直播间不存在或未开播"),
        _INVALID_REQUEST,
        _RATE_LIMITED,
        _UPSTREAM_FAILED,
    ),
)
# 网页界面与它使用的接口：随 web_enabled 一起开关。
web_router = APIRouter(include_in_schema=False)
api_router = APIRouter(
    prefix="/api",
    tags=["网页"],
    dependencies=[Depends(_enforce_rate_limit)],
    responses=_error_responses(
        (HTTPStatus.NOT_FOUND, "视频不存在或无法观看"),
        _INVALID_REQUEST,
        _RATE_LIMITED,
        _UPSTREAM_FAILED,
    ),
)


class PageInfo(BaseModel):
    """视频的一个分 P。"""

    page: int = Field(description="分 P 序号，从 1 开始，即视频链接中的 p 参数")
    title: str = Field(description="分 P 标题")
    duration: int = Field(description="时长（秒）")


class VideoInfoResponse(BaseModel):
    """视频的标题、封面与分 P 列表。"""

    title: str = Field(description="视频标题")
    cover: str = Field(description="封面图片地址（https）")
    pages: list[PageInfo] = Field(description="全部分 P")


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
    room_id: Annotated[int, PathParam(ge=1, description="直播间号，支持短号")],
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
    bvid: BvidPath,
    resolver: ResolverDep,
    client_ip: ClientIPDep,
    p: Annotated[int, Query(ge=1, description="分 P 序号，从 1 开始")] = 1,
) -> RedirectResponse:
    """重定向到视频指定分 P 的 MP4 直链；CDN 镜像按访问者所在地区选择。"""
    url = await resolver.resolve_video(bvid, p, client_ip)
    return RedirectResponse(url, status_code=_REDIRECT_STATUS)


@web_router.get("/")
async def index() -> HTMLResponse:
    """网页界面。"""
    return HTMLResponse(_INDEX_HTML, headers=_PAGE_HEADERS)


@api_router.get("/video/{bvid:bvid}", summary="查询视频的标题、封面与分 P 列表")
async def get_video_info(bvid: BvidPath, resolver: ResolverDep) -> VideoInfoResponse:
    """返回视频标题、封面与全部分 P，供网页界面列出每个分 P 的链接。"""
    info = await resolver.get_video_info(bvid)
    return VideoInfoResponse(
        title=info.title,
        cover=info.pic,
        pages=[PageInfo(page=p.page, title=p.part, duration=p.duration) for p in info.pages],
    )
