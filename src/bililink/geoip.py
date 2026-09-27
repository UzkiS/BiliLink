"""判断 IP 地址是否位于中国大陆，供按访问者所在地区选择 CDN 镜像使用。

数据来自 APNIC 的地址分配记录：APNIC 按国家或地区登记地址段，其中 ``CN`` 只包含中国大陆，
香港、澳门、台湾另有代码。登记地与实际使用地偶有出入，但对家庭宽带、移动网络等访问者足够准确。
随包发布的数据文件由 ``uv run poe update-geoip`` 生成，不要手动编辑。
"""

import bisect
import functools
from collections import Counter
from collections.abc import Iterable
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    collapse_addresses,
    ip_network,
    summarize_address_range,
)
from pathlib import Path

type IPAddress = IPv4Address | IPv6Address
type IPNetwork = IPv4Network | IPv6Network

APNIC_DELEGATED_URL = "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"
"""APNIC 地址分配记录。

格式见 https://www.apnic.net/about-apnic/corporate-documents/documents/resource-guidelines/rir-statistics-exchange-format/
"""

DATA_FILE = Path(__file__).with_name("cn_networks.txt")
"""中国大陆的 IP 段，每行一个 CIDR，``#`` 开头的行是注释。"""


class MainlandChinaNetworks:
    """中国大陆的全部 IP 段，用 ``address in networks`` 判断地址是否属于中国大陆。"""

    def __init__(self, networks: Iterable[IPNetwork]) -> None:
        networks = tuple(networks)
        self._ipv4 = _AddressRanges(
            collapse_addresses(n for n in networks if isinstance(n, IPv4Network))
        )
        self._ipv6 = _AddressRanges(
            collapse_addresses(n for n in networks if isinstance(n, IPv6Network))
        )

    def __contains__(self, address: IPAddress) -> bool:
        ranges = self._ipv4 if isinstance(address, IPv4Address) else self._ipv6
        return int(address) in ranges


class _AddressRanges:
    """同一地址族中互不重叠、按起始地址排序的网段，用二分查找判断地址归属。"""

    def __init__(self, networks: Iterable[IPNetwork]) -> None:
        networks = tuple(networks)
        self._starts = [int(network.network_address) for network in networks]
        self._ends = [int(network.broadcast_address) for network in networks]

    def __contains__(self, address: int) -> bool:
        index = bisect.bisect_right(self._starts, address) - 1
        return index >= 0 and address <= self._ends[index]


@functools.cache
def load_mainland_china_networks() -> MainlandChinaNetworks:
    """读取随包发布的数据文件；数据在运行期间不会变化，每个进程只读取一次。"""
    lines = DATA_FILE.read_text(encoding="utf-8").splitlines()
    return MainlandChinaNetworks(ip_network(line) for line in lines if not line.startswith("#"))


def render_data_file(delegated: str) -> str:
    """把 APNIC 地址分配记录转换为数据文件的内容：中国大陆的全部 IP 段，合并相邻网段后每行一个。"""
    header, *rows = [
        line.split("|") for line in delegated.splitlines() if line and not line.startswith("#")
    ]
    summary = {row[2]: int(row[4]) for row in rows if row[-1] == "summary"}
    records = [row for row in rows if row[-1] != "summary"]
    # 文件头与汇总行给出了各类记录的数量，据此发现下载中断等原因造成的数据不完整。
    counted = Counter(record[2] for record in records)
    if counted != summary or len(records) != int(header[3]):
        msg = f"APNIC 数据不完整：汇总行记录数 {summary}，实际读到 {dict(counted)}"
        raise ValueError(msg)

    ipv4: list[IPv4Network] = []
    ipv6: list[IPv6Network] = []
    for _registry, country, kind, start, value, *_ in records:
        if country != "CN":
            continue
        if kind == "ipv4":
            # IPv4 记录给出的是地址数量，不一定是 2 的幂，需要拆分为若干 CIDR。
            first = IPv4Address(start)
            ipv4 += summarize_address_range(first, first + int(value) - 1)
        elif kind == "ipv6":
            ipv6.append(IPv6Network(f"{start}/{value}"))  # IPv6 记录给出的是前缀长度

    lines = [
        "# 中国大陆（APNIC 国家代码 CN）的 IP 段。",
        "# 由 `uv run poe update-geoip` 生成，请勿手动编辑。",
        f"# 数据来源：{APNIC_DELEGATED_URL}（{header[2]} 版）",
        *map(str, collapse_addresses(ipv4)),
        *map(str, collapse_addresses(ipv6)),
    ]
    return "\n".join(lines) + "\n"
