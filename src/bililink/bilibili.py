"""B 站 Web API 客户端。

职责仅限于：发起 HTTP 请求、解析 ``{code, message, data}`` 响应信封、把各种失败映射为
:mod:`bililink.errors` 中的业务异常。选择分 P、挑选直播流等业务规则见 :mod:`bililink.resolver`。

接口说明参考 https://github.com/SocialSisterYi/bilibili-API-collect 。
"""

from collections.abc import Mapping
from types import TracebackType
from typing import Annotated, Self

import httpx2
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from bililink.errors import NotFoundError, UpstreamError

BVID_PATTERN = "BV[1-9A-HJ-NP-Za-km-z]{10}"
"""BV 号格式：``BV`` 加 10 位 base58 字符（不含 ``0``、``I``、``O``、``l``）。"""

_API_BASE = "https://api.bilibili.com"
_LIVE_API_BASE = "https://api.live.bilibili.com"

# 不带浏览器 User-Agent 的请求会被 B 站风控拦截（HTTP 412）；有 UA 时无需任何 Cookie。
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

# 表示“资源不存在或当前无法观看”的业务错误码映射为 404，其余非 0 错误码一律视为上游故障（502）。
_NOT_FOUND_CODES = frozenset(
    {
        -404,  # 啥都木有
        -403,  # 访问权限不足（如需要登录或大会员）
        -10403,  # 地区限制
        60004,  # 直播间不存在
        62002,  # 稿件不可见
        62004,  # 稿件审核中
        62012,  # 仅 UP 主自己可见
    }
)
# pagelist 唯一的参数是已通过格式校验的 BV 号，此时 -400 说明它不对应任何稿件（如 BV1zzzzzzzzz）。
_PAGELIST_NOT_FOUND_CODES = _NOT_FOUND_CODES | {-400}

type NonEmpty[T] = Annotated[tuple[T, ...], Field(min_length=1)]
type _QueryParams = Mapping[str, str | int]


class _Model(BaseModel):
    """响应模型基类：只声明用到的字段，上游新增字段会被忽略。"""

    model_config = ConfigDict(frozen=True)


class _Envelope(_Model):
    """B 站接口统一的响应信封；``data`` 在确认 ``code`` 成功后才按具体类型校验。"""

    code: int
    message: str = ""
    data: JsonValue = None


class VideoPage(_Model):
    """视频的一个分 P。"""

    cid: int
    page: int


class VideoSegment(_Model):
    """视频文件，对应响应中的 ``durl`` 条目。"""

    url: str


class VideoPlayInfo(_Model):
    """视频某一分 P 的播放信息。"""

    durl: NonEmpty[VideoSegment]


class LiveUrlInfo(_Model):
    """直播流的一个 CDN 节点。"""

    host: str
    extra: str


class LiveCodec(_Model):
    """直播流的一种编码。"""

    codec_name: str
    base_url: str
    url_info: NonEmpty[LiveUrlInfo]


class LiveFormat(_Model):
    """直播流的一种封装格式。"""

    codec: NonEmpty[LiveCodec]


class LiveStream(_Model):
    """直播流的一种传输协议。"""

    format: NonEmpty[LiveFormat]


class LivePlayUrl(_Model):
    """直播间当前可用的全部直播流。"""

    stream: NonEmpty[LiveStream]


class LivePlayUrlInfo(_Model):
    """直播间播放地址信息。"""

    playurl: LivePlayUrl


class LiveRoomPlayInfo(_Model):
    """直播间播放信息；未开播、轮播中或加密时 ``playurl_info`` 为 ``None``。"""

    playurl_info: LivePlayUrlInfo | None = None


_VIDEO_PAGES = TypeAdapter(tuple[VideoPage, ...])
_VIDEO_PLAY_INFO = TypeAdapter(VideoPlayInfo)
_LIVE_ROOM_PLAY_INFO = TypeAdapter(LiveRoomPlayInfo)


class BilibiliClient:
    """B 站 Web API 的异步客户端。

    内部复用同一个连接池，必须通过 ``async with`` 管理生命周期。
    ``transport`` 用于替换网络层（测试时注入 :class:`httpx2.MockTransport`）。
    """

    def __init__(
        self,
        *,
        sessdata: str | None,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx2.AsyncClient(
            headers=_DEFAULT_HEADERS,
            cookies={"SESSDATA": sessdata} if sessdata else None,
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        await self._http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.__aexit__(exc_type, exc, traceback)

    async def get_video_pages(self, bvid: str) -> tuple[VideoPage, ...]:
        """获取视频的分 P 列表。"""
        return await self._get(
            f"{_API_BASE}/x/player/pagelist",
            {"bvid": bvid},
            _VIDEO_PAGES,
            not_found_codes=_PAGELIST_NOT_FOUND_CODES,
        )

    async def get_video_play_info(self, bvid: str, cid: int) -> VideoPlayInfo:
        """获取视频某一分 P 的 MP4 播放信息。"""
        params: _QueryParams = {
            "bvid": bvid,
            "cid": cid,
            # html5 平台返回音视频合一的单文件 MP4，且 CDN 不校验 Referer，浏览器可直接播放。
            "platform": "html5",
            "otype": "json",
            "qn": 120,  # 请求 4K，实际画质取决于账号权限与稿件本身
            "fourk": 1,
            "fnval": 1 | 128,  # MP4 | 4K
            "high_quality": 1,
        }
        return await self._get(f"{_API_BASE}/x/player/playurl", params, _VIDEO_PLAY_INFO)

    async def get_live_room_play_info(self, room_id: int) -> LiveRoomPlayInfo:
        """获取直播间播放信息，``room_id`` 支持短号。"""
        params: _QueryParams = {
            "room_id": room_id,
            "platform": "h5",
            "protocol": "0,1",  # http_stream、http_hls
            "format": "1",  # ts，即返回 HLS（m3u8）
            "codec": "0,1",  # avc、hevc
        }
        return await self._get(
            f"{_LIVE_API_BASE}/xlive/web-room/v2/index/getRoomPlayInfo",
            params,
            _LIVE_ROOM_PLAY_INFO,
        )

    async def _get[T](
        self,
        url: str,
        params: _QueryParams,
        data_type: TypeAdapter[T],
        *,
        not_found_codes: frozenset[int] = _NOT_FOUND_CODES,
    ) -> T:
        """请求接口并返回校验后的 ``data``；任何失败都转换为业务异常。"""
        try:
            response = await self._http.get(url, params=params)
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            msg = f"B 站接口返回 HTTP {exc.response.status_code}"
            raise UpstreamError(msg) from exc
        except httpx2.HTTPError as exc:
            msg = f"无法连接 B 站接口（{type(exc).__name__}）"
            raise UpstreamError(msg) from exc

        try:
            envelope = _Envelope.model_validate_json(response.content)
        except ValidationError as exc:
            msg = "B 站接口返回了无法识别的数据"
            raise UpstreamError(msg) from exc

        if envelope.code in not_found_codes:
            msg = f"{envelope.message}（B 站错误码 {envelope.code}）"
            raise NotFoundError(msg)
        if envelope.code != 0:
            msg = f"B 站接口返回错误：{envelope.message}（错误码 {envelope.code}）"
            raise UpstreamError(msg)

        try:
            return data_type.validate_python(envelope.data)
        except ValidationError as exc:
            msg = "B 站接口返回的数据结构不符合预期"
            raise UpstreamError(msg) from exc
