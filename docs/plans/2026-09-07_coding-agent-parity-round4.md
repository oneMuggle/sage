# 编码代理对标差距分析·第四轮：架构收口 / 信任感 UI / 差异化闭环（2026-09-07）

- **状态**：批次 B 实施中（worktree `.worktrees/feat-parity-r4`，分支 `feat/parity-r4`，基线 7700442a）
- **上游文档**：[2026-09-06_coding-agent-parity.md](./2026-09-06_coding-agent-parity.md)（第一轮 G1-G10，全交付）、第二轮 L/U/F（批次 A/B/C 全交付，round2 文档在主工作区未入库）、[2026-09-06_coding-agent-parity-round3.md](./2026-09-06_coding-agent-parity-round3.md)（批次 D 已实施；批次 E/F 未启动）——本文不重复已交付项，只记录第四轮盘点结论与新批次规划
- **对标对象**：Claude Code / Codex（CLI 编码代理）、Cursor / Qoder（Agentic IDE）、Cline / WorkBuddy（agent 客户端 / 交付物导向）
- **编号约定**：延续 L / U / F 编号顺延（本轮新增 U19、U20）；会话维度沿用 S 系
- **方法**：前三轮交付后全量盘点——工具面、会话语义、成本记账已不落后，本轮聚焦"收口"：架构双路径收口（L14）、差异化功能收口（F11）、信任感收口（U17/U19/S8）

## 0. 结论速览

三轮 parity 之后，Sage 不缺工具和功能广度，缺的是三类"收口"：

1. **架构收口（L14）**：legacy 与 hex API_MODE 双 agent 路径并存，每次功能都要双写或漂移（`web_tool.py` 的 main/win7 分支漂移是已确诊症状）。这是所有后端新项的隐性税，必须先做收敛决策。
2. **信任感收口（U17/U19/S8）**：主流产品（Claude Code 上下文百分比、Cursor/Copilot 行级 diff accept/reject、各家任务完成通知）给用户的"一切尽在掌握"感，Sage 目前是盲区——上下文用量不可见、变更只能整体看不能按 hunk 撤、后台会话跑完无感知。本轮批次 B 一次补齐。
3. **差异化收口（F11/F2/F10）**：押注"桌面 agent 工作台"的三个方向各自差最后一公里——office 生成后不能内嵌预览、symbol_search 有 AST 检索但无语义索引、review lane 有编排但无日常轻入口。差异化功能自己不闭环等于没有。

**勘误**：第二轮文档所列 U6（OS 通知）实际未落地——`electron/main.ts` 无 `new Notification` 调用、preload 无通知通道、renderer 无触发点（本轮 grep 复核零命中）。本轮以 S8（分会话 OS 通知）名义一次做对，不再单列 U6。

## 1. 前置决策：L14 双路径收敛（建议，需评审拍板）

**建议决策**：hex（`backend/adapters|application|domain`）定为唯一演进主路径，legacy（`backend/core/legacy/` + `api/legacy_routes.py` 聊天主链路）**冻结**——只修 P0 级 bug，不再新增能力；新功能一律落 hex 或独立 service 模块。设过渡期：待 hex 聊天主链路（run_loop 等价物 + 流注册 + 权限门）功能等价清单核对完成后，legacy 聊天路径转 deprecated。

**理由**：
- 第三轮 L15 的实施经验（`secret_box.py` 独立 service 模块，legacy/hex 全覆盖）证明"独立模块 + 单咽喉接入点"可以规避双写，但聊天主链路内的功能（如本轮的 L9 窗口记账、U17 上下文透出）仍只能在 legacy 内做，hex 侧持续漂移。
- `web_tool.py` main/win7 双分支漂移 + round3 勘误记录的 L4 脱落，都是双路径 + 双 git 分支四维矩阵的必然成本。

**本批次影响**：批次 B 三项均为独立 service/前端改动，不触碰聊天主链路核心，不受 L14 决策阻塞；L16（批次 A）实施前必须先落此决策。

## 2. 批次规划（第四轮总览）

| 批次 | 主题 | 内容 | 优先级 |
| --- | --- | --- | --- |
| **A** | 可靠性（**本日收口**） | L14 收敛决策（§1，待评审）、L16 前端恢复横幅（后端启动恢复已在 main）、W 系渲染降级（核查已在 main） | P0 |
| **B** | 信任感 UI（**已交付**，commit 3c2ec5b4） | U17 ContextMeter 上下文用量指示、U19 逐文件/逐 hunk 变更撤销、S8 分会话 OS 通知 | P0 |
| **C** | 工作流（**L4' 已交付**） | L4' prompt 前缀稳定化（环境/记忆移尾 ✅）、F1 PlanDrawer（**勘误：PlanCard+todos 链路已大半覆盖**）、L12 完整中断粒度（→批次 F） | P1 |
| **D** | 差异化闭环（**F10/F11-PDF 已交付**） | F10 /review 轻入口（grep 版 ✅）、F11 产物内嵌预览（PDF ✅；docx/xlsx/pptx 需后端转换 →批次 F）、F2 语义索引（→批次 F） | P1 |
| **E** | 打磨（**U18/U12-MVP 已交付；U10 勘误已交付**） | U18 快捷键帮助层（`?` 覆盖层 ✅）、U12 桌面壳（托盘 + Alt+Shift+S 唤起 ✅，关闭行为未改）、U7 Mermaid（需引入 mermaid 依赖，单独评审）/ANSI（→批次 F）、U20 diff 视图增强（随 U19 后续迭代） | P2 |

