# Sage 优化方案 · 续篇（UI / 功能 / 逻辑）（2026-10-02）

> 基线：`origin/main` @ `38c5f7992`（本地最后一次 fetch）。方法：只读取证——git 历史、静态扫描、真实执行 `electron/commands.ts` 取命令表、导入 `backend.main` 枚举 `app.routes` 取真实路由、在 `sage-backend` 环境实跑测试。数字均为 2026-10-02 当日实测，口径与局限见 §9。
> 与既有文档的关系：续 `docs/plans/2026-10-01_mainstream-ai-ux-optimization-proposal.md`（#1869，下称「10-01 方案」）。10-01 方案的诊断是「功能不缺，缺价值闭环」，聚焦**后端已建成、前端没入口**。本文补它没覆盖的另一半——**前端已有入口、却走不通**——并把它做成可自动化的门禁；同时给出 UI、逻辑上的存量治理方案。
> 范围：Sage 主体（聊天、代理、Office、记忆、项目、设置、IPC 桥与后端）。**不含** Arena 账号 / 验证码 / 抽卡 / 临时邮箱相关模块，本文不对它们做任何优化建议。
> AGENTS.md 对照：原则 1（spec 先行）——本文即方案文档，未改任何业务代码；原则 2（单一所有者）——§7 给出在飞 PR 冲突登记；原则 5——在独立 worktree 完成。
> 修订（2026-10-03）：复核时发现原稿把 10px 直接映射到 `text-ui-xs`，与 `DESIGN.md` §4「xs 仅用于快捷键徽标」冲突。已改写 U1 方案第 2、3 步与 §10 第 5 项；U1「现状」里的字号计数补注了此前未列出的 2 处。其余内容未改。
> 实施后更正（2026-10-03）：批次 0 / 1 落地时发现本文有四处需要更正——L4 的松弛数字（§0、§3-L4、§8）、L1 门禁必须把主进程特判的流式命令建模、L1 的 12 条「从未接入」并非纯映射、`projects_create_session` 不能复用 `/open`（§10-3）。逐条证据与结果见 `docs/mcp-sage-optimization-implementation-20261003.md`。

## 0. 结论速览

**最大的缺口不是「缺功能」，而是「入口与能力之间的契约没人守」。** 本次扫描发现 **27 条前端 IPC 调用链走不通**，其中 13 条是 2026-09-18 一次合并（#857）回归删掉的，至少已存在 14 天。它们在此后所有 CI 全绿的合并里一直存在——因为前端单测都把 `invoke` 桩掉了，检索未见任何测试断言「前端用到的命令 ⊆ 桥里登记的命令」。

| # | 线 | 建议 | 优先级 | 估算 | 证据 |
| --- | --- | --- | --- | --- | --- |
| L1 | 逻辑 | IPC 桥修复 + 契约门禁（27 条断链、3 个静态测试） | **P0** | 2–3 天 | 已核实 |
| F1 | 功能 | Office / 项目两大主打能力端到端验收（L1 打通后补 e2e，把静默降级改为可见） | **P0** | 2 天 | 已核实 |
| L2 | 逻辑 | `commands.ts` 按域拆分（根因：单一热点文件 + 旧分支覆盖） | P1 | 1–2 天 | 已核实 |
| F2 | 功能 | 10-01 方案 P0-3 的前置：artifact 携带 workspace / format_spec | P1 | 3–4 天 | 已核实（现状） |
| L3 | 逻辑 | 静默失败：分级 + 棘轮（后端 349、前端 116 处） | P1 | 持续 | 启发式 |
| L4 | 逻辑 | 架构基线收紧（真实松弛 1,737 行 / 9 项；win7 线 3,743 行 / 24 项） | P1 | 0.5 天 | 已核实（已更正） |
| U1 | UI | 字号标尺落地：213 处 10/11px 绕过用户字号设置 | P1 | 2–3 天 | 已核实 |
| U2 | UI | 失败可见性规范（与 L3 联动） | P1 | 1 天 | 已核实 |
| L5 | 逻辑 | hex / legacy 双栈：5 组重复路由 + 注释与代码矛盾 | P2 | 1 天 | 已核实 |
| U3 | UI | i18n：约 1,892 处硬编码中文（取决于语言策略） | P2（先决策） | 持续 | 启发式 |
| U4 | UI | 无障碍补缺：8 处无名图标按钮 + lint 缺位 | P2 | 0.5 天 | 下界 |
| L6 | 逻辑 | Electron 21 冻结的代价：决策 + spike | P2（决策） | spike 3 天 | 事实已核实 |

