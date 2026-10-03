# 主流 AI 应用对标 · UI/功能/逻辑优化建议方案（2026-10-01）

> 参照对象：Claude（Memory / Incognito / Capabilities）、ChatGPT（Dreaming /
> Temporary Chat）、Cursor（Checkpoints）、Copilot、Claude Code、Cline、Windsurf，
> 以及 2026 年 agentic UX 行业共识（permissions / observability / reversibility）。
> 方法：先按代码事实盘点现状（§1–§2），再对标（§3），最后按
> 「价值 × 成本 × 冲突风险」分批给方案（§4–§6）。
>
> 与既有文档的关系：
> - `2026-09-27_mainstream-ai-parity-analysis.md` 覆盖的是 **coding-agent 类**
>   （/rewind、checkpoints、diff UX）。其 backlog 现状：W1 已落地
>   （`src/widgets/chat/rewind/RewindDialog.tsx`）、W2 已落地
>   （`src/shared/lib/shortcuts.ts` + `KeyboardShortcutsHelp.tsx`）、G2 failover
>   **全仓零实现**、G4/G5 部分。
> - 本文**不重复**上述范围，聚焦此前完全没被对标覆盖的两个维度：
>   **① 消费级记忆产品的透明度设计；② 已建成能力的「最后一公里」断裂。**
> - 交叉参考：`2026-09-24_zcode-parity-gap-analysis.md`、`parity-loop-sop.md`。

---

## 0. 一句话诊断

> **Sage 现在不缺功能，缺的是「价值闭环」——后端已经建成的价值，有一批断在
> 最后一米，UI 上看不见、点不到、撤不回。**

近期 commit 构成印证：`docs 回填` / `test 补齐` / `refactor 路由迁移` 占绝大多数，
功能扩张期（parity round 已到 R77）已经过去。此时继续加功能的边际收益，
低于把已有能力接通到用户手上的收益。

---

## 1. 现状体检：三个「已建成但断链」的事实

### 1.1 记忆：能写、能看、**不能删**（哲学自违）

`PHILOSOPHY.md:19-20` 明确把「不可删除：用户无法清除记忆」列为**反模式**。
但代码事实是：

| 能力 | 后端 | 前端 API | UI 实际调用 |
|---|---|---|---|
| 搜索 | `GET /memory/search`（`legacy_memory_routes.py:349`） | `memoryApi.searchMemories`（`memoryApi.ts:291`） | **零调用** |
| 删除 | `POST /memory/delete`（`:450`） | `memoryApi.deleteMemory`（`memoryApi.ts:349`） | **零调用** |
| 诊断 | `GET /memory/diagnostics`（`:382`） | `getMemoryDiagnostics`（`:280`） | **零调用** |

`MemoryBrowser.tsx:365-474` 用的是自带的**只读** `MemoryItemCard`；
真正带两步删除的 `MemoryItem.tsx:40-45` 虽从 `index.ts:5` 导出，但**无渲染方**。
`MemoryBrowser` 反而有 6 张统计卡（`:239-246`）+ 双维筛选（`:290-326`）。

**结论**：用户有一条错误记忆时，无路可走。这是哲学与实现的直接冲突，
且是全部缺口里成本最低、感知最强的之一。

### 1.2 Office：能 lint、**不能修**，且对话链上不可达

| 环节 | 状态 | 证据 |
|---|---|---|
| lint 报告 | ✅ 完整（徽章/计数/规则数/Top N） | `OfficeDeliveryDrawer.tsx:66-82,174-222` |
| 无规范时如实提示 | ✅ 优秀（「未指定格式规范，已跳过检查」） | `:156-160` |
| **一键修复** | ❌ 端点存在 `POST /word/repair`（`office_routes.py:676`） | `officeApi.ts` **无** `repairWord`，全仓零引用 |
| self-checks | ❌ `GET /doc/{id}/self-checks`（`:1099`） | 零引用 |
| 期刊 FormatSpec 库 | ❌ `journalApi.listSpecs/getSpec`（`journalApi.ts:29,37`） | **只被测试消费**，无 UI 组件调用 |

