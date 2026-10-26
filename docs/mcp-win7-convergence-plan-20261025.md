# Win7 ↔ Main 收敛计划（2026-10-25）

> 触发背景：`Win7 Sync` 的自动合流已失效——`auto_sync` 在 933 个未并入 commit 上产出 410 个冲突文件，且 `GITHUB_TOKEN` 无法推送 `.github/workflows/**`，导致 sync job 恒定失败。本文件把「整体 merge」降级为「按批次 + 三分法」的可审计收敛流程。

## 1. 基线快照

| 时点 | main | release/win7 | 异动文件 | main-only | real | 需动作 |
|---|---|---:|---:|---:|---:|---:|
| 派发前 | `0d687001` | `2cf64d73` | 983 | 233 | 421 | 714 |
| 批次 1 后 | `a91df263` | `98217ae2` | 706 | 29 | 348 | 437 |

- merge-base `476904b4096c`；main ahead **935** / win7 ahead **1267**。
- 分层：`typing-only 123`（py38 回写，必要差异）/ `frozen 16`（D 类冻结件）/ `intentional 130`（已登记）/ `win7-only 60`。

## 2. 收敛法则（不可违背）

1. **只收敛 `grade ∈ {main-only, real}`**。`intentional`、`frozen`、`typing-only`、`win7-only` 一律不动。
2. **必须做三分法判定**，禁止无脑取 main：

   | 判定 | 条件 | 处置 |
   |---|---|---|
   | `safe-take-main` | win7 blob == merge-base blob 且 main 已改 | 直接取 main |
   | `win7-ahead-keep` | main blob == merge-base blob | 保留 win7，跳过 |
   | `both-changed` | 三方互不相同 | 需人工 3-way，不自动合 |
   | `no-base` | merge-base 无此文件 | 需人工比对，不自动合 |
   | `win7-deleted` | win7 侧不存在 | 需人工确认后补回 |

3. **分支本地校验件不得被 main 覆盖**：`architecture-baseline.json`、`scripts/`、`.github/workflows/`。它们的正确值取决于本分支的代码规模与工作流语义。
4. 内容一律复用 main 的 **blob sha** 建树，不做文本改写，保证 LF 与零漂移。
5. 每批次独立 PR → 双轨 CI 全绿 → squash merge。

## 3. 三分法判定结果（对 377 个待动作文件）

| 区域 | safe-take-main | both-changed | win7-ahead-keep | win7-deleted | no-base | absent-on-main |
|---|---:|---:|---:|---:|---:|---:|
| backend | 4 | 36 | 4 | 0 | 34 | 0 |
| backend/tests | 6 | 29 | 9 | 1 | 39 | 1 |
| src | 6 | 85 | 0 | 0 | 52 | 0 |
| electron | 1 | 14 | 5 | 0 | 19 | 0 |
| scripts | 1 | 2 | 0 | 0 | 9 | 0 |
| docs | 0 | 0 | 0 | 0 | 1 | 6 |
| root | 2 | 1 | 0 | 0 | 4 | 0 |
| .github | 0 | 1 | 0 | 0 | 2 | 0 |
| 其余 | 1 | 0 | 1 | 0 | 1 | 0 |
| **合计** | **21** | **168** | **19** | **1** | **161** | **7** |

**结论：真正可自动收敛的只有 21 个文件。** 168 个 `both-changed` 与 161 个 `no-base` 必须逐文件 3-way 处理，这是后续批次的成本主体，不存在「再跑一次 auto_sync 就好」的捷径。

## 4. 批次执行记录

| 批次 | 范围 | 结果 |
|---|---|---|
| 1 | `docs/` | ✅ #2487，275 文件（新增 206 / 覆盖 69）。win7 自有文档 48 个跳过 |
| 2 | `electron,scripts,.github,root,...` 全量 | ❌ #2490 关闭：`architecture-baseline.json` 与 `scripts/check-version-lockstep.mjs` 被误覆盖，Architecture check 与版本一致校验双红 |
| 2b | 同上，剔除 `architecture-baseline.json`/`scripts/`/`.github/` | ❌ #2491 关闭：3 个 electron job 全红，electron 构建面非同源 |
| 2c | 再剔除 `electron/` | ⏳ 待执行（AGENTS.md / CONTRIBUTING.md / DESIGN.md / build/installer.nsh / .superpowers / tests） |

## 5. 后续待办

