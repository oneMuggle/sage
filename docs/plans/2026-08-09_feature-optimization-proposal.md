# Sage 功能优化建议方案（2026-08-09 全面体检版）

> **状态**: 计划（待评审）
> **日期**: 2026-08-09
> **作者**: Claude（基于 4 路并行代码库扫描 + 已有规划文档核对 + git/PR 状态核实）
> **目标分支**: `main`（Win7 LTS 按需 cherry-pick）
> **与既有方案关系**: 本文档是**现状驱动**的补全方案，与 `2026-07-30_sage-optimization-final.md`（50 项，47 项已实现）、`2026-08-07_pi-hermes-feature-recommendations.md`（14 项，待评审）互补去重，见 §6。

---

## 0. 现状体检结论（TL;DR）

本轮对 backend/、src/、electron/、docs/technical/、CI 做了全面扫描，核心结论：

1. **最大 ROI 在"变现存量"**：9 个已实现功能压在 10 个 open PR + 7 个未推送本地分支里，只差合并/推送，不需要写一行新功能代码。
2. **聊天主链路存在已确认的性能病灶**：`sqlite_adapter` 与 45 个 legacy async handler 在事件循环上直接跑同步 sqlite/文件 IO/jieba 分词，修复只存在于一个已漂移 792 文件的本地分支，main 上未修。
3. **存在多处"假功能/假设置"**：代理设置可编辑但无消费代码、FeedbackModal 提交只打 console、Wiki 三个视图跑 mock 数据（后端真 API 已就绪）、i18n 无语言切换入口（329 条英文翻译是死资产）。
4. **安全欠账分散但同质**：`PRAGMA foreign_keys=ON` 未启用、deepMerge 原型污染 + apiKey 泄漏进 console、SQLite 明文 apiKey、SKILL.md prompt injection、依赖仍有 5 个 `>=` 未固定。
5. **双轨（legacy/hex）停在半路**：`API_MODE` 默认值已从 hex 退回 legacy，hex 端点 DI 未装配、大面积缺失，需要立项收敛决策。
6. **工程门禁有洞**：backend CI job 分支条件过窄、无 dependabot/安全扫描、无 nightly、hermetic e2e 零 CI 曝光、**整合状态下从未跑过一次全量测试**。

优先级原则：先变现存量（零成本高收益）→ 修病灶（性能/安全）→ 清假象（重建用户信任）→ 补能力（新功能）。

---

## 1. P0 — 速赢（2 周内）

### 1.1 变现存量资产【本轮最高 ROI】

**问题**: 50 项优化方案中至少 16 项"已实现"但不在 main：
- 10 个 open PR：S1–S7 堆叠链（#255–#261）+ A17 Code Diff（#240）+ A19 工具链追踪（#241）+ win7 predev（#277）
- 7 个未推送本地分支：A18 ContextSnapshot / U7 RightRail / U19 会话树可视化 / A6 工具并发 / A30 供应链硬化 / U11 DrainedToast / A3 hermetic e2e

**建议**:
- [ ] 按状态文档 §5.2 顺序合并：先无冲突项 → S1→S7 严格按序 → A19 → A6 → 其余
- [ ] 7 个本地分支 rebase 到最新 main 后推送开 PR（注意 U19 依赖 A24，A24 已合并，可回归验证树形渲染真正生效）
- [ ] **合并完成后在整合状态跑一次 vitest + pytest 全量**（状态文档 §8：从未跑过，系统性风险）
- [ ] 顺手修 A15 遗留：`py_compile` 改 `ast.parse()`（消除写文件产生 `__pycache__` 副作用）+ 补语法检查专属测试
- [ ] A6↔A19 合并时人工对齐 `run_loop` 事件时序（状态文档 §8 风险项）

**工作量**: 中（主要是冲突解决与验证，非开发）
**风险**: 低。分支均已独立 review 过。

### 1.2 修复聊天主链路事件循环阻塞【性能头号项】

**问题**: main 上确认未修——
- `sqlite_adapter.py` 所有 async 方法直调同步仓储（docstring 里的"非阻塞"推理是错的，调用就发生在事件循环线程上）
- `legacy_routes.py` 45 个 `async def` handler 直调同步 repo（sessions CRUD、get_messages、memory 搜索等）
- `wiki_routes.py` async handler 里同步 `read_text()/write_text()/rmtree()`
- memory 路由的 jieba 分词（CPU 阻塞）跑在事件循环上
- 旧修复分支 `fix/async-event-loop-blocking-watchdog-episodic`（c7f130ae）与 main 漂移 792 文件，且其针对的 `_session_watchdog` 在 main 上不存在——**不可 cherry-pick，需重做**

