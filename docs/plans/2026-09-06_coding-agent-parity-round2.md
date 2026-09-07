# 编码代理对标差距分析·第二轮：UI / 功能点 / 逻辑（2026-09-06）

- **状态**：批次 A 已交付（L1/L2/U1，main PR #451；win7 PR #452）；批次 B 已交付（L3/L5/L7/U5/U8/U13，main PR #456；win7 PR #461）；批次 C-1 已交付（L8/L13/F5/F6/U10/U14，main PR #463；win7 PR #464）；批次 C-2 已交付（L11/U9/U7，main PR #468，win7 待 cherry-pick）；批次 C-3 已交付（L6/L9-lite/L12-lite/L10/U11，main PR #469，win7 待 cherry-pick）——第二轮 P0/P1/P2 全部落地
- **实施记录**：批次 A/B/C 分支 `feat/parity-r2-batch-{a,b,c,c2,c3}`（worktree `.worktrees/` 同名目录）。win7 对齐沿用第一轮 §4 惯例（A/B/C-1 已同步，C-2/C-3 待 cherry-pick）
- **win7 实施备注**：① 后台线程池写 SQLite 在 py3.8 下段错误（CI 实证）——落库一律行内同步 + _SQLITE_LOCK；② 同步 DB 调用统一经 `_run_db_sync`（内部自带锁的函数走裸 executor，防非重入死锁）；③ `test_explicit_null_orchestration_mode` 断言须在 patch 作用域内轮询（producer 后台任务时序竞态，前置 await 增多后必输）
- **CI 备注**：PR459/461 期间 GitHub 的 pull_request 事件对 `cherry-win7-batch-b` 分支一度不触发（同构分支 PR452 正常），期间以 `workflow_dispatch` 手动跑 CI 验证；后续 push 事件恢复正常
- **上游文档**：[2026-09-06_coding-agent-parity.md](./2026-09-06_coding-agent-parity.md)（第一轮 G1-G10 工具面差距，Phase-1/2 已交付，仅剩 G7）——本文不重复其内容，承接其后继续分析
- **对标对象**：ZCode（CLI 编码代理）、Qoder（Agentic 编码 IDE）、Codex（OpenAI 编码代理）；参照 Claude Code / Cursor 习惯用法
- **方法**：三路代码勘察（前端 19 项逐条核查 / 后端主循环与逻辑链路 / 存量与在途工作清查），全部结论附 `file:line` 证据
- **编号约定**：L = 逻辑层（agent 循环 / 上下文 / 可靠性）、U = UI 层、F = 功能点；与第一轮 G 编号互引

## 0. 结论速览

第一轮解决了"工具面"（agent 能做什么）。本轮发现的主要差距集中在三处：

1. **逻辑层有两个 P0 级问题**：主聊天路径**不携带会话历史**（L1）、**无真流式**（L2）——这两项不修，Sage 不具备主流编码代理的底线会话语义；另有重试/缓存/并行/记忆注入等一批 P1-P2。
2. **UI 层缺"编码代理三件套"**：diff 审查视图（U1）、checkpoint/rewind 入口（U2）、Git 面板（U3）均无 UI——第一轮交付的 git/checkpoint 工具前端零消费（`grep checkpoint|rewind` 前端零命中）。
3. **架构债需要决策**：新能力持续落在 hex 路径而生产默认 legacy（L14），建议先收敛再继续投入。

已具备的相对强项（不再建设）：NDJSON 两段式流事件架构、权限审批往返（含 remember 持久化规则）、编排计划卡/任务树/子代理事件时间线、MCP 管理 UI、后端进程监督 + 自动更新/回滚、tier 化 E2E、会话 fork/compact/HTML 导出。

## 1. 逻辑层差距（L）

