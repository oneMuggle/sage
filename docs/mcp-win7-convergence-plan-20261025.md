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