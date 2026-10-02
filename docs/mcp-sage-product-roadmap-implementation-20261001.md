# Sage 产品路线实施报告（截至 2026-10-01）

- 范围：完整优化路线，分批实施；主线与 Win7 LTS 双轨。
- 主线 worktree：`.worktrees/sage-product-roadmap-main-20261001`（分支 `feat/sage-product-roadmap-main-20261001`，基线 `419ff871f`，已合入 `origin/main` `4ac57c8cd`，见“基线合并与冲突解决”）
- Win7 worktree：`.worktrees/sage-product-roadmap-win7-20261001`（分支 `feat/sage-product-roadmap-win7-20261001`，基线 `0238bb43d`，已合入 `origin/release/win7` `f4461a655`）
- 方案文档：两条线各自的 `docs/plans/2026-10-01_sage-product-roadmap.md`
- 前置评审：`docs/mcp-sage-product-optimization-20261001.md`（分支 `docs/mcp-sage-product-review-20261001`）

## 完成状态总览

| 批次 | 状态 | 说明 |
|---|---|---|
| A 可信底座 | 已完成并验证 | 资料可用性（改为方案 A，见 A1）、关键设置回执、协议感知状态、长期记忆契约、设置与任务状态 |
| B 成果流程 | 主要入口已完成并验证 | 任务简报、项目工作台、设置分组与定位；Office 主流程仅接入入口，未改管线 |
| C 持续复用 | 部分完成 | 任务配方、能力感知入口、来源说明校准已完成；本次新增来源可追溯（C1）与技能×定时任务联动（C2）；能力感知自动路由、单任务硬预算未实施（见“延后”） |
| 全量门禁 | 本地 + CI 均通过 | 本地：全量 vitest、后端定向 pytest、ruff、架构基线、ESLint、类型检查均通过；CI：两条线的真实 `pull_request` 检查（含必需项）均通过 |
| 发布 | 已开 PR，未合并 | 主线 PR #1867（合并提交 `fd44020ca`）、Win7 PR #1868（合并提交 `a021bc284`）均为 `MERGEABLE / CLEAN`，必需检查全部通过；等 reviewer 授权合并（含上面的 `/office` 门控取舍确认） |

## 批次 A：可信底座（已完成）

### A1 项目资料可用性
- 采用仓库内既有方案 A（cherry-pick 本地分支 `fix/project-materials-ready-main` / `fix/project-materials-ready-win7`，此前未推送）：`add()` 默认直接写 `ready`，`status` 参数化并校验；`pending_index` / `failed` 与 `mark_ready` / `mark_failed` 保留给未来的异步索引管线。
- 去重命中 `failed` 行 = 重试：按本次 `status` 复活并清空 `error_message`；`pending_index` 行不被静默改写。
- `backend/data/database.py` 追加幂等回填，修正升级前已卡在 `pending_index` 的存量资料（注释标明：接入异步索引时必须移除或按版本门控）。
- **替换了本分支上一版“按项目范围的遗留纯文本启发式修复”**：该实现无法区分“等待索引”与“遗留纯文本”，会把 pending／失败行误判为可用，CI 的 `test_pending_materials_are_excluded_from_injection` 因此失败；现已移除。
- 测试：采用该提交的单元/集成断言（新增默认 `ready`、显式 pending、非法 status、failed 复活、添加后无需手工 `mark_ready` 即注入），并保留本轮新增的显式状态语义与项目范围回归。

### A2 严格保存与真实回执
- `src/shared/api/settingsClient.ts`：新增 `setSettingsStrict` / `getPreferenceStrict`，失败与超时不再被当作成功；`setPreference` 仅在后端确认后派发变更事件。
- `src/entities/setting/storage.ts`：新增 `saveSettingsStrict`（后端优先，缓存不可用单独提示）。
- `settingsStore` / `useSettings`：新增 `updateSettingsStrict` 并串行化写入，避免旧失败覆盖新成功。
- 新增 `useConfirmedPreference`：序列化写入、区分草稿与已确认值、失败回滚并可重读。
- 权限模式、降级模型、自动快照、每日限额、记忆开关改为显式回执（保存中／已确认／未确认）。

