# 编码代理对标差距分析·第五轮：信任闭环还账（2026-09-08）

- **状态**：批次 A 全部交付 ✅（main 分支 `feat/parity-r5-batch-a`，基线 `aa8ec52d` = origin/main；b084ea82 方案 / e8fc17bb U2' / 08f8e6c8 U4' / f9cc278b U5'+B1 / 0e2b58f9 U7' / 890dd733 lint）
- **本地验证记录**：tsc --noEmit 零错误；改动面 eslint 清洁；vitest 全量 1699 passed（13 失败均在基线 stash 复核为既有 Windows electron 日志/路径类，与本批无关——本批 electron 仅 commands.ts 纯新增）；后端 api 96 passed；session/checkpoint/workspace 单测 66 passed（1 个 Windows symlink 语义失败为既有）；integration 的 repl/office/wiki/skill 失败与 orchestration_stream 挂起均逐一在 aa8ec52d 基线复现，非本批引入（CI Linux 为准）
- **上游文档**：[2026-09-07_coding-agent-parity-round4.md](./2026-09-07_coding-agent-parity-round4.md)（第四轮：批次 A/B/C/D/E 已交付，剩余项归入其"批次 F"）、[2026-09-06_coding-agent-parity-round3.md](./2026-09-06_coding-agent-parity-round3.md)（批次 D 交付，E/F 部分脱落）、[2026-09-06_coding-agent-parity-round2.md](./2026-09-06_coding-agent-parity-round2.md)（全交付，但 U2/U4/U5 存在名义交付与实际范围出入）——本文不重复已交付项
- **对标对象**：Claude Code 2.0（checkpoints/一键 rewind）、Cursor（checkpoints、消息编辑重发）、ChatGPT / Claude.ai（消息编辑交互）、主流聊天 UI（Mermaid 渲染标配）
- **编号约定**：延续 L / U / F 编号；带 `'` 的为历史编号的"补交付"（此前批次清单脱落或范围缩水）
- **方法**：基于 origin/main（aa8ec52d）全量 grep 复核四轮之后的前端消费面，清查历轮"清单有、代码无"的脱落项；每项附 file:line 证据

## 0. 结论速览

四轮之后，工具面、会话语义、成本记账、信任感 UI 已不落后于主流。本轮盘点发现的问题是**交付连续性**：部分早期 P1 项在批次重组中脱落，至今零代码：

1. **U2 checkpoint UI 脱落至今**：`checkpoint_create/list/restore` 三工具 2026-09-06（第一轮 G2）交付，但 `src/` 全目录 grep `checkpoint` **零命中**——第一轮已确诊"前端零消费"，round2 批次 B、round3 批次 D 两次列入清点，均未实施。Claude Code 2.0 / Cursor 的标志性安全网在 Sage 只能靠 LLM 自主调工具。
2. **U4 会话管理只交付一半**：消息排队/置顶/fork/导出已交付；重命名无 UI（后端 `PATCH /sessions/{id}` 早已存在，`electron/commands.ts` 无路由、`sessionApi` 无方法）；侧栏搜索组件（`SessionList.tsx:24-31`）是死代码。
3. **U5 消息编辑重发未做**：只有 fork 入口（复制到消息为止、跳转新会话），无"编辑此消息并重发"——ChatGPT/Claude.ai/Cursor 标配交互。且实施勘察发现 **`fork_session` 不复制工作区绑定**（`session_workspace_bindings` 无 fork 处理，`backend/office/session_workspace.py` 无相关函数）：现有 fork 功能本身存在"分叉后丢失工作区"缺陷，本批顺带修复。
4. **U7 Mermaid 渲染**：round4 明确"需引入 ~1MB 渲染依赖，单独评审"。本批给出评审结论（主流 AI 聊天 UI 标配；架构图/流程图是编码场景高频产物；动态 import 不进主包）并实施。
5. **消息全文搜索从未入清单**（新编号 F12）：会话多了之后"哪个会话改过 X"无法检索；messages 表无 FTS 索引。→ 归入本批批次 B。

## 1. 差距矩阵（本轮范围）

