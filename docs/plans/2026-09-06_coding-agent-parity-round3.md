# 编码代理对标差距分析·第三轮：安全 / 交互闭环 / 交付物体验（2026-09-06）

- **状态**：批次 D 已实施（分支 `feat/parity-r3-batch-d`，main 基线 7c831ba5；win7 侧 `cherry-win7-parity-r3` = C-1 补齐 + 本批 cherry-pick）。实施中发现三处设计修正（见 §6.0），文档同步更新
- **上游文档**：[2026-09-06_coding-agent-parity.md](./2026-09-06_coding-agent-parity.md)（第一轮 G1-G10 工具面）、[2026-09-06_coding-agent-parity-round2.md](./2026-09-06_coding-agent-parity-round2.md)（第二轮 L/U/F，批次 A/B/C-1 已交付）——本文不重复两轮已列项，只记录第三轮新发现 + 对既有计划的勘误
- **对标对象**：Claude Code / ZCode（CLI 编码代理）、Qoder（Agentic IDE，Quest Spec 驱动）、Codex（OpenAI，review 模式）、WorkBuddy（腾讯，多代理办公交付物）；参照 Cursor
- **编号约定**：延续第二轮 L / U / F 编号顺延
- **方法**：在第二轮勘察基础上，针对两轮未覆盖面（安全存储、审批内容呈现、代码块交互、上下文可视化、流恢复、交付物体验）做定向代码核查 + 竞品 2026-06 后功能面核对

## 0. 结论速览

两轮之后，Sage 在"工具面"与"会话语义"上已接近主流水平；本轮发现的差距集中在四个此前未扫描的维度：

1. **安全**：API Key 明文落库（L15），两轮计划均未覆盖，建议升为 P1。
2. **审批透明度**：写类工具审批对话框只展示 `args_summary`，用户"盲批"diff（U15）——与 PHILOSOPHY"透明可控"直接冲突，也落后于 Claude Code/Qoder 的审批即预览体验。
3. **上下文可视化**：模型上下文窗口用量对用户完全不可见（U17），L1/L9 落地后这将是用户感知最强的缺失。
4. **交付物体验**：对 WorkBuddy 的正面战场（office 生成）缺内嵌预览（F11）；对 Codex 缺一键 review 入口（F10）。

**勘误**：第二轮批次清单中 L4（prompt caching）脱落——已交付批次（A/B/C-1）与批次 C 剩余清单均不含 L4，需回补排期。

**前置动作**：本地 main 落后 origin/main 6 提交（批次 A/B/C-1 均在 origin），继续任何批次前先同步；L14 双路径收敛决策仍未做出，仍是所有后端新项的前置。

## 1. 逻辑层新增差距（L，顺延编号）

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| L15 | **API Key 明文落库**：settings_repo 全文件无 encrypt/fernet/base64 等处理（grep 零命中），api_key 随 settings 明文进 SQLite；数据库文件随备份/导出/日志泄漏即泄密 | backend/data/settings_repo.py | 桌面端普遍走 OS 凭据库（macOS Keychain / Windows DPAPI / libsecret） | **P1（安全）** |
| L16 | **run 级恢复语义缺失**：流注册表为进程内存态，后端崩溃/被 supervisor 重启（最多 3 次）后运行中 run 直接蒸发；前端无"运行中断，点击继续/重试"的恢复路径 | api/chat_stream_registry.py（内存态）；electron/backendSupervisor.ts 重启仅拉起进程不恢复 run | Codex/WorkBuddy 任务可断点续跑 | P2 |
| L4※ | **勘误：prompt caching 从批次清单脱落**——第二轮 §4 批次 A/B/C 均未含 L4，但 L1（历史接线，已交付）落地后稳定长前缀已具备，cache_control 是成本/延迟的最大单项杠杆 | 第二轮表格 L4（P1）| Claude Code / OpenAI 均默认吃缓存 | **P1（回补排期）** |

### 1.1 L15 路径勘察

- 方案（推荐）：Electron main 侧用 `safeStorage`（Electron 21 已支持，Windows 走 DPAPI，兼容 win7 线）加密后落库，密文字段仍存 settings 表；后端读取时经 IPC 向 main 请求解密、仅驻内存。备选：主进程代持全部 key，后端每次 LLM 调用经 main 转发鉴权——改动大，不推荐第一步。
- 迁移：启动时检测明文字段 → 加密回写，一次性升级；导出/HTML 导出路径需同步脱敏核查。

