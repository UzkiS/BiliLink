"""容器健康检查：``python -m bililink.healthcheck``，服务健康时退出码为 0，否则为 1。"""

import contextlib
import ipaddress

import httpx2

from bililink.config import Settings


def main() -> int:
    """请求服务的 ``/healthz``，地址与端口取自服务使用的同一份配置。"""
    settings = Settings()
    url = httpx2.URL(
        scheme="http", host=_reachable_host(settings.host), port=settings.port, path="/healthz"
    )
    try:
        httpx2.get(url, timeout=3, trust_env=False).raise_for_status()
    except httpx2.HTTPError:
        return 1
    return 0


def _reachable_host(host: str) -> str:
    """监听所有网卡（``0.0.0.0`` 或 ``::``）时改用对应的回环地址，否则直接使用监听地址。"""
    with contextlib.suppress(ValueError):  # 不是 IP 地址，而是主机名
        address = ipaddress.ip_address(host)
        if address.is_unspecified:
            return "::1" if isinstance(address, ipaddress.IPv6Address) else "127.0.0.1"
    return host


if __name__ == "__main__":
    raise SystemExit(main())