更关键的是**链路断裂**：`openDelivery` 仅被 `OfficeGenerateForm.tsx:93,297` 与
`LaneBoard.tsx:210,239` / `TaskCenterWidget.tsx:286,290` 调用。
**对话里产出的 docx 永远不会自动打开验收抽屉** —— 用户交完稿看不到任何 lint 结果。

而 `/office` 入口还被 feature-unlock 门控（`Sidebar.tsx:64,94-97`）：核心差异化能力
默认不可见，隐藏期间只能靠输 URL 发现。

**发现问题的能力有，修复问题的能力没有，闭环断在最后一步。**

### 1.3 审批：桌面端可能被「静默消耗」

`RemoteApprovalBridge.tsx:21-63` 每 3 秒轮询 `permissions_pending`，
请求在 Telegram 处理后**静默 `state.resolve()`**（`:27-30`，无 toast）。

对比：记忆写入有撤销 + 提示（`MemoryWriteHints.tsx:113-149`），
**而风险更高的危险操作审批没有撤销、没有回执、没有来源标注**。
可撤销性出现倒挂。

OS 通知也只带 tool_name + 子任务 id（`ApprovalDialog.tsx:77-80`），无风险等级、无等待时长。

### 1.4 附带发现：设置页存在隐形 tab（实锤缺陷）

`Settings.tsx:69-88` 的 tabs 数组从 `'basic'` 起，**不含 `'general'`**；
但 `:55` 默认 `activeTab = 'general'`，`:171` 渲染 `<GeneralTab>`。

后果：
- 默认落地页在左侧导航**无任何高亮项**；
- 25KB 的 `GeneralTab`（最大 tab）**无导航入口**，切走后回不来；
- `GeneralTab` 是**唯一未被 `settingsSearchIndex.ts` 收录**的 tab → 搜「重置」也搜不到；
- 而破坏性操作「重置全部设置」正藏在这里（`GeneralTab.tsx:362-430`）。

即：**项目哲学强调「不可逆操作必须可审计可回滚」，而重置入口本身是隐形的。**

### 1.5 记忆「读」的透明度缺失

`Message.tsx:827-835` 气泡内 memory chip 只显示 `memory_type` + 截断 preview，
**无检索得分、无命中原因、不可点击回溯记忆库**。
写入有提示（`MemoryWriteHints.tsx`），**读取没有** —— 而「它凭什么引用了这条」
正是用户核对答案可信度时最想知道的。

---

## 2. 信息架构体检

| # | 问题 | 证据 |
|---|---|---|
| IA1 | 记忆能力散在 4 处：`/memory` 页 + 侧栏 + 设置「记忆」tab + 设置「记忆与知识」tab | `Sidebar.tsx:59`、`Settings.tsx:71,76` |
| IA2 | 术语不统一：知识库 / `/wiki` / 「记忆与知识」 | `Sidebar.tsx:60`、`Settings.tsx:71` |
| IA3 | 任务进度两处并存：右面板「进度」tab + 全局 TaskCenter 胶囊 | `RightPanel.tsx:56`、`Layout.tsx:166` |
| IA4 | 隐藏功能无发现路径：`/orchestration` `/office` `/arena` 默认不渲染 | `Sidebar.tsx:94-99,178-183` |
| IA5 | 设置搜索只跳 tab、不锚点定位，65 条索引价值折半 | `Settings.tsx:98-101` |
| IA6 | 模型切换是「盲操作」：不校验上下文长度、不提示窗口变化 | `SessionModelPicker.tsx:65-88` |
| IA7 | 「清空全部归档」用 `window.confirm`，与项目内两步确认惯例不一致 | `ConversationsSection.tsx:151` vs `GeneralTab.tsx:359` —— ✅ P1-8 已修 |