| # | 差距 | 证据（origin/main 复核） | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| U2' | **checkpoint/rewind 零 UI**：工具已交付（`backend/tools/checkpoint_tool.py`），无 REST、无前端消费 | `git grep -il checkpoint origin/main -- src/` 零命中 | Claude Code 2.0 checkpoints、Cursor rewind | **P0** |
| U4' | **会话重命名 + 侧栏搜索**：PATCH 路由后端已有（`legacy_routes.py:598`，`SessionUpdate{title?}`）但 electron 桥/API/UI 三层全缺；侧栏无搜索框 | `electron/commands.ts` 无 session PATCH 路由；`SessionList.tsx` 死代码 | 三家均有 | **P1** |
| U5' | **消息编辑重发**：Message 操作栏仅 复制/评分/fork（`Message.tsx:393-431`） | fork 语义 `session_repo.py:320`（复制 at_message_id 及之前，单事务原子） | ChatGPT/Claude.ai 编辑重发、Cursor restore-and-edit | **P1** |
| B1 | **fork 不继承工作区绑定**（U5' 前置缺陷修复） | `session_workspace.py` 无 fork 函数；`session_repo.py:320` fork_session 不触 binding 表 | — | **P1（随 U5'）** |
| U7' | **Mermaid 不渲染**（代码块按普通高亮处理，用户看到的是源码） | `Message.tsx:285-306` code 映射直达 ShikiCodeBlock；package.json 无 mermaid | 主流 AI 聊天 UI 标配 | **P2** |
| F12 | **消息全文搜索**：无端点、无 UI | `GET /sessions` 无 q 参数；messages 无 FTS | Claude Code 历史检索 | P2 → 批次 B |

## 2. 批次规划

| 批次 | 主题 | 内容 | 状态 |
| --- | --- | --- | --- |
| **A** | 信任闭环还账（本批） | U2' checkpoint UI、U4' 重命名+搜索、U5'+B1 编辑重发（含 fork 继承绑定）、U7' Mermaid | 实施中 |
| **B** | 检索与自动化 | F12 消息全文搜索（端点+命令面板入口）、发送前自动快照（设置开关，producer 挂点）、U20 diff 视图增强、F11 docx/xlsx/pptx 产物预览（承 round4 批次 F） | 待排期 |

round4 批次 F 中的 L12 完整中断粒度、F2 语义索引不在本轮，维持 round4 排期结论。

## 2.1 批次 B 详细设计（2026-09-09 增补，本次实施）

> 基线：origin/main `07762ec9`（含 round6 #521）；分支 `feat/parity-r5-batch-b`。

### B-1 F12 消息全文搜索（P2，工作量 M）