**建议**:
- [ ] 新分支重做：StoragePort 实现统一 `asyncio.to_thread` 包装（或降级为 `def` handler 让 FastAPI 走 threadpool）
- [ ] wiki 文件 IO 走 `aiofiles` / `to_thread`；jieba 预热 + `to_thread`
- [ ] 评估单一 sqlite 连接（`check_same_thread=False` 全局共享）→ 每线程连接或连接池
- [ ] 回归验证：并发聊天时 `/health` 响应时间不劣化

**工作量**: 中
**风险**: 中。触及聊天主链路，需全量测试兜底（依赖 1.1 的全量测试基线）。

### 1.3 速修包（单行/小改，可一个 PR 打包）

| # | 修复 | 位置 | 性质 |
|---|------|------|------|
| a | `PRAGMA foreign_keys=ON` 在 `get_connection` 启用（否则 session_workspace_bindings 的 ON DELETE CASCADE 是 silent no-op） | `backend/data/database.py` | 安全/数据完整性 |
| b | deepMerge 跳过 `__proto__/prototype/constructor` 键（原型污染）+ 冲突告警 JSON.stringify 前路径级脱敏（apiKey 进 console） | 前端 settings deepMerge（32 章） | 安全 |
| c | DB 补 4 个索引：`tool_usage(session_id)`、`review_events(status)`、`skill_drafts(status)`、`memories_episodic(expires_at)` | `backend/data/database.py` | 性能 |
| d | **Learn worker 空上下文修复**：`POST /learn` 入队时 `messages: []` 占位 → worker 从 `MessageRepository.get_by_session` 加载历史（代码内已有 TODO(I-2) 与完整说明，改动极小，直接决定 Background Review 产出质量） | `backend/api/legacy_routes.py:1923-1946` | 功能质量 |
| e | vitest exclude 加 `'**/.claude/**'`（`.claude/worktrees/` 有 6 个完整 checkout，本地全量测试时间×7 且可能串环境） | `vite.config.ts` | 工程 |
| f | MemoryTab"同步到内部服务器"开关误绑 `settings.autoMemory`（与通用 Tab 自动记忆同字段、双语义矛盾）+ 移除硬编码 `%APPDATA%\Sage\memory.db` 展示 | `src/pages/settings/MemoryTab.tsx` | UX bug |
| g | NewMemoryModal 保存成功后 `window.location.reload()` 整页刷新 → 改局部刷新列表；顺手换手搓模态为 shared/ui Modal（补 Esc/焦点管理） | `src/widgets/memory/NewMemoryModal.tsx` | UX |
| h | 仓库卫生：删根目录 `test-nav-history.mjs` 调试残留、`backend/backend/` 嵌套空目录、`backend/schemas/`（仅剩 `__pycache__`）、`backend/mcp/lifecycle/`（已被 pool.py 取代）；`.gitignore` 加 `桌面/`、`Desktop/`、`chat-*.png` | 根目录/backend | 卫生 |

**工作量**: 小（每项 1–30 行）
**风险**: 低。

### 1.4 "假功能/死设置"清理【用户信任】

**问题**:
- 网络 Tab 代理模式/代理地址/TLS 版本可编辑可持久化，但前后端**零消费代码**——用户以为配了代理实际直连
- `compactMode` 开关无任何样式消费方
- FeedbackModal 提交只 `console.warn`，Welcome 页却说"反馈功能开发中"，Titlebar 却挂着"可用"按钮——三处口径矛盾
- Wiki LintView/ReviewView/ResearchPanel 全跑 mock 数据，而 `POST /wiki/research` 等真端点已在后端就绪

**建议**（每项二选一，不允许维持现状）:
- [ ] 代理：接线（注入 httpx/fetch client）或暂时隐藏该 Tab 分区
- [ ] compactMode：实现间距 class 注入或移除开关
- [ ] 反馈：接后端落库/落文件，或统一下线三处入口
- [ ] Wiki research 接真 API（后端已就绪，纯前端接线）；lint/review 后端无端点 → 补端点或 UI 显式标注"演示"
- [ ] 顺带决策：`SessionTreeView` 死组件（A24 已合并，应接线到会话区）与 4 个零引用 shared/ui 组件（Skeleton/EmptyState/Tooltip/Popover）接线或删除；store.ts 的假 Lazy* 换成路由级真 `React.lazy`（首屏 bundle 现含全部 11 页）