**已确认不是问题**（曾疑为缺口，实为已实现，勿重复排期）：
- 流式中可继续输入 —— `ChatInput.tsx:357-358` 走 steering 注入当前 run，失败回退队列。
  但**用户不知道这条会被注入还是排队**，属反馈缺失而非能力缺失（见 P1-6）。

---

## 3. 对标结论：主流 AI 应用做对了什么

### 3.1 记忆：透明度是分水岭，不是功能

| 产品 | 存储形态 | 关键设计 | 对 Sage 的启示 |
|---|---|---|---|
| **Claude** | 分类条目，可读可编辑 | **主动告知「我正在用这条记忆」**；Pause（保留）/Reset（清除）二分；Incognito chat | Sage 写入有提示、**读取无提示**；无 Pause/Reset 二分；无临时对话 |
| **ChatGPT** | Dreaming 后台综合 | 静默使用，摘要视图（≠全量），Temporary Chat 绕过记忆读写 | 反例：静默即不可审计 |
| **Gemini / Copilot** | 账号级画像 | 活动记录 + 自动删除期 | 本地优先的 Sage 天然占优，但需把「本地」讲成卖点 |

**关键洞察**：Claude 2026 年最有效的差异点不是记忆更强，而是
**「每条记忆是可读可编辑的文件 + 使用时明确声明」**。
Sage 的记忆存本地 SQLite + ChromaDB，**架构上比 Claude 更可审计，却没把
这个优势露出来**。

### 3.2 Agent surface 三要素（2026 行业共识）

权限（permissions）、可观测（observability）、可逆（reversibility）。
行业共识句：**「当自动化失败时，trace 就是 UI」**。

对照 Sage：
- 权限 ✅ 优秀（`ApprovalDialog.tsx` 风险分级 + diff 预览 + 拒绝反馈回传，全项目最高完成度）
- 可观测 ⚠️ 有时间线，但历史 run 在 Wave 4 被删（`orchRunClient.ts:7`）
- 可逆 ⚠️ 记忆可撤、审批不可撤 —— **倒挂**

### 3.3 已验证有效的 UI 原语

1. **plan-and-execute**：执行前展示可编辑步骤列表（后端 `orch_routes.py:564` 仍在，UI 已删）
2. **confidence signaling**：二元「有把握 / 没把握」优于百分比（用户决策更快）
3. **progressive delegation**：先全审批 → 连续批准 N 次后对常规操作自动放行
4. **two-pane separation**：对话区（谈意图）+ 控制区（盯进度/审批/产物）
   —— Sage 右面板 5 tab 已覆盖 ✅
5. **post-action summary**：工作流结束给出「改了什么 / 碰了什么 / 为什么 / 哪些失败」

**Sage 已具备 4/5**（two-pane、tool call 分发渲染、上下文水位、消息操作区），
缺 plan 预览与 post-action 摘要。

---

## 4. 优化建议 · P0（缝上断链，零/低后端改动，最高 ROI）

> 统一判据：**后端已就绪，只差 UI 接线**。全部避开 `legacy_routes` 拆分战区，
> 纯前端 + i18n + 测试，可与并行会话安全并发。

### 4.1 实施状态（2026-10-01 首轮落地）

