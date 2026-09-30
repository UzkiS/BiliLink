# BiliLink · B 站视频与直播直链解析

[![CI](https://github.com/UzkiS/BiliLink/actions/workflows/ci.yml/badge.svg)](https://github.com/UzkiS/BiliLink/actions/workflows/ci.yml)
[![最新版本](https://img.shields.io/github/v/release/UzkiS/BiliLink?label=%E7%89%88%E6%9C%AC&color=fb7299)](https://github.com/UzkiS/BiliLink/releases/latest)
[![许可证](https://img.shields.io/github/license/UzkiS/BiliLink?label=%E8%AE%B8%E5%8F%AF%E8%AF%81&color=5c6bc0)](LICENSE)
[![Docker 支持 amd64 与 arm64](https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ed?logo=docker&logoColor=white)](#部署)
[![VRChat 视频与直播](https://img.shields.io/badge/VRChat-%E8%A7%86%E9%A2%91%20%2F%20%E7%9B%B4%E6%92%AD-fb7299)](#在-vrchat-中播放-b-站视频与直播)

BiliLink 是可自行部署的 Bilibili（哔哩哔哩／B 站）视频与直播直链解析服务，基于 FastAPI，支持 Docker 部署。
把视频 BV 号转为 MP4 直链，把直播间号转为 HLS（m3u8）播放地址，支持视频分 P、网页预览与按地区选择 CDN 节点。

访问 `http://你的域名/BV1GJ411x7h7`，
即被重定向到该视频的 MP4 直链，可直接用于 `<video>` 标签、播放器等任何需要“一个直链”的场景。

[部署](#部署) · [使用](#使用) · [配置](#配置) · [常见问题](#常见问题) · [支持项目](#支持项目)

## 功能

- **视频**：`/{BV号}` 重定向到音视频合一的 MP4 直链，`?p=` 指定分 P；
  直链域名按访问者所在地区改写为 CDN 镜像节点（见 [CDN 节点](#cdn-节点)）。
- **直播**：`/live/{直播间号}` 重定向到 HLS（m3u8）直播流，支持短号，优先选择 H.264 编码。
- **网页界面**：粘贴 BV 号、视频网址、直播间号或直播间网址即可生成链接；自动列出全部分 P，
  可逐条复制或一键复制全部，也可以直接预览视频与直播。
- **限流**：按客户端 IP 限流（规则可配置），可正确识别反向代理之后的真实 IP。
- **运维**：统一的 JSON 错误响应、`/healthz` 健康检查、可选的 OpenAPI 文档。

## 网页预览

粘贴视频网址后，页面会列出全部分 P，可预览视频、筛选选集，并逐条或一键复制播放链接。

![BiliLink 网页界面：视频预览、分 P 选集、筛选与链接复制](./docs/screenshots/web-preview.png)

## 部署

镜像发布在 GitHub Container Registry，支持 x86_64（amd64）与 ARM64。

部署前，先在服务器上确认它能正常访问 B 站接口：

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" -e "https://www.bilibili.com/" \
  "https://api.bilibili.com/x/web-interface/view?bvid=BV1GJ411x7h7"
```

输出 `200` 即可部署；输出 `412` 说明这台服务器的出口 IP 已被 B 站风控，部署后也无法解析视频，
需要更换服务器或网络（见[常见问题](#常见问题)）。

### Docker Compose（推荐）

```bash
mkdir bililink && cd bililink
curl -fsSLO https://raw.githubusercontent.com/UzkiS/BiliLink/main/compose.yaml
docker compose up -d
```

`compose.yaml` 使用宿主机网络（`network_mode: host`）：服务直接监听宿主机端口，不经过 Docker 的端口映射
（端口映射会绕过 ufw 等防火墙的规则），访问由系统防火墙与云服务器安全组控制。
监听端口由 `compose.yaml` 中的 `BILILINK_PORT` 给出，更换端口时在 `.env` 中设置 `BILILINK_PORT` 即可；
容器以非 root 用户运行，不能使用 1024 以下的端口。

更新到最新版本：

```bash
docker compose pull && docker compose up -d
```

### Docker

```bash
docker run -d --name bililink --restart unless-stopped -p 5000:5000 ghcr.io/uzkis/bililink:latest
```

需要自定义配置时，把配置写入 `.env`（见[配置](#配置)），再加上 `--env-file .env` 参数。

### 镜像标签

| 标签                | 说明                                  |
| ------------------- | ------------------------------------- |
| `latest`            | 最新正式版本                          |
| `1.0.0`、`1.0`、`1` | 指定版本；`1` 始终指向 1.x 的最新版本 |
| `main`              | main 分支的最新构建，可能不稳定       |

### 从源码运行

需要安装 [uv](https://docs.astral.sh/uv/)，它会自动下载项目所需的 Python 版本并安装依赖：

```bash
uv run --no-dev bililink
```

## 使用

| 请求                          | 结果                                                   |
| ----------------------------- | ------------------------------------------------------ |
| `GET /BV1GJ411x7h7`           | 307 → 第 1 P 的 MP4 直链                               |
| `GET /BV1ex411J7GE?p=3`       | 307 → 第 3 P 的 MP4 直链                               |
| `GET /live/6`                 | 307 → 直播间 6 的 m3u8 地址                            |
| `GET /`                       | 网页界面                                               |
| `GET /api/video/BV1ex411J7GE` | 200，视频标题、封面与分 P 列表（JSON），供网页界面使用 |
| `GET /healthz`                | 200 `{"status": "ok"}`                                 |

网页界面生成的都是指向本服务的链接：每次播放时重新解析，因此可以长期使用、分享给他人。
只需要重定向服务时，可以设置 `BILILINK_WEB_ENABLED=false` 关闭网页界面及其使用的 `/api` 接口。

```bash
curl -i http://127.0.0.1:5000/BV1GJ411x7h7
```

出错时统一返回 JSON `{"error": "错误说明"}`：

| 状态码 | 含义                                                                        |
| ------ | --------------------------------------------------------------------------- |
| 404    | 路径不存在；视频或分 P 不存在或无法观看（如地区限制）；直播间不存在或未开播 |
| 422    | 参数无效，如 `p=0`                                                          |
| 429    | 超出限流配额，`Retry-After` 响应头给出需要等待的秒数                        |
| 502    | B 站接口不可用或返回异常                                                    |

开启 `BILILINK_DOCS_ENABLED` 后，可在 `/docs` 查看由代码生成的完整接口文档。

### 在 VRChat 中播放 B 站视频与直播

BiliLink 可用于 VRChat 世界中的视频播放器。通过 Nginx、Caddy 等反向代理为服务配置 HTTPS 域名后，
把网页生成的链接粘贴到播放器的 URL 输入框即可：视频使用 `https://你的域名/BV1GJ411x7h7`，
直播使用 `https://你的域名/live/6`，分 P 使用 `?p=` 指定。

使用 HTTPS 链接；自建域名需要观看者在 VRChat 设置中开启 **Allow Untrusted URLs**。
相关要求见 [VRChat 播放器文档](https://creators.vrchat.com/worlds/udon/video-players/)
与[域名允许列表](https://creators.vrchat.com/worlds/udon/video-players/www-whitelist)。

## 配置

配置通过 `BILILINK_` 前缀的环境变量，或工作目录下的 `.env` 文件提供。
全部配置项、默认值与说明见 [`.env.example`](.env.example)，该文件由代码生成，始终与实现一致：

```bash
curl -fsSL https://raw.githubusercontent.com/UzkiS/BiliLink/main/.env.example -o .env
```

未知的 `BILILINK_` 配置项（例如拼写错误）会让服务拒绝启动，而不是被静默忽略。

### 部署在反向代理之后

限流与 [CDN 节点](#cdn-节点)的地区判断依据的都是客户端 IP。部署在 Nginx、Caddy 等反向代理之后时，
必须把 `BILILINK_FORWARDED_ALLOW_IPS` 设置为反向代理的地址：

- 没有包含代理的地址时，所有请求都被视为来自代理，共享同一份限流配额，并且都按中国大陆访问者选择 CDN 节点；
- 设置为 `*` 时，任何客户端都能伪造 `X-Forwarded-For` 绕过限流（仅当服务只能经由代理访问时才可以这样设置）。

注意这里填的是**服务看到的**代理地址。代理与服务在同一台机器上时，用 Compose 部署（宿主机网络）
看到的是 `127.0.0.1`；用 `docker run -p` 部署时，来源通常是 Docker 网桥网关（默认 `172.17.0.1`）。
不确定时，查看服务日志中请求的来源地址即可。

网页界面生成的链接以页面自身的地址为前缀，因此服务可以部署在根域名、子域名或子路径下，无需额外配置。
部署在子路径（如 `https://a.com/bili/`）下时，反向代理需要去掉路径前缀后再转发：

```nginx
location /bili/ {
    proxy_pass http://127.0.0.1:5000/;  # 末尾的 / 表示去掉 /bili 前缀
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

```caddyfile
redir /bili /bili/
handle_path /bili/* {
    reverse_proxy 127.0.0.1:5000
}
```

在 Kubernetes 中部署时，如果 Service 名为 `bililink`，Kubernetes 自动注入的 `BILILINK_PORT` 等环境变量会与配置冲突，
请在 Pod 中设置 `enableServiceLinks: false`。

### CDN 节点

B 站按调用接口的 IP（也就是本服务所在的服务器）分配视频节点，这个节点对观看者未必合适。
因此本服务会把视频直链的域名改写为 CDN 镜像域名：镜像域名由观看者的设备自己解析，
CDN 会把观看者调度到就近的节点。按观看者 IP 判断地区后：

- 中国大陆的观看者使用 `BILILINK_CDN_HOSTS` 中的镜像；
- 其他地区的观看者使用 `BILILINK_CDN_OVERSEAS_HOSTS` 中的海外镜像。实测中国大陆的镜像在海外只会解析到大陆节点，
  跨境访问慢且不稳定；海外镜像则会解析到观看者所在国家或地区的节点；
- 内网地址等无法判断地区的观看者按中国大陆处理。

同一条链接被多人播放时，每个人都会得到适合自己所在地区的节点。
地区依据中国大陆 IP 段（来自 APNIC）在内存中判断，每次播放无需查询外部服务。
启动时先使用内置数据，在后台下载最新 APNIC 数据，之后按 `BILILINK_GEOIP_UPDATE_INTERVAL` 定期自动更新；
更新通过完整性与地址段校验后立即生效，无需重启容器。下载超时、数据异常时保留已有数据，下一轮继续重试。

默认只更新内存，兼容 `compose.yaml` 的只读文件系统，不需要修改部署配置。
希望重启后保留更新结果时，设置 `BILILINK_GEOIP_CACHE_FILE`，并为该文件所在目录挂载可写卷；
启动时优先读取有效缓存，缓存不可用时使用内置数据。缓存写入失败不影响本次内存更新。
设 `BILILINK_GEOIP_UPDATE_INTERVAL=0` 可关闭后台网络更新。更新间隔与下载超时的默认值见 [`.env.example`](.env.example)。

两项配置的默认值见 [`.env.example`](.env.example)。不需要按地区区分时，把两项设为相同的列表；
设为 `[]` 则保留 B 站返回的原始域名。

直播流的地址与分配到的节点绑定，无法改写，因此直播节点始终由 B 站按服务器所在地区分配。

### 画质

默认以游客身份请求，可获取的画质较低。设置 `BILILINK_SESSDATA`（B 站登录 Cookie 中的 `SESSDATA`）后，
可获取该账号有权观看的更高画质。

## 常见问题

**浏览器能播放，但 VLC、ffmpeg 或 curl 访问时返回 403？**

B 站 CDN 会拒绝部分程序默认的 User-Agent（实测 curl、VLC、ffmpeg 的默认值会被拒绝，浏览器与 mpv 正常），
这是上游的行为。BiliLink 只返回重定向，之后由播放器直接连接 B 站 CDN 并发送它自己的 User-Agent，
服务端无法代为设置。为播放器设置一个浏览器 User-Agent 即可，最简单的 `Mozilla/5.0` 就能通过：

```bash
vlc --http-user-agent="Mozilla/5.0" http://127.0.0.1:5000/BV1GJ411x7h7
ffmpeg -user_agent "Mozilla/5.0" -i http://127.0.0.1:5000/BV1GJ411x7h7 video.mp4
```

**返回 502，提示“B 站接口返回 HTTP 412（风控拦截）”？**

B 站会拦截它认为可疑的请求并返回 HTTP 412。BiliLink 发出的请求已经带有浏览器的请求头，持续出现这个错误，
说明服务器的出口 IP 被 B 站风控了。这无法通过修改配置解决，设置 `BILILINK_SESSDATA` 也一样，
只能更换服务器或网络；更换前可以先用[部署](#部署)一节开头的命令测试新的服务器。

## 开发

开发环境、代码规范、测试与发布流程见 [AGENTS.md](AGENTS.md)，变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 支持项目

我的蓝色大肥鱼为爱发电没饭吃了！！！如果本项目有帮到你，可以给她喂一点白饭！🐳🍚

<p><img src="./docs/support/blue-fish.webp" width="280" alt="吃白饭的蓝色大肥鱼"></p>

点个 Star、提个建议、分享给朋友，也都是支持。

<details>
<summary>投喂入口 · 微信 / 支付宝</summary>

<p>点击图片可查看原图。</p>
<table>
  <tr><th>微信支付</th><th>支付宝</th></tr>
  <tr>
    <td><a href="./docs/support/wechat-pay.png"><img src="./docs/support/wechat-pay.png" width="220" alt="微信支付支持项目收款码"></a></td>
    <td><a href="./docs/support/alipay.jpg"><img src="./docs/support/alipay.jpg" width="220" alt="支付宝支持项目收款码"></a></td>
  </tr>
</table>
</details>

## 致谢

- [BVAnalysis](https://github.com/RWONG722/BVAnalysis)：本项目的起点
- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)：B 站接口文档

## 许可证

[GPL-3.0](LICENSE)
