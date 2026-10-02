# syntax=docker/dockerfile:1

# ---- 构建阶段：按 .python-version 安装 Python，按 uv.lock 安装依赖 ----
FROM ghcr.io/astral-sh/uv:0.12.22-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

COPY .python-version ./
RUN uv python install

# 先只安装依赖，源码变更时可复用这一层缓存。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---- 运行阶段：只包含 Python 解释器与虚拟环境 ----
FROM debian:trixie-slim

# httpx2 通过 truststore 使用系统证书库校验 HTTPS，而 slim 镜像默认不含 CA 证书。
# CA 证书应始终保持最新，因此不固定版本。
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bililink \
    && useradd --no-log-init --no-create-home --shell /usr/sbin/nologin \
        --uid 10001 --gid 10001 bililink

COPY --from=builder /python /python
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# 所有配置通过 BILILINK_* 环境变量传入（见 .env.example）；
# 端口同样由 BILILINK_PORT 决定，因此这里不用 EXPOSE 重复声明默认值。
# 使用数字 UID，使 Kubernetes 的 runAsNonRoot 能够校验。
USER 10001:10001
WORKDIR /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-m", "bililink.healthcheck"]

CMD ["bililink"]