| # | 差距 | 证据 | 对标 | 价值 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| L1 | **主聊天不携带会话历史**：legacy producer 每次只组装 `[system, attachments?, user]`，持久化历史不进 LLM 请求（代码自述该局限） | api/legacy_routes.py:2248-2260、:748-753 | 三家均携带完整历史 | 用户第二条消息起 agent"失忆"，追问"继续刚才的修改"无法执行；compaction 只惠及存储/UI/fork，不省每轮 token | **P0** |
| L2 | **无真流式 tool-calling**：主循环用非流式 `chat()`，DONE 后按 6 字符/40ms 假切块；`chat_stream` 不支持 tools | legacy_routes.py:19-20、:2329-2344；llm_client.py:388-468 | 三家均真流式 | 首 token 延迟 = 整个响应时长，长回复时前端"卡死"观感 | **P0** |
| L3 | **无 API 重试/退避**：429/5xx/timeout 仅分类后直接终止 run；429 解析了 retry-after 但不自动重试 | llm_client.py:169-213 | 三家均指数退避 | 长任务因瞬时抖动整体失败 | P1 |
| L4 | **无 prompt caching**：全链无 cache_control；仅 hex adapter 读 cached_tokens 做拆账 | grep 无命中；adapters/out/llm/openai.py:86-101 | Claude Code/OpenAI 均吃缓存 | 长上下文成本/延迟减半以上；**依赖 L1**（先有稳定长前缀） | P1 |
| L5 | **system prompt 无环境上下文、无技能清单**：`build_system_base` 仅身份+office+agent 列表；无 cwd/git 分支/日期/平台；技能只能靠 LLM 盲调 skill 工具 | profiles.py:611-614；skill_tool.py:75-97 | Claude Code `<env>` 块 + Skill 元数据注入 | 模型对工作区状态零感知；已有技能发现不了 | P1 |
| L6 | **工具串行执行**：一次响应的多 tool_calls 用 for 循环串行（仅 agent/dispatch/blocking 三特例） | agent.py:688、:887-912 | 三家并行独立调用 | 多文件读/多搜索场景耗时线性叠加 | P2 |
| L7 | **legacy 循环缺每-run 守卫 + 参数解析静默**：`ToolPolicy.max_tool_calls_per_run=25` 仅 hex 消费；tool args JSON 解析失败静默变 `{}` | tool_policy.py:31 vs chat_service.py:686-693；agent.py:689-696 | — | 失控循环无刹车；LLM 拿不到"参数错了"的反馈会重复犯错 | P1 |
| L8 | **用量不落库、不分会话、无 cache 拆账**：内存 ring buffer 1000 条，重启即失 | usage_tracker.py:25；usage_routes.py:18-21 | Claude Code /cost、Cursor 用量 | 无法回答"这个会话花了多少" | P2 |
| L9 | **ContextCompactor 三层压缩未接线 + 无 per-model 窗口记账**：131072 为硬编码默认 | application/services/context_compactor.py（仅 branch_summarizer 文档引用） | 三家按模型窗口管理 | 依赖 L1 落地后才有意义 | P2 |
| L10 | **MCP 仅 stdio + 仅 tools**：无 SSE/streamable-http 传输；无 resources/prompts | mcp/client.py:85-92、:197-219 | Claude Code 全传输 + prompts 即命令 | 远程 MCP server 无法接入 | P2 |
| L11 | **hooks 仅 pre/post_tool_use**：缺 SessionStart/Stop、UserPromptSubmit、Stop 等点 | hooks/config.py:28 | Claude Code 8 个 hook 点 | 自动化面窄（如会话结束自动总结做不到） | P2 |
| L12 | **中断粒度粗**：interrupt 标志每轮迭代顶部才消费，执行中的工具不可取消；子代理 worker 超时后不可杀 | agent.py:622-631；agent_tool.py:404-414 | 三家可中断在执行操作 | 卡住的 bash 只能等超时 | P2 |
| L13 | **记忆不注入主聊天循环**：legacy `/chat/stream` 不注入记忆上下文，仅 memory_search 工具可及——与 PHILOSOPHY"记忆优先"定位相悖 | legacy_routes.py:2248-2260 | Claude Code 自动注入 CLAUDE.md/记忆 | 产品核心卖点未在主路径生效 | P2 |
| L14 | **双路径架构债**：ToolPolicy/ContextCompactor/SessionService/cache 拆账等新能力均落在 `API_MODE=hex`，生产默认 legacy（main.py:608），能力持续单侧漂移 | main.py:572-613 | — | 重复建设 + 新能力到不了用户 | **P1（先决策）** |

### 1.1 重点项路径勘察

