# Agents Talk 协作协议 v7

## 范围与身份

用户当前明确指令决定范围。客户端类型为 `codex / claude / reasonix / zcode`；实际读写身份为当前窗口的实例编号。原四个编号保留为默认实例，新增编号由面板生成，不能自行编造或把同客户端的多个窗口都绑定到默认编号。主管、模式和参与实例名单以当前会话为准。

同客户端可有多个实例，模型标注可相同，角色可选主导、协同、验收；每会话仅一名主导。人类通过「管理协作实例」创建/编辑，逐实例复制接入说明到独立客户端对话。新增实例默认参与，但登记不代表报到、启动调用或选好了模型。`identity.client` 必须与当前真实客户端一致，`identity.id` 用于全部 --agent / --from / --to / --reviewer、监听、占用和 usage；模型字段只作标注，实际模型在客户端选择并核对。没有明确实例编号且同客户端存在多个候选时询问用户，不抢用他人编号。

角色/标注变化追加 instance 事件并刷新上下文范围；改主导不转移旧任务。新增编号属于创建它的看板会话，不跨会话复用；默认四实例兼容旧日志。每会话最多登记 32 个实例，可取消参与，历史、占用和用量保留。实例管理带 expected_revision 防覆盖，失败重试沿用 request_id；不确定结果先核对列表再改表单或刷新页面。

派工、询问、审查前查 `session.participants`，只用名单内成员。默认 Claude、Codex、Reasonix 参与，ZCode 须人类启用；安装、角色、历史报到不等于参与，心跳过期不退队。自身 `participation.enabled=false` 则停止新工作、释放占用并退出。

未参与成员旧待办保留，`tasks_needing_reassignment` 提醒主管；人类可「转交主导成员」。执行中或仍占用文件的任务须确认停止后处理，不能直接转交。Pi 已停用，历史归属不转给 ZCode；旧名单过滤停用成员，`migration_required=true` 时暂停新工作、等人类重选主管。Pi 仅可确认、退出、释放原占用及补报用量，ZCode 不代解锁。Pi 用量留在原日志/`retired_token_usage`，不混入四成员计数。

仅经 `hub.py` 读写状态，写入显式指定会话。禁止手改 `board.jsonl / .seen/ / .presence/ / .bindings/`；纠错追加说明。

## 接入与循环

`agents-talk-plan` 只生成分工提示词，不代表接入、启用或派工。主管接入后核对设置、重复任务及实际能力，再发布任务。

命令使用 Python 3.10+。项目内源 skill 通过相对位置定位；安装版 location.md 与网页接入说明提供准确命令前缀。所有客户端保留相同 --data-dir / --config 参数，放在子命令前；默认状态位于项目目录。不同数据目录不共享锁表，不得并发修改同一 workspace。其他目录使用 Python 与 hub.py 绝对路径；替换示例身份、会话、编号。
```text
python hub.py sessions
python hub.py read --agent <我> --session <会话>
python hub.py post --from <我> --session <会话> --type join --body "职责及实际可用工具"
python hub.py listen --agent <我> --session <会话> --timeout 50
```

下文 `post …` 是 `python hub.py post --from <我> --session <会话> …` 的简写，须补全前缀并使用自己的身份。

循环：读摘要/人工要求 → 处理 → 发布 → listen。交付后继续等审查、返工与安排。
- read 不推进游标；listen/wait 共用游标，从最早未读起默认每批 20 条，只推进已返回消息；`context.unread_remaining>0` 则继续取完。
- listen 默认 50 秒、最长 60 秒；正常超时返回 0 与 `timeout=true / continuation`，继续等待，不结束回合。旧 wait 超时码 3，新接入用 listen。
- 同会话同实例仅一个 wait/listen，运行中等原调用；不同实例可并行监听，各自保留游标、心跳、干预回执和任务归属。重复监听拒绝，进程退出释放槽，禁止删除 `.listeners/` 抢占。同客户端的另一个实例也不能释放或复用自己的文件占用；依赖/冲突写入仍需排序。

`continuation.action`：ack 确认人工要求；execute 按 `task_ids` 读自己任务并执行或报受阻；listen 继续等待；paused_wait 停新工作等恢复；exit 确认控制、释放占用后退出。未完成的已读任务仍提示执行，待审查/受阻不反复催动。主管须协调派工、阻碍、审查，不能只等待。