**后端**（`backend/api/legacy_routes.py` 记忆 API 区旁新增，`@with_db_lock`）：
- `GET /search/messages?q=&session_id=&limit=`：q 长度 2-200（越界 422），limit 1-50 默认 20；LIKE 通配符转义（`%/_/\` + `ESCAPE ''`）；
- 仅搜 `role IN ('user','assistant')`（tool/system 行无检索价值）；JOIN sessions 取标题；`ORDER BY created_at DESC`（最新优先）；
- 响应 `{results: [{message_id, session_id, session_title, role, snippet, created_at}], has_more}`——取 limit+1 条探测 has_more，避免 COUNT 双查；snippet 为命中点前后 80 字符 excerpt。

**前端**：
- `sessionApi.searchMessages(q, opts?)` + `electron/commands.ts` `search_messages` GET 路由（q 进 query string）；
- **入口复用侧栏搜索框**（U4' 已交付）：输入 ≥2 字符时 debounce 300ms 异步搜消息，命中会话并入过滤列表（标题匹配优先、消息命中次之），SessionItem 显示 `💬N` 徽标，点击即跳会话；
- `/search` 斜杠命令保持 LLM 知识库搜索语义不变（`commandToPrompt` :187），消息检索入口收敛在侧栏，不做第二入口。

**测试**：`backend/tests/api/test_message_search_api.py`（跨会话命中/role 过滤/转义/session 过滤/limit 与 has_more/空 q 422）；ConversationsSection 消息命中并入 + SessionItem 徽标用例。

### B-2 发送前自动快照（P2，工作量 S-M）

**后端**：
- `settings_repo.KEYS` 白名单加 `"auto_checkpoint"`（`"1"/"0"` 字符串 KV，**默认关**——不改变既有行为，用户显式开启）；
- 抽独立函数 `_auto_checkpoint_if_enabled(session_id) -> Optional[str]`（settings 读 → `get_workspace_binding` → `CheckpointCreateTool(...).execute()`，任一步失败静默返回 None——与 S1/L11/F5 同款 fail-open）；producer 在运行态落库（:2013）之后挂调用，经 `run_in_executor` 包裹（zip 大工作区秒级耗时，不阻塞事件循环）；py3.8 纪律：`Optional[str]` 注解、无 to_thread。

**前端**：GeneralTab 新增"发送前自动快照"卡片——走后端 KV（get_preference/set_preference 既有通道），自管加载态；与 autoMemory 等 localStorage 开关并存（后端 producer 必须能读到该开关，故不走 localStorage）。

**测试**：`backend/tests/api/test_auto_checkpoint.py`（开启+绑定→产生快照 / 关闭→不产生 / 开启+未绑定→静默 None，SAGE_USER_DATA_DIR 隔离）；GeneralTab 开关读写用例。

## 3. 批次 A 详细设计（本次实施）

### 3.1 U2' checkpoint UI——一键快照 / 一键回滚（P0，工作量 L）

**原则**：用户主动触发的 restore 走**前端 confirm + REST 直接执行**（与 round4 U19 `POST /changes/revert` 同先例——用户意图明确的写操作不进 agent 审批门禁）；restore 语义"只覆盖不删除"须在 confirm 文案中明示。

**后端**（`backend/api/workspace_routes.py` 扩展，复用既有工具类实例化模式——参考 `:216` 直接调 `GitStatusTool`）：
- `GET /sessions/{id}/workspace/checkpoints` → `CheckpointListTool` → `{checkpoints: [{checkpoint_id, created_at, bytes, files}]}`；未绑定 403 `workspace_not_bound`（沿用 `_bound_workspace_or_raise`）。
- `POST /sessions/{id}/workspace/checkpoints` → `CheckpointCreateTool`（手动快照按钮）→ `{checkpoint_id, files, skipped, bytes}`。
- `POST /sessions/{id}/workspace/checkpoints/restore`，body `{checkpoint_id}` → `CheckpointRestoreTool`（WRITE_LOCAL 风险类，但 REST 路径以 confirm 代审批）→ `{checkpoint_id, restored}`；zip-slip/越界防护沿用工具内实现。
- 工具类签名适配：REST 侧构造带 `workspace_root` 的 `ToolPolicy`（与 GitStatusTool 同法）；返回统一 `detail={code,message}` 错误结构。

**前端**：
- `electron/commands.ts`：`workspace_list_checkpoints` / `workspace_create_checkpoint` / `workspace_restore_checkpoint` 三条路由。
- `workspaceApi.ts`：`listCheckpoints / createCheckpoint / restoreCheckpoint`（snake→camel 映射 + handleApiError）。
- `ChangesSection.tsx`：变更页头部加"检查点"折叠区——快照列表（时间/文件数/体积）+ 每行"恢复"按钮（confirm：列明覆盖语义）+ 头部"创建快照"按钮；恢复/创建后刷新变更清单与快照列表。
- i18n：`changes.checkpoint.*` 键组（zh/en 同步）。

**测试**：后端 `backend/tests/api/test_workspace_checkpoint_routes.py`（列表/创建/恢复往返、未绑定 403、checkpoint_id 非法 400）；前端 `ChangesSection` 检查点区交互用例（mock workspaceApi）。

### 3.2 U4' 会话管理收尾——重命名 + 侧栏搜索（P1，工作量 M）

- **重命名**：`electron/commands.ts` 加 `session_update`（PATCH `/api/v1/sessions/{id}`，body 仅透传 `{title}`）；`sessionApi.rename(sessionId, title)`；`SessionItem` 标题双击进入 inline 编辑（Enter 提交 / Esc 取消，沿用 hover 操作区风格加铅笔入口）；store 更新 `sessions` 数组原地替换（无新 action，复用现有 set 模式）。
- **侧栏搜索**：`ConversationsSection` 顶部加过滤输入框（纯前端 `title.toLowerCase().includes()`，复用死代码 `SessionList.tsx:24-31` 模式后删除死代码组件及其 barrel 导出）；过滤仅影响展示顺序，不影响 dnd 排序存储。
- **测试**：SessionItem 重命名交互 + ConversationsSection 过滤用例。

### 3.3 U5' 消息编辑重发 + B1 fork 继承工作区绑定（P1，工作量 M）

- **B1（前置）**：`fork_session`（`session_repo.py:320`）单事务内复制源会话的**活跃工作区绑定**（`session_workspace_bindings` 新行，`generation` 延续递增，`activated_at` 重新计时）；无绑定的源会话行为不变。顺带使现有 fork 功能获益。
- **交互**：`Message` 操作栏对 `role=user` 消息加"编辑重发"（`data-testid="edit-resend"`）→ 内容回填输入框 + 输入卡片顶部显示"正在编辑重发"提示条（Esc/关闭取消）→ 发送时：`sessionApi.fork(sessionId, 前一条消息id)`（fork 语义=复制该消息**及之前**，故传前一条 id；目标消息为首条时传 `undefined` 会全量复制，需后端 fork 支持"空前缀"——**实现取巧**：首条消息场景直接 fork 全量后无法去除末条，改为后端 `ForkSessionRequest.at_message_id` 支持显式空串语义？不引入：首条消息时复用 `POST /messages/{id}/delete` 于新会话副本上删除该条——零后端改动）→ 切换到 fork 会话 → `sendMessage(编辑后内容)`。原会话完整保留（透明可控哲学：不截断历史）。
- **流式保护**：`isLoading` 或目标消息之后已有工具往返时，编辑回填仍允许（改历史文案），但发送守卫复用现有排队/禁用逻辑。
- **测试**：Chat 编辑重发流程用例（mock sessionApi.fork + sendMessage）；fork 继承绑定的后端单测（有/无绑定两分支）。

### 3.4 U7' Mermaid 渲染（P2，工作量 M；依赖评审结论见 §5）

- 新增 `src/widgets/chat/MermaidBlock.tsx`：`lang === 'mermaid'` 的代码块渲染为 SVG；`import('mermaid')` 动态加载（不进主包，code-split）；主题跟随 ThemeProvider（dark/light）；渲染失败（语法错误）回退 `ShikiCodeBlock` 原样展示源码 + 错误提示。
- `Message.tsx` `components.code` 加 mermaid 分支（`:285` 处）。
- **测试**：MermaidBlock mock mermaid 模块的渲染/失败回退用例。

## 4. 双分支纪律（main ↔ release/win7）

1. **方向唯一**：main 落地且验证绿 → `cherry-win7-parity-r5` 分支逐提交 cherry-pick → 冲突手工适配 → win7 侧相关测试绿。本轮 main 基线 = origin/main `aa8ec52d`。
2. **py3.8 纪律**（后端改动均为 cherry-pick 零成本前提）：禁 PEP 604（`X | None`）/PEP 585（内建泛型标注）——本批后端新增签名一律 `Optional[X]` / `List[Dict[str, Any]]` 风格；禁 `zip(strict=)`（#487 实证踩坑）。
3. **前端 / electron 桥两分支同构**（Electron 均 ^21.4.4）：本批前端改动无分支差异面；`mermaid` 依赖为纯前端 npm 包，win7 线 Electron 21 Chromium 108 可运行（mermaid 11 产物为 ES2020 兼容，vite 构建目标跟随项目现有 browserswitch）。
4. **每项独立 commit**（U2' / U4' / U5'+B1 / U7' 各一个），可单独 revert；win7 冲突无法干净 cherry-pick 时等价重写、验收口径一致。

## 5. Mermaid 依赖评审（round4 遗留决策，本批落结论）

- **结论：引入 `mermaid@^11`**。理由：① 流程图/时序图/架构图是编码代理输出的高频产物，Cursor/Claude（claude.ai）/ChatGPT 均默认渲染，属"标配体验"而非锦上添花；② 动态 `import()` 使其独立 chunk，不打开含 mermaid 图的会话不加载，主包体积零增长；③ mermaid 11 产物 ES2020 兼容 Electron 21 Chromium 108，win7 线无额外约束。
- **风险与缓解**：渲染死循环/超大图 → `mermaid.initialize({ startOnLoad: false, maxTextSize: 50000, maxEdges: 500 })` + 渲染失败回退源码展示；XSS → mermaid 自带 `securityLevel: 'strict'`（默认）。

## 6. 验收标准

| 项 | 验收 |
| --- | --- |
| U2' | Changes 面板可创建快照、可查看快照列表（时间/文件数/体积）、可一键恢复（confirm 明示"覆盖不删除"）；恢复后变更清单刷新；未绑定工作区不显示检查点区 |
| U4' | 侧栏会话可双击标题重命名（Enter/Esc）；顶部搜索框即时过滤会话列表；重命名后侧栏/聊天头部同步 |
| U5' | user 消息操作栏"编辑重发"→ 回填输入框 → 发送后跳转到 fork 会话且新消息为编辑后内容，原会话保留；fork 会话继承源会话工作区绑定 |
| U7' | 含 ```mermaid 代码块的消息渲染为图表；语法错误回退源码；dark/light 主题正确 |
| 回归 | `vitest run`、`tsc --noEmit`、`eslint`、本批相关 `pytest` 全绿；主包体积无显著增长（mermaid 独立 chunk） |