| # | 建议 | 状态 | 落地位置 / 备注 |
|---|---|---|---|
| **P0-1** | 记忆可搜索 + 可删除 | ✅ 已落地 | `MemoryBrowser.tsx` 搜索框（300ms 防抖 → `searchMemories`）+ 卡片两步确认删除（`deleteMemory`）。**删除失败只 toast 不走 `setError`** —— 后者是列表级错误态，一设置会把整个记忆库替换成「加载失败」 |
| **P0-2** | Office 修复闭环 | ✅ 已落地 | `commands.ts:office_word_repair` + `officeApi.repairWord` + 抽屉内「一键修复」。**修复报告独立于按钮条件**：全修完时 `lint.ok` 翻真，若绑在一起用户点完会看到反馈凭空消失 |
| **P0-3** | 对话产物自动开验收 | ⏸️ **降级为独立批次** | 见 §4.2 —— 原判断「中成本」被推翻 |
| **P0-4** | 远程审批回执 | ✅ 已落地 | `RemoteApprovalBridge.tsx` 静默 `resolve()` → `toast.info`（工具名/风险/等待时长）。**按 `request_id` 幂等去重**：3s 轮询跨 tick 时序会重复骚扰 |
| **P0-5** | 修复隐形 GeneralTab | ✅ 已落地 | `Settings.tsx` tabs 补 `'general'` + `settingsSearchIndex` 收录 `reset_settings`（此前是唯一未被索引的 tab，搜「重置」无结果） |
| **P0-6** | 记忆引用可回溯 | ✅ 已落地 | 气泡内 memory chip → `/memory?focus=<id>` → 卡片高亮 + 滚入视区。走 **prop 注入**（`Chat → MessageList → TurnGroup → Message`）而非 `useNavigate`，避免打爆 13 个未包 Router 的既有测试 |

**测试**：新增 22 例（记忆搜索 3 / 记忆删除 3 / 深链定位 3 / 审批回执 1+适配 / Office 修复 5 / 通用修复若干）。

### 4.2 P0-3 降级说明（原判断有误）

原方案写「挂 `MemoryWriteHints` 同级的流结束回调」即可，实测**不成立**：

1. **两条链路互不相通**。对话产出的 docx 走 **artifact** 通路（tool_call → `artifactsByToolCall` → 右面板 `selectArtifact`）；Office 验收走 **taskCenter** 通路（`OfficeGenerateForm` / `LaneBoard` → `openDelivery`）。`openDelivery` 现有 3 个调用方全在 Office/Lane 侧，对话流根本不在这条链上。
2. **对话链路不携带 FormatSpec**。`lintWord` / `repairWord` 都强制要求 `format_spec`；对话生成的产物没有规范快照，无规范时后端只能 skip —— 那样等于给用户一个永远显示「未指定格式规范」的死按钮。
3. 因此正确形态不是「自动弹抽屉」（自动弹窗本身也会打断连续对话），而是**先让 artifact 携带 workspace + formatSpec 关联，再在气泡内产物 chip 上挂「格式检查 / 验收」入口**（chip 已有 `useRightPanelStore` 全局通路，接入成本不高）。

**结论**：P0-3 前置条件是后端给 artifact 补 `workspace_path` / `format_spec` 元数据，属跨层改动，单独排期。

**P0 合计预期收益**：一次性把「记忆优先」「Office 交稿」「透明可控」三条核心主张
从**架构层**兑现到**产品层**。这批是本次建议里性价比最高的。

---

## 5. 优化建议 · P1（对标主流的体验升级）

### 5.1 实施状态（2026-10-01 首轮）

> **重要修正**：P1-2 盘点后发现**已完整实现** —— `Chat.tsx:101-115` 用 sessionStorage
> 持久化 `tempChatSessions`，`isTempChat` 门控记忆写入提示与落库。本项无需再做。
> 这是本轮第二个教训：**「以为缺」不等于「缺」**，实施前必须逐项核实。