1. 批次 2c：仅剩纯文档型根文件与 `build/`、`.superpowers/`，风险最低。
2. `src/` 178 个文件：85 个 `both-changed` 是 win7 自查 UI 特性（滚动按钮、输入历史等）与 main 新增的交叉，必须逐文件人工 3-way，建议按 feature 目录切小批。
3. `backend/` 203 个文件：注意 `cls=B`（39 个）是 win7 兼容垫片，改写目标应为 `backend/compat/win7`，不得直接替换业务文件。
4. `architecture-baseline.json` 只有在 `src/` 收敛到位后才可重新对齐，否则恒红。
5. `Win7 Sync` 的 push 权限问题独立修复：`sync` job 需带 `workflows` 权限的 PAT（secrets 不可用时可回退为 `gh api` 建分支，避开 git push 的 workflow 校验）。

## 6. 复现方式

三分法判定脚本（宿主侧）：读取 parity 看板 JSON + `git ls-tree` 三份 ref（`origin/main` / `origin/release/win7` / merge-base），输出第 3 节的表。看板通过 `Win7 Sync` 的 `workflow_dispatch`（`do_sync=false`）刷新，artifact 名 `win7-parity`。

## 7. 第二批实测（2026-10-25 追加）

| 批次 | 范围 | 结果 |
|---|---|---|
| 3 | `src/` 三方合并 | ✅ #2498 → `4dcf2f9a`，23 文件（三方合并 17 / 直接取 main 6） |
| ci | `win7-sync.yml` 推送权限 | ✅ #2499 → `ca9c0afb` |

### 批次 3 的方法与实测产出

对 89 个 `both-changed` 文件用 `git merge-file -p --diff3`（ours=win7 / base=merge-base / theirs=main）逐文件三方合并：

- **22 个文本零冲突** → 上传合并结果；其中 **5 个因依赖面未合被剔除**（详见下）
- **67 个有冲突** → 保留原状，转人工
- 另有 **6 个** `safe-take-main` 直接复用 main 的 blob

被剔除的 5 个文件及原因（已验证，非猜测）：

| 文件 | 原因 |
|---|---|
| `src/features/office/OfficeGenerateForm.tsx` | 依赖 `PptSlideSpec.layout` 与 i18n key，二者仍在冲突集 |
| `src/shared/api/officeApi.ts` | 调用 `office_word_repair`，win7 主进程未注册该 IPC 命令 |
| `src/shared/api/orchRunClient.ts` | 调用 `orchestration_get_run`，同上 |
| `src/pages/settings/__tests__/EndpointsTab.test.tsx` | 被测组件 `EndpointsTab` 仍在冲突集 |
| `src/pages/settings/__tests__/PromptTemplatesTab.memory.test.tsx` | 被测组件缺 `tplmem-orphans` testid，实现未合 |

**教训：三方合并"文本干净"不等于"可合"。** 判定链必须再加两道闸：

1. `tsc --noEmit`（检出依赖面缺口）
2. `vitest` 跑 `electron/__tests__/ipc-contract.test.ts`（检出渲染进程调用主进程未注册命令）

批次 3 最终在本地通过 `tsc` 0 错、IPC 契约 111 tests、相关 vitest 81 tests，CI 才放行。

### win7-sync.yml 权限修复要点

- `GH_TOKEN` 改为 `secrets.WIN7_SYNC_TOKEN || github.token`
- 两条 push 路径前插入「剥离 `.github/workflows/**` 改动并 amend」步骤，使 push 不再触碰 workflow 文件
- 被剥离的 workflow 改动保留在 sync 报告里，转人工处理

### 收敛进度总览

| 时点 | 异动文件 | main-only | real | 需动作 |
|---|---:|---:|---:|---:|
| 起点 | 983 | 233 | 421 | 714 |
| 批次 1 | 706 | 29 | 348 | 437 |
| 批次 3 | **683** | **30** | **323** | **414** |

剩余 414 个需动作文件中，`backend` 203、`backend/tests` 157 是最大头；`src` 已从 178 降到 159。

### 后续优先级（按收益/风险比）

1. `backend/tests` 157 ——纯测试文件，风险最低，可批量取 main（需先剔除依赖未合实现者）
2. `backend` 203 ——`cls=B` 39 个垫片必须改 `backend/compat/win7`，其余按三方合并
3. `src` 剩余 159 ——67 个冲突文件需逐个 3-way，建议按 feature 目录切分
4. `electron` 47 ——最后做，构建面差异最大
5. `architecture-baseline.json` ——等 `src`/`backend` 收敛到位后再对齐

