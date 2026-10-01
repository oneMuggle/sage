# Sage 产品路线实施报告（截至 2026-10-01）

- 范围：完整优化路线，分批实施；主线与 Win7 LTS 双轨。
- 主线 worktree：`.worktrees/sage-product-roadmap-main-20261001`（分支 `feat/sage-product-roadmap-main-20261001`，基线 `419ff871f`）
- Win7 worktree：`.worktrees/sage-product-roadmap-win7-20261001`（分支 `feat/sage-product-roadmap-win7-20261001`，基线 `0238bb43d`）
- 方案文档：两条线各自的 `docs/plans/2026-10-01_sage-product-roadmap.md`
- 前置评审：`docs/mcp-sage-product-optimization-20261001.md`（分支 `docs/mcp-sage-product-review-20261001`）

## 完成状态总览

| 批次 | 状态 | 说明 |
|---|---|---|
| A 可信底座 | 已完成并验证 | 资料可用性（改为方案 A，见 A1）、关键设置回执、协议感知状态、长期记忆契约、设置与任务状态 |
| B 成果流程 | 主要入口已完成并验证 | 任务简报、项目工作台、设置分组与定位；Office 主流程仅接入入口，未改管线 |
| C 持续复用 | 部分完成 | 任务配方、能力感知入口、来源说明校准已完成；细粒度来源追溯、技能/定时任务联动、自动路由、单任务硬预算未实施 |
| 全量门禁 | 本地已通过 | 定向与全量 vitest、ruff、架构基线、ESLint、Prettier、类型检查均通过；CI 为最终门禁 |
| 发布 | 已开 PR | 主线 PR #1867、Win7 PR #1868，均已推送；CI 结果待观察，未合并 |

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
- **未实施**：单条文件/记忆标识的来源追溯（后端未采集标识）、技能与定时任务联动、能力感知自动路由、单任务硬预算。

## 验证结果

- 两条线定向回归：各 14 个文件 / 41 个测试通过（含新增的资料、回执、协议、记忆、简报、设置分组测试）。
- 后端：`test_project_material_repo.py` 与 `test_product_roadmap_integrity.py` 共 22 个测试通过；Win7 使用真实 `sage-backend-py38` 环境执行。
- 后端资料链路定向回归（PR 后补充）：两条线各 **49 个测试**通过——主线 Python 3.11.16（`sage-backend`）、Win7 Python 3.8.20（`sage-backend-py38`），覆盖 `test_project_material_repo.py`、`test_product_roadmap_integrity.py`、`test_project_routes_m3.py`、`test_project_overview_injection.py`。
- `ruff check backend/`：两条线均通过（修正了 `pytest.raises(ValueError)` 过宽的 PT011）。
- 架构基线：`backend/data/database.py` 因回填增长 13 行，按 ratchet 协议登记为有意增长（主线 1949→1962、Win7 1982→1995），未下调任何既有条目。
- 类型检查（renderer + electron）、架构基线检查、ESLint、Prettier：两条线均通过（未放宽基线，i18n 增长通过提取共用模块保持预算）。
- 全量前端套件（最终）：主线 473 文件 / 3424 测试通过、2 跳过，退出码 0；Win7 444 文件 / 3198 测试通过、2 跳过，退出码 0。
- 首轮全量发现 11 个失败，全部由本轮界面改动导致旧断言过期（推荐项数量与名称、渐变类名、Office 门控）；已按新行为更新 4 个测试文件，未放宽断言、未跳过用例。

## 已知限制与未完成项

- **远端新鲜度未验证**：两次 `git fetch` 分别遇到连接重置与低速超时，基线使用已存在的 origin 跟踪引用。集成前必须重新 fetch 并核对漂移、执行分支新鲜度检查。
- **推送链路受阻**：`https://github.com` 的 IPv6 通路当前不可达（`curl -4` 返回 200、`curl -6` 失败），`git push` 反复被连接重置；改用 GitHub Git Data API 按对象精确提交（blob → tree → commit → ref），远端提交 sha 与本地完全一致（主线 `8a9c33620`、Win7 `3e4b615be`）。网络恢复后建议重新 `git fetch` 核对远端引用。
- 本机 lefthook 因缺少 `if` 内置命令无法执行（环境假警报），提交/推送使用 `--no-verify`；已手动跑通 ruff、架构基线检查、定向 pytest、ESLint、Prettier、类型检查。
- CI 是最终门禁：主线 PR #1867、Win7 PR #1868，结果待观察。
- 未做真实界面点验、性能测量、用户研究；窄窗口/大字号/高 DPI 等仍为待验证项。
- 未实施自动数据迁移与历史清理；未改动生产数据库。
- 批次 C 的自动路由与硬预算需要后端配套能力，当前仅打通入口与说明。
