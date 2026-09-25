# 更新日志

本项目的重要变更都记录在此文件中。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.0.0] - 2026-09-26

首个正式版本：对原有代码进行工程化重构。对外 URL（`/{BV号}`、`?p=`、`/live/{直播间号}`）与 307 重定向行为保持兼容。

### 新增

- Docker 镜像自动发布到 `ghcr.io/uzkis/bililink`（amd64 与 arm64），附带签名的构建来源证明；提供 `compose.yaml`。
- `GET /healthz` 健康检查接口，镜像内置健康检查。
- 可选的 OpenAPI 接口文档（`BILILINK_DOCS_ENABLED`）。
- 限流响应附带 `Retry-After` 响应头。

### 变更

- 配置改为 `BILILINK_` 前缀的环境变量或 `.env` 文件，不再读取 `data.json`。
  迁移方法：把原 `data.json` 中的 `SESSDATA` 写入 `.env` 的 `BILILINK_SESSDATA`。
- 未知的 `BILILINK_` 配置项（例如拼写错误）会让服务拒绝启动。
- 启动命令改为 `bililink`（或 `python -m bililink`），运行环境要求 Python 3.14（使用 uv 或 Docker 时自动满足）；
  依赖改由 `pyproject.toml` 与 `uv.lock` 管理，移除 `requirements.txt`。
- 错误统一返回中文说明的 `{"error": "..."}` JSON，状态码按语义区分：
  - 未知路径：403 → 404；
  - 直播间号不是数字（如 `/live/abc`）：422 → 404；
  - 视频或直播间不存在、直播间未开播：500 → 404；
  - 格式合法但不对应任何稿件的 BV 号、因地区限制等原因无法观看的视频：500 → 404；
  - 分 P 超出范围：原先静默回退到第 1 P → 404；
  - 参数无效（如 `p=0`、`p=abc`）：原先静默回退到第 1 P → 422；
  - B 站接口异常：500 → 502。
- 视频路径必须恰好是 BV 号（原先只要路径中包含 BV 号即可，如 `/xxBV1GJ411x7h7`）；
  带尾部斜杠的路径（如 `/BV1GJ411x7h7/`）不再被重定向，返回 404。
- 视频与直播共享同一份限流配额（原先各自计数），并改为滑动窗口算法（原为固定窗口），避免窗口边界处的突发流量翻倍。
- 直播流显式优先选择 H.264（AVC）编码，不再依赖接口返回的顺序。
- 配置了 SESSDATA 时，直播接口同样以登录身份请求（原先只有视频接口携带）。

### 修复

- B 站返回业务错误、非 JSON 响应（如风控拦截的 HTTP 412）或网络异常时，服务不再以 500 崩溃。

### 移除

- 不可达的 `/submit` 路由，以及未使用的搜索、登录状态检查与 WBI 签名代码。
- 不起作用的 `TrustedHostMiddleware`（`allowed_hosts=["*"]`）与 `GZipMiddleware`。

### 安全

- 默认只信任来自 `127.0.0.1` 的 `X-Forwarded-For`（原先信任任意来源，客户端可伪造 IP 绕过限流）。
  部署在反向代理之后时需要设置 `BILILINK_FORWARDED_ALLOW_IPS`。
- SESSDATA 不再存放在受版本控制的 `data.json` 中（原先填入 Cookie 后容易被误提交），并以 `SecretStr` 保存，
  不会出现在日志与异常信息中。
- 重定向前校验目标必须是绝对 http(s) 地址；不再根据请求的 Host 头为尾部斜杠生成跳转地址。
- Docker 镜像以非 root 用户运行。

### 性能

- 复用 HTTP 连接池；不再为每个请求抓取一次 B 站首页以获取 Cookie（实测接口不需要这些 Cookie）。

[Unreleased]: https://github.com/UzkiS/BiliLink/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/UzkiS/BiliLink/releases/tag/v1.0.0
