# 发布与验收

## 当前版本

`0.1.0-rc.3`，MIT 许可，公开预发布版。源码与演示材料位于 [GitHub Release](https://github.com/fffssss11/agents-talk/releases/tag/v0.1.0-rc.3)。保留预发布标记，便于收集原生客户端与不同设备的试用反馈。

运行程序沿用 rc.2。本版增加许可证一致性检查、公开项目元数据、文档链接回归，以及精简 PPT 和宣传视频。

## 实际验证

2026-09-12 本机 Windows 验证结果：

| 内容 | 结果 |
| --- | --- |
| Python 3.13.5 | 93 项测试，92 项通过，1 项因符号链接权限限制跳过 |
| Chrome 浏览器 | 三套回归通过，含发送、人工控制、重连、窄屏、观察窗和同客户端多实例 |
| 发布检查 | 精确清单、许可证、版本一致性、文档本地链接及静态隐私检查通过 |
| PPT 与 PDF | 6 页，PPTX 结构、版面、字体和重新导入检查通过，逐页检查可见内容 |

跨平台 CI 包含 Windows/macOS/Ubuntu 与 Python 3.10/3.13，以及 Linux Chromium 浏览器测试。前一版已有 [7 个 job 全部通过的记录](https://github.com/fffssss11/agents-talk/actions/runs/34680720373)。本版本最终提交与 CI 链接列在 Release 中，最新状态见 [Actions](https://github.com/fffssss11/agents-talk/actions)。配置本身不代表每次运行已经通过。

本机 Playwright 下载曾遇到 TLS 传输错误，测试改用已安装的 Chrome，没有关闭 TLS 校验。测试、截图和干净安装均使用独立目录，不写正式聊天。

## 交付内容

- 源码 ZIP，内含 `SOURCE-MANIFEST.json`，记录每个源码文件的 SHA-256。
- ZIP 独立校验文件与全部附件的 `SHA256SUMS.txt`。
- 6 页可编辑 PPTX，以及图像 PDF 阅读版。
- 54 秒 1080p/60fps MP4，AAC 立体声，含原创合成配乐，无旁白。画面使用隔离演示截图，概念背景由 AI 生成。视频验证记录随 Release 列出。

发布工具只读取 `release-files.json` 的精确文件，不遍历真实聊天、附件、成果、配置、安装版路径、依赖或备份。同一源码字节生成确定的 ZIP，工具拒绝覆盖已有归档。校验值检查文件一致性，不提供作者签名。

## 已知边界

- 未覆盖所有原生客户端的 skill 发现、实际模型/API 调用、媒体生成或账户组合。安装文件成功仍需检查实际报到。
- 不提供原生窗口自动创建、真实模型切换或回合停止后的自动唤醒保证。
- 仅面向可信本机，缺少多租户认证、系统沙箱及本地加密。没有第三方安全审计或性能收益基准。
- Windows 提供快捷方式，macOS/Linux 使用前台入口，均没有原生桌面安装包。
- PPT 使用微软雅黑，接收端可能替换字体。PDF 与 MP4 已渲染文字。未在 PowerPoint 原生应用内验证。

## 复现

按 [发布检查清单](publication-checklist.md) 从干净副本运行：

```sh
python -m unittest discover -s tests -v
python scripts/audit_public.py --source .
python scripts/build_release.py --check
python scripts/build_release.py
```

浏览器测试见 [贡献指南](../CONTRIBUTING.md)，视频制作见 [分镜与复现](promo/README.md)。`--allow-unlicensed` 仅供未选择许可证的私人候选审阅，公开 CI 与正常发布不使用该参数。