建议顺序：批次 0（零风险收尾）→ 批次 1（L1、F1，P0）→ 批次 2（F2、U1、L3 首批）→ 批次 3（L2 拆分，等在飞 PR 合并）→ 批次 4（需先决策的 L5 / L6 / U3）。详见 §7。

## 1. 与既有文档的关系（不重复）

| 来源 | 项 | 本次核对的状态 | 本文处理 |
| --- | --- | --- | --- |
| 10-01 方案 | P0-1 / 2 / 4 / 5 / 6，P1-1 ~ 8，P2-2 / 5 / 6 / 7 | 已落地 | 不重复 |
| 10-01 方案 | P0-3 对话产物接入验收 | 未做，前置是 artifact 元数据 | → F2 |
| 10-01 方案 | P1-5 记忆 / 知识入口收敛 | 设置页侧已落地（`src/pages/settings/Settings.tsx:100` 注释：「记忆与知识」tab 已下线并入），方案 §5.1 表仍写「未做」 | 建议回填文档，不再立项 |
| 10-01 方案 | G2 failover chain | 未做 | 沿用「暂缓」，解锁条件见 §8 |
| UX-IA Round 3 | B-2 / C | 按其 §7.2 决策保持阻塞（#1867 / #1828） | 不触碰 |

## 2. 体检数据

| 维度 | 数据 |
| --- | --- |
| 规模 | 前端 `src` 非测试 89,196 行 / 497 文件，测试 56,626 行 / 418 文件；后端非测试 176,115 行 / 640 文件，测试 203,705 行 / 949 文件；`electron` 13,836 行 / 58 文件 |
| 大文件 | 非测试源码中 51 个超过 800 行（`architecture-policy.json` 上限）、14 个超过 1500 行。Top：`electron/main.ts` 2703、`backend/core/legacy/agent.py` 2527、`src/shared/api/types.ts` 2436、`backend/api/legacy_routes.py` 2367、`backend/orchestration/chat_dispatcher.py` 2257 |
| IPC 桥 | 命令表 212 条；真实应用注册 397 条 (verb, path)；命令表中 211 条能对上真实路由，1 条对不上；前端另有 26 个命令名在表中无定义（§3） |
| e2e | `e2e/` 仅 10 个受管文件：hermetic 4、live 4（侧栏技能与 wiki）、electron smoke 1、README；没有 Office / 项目 / Prompt / 审批相关流程 |
| 双轨 | 自 2026-09-15 起 `main` 645 个提交、`release/win7` 409 个（约为 main 的 63%） |
| 前端 UI | 按钮 563、`aria-label` / `aria-labelledby` 230、`role=` 113；任意字号 `text-[Npx]` 231 处，设计标尺 `text-ui-*` 仅 35 处；硬编码十六进制色 60 处（35 处在 wiki 图谱）；z-index 工具类 46 处、8 个取值 |
| 吞异常 | 后端 `except Exception` 1009 处，其中吞掉（pass / continue / 空返回）349 处、分布 169 个文件；前端空 catch 80 + `.catch(()=>noop)` 36 |
| 其他 | i18n 键 zh 1119 / en 1119（完全对齐）；后端 TODO / FIXME 仅 3 处；`React.lazy` 13、`memo` 7；已引入 `@tanstack/react-virtual` |

## 3. 逻辑线

### L1 · IPC 桥修复 + 契约门禁（P0）

**现象。** 前端经 `invoke(cmd)` → Electron 主进程 `invokeBackend` → 后端 HTTP。主进程只认命令表：`electron/invoke.ts:82-84` 对未登记命令抛 `UnknownIpcCommandError`，全仓没有第二个注册表或兜底转发。

**断链清单（共 27 条）。**

