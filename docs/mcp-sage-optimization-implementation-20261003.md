# Sage 优化方案实施记录 · 批次 0 + 批次 1（2026-10-03）

> 对应方案：`docs/plans/2026-10-02_ui-feature-logic-optimization-followup.md`。基线：`origin/main` @ `38c5f7992`、`release/win7` @ `6069b48e5`。
> **状态（2026-10-03）：已 push 并按域开 PR（#1890–#1897，见 §2），均未合并。** 写下初稿时它们还都是本地提交。提交与推送用了 `LEFTHOOK=0` / `--no-verify`：未引导的 worktree 里 lefthook 的 pre-commit 在 Node 层直接崩溃（与改动无关）；该钩子只对 `backend/**/*.py`、`src/**/*.{ts,tsx}` 生效，已手动跑了等价的 ruff / eslint / prettier。按 AGENTS.md 原则 4，推送时须在 PR 描述里说明。
> 没有运行 Electron，没有手测任何界面；验证是静态检查 + 单元 / 契约测试 + 对真实 FastAPI app 的路由核对（见 §3）。

## 0. 结论速览

- 批次 0（L4、L5、P1-5）与批次 1 的 L1（门禁 + 全部可修的断链）已在 main 与 win7 两条线实现并开 PR（未合并）。F1（4 个 e2e）**没做**，原因见 §5。
- **方案有四处需要更正**（§1）。其中两处会直接影响结论：L4 的松弛数字是错的；「12 条从未接入」不是纯映射——接通后会在运行时暴露前后端从未联调过的契约错误。
- 实施中修掉了方案没预料到的 3 个真问题：PDF 表单填写会静默丢字段（Office）、项目类型检测在 UI 上显示 `[object Object]` 或直接抛错、侧栏「+」永远 404。

## 1. 对方案的更正

### 1.1 L4 松弛数字（方案 §0 / §3-L4 / §8）

方案写「72 项里 71 项松弛，共 1808 行」。**真实是 9 项、1,737 行。** 基线按脚本的 `split('\n').length` 记录，比 `wc -l` 每项多 1；用 `wc -l` 对账会把 72 个虚假的 1 行也算成松弛（`wc -l` 口径重算得 1,809 行 / 72 项，与原稿的 1,808 / 71 基本一致，印证了原因）。`legacy_routes.py` 仍是大头：基线 3976、实际 2368，松弛 1,608（占 93%）。`release/win7` 的真实松弛更大：24 项 / 3,743 行（`legacy_routes.py` 1,655、`office/word.py` 505、`browser_tool.py` 386）。

### 1.2 L1 门禁必须把主进程特判建模

`electron/main.ts` 的 `sage:invoke` 在查 `COMMAND_ROUTES` 之前就特判了 `wiki_chat_stream`、`wiki_ingest_stream`。静态扫描渲染端会得到 28 个「未登记」命令 = 方案登记的 26 条真缺口 + 这 2 个正常工作的流式命令。T1 因此由测试解析 `main.ts` 得到这个集合（解析不到会明确报错，不会静默放行）。

### 1.3 项目域 12 条「从未接入」不是纯映射

方案写「后端路由已存在，需新写映射」。逐条对照后端路由与请求模型（全部 `extra="forbid"`）后：

| 问题 | 后果（若只补映射） | 处理 |
| --- | --- | --- |
| `detectType`：后端返回 `{project_type, confidence, signals:[{type,weight}]}`，前端按 `{detected_type, …, signals:string[]}` 解析 | 路由 200，但 `detectedType` 为 `undefined`；`ProjectTypeSelector` 的 `join('、')` 显示 `[object Object]`，`TypeDetectionPreview` 把对象当 React 子节点渲染会抛错 | 前端映射到 UI 需要的形状（`signal.type` 本身就是可读文案） |
| 约束 / 里程碑的 update、delete：后端路由是 `/projects/{project_id}/…/{id}` 且按项目校验归属，前端只传实体 id | 路径缺 project_id | 4 个 API 方法加 `projectId` 参数，5 个调用点（组件作用域里本来就有 `projectId`） |
| 创建里程碑时前端表单带 `status`，`MilestoneCreateRequest` 没有该字段 | 422 | 映射按后端字段白名单取值，丢弃 `status`（新里程碑为 pending） |
| `projects_import_constraints`：前端传 `category`，后端字段叫 `template` | 422 | 映射里换名 |

这几个方法此前在测试里**零引用**；新增了测试覆盖。

### 1.3.1 创建里程碑时的「状态」字段是个遗留的产品缺口

编辑器的创建表单有「状态」下拉，但后端创建接口不接受它，现在被映射层静默丢弃。要么给 `MilestoneCreateRequest` 加 `status`，要么创建表单隐藏该字段——需要产品决策，本次未动。

### 1.4 Office `office_pdf_fill_form` 的潜伏 bug