## 2.3 批次 D 详细设计（2026-09-09 增补，本次实施）

> 基线：origin/main `6b8e66e0`；分支 `feat/parity-r5-batch-d`。主题：**可靠性兜底 + 代理 git 能力补全 + 测试失败感知**（源自首轮对标报告的 fallback model / git 扩面 / 测试感知三项，避开 #547 Office 专项）。

### D-1 fallback model（P2，工作量 M）

主模型重试耗尽（L3 的 429/5xx/超时/网络类错误，attempts 默认 3）后整体失败，长任务因单点抖动报废。对标 Claude Code `fallbackModel`。

- `LLMConfig` 加 `fallback_model: Optional[str] = None`（同 endpoint 换 model，v1 不做跨 endpoint）；
- `llm_client.chat()` 与 `chat_stream_events()` 的重试耗尽点（:468/:752）：耗尽且错误可重试、`fallback_model` 非空且 != 主 model、且本次会话未用过 fallback → 记 warning、`dataclasses.replace(config, model=fallback)` 重置 attempt 再入循环（每实例至多一次，`_fallback_used` 守卫）；流式沿用 `nothing_yielded` 重放安全判据；
- 偏好 `fallback_model`（KV 白名单）+ producer 读取注入 `llm_config` dict；GeneralTab 模型区加输入框（同 SpendLimitInput 模式）。

