# 项目协作入口

- 加入会话时读 `PROTOCOL.md`，通过 `skills/agents-talk/SKILL.md` 接入。具体规则只维护在协议中。
- 普通任务写入范围为 `workspace/`，会话状态通过 `hub.py` 读写。用户明确要求维护本项目基础设施时，可修改相应文件并同步协议。
- 后端使用 Python 标准库，前端使用本地 HTML / CSS / JavaScript。不要把模拟消息混入正式日志。
- 行为变化运行 `python -m unittest discover -s tests -v`，界面变化检查桌面和窄屏，验证发送、控制和重连。
- 浏览器开发测试使用 `npm ci`、`npx playwright install chromium`、`npm test`；不依赖本机私有运行环境。
- 源码发布仅用 `scripts/build_release.py` 的精确清单，禁止打包真实会话、附件、业务目录、本地配置及备份；新增维护文件同步 `release-files.json`。
- 尊重用户已有修改，记录实际行为及验证结果，文档保持一个规则来源。