依赖关系：批次 A 的 L16 依赖 L14 决策；批次 C 的 L4' 依赖 L1（已交付）；批次 D 的 F10 语义版依赖 F2。批次 B 无前置依赖，先行实施。

**批次 A 实施期勘误（2026-09-07）**：核查发现 L16 的后端部分（`SessionRepository.recover_stale_run_states`，`backend/main.py:262` lifespan 启动时调用）与 W 系渲染降级（`backend/tools/web_render.py`，W1/W2 已接入 `web_tool.py`）**均已在 main 交付**——round3 文档的"未做"清单过时。批次 A 剩余缺口只有 L16 的前端体验层：用户打开被标记 `failed`（"应用重启，运行中断"）的会话时无任何恢复入口。已补：`InterruptedRunBanner` 横幅（识别该终态 → 重发最后一条 user 消息 / 忽略）。L14 执行决策仍待评审拍板，不阻塞其余批次。

**批次 C/D/E 实施期勘误（2026-09-07，同日第二轮核查）**：
- **U10 i18n**：GeneralTab 已有"语言 / Language"切换（`LanguageSwitcher`，useI18n.setLocale + localStorage 持久化）——round3 的"半成品"描述过时，非差距。
- **F1 PlanDrawer**：`components/PlanCard`（编排计划可编辑/确认/锁定）+ `todo_snapshot` → Progress 任务板已覆盖"计划→执行打钩"主链路；Qoder Quest 式"计划持久化为工件、跨会话引用"的增量暂缓，避免重复建设。
- **F11**：`ArtifactViewer` 已支持 image/code/json/csv；本批补 PDF（base64 data URL + iframe 内嵌 Chromium PDF viewer，`detect_artifact_kind` 增 `.pdf`，20MB 上限，历史 text-kind PDF 后缀兜底）。docx/xlsx/pptx 二进制渲染需后端转换端点，归入批次 F。
- **U12 范围收敛**：托盘（显示/退出菜单 + 点击唤起）+ 全局快捷键 Alt+Shift+S toggle 窗口已交付；刻意不做"关闭即隐藏到托盘"（不改变用户预期，后续批次评审）。
- **归入批次 F（后续排期）**：L12 完整工具级中断、F2 语义索引（依赖 rag-service 复用评估）、docx/xlsx/pptx 产物预览、U7 Mermaid/ANSI 渲染（Mermaid 需引入 ~1MB 渲染依赖，单独评审）。

## 3. 批次 B 详细设计（本次实施）

### 3.1 U17 ContextMeter——上下文用量指示（P0，工作量 M）

**问题**：全 UI 无上下文窗口用量指示；长会话中用户对"何时失忆/何时压缩"零预期。L9-lite 的前端 `max_context` 上报通道已预留但前端从未发送。

**后端**（`usage_tracker.py` + `api/usage_routes.py`）：
- `UsageTracker.last_request(session_id)`：查 `usage_events` 该会话最新一行的 `model / prompt_tokens / cached_tokens / created_at`。上一轮请求的 `prompt_tokens` 是"当前上下文占用"的最佳可得代理（本轮请求 = 历史 + system + 新消息，恰好等于下一轮开始前的上下文基线）。
- `GET /api/v1/usage/session/{id}` 响应追加 `last_model / last_prompt_tokens / last_cached_tokens / last_at` 字段（缺数据时为 null），无新端点。

**前端**：
- 新增 `src/shared/lib/modelWindows.ts`：主流模型上下文窗口映射表（claude-sonnet/opus 200k、gpt-4o/4.1 128k、o3 200k、deepseek 128k、gemini-2.5-pro 1M 等），最长前缀匹配，未知模型默认 128k——与 `PRICING_PER_MILLION_TOKENS` 同构。
- 新增 `src/widgets/chat/ContextMeter.tsx`：紧凑横条 + 百分比 + tooltip（已用/窗口/缓存命中）；配色阈值 <70% 绿、70-90% 黄、≥90% 红；数据源复用 `fetchSessionUsage`；流结束时自动刷新（订阅 `useChatStreamStore` 该会话 `streaming.messageId` 非空 → 空的跳变）+ 60s 兜底轮询。
- 挂载 `src/pages/Chat.tsx` 头部，紧邻 `SessionUsageBadge`。
- 聊天流请求体透传 `max_context = contextWindowFor(model) * 0.75`（激活 L9-lite 已预留的后端预算通道，预留 25% 给回复与工具 schema）。**行为影响评估**：默认历史预算为 `max(compact阈值×3, 18000)` ≈ 18k，推导值（如 200k 窗口 → 150k）看似放大 8 倍，但 M4 自动压缩在估算 token ≥ 6000 且消息数 ≥ 12 时先行触发，预算只是压缩失效时的兜底上限，实际每轮成本变化有限；用户在设置中显式配置 ≥20000 的 maxContext 时优先用户值。