| 域 | 条数 | 命令 | 成因 |
| --- | --- | --- | --- |
| Office | 10 | `office_capabilities` `office_excel_recalc` `office_import_convert_legacy` `office_pdf_data` `office_pdf_fill_form` `office_pdf_preview` `office_pdf_read_form` `office_snapshot_diff` `office_template_thumbnail` `office_word_data` | #857 回归删除 |
| 项目 | 14 | 回归删除 1：`projects_update_allowed_paths`。从未接入 12：`projects_create_constraint` `projects_create_milestone` `projects_delete_constraint` `projects_delete_milestone` `projects_detect_type` `projects_git_status` `projects_import_constraints` `projects_list_constraints` `projects_list_milestones` `projects_update_constraint` `projects_update_milestone` `projects_update_type`。指向不存在的后端路由 1：`projects_create_session` | 见证据 |
| Prompt | 1 | `prompts_reorder` | #857 回归删除 |
| 聊天 | 1 | `agent_chat`（win7 分支仍保留该键，main 已无） | #857 回归删除 |
| Wiki | 1 | `wiki_chat_cancel`（`src/shared/api-client/wiki.ts:288`） | 从未接入 |

**证据链。**

- 回归提交 `08c06ba1f`（#857「三阶段 AI 工作区优化」，2026-09-18，单父提交）对 `electron/commands.ts` 的改动是 +35 / −73：键数 177 → 169，删 13 个、增 5 个。被删的 13 个就是上表标「#857 回归删除」的那些，至今仍被前端调用、仍未恢复。它们由 #845 / #920 / #1013 在 09-15 ~ 09-17 加入，#857 的分支基线早于这三个合入，符合「旧分支合并覆盖新增」的形态。
- 「从未接入」的 13 条：`git log -S` 限定 `electron/commands.ts` 检索，历史上从未出现过该键。
- `projects_create_session` 自 #727（2026-09-13）起映射到 `POST /api/v1/projects/*/sessions`，真实应用只有 `GET /api/v1/projects/*/sessions` 与 `POST /api/v1/projects/*/open`，没有 POST 该路径。
- 前端调用方可在静态检索中找到。`src/features/office/`：`OfficePreviewPanel.tsx`（PDF 预览 / Excel 重算）、`DocxNativePreview.tsx`（Word 原生预览）、`PdfFormFillDialog.tsx`（PDF 表单）、`OfficeSnapshotPanel.tsx`（快照对比）、`OfficeCapabilityBar.tsx`（能力条）；`src/features/project-type/`：`ConstraintManager.tsx`、`MilestoneManager.tsx`、`ProjectTypeSelector.tsx`、`GitStatusWidget.tsx`。个别封装（如 `office_pdf_fill_form`、`office_template_thumbnail`）是否有 UI 调用方未逐条确认。
- Win7 LTS 同样缺失（抽查 8 个键，main 与 win7 均无）。

**用户可见症状（已读源码核实）。**

| 入口 | 位置 | 失败表现 |
| --- | --- | --- |
| 审批框「项目级允许」 | `src/widgets/permission/ApprovalDialog.tsx:142` | 每次 `toast.error`，且不会继续批准 |
| Prompt 拖拽排序 | `src/pages/settings/PromptTemplatesTab.tsx:63-66` | 静默回滚（`catch { await load() }`），用户只看到条目弹回去 |
| Office 能力条 | `src/features/office/OfficeCapabilityBar.tsx:54-60` | 探测失败整条隐藏，无任何提示 |
| 侧栏「在项目里新建会话」 | `src/widgets/sidebar/sections/ProjectSection.tsx:323` | 弹出「打开失败」toast |
| 其余（PDF 预览 / 表单、Excel 重算、Word 原生预览、快照对比、约束 / 里程碑 / 类型、Git 状态） | `officeApi.ts`、`projectApi.ts` | 失败行为未逐条核实 |

**为什么 CI 一直是绿的。** 前端单测按 `desktopInvoke.ts` 的约定用 `vi.mock` 桩掉传输层；`electron/__tests__/commands.test.ts` 等检索 `COMMAND_ROUTES` 的测试只验证条目本身与 `UnknownIpcCommandError` 的形状；后端测试直接调路由。三层都对，中间那一层没有人守。

**方案。**