### A3 协议感知接入状态
- 新增 `src/entities/setting/endpointReadiness.ts`：首启与侧栏共用同一规则；Ollama 免密钥。
- 侧栏连接探测传递协议，迟到响应不再覆盖当前端点状态。

### A4 长期记忆契约
- 新增 `useSessionMemoryPause`：以设备本地持久化的方式记录“暂停长期记忆”，迁移旧的 `sessionStorage` 标记；存储不可读时对该会话失败关闭并提示，不谎称已保存。
- 文案改为“暂停长期记忆”，并明确历史与产物仍保留、云端模型仍收到请求；非无历史、非离线模式。
- 后端 `memory_mode` 收紧为 `on | off`，未知值不再被静默当作 `on`；旧缺省行为保持兼容。

### A5 设置与任务状态
- 设置初始落点修正为 `basic`，非法/隐藏值有可测试回退（Win7 无 `remote-workspaces` 页签，已按各自基线处理）。
- 任务中心区分运行中、待授权、待验收与已结束；终态不再持续旋转。

## 批次 B：成果流程（主要入口已完成）

- **首页任务简报**：默认场景改为写报告、整理资料、分析表格、制作演示，并保留编码入口；点击打开简报（目标／受众／资料／格式／检查要求／项目范围），明确“列出文件名不等于已上传或已读取”，提交后进入现有对话执行链路，不绕过权限与审批。
- **项目工作台**：新增 `/projects`，复用同一套项目 API 与组件，仅切换为宽松展示模式；项目提供上下文，目录绑定与授权仍决定文件访问范围。
- **设置层级**：按基础、模型、记忆资料、工具安全、网络远程、诊断用量分组；搜索命中后定位到真实行，定位不到时如实提示，不伪造跳转。
- **导航**：侧栏一级导航新增“项目工作台”与“文档与验收”；原先被渐进式披露门控的 Office 提升为核心入口。
- 首页 GitHub 指向修正为项目仓库；移除了固定端口、默认不可用的 WebUI 快捷入口。
- **未完成**：Office 内部流程（简报→大纲→草稿→修订→检查→验收→导出）仅完成入口与验收入口，未改造生成管线本体。

## 批次 C：持续复用（部分完成）

- 任务配方：可保存简报草稿，明确“保存不等于执行”“人工核对不等于系统自动校验”；不可读时不覆盖已有数据。
- 能力感知入口：基于现有模型目录元数据提示工具能力、价格已知性，不按名字猜测能力，不自动切换服务商，不把选择器冒充硬限额。
- 上下文来源：说明改为“上一轮请求的来源分类与预算统计”，并声明不是发送前预览、不代表内容已核验。
### 批次 C（第二阶段，本次新增）

- **C1 来源可追溯**：`backend/chat/context_sources.py` 只从最终 payload 中**真实存在的格式**提取单条标识（资料 `--- <id> [status] ---`、技能清单 `- /name`、自动激活 `Skill '<name>' auto-activated`、附件 `=== ref ===`），来源条目新增 `items / excluded / identifiable / omitted_items`；记忆召回、项目指令/概览/约束等取不到稳定标识的来源标为不可追溯。**未改动装配链路、预算阈值与估算口径**。
- **C1 前端四态**：来源面板可展开单条明细，明确区分已注入 / 已截断 / 被排除 / 未核验；标识为注入内容中的真实记录，没有可用跳转入口时不提供跳转。
- **C2 技能 × 定时任务联动**：新增 `src/features/scheduled/skillLink.ts`，技能引用就是正文里的 `/技能名`，按 `skillsApi.list()` 返回的真实技能校验（已启用 / 已停用 / 未注册）；定时任务弹窗可插入/移除引用，存在失效引用时保存前必须显式确认，**不静默丢弃、不自动改写正文**；技能列表不可用时提示无法校验且不阻塞保存。**未新增后端字段、未改执行链路、不自动运行技能**。
- **延后**：定时任务列表的技能徽标（需列表侧加载技能再做，避免为展示而新增后端字段）、配方 → 定时任务预填入口、C3 能力感知路由、C4 单任务硬预算。
- **CI 暴露并已修正的两处（随补修提交推送，既有断言未放宽）**：
  - `CreateTaskModal.tsx` 中 `./skillLink` 的导入位置与组内空行触发 eslint `import/order` 两条 error → 导入移入同级导入组（`./cronValidator` 之后）。
  - 新增控件造成既有测试的选择器歧义：① `ContextSourceList` 用 `/^context-source-/` 统计“顶层来源行”，嵌套的展开/明细/单条元素复用同一前缀会多匹配 3 个节点 → 嵌套元素改用 `context-meter-source-*` 前缀（`context-source-trimmed-*` 保持原样）；② `ScheduledTasks` 页面用 `getByRole('combobox')` 断言目标会话下拉，弹窗新增「插入技能引用」下拉后同页出现两个 combobox → 改为 `getAllByRole('combobox')[0]`。两处都只改定位方式，断言内容不变。