## 2. UI 层新增差距（U，顺延编号）

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| U15 | **写类工具审批"盲批"**：ApprovalDialog 仅渲染 `args_summary` 文本（:132-137），write/edit/apply_patch 将写入什么内容用户看不到即点同意；300s 超时 default-deny 放大了误批/漏批双向风险 | src/widgets/permission/ApprovalDialog.tsx:132-137 | Claude Code 审批即见编辑内容；Qoder/Cursor 提案式 diff review | **P1** |
| U16 | **代码块零操作栏**：ShikiCodeBlock 无复制/应用到文件/另存等任何动作（grep copy\|apply\|save 零命中），复制都要手动划选 | src/widgets/chat/ShikiCodeBlock.tsx | 主流聊天 UI 标配 | P1（小改动高感知） |
| U17 | **上下文用量不可见**：全 UI 无 token/上下文剩余指示、无"即将自动压缩"预告（grep 剩余/remaining/context window 零命中）；长会话中用户对何时失忆/压缩零预期 | RightPanel / ChatPage 无命中 | Claude Code 上下文百分比、Cursor 进度指示 | P1（依赖 L9 per-model 记账） |
| U18 | **无快捷键体系与帮助层**：Emacs 键位（InputCard U20）与 `/` 菜单已有，但无全局快捷键表、无 `?` 帮助覆盖层；键盘效率特性不可发现 | src/ 无 shortcuts 帮助组件 | 主流均有 | P3（小） |

### 2.1 U15 路径勘察

- 后端 ApprovalGate 构造请求处（services/permission_gate.py）对 WRITE_LOCAL 风险类工具追加 `diff_preview` 字段：edit/apply_patch 用新旧内容算 unified diff，write_file 用"新文件全文（截断预算）"；审批 payload 随 SSE 下发。
- 前端 ApprovalDialog 对带 `diff_preview` 的请求改用 ShikiCodeBlock（diff 语言，既有支持）渲染；超大 diff 折叠 + "查看全文"。
- 注意与 apply_patch 的 validate-all-then-write 语义对齐：预览的应是校验通过后的最终写入集。

## 3. 功能点新增差距（F，顺延编号）

| # | 差距 | 现状与证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| F10 | **一键改动审查（/review）**：orchestration 已有 review lane（约 30 模块），但日常场景缺轻入口——"审一下当前工作区改动"无斜杠命令/按钮；git_diff 工具（G1）已就绪 | ChatInput 斜杠清单无 review；orchestration/ 有 review 模块 | Codex 专属 review 模式 | P2 |
| F11 | **Office 交付物内嵌预览**：office 工具能全生命周期生成 docx/xlsx/pptx/PDF，但聊天内交付形态是 artifact 文件卡片，无渲染预览；WorkBuddy 以"生成即可看可下载"为核心体验 | src/widgets/chat/ artifacts 卡片；office/ 模块已有 HTML 导出能力可复用 | WorkBuddy 交付物导向 | P2 |
| F1※ | **扩充（非新增）**：Plan UI 落地时建议对齐 Qoder Quest 的 Spec 工作流——计划=可编辑 spec 文档（用户可改/批）→ 执行打钩 → 完成报告；plan 持久化为工件、可跨会话引用，而非一次性结构体。G3 plan_write 的 goal+steps 结构可直接承载 | 第二轮 F1 | Qoder Quest Spec 模式 | 随 F1 |

### 3.1 差异化判断（不追什么、押什么）

- **不追 IDE 能力**：行内编辑、tab 补全、代码索引编辑器集成是 Qoder/Cursor 主场，Sage 定位是桌面助手而非 IDE，不正面竞争。
- **押"桌面 agent 工作台"**：记忆系统（所列竞品均无同级物）、office 全套 CRUD、可视化多代理编排（强于全部对标对象）、Win7 LTS 支持（独家）、带沙箱+UI 的技能系统。
- 对 WorkBuddy 的胜负手在交付物体验（F11）与任务叙事（计划卡/进度已在建，F1）；对 Claude Code/ZCode 在编码闭环手感（U15/U17/L4）；对 Codex 在 review 入口（F10）与桌面壳（第二轮 U12）。

## 4. 建议实施批次