旧映射（#857 之前）让桥的 camelCase→snake_case 递归改写了 `data` 里的键，而 `data` 是「PDF 表单字段名 → 值」，后端按名字精确匹配并**静默忽略未命中项**：`firstName` 被改成 `first_name`，`Name` 被改成 `_name`，表单显示保存成功但这些字段是空的。恢复时改用 `rawBody` + 显式 snake_case 顶层键。去掉 `rawBody` 时回归测试变红（`Name` → `_name`），已实测。

### 1.5 `projects_create_session`：更正我之前的建议

我曾建议「先复用 `POST /projects/{id}/open`」。证据相反：`open_project` 的语义是**优先复用最近活跃会话**，而前端 `createSession` 的注释是「显式新建一个绑定会话」（侧栏项目行「+」）。复用 `/open` 会让「+」在已有会话时静默打开旧会话。已改为补后端 `POST /projects/{id}/sessions`（总是新建，201，响应与 `/open` 同形）。

### 1.6 `agent_chat`、`wiki_chat_cancel`

- `agent_chat`：唯一调用点 `chatApi.chat()` 在 src 与测试里**没有任何调用方**（前端只走 `chatStream`）。按方案原则「无调用方即删封装」，已删除。
- `wiki_chat_cancel`：后端没有对应端点，主进程也没实现。但它**今天无害**——hook 清理时 `cancelWikiChatStream(...).catch(() => {})` 吞掉 rejection，真正的中止由 `sage:unlisten` → `streamControllers` 完成。保留在已知缺口名单里，**待你决策**（§5）。

### 1.7 win7 线的差异

win7 渲染端没有 Prompt 拖拽排序（`prompts_reorder` 只在 main），且仍注册着 `agent_chat`；所以 win7 上**跳过** prompts 与 chatApi 删除两个提交。win7 的已知缺口是 Office 10 + 项目 13 + wiki 1。

## 2. 分支与提交

main 线（前三条基于 `origin/main`，后四条基于门禁分支 #1890；领域 PR 的 diff 会带上门禁的 2 个提交，先合哪个都能干净合并）：

| 分支 | PR | 提交 | 内容 |
| --- | --- | --- | --- |
| `chore/arch-baseline-tighten-20261003` | #1891 | `4b4d57b15` `5b2d2ff4e` | `architecture-check` 增加 `--tighten` / `--max-slack`（保格式的文本级改写，只降不升）+ 9 个测试；基线一次性收紧 9 项（松弛 1,737 → 0） |
| `chore/batch0-comment-backfill-20261003` | #1892 | `fb27e69c4` `2707a856f` | L5：更正 4 处「API_MODE 缺省 hex」的过时表述（`main.py`、`hex_routes.py`、`02-architecture.md`、`18-hexagonal.md`）；10-01 方案 P1-5 状态回填 |
| `feat/ipc-contract-gate-20261003` | #1890 | `df1083375` `5d57063fa` | `commandRoutes/` 域路由表汇总（`commands.ts` 只加 3 行）；L1 门禁：`scripts/export-ipc-manifest.mjs`、`electron/ipc-manifest.json`、T1 / T3（vitest）、T2（pytest）、`electron/ipc-known-gaps.json` |
| `fix/ipc-bridge-office-20261003` | #1893 | `4e8d50578` | 恢复 Office 10 条（含 §1.4） |
| `fix/ipc-bridge-projects-20261003` | #1894 | `027950139` `d84d5888d` | 项目域 12 条映射；前端 API 层契约对齐（§1.3） |
| `feat/project-create-session-20261003` | #1895 | `045857a96` | 后端 `POST /projects/{id}/sessions`（§1.5）；`project_routes.py` 基线 838 → 849 |
| `fix/ipc-bridge-misc-20261003` | #1896 | `cceff58b0` `ea7c3318e` | 恢复 `prompts_reorder`；删除无调用方的 `chatApi.chat()` |

win7 线：`chore/ipc-contract-win7-20261003`（**#1897**，base `release/win7`，10 个提交，`cherry-pick -x` 保留来源）：arch-check、win7 基线收紧（24 项）、L5、P1-5、汇总层、门禁（manifest 与名单按 win7 重新生成）、Office、项目桥映射、项目前端契约、会话路由。

实现要点：
- 门禁的 manifest 用 TypeScript 自带的 `transpileModule` + 极小的 CommonJS 加载器求值，不引入 esbuild 这个隐式依赖；加载器拒绝包导入，以此强制路由模块保持纯净。
- 已知缺口名单**只减不增**：新缺口红，已修复却未删的条目也红。
- `wiki_chat_cancel` 与 `projects_update_allowed_paths`（由在飞 PR #1010 提供）是合并全部分支后名单里仅剩的两条。

## 3. 验证证据