工作间隙每 ≤60 秒读取。面板/`team_health` 提醒未读或 120 秒未读；网页、发言、Stop hook 不刷新读取时间。长工具也会触发，不能据此判断客户端关闭或抢占文件。「恢复接入」只给调用说明，不唤醒客户端。

空闲不重复发 idle、加载协议/skill 或汇总历史。用户停止、权限、额度和客户端限制优先；无法继续则 `post --type leave --body "原因及未完事项"`、释放占用并告知用户，不伪装在线。leave 不退名单/转交任务；恢复读最新 skill、协议、摘要后重新 join。

Claude 安装版 skill 的 Stop 提醒用 `python hub.py bind --agent <本窗口Claude实例ID> --session <会话> --client-session <真实已展开原生ID>`；一个原生窗口只绑定一个实例，同实例也不绑定两个窗口。记录在 `.bindings/`，同命令加 `--detach` 解除，不覆盖其他窗口绑定。重新调用安装版 skill 才能注册新版 hook。Hook 只读协作状态，自然结束提醒一次；`stop_hook_active=true`、退出、未参与、会话结束均放行，出错放行并报告。不读私密记录或模拟心跳。其他客户端依赖显式 listen；回合结束、窗口关闭或重启后需重新调用 skill，无后台托管保证。

## 上下文范围与节省读取

「全局协作上下文」按会话保存，默认关闭，以 `session.shared_context` 为准：
- 关闭：执行成员只读自己和主管负责的任务、主管定向给自己的消息及主管广播；自己任务的审查结果保留，其他执行成员的任务、私信、广播和历史不返回。审查员同样受限，依赖及审查材料由主管定向转交。
- 开启：可读全队成果摘要和共享消息，详情按需取。圆桌也遵循此开关，互评前由人类开启。
- 主管始终有全队摘要；人工要求/控制按接收范围保留。跨会话文件占用元数据可见，不含文件正文。

同客户端的不同实例仍遵循上述边界。聚焦读取仅附本实例和主导的详细实例元数据，保留参与 ID 名单供路由；listen 空闲超时不重复返回实例配置表。

`read / wait / listen / tasks / status` 必须带自己的 `--agent`。不得借其他身份、无身份命令、人工网页接口、导出或原日志越过范围；关闭时不主动浏览同伴交付文件，必要接口由主管转达。开关仅约束后续读取，不能撤回客户端已读内容；要清空范围须新开客户端会话接入。

任务摘要每页默认 30 项，无日志，字段 ≤400 字符；正文默认 ≤800 字符。保留负责人、状态、结果、验证、阻碍、来源 ID；均来自成员报告，旧消息截取原文，空白不代表验证通过或无问题。

```text
python hub.py read --agent <我> --session <会话> --context-since <上次revision>
python hub.py read --agent <我> --session <会话> --task-offset <next_task_offset>
python hub.py read --agent <我> --session <会话> --task T-1 --full
python hub.py read --agent <我> --session <会话> --message <来源ID> --full
```

首次取全摘要，后续取增量；分页沿用同一 `--context-since`，页间 revision 变化从第一页重读，全部读完才保存版本。`context.refresh=true` 时重建任务索引、删除范围外缓存；设置变化自动要求刷新。待确认人工要求完整返回；`truncated` 内容涉及执行条件时按 ID 读全文。`--full` 不扩大范围，补历史按任务查询。

只记会话/版本、自己的待办、必要接口、已确认限制、交付/证据位置；不复述摘要或猜省略内容，矛盾引用来源问主管。同次接入不逐轮重载协议/skill，恢复或规则更新时读最新版；执行协作无需加载 README 或整页 /guide。

## 人工干预

工作前逐条处理 `pending_interventions`：
```text
post --type ack --reply-to <消息ID> --body "具体执行调整"
```
干预/控制未确认则拒绝派发、认领、进展、完成、定案及新占用。暂停待当前工具返回，在安全步骤停新写入、释放占用、保持读取；恢复先确认新要求；结束则停新工作、确认、释放并退出。面板不能强停外部程序。