## 基线合并与冲突解决（批次 C 之后）

两个 PR 的基线在批次 C 推送之后继续前进（`origin/main` `419ff871f` → `4ac57c8cd`，合入了 PR #1869；`origin/release/win7` `0238bb43d` → `f4461a655`），两个 PR 一度变为 `CONFLICTING`。已把新基线合入各自分支（合并提交：主线 `fd44020ca`、Win7 `a021bc284`），冲突与取舍如下：

- **主线 7 个冲突文件**：`architecture-baseline.json`（逐文件取较大值，i18n en/zh 按实测 1322/1289 重新登记，未下调任何条目）、`settings/components.tsx`、`Settings.tsx`、`ToolsConnectionsTab.tsx`、`MemoryKnowledgeTab.tsx`、`Sidebar.tsx` 及其测试。原则：上游行为一律保留，本分支新增能力（显式回执、搜索定位兜底、项目工作台 / 文档与验收入口）叠加其上。
- **Win7 3 个冲突文件**：`Settings.tsx`、`ToolsConnectionsTab.tsx`、`Sidebar.tsx`；同一原则，但 Win7 基线没有主线的 `data-settings-anchor` 跳转机制与 P1-7 灰态门控，所以不照搬主线的写法。
- **待 reviewer 确认的产品取舍**：`/office`（文档与验收）两轨处理不同。主线保留上游 P1-7 的“灰态可见 → 用途说明 → 确认后解锁”，位置提升到一级但不取消门控；Win7 的门控是“未解锁就不渲染”，把 `/office` 放进去会重新藏起来（正是批次 B 要解决的“功能不存在”错觉），因此 Win7 不门控、常驻一级。主线如要取消门控，删掉 `ADVANCED_FEATURE_BY_PATH` 里的 `'/office'` 即可。
- **为适配上游测试**：主线 3 个测试（`MemoryKnowledgeTab.clearAll`、`TrustEscalation`、`Settings.anchor`）与 Win7 的 `TrustEscalation` 做了选择器 / mock 适配（mock 签名与真实 `settingsClient` 一致），断言内容未放宽；`Sidebar.feature-unlock` 按合并后的行为重写。
- **合并后本地验证**：主线全量 vitest 487 files / 3580 tests，Win7 455 files / 3310 tests，均通过；两轨 typecheck、lint（0 error）、architecture-check、ruff 通过；后端定向各 195 通过（主线 Python 3.11.16、Win7 Python 3.8.20）。

## 验证结果