1. **先上门禁，只报告不阻塞。** 单一事实源是 `commands.ts`：
   - 新增 `scripts/export-ipc-manifest.mjs`（用 esbuild 转译并求值 `COMMAND_ROUTES`，以代理参数调用每个 `path()`，本次取证即用此法），生成 `electron/ipc-manifest.json`（method + 路径模板）。
   - **T1（vitest）**：扫描 `src/**` 非测试文件里的 `invoke('字面量')`，断言 ⊆ 清单键 ∪ 主进程 `sage:invoke` 里特判的流式命令（`wiki_chat_stream` / `wiki_ingest_stream`，它们在查 `COMMAND_ROUTES` 之前就被 `electron/main.ts` 分发，不算缺口）；并断言清单与 `COMMAND_ROUTES` 一致（防清单陈旧）。
   - **T2（pytest）**：导入真实 app，枚举 `app.routes`，断言清单里每条 (method, path) 都存在。比正则解析可靠——本次取证中正则版把 118 条存在的路由误判为缺失，因此不采用。
   - **T3（vitest）**：命令键不得重复（L2 拆分后用 spread 合并，重复键会静默覆盖）。
   - T1 / T2 各带一份「已知缺口允许名单」，初始即上述 26 + 1 条，名单**只减不增**。
2. **再修，按域分 PR，每个 PR 双轨落地。**
   - Office 10 条：原定义可由 `git show 08c06ba1f^:electron/commands.ts` 取回，**必须对照当前后端签名逐条核对**（#857 之后后端有改动），不要整段回贴。
   - 项目 12 条：后端路由已存在于 `backend/api/project_routes.py`，需新写映射。`projects_create_session` 需先定语义：改指 `POST /projects/{id}/open`（若其响应形态与 `ProjectOpenWire` 一致）或补后端 POST 路由。
   - `projects_update_allowed_paths`：由在飞 PR #1010 提供，本方案不重复加。
   - `prompts_reorder` 1 条；`wiki_chat_cancel` 需先确认后端取消端点；`agent_chat` 需先确认调用点是否仍有效，若是死代码则删前端封装。
3. **门禁转阻塞**：在 #1010 / #1626 / #1131 合并、允许名单清零之后。

**验收。** T1 / T2 / T3 在两条轨道上绿；允许名单 27 → 0；上表 4 个入口手测通过；F1 的 e2e 通过。

**冲突与风险。** `electron/commands.ts` 当前有 3 个在飞 PR（#1010、#1626、#1131）。修复条目先放进 L2 的新域文件，`commands.ts` 只多一行汇总，冲突面最小。

### L2 · `commands.ts` 按域拆分（P1）

`electron/commands.ts` 1381 行（策略上限 800，基线 1382，几乎零松弛），每个新能力都要改它，是仓库里最典型的冲突热点；#857 回归的根因正是「旧分支合并时覆盖了同文件的新增」。

- 方案：拆成 `electron/commandRoutes/{chat,sessions,memory,office,projects,skills,wiki,system,…}.ts`，`commands.ts` 只做 spread 汇总（目标 < 100 行）；T3 保证无重复键；清单脚本沿用 L1。
- 收益：冲突面按域隔离；`commands.ts` 可从架构基线移除一项。
- 顺序：等 #1010 / #1626 / #1131 合并后一次完成（AGENTS.md 原则 2）；之前 L1 的恢复条目已放进新域文件，不受影响。

### L3 · 静默失败：分级 + 棘轮（P1）

- 数据：后端吞异常处理器 349 处（`backend/wiki/files.py` 9、`backend/orchestration/chat_dispatcher.py` 7、`backend/orchestration/lane_registry.py` 7、`backend/tools/web_render.py` 7、`backend/api/llm_proxy_routes.py` 6……）；前端 116 处（空 catch 80 + `.catch(()=>noop)` 36，分布 61 个文件）。均为正则计数，属启发式。
- 与 `PHILOSOPHY.md`「反模式：静默失败」直接相关：L1 里已核实的 Prompt 排序、能力条两例，本质都是吞错。
- **不是全都该改**：前端靠前的文件多为本地存储的尽力而为（`src/entities/setting/storage.ts`、`src/entities/font/fontStorage.ts`、`src/entities/theme/storage.ts`），合理。
- 方案：
  1. 分级：A「用户发起的操作失败」必须可见；B「后台尽力而为」至少 `logger.debug` + 注释写明理由；C「本地存储 / 清理」允许。
  2. 工具：后端 ruff 的 `S110` / `S112` / `BLE001`，前端 `no-empty` 加自定义规则；以当前计数为**基线棘轮**（只降不增，对应 `architecture-baseline.json` 的做法）。
  3. 先治核心循环（上列 Top 文件）；`_record_artifact_safely`（`backend/tools/file_tool.py:144`，「内部已吞掉一切异常」）改为 `logger.warning`，与 F2 同批。
- 验收：基线数每批次单调下降；A 类清单清零。