- **L1 历史接线（P0，其余多项的前提）**：producer 组装 messages 前，先 `MessageRepository.get_by_session` 取历史（含 role=tool 往返消息按持久化契约还原），复用 `compact_messages`（chat/compaction.py）按 token 预算裁剪，再交给 `run_loop`——run_loop 内部本就往 messages 上累积工具往返（agent.py:957-963），只需改初始输入。风险点：与自动记忆提取的重复注入、附件块位置、fork 消息的 tool_call_id 配对完整性。验收：多轮追问"继续刚才的修改"能引用上一轮工具结果。L4/L9/L13 均以 L1 为前提。
- **L2 真流式（P0）**：`LLMClient.chat_stream`（llm_client.py:388-468）扩展 stream tool_calls delta 聚合（OpenAI 兼容 `stream_options.include_usage`），run_loop THINKING 段改消费流、聚合完成再进 ACTING；不支持流式 tools 的 provider 回退现有非流式路径。删 fake 切块（legacy_routes.py:19-20、:2329-2344）。
- **L3 重试退避（P1）**：llm_client 请求层对 RATE_LIMITED/SERVER_ERROR/TIMEOUT/NETWORK 指数退避重试（≤3 次，尊重 retry-after）。注意幂等性与 interrupt 标志的交互。
- **L5 环境上下文（P1）**：`build_system_base` 追加 env 块（平台/日期/workspace 绑定路径 + git 分支与 porcelain 短状态，30s 超时 fail-safe）+ 技能名与一行描述清单（截断预算约 2k 字符）。复用 G1 git 工具的 subprocess 方式。
- **L14 收敛决策（先于继续开发）**：二选一——(a) 新逻辑一律落 legacy，hex 冻结新投入，稳定后评估切流（保守，推荐）；(b) 全力补齐 hex 并切默认（彻底，风险大）。不决策则每项后端差距都要做两遍。

## 2. UI 层差距（U）

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| U1 | **无 diff 视图 / 变更审查面板**：全库无 diff 组件，编辑结果只是折叠纯文本面板；无逐文件 accept/reject | Message.tsx:121-145；grep diff 组件零命中 | Cursor/Codex review changes、Qoder diff | **P0** |
| U2 | **checkpoint/rewind 零 UI**：G2 工具已交付，前端零消费 | grep `checkpoint\|rewind` src/electron 零命中 | ZCode rewind、Cursor checkpoints | P1 |
| U3 | **无 Git 集成 UI**：无变更文件列表/提交面板；`git_commit_message`（G9）已就绪无入口；worktreeIsolation 字段存在无开关 | entities/setting/types.ts:91 | Qoder SCM 面板 | P1 |
| U4 | **会话管理缺口**：无重命名；搜索框组件是死代码（SessionList.tsx 从未被引用）；置顶仅展示图标无操作 | SessionList.tsx:36-52；SortableSessionList 无搜索 | 三家均有 | P1 |
| U5 | **消息级操作**：无编辑重发（fork_session + `forked_at_message_id` 语义可复用）；流式中无消息排队（isLoading 直接拒绝发送） | ChatInput.tsx:229-230；useChat.ts:122 | 三家均有 | P1 |
| U6 | **无 OS 通知**：无 native Notification/声音/闪烁。审批 300s 超时 default-deny——用户离开窗口 = 审批必然失败 | permission_gate.py:42、:181-201 | 三家桌面端均有 | P1 |
| U7 | **渲染增强缺失**：无 LaTeX（remark-math+katex）、无 Mermaid；bash 输出无 ANSI 终端样式（普通 `<pre>`） | Message.tsx:121-145、package.json | 主流均渲染 | P2 |
| U8 | **模型切换 UI**：G5 后端已交付（GET/PUT `/sessions/{id}/model`），缺输入区/头部 provider+model 选择器 | 原文档 G5"设置页属前端里程碑" | 三家均有 | P1 |
| U9 | **设置缺口**：hooks 无配置 UI（settings `hooks` JSON schema 明确，CRUD 即可）；G6 图片输入后端已交付，缺上传/粘贴接线 | hooks/config.py:99-114 | Claude Code hooks | P2 |
| U10 | **i18n 半成品**：zh/en 双字典齐备，但无切换入口、locale 不持久化、大量组件硬编码中文 | i18n/index.tsx 仅定义处 | — | P2 |
| U11 | **长列表无虚拟化**：MessageList 全量 map；`VirtualSessionList.tsx` 是死代码；@tanstack/react-virtual 已在依赖 | MessageList.tsx:34-45 | — | P2 |
| U12 | **桌面壳缺口**：无托盘、无 OS 级全局快捷键、无 `sage://` 协议、无多窗口；second-instance 直接退出不聚焦已有窗口 | main.ts:111-124 | Codex 桌面端 | P3 |
| U13 | **剪贴板粘贴图片缺失**：拖放/按钮上传已有，无 onPaste 处理（G6 后端已收 images，接上即通） | InputCard.tsx:188-197、useFileUpload.ts | 三家均有 | P1（小改动高感知） |
| U14 | **无会话级 token/成本显示**：仅设置页全局 UsagePanel | UsagePanel.tsx:43-105 | Claude Code /cost | P2（依赖 L8） |

### 2.1 重点项路径勘察