| # | 建议 | 状态 | 落地位置 / 备注 |
|---|---|---|---|
| **P1-1** | 记忆 Pause / Reset 二分 | ✅ 已落地 | ① `autoMemory` 开关 desc 澄清「关闭只停止新增，已记住的仍保留」；② 新增 `ClearAllMemoriesSection` —— 统计条数 → 需输入「清除全部记忆」才放行 → 分页逐条删 → **失败数如实上报**。单条失败不中断整体，不谎称全部清除 |
| **P1-2** | 临时对话（无痕） | ✅ 早已实现 | `Chat.tsx` sessionStorage + `isTempChat` 门控 |
| **P1-3** | 模型切换后果预警 | ✅ 已落地 | `SessionModelPicker` 切换**前**预检：`getEffective`(目标窗口) + `fetchSessionUsage`(当前占用)，超 80% 才拦。**任一数据不可得就不拦** —— 宁可少拦，不可把正常切换变成阻碍 |
| **P1-4** | 设置搜索锚点定位 | ✅ 已落地 | ① 共享 `SettingRow` 新增可选 `anchor` prop → 渲染 `data-settings-anchor`；② `Settings.tsx` 点击搜索结果后记下 anchor，**等目标 tab 渲染完**再 `scrollIntoView` + 一次性高亮（`.settings-anchor-flash`，尊重 `prefers-reduced-motion`）；③ 已在 Basic/General/MemoryKnowledge/Memory/Models/Network/Orchestration/ToolsConnections 共登记 **30+ 锚点**（编排 tab 一屏 15 项，问题最集中）。**未登记锚点的条目静默降级为「只切 tab」** —— 整 tab 级条目（端点/MCP/Zotero…）本就无需定位。`scrollIntoView` 已守卫（jsdom 未实现） |
| **P1-5** | 记忆/知识库入口收敛 | ✅ 已落地（设置页侧） | **回填（2026-10-03）**：原状态「未做」已过期（本节标题即「首轮」状态）。核实 origin/main：设置页原有「记忆」与「记忆与知识」两个 tab，后者里**没有任何知识库设置**，只装记忆开关/管理；现已合并为单个 `memory` tab —— `MemorySettingsTab` 内嵌 `MemoryKnowledgeTab`，`Settings.tsx:100` 注释写明「已下线并入」。随 #1869（`4ac57c8cd`）落地。**只核对了设置页侧**，设置页之外是否还有该收敛的记忆入口，本次未核对 |
| **P1-6** | steer/排队意图可见化 | ✅ 已落地 | 核实结论：steer 已有 toast 反馈且立即生效，**不需要 UI**；真正的洞是**队列** —— 原本只活在 `useChat` 的 ref 里，唯一信号是 4 秒即逝的 toast，用户既看不到也撤不掉。更严重的是错误/中断路径刻意不 flush → 消息变成「僵尸队列」静默滞留，可能被下一条无关流意外带发。改为：队列加稳定 `id` + state 镜像（ref 仍是异步回调的真相来源），新增 `PendingQueueStrip` 常驻在输入框上方，显示条数/内容、**逐条撤回 + 全部清空**，并写明「当前回复结束后自动发送」 |
| **P1-7** | 隐藏功能发现路径 | ✅ 已落地 | `/office` 是核心差异化能力却默认 `return null` 藏起来，只能靠输 URL 发现。改为「更多」分组内**灰态常驻可见** + 点击给出用途说明卡（`LOCKED_FEATURE_HINTS`）→ 确认后解锁进入。**关键语义修正**（被既有 `ArenaAccountsToggle` 集成测试逼出）：必须区分「用户显式关闭」与「从未使用」—— 前者完全隐藏（尊重用户意图），后者灰态劝导。为此新增 `FEATURE_DISABLE_STORAGE_KEY` 独立追踪 + `useFeatureExplicitlyDisabled` hook |
| **P1-8** | 统一危险操作确认 | ✅ 已落地（范围比初判大） | 项目 R3 已引入 `confirmDialog` 服务（`src/shared/ui/ConfirmDialog/`，挂在 `AppProviders`），但仍有 **7 个文件 11 处 `window.confirm` 漏网**。全部替换：行内删除按钮走 `TwoStepDelete`（`AccountTable` 覆盖 Arena 两页 + `TodoPage`），设置页危险操作走 `confirmDialog`（`RemoteWorkspacesTab` 5 处 / `NetworkTab` / `ProvidersManager` / `ConversationsSection`）。**生产代码 `window.confirm(` 已归零** |