### L4 · 架构基线收紧（P1）

`architecture-baseline.json` 共 72 项，其中 9 项存在真实松弛，合计 1,737 行；`backend/api/legacy_routes.py` 基线 3976、实际 2368，单项松弛 1,608 行（占 93%）。（原稿的「71 项 / 1808 行」是计数口径错误：基线按脚本的 `split('\n')` 记录，比 `wc -l` 每项多 1，用 `wc -l` 比对会把 72 个虚假的 1 行也算成松弛。`release/win7` 的真实松弛更大：24 项 / 3,743 行。）含义：该文件可以静默回涨 1600 行而 CI 不红——棘轮只防新增、没锁住已拿到的收益。此外功能 PR 常「按棘轮上调」基线，使上限只升不降。

- 方案：`architecture-check` 增加 `--tighten`，把基线下调到当前值；CI 增加「松弛 ≤ 5%」检查，或合并后自动开收紧 PR。首次一次性收紧 9 项（win7 线 24 项），零行为风险，约 0.5 天。
- 风险：基线文件本身是高冲突文件，收紧 PR 宜在 DSH 重构批次间隙快速合并。

### L5 · hex / legacy 双栈收敛（P2）

- 事实：`hex_routes.py` 与 `legacy_*_routes.py` 对同一 (verb, path) 重复定义 5 组：`POST /chat`、`GET /settings`、`PUT /settings`、`GET /preferences/*`、`PUT /preferences/*`。默认 `API_MODE` 是 `legacy`（`backend/main.py:987`），而同一段注释在 `:990` 写「API_MODE=hex（默认）」、在 `:997` 又写「缺省仍为 legacy」，自相矛盾。
- 后果：非默认栈的 settings / preferences 实现是死代码却仍要维护，改一处漏一处；注释误导读者。
- 方案：(1) 先改注释（5 分钟）；(2) settings / preferences 抽成同一个 application 服务，两栈委托同一实现，或删除 hex 副本；(3) `/chat` 双栈作为迁移灰度，设定删除日期。约 1 天，与 DSH 路线对齐。

### L6 · Electron 21 冻结的代价：先决策（P2）

- 事实：主线与 LTS 都固定在 Electron 21.4.4 / Chromium 106（`README.md:68-69`、`package.json` 为 `^21.4.4`）。原因写在 `docs/technical/20-electron.md`：21 是最后一版官方支持 Win7 的版本。代价是主线用户（Win10+ / macOS / Linux）也停在 2022 年的 Chromium。
- 已有缓解（本次核查）：渲染端 3 处 `dangerouslySetInnerHTML` 均有缓解——Mermaid 走 strict 模式、Shiki 输出、后端 `html.escape` 全转义的 docx 预览降级路径；docx 原生预览用了 DOMPurify；HTML 产物走沙盒 iframe。所以这**不是已存在的漏洞**，而是随时间累积的安全与维护负债。
- 建议：先做一个**决策**——是否解除「主线必须可 cherry-pick 到 win7」的约束。解除则做 3 天 spike（升到当前受支持的 Electron，跑 e2e smoke 与原生模块）；不解除则把该负债在文档里显式登记，并保持依赖审计门禁。

## 4. 功能线

### F1 · Office / 项目两大主打能力端到端验收（P0）

README 把「Office 全链路」放在第一位，项目类型 / 约束 / 里程碑是 09-24 的新增能力。L1 的清单显示这两块恰是最不通的，而 e2e 里一个相关流程都没有。

- L1 打通后补 4 个 e2e：Office 预览（PDF / Word）、项目「检测类型 → 加约束 → 加里程碑」、审批框「项目级允许」、Prompt 拖拽排序。
- 把静默降级改为可见（见 U2）：能力条探测失败显示「能力不可用：原因」，排序回滚给出 toast。
- 项目类型相关组件顺手补无障碍标签（U4：`src/features/project-type/ConstraintManager.tsx:161,164`、`src/features/project-type/MilestoneManager.tsx:185`）。
- 验收：4 个 e2e 在 CI 绿；手测清单见 L1。

### F2 · 10-01 方案 P0-3 的前置：artifact 携带 workspace / format_spec（P1）

10-01 方案 §4.2 已论证：对话产出的 docx 走 artifact 通路，验收抽屉走 taskCenter 通路，且 `lintWord` / `repairWord` 都强制要求 `format_spec`。现状（本次核对）：

