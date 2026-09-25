"""根据 src/bililink/config.py 重新生成仓库根目录的 .env.example。"""

from pathlib import Path

from bililink.config import render_env_example

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def main() -> None:
    """写入 .env.example（UTF-8、LF 换行）。"""
    ENV_EXAMPLE.write_text(render_env_example(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