**工作量**: 小到中
**风险**: 低。

### 1.5 doctor 二期扩容

**问题**: doctor 8 项检查已落地（PR #283），但用户最常报障的三类未覆盖；config_integrity 只查 JSON 合法性，过浅。

**建议**:
- [ ] 新增检查：LLM endpoint/API key 可用性、已配置 MCP server 可达性、重依赖可导入性（hnswlib/jieba/sqlite-vec——恰是仍未 `==` 固定的 3 个包）、日志目录膨胀、前端 dist 可用性
- [ ] 集成进 CI 烟测阶段（41 章 §41.10 已留 `SAGE_DOCTOR_ON_START` 口子）
- [ ] 41 章已列的 port_mcp / data_migration（pragma user_version 对比）两项

**工作量**: 小
**风险**: 低（纯只读诊断）。

---

## 2. P1 — 核心体验与安全（1–2 个月）

### 2.1 安全专项（分散欠账，同质归拢）

- [ ] **工具沙箱一期**（pi-hermes §1.2，已确认未动工）：ToolExecutionContext 加 `sandbox` 字段；bash/office_create 等写操作工具至少 workspace_only 强隔离；Docker backend 二期 opt-in
- [ ] **SKILL.md prompt injection**（24 章 §9.13）：聊天层把 SKILL.md body 视为不可信内容，包装隔离，不直接拼 system prompt
- [ ] **apiKey 加密存储**：SQLite 明文为既有设计，评估 OS keyring（Win DPAPI / libsecret）迁移路径；32 章 hex 路径 legacy 字段残留一并收敛
- [ ] **依赖固定补齐**（pi-hermes §1.3，确认完成约一半）：jieba/sqlite-vec/networkx/numpy/hnswlib 5 个 `>=` → `==`（hnswlib/numpy 是 ABI 敏感包，漂移风险最高）；建 `requirements.in` + pip-compile lockfile；前端加 `.npmrc save-exact=true`
- [ ] CI 补 dependabot + 每周 `pip-audit` / `npm audit` workflow（当前 `.github/` 完全无安全扫描）

**风险**: 沙箱中；其余低。

### 2.2 流式与实时体验升级

**问题**: 23 章明确遗留——流式是事件级一次一行（非 token 级）；流式中断直接清空已生成内容；前端 cancel() 不取消后端（fire-and-forget）；Artifacts 列表只在面板打开时拉取，不随流式事件刷新。

- [ ] 后端支持逐 token push（SSE/NDJSON token 事件），前端 token-by-token 渲染
- [ ] 流式中断保留已生成内容（不清空 streaming 态）
- [ ] cancel() 透传后端真正终止生成（兼顾 36 章残余风险：worker 线程不可杀、LLMClient 无超时敞口）
- [ ] Artifacts：流式事件驱动实时刷新 + PDF kind 专用渲染器（现落入 text fallback 被拒）+ tool_call_id 跳转定位（列已预留）+ 产物搜索/过滤
- [ ] 统一事件推送后，Skills 页 10s 轮询也可换为事件驱动（24 章）

**工作量**: 中到大
**风险**: 中（协议层改动需前后端 + Electron relay 三方同步）。

### 2.3 i18n 完成战役

**现状**: 键表健康（zh/en 各 329 键完全对齐），完成度约 55–60%；46% 组件文件仍硬编码中文；**无任何语言切换入口，en.ts 是死资产**。

- [ ] Settings→通用 加"界面语言"选择器（接通 setLocale，半小时工作量，先让英文资产活过来）
- [ ] 优先清"有键不用"：Settings 子导航、GeneralTab 分区标题、Chat.tsx 标题/placeholder（纯 `t()` 替换）
- [ ] 错误文案 i18n 化（useChat 未配置 API/发送失败、Welcome 创建会话失败等——最高频可见文案）
- [ ] aria-label 语言统一（InputCard 英文/WindowControls 中文混杂）
- [ ] 按页面批量推进 Memory/Agents/Skills/Knowledge 四个零 i18n 页面
- [ ] 实现 `common.skip_to_content` skip link（键已存在，只差渲染）

**工作量**: 中（机械替换为主，可分批）
**风险**: 低。