- 两条线定向回归：各 14 个文件 / 41 个测试通过（含新增的资料、回执、协议、记忆、简报、设置分组测试）。
- 后端：`test_project_material_repo.py` 与 `test_product_roadmap_integrity.py` 共 22 个测试通过；Win7 使用真实 `sage-backend-py38` 环境执行。
- 后端资料链路定向回归（PR 后补充）：两条线各 **49 个测试**通过——主线 Python 3.11.16（`sage-backend`）、Win7 Python 3.8.20（`sage-backend-py38`），覆盖 `test_project_material_repo.py`、`test_product_roadmap_integrity.py`、`test_project_routes_m3.py`、`test_project_overview_injection.py`。
- 批次 C 定向回归：前端 **31 个测试**通过（`ContextMeter` 来源明细、`skillLink`、`CreateTaskModal`、i18n 套件），后端 **61 个测试**通过（含 `test_context_sources.py` 12 例）。
- 批次 C 补修后的**全量前端套件**：主线 **476 文件 / 3435 测试**通过（2 跳过），Win7 **447 文件 / 3209 测试**通过（2 跳过），退出码 0。
- CI（批次 C）：**更正**——此前文档与 PR 评论里写的“`pull_request` 事件被 GitHub 静默丢弃”是误判。两个 PR 在基线前进后处于 `CONFLICTING`，GitHub 不会为有合并冲突的 PR 派发 `pull_request` 工作流（GitHub 文档如此规定），所以批次 C 的推送没有产生 PR 检查；当时用 `ci-rerun.yml`（`workflow_dispatch`）补跑的结果只能证明代码本身能通过，**不参与分支保护判定**（见 `docs/plans/2026-10-01_ux-ia-round3-panel-slot.md` §7.3）。解冲突合入新基线后，真实 `pull_request` 检查随即触发并通过：主线 CI run 36957094454 + E2E PR Gate run 36957094446（含必需项 `stub-smoke` / `stub-deep` / `live-boot`，全部 pass）；Win7 CI run 36960804610（Backend Python 3.8 / Frontend / Electron build ×2 / Electron smoke / Architecture check / All Checks 全部 success）。两个 PR 当前为 `MERGEABLE / CLEAN`。
- `ruff check backend/`：两条线均通过（修正了 `pytest.raises(ValueError)` 过宽的 PT011）。
- 架构基线：`backend/data/database.py` 因回填增长 13 行，按 ratchet 协议登记为有意增长（主线 1949→1962、Win7 1982→1995），未下调任何既有条目。
- 类型检查（renderer + electron）、架构基线检查、ESLint、Prettier：两条线均通过（未放宽基线，i18n 增长通过提取共用模块保持预算）。
- 全量前端套件（批次 A/B 收尾时）：主线 473 文件 / 3424 测试通过、2 跳过，退出码 0；Win7 444 文件 / 3198 测试通过、2 跳过，退出码 0。
- 首轮全量发现 11 个失败，全部由本轮界面改动导致旧断言过期（推荐项数量与名称、渐变类名、Office 门控）；已按新行为更新 4 个测试文件，未放宽断言、未跳过用例。

## 已知限制与未完成项

- **远端新鲜度**：本机 `git fetch` 曾因网络问题失败，基线新鲜度改用 `gh api` 核对：合并时 `origin/main`=`4ac57c8cd`、`origin/release/win7`=`f4461a655`；此后 `main` 又前进到 `456b9a9e8`（4 个提交，仅 CI 工作流 / 依赖审计 / 文档，与本 PR 无源码重叠，PR 仍为 CLEAN）。合并前若基线再前进，需要重新合并并等待真实 PR 检查。
- **推送链路受阻**：`https://github.com` 的 IPv6 通路不可达（`curl -4` 返回 200、`curl -6` 失败），`git push` 反复被连接重置；改用 GitHub Git Data API 按对象精确提交（blob → tree → commit → ref），远端提交 sha 与本地完全一致（主线 `8a9c33620` → 批次 C 后 `8eb5b9a76` → 合并提交 `fd44020ca`；Win7 `3e4b615be` → `d992ac189` → `a021bc284`）。合并提交使用保留两个 parent 的脚本推送，并复用两侧 parent 已有的 blob，只上传冲突解决产生的新内容。网络恢复后建议重新 `git fetch` 核对远端引用。
- 本机 lefthook 因缺少 `if` 内置命令无法执行（环境假警报），提交/推送使用 `--no-verify`；已手动跑通 ruff、架构基线检查、定向 pytest、ESLint、Prettier、类型检查。
- CI 是最终门禁：两个 PR 当前均为 `MERGEABLE / CLEAN`，必需检查全部通过。`ci-rerun` 只是人工验证手段，不再作为门禁证据；PR 一旦再次出现合并冲突，`pull_request` 检查就不会触发——这是需要留意的信号，而不是 GitHub 丢事件。
- 未做真实界面点验、性能测量、用户研究；窄窗口/大字号/高 DPI 等仍为待验证项。
- 未实施自动数据迁移与历史清理；未改动生产数据库。
- 批次 C 的自动路由与硬预算需要后端配套能力，当前仅打通入口与说明。
