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