### 2.4 记忆系统实质升级

**问题**: "语义检索"名不副实——仅 HashEmbedder（字符哈希伪向量），ModelEmbedder 只存在于注释；episodic 搜索走 jieba + 多 LIKE OR，无 FTS5（semantic 已有 FTS5 可复用）；跨会话自然语言召回缺失（pi-hermes §2.5 未动工）。

- [ ] HashEmbedder → 真实 embedding（复用 LLM proxy 的 embedding 端点，Settings 补 embedding 配置——25 章遗留同源）
- [ ] episodic 表复制 semantic 的 FTS5 + jieba 方案（`ensure_semantic_fts_schema`/`backfill` 模式健康可直接套用）
- [ ] memory_recall 工具：FTS5 命中 → top-N → LLM 摘要（Haiku 级控成本，24h cache）
- [ ] 35 章 FOLLOWUP(persisted-history-injection)：legacy producer 把持久化历史注入 run_loop——**不做则自动压缩的 token 节省完全不生效**，同时是 16 章部分埋点的前置
- [ ] DB 膨胀治理：working_memory_snapshot/orchestration_lane_events/tool_usage 等只增表加 TTL/上限清理 + 启动期 incremental_vacuum（全库当前无任何 VACUUM）

**工作量**: 中到大
**风险**: 低到中。

### 2.5 hex/legacy 双轨收敛决策

**现状**: `API_MODE` 默认值 2026-06-13 从 hex 退回 legacy（SessionService/ChatService DI 未装配）；hex_routes 6 个 sessions 端点在默认模式下不注册；`get_chat_service()` 默认 `raise NotImplementedError`；hex 缺失 /memory /evolution /interrupt /learn /skills /messages 全部端点——**将来若切 hex 会静默丢功能**。

**决策记录（2026-08-09）**: 用户选定**方案 A**——装配 SessionService/ChatService DI + 补齐 hex 缺失端点（/memory /evolution /learn /skills /messages）+ 分阶段切回 `API_MODE=hex`，legacy 路由打 deprecated 标记。具体落地需另立专项 plan 展开，本方案不重复实施步骤。

**建议**（先决策后动工）:
- ~~方案 A~~ → 已选定，需另立 hex 迁移专项 plan（不在本方案范围）
- 方案 B：承认 legacy 长期主体地位，删除 hex_routes 半成品避免误导，18 章六边形架构文档同步降级表述
- 不论 A/B：先产出**端点覆盖对照表**（本调研 §二 已列雏形），10 个按 API_MODE 条件 skip 的集成测试要在 CI 显式跑 hex+legacy 两遍（当前一半矩阵永远无人验证）。A 路线下此为迁移验收清单的一部分；B 路线下此为删除 hex 前必跑的覆盖确认

**工作量**: 决策小，执行大
**风险**: 中。这是架构债，拖得越久越贵。

### 2.6 Electron 可靠性

- [ ] 渲染进程崩溃恢复：`render-process-gone`/`unresponsive`/`did-fail-load` 目前只记日志 → 自动 reload 一次，失败弹诊断对话框
- [ ] 后端进程运行期守护：监听 backendProc exit → 自动 respawn + 前端状态提示（长任务期间后端挂掉当前是静默失联）
- [ ] doctor 与 backend spawn 并行化（当前串行，冷启动最坏 +5s）；顺带修 dev 下 doctor 用 `python` 而后端走 `conda run` 的解释器不一致
- [ ] 前端设置保存静默失败链加状态反馈（localStorage 先写 + 后端异步推，后端失败仅 console.warn）

**工作量**: 中
**风险**: 低到中。

---

## 3. P2 — 能力补全（2–3 个月）

### 3.1 自更新通道（pi-hermes §2.3，未动工，quick win 属性）

- [ ] `GET /api/v1/release/check?channel=&current_version=` 包装 GitHub Releases API + semver 比较
- [ ] Settings→About 卡片："有新版本"提示 + 外链下载（不做自动安装，风险低）
- [ ] 与 release tiers（30 章）四档通道天然契合；先做"提示"，electron-updater OTA 留 P3 评估

### 3.2 技能生态闭环（24 章最集中的功能缺口）