---

## 6. 优化建议 · P2（需后端补语义，单独立项）

| # | 建议 | 后端缺口 | 对标 |
|---|---|---|---|
| **P2-1** | **审批撤销** —— 让高危操作审批可反悔（与记忆 undo-write 对称） | ⚠️ **原判断需修正** | 核实发现「撤销**待审批请求**」价值为零（UI 已有「拒绝」按钮），且后端 `answer(false)` 本就能解析 Future。真正可反悔的是**已落盘的副作用**，而 `FileChangeCard` 的逐文件回滚（`file-change-revert` → `workspace_revert_changes`）**早已实现** —— 第六次「以为缺≠缺」。**本批落地的真实缺口**：① 逐文件回滚**零二次确认**（P1-8 全量替换时的漏网之鱼，不在设置页也不在行内删除按钮里）；② `apply_patch` 一次动 N 个文件要点 N 次。→ 补 `confirmDialog({danger})` + 新增「全部回滚 (N)」，部分失败如实上报「已回滚 M 个 + 失败清单」 |
| **P2-2** | **技能演化审计 + 回滚 UI** | ✅ 已落地 | 端点确实存在但从未被接出来（`skillsApi.ts` 无方法 → 会抛 `UnknownIpcCommandError`）。补 `electron/commands.ts` 两条路由 + `skillsApi.getAudit/rollback` + `SkillCard` 的「历史」按钮 + `SkillAuditDrawer`。**两处后端限制如实写进 UI**：审计 list 的 SQL 不返回 before/after 内容（只能做元数据时间线，做不了 diff）；回滚无条目粒度（只能「回到上一版」，不能点某条历史回那版）。回滚走 `confirmDialog({danger})` |
| **P2-5** | **渐进式授权** —— 连续批准 N 次后对常规操作自动放行（带通知） | ✅ 已落地 | ⚠️ 方案漏掉既有资产：`subagent_approval.py` 的 `AutoApproveEnforcer` 已是 autopilot 雏形（run 级**二值开关**、只覆盖子代理、与用户历史无关）。本批做的是**会话级、由用户自己批准历史驱动**的版本：① `ApprovalDecisionRepository.consecutive_gui_approvals()`（只认 `answered_by='gui'` 且 approved，遇拒绝即重置，不跨会话）；② `TrustEscalationEnforcer` 包在 `agent._build_permission_enforcer()`（**注入路径不包** —— 子代理已有 autopilot，两套叠加会绕过「连续人工批准」前提）；③ `GET/POST /permissions/trust-policy` + 设置页开关与阈值 + 已积累信任可视化。**默认关闭**，9 条安全不变式逐条有测试（deny 胜出、破坏性/可疑命令不自动放行、边界升级不放行、无法静态评估的工具转人工、计数失败降级为继续问人、每次放行落审计 `answered_by='trust'`） |
| **P2-6** | **运行后摘要** —— 完成时给「改了什么/碰了什么/哪些失败」 | ✅ 已落地（零后端改动） | 新增 `RunSummaryPanel`（挂在 `SubagentLivePanel` 相邻位，二者互斥：运行中 / 结束后）。「哪些失败」用现成的 `taskBoard.statuses`（含 `error` + `retry_count`）+ `progress` 计数；「碰了什么」复用 workspace changes 缓存。**三处如实标注**：文件是 **workspace 级快照、无 run 归属**（文案写「本次会话工作区变更」而非「本次 run 改动」）；未绑定 git 仓库如实显示不可用原因；「执行了哪些工具及成败」后端**零实现**（无 run 级工具台账），因此不展示 —— 宁可少说不可编造。附带「重跑失败任务」入口（复用既有 `rerun-failed` 通路） |
| **P2-3** | **编排历史复盘** | ⚠️ **已实现，方案判断过期** | 逐项核实后：`GET /orch/runs` 的**带 session 过滤版本**仍在（`orch_routes.py:118`），`orchRunClient.listSessionRuns` / `getRun` / `rerunFailed` 均已存在，UI 是 `SessionRunHistory.tsx`（挂在 `ProgressSection.tsx:108`），`rerun-failed` 端点 + `Chat.handleRerunFailed` 链路完整。本条的判断停留在 Wave 4 删无过滤 `listRuns` 的那个时点，C1（2026-09-09）已回归。**真实剩余缺口**仅「全局跨会话编排历史」——后端已无该端点，需新增 |
| **P2-4** | **计划预览（plan-and-execute）** | ⚠️ **已实现，方案判断过期** | `POST /orch/plan-items`（`orch_routes.py:564`）链路完整：`Chat.tsx:1087` 的 `plan-approve-orch` 直接调 `planItemsFromText` 后带 `planOverride` 发送；`PlanCard.tsx` 支持逐行编辑 + 删除（≥1 行守卫）+ `开始执行`；挂载在 `Chat.tsx:1156`。方案称「UI 已删」为误判 |
| **P2-5** | **渐进式授权** —— 连续批准 N 次后对常规操作自动放行（带通知） | 需信任度状态机 | progressive delegation |
| **P2-6** | **运行后摘要** —— 完成时给「改了什么/碰了什么/为什么/哪些失败」 | 需聚合 | post-action summary |
| **P2-7** | **EvolutionPanel 文案修正** | ✅ 已落地 | 核实后确认原文案确属误导：技能演化**只产出草稿**，需在「技能」页逐条 approve/reject（`legacy_skill_draft_routes.py:102,244`），并非「无需手动操作」。改为如实分两层陈述：5 个维护任务自动调度 vs 技能草稿需人审批，并指明审批入口在哪 |