- **门禁有牙**：5 种变异均被拦截——模拟 #857（删被调用的命令）、渲染端新增未登记调用、重复键、过期名单条目、manifest 指向不存在的路由。
- **请求体对真实后端校验**：用渲染端的典型参数生成请求体，交给后端真实的 pydantic 请求模型校验，项目域 7 类全部接受（一次性验证，未提交）。
- **T2**：每条 manifest 的 (method, path) 在真实 FastAPI `app.routes` 里都存在。
- **集成演练**（scratch worktree，已丢弃）：把 4 个领域分支合到门禁分支上——93 个前端测试文件、126 个后端测试全过，两套 `tsc` 退出码 0，manifest 235 条。**这次演练发现了会话分支缺基线上调**（单独开 PR 会让 `architecture-check` 变红），已修。
- **win7（Python 3.8.20）**：契约 + 会话路由 + 项目集成共 14 个测试通过；前端 65 个测试文件通过，两套 `tsc`、eslint 通过，manifest 220 条。
- **冲突预演**：用 `git merge-tree` 对在飞 PR 做试合并并扣除对照组（`origin/main × 该 PR`）：#1626、#1131、#1209 **无新增冲突**；#1867 仅 `architecture-baseline.json` 一个文件；#1010、#1334 无本地分支，**未验证**。

局限：T1 只跟进同文件内的 wrapper（跨文件 wrapper 不跟进）；没有 UI 手测；下面 §6 是手测清单。

## 4. 合并顺序与冲突预期

1. 先合 `chore/arch-baseline-tighten-20261003`（基线文件是高冲突文件，收紧 PR 宜快）；其后合入的分支若改了同一行基线，取较大值或用 `node scripts/architecture-check.mjs --tighten` 重新对齐。
2. 再合 `feat/ipc-contract-gate-20261003`（后四条依赖它）。
3. 其余四条任意顺序。已实测：合并时 `index.ts` 与 `ipc-known-gaps.json` 会有「各加一行 import/spread、各删一组名单」的并集型冲突（机械可解）；`ipc-manifest.json` 一次都没冲突，真冲突时直接 `npm run ipc:manifest` 重新生成。
4. 合并后名单里仅剩 `projects_update_allowed_paths`（#1010 合并后删除该条）与 `wiki_chat_cancel`。
5. 已按 AGENTS.md 先 `git fetch` 确认 base 未移动（`origin/main` 仍是 `38c5f7992`、`release/win7` 仍是 `6069b48e5`）后推送；各 PR 描述里已写明 `--no-verify`。win7 PR 对 4 个在飞 win7 PR（#1868、#894、#862、#852）试合并无新增冲突。

## 5. 没做的 / 待决策

- **F1（4 个 e2e）没做。** 这仓库的 e2e 用 Playwright + Vite dev server，且 `playwright.config.ts` 的 `reuseExistingServer: !process.env.CI` 会在 1420 端口上静默复用别人已经起着的 dev server——在 worktree 里跑出来的结果可能测的是另一份代码。要做需要单独一轮：从 worktree 起 Vite 到空闲端口并覆盖 `baseURL`，沿用 `tests/e2e/journal.spec.ts` 的 IPC mock 写法。我没法在这里看到浏览器界面调选择器，不交付未验证的 e2e。
- **待你决策**：① `wiki_chat_cancel`——删掉这次调用，或在主进程实现带 owner token 的取消；② 创建里程碑时的「状态」字段（§1.3.1）；③ 方案 §10 的 L6（Win7 约束）、U3（英文界面）、U1（≤ 11px 口径）三项，本次未涉及。
- 批次 2 / 3 / 4（F2、U1、L3、U2、L2、L5 完整收敛、L6、U3）未动。
- `--max-slack` 已实现但**没有接进 CI**（避免让在飞 PR 意外变红）；L1 门禁转阻塞的条件不变：#1010 / #1626 / #1131 合并、名单清零之后。

## 6. 手测清单（我没有运行界面）

- 设置 → Prompt 模板：拖拽排序后刷新，顺序保持（此前会弹回且无提示）。
- Office：PDF 预览、Word 原生预览、Excel 重算、快照对比、能力条、PDF 表单（用一份字段名带大写 / 驼峰的表单，填写后字段应有值）。
- 项目：创建向导选目录，「检测依据」应显示文案而非 `[object Object]`；约束新增 / 编辑 / 删除 / 导入模板；里程碑新增 / 改状态 / 删除；Git 状态 widget；侧栏项目行「+」每次都新建一个会话。
- 审批框「项目级允许」依赖 #1010，本次未修，仍会失败。

## 7. 复现

- 前端：`node node_modules/vitest/vitest.mjs run electron/__tests__ src/shared/api/__tests__`（worktree 内用根检出的 `node_modules`）。
- 后端：在 `backend/` 下 `<sage-backend 的 python> -m pytest tests/contract tests/unit/api/test_project_create_session.py`；win7 线用 `sage-backend-py38`。
- 重新生成 manifest：`npm run ipc:manifest`；检查是否陈旧：`npm run ipc:manifest:check`。
- 基线：`node scripts/architecture-check.mjs --tighten`；松弛检查：`--max-slack=N`。
