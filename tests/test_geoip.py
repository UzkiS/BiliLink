"""中国大陆 IP 段：数据文件的生成、读取与地址归属判断。"""

from ipaddress import ip_address, ip_network

import pytest

from bililink.geoip import MainlandChinaNetworks, load_mainland_china_networks, render_data_file
from fakes import APNIC_DELEGATED


def test_render_data_file_collapses_mainland_networks() -> None:
    lines = render_data_file(APNIC_DELEGATED).splitlines()
    comments = [line for line in lines if line.startswith("#")]
    networks = [line for line in lines if not line.startswith("#")]

    assert comments[-1] == (
        "# 数据来源：https://ftp.apnic.net/stats/apnic/delegated-apnic-latest（20260926 版）"
    )
    # 只保留 CN 的 IP 段：相邻的两个 /24 合并为 /23；768 个地址不是 2 的幂，拆为两个 CIDR。
    assert networks == ["1.0.1.0/24", "1.0.8.0/23", "1.1.0.0/23", "1.1.2.0/24", "240e::/20"]


@pytest.mark.parametrize(
    "delegated",
    [
        APNIC_DELEGATED.replace("apnic|*|ipv4|*|5|summary", "apnic|*|ipv4|*|6|summary"),
        APNIC_DELEGATED.removesuffix("apnic|HK|ipv6|2400:8500::|32|20130315|allocated\n"),
        APNIC_DELEGATED.replace("|8|19830613|", "|9|19830613|"),
    ],
)
def test_render_data_file_rejects_incomplete_data(delegated: str) -> None:
    with pytest.raises(ValueError, match="APNIC 数据不完整"):
        render_data_file(delegated)


@pytest.mark.parametrize(
    "delegated",
    [
        "",
        "# 只有注释\n",
        "<!DOCTYPE html>\n<html>\n",  # 下载到的是网页而不是数据文件
        APNIC_DELEGATED.replace("apnic|JP|ipv4|1.0.16.0|4096|20110412|allocated", "apnic|JP"),
    ],
)
def test_render_data_file_rejects_malformed_data(delegated: str) -> None:
    with pytest.raises(ValueError, match="APNIC 数据格式无效"):
        render_data_file(delegated)


def test_networks_contain_addresses_between_boundaries() -> None:
    networks = MainlandChinaNetworks(
        [ip_network("1.0.2.0/23"), ip_network("1.0.1.0/24"), ip_network("240e::/20")]
    )

    assert ip_address("1.0.1.0") in networks
    assert ip_address("1.0.3.255") in networks
    assert ip_address("1.0.0.255") not in networks
    assert ip_address("1.0.4.0") not in networks
    assert ip_address("240e:fff::1") in networks
    assert ip_address("240f::1") not in networks
    assert ip_address("::1") not in networks


def test_empty_networks_contain_nothing() -> None:
    networks = MainlandChinaNetworks([])

    assert ip_address("1.0.1.0") not in networks
    assert ip_address("240e::1") not in networks


@pytest.mark.parametrize(
    "address",
    [
        "114.114.114.114",  # 114DNS
        "223.5.5.5",  # 阿里 DNS
        "240e::1",  # 中国电信 IPv6
    ],
)
def test_packaged_data_contains_mainland_addresses(address: str) -> None:
    assert ip_address(address) in load_mainland_china_networks()


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",  # 美国
        "203.186.1.1",  # 香港
        "126.0.0.1",  # 日本
        "2001:4860:4860::8888",  # 美国 IPv6
    ],
)
def test_packaged_data_excludes_other_addresses(address: str) -> None:
    assert ip_address(address) not in load_mainland_china_networks()
