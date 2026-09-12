# 发布与验收

## 当前状态

`0.1.0-rc.2` 已上传至 [fffssss11/agents-talk](https://github.com/fffssss11/agents-talk)。仓库保持私有预发布状态，许可证及公开署名待项目所有者确认，当前不对外授予开源许可。

源码和项目介绍材料用于发布前审阅。确认许可证后需加入 LICENSE、同步 package 元数据和发布清单，重新打包，再转为公开。不得将私人候选包描述成已经授权的开源版本。

## 实际验证

2026-09-12 完成本轮验证。程序及启动脚本对应提交 `80772e5`，随后文档更新不改变这些程序文件。

| 环境或内容 | 结果 |
| --- | --- |
| 本机 Windows，Python 3.13.5 | 89 项测试，88 项通过，1 项因符号链接权限限制跳过 |
| GitHub Windows，Python 3.10 / 3.13 | 后端、安装、启动、诊断、源码清单和隐私检查通过 |
| GitHub macOS / Ubuntu，Python 3.10 / 3.13 | 后端、安装、诊断、源码清单和隐私检查通过；Windows 专用测试跳过 |
| 浏览器 | 本机 Chrome 与 GitHub Linux Chromium 的三套回归通过，含发送、人工控制、重连、窄屏、观察窗和同客户端多实例 |
| 安装与干净副本 | 隔离 skill 目标验证预览、安装、重复安装和保守卸载；源码 ZIP 解压启动为零消息、零任务 |
| 演示材料 | 12 页 PPTX 结构、版面、字体策略与重新导入检查通过；PPT/PDF 逐页检查，备注、链接、作者属性和附件检查未发现私人信息 |

[通过的 GitHub CI 运行](https://github.com/fffssss11/agents-talk/actions/runs/34680493153) 含 7 个成功的 job。CI 使用托管环境，不能替代所有用户设备和原生客户端的验证。

审查中修复了英文 Windows 输出中文路径的编码错误；随后一次 Windows 启动测试超出原 35 秒测试预算。现已优先验证明确指定的 Python，服务就绪等待有计时边界并核对新进程 PID，失败时只清理本次子进程；测试保留所有原断言，并为互斥锁等待和共享运行器启动留出预算。复验全部通过。

本机 Playwright Chromium 下载曾因 TLS 传输错误未完成，没有关闭 TLS 校验。本机浏览器测试使用已安装的 Chrome；GitHub Linux 成功安装并运行 Playwright Chromium。

## 尚未验证或不提供的能力

- 本轮未验证真实客户端中的 skill 发现、模型/API 调用、图片/视频生成效果或所有账户组合。文件安装成功不等于原生接入成功。
- 没有压力测试、性能收益基准或第三方安全审计认证。长历史读取仍需推导事件，面向可信本机的小规模协作。
- Windows 提供桌面快捷方式；macOS/Linux 使用前台入口，没有原生桌面安装包。
- PPT 使用微软雅黑，其他设备可能替换字体。PDF 为图像阅读版。没有宣称在 PowerPoint 原生应用内验证。

## 发布包与隐私

只收录 `release-files.json` 中精确列出的源码和公开演示图，不遍历工作目录。排除真实消息、附件、业务成果、本机配置、安装版路径、依赖、备份及诊断日志。本轮正式聊天日志和本机配置的校验值未发生变化。

包内 `SOURCE-MANIFEST.json` 记录各源码文件的 SHA-256，包外校验文件记录 ZIP 和演示材料的摘要。固定 ZIP 时间戳，同一份源码字节生成一致的归档。校验值用于检查完整性，不构成作者签名。打包器拒绝覆盖已有 ZIP。

## 复现发布检查

遵循 [三轮发布检查](publication-checklist.md)，从独立干净目录操作：

```sh
python -m unittest discover -s tests -v
python scripts/audit_public.py --source .
python scripts/build_release.py --check
python scripts/build_release.py
```

许可证确认前，上述打包命令需显式添加 `--allow-unlicensed`，输出仅限私人审阅。确认后去掉该标记。运行面板不依赖 pip 或 npm；浏览器开发测试命令见 [贡献指南](../CONTRIBUTING.md)。