- `backend/tools/office_create_tool.py:1557-1558` 只调用 `_record_artifact_safely(str(output), stat.st_size)`；该函数签名（`backend/tools/file_tool.py:144`）只有路径和大小，**不记录 workspace 与 format_spec**。
- 数据表 `artifacts` 在 `backend/data/database.py:1131`，仓储类在 `backend/data/artifact_repo.py:44`。

方案（最小改动）：

1. `_record_artifact_safely` 增加可选参数 `workspace_path`、`format_spec`；
2. 按现有迁移框架追加一步，给 `artifacts` 加两个可空列；
3. 产物接口返回这两个字段；
4. 气泡内产物 chip：有 `format_spec` 时显示「格式检查 / 一键修复」，打开现有的 `src/features/office/OfficeDeliveryDrawer.tsx`；无规范时显示「未指定规范」（抽屉本就支持，见 10-01 方案 §1.2）；
5. 记录失败改为 `logger.warning`（见 L3）。

验收：对话生成的 docx → 气泡 chip → lint 报告 → 一键修复；后端 artifact 往返测试、前端 chip 可见性测试、e2e 各一。风险：`database.py` 在架构基线内，迁移只追加不改核心；开工前核对 #1209（Office Round D）的改动面。

## 5. UI 线

### U1 · 字号标尺落地（P1）

- 规范：`DESIGN.md` §4 写明「所有操作界面文本**只能**采用」`text-ui-*` 标尺（xl 18 / lg 16 / base 14 / caption 13 / sm 12 / xs 10，其中 xs 仅用于快捷键徽标），且该标尺由用户可调的 `--ui-font-size` 驱动（`tailwind.config.js:93-98` 为 `calc(var(--ui-font-size, 14px) ± n)`）。
- 现状：任意字号 `text-[Npx]` 231 处（`10px` 115、`11px` 98、`18px` 7、`12px` 5、`15px` 2、`13px` 2，以上合计 229，余 2 处为其他取值；分布 81 个文件），标尺 `text-ui-*` 仅 35 处，采用率约 13%。
- 影响：这 213 处 10 / 11px 文本是固定像素，用户在设置里调大字号时它们不会跟着变——对低视力用户是实打实的问题；11px 还不在标尺内。
- 现有 lint 没有规则在守（`eslint.config.js` 只有 `import/no-restricted-paths`），规范只存在于文档。
- 方案：
  1. 先上 lint：用 `no-restricted-syntax` 禁止 className 字符串字面量中的 `text-[…px]`，**以 231 为基线棘轮**，新增即红；
  2. 再 codemod，**按目录分 PR**（一次改 81 个文件会与所有在飞 PR 冲突）。12px → `text-ui-sm`、13px → `text-ui-caption`、18px → `text-ui-xl` 可机械替换；**10px 与 11px 不能直接套，需设计决策**：`DESIGN.md` §4 规定 `text-ui-xs`（10px）仅用于快捷键徽标，而 10px 有 115 处，未必都是徽标（未逐处核实）；11px 则不在标尺内。做法：先把 10px 的 115 处按「快捷键徽标 / 其他」分类（徽标 → `text-ui-xs`），其余 10px 与全部 11px 二选一——
     - (a) 保持视觉不变：新增 `text-ui-2xs`（`--ui-font-size - 3px`）承接 11px，并把 `DESIGN.md` §4 里 `xs` / `2xs` 的适用范围改写为「次级元信息」；
     - (b) 并入 `text-ui-sm`（10px +2px、11px +1px）：与规范字面一致，但这些文本会整体变大；
  3. 每个 PR 附关键页面前后截图。10-01 方案 §8 与 `DESIGN.md` §10 都说 calm / dense 是主动选择，不放宽密度，(b) 与此冲突（最多影响 213 处文本），所以取舍必须由设计负责人拍板；建议倾向 (a)——密度不变，同时让这些文本跟随用户字号设置，正是 U1 要解决的问题。
- 验收：新增 `text-[Npx]` 为 0；基线逐批下降；把 `--ui-font-size` 调到 16px 时对应区域明显放大（手测）。

### U2 · 失败可见性规范（P1，与 L3 联动）

L1 已核实的三种形态：明确失败（审批框，有 toast）、静默回滚（Prompt 排序）、静默降级（能力条）。后两种违背「透明可控」。