**测试**：`test_llm_client_errors.py` 模式——mock httpx 连续 429，无 fallback 抛 LLMError；配 fallback 后第二轮以 fallback model 成功；fallback 只触发一次；流式同口径。

### D-2 git 工具扩面：branch / checkout / stash（P2，工作量 M）

现有四工具只有 status/diff/log/commit——agent 无法结构化地建分支、切分支、暂存现场（多任务并行/实验分支场景硬需求）。

- `git_branch`（READ）：列本地分支（含当前分支标记）→ `{branches:[{name, is_current}]}`；
- `git_checkout`（WRITE_LOCAL）：`{branch, create?: bool}`——create 走 `-b`；脏工作区冲突由 git 报错透传；
- `git_stash`（WRITE_LOCAL）：`{action: "list"|"push"|"pop", message?: str}`——list 出 `{stashes:[{index, message}]}`；push 支持可选 -m；
- **ref 名校验**（首个 ref 输入面，新纯函数 `_valid_ref`）：`^[A-Za-z0-9._/\-]{1,200}$` 且不以 `-` 开头、不含 `..`——防选项注入与路径穿越；
- 注册链：tool_names `GIT_TOOLS` + `tools/__init__.py` import/register + profiles `*GIT_TOOLS` 自动带上 + `__all__`。

**测试**：`test_git_tool.py` 照既有 repo fixture 分节新增（列分支/创建切换/stash push-pop 往返/ref 校验拒绝/非仓库优雅失败）；`test_tool_names.py` 注册面对齐自动覆盖。

### D-3 测试失败感知（P2，工作量 M）

bash 跑测试非零退出时，LLM 只能从 30KiB 截断文本里自己找失败清单——新纯函数把 pytest/vitest 失败解析成结构化数据回喂。

- 新模块 `backend/tools/test_output_parser.py`：`parse_test_failures(stdout, stderr) -> Optional[Dict]`——pytest（`FAILED path::test` 行 + `N failed, M passed` 汇总）、vitest/jest（`FAIL path` + `✗/×` 用例行 + `Tests: N failed` 汇总）；只扫末尾 200 行；无命中返回 None；
- bash_tool 挂点：`_run_foreground` 读输出后解析，命中且 exit_code != 0 → `content["test_failures"] = {...}`（`_decorate` 同款派生字段形态，非零退出本就 success=True 语义不变）。

**测试**：新 `test_output_parser.py`——pytest 样例、vitest 样例、混合噪声、无匹配 None、超长输出只扫尾部。

## 2.4 批次 E 详细设计（2026-09-10 增补，本次实施）

> 基线：origin/main `0e46f6f9`；分支 `feat/parity-r5-batch-e`。主题：**桌面壳收尾 + F2 语义索引 v1**（避开 #547 Office 专项与 round6 领域）。