- [ ] PR-7.1 ChatService 集成 SkillPort + execute 实跑（否则 builtin 路由 execute 大多返 success=False）
- [ ] PR-7.2 Skill enabled 状态 SQL 持久化（当前进程内态重启归零）
- [ ] 技能**编辑**端点（当前只能删了重建）；用户自定义 skill（PR-7.3）
- [ ] gating 修 `requires.config` v1 不支持（声明 config 依赖的技能永远过不了门控，死功能）
- [x] rescan 返回的 skipped 恒为 []（loader 不返 detail，前端 warn toast 永不触发）
- [ ] lifecycle active/stale 30 天阈值硬编码 → settings 可配
- [ ] 定时任务补执行历史/运行结果端点（当前失败只记日志，用户零可见性）——与 §3.3 投递互补

### 3.3 定时任务投递 × 消息网关（pi-hermes §2.1+§2.2，捆绑规划）

- [ ] DeliveryChannel Protocol（desktop_toast/telegram/email/webhook）+ ScheduledTask 加 `deliver_to`
- [ ] Telegram gateway 一期（复用 chat NDJSON 协议 + A24 session 树续接）
- 已确认 backend 无 gateway/、scheduler 无 deliver_to 字段——完全空白，需整体设计

### 3.4 CI 工程加固

- [ ] backend job `if` 条件放宽：所有 PR + push 都跑（当前推 feature 分支不开 PR 时后端检查完全不跑，已知问题）
- [ ] nightly workflow：hermetic e2e + backend 全量 + electron smoke（当前 CI 只跑 smoke.spec.ts 一个文件，hermetic/live 零曝光；也解决"合并后无人跑全量"）
- [ ] bundle-size 门禁（size-limit 或 dist diff 断言；当前只有 500KB warning 且被主动调高过）
- [ ] 移除长期化的 `continue-on-error: true`（mypy、legacy pytest）与 `npm ci --force --force`
- [ ] 15 章遗留：lefthook 硬编码 conda 路径、8 条 ESLint 违规清零、**后端覆盖率 43% → 80% 主线**、import-linter 配置（18 章前置已具备）

### 3.5 Wiki 与知识库增强

- [ ] HNSW 索引 GC/定期重建（已删记录永久残留，召回越用越脏——`vectorstore_hnsw.py:189`）
- [ ] wiki project 删除/关闭端点（CRUD 半边缺失）、orchestration lane 删除/归档端点（lane 只进不出）
- [ ] 多格式文档解析（PDF/DOCX/PPTX）——与 Artifacts PDF 预览共建解析层
- [ ] 图布局从 id 哈希网格升级 dagre/force-layout；Adamic-Adar 相似度 TODO
- [ ] embedding 端点独立配置（当前 MVP 复用 chat 端点）

### 3.6 无障碍（17 章 PG1-L5）

- [ ] 手搓模态全部换 headlessui Modal/Radix（已有成熟原语，ApprovalDialog/QuestionDialog 是正面样板）
- [ ] 侧边栏 `aria-current="page"`（全库当前零处）、icon-only 按钮补 aria-label（shared/ui Modal 关闭按钮影响所有使用方）
- [ ] 统一错误/加载/重试组件（17 章 PG1-L4：ErrorBoundary/LoadingState/RetryButton/Skeleton 共享件）
- [ ] 对比度 ≥4.5:1、焦点环、Lighthouse a11y ≥95 目标

---

## 4. P3 — 长期方向

| 项 | 说明 |
|---|------|
| electron-updater OTA | 当前 `publish: null` 完全无自动更新，用户永远停在旧版（含安全修复）；NSIS/deb 双渠道需分别验证 |
| Electron 升级双轨策略 | main 线 Electron 21.4.4 已 EOL、Chromium 106 有已知 CVE（20 章 HIGH），win7 线冻结是既定决策——main 升级新版、win7 冻结需在方案里写死 |
| CLI 模式（pi-hermes §2.4） | 复用 agent.run_loop + doctor 骨架，SSH/离线部署入口 |
| 轨迹导出（pi-hermes §3.1） | session_messages + tool_calls → fine-tuning JSONL，现有 session_repo 之上低成本 |
| Zotero 集成 | ideas 池 Backlog，触发条件未满足（wiki 稳定 ≥1 月 + ≥50 篇文献），保持观察 |
| macOS dmg + deb GPG 签名 | 26 章遗留；mac.target=null 是战略决策，重启需用户背书 |
| legacy 前端组件清理 | 17 章 PG1：src/components/ 遗留目录、lib/store.ts 跨实体拆分 |
| usage 落库 + 历史报表 | 当前内存 ring buffer 重启清零（37 章），"本周花了多少钱"做不到 |

