# 宣传视频

[观看或下载 MP4](https://github.com/fffssss11/agents-talk/releases/download/v0.1.0-rc.3/Agents-Talk-Promo-1080p60.mp4)

54 秒，1920×1080，60 fps，H.264 视频与 AAC 立体声。文字直接呈现在画面中，无旁白。原创合成配乐带淡入淡出，未使用外部歌曲或声音采样。

## 分镜

| 时间 | 画面与内容 |
| --- | --- |
| 00:00 至 00:06 | 多窗口协作的交接问题，概念背景与动态标题 |
| 00:06 至 00:12 | Agents Talk 面板，实际空白会话 |
| 00:12 至 00:20 | 同客户端的主导、实现、验收窗口 |
| 00:20 至 00:29 | 派发、独立验收与依赖整合工作树 |
| 00:29 至 00:37 | 全员对话与人工要求 |
| 00:37 至 00:45 | 聚焦与全局摘要机制示意 |
| 00:45 至 00:54 | Python 启动步骤与 GitHub 下载入口 |

功能依据为 [README](../../README.md) 和 [协议](../../PROTOCOL.md)。实际界面使用明确标注的隔离演示数据，概念背景由 AI 生成。没有真实模型调用或效率收益测量。截图动效属于剪辑，不表示各客户端的实时执行速度。

## 修改与复现

`timeline.js` 控制文案、场景时刻、五次缓动和界面推拉。浏览器预览默认暂停，点击按钮播放。`render.cjs` 按确定时间逐帧绘制，再交给 FFmpeg 编码，不启动 hub，不读取本机协作历史。

需要 Node 20+、Playwright、浏览器与支持 `libx264`/AAC 的 FFmpeg。它们仅用于视频制作，用户运行面板无需这些工具。

```sh
npm ci
npx playwright install chromium
node docs/promo/render.cjs --stills
node docs/promo/render.cjs
```

FFmpeg 默认从 PATH 查找，可用 `FFMPEG` 环境变量指定可执行文件。浏览器可用 `AGENTS_TALK_BROWSER` 指向本机 Chrome。Windows 渲染字体为微软雅黑，其他平台需安装合法可用的中文字体并调整字体配置，重新检查换行。

`--stills` 只生成审阅帧与 `docs/assets/promo-poster.png`。完整渲染同时更新海报，输出 `dist/media/Agents-Talk-Promo-1080p60.mp4`。中间帧与配乐在 `.runtime/promo-build/`，不进入源码包。脚本拒绝覆盖已有 MP4，修订前保留旧版并选择新的输出名称。

编码参数参考 [FFmpeg 文档](https://ffmpeg.org/ffmpeg.html)。素材与工具说明见 [THIRD_PARTY_NOTICES](../../THIRD_PARTY_NOTICES.md)。重新发布前检查完整视频、转场、音量、元数据及实际帧数，计算 SHA-256。
