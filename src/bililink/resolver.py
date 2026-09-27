"""业务规则：把 BV 号 / 直播间号解析为可直接播放的媒体地址。"""

import random
from collections.abc import Sequence
from urllib.parse import urlsplit

from bililink.bilibili import BilibiliClient, LiveCodec, LivePlayUrl
from bililink.errors import NotFoundError, UpstreamError
from bililink.geoip import IPAddress, MainlandChinaNetworks

# 直播优先选择 AVC（H.264）：所有浏览器与播放器都能解码；没有 AVC 时才退回第一个可用编码。
_PREFERRED_LIVE_CODEC = "avc"


class Resolver:
    """媒体直链解析器，路由层唯一依赖的业务入口。"""

    def __init__(
        self,
        client: BilibiliClient,
        *,
        cdn_hosts: Sequence[str],
        cdn_overseas_hosts: Sequence[str],
        mainland_networks: MainlandChinaNetworks,
    ) -> None:
        self._client = client
        self._cdn_hosts = tuple(cdn_hosts)
        self._cdn_overseas_hosts = tuple(cdn_overseas_hosts)
        self._mainland_networks = mainland_networks

    async def resolve_video(self, bvid: str, page: int, client_ip: IPAddress | None) -> str:
        """返回视频第 ``page`` P（从 1 开始）的 MP4 直链，CDN 镜像按访问者所在地区选择。"""
        pages = await self._client.get_video_pages(bvid)
        cid = next((p.cid for p in pages if p.page == page), None)
        if cid is None:
            msg = f"视频 {bvid} 没有第 {page} P（共 {len(pages)} P）"
            raise NotFoundError(msg)
        play_info = await self._client.get_video_play_info(bvid, cid)
        return _ensure_http_url(self._rewrite_cdn_host(play_info.durl[0].url, client_ip))

    async def resolve_live(self, room_id: int) -> str:
        """返回直播间的 HLS（m3u8）直链。"""
        room = await self._client.get_live_room_play_info(room_id)
        if room.playurl_info is None:
            msg = f"直播间 {room_id} 当前未开播"
            raise NotFoundError(msg)
        codec = _pick_live_codec(room.playurl_info.playurl)
        url_info = codec.url_info[0]
        return _ensure_http_url(f"{url_info.host}{codec.base_url}{url_info.extra}")

    def _rewrite_cdn_host(self, url: str, client_ip: IPAddress | None) -> str:
        """把视频直链的域名随机替换为访问者所在地区的镜像域名。

        B 站按调用接口的 IP（即本服务）分配节点，返回的节点离访问者未必近，
        甚至可能是只在部分网络可达的 PCDN 或区域节点。镜像域名则由访问者自己解析，
        CDN 的调度会把访问者分配到就近节点：实测中国大陆的镜像在海外也只解析到大陆节点，
        海外镜像（``*ov``）才会解析到访问者所在国家的节点，因此按访问者是否位于中国大陆选择镜像组。
        镜像节点的路径与原节点一致，签名也不绑定域名，替换域名即可访问同一文件。
        """
        hosts = self._cdn_overseas_hosts if self._is_overseas(client_ip) else self._cdn_hosts
        if not hosts:
            return url
        host = random.choice(hosts)  # noqa: S311 - 仅用于分散负载，与安全无关
        return urlsplit(url)._replace(netloc=host).geturl()

    def _is_overseas(self, client_ip: IPAddress | None) -> bool:
        # 拿不到地址或不是公网地址时无法判断地区（如内网访问、经未配置 forwarded_allow_ips 的
        # 反向代理访问），按中国大陆处理，与按地区选择镜像之前的行为一致。
        return (
            client_ip is not None
            and client_ip.is_global
            and client_ip not in self._mainland_networks
        )


def _pick_live_codec(playurl: LivePlayUrl) -> LiveCodec:
    codecs = [codec for stream in playurl.stream for fmt in stream.format for codec in fmt.codec]
    return next((c for c in codecs if c.codec_name == _PREFERRED_LIVE_CODEC), codecs[0])


def _ensure_http_url(url: str) -> str:
    """确保重定向目标是绝对 http(s) 地址，避免把异常的上游数据透传给客户端。"""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        msg = "B 站返回了无效的播放地址"
        raise UpstreamError(msg)
    return url
