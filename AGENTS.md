# AGENTS.md

本文件是 BiliLink **工程规范的唯一来源**，面向 AI 编码助手与人类贡献者。
`CLAUDE.md` 只引用本文件；其他文档与本文件冲突时，以本文件为准。

## 项目概览

BiliLink 是一个 FastAPI 服务：把 B 站视频 BV 号或直播间号解析为可直接播放的媒体地址，并以 307 重定向返回。
对外接口（URL 形式、状态码、`{"error": "..."}` 错误格式）是公开契约，破坏性变更必须升级主版本号。

## 常用命令

命令只在 `pyproject.toml` 的 `[tool.poe.tasks]` 中定义，CI 执行的是同一套命令。

| 命令 | 用途 |
| --- | --- |
| `uv sync` | 安装依赖与开发工具（首次还会自动安装所需的 Python） |
| `uv run pre-commit install` | 安装 Git 提交钩子（克隆后执行一次） |
| `uv run poe check` | **提交前必须通过**：lint + test，与 CI 的检查任务相同 |
| `uv run poe lint` | ruff、mypy、deptry、hadolint、actionlint、zizmor 与通用文件检查，会自动修复可修复项 |
| `uv run poe test` | 运行离线测试，行与分支覆盖率必须 100% |
| `uv run poe test-live` | 运行真实 B 站接口测试，检查上游接口是否变更 |
| `uv run poe dev` | 本地开发：仅本机可访问，自动重载并开放 `/docs` |
| `uv run poe env-example` | 修改配置项后重新生成 `.env.example` |
| `uv run poe update-geoip` | 从 APNIC 下载最新数据，重新生成中国大陆 IP 段 |
| `uv run pytest tests/test_api.py -k video` | 只运行部分测试（不统计覆盖率） |

## 目录结构与分层

```text
src/bililink/
├── __main__.py        命令行入口：按配置启动 uvicorn
├── app.py             应用组装：生命周期、路由注册、统一异常处理
├── routes.py          HTTP 层：参数校验、依赖注入、响应转换
├── resolver.py        业务层：选择分 P、按访问者地区改写 CDN、选择直播编码
├── bilibili.py        B 站接口客户端：请求、响应解析、错误码映射
├── geoip.py           判断 IP 是否属于中国大陆；cn_networks.txt 是它的数据（生成）
├── ratelimit.py       按客户端 IP 限流
├── errors.py          业务异常与错误响应格式
├── config.py          运行时配置
└── healthcheck.py     容器健康检查命令
tests/
├── fakes.py           B 站接口替身（httpx2.MockTransport）
├── fixtures/          录制自真实接口的响应（已裁剪、脱敏）
├── test_live.py       真实 B 站接口测试（标记为 live，默认不运行）
├── test_consistency.py  唯一事实源守护测试
└── test_*.py
scripts/               开发脚本（不随包发布）
.github/workflows/     ci.yml：检查、镜像冒烟测试与发布；live.yml：每日真实接口巡检
Dockerfile、compose.yaml  镜像构建与部署
```

依赖方向只能是 `routes → resolver → bilibili`：

- 只有 `bilibili.py` 访问 B 站；它只处理协议，不包含业务规则。
- `geoip.py` 只回答“某个 IP 是否属于中国大陆”，按地区选择镜像的规则在 `resolver.py`。
- `resolver.py` 不感知 Web 框架；`routes.py` 不包含业务逻辑。
- 业务错误一律抛出 `errors.py` 中的异常，由 `app.py` 统一转换为错误响应；不要在路由中手写错误响应。
- 配置只由 `app.py`、`__main__.py` 与 `healthcheck.py` 从 `Settings` 读取，再通过构造参数传给下层模块；
  下层模块不直接依赖 `Settings`。

## 唯一事实源

每个事实只在一处定义，其余位置引用它或由工具生成。修改时只改定义位置，再同步派生物；
不要在文档、Dockerfile、CI 中复制默认值、版本号或命令。无法避免引用的地方（如 README 中的示例端口），
由 `tests/test_consistency.py` 保证与定义一致。

| 事实 | 定义位置 | 派生物 / 引用方 |
| --- | --- | --- |
| 项目版本 | `pyproject.toml` 的 `[project].version` | `bililink.__version__`、OpenAPI、镜像标签（发布时校验 `vX.Y.Z` 与之一致） |
| 依赖与开发工具版本 | `pyproject.toml` + `uv.lock` | Docker 镜像、pre-commit 的 local hooks、CI |
| Python 版本 | `.python-version`（开发、CI 与镜像使用的版本）；`requires-python`（最低版本） | CI、Docker 镜像 |
| uv 版本 | `[tool.uv].required-version`（版本范围） | CI（setup-uv）；Dockerfile 固定的版本（测试保证在范围内） |
| 配置项、默认值与说明 | `src/bililink/config.py` | `.env.example`（生成）；README、`compose.yaml` 中的端口（测试保证一致） |
| 开发命令 | `[tool.poe.tasks]` | CI、本文件 |
| 工具规则（ruff、mypy、pytest、coverage、deptry） | `pyproject.toml` | pre-commit、CI、编辑器 |
| BV 号格式 | `bilibili.BVID_PATTERN` | 路由匹配、OpenAPI |
| 中国大陆 IP 段 | APNIC 地址分配记录 | `src/bililink/cn_networks.txt`（由 `uv run poe update-geoip` 生成） |
| 错误响应格式与状态码 | `errors.ErrorResponse`、`routes.py` 中声明的错误响应 | 异常处理器、OpenAPI、README 错误码表（测试保证一致） |
| HTTP 接口契约 | `routes.py`（OpenAPI 由代码生成） | README 中的用法示例 |
| 镜像地址 | `[project.urls].Repository`（CI 按仓库名发布） | README、`compose.yaml`（测试保证一致） |
| B 站接口的非显然行为 | `bilibili.py` 中对应代码旁的注释 | — |
| 工程规范 | 本文件 | `CLAUDE.md` |