- **前置**：同步本地 main ← origin/main（批次 A/B/C-1 已在 origin）；L14 双路径决策落地（建议新逻辑一律落 legacy）。
- **批次 D（P1，安全 + 审批透明）**：L15 key 加密、U15 diff 审批、U16 代码块操作栏、L4 prompt caching 回补；并清点第二轮批次 C 剩余中的 P1 项（U2 checkpoint UI、U3 Git 面板、U4 会话管理、U6 OS 通知）确保不脱落。
- **批次 E（P1-P2，编码闭环手感）**：U17 上下文指示（依赖 L9 记账先行）、F1 Plan UI（按 Spec 工作流验收）、F10 /review、L6 并行工具、L12 中断粒度。
- **批次 F（P2-P3，交付物与长尾）**：F11 office 预览、L16 run 恢复、L10 MCP 传输、L11 hook 扩点、U7 渲染增强（LaTeX/Mermaid/ANSI）、U9 hooks UI、U11 虚拟化、U18 快捷键帮助。
- **win7 对齐**：沿用既有惯例 cherry-pick `release/win7`；L15 用 Electron 21 safeStorage（DPAPI）无新依赖；后端项维持 py3.8 纪律（禁 PEP 604/585）。

## 5. 证据来源说明

- 定向核查：src/widgets/permission/ApprovalDialog.tsx、src/widgets/chat/ShikiCodeBlock.tsx、src/widgets/chat/Message.tsx（ThinkingPanel 已存在，非差距）、src/widgets/chat/ChatInput.tsx（@ 文件提及 AtFileMenu 已存在，非差距）、src/widgets/command/CommandPalette.tsx（命令面板已存在，非差距）、backend/data/settings_repo.py、api/chat_stream_registry.py、electron/backendSupervisor.ts。
- 负向证据均为 grep 零命中（encrypt/feernet/base64、copy|apply|save、剩余/remaining/context window、review 斜杠命令）。
- 竞品功能面：Qoder Quest Spec 模式（docs.qoder.com）、Codex review 模式、WorkBuddy 交付物导向（workbuddy.ai，2026 评测）。

## 6.0 实施期设计修正（2026-09-06，随批次 D 落地同步）

1. **U16 勘误（非差距）**：ShikiCodeBlock 的复制按钮**已随批次 A 交付**（第二轮勘察时 grep 大小写遗漏 `Copy/copied`）。本批仅补其硬编码中文的 i18n（`codeBlock.copy/copied` 键 + ChangesSection 测试补 I18nProvider）。U16 从批次 D 移除。
2. **L15 范围收窄**：GET/HTTP 面的 apiKey 脱敏（`redact_secrets`，OWASP A02）已于 2026-08-26 落地，前端掩码改动**不再需要**。本批只做"落库静态加密"——接入点从 settings 路由层下沉到 `SettingsRepository.get/set` 字符串层（单一咽喉点，legacy/hex/preferences 全覆盖），迁移读原始行统计（解密视图会让加密计数恒为 0）。
3. **L4 口径调整**：全链路走 OpenAI 兼容线格式（`/v1/chat/completions`），无原生 Anthropic Messages API——cache_control 注入**不适用**。落地为"缓存感知记账"：`extract_cached_tokens` 归一化三家 usage 形态（OpenAI `prompt_tokens_details.cached_tokens` / DeepSeek `prompt_cache_hit_tokens` / Anthropic `cache_read_input_tokens`）+ 缓存价（输入价 × 0.1）成本折算 + `usage_events.cached_tokens` 落库列（ALTER 迁移）+ 会话摘要透出。稳定长前缀由 L1 保障，OpenAI 系/DeepSeek 自动命中。

## 6. 实施方案（批次 D 逐项设计）

> 双分支总原则：main 与 win7 的 Electron 均为 ^21.4.4（已核实 `package.json:81` 与 `origin/release/win7:package.json`），**前端 / electron 桥改动两分支完全同构**；分支差异只存在于后端 Python（win7 线 py3.8 运行时）。因此所有后端代码在 main 上就按 py3.8 纪律编写（见 §7.3），cherry-pick 零改动成本。

### 6.1 L15 API Key 加密（P1，工作量 M）

**选型**：纯 Python 后端加密（方案 A），不用 Electron safeStorage（方案 B）。理由：后端是独立 Python 进程直读 SQLite，方案 B 需要后端↔main 进程新增解密 IPC/HTTP 通道，改动横跨 electron/main + preload + api 三层且双分支各维护一份；方案 A 收敛在后端单层，两分支同一份代码。