- **U1 diff 视图（P0）**：RightPanel（现有 Progress/Artifacts 抽屉）加"变更"页——消费 `git_status` 列出会话改动文件、`git_diff` 按文件渲染；编辑类工具卡片内嵌 diff 用 ShikiCodeBlock 既有 `diff` 语言支持（ShikiCodeBlock.tsx:38）；"还原此文件"按钮联动 `checkpoint_restore` + 审批门禁。纯前端 + 第一轮既有工具，无后端改动。
- **U6 OS 通知（P1）**：渲染端在 `permission_request` / `done` / `task_status` 事件处经 preload 调主进程 Notification；Electron 侧加托盘可选。核心场景：审批等待与长任务完成时用户不在窗口前。
- **U5 编辑重发（P1）**：复用 `fork_session(session_id, forked_at_message_id)`（session_repo.py:263-355）——编辑 = fork 前缀 + 新 user 消息 + 跳转新会话；消息排队 = isLoading 时入队，流结束后自动发送。
- **U2/U3（P1）**：发送前自动 `checkpoint_create`（GeneralTab 加开关）+ 消息卡片"回滚到此消息前"；Git 页 = 变更列表 + `git_commit_message` 素材按钮 + `git_commit` 提交（走既有 INTERACTIVE 审批）。

## 3. 功能点差距（F）

| # | 差距 | 现状与证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| F1 | Plan UI 产品化 | G3 后端（plan_write）已交付，缺计划视图/审批 UI —— 并入 U 系前端里程碑 | Qoder Quest | P1 |
| F2 | 语义索引 embedding 版 | G4 已交付务实版（symbol_search）；embedding 版（wiki hnsw 可复用）留待实证需求 | Qoder Context Engine | P3 |
| F3 | 浏览器自动化 | G7 唯一遗留项，需 Electron CDP/playwright 桥 | ZCode browser-use | P3（跨端里程碑） |
| F4 | IDE 桥接（VS Code 扩展） | extension/ 仅 wiki-clipper；可先用 `sage://` 深链（U12）起步传选区/文件上下文 | Claude Code VS Code 桥 | P3 |
| F5 | 花费限额/预算 | usage_tracker 无上限控制；preferences 加 spend_limit + 超限拦截 | Claude Code/企业场景 | P2（小） |
| F6 | 用户级规则文件 | project_context.py 仅从工作区向上发现 SAGE.md/CLAUDE.md，无 `~/.sage/SAGE.md` 全局层 | Claude Code 分层 memory | P2（小） |
| F7 | CLI 聊天入口 | cli/ 仅 doctor/skills；GUI-first 定位下优先级低 | Claude Code CLI 即本体 | P3 |
| F8 | 自定义 slash 命令 | SKILL.md 已动态合并进斜杠菜单（ChatInput.tsx:128-141），基本覆盖 | — | 无差距 |
| F9 | 子代理并发度可配置 | dispatch_subagents 并发信号量硬编码 4 | — | P3（小） |

## 4. 建议实施批次

- **批次 A（P0，会话语义正确性）**：L1 历史接线 → L2 真流式（L1 是 L4/L9/L13 的前提）；U1 diff 视图可并行（纯前端 + 既有 git 工具）。
- **批次 B（P1，可靠性 + 闭环收尾）**：L3 重试、L5 环境上下文、L7 循环守卫；U13 粘贴图片、U8 模型选择器（收尾 G5）、U6 通知、U5 消息操作、U4 会话管理、U2 checkpoint UI、U3 Git 面板（收尾 G9）、F1 Plan UI（收尾 G3）。
- **批次 C（P2）**：L8+U14 用量落库与会话成本、L6 并行工具、L9 压缩接线、L10 MCP 传输扩展、L11 hooks 扩点、L12 中断粒度、L13 记忆注入、U7/U9/U10/U11、F5/F6。
- **待决策**：L14 双路径收敛（建议新逻辑一律先落 legacy，hex 冻结新投入）；决策前批次 A/C 的后端项只在 legacy 实施。
- **P3 / backlog**：U12 桌面壳、F3（=G7）、F4、F7、F9、F2 embedding 版。
- **win7 对齐**：沿用第一轮 §4 惯例（main 落地后 cherry-pick `release/win7`）；L1/L2/L3 等后端项注意 py3.8 兼容纪律（禁 PEP 604/585）。

## 5. 证据来源说明

- 前端勘察：src/ 全量 + electron/（19 项逐条核查，含死代码甄别）。
- 后端勘察：core/legacy/agent.py、api/legacy_routes.py、llm_client.py、chat/compaction.py、application/services/、mcp/、hooks/、data/、services/usage_tracker.py。
- 在途工作确认：第一轮 Phase-2 交付物与工作区状态一致（G5/G8/G9 相关文件）。