## 编码规范

- Python 3.14，所有代码带完整类型注解；`mypy --strict` 与 ruff（`select = ["ALL"]`）必须零报错。
  确需豁免时使用带规则码与理由的 `# noqa: XXX - 理由`，不要为了通过检查而放宽全局规则。
- 注释、docstring 与用户可见文本（错误信息、日志）使用简体中文；标识符使用英文。
- 注释解释“为什么”，尤其是 B 站接口的非显然行为；不要复述代码。注释必须与实测行为一致。
- 不提交注释掉的代码、`print`、未使用的代码与依赖。
- HTTP 客户端统一使用 httpx2（httpx 已基本停止维护，Starlette 也已转向 httpx2），不要引入 httpx、requests、aiohttp。
- 全链路异步；访问 B 站必须复用 `BilibiliClient` 内的连接池，禁止按请求新建 HTTP 客户端。
- 外部数据用 pydantic 模型在边界处解析，只声明用到的字段，并用类型表达约束（如 `NonEmpty`）；
  业务代码不再做防御性判空。
- 日志使用 `logging.getLogger(__name__)`；禁止记录 `SESSDATA` 等机密。
- 依赖通过 `uv add` / `uv remove` 管理，不要手动编辑 `uv.lock`；直接 import 的包必须显式声明（deptry 检查）。

## 测试规范

测试分两类，各司其职：

- **离线测试**（`uv run poe test`，PR 门禁）不访问网络：B 站接口统一使用 `tests/fakes.py` 中的 `FakeBilibili`。
  这保证结果确定，并能覆盖真实接口无法按需触发的异常（风控 412、超时、非 JSON 响应、B 站宕机等）。
- **真实接口测试**（`tests/test_live.py`，标记为 `live`）直接访问 B 站，用于发现上游接口变更；
  由 `uv run poe test-live` 运行，CI 每天定时运行一次，失败时 GitHub 会发邮件通知。
  只断言稳定的事实，不依赖直播间此刻是否开播、某条视频此刻的画质等易变状态。

其他要求：

- 新增或修改的行为必须有离线测试；覆盖率要求行与分支 100%。修改了 B 站相关逻辑时同时运行 `uv run poe test-live`。
- 通过公开接口验证行为（HTTP 契约、`Resolver`、`BilibiliClient`、`RateLimiter`），不直接测试私有函数。
- `tests/fixtures/` 中的夹具录制自真实接口，只保留用得到的字段，并把 URL 查询串等含 IP、签名的部分替换为占位值。
  真实接口测试发现上游变更时，重新录制受影响的夹具。
- 所有警告都视为错误（`filterwarnings = ["error"]`），出现警告时修复根因，而不是忽略。

## 安全

- `SESSDATA` 只能通过环境变量或 `.env` 提供，以 `SecretStr` 保存；`.env` 不入库。
- `BILILINK_FORWARDED_ALLOW_IPS` 只能填写真实反向代理的地址，否则客户端可以伪造 IP 绕过限流。
- 重定向目标只能来自 B 站接口的返回值，并且必须通过绝对 http(s) 地址校验；不开启尾部斜杠自动重定向。
- Docker 镜像以非 root 的数字 UID 运行；`.dockerignore` 是白名单，新增构建所需文件时显式加入。
- GitHub Actions 以完整 commit SHA 固定版本；会发布镜像的 `ci.yml` 不使用任何缓存，防止缓存投毒。

## 提交与发布

- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：
  `feat`、`fix`、`perf`、`refactor`、`test`、`docs`、`build`、`ci`、`chore`；描述使用中文，一个提交只做一件事。
- 用户可见的变更（接口行为、配置项、部署方式）写入 `CHANGELOG.md` 的 `[Unreleased]`。
- 镜像由 CI 自动发布到 `ghcr.io`（amd64 与 arm64），附带签名的构建来源证明：
  推送到 main 发布 `main` 标签；推送 `vX.Y.Z` 标签发布 `X.Y.Z`、`X.Y`、`X` 与 `latest`。检查未通过时不会发布。
- 发布新版本：
  1. 修改 `pyproject.toml` 中的 `version`，运行 `uv lock`；运行 `uv run poe update-geoip` 更新中国大陆 IP 段；
  2. 把 `CHANGELOG.md` 的 `[Unreleased]` 整理为新版本并提交；
  3. `git tag vX.Y.Z && git push origin main vX.Y.Z`（CI 会校验标签与 `version` 一致）。
- 首次发布后，GHCR 上的镜像默认为私有：需要在 GitHub 的 Packages 页面把它的可见性改为 Public（一次性操作，不可撤销）。

## 完成标准

提交前逐项确认：

1. `uv run poe check` 通过。
2. 新行为有测试，覆盖率保持 100%；修改了 B 站相关逻辑时，`uv run poe test-live` 也通过。
3. 修改了配置项：已运行 `uv run poe env-example`。
4. 修改了依赖：通过 `uv add` / `uv remove` 完成，`uv.lock` 已一并提交。
5. 用户可见的变化：已更新 `README.md` 与 `CHANGELOG.md`。