## 8. 批次 4 与最终进度（2026-10-25 收尾）

| 批次 | 范围 | 结果 |
|---|---|---|
| 4 | `backend/tests/` | ✅ #2502 → `961d2b85`（14 文件：三方合并 10 / 直接取 main 4） |

### 批次 4 踩到的坑：合并产物可能语法/风格坏

`backend/tests/unit/test_storage_schema.py` 的三方合并返回 rc=0（"零冲突"），但把 win7 新增的 `from typing import List` 和 main 改写的模块 docstring 粘在了同一行，导致 ruff `F811` 失败、py38 job 变红。

**因此验证链再补两道**（现已强制）：

3. Python 侧：对每个合并后的 `.py` 执行 `compile()` 语法校验 + `ruff check --fix --select F,E9`
4. 修复后必须**重新上传 blob**——PR 分支里的旧 blob 不会自动跟着工作区变

### 最终进度

| 时点 | 异动文件 | main-only | real | 需动作 |
|---|---:|---:|---:|---:|
| 起点 | 983 | 233 | 421 | 714 |
| 批次 1（docs） | 706 | 29 | 348 | 437 |
| 批次 3（src） | 683 | 30 | 323 | 414 |
| 批次 4（backend/tests） | **676** | **32** | **314** | **407** |

> `main` 在本轮期间被其他人推了多次（`0d687001` → `58afc32d`），所以 `main-only` 会小幅回升，这是活性而非倒退。

### 剩余 407 个需动作文件的分布

`backend 199` / `src 162` / `backend/tests 150` / `docs 72` / `electron 47` / `scripts 23` / `.github 7` / 其余 15。

其中真正可再自动化的部分已基本榨干：本轮实测「safe-take-main + 三方干净合并」的命中率约 **12%~25%**，且每批都需要 `tsc` / `vitest` / `pytest` / `ruff` 四道闸逐一把不合格文件剔除。**剩余主体是 168 个 both-changed 冲突文件与 161 个 no-base 文件，只能人工 3-way。**

## 9. 批次 5：src 冲突文件机械解冲突（2026-10-25）

67 个三方冲突文件按**冲突块形态**分型处理，只有三类可机械判定：

| 形态 | 判定依据 | 处置 |
|---|---|---|
| 纯顺序差异 | 两侧行集合相同、顺序不同 | 取 main 顺序 |
| 子集包含 | 一侧是另一侧超集 | 取超集 |
| 注释标记差异 | 仅差 `（同步 #NNN）` 标记 | 取 main 干净版 |
| 其余 | 语义分叉 | **保留冲突，不动** |

结果：**27 个文件机械解冲突成功** → 以 `tsc` 为唯一判据迭代剔除后保留 **16 个**（#2507 → `b43e3765`）。

### 淘汰的 11 个及原因（全部有实测证据）

| 文件 | 原因 |
|---|---|
| `AtFileMenu.tsx` | 用了 `'allowed-file'`，但 `FileSearchKind` 仍是 win7 版（`fileSearchClient.ts` 在冲突集） |
| `chatStreamStore.ts` | 「取超集」产生重复方法 `addCompletedStep` / `finalizeStep` |
| `shared/ui/index.ts` | 「取超集」产生重复导出 `Card` / `PanelShell` |
| `OfficeDeliveryDrawer.tsx` + 其 test | 依赖 office repair API（未合） |
| `GeneralTab.tsx` + 其 test | 依赖 permissionApi 插件状态（未合） |
| `PromptTemplatesTab.test.tsx` | 被测组件 `PromptTemplatesTab.tsx` 仍在冲突集 |
| `fileSearchClient.test.ts` | 被测 `fileSearchClient.ts` 仍在冲突集 |
| `orchRunClient.test.ts` | 被测 `orchRunClient.ts` 因 IPC 未注册已延后 |
| `SessionModelPicker.test.tsx` | 被测 `SessionModelPicker.tsx` 仍在冲突集 |

**新教训：`subset`/`order` 启发式会制造重复声明。** 必须以 `tsc` 为唯一判据迭代剔除——我的静态重复声明检测既有误报（局部变量 `next`/`slots`）又有漏报（`export { Card } from` 形式）。

### 剩余 40 个冲突文件分诊

