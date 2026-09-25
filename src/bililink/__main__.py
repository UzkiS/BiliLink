"""命令行入口：``bililink`` 或 ``python -m bililink``，按配置启动 uvicorn。"""

import copy
from pathlib import Path
from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from bililink.config import Settings


def build_log_config(level: str) -> dict[str, Any]:
    """在 uvicorn 默认日志配置上加入 ``bililink`` logger，使应用日志与服务器日志格式一致。"""
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"]["bililink"] = {"handlers": ["default"], "level": level, "propagate": False}
    return config


def main() -> None:
    """按 :class:`~bililink.config.Settings` 启动服务。"""
    settings = Settings()
    uvicorn.run(
        "bililink.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        # 只监视本包源码；默认会轮询整个工作目录（包括 .venv 中的上千个文件）。
        reload_dirs=[str(Path(__file__).parent)] if settings.reload else None,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        log_config=build_log_config(settings.log_level),
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
