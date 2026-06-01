# DLD Any Media

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的可视化媒体下载器，克莱因蓝主题，TikTok 风格 UI。

![screenshot](https://github.com/user-attachments/assets/placeholder)

## 功能

- 粘贴链接即可下载视频或音频
- 支持画质选择（最佳 / 1080p / 720p / 480p）
- 视频输出 MP4，音频自动提取为 MP3
- 下载进度实时显示
- 下载记录管理

## 前置条件

1. **Python 3.8+** — [下载地址](https://www.python.org/downloads/)
2. **yt-dlp** — 安装：`pip install yt-dlp`
3. **Flask + Flask-CORS** — 安装：`pip install flask flask-cors`
4. **FFmpeg**（可选，转换格式时需要）— [下载地址](https://ffmpeg.org/download.html)

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/dld-any-media.git
cd dld-any-media

# 2. 安装依赖
pip install yt-dlp flask flask-cors

# 3. 启动
python app.py
```

浏览器会自动打开 `http://127.0.0.1:5128/`。

Windows 用户也可以直接双击 `start.bat` 启动。

## 截图

| 主界面 | 下载记录 |
|--------|----------|
| ![main](screenshot-main.png) | ![tasks](screenshot-tasks.png) |

## 技术栈

- **后端**：Flask + yt-dlp Python API
- **前端**：原生 HTML/CSS/JS，无框架
- **主题**：克莱因蓝 (#002FA7) + TikTok 风格圆角卡片

## License

MIT