### E-1 `sage://` 深链（P2，工作量 S-M）

- main.ts：`app.setAsDefaultProtocolClient("sage")`（vitest guard 同 requestSingleInstanceLock 模式）；macOS `open-url` 事件 + Windows 经 second-instance argv 消费；
- 新纯函数 `parseSageDeepLink(argv: string[]): { sessionId: string } | null`（解析 `sage://chat?session=<id>`，非法/无参返回 null）+ 单测；
- 命中后 show 窗口并复用既有 `sage:event:session-notify-click` 通道 → `App.sessionDeeplink` 桥已有 navigate(`/chat?session=`) 消费端，零前端改动。

### E-2 关闭入托盘（P2，工作量 S；U12 收尾，推翻 tray.ts 头注约定）

- 主进程 JSON 文件先例（demo mode）：`<userData>/sage-close-to-tray.json` + IPC `sage:close-to-tray:get/set`；
- GeneralTab 新 Toggle（invoke 直连主进程）；close 事件拦截：enabled 且 !appIsQuitting → `e.preventDefault(); win.hide()`；托盘「显示/退出」菜单已可恢复。

### E-3 F2 工作区语义索引 v1（P2，工作量 L）

- 新工具 `codebase_search(query)`（READ）：增量索引工作区源文件 → embedding 余弦 top-k → `{results:[{path, start_line, snippet}]}`；
- 存储：**sqlite3 + numpy 余弦**（`~/.sage/workspace-index/<workspace-sha1>/index.sqlite3`）——纯 wheel 依赖（numpy 已有），规避 hnswlib 无 py38 wheel / sqlite-vec 打包风险；v1 块数上限 50k；
- embedding：复用 wiki `build_embed_request/parse_embed_response`（OpenAI 兼容），配置取 `app_settings.modelSelections.embeddingModel`（新增 `load_embedding_config()`）；未配置 embedding → 工具报错引导设置；
- 增量：源文件 mtime+size 缓存于索引库，只重嵌变化文件；枚举复用 EXCLUDED_DIRS 剪枝 + 源码扩展名白名单；分块按 40 行滑窗；
- 索引构建同步执行（工具自身就是显式调用，首问全量索引属预期行为），单文件 256KB 读取上限。

**测试**：deep link 解析单测；close-to-tray IPC 单测；workspace_index 枚举/分块/余弦检索/增量单测（embedding 用假向量函数注入，不发网络）。

## 2.5 批次 F 详细设计（2026-09-10 增补，本次实施）

> 基线：origin/main `c53c1b64`（含并行会话的 round7 批次 A）；分支 `feat-parity-r5-batch-f`。主题：**编辑成功率与代码理解补强**。

### F-1 edit_file 行级容错匹配（P1，工作量 M）

`old_string` 逐字符精确匹配是编辑失败的最大来源——模型给的片段常带缩进/行尾差异，一次失败即浪费一整轮 LLM。精确匹配 0 命中时新增**行级 trim 容错**兜底：

- `_resolve_fuzzy_range`：文件行与 old_string 行各自 strip 后做连续窗口匹配；命中恰好 1 处 → 定位字符区间（`splitlines(keepends=True)` 累加偏移，保留 CRLF/其余原文不动）；0 处或多处 → 维持原错误语义；
- 替换块行尾跟随文件风格（文件含 CRLF 且 new_string 无 → 归一为 CRLF）；
- `replace_all` 不走容错（语义复杂）；响应 content 加 `fuzzy_matched: true` 供诊断。

**测试**：缩进差异命中、CRLF 保留、多处 fuzzy 拒绝、精确匹配优先、new_string 行尾归一。

### F-2 JSON 写后语法校验（P2，工作量 S）

`write_diagnostics.attach_diagnostics` 现仅覆盖 Python AST。`.json` 写入后加 `json.loads` 校验（stdlib 零依赖），语法错误随工具结果回喂。
**测试**：合法/非法 JSON 各一。

### F-3 symbol_search 扩展 JS/TS（P2，工作量 M）

`symbol_search` 现仅 Python AST。v1 加 JS/TS/JSX/TSX 的正则级定义提取（`function name(`、`class name`、`const name = (`/`= =>`、`interface/type name`），与 Python 符号合并入既有倒排索引；非 Python 文件不走 AST。
**测试**：TS/JS 样例文件的符号发现与查询命中。