| 类别 | 数量 | 含义 |
|---|---:|---|
| `NEW-SYMBOL` | 6 | main 侧依赖 win7 尚不存在的符号，须先移植依赖 |
| `TEXTUAL` | 34 | 纯语义分叉，需人读代码决定 |

**`NEW-SYMBOL` 明细**：

| 块数 | 文件 | 缺失符号 |
|---:|---|---|
| 1 | `src/shared/lib/hooks/useFeatureUnlock.ts` | `useFeatureExplicitlyDisabled` |
| 2 | `src/shared/lib/hooks/__tests__/useFeatureUnlock.test.ts` | 同上 |
| 2 | `src/widgets/layout/Layout.tsx` | `useRightPanelStore` |
| 3 | `src/widgets/chat/progress/ProgressSection.tsx` | `useState` |
| 3 | `src/widgets/memory/MemoryBrowser.tsx` | `handleDeleteMemory` |
| 12 | `src/widgets/layout/Sidebar.tsx` | `useCallback`、`useFeatureExplicitlyDisabled` |

**需要产品决策的两个文件**（不是技术冲突）：

- `src/widgets/layout/Sidebar.tsx`（12 块）：win7 有 UX-IA R3 的「56px rail + 分组侧栏 + 可折叠」重设计；main 有 P1-7「锁定功能可见化」+ `/office` 注册 + `useFeatureExplicitlyDisabled`。二者是两套导航语义，合谁都得先定产品口径。
- `src/widgets/chat/RightPanel.tsx`（12 块）：win7 右栏布局与 main 的变更互相覆盖。

**这两项建议登记为「待产品裁决」，不纳入机械收敛。**

## 10. 收敛总账（截至批次 5）

| 时点 | 异动文件 | main-only | real | 需动作 |
|---|---:|---:|---:|---:|
| 起点 | 983 | 233 | 421 | 714 |
| 批次 1（docs） | 706 | 29 | 348 | 437 |
| 批次 3（src 三方合并） | 683 | 30 | 323 | 414 |
| 批次 4（backend/tests） | 676 | 32 | 314 | 407 |
| 批次 5（src 冲突机械解） | **666** | **34** | **306** | **401** |

五批合计收敛 **313 个文件**（714 → 401）。剩余 401 中：`backend 199`、`src 155`、`backend/tests 146`、`docs 73`、`electron 47`、`scripts 23`。

### 结论：src 的机械收敛已到极限

`src` 从 178 → 155，剩下的 40 个冲突文件里 34 个是纯语义分叉。机械手段（顺序/子集/注释）已全部用尽，继续自动化只会制造重复声明或半迁移状态。**后续 src 只能按 feature 逐个读代码人工 3-way，单文件成本约 10~30 分钟。**

## 11. 批次 6–15：src 冲突文件人工 3-way（2026-10-26）

批次 5 之后剩余的 40 个手工冲突文件，按「产品口径先定、再技术落地」推进，共 15 个 PR。

### 两次产品裁决

1. **Sidebar（12 块）→ 以 win7 的 rail 为基座 + 移植 main 的 P1-7。**
   实测发现 **win7 本来就有 rail**（`sidebar-rail-nav` / `NavGroup` / `variant="rail"`），与 main 是同一套实现；
   197 行 diff 全部是 main 侧新增或格式化，即 **main ⊃ win7**。所以「rail 为基座 + 移植 P1-7」的落地方式就是取 main，再补齐依赖链。
2. **RightPanel（12 块）→ 并集。**
   两侧架构相同（都有 `PanelOptionsMenu` 浮层），差异只在取舍：win7 有 `trajectory`/`preview` 两个 Tab 与 360/520/720 宽档位，
   main 有左栏联动自动折叠。→ 6 Tab + 宽档位取 win7，自折叠取 main。

随后用户指示 **「跟着对齐」**：`trajectory`/`preview` 一律按**顶层 Tab** 模型，于是把 `ProgressSection`（main 的 sub-tab）与
`ChangesSection`（main 的 `autoPreviewMode`）都回退到 win7 口径，避免「Tab 是顶层的、组件却按 sub-tab 渲染」的半迁移状态。

### PR 台账（批次 6–15）