---

## 5. 明确不建议做（本轮证据支持）

| 项 | 理由 |
|---|------|
| cherry-pick `fix/async-event-loop-blocking-watchdog-episodic` 分支 | 与 main 漂移 792 文件，其针对的 `_session_watchdog` 在 main 不存在；按 §1.2 重做 |
| A27 工具执行钩子（win7 线副本） | 会删除 main 的 M1 权限执行器，权限绕过风险（状态文档 §6 已定性）；任何钩子类需求先对齐 M6 hooks |
| 维持"假设置"现状 | 代理/compactMode/反馈空壳：接线或下线，不接受"看起来有"——与 PHILOSOPHY.md"透明可控"直接冲突 |
| plugins/ 空壳包盲目立项 | `backend/plugins/` 只有 `__init__.py`，无明确需求前删除优于保留占位 |

---

## 6. 与既有方案的去重对照

| 来源 | 状态 | 本方案处理 |
|---|---|---|
| 50 项方案（2026-07-30） | 47 项已实现；**16 项未进 main** | §1.1 变现存量；跳过项维持（A11 STT / A22 扩展示例 / A27 钩子 / 隐性 U14） |
| pi-hermes §1.1 doctor | ✅ 已合并（PR #283/285/286） | 本方案 §1.5 做二期扩容 |
| pi-hermes §1.2 沙箱 | 未动工（确认无 backend/sandbox/） | 本方案 §2.1 |
| pi-hermes §1.3 依赖固定 | 半完成（核心已 `==`，5 包残留） | 本方案 §2.1 补齐 |
| pi-hermes §2.1/2.2/2.3/2.4/2.5 | 全部未动工（代码层确认） | §3.3 / §3.1 / P3 CLI / §2.4 分别承接 |
| pi-hermes §3.1–4.2 | 未动工 | P3 承接或维持 Backlog |
| ideas 池 Zotero / wiki 文档更新 | Backlog / Next Up | 维持原触发条件不变 |

**新增（既有方案均未覆盖）**：§1.2 事件循环阻塞、§1.4 假功能清理、§2.3 i18n 战役、§2.5 hex 收敛决策、§2.6 Electron 可靠性、§3.4 CI 加固大部分条目、§1.3 速修包 b/c/d/f/g。

---

## 7. 建议执行顺序与里程碑

```
Week 1    §1.3 速修包 + §1.4 假功能决策（小 PR 并行）
Week 1-2  §1.1 存量合并波（S1→S7 按序 + 7 分支 rebase/推送）+ 整合态全量测试
Week 2-3  §1.2 事件循环阻塞重做 + §1.5 doctor 二期
Week 4-8  §2.1 安全专项 + §2.3 i18n（可并行，机械工作）
Week 6-10 §2.2 流式升级 + §2.4 记忆升级
Week 8-12 §2.5 hex 收敛决策落地 + §2.6 Electron 可靠性
Month 3+  P2 各项按用户价值排序推进
```

**里程碑验收**:
- M1（Week 2）：open PR ≤ 3，整合态全量测试绿
- M2（Week 4）：聊天并发下 `/health` P95 无劣化；安全专项 5 项全绿
- M3（Week 12）：i18n 完成度 ≥90% 且语言可切换；流式中断保留内容可用
- 每个 P0/P1 项沿用 pi-hermes §8 验收标准（覆盖率 ≥80%、Win7 兼容性验证、文档同步、CHANGELOG 条目）

---

## 8. 风险评估

| 风险 | 缓解 |
|---|---|
| §1.2 触及聊天主链路，回归面大 | 先在 §1.1 建立全量测试基线；小步提交，每步跑并发回归 |
| §1.1 堆叠链 S1–S7 合并顺序错误引发连锁冲突 | 严格按状态文档 §5.2 顺序；A17/A19/A6 热点文件（agent.py）留人工对齐预算 |
| §2.5 hex 决策拖延 | 设 deadline（Week 8 前必须出决策文档），逾期默认方案 B（保守） |
| Win7 LTS 双线维护成本 | P0/P1 每项完成时明确标注"是否 cherry-pick"；doctor/依赖固定/安全项默认同步 win7 |
| 本方案范围过大 | P0 全部为低风险高确定性项，可独立先行；P1/P2 按会话逐步拆独立 plan |