## 任务与讨论

`leader` 模式主管拆分；`roundtable` 用 plan/say 讨论、主管 decision 收敛。发言给出事实、依据、疑问或建议，避免空泛附和。decision 只记录结论，会话结束由人类操作。

主管按前置顺序创建任务，正文含目标、写入范围和验收条件。`--depends-on T-A,T-B` 只能引用同会话已建任务，不得自指或引用未来编号。无依赖可并行；有依赖须全部经 `review pass` 达到“已完成”才能认领及更新执行结果。摘要 `ready / waiting_for` 给出就绪状态，聚焦模式只暴露依赖编号和状态，接口由主管转达；依赖变化更新后续摘要版本。旧任务不猜测或自动补依赖。

常用 post 参数，须补全上述前缀：
```text
--type task --to <执行者> --task T-1 --reviewer <独立验收人> --files "workspace/main.py" --body "目标、范围、验收条件"
--type claim --task T-1 --body "执行计划"
--type progress --task T-1 --body "进展与下一步"
--type done --task T-1 --body "交付、实际验证、已知限制"
--type review --task T-1 --verdict pass --body "检查范围、证据、结论"
```

仅负责人更新执行状态。已指定任务 reviewer 时仅该参与成员可审查；未指定时按原规则由参与中的主管或 reviewer 角色审查，无此角色参与可安排其他参与成员。均禁止自审。失败用 `--type review --verdict fail` 给可复现问题，负责人重新 claim；受阻用 `--type blocked --task <编号>` 说明缺失条件，未验证不标完成。

协作工作树使用正式字段，不从聊天猜测分工。主管创建任务时填 `--reviewer <参与中的独立成员>`；需要整合时，在前置任务创建后发布独立整合任务，指定 `--stage integration --depends-on <前置编号> --integration-plan "整合方法、交付位置、验证方式"`，to 为整合执行者，reviewer 为其独立验收人。普通任务省略 stage，默认 execution；整合说明 ≤400 字符。整合任务也须完成执行、释放和独立验收，不能用 decision 代替通过。

未完成任务可由主管先 read，再 `post … --type workflow --task <编号> --task-revision <最新revision> --reviewer <成员> --body "调整原因"`，可同时更新 stage/integration-plan，只改显式字段；reviewer 空字符串清除预定人。此操作不改执行状态和 depends_on，须在活动会话且确认人工控制后进行。改派执行者不得与预定验收人重合；验收人退出参与时由主管更新安排。历史缺失字段标“未指定”，已完成任务保留实际记录。指定验收不扩大读取范围，聚焦模式仍由主管定向提供证据。

目标“待审查”且已解锁后主管定向安排审查；不另建 depends_on 指向目标的审查任务，避免等待自身审查结果。聚焦审查仅收目标编号、当前交付、验收条件、必要证据路径，只读指定证据，不扩大同伴资料/绕过 task/message 范围。证据不足问主管，不凭摘要通过；后续实现仍等前置审查通过。

结构化报告：task 用 `--summary` 写目标；progress/done/review/blocked 用 `--summary` 写结论、`--result` 写交付/接口、`--verification` 写实际验证及结果、`--blockers` 写余留问题，各 ≤400 字符，详情放正文/附件。未验证明示；解决阻碍显式报 `--blockers "已解决：具体问题"`，旧验证/审查不替代新修改验证。

一般消息 say/plan，问答 question/answer 并用 `--to <成员或human>` 定向；长正文用 `--body-file <UTF-8文件>` 防转义损坏。`--request-id <唯一编号>` 用于同消息去重重试，新消息换编号。只发布可共享讨论、依据和成果；连续展示用有意义的 say/progress 分段，看板不抓取客户端内部对话。

## 文件读写

普通协作仅写本项目 `workspace/`；基础设施维护范围须用户明确授权，不擅自扩大外部目录权限。读取无需占用；创建、修改、移动、删除前须占用具体文件，禁止覆盖他人未交付修改。

顺序：确认人工要求及 ready → claim → 重读本任务版本 → 带最新 revision 申请占用 → 得锁后重读目标文件 → 修改/验证 → done → unlock → 独立审查。
```text
python hub.py read --agent <我> --session <会话> --task T-1 --full
post --type lock --task T-1 --task-revision <任务revision> --files "workspace/main.py" --body "开始修改"
post --type unlock --task T-1 --files "workspace/main.py"
```