**设计**：新模块 `backend/services/secret_box.py`，平台分派，零新依赖：

| 平台 | 机制 | 存储形态 | 依赖 |
| --- | --- | --- | --- |
| Windows（含 Win7） | ctypes 调 crypt32.dll DPAPI（CryptProtectData/CryptUnprotectData，CRYPTPROTECT_UI_FORBIDDEN），用户级作用域 | `enc:dpapi:v1:<base64>` 内联密文 | stdlib ctypes，Win7 原生支持 |
| macOS | `security` CLI generic password（service=`sage`，account=endpoint id） | `enc:keychain:v1:<account>`，明文不落库 | 系统 CLI |
| Linux | `secret-tool`（libsecret），探测可用才用 | `enc:secret-tool:v1:<attr>` | 系统 CLI |
| 兜底（以上全不可用） | 保持明文 + 标记 | `enc:none:v1:` | doctor 持续告警 |

- 接入点：settings 读写的单一 helper（在 legacy_routes 的 settings 路由段收敛为一个 `load_app_settings()/save_app_settings()`，本身就是 cherry-pick 冲突面压缩手段），对 `endpoints[].apiKey` 及等价全局 key 字段透明 wrap/unwrap，`enc:` 前缀做版本化。
- 迁移：启动时 `migrate_plaintext_keys()`——无前缀非空 key → 按平台加密回写；单条失败保留明文并记日志（fail-open，不阻塞启动），doctor 汇报每 endpoint 加密状态。
- **行为变更（两分支同构，同一 PR）**：GET settings 不再返回明文 key，改回 `has_key + masked`（`sk-…last4`）；PUT 仅在用户提交新值时更新。前端 EndpointsTab 输入框改占位符"已保存，输入以更换"。
- 触点：`backend/services/secret_box.py`（新）、`legacy_routes.py` settings 段、doctor 检查项、`src/pages/settings/EndpointsTab.tsx`。
- 测试：平台抽象层可注入 fake provider 的 roundtrip 单测、迁移单测；stub-smoke E2E 增"读 DB 文件 grep 不到明文 key"断言。

### 6.2 U15 审批 diff 预览（P1，工作量 M）

- 后端 `backend/services/permission_gate.py`：`ApprovalRequest`（现仅 tool_name/args_summary/risk 三字段，:139-141）增加 `diff_preview: Optional[str]`；构造处对 WRITE_LOCAL 风险类工具生成 unified diff（`difflib.unified_diff`，stdlib）：
  - `edit_file`：读目标文件现内容 vs `old_string`→`new_string` 应用结果（edit_tool.py 已有参数校验 ：102 可复用）；
  - `write_file`：现文件内容（不存在则 new file diff）vs `args.content`；
  - `apply_patch`：复用 patch_tool.py 的解析（dry-run 语义，不落盘），逐文件 diff 拼接；
  - 截断预算 8KB，尾部标注"(diff 已截断)"；读文件失败 → `diff_preview=None` 回退现状 args_summary，不阻塞审批。
- SSE `permission_request` 事件透传新字段（api 层加字段即可）。
- 前端 `src/widgets/permission/ApprovalDialog.tsx`：有 `diff_preview` 时以 ShikiCodeBlock `language="diff"` 渲染（既有能力，>200 行默认折叠），args_summary 降为次要信息。300s 超时 default-deny 语义不变。
- 测试：gate 三类工具 diff 生成 + 截断单测；ApprovalDialog vitest。

### 6.3 U16 代码块操作栏（P1，工作量 S）

- `ShikiCodeBlock.tsx` 加 header：语言标签 + 复制按钮（`navigator.clipboard.writeText` + sonner toast，均为既有依赖）。
- "另存为"（可选）：需确认 electron 桥是否已暴露 save dialog；没有则在 `electron/main.ts` + `preload.ts` 加 `dialog:saveText` 通道（两分支同构，无新依赖）。

### 6.4 L4 prompt caching 回补（P1，工作量 M；前置 L1 已在 origin/main）

- `llm_client.py`：
  - claude provider：system 块与消息序列最后一个工具边界加 `cache_control: {"type":"ephemeral"}`（≤4 个 breakpoint）；usage 归一化 `cache_read_input_tokens` / `cache_creation_input_tokens` 入 usage_tracker（L8 已落库）。
  - openai 兼容系：请求不变（前缀自动缓存）；读取 deepseek `prompt_cache_hit_tokens` 等字段归一化拆账。
  - `chat_stream`（L2 真流式，已交付）同口径。
