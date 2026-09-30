# 更新日志

本项目的重要变更都记录在此文件中。
更新记录由 release-please 根据 Conventional Commits 自动生成，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [1.2.0](https://github.com/UzkiS/BiliLink/compare/v1.1.1...v1.2.0) (2026-09-30)


### 新增

* 网页增加支持项目入口 ([a64fd5f](https://github.com/UzkiS/BiliLink/commit/a64fd5f8bcd8eb847d0a49d2701a22f778381d81))
* 自动维护运行时中国大陆 IP 段 ([c400851](https://github.com/UzkiS/BiliLink/commit/c4008519af9137a2b2b18bfedb2c2816c281d29c))


### 修复

* 修复网页首页与结果页的窄屏横向溢出 ([cd43079](https://github.com/UzkiS/BiliLink/commit/cd43079ea61daeb4d2f743a40def2002dbb1beeb))

## [1.1.1] - 2026-09-27

### 变更

- B 站接口返回 HTTP 412（风控拦截）时，错误信息改为说明这通常是服务器的出口 IP 被 B 站限制、需要更换出口 IP，
  不再只转述一个看不出含义的状态码。
- `compose.yaml` 改用宿主机网络（`network_mode: host`）：不再创建单独的 Docker 网络，也不再做端口映射
  （端口映射会绕过 ufw 等防火墙的规则），服务直接监听宿主机端口，访问由系统防火墙与云服务器安全组控制；
  监听端口在 `compose.yaml` 中由 `BILILINK_PORT` 显式给出。改用新的 `compose.yaml` 时：
  - 修改过端口映射的，改为在 `.env` 中设置 `BILILINK_PORT`（不能使用 1024 以下的端口）；
  - 反向代理与服务在同一台机器上的，服务看到的代理地址由 Docker 网关变为 `127.0.0.1`，
    `BILILINK_FORWARDED_ALLOW_IPS` 需要相应修改。

## [1.1.0] - 2026-09-27

### 新增

- 网页界面（`/`）：粘贴 BV 号、视频网址、直播间号或直播间网址即可生成链接；自动列出全部分 P，
  可按标题、序号或范围筛选，逐条复制或一键复制，并可预览视频与直播。生成的链接以页面地址为前缀，
  部署在根域名、子域名或反向代理的子路径下都可以直接使用。默认开启，设置 `BILILINK_WEB_ENABLED=false` 可关闭。
- `GET /api/video/{BV号}`：返回视频标题、封面与分 P 列表，供网页界面使用，随网页界面一起开关。
- 按观看者所在地区选择视频 CDN 镜像：中国大陆以外的观看者改用海外镜像（新增配置 `BILILINK_CDN_OVERSEAS_HOSTS`），
  由镜像的 DNS 调度到观看者所在国家或地区的节点，不再跨境访问大陆节点。

### 变更

- `BILILINK_CDN_HOSTS` 只用于中国大陆的观看者（以及内网等无法判断地区的观看者），此前所有观看者都使用它。
  地区依据客户端 IP 判断，部署在反向代理之后时需要正确设置 `BILILINK_FORWARDED_ALLOW_IPS`。
- 视频不存在时，错误信息改为“视频 {BV号} 不存在”，不再直接转述 B 站难以理解的提示
  （如“请求错误（B 站错误码 -400）”“啥都木有（B 站错误码 -404）”）。

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

[1.1.1]: https://github.com/UzkiS/BiliLink/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/UzkiS/BiliLink/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/UzkiS/BiliLink/releases/tag/v1.0.0
