# 参与开发

## 环境和验证

运行依赖 Python 3.10+ 标准库。界面为本地 HTML/CSS/JavaScript，不依赖 CDN 或前端构建器。浏览器开发测试额外需要 Node 20+。

```sh
python -m unittest discover -s tests -v
npm ci
npx playwright install chromium
npm run check
npm test
```

Linux CI 安装浏览器及系统依赖使用 `npx playwright install --with-deps chromium`。浏览器三套测试依次使用 18765、18766、18767，端口被占用会失败，不应复用其他服务。用 `AGENTS_TALK_PYTHON` 指定 Python 可执行文件，用 `AGENTS_TALK_BROWSER` 指定已有 Chromium 系浏览器；默认使用 Playwright 下载的 Chromium。不要设置变量指向真实会话数据。浏览器下载受网络限制时可用环境变量指定本机已安装的浏览器，不要关闭 TLS 验证。

公开 README 截图用 `node tests/preview.cjs` 重新生成，只展示独立空白会话，额外使用 18768 端口。

所有测试使用临时状态目录与 `config.example.json`。截图写入 `.runtime/`，只包含隔离测试数据。发布验证另检查解压后的干净副本，不允许测试依赖开发者已有 `config.json`、`python-path.txt` 或安装的全局 skill。

## 代码地图

| 入口 | 职责 |
| --- | --- |
| `hub.py` | CLI、事件事务、状态推导、上下文范围及回环 HTTP 服务 |
| `web/` | 消息、任务、工作树、实例和人工控制界面 |
| `start.py` | 无安装依赖的前台启动入口 |
| `scripts/install_skills.py` | 可预览的 skill 安装、备份、归属清单及保守卸载 |
| `scripts/project_tools.py` | 只读环境诊断 |
| `scripts/build_release.py` | 精确清单打包和发布前静态检查 |
| `scripts/audit_public.py` | 源码、Git 身份及演示附件的只读隐私检查 |
| `skills/` | 两个可移植 skill 的唯一维护源 |
| `PROTOCOL.md` | agent 的读写及协作规则 |
| `tests/` | 后端回归、发布/安装回归及浏览器验证 |

事件写入在跨进程事务锁内完成验证与追加；不直接修改旧事件。人类 HTTP 写入使用页面凭证和来源检查，agent 通过 CLI 使用明确实例身份。它们共享同一份本地事件状态，但上下文输出不同，详细信任边界见 SECURITY.md。

## 提交要求

- 修复优先附带可复现测试，使用虚构的隔离输入，不复制真实聊天、原生客户端日志或附件。
- 保留旧日志兼容性、实例身份、文件占用、人工确认和独立验收约束。
- 规则变化更新 PROTOCOL.md，README 只保留入口与用户摘要；不复制第二份完整协议。
- 新增维护文件时更新 `release-files.json`，不要把整个目录递归加入发布清单。
- UI 变化验证桌面、窄屏、键盘、减少动画偏好，覆盖发送、控制和断线重连。
- 不在运行时引入外部遥测、自动安装、未经请求的远程调用或真实客户端代发。
- 公开问题/变更说明中注明实际执行的命令、结果和未验证的平台，不把 CI 配置写成已通过的 CI 结果。

## 发布前

跟随 [发布清单](docs/release.md)。版本同时更新 `VERSION`、`package.json` 和 lockfile。发布清单只打包源码，`.gitignore` 仅保护 Git 默认选择，不能清除曾经提交的秘密，也不替代人工安全审查。

贡献代码按本项目 MIT 许可证分发。提交前确认你有权贡献相关内容，不包含私人数据或未经授权的第三方材料。