| PR | 内容 | 文件数 |
|---|---|---:|
| #2513 | Sidebar 取 main + `SidebarNavItem` / `useFeatureUnlock` / 两个 locale 手术式插入 5 键 / `ArenaAccountsToggle.test` 契约同步 | 8 |
| #2514 | RightPanel 并集 + store + Layout | 4 |
| #2517 | 顶层 Tab 对齐（`store.ts` 取 main 仅注释差异；`ChangesSection` / `ProgressSection` 取 win7） | 3 |
| #2518 | 设置页 P1-4 锚点 / P0-5 补 `general` tab、P1-8 `confirmDialog`、两个仅注释差异 | 6 |
| #2519 | 插件通配 R98 fail-closed、CodeMirror 懒加载、NetworkTab 并集（保留 `BrowserEnvironmentSection`）、v8 注释 | 5+1 |
| #2520 | Layout 左右栏联动 + 编排配置类型取 win7 超集 | 5 |
| #2521 | `allowed_paths` 搜索种类 + **恢复批次 5 剔除的 `AtFileMenu`** | 4 |
| #2522 | 密度 token 保留 + 设置锚点动画并集、会话模型切换风险提示 | 4 |
| #2523 | McpTab 纯格式化收敛到 main | 2 |
| #2524 | 记忆搜索/删除（P0-1/P0-6）+ 提示词模板条目级导入（r55） | 4 |

### 三条可复用的判断法则（本轮新增）

1. **「超集」判定要看导出集合，不能看行数。** `Chat.tsx` 673 vs 673、`McpTab.tsx` 651 vs 649 这类「等长」文件里藏着方向相反的差异。
2. **格式化分叉必须单向收敛。** 保留 win7 的格式化等于放弃合并——下次 merge 还冲突。McpTab 这类只能整体接受一侧。
3. **取 main 前先查它引用的依赖是否在 win7 缺失。** `ShikiCodeBlock`（需 `@shikijs/langs|themes`）与 `permissionApi`（需 R99-R102 后端）都是因此推迟。

### 推迟的 4 项（各有明确原因）

| 文件 | 原因 |
|---|---|
| `src/widgets/chat/ShikiCodeBlock.tsx` | 依赖新增 npm 包 `@shikijs/langs`/`@shikijs/themes`，牵动 `package.json` + lockfile，须单独立项 |
| `src/shared/api/permissionApi.ts` + `PermissionRulesManager.tsx` | main 侧是 R99–R102 功能移植（插件归属徽标、按插件整组撤销、一键清空），需后端端点配合 |
| `src/shared/api/types.ts` | main-only 570 行新增类型，牵涉面广，须先确认引用方是否都已在 win7 |
| `src/pages/settings/McpTab.tsx` 之外的 MCP 工具面板 | 依赖 win7 独有的 `mcp_server_tools` / `authorizeServer`，两侧 API 面不同 |

### 一个必须记住的流程教训

**推送内容只能取自内存快照（`C:/temp/conv/pr_*.json`），绝不能读 worktree。**
#2513 第二次提交时脚本从被 `git reset --hard` 回退过的 worktree 读文件，把 7 个文件覆盖回 win7 旧版，
CI 立刻报 `FEATURE_DISABLE_STORAGE_KEY` 缺失。修正后已补一条远端校验（直接按文件路径 + ref 拉回内容做符号断言）。

## 12. 总账更新（2026-10-26，批次 15 之后）

| 时点 | 异动文件 | main-only | real | 需动作 | src |
|---|---:|---:|---:|---:|---:|
| 起点 | 983 | 233 | 421 | 714 | 178 |
| 批次 4（backend/tests） | 676 | 32 | 314 | 407 | 178 |
| 批次 5（机械解冲突） | 666 | 34 | 306 | 401 | 155 |
| **批次 15（人工 3-way 收口）** | **645** | **38** | **283** | **382** | **132** |

新增合并 11 个 PR（#2513–#2525），`src` 从 **155 → 132**，real 从 **306 → 283**。

**main-only 逆势升到 38**：并非常态倒退，而是 main 侧本轮仍在活跃推送（main ahead 940 → 943），
新增的 main-only 文件是主线上新加的能力，需要下一批次（或下一次同步）再收。
这正是「收敛不是一次性动作，而是持续追平」的量化体现。

### 下一批次的入口

1. `src` 仍剩 132 个需动作文件，其中本轮的 4 个推迟项已列在 §11。
2. `backend`（200）与 `backend/tests`（145）是本轮之后最大的两块，适合按域批量机械合并（批次 4 的流程已验证）。
3. `electron`（48）受 IPC 契约约束，需过 `electron/__tests__/{commands,invoke,ipc-contract}.test.ts` 三道闸。