- 规范：(a) 乐观更新失败回滚时必须 toast；(b) 能力探测失败显示「不可用 + 原因」，不整条隐藏；(c) 提供统一的 `reportActionFailure(contextKey, err)`（toast + `logger.warn` + i18n 文案），替代各处手写的 `toast.error(t(...).replace('{message}', errorMessage(err)))`。
- 验收：对前端 116 处吞错点按 L3 分级，A 类清零；新增代码被 lint 拦住。

### U3 · i18n 覆盖（P2，先决策）

- 事实：zh / en 键集完全对齐（各 1119 个），但剔除注释后界面里仍有约 1,892 处硬编码中文（字符串字面量 1,505 + JSX 文本 387，分布 172 个 `.tsx` 文件，占非测试 `.tsx` 的 61%）。用户可见属性中：toast 66、placeholder 31、`title` 91、`label` 108、`aria-label` 92。抽样确认是真实文案（如 `'开启公网通道？'`、`'无法保存演示模式设置'`）。启发式口径，可能含少量非界面字符串。
- 影响：英文界面会中英混杂；读屏软件会朗读中文标签。
- **先决策**：英文是否为正式支持的界面语言？是 → lint 棘轮（基线 ≈1,892）+ 按区域抽取（`RemoteWorkspacesTab` 55、`ChangesSection` 55、`GeneralTab` 54、`Skills` 53、`MemoryBrowser` 48、`FileChangeCard` 45）；否 → 在文档中标注英文为部分支持，避免误导。

### U4 · 无障碍补缺（P2）

- 现状不差：按钮 563、`aria-label` / `aria-labelledby` 230、`role=` 113。启发式下界：8 处无名图标按钮，全部集中在 `src/features/project-type/`（`ConstraintManager.tsx:161,164`、`MilestoneManager.tsx:185` 等）。
- `eslint.config.js` 与 `package.json` 里没有 `jsx-a11y` 插件。方案：补上并开启 `control-has-associated-label` 等规则，以现有违例为基线；92 处中文 `aria-label` 并入 U3。

## 6. 本文明确不做

- 不碰 Arena 相关模块，也不对其做任何优化建议。
- 不新增功能面（沿用 10-01 方案 §8）：本文所有「功能」项都是把已建成的能力接通、验收。
- 不做一次性大扫除：全部走「棘轮 + 分批」。
- 不立即升级 Electron：先做 L6 的决策。
- 不做 G2 failover：沿用暂缓，解锁条件见 §8。

## 7. 批次路线与冲突登记

| 批次 | 内容 | 双轨 | 说明 |
| --- | --- | --- | --- |
| 0 | L4 基线收紧；L5 注释更正；10-01 方案 §5.1 的 P1-5 状态回填 | main → win7 | 零行为风险，约 1 天 |
| 1 | L1：门禁（只报告）→ Office / Prompt / 项目修复（分 PR）；F1 的 e2e | **必须双轨**（win7 同缺） | P0，约 4–5 天 |
| 2 | F2；U1 的 lint + 首批 codemod；L3 核心循环首批；U2 | main → win7 | 多文件改动，按目录分 PR |
| 3 | L2 拆分；L1 门禁转阻塞 | main → win7 | 等 #1010 / #1626 / #1131 合并 |
| 4 | L5 完整收敛；L6；U3 | 视决策 | 需先决策 |

在飞 PR 冲突登记（`gh pr list --state open`）：

| PR | 占用 | 与本文的关系 |
| --- | --- | --- |
| #1010 allowed_paths | `electron/commands.ts`（新增 `projects_update_allowed_paths`、`attachment_rag_search`） | L1 不重复加该键；T1 允许名单保留它，合并后移除 |
| #1626 Office F1 / F2 | `electron/commands.ts`（新增 `office_doc_revision`） | L1 / F2 开工前核对 |
| #1131 端点限额 | `electron/commands.ts`（新增 `usage_by_endpoint`） | 同上 |
| #1209 Office Round D | Office 读缓存层 / 沙箱评审 / OCR 回退 | F2 开工前核对 office 工具改动面（未核对具体文件） |
| #1867 / #1868 | `Sidebar.tsx` 等（产品路线 A / B） | 本文不触碰 |
| #1828 / #1133 / #1334 | `RightPanel` / `Layout.tsx` / task-center | 本文不触碰 |

双轨成本：自 2026-09-15 起 win7 的提交数约为 main 的 63%。U1 的多文件 codemod 会放大 cherry-pick 冲突，所以「先棘轮、后分目录」。