- 开关 `prompt_cache_enabled`（默认开）：settings_repo.KEYS 白名单加 key。
- py3.8：纯 dict/str 操作，无兼容点。
- 验收：同一长会话第二轮起 Anthropic 返回 cache_read>0；成本估算按缓存价折算（可后置到 L8 定价表）。

### 6.5 批次 E/F 概要（双分支注记）

- **U17 上下文指示**：后端 `MODEL_WINDOWS` 静态表（py3.8 dict）+ L9 记账接线 → run 状态事件加 `context_used/context_limit` → 前端输入区/RightPanel ContextMeter + 阈值预告"即将自动压缩"。同构。
- **F1 Plan UI**：注意 `src/components/PlanCardList.tsx` 是**编排 run 历史列表**，与 plan_write 无关，F1 前端从零做：PlanDrawer（消费 plan_write 状态）+ 可编辑 + 批准门禁 + 步骤打钩；后端 legacy_routes 目前无 plan 事件通道（grep 零命中），需沿两段式流注册表模式新增。后端项守 py3.8 纪律。
- **F10 /review**：纯前端斜杠命令 + prompt 模板组装（消费 git_diff 工具输出），零后端改动。同构。
- **F11 office 预览**：office 生成结果内嵌预览卡片（docx/pptx 轻量 HTML 渲染、xlsx 表格预览），复用 artifact 读取链路；工作量 L，维持 P2。

## 7. main + win7 双分支交付流程

### 7.1 硬约束与顺序

1. **先同步基线**：本地 main 落后 origin/main 6 提交（批次 A/B/C-1 都在 origin）——先 `git pull`；round2 遗留的 C-1→win7 cherry-pick（round2 文档 §0 标注待办）一并补上。批次 D 从两者完成后的基线开工。
2. **方向唯一**：main 落地且 CI 绿 → cherry-pick 到 `release/win7` → win7 CI 绿。禁止 win7 先行或长期漂移（round2 惯例：分支 `feat/parity-r3-batch-d` → `cherry-win7-parity-r3`）。
3. **每项独立 commit/PR**：可单独 revert；win7 侧冲突无法干净 cherry-pick 时允许等价重写，但验收口径一致。

### 7.2 本批次两分支差异面（结论：极小）

| 改动 | main | win7 |
| --- | --- | --- |
| U15 前端 / U16 / F10 | 同构 | 同构（同 Electron ^21.4.4） |
| L15 secret_box | 同一份 Python 代码 | 同一份；DPAPI 路径 Win7 原生支持 |
| L15 迁移 / L4 / U15 后端 | py3.8 写法 | 无需改动（见 7.3） |
| 新依赖 | 无 | 无（批次 D 全程零新增） |

### 7.3 py3.8 纪律（main 上直接遵守，cherry-pick 零成本）

- `from __future__ import annotations` 置顶（此后 PEP 604 `X | Y`、PEP 585 泛型仅可用于注解位置）；运行时禁 `X | Y`（isinstance/cast）、禁 `list[T]()` 运行时下标、禁 match、禁 3.9+ 的 `dict |` 合并与 `str.removeprefix/removesuffix`。
- 参考现状：settings_repo.py 即此写法（future import + 注解用 `str | None`）。

### 7.4 冲突热点预判

- `legacy_routes.py` 是最大冲突源（A/B/C 批次都在改）：L15 只动 settings 路由段并收敛为 helper、U15 只在 permission_gate + SSE 透传，与 C 剩余项（L6 在 agent.py、L10 在 mcp/、L11 在 hooks/）文件重叠小，冲突风险低。
- `llm_client.py`：L2/L3 刚改过 stream 与重试段，L4 改 cache 注入与 usage 归一化，cherry-pick 时注意基于批次 A 后的行号。

### 7.5 测试与验收矩阵

- 每项：pytest 单测 + vitest 组件测试 + ruff + lefthook 全绿；E2E 按 tier 归属（改动冒烟进 `test:pr` 的 stub-smoke，交互流进 deep/nightly）；win7 线加跑 `test:packaging`。
- 批次 D 整体验收：(1) DB 文件 grep 不到明文 key；(2) 写类工具审批弹窗可见 diff；(3) 代码块可一键复制；(4) Anthropic 长会话第二轮起 cache_read>0；(5) 两分支 CI 均绿、CHANGELOG 双线记录。