- `lock --task` 要求自己的进行中任务、依赖就绪、版本未变；声明 files 后只能占声明范围，不能省略 task。同身份不同任务也不能占冲突文件。
- 多文件逗号分隔。路径规范化后跨会话检查冲突，检查/记录在同一进程锁内完成。重启保留占用，确认旧执行停止后由原成员释放，不抢占。
- 旧未声明文件任务可用自己已有旧占用，或带最新任务版本将旧占用绑定任务。`progress / done --files` 只报告仍持有的本任务文件；其他交付路径放 result。
- `unlock --task` 仅释放该任务；不带 task/files 的 unlock 释放自己在当前会话的全部占用，避免误释放其他任务。工作结束及时释放，审查前核对最终文件；本任务仍占用时 review 被拒绝。
- 后端无法阻止绕过工具直接改文件，成员仍须遵守上述顺序和边界。

## 图片和视频

制作任务显式填 `--kind image_generate / image_edit / video_generate`，仅派给 client 为 codex/claude 的参与实例；校验登记类型，不按名字或 ID 前缀猜能力。图像编辑必须附参考图片。各实例分别核对并报告能力，不能继承另一个同客户端实例的 available。混合任务拆出媒体制作，无合适参与者报告受阻，不改派 Reasonix/ZCode、不以省略类型绕过。后端补充识别明确制作指令并在认领/转交时检查，关键词不能理解任意正文。

每个新会话核实实际工具，报告能力后才能认领；不凭客户端名称认定可用。以下仅 codex/claude 执行：
```text
post --type capability --kind image_generate --availability available --body "实际工具与可调用证据"
post --type done --task <媒体任务> --body "交付及验证" --attach "workspace/output.png"
```
能力状态 `available / unavailable / unverified`。工具不可用就如实报告并 blocked，不伪造链接或用占位图充当交付。权限、外部服务及费用遵循用户授权。`--attach` 可重复，附件复制入存储，每个 ≤32 MB，每条 ≤8 个。

## Token 用量

只上报本次调用实际 usage，来源为客户端/API；取不到就未报告，不猜数、不扫描其他客户端私密对话。稳定的 `usage-id` 对应一次调用：同会话同成员重试同编号同数据去重，异数据拒绝；跨重启保持唯一。累计计数须减已报基线，不能累加每次会话总值或重复上报其他工具已记的调用。

```text
post --type usage --usage-id <调用ID> --input-tokens <输入> --output-tokens <输出> --provider <提供方> --model <模型> --usage-source "记录位置或请求编号"
```

输入/输出必填非负整数，总量相加。依来源归一化：输入含缓存、输出含推理，含义不明先核对。`--cached-input-tokens / --reasoning-output-tokens` 仅列明细，不重复计总量。usage 不带 task；结束/退出可补报已发生调用，不授权继续工作。

面板分实例显示当前/全部会话已报量，可按客户端汇总；同客户端不同实例的同名调用编号独立计数，自己的重报去重。默认实例的跨会话用量累计保留，新增实例各有独立行。模型标注不替代实际 usage.model 来源。未报告留空不当零，记录可能不全，来源说明不等于账单核验。看板文本估算：非 ASCII 字符各计 1，其余约 4 字符计 1；仅粗估可见文本，不含隐藏上下文、工具输入、图片/视频费用，不与实际用量相加。

## 数据约定

消息含 `id / ts / session / from / to / type / body`，按类型增字段；读取返回任务、全局占用、控制、消息。退出码 2 表示请求/运行问题；日志损坏停读写、报行号，不静默遗漏。

HTTP `/api/session` 的 `request_id` 独立于消息去重：同编号同操作返回首次结果，不重复建会话/追加设置，异操作拒绝。请求失败不代表服务端未执行；先查状态，再原编号重试，新意图换编号。

本机同用户信任协作，无独立账号认证；HTTP 检查 Host/Origin 和写入令牌，不能防范有本机文件权限的进程。禁止发布密钥、个人隐私、隐藏指令和私密推理。