## 8. 度量与验收

| 指标 | 现值 | 目标 |
| --- | --- | --- |
| 前端调用链走不通的 IPC 命令 | 27 | 0（门禁阻塞） |
| 前端用到但桥里未登记的 `invoke` 名 | 26 | 0 |
| 架构基线松弛行数 | 1,737（win7 线 3,743） | ≤ 100 |
| `electron/commands.ts` 行数 | 1,381 | < 100（汇总文件） |
| 后端 / 前端吞异常点 | 349 / 116 | 每批次单调下降；A 类清零 |
| `text-ui-*` 在字号用法中的占比 | ≈ 13% | ≥ 80%（新代码 100%） |
| 硬编码中文界面文案 | ≈ 1,892 | 先决策；决策后每批 -15% |
| e2e 受管文件 | 10（无 Office / 项目 / 审批） | +4（F1） |

G2 failover 的解锁条件（沿用 10-01 方案的暂缓结论）：`backend/api/legacy_routes.py` 降到 800 行以内，或端点选择逻辑已抽到 application 层。

## 9. 数据口径与局限

**已核实（直接证据）。** 命令表通过真实执行 `electron/commands.ts` 取得（212 条，0 个求值错误）；后端路由通过导入真实 app 枚举 `app.routes` 取得（397 条）；前端 `invoke('字面量')` 为静态扫描；回归定位用 `git log -S` 限定 `electron/commands.ts`，并对 `08c06ba1f^` / `08c06ba1f` 做键集合差；4 处用户症状逐处读了源码。

**启发式（仅作线索）。** 吞异常 / 空 catch 的正则计数；硬编码中文的计数；无名图标按钮（下界）；`text-[Npx]` 等字面量计数。

**已发现并弃用的口径。** 「后端路由无消费者」的正则普查有误报——例如 `model-catalog` 路由通过 `build_router()` 工厂挂载、前端经 `backendRequest` 漏斗调用，正则看不到；「命令表条目在后端无路由」的后缀匹配版本误判了 118 条。两者都**不作为结论**，只作为 L1 / T2 改用 `app.routes` 精确对账的动机。

**未做。** 没有运行 Electron 应用做手工验证；没有测前端运行时性能；没有评估 Arena 相关模块（范围外）。

## 10. 待决策

1. **L6**：主线是否继续受 Win7 约束（决定是否做 Electron spike）。
2. **U3**：英文界面是否为正式支持语言。
3. **L1**：`projects_create_session` 的语义——复用 `POST /projects/{id}/open`，还是补后端 `POST /projects/{id}/sessions`。**已按证据定：补后端路由。** `open` 优先复用最近活跃会话，而侧栏「+」要的是每次新建，复用 `/open` 会让它在已有会话时静默打开旧会话（实施记录 §1.5）。
4. **L1**：`agent_chat`、`wiki_chat_cancel` 是否仍需要。**已按证据处理：** `agent_chat` 无调用方 → 已删前端封装；`wiki_chat_cancel` 今天无害（hook 吞掉 rejection，真正的中止走 `sage:unlisten`）→ **仍待决策**：删掉这次调用，或在主进程实现带 owner token 的取消。
5. **U1**：≤ 11px 文本的处理口径——(a) 新增 `text-ui-2xs`、视觉不变，并改写 `DESIGN.md` §4 中 `xs` 的适用范围；还是 (b) 并入 `text-ui-sm`（10px +2px、11px +1px）。10px 的 115 处是否都是快捷键徽标，需先分类（见 U1）。
6. **批次 1** 是否直接开修复 PR。

## 附录：取证方法（可复现）

1. 命令表：用 esbuild 转译 `electron/commands.ts` 并求值，以代理参数调用每个 `path()`，导出 (method, path)。
2. 真实路由：临时目录作 cwd、`PYTHONPATH` 指向 worktree，在 `sage-backend` 环境导入 `backend.main` 并遍历 `app.routes`（避免在仓库根生成 `data/`）。
3. 前端调用：对 `src/**` 非测试文件匹配 `invoke(<泛型>)?('字面量'`。
4. 回归定位：`git log -S'<cmd>' -- electron/commands.ts`，再比较 `08c06ba1f^` 与 `08c06ba1f` 的键集合。
5. 症状：逐处阅读调用点源码，不依赖启发式。
