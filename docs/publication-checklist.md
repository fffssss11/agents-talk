# 公开发布检查

只发布精确源码清单和经过独立审阅的演示附件。不要对正在使用的目录执行全量提交或压缩。

## 三轮检查

1. **源码与事实**：检查 `release-files.json`、README、协议、版本、许可证和安装入口。说明已实现的功能、实际运行过的测试及未验证事项。
2. **隐私与材料**：检查源码、截图、PPT 可见文字和备注、作者属性、外部链接、PDF 元数据及附件。仅使用空白会话或明确标注的隔离演示，禁止原生客户端私密记录、账号令牌、个人目录和真实业务材料。
3. **干净副本与远端**：从发布包解压或从仓库克隆，运行测试、安装预览和启动检查。上传后核对远端树、提交邮箱、CI 结论及下载校验值。

```sh
python -m unittest discover -s tests -v
python scripts/build_release.py --check
python scripts/audit_public.py --source .
python scripts/build_release.py
python scripts/audit_public.py --artifact ./dist/agents-talk-VERSION.zip
```

上方 `VERSION` 需替换为实际版本。PPTX/PDF 可通过重复 `--artifact` 检查。扫描只报告问题类别，不回显匹配的敏感值。规则匹配不覆盖所有隐私，必须人工审阅图片和事实。

PDF 的标准库扫描仅检查暴露的语法，不解码压缩流或混淆元数据；还需要 PDF 解析器核对元数据、动作和附件，并逐页检查渲染结果。不要把扫描通过理解成安全认证。

## GitHub 内容

- 使用独立的空目录导入审核后的源码，避免旧提交历史带出已删除的信息。
- 只在此仓库设置 Git 提交身份，使用 GitHub 设置中提供的隐私邮箱。不要改全局 Git 身份。
- 提交前运行 `python scripts/audit_public.py --source . --tracked`，确保 Git 追踪文件恰好等于发布清单，提交邮箱均为 GitHub 隐私邮箱。
- 不在公开 issue 中提供漏洞利用细节。启用 GitHub 私密漏洞报告后更新 SECURITY.md 的实际入口。
- 版本仍需外部试用时标为 pre-release，不能根据单机通过就宣传全平台验证。
- Release 附源码 ZIP、SHA-256、项目介绍 PPTX 和 PDF。保留包内源码清单，不上传开发依赖、构建日志或私密审查收据。

SHA-256 可用于检查文件是否一致，不提供作者身份认证。Windows 用 `Get-FileHash 文件名 -Algorithm SHA256`；macOS 可用 `shasum -a 256 文件名`；Linux 可用 `sha256sum 文件名`。

如果发现已公开的有效密钥，立即撤销或轮换，再处理仓库与历史；删掉文件无法使旧密钥失效。