### 3.2 U19 逐文件 / 逐 hunk 变更撤销（P0，工作量 L）

**问题**：Changes 面板只读；用户对 agent 的改动只有"整体接受"或"checkpoint 整体回滚"两个粒度，无法"留下文件 A 的修改、只撤文件 B 的第三块 hunk"。Cursor/Copilot 的行级 accept/reject 是信任感的核心来源。

**后端**（新模块 `backend/office/workspace_revert.py` + `api/workspace_routes.py` 两端点）：
- `POST /sessions/{id}/workspace/changes/revert`，body `{paths: string[], delete_untracked?: bool}`：受跟踪文件 `git checkout -- <path>`（仅工作区，不动 index）；未跟踪文件需显式 `delete_untracked=true` 才删。路径必须位于 workspace 内（防逃逸，复用 `_bound_workspace_or_raise`）。
- `POST /sessions/{id}/workspace/changes/revert-hunks`，body `{path: string, hunk_indices: number[]}`：对该 path 取 `git diff -- <path>` 全量 unified diff → 按 `@@` 切 hunk → 取所选 hunk 重建补丁（保留文件头）→ `git apply --reverse`。hunk 相互独立且工作区内容与 diff 基线一致，反向应用子集是安全的；任一 hunk 应用失败即整体失败不动盘（git apply 原子性）。
- 纯函数（diff 切分 / 补丁重建）与 git 执行分离，pytest 覆盖切分与重建；端点集成测试覆盖 revert 成功 / 未绑定 403 / 路径逃逸 400。

**前端**（`ChangesSection.tsx`）：
- 文件清单每行加"撤销"按钮（confirm 后调用 revert）。
- diff 视图前端解析 unified diff 成 hunk 块，每块可勾选；"撤销所选 hunk"按钮调用 revert-hunks 后刷新。复用既有 `ShikiCodeBlock`（diff 语言）逐 hunk 渲染。
- 撤销后自动 refresh 变更清单；工作区无绑定 / git 失败沿用既有错误文案通道。

### 3.3 S8 分会话 OS 通知（P0，工作量 M）

**问题**：S1-S7/S9 多会话并行已交付，但后台会话跑完/失败/等审批时用户无感知（窗口失焦或停留在别的会话时）。且第二轮 U6 名义交付、实际零代码（见 §0 勘误）。

**Electron main**（`electron/main.ts`）：
- `ipcMain.handle('sage:session:notify', ...)`：`Notification.isSupported()` 守卫 → 展示系统通知（title=会话标题，body=状态摘要）；`click` 事件 → `mainWindow.show()/focus()` + `webContents.send('sage:session:notify:click', {sessionId})`。
- 通知去抖：同一 sessionId 3s 内只发一条。

**preload + 类型**（`electron/preload.ts` + `src/shared/types/electron-api.d.ts`）：暴露 `notifySession(payload)` 与 `onSessionNotifyClick(handler)`（browser 环境降级 no-op，沿用 desktopInvoke 判定模式）。

**Renderer**（`src/features/send-message/useChat.ts` 流事件处理）：
- 触发点三处：`done`（后台会话正常完成）、`failed`（失败）、`permission_request`（后台会话等待审批）。
- 触发条件：`sessionId !== 当前会话id || document.visibilityState === 'hidden'`；命中才调 `notifySession`。当前会话前台可见时不打扰。
- 通知点击 → 路由跳 `/chat?session=<id>`（复用 S 系深链）。

## 4. 双分支与纪律注记

- 后端改动维持 **py3.8 纪律**（禁 PEP 604/585 内建泛型标注），保证 `release/win7` cherry-pick 零成本；前端 / electron 桥改动两分支同构（Electron 均 ^21.4.4）。
- U19 的 `git apply --reverse` 与 `git checkout --` 在 Win7 自带 git 2.x 均可用，无新依赖。
- S8 使用 Electron `Notification`（主进程），Win7 下为Balloon 提示，可用。

## 5. 验收标准

| 项 | 验收 |
| --- | --- |
| U17 | 选一个已知窗口的模型发起多轮流对话后，头部出现"已用 xx% 上下文"指示，数值随流结束刷新；≥90% 变红；tooltip 展示 token 明细与缓存命中 |
| U19 | Changes 面板可撤销单文件改动、可勾选单 hunk 撤销；撤销后清单即时刷新；未绑定工作区会话不显示操作按钮 |
| S8 | 后台会话完成/失败/等审批时弹出 OS 通知（前台当前会话不弹）；点击通知聚焦窗口并跳转对应会话 |
| 回归 | `vitest run`、`tsc --noEmit`、`eslint`、相关 `pytest` 全绿；无新增 console error |
