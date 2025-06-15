# ✨ BiliLink

## 项目概述
基于 FastAPI 的 Bilibili 链接解析工具，支持B站视频、直播推流链接提取。

本项目是 [BVAnalysis](https://github.com/RWONG722/BVAnalysis) 的 FastAPI 重构版，并在原有功能上添加了直播和 IP 限流功能。

代码大部分由豆包重构，甚至标题和README都是豆包写的（）

## 功能特性
1. **视频解析**：支持输入 BVID 解析视频信息并跳转至视频播放链接。
2. **直播功能**：支持输入直播间 ID 获取直播推流链接。
3. **IP 访问限制**：对每个 IP 的访问频率进行限制(10次/分钟)，防止恶意请求。

## 环境要求
- Python 3.x
- 所需依赖库可通过 `requirements.txt` 文件安装。

## 安装与启动
### 安装依赖
```bash
pip install -r requirements.txt
```

### 启动项目
```bash
python ./app.py
```

### 配置说明
- 默认情况下，项目会监听 `0.0.0.0:5000` 端口。你可以在 `app.py` 文件中修改相关配置。

## 使用方法
### 视频解析
- 访问 `http://127.0.0.1:5000/BVxxxxxxxxxx` 获取视频播放链接，其中 `BVxxxxxxxxxx` 为具体的 BVID。
- 若需要指定视频的分 P 页面，可访问 `http://127.0.0.1:5000/BVxxxxxxxxxx?p=1`，其中 `p` 为页面编号。

### 直播推流
访问 `http://127.0.0.1:5000/live/xxxxxxx` 获取直播间的推流链接，其中 `xxxxxxx` 为具体的直播间 ID。

## 许可证
本项目遵循 [BVAnalysis](https://github.com/RWONG722/BVAnalysis) 采用 GNU General Public License v3.0 许可证，详情请参阅 `LICENSE` 文件。

## 贡献与反馈
如果你对本项目有任何建议或发现了问题，欢迎提交 Issues 或 Pull Requests。