---

## 7. 建议的实施顺序

```
第 1 批（1–2 天，零风险）  P0-5  P0-4
第 2 批（3–5 天，最高 ROI） P0-1  P0-2
第 3 批（1 周）             P0-6  P0-3
第 4 批                     P1-1 ~ P1-8
P2 独立立项，按并发战区排期
```

**并行冲突规避**：P0 全部落在前端 widget 层（`widgets/memory`、`features/office`、
`widgets/chat`），不触碰 `backend/api/legacy_routes.py` —— 该文件正处于
Capability Seam 拆分（DSH-R7+）战区。

---

## 8. 明确**不建议**现在做的

| 项 | 理由 |
|---|---|
| **G2 failover chain** | 沿用 9-27 结论：需动 `legacy_routes` 端点选择，正处拆分战区；且用户价值低于 P0 批次 |
| 多设备同步 / 离线缓存 | `PARITY.md:95-98` 已判定远期，当前无用户需求证据 |
| 继续加新功能 | 近期 commit 已是测试/重构为主，功能面足够；边际收益低于接通存量 |
| 会话拖拽排序 | 当前后端 SQL 排序（`Sidebar.tsx:142-144`）有明确产品理由，勿推翻 |
| 放宽设计密度 | `DESIGN.md` 的 calm/dense 是主动选择，非缺陷 |

---

## 9. 验收方式

- P0 各项：新增 vitest 覆盖（记忆删除两步确认、repair 调用序列、审批 toast、
  GeneralTab 导航可见性、memory chip 跳转），`tsc` + `eslint` + `vitest` 全绿。
- P1 各项：沿用 `parity-loop-sop.md` 的轮次记账法。
- 全部批次完工后回填本文件 §4–§6 状态，并更新
  `2026-09-27_mainstream-ai-parity-analysis.md` 的 backlog 交叉引用。

---

**日期**：2026-10-01
**范围**：UI / 功能 / 逻辑三维度
**方法**：代码事实盘点 + 2026 主流产品对标
