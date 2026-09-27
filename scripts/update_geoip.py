"""从 APNIC 下载最新的地址分配记录，重新生成 src/bililink/cn_networks.txt。"""

import httpx2

from bililink.geoip import APNIC_DELEGATED_URL, DATA_FILE, render_data_file


def main() -> None:
    """下载地址分配记录并写入数据文件（UTF-8、LF 换行）。"""
    response = httpx2.get(APNIC_DELEGATED_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    DATA_FILE.write_text(render_data_file(response.text), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
