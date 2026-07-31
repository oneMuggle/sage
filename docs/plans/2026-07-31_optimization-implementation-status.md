# Sage 优化方案实施状态与分支映射

> **文档定位**：`2026-07-30_sage-optimization-final.md`（50 项方案）的实施状态快照 +
> 整形后的真实分支映射。后续会话**以本文档为准**，不要参考旧会话总结里的分支表。
>
> 生成日期：2026-07-31

---

## 1. 总体状态

| 指标 | 数值 |
| --- | --- |
| 方案总项 | 50 |
| 已实现 | 47 |
| 明确跳过 | 3（A11 / A22 / A27） |
| 已推送并开 PR | 2（#240 A17、#241 A19） |
| 待推送分支 | 29（9 层堆叠 + 20 独立） |

**所有分支均基于 `origin/main`，未推送。** 本次会话只做整形，不做推送。

---

## 2. 整形背景（为什么需要这份文档）

上一轮 27 个并行 subagent **共享同一个主 worktree** 施工，造成三类问题，
旧会话总结里的分支表因此**不可信**：

1. **分支串扰**：commit 落在了名字无关的分支上
   （A16 落在 a19 分支、U19 落在 a5 分支、`feat/skill-auto-activation-a16` 与
   `feat/session-tree-visualization` 是空分支等 6 处错配）。
2. **误建基线**：Phase 0 全部 + Phase 1 全部 + A1/A2/A12/A13/A24/A27 共 28 个 commit
   建在了 `release/win7` 之上，含 252 个 LTS commit。按项目 CLAUDE.md
   的双分支隔离强制规则，**禁止 merge release/win7 到 main**，只能 cherry-pick。
3. **重复实现**：A16 存在两套（worktree 未提交的早期版 vs 已 review 的最终版）；
   A12 存在两个 commit（内容 blob 完全相同，仅父链不同）。

本次已全部整形完毕，回滚点见 §7。

> **后续约束**：并行 agent **必须**各自使用独立 git worktree，严禁共享主 worktree。
> 这是本轮混乱的唯一根因。

---

## 3. 堆叠链（win7 线移植，须按序合并）

27 个 commit 从 `release/win7` 线 cherry-pick 到 main 线。存在**真实跨层依赖**
（A2 依赖 A25 的 faux_provider、A1 依赖 A15 的 file_tool），因此组织为堆叠 PR，
**必须自上而下依次合并**，每层的 PR base 是上一层。

| # | 分支 | base | 新增 | 覆盖优化项 |
| --- | --- | --- | --- | --- |
| S1 | `fix/agent-tools-whitelist` | `origin/main` | +1 | *(非方案项)* agent profile.tools 白名单 + agent_id 路由 |
| S2 | `feat/phase0-cleanup-quickwins` | S1 | +9 | A9 A15 A29 / U1 U3 U5 U13 U16 |
| S3 | `feat/phase1-ui-primitives` | S2 | +5 | U2 U4 U6 U15 |
| S4 | `feat/phase1-security-release` | S3 | +4 | A3(部分) A7 A8 A14 |
| S5 | `feat/phase1-agent-infra` | S4 | +3 | A23 A25 A26 |
| S6 | `feat/quality-middleware-a13` | S5 | +1 | A13 |
| S7 | `feat/permission-riskclass-a1` | S6 | +2 | A1 |
| S8 | `feat/llm-provider-a2` | S7 | +1 | A2 |
| S9 | `feat/session-branch-tree-a24` | S8 | +1 | A24 |

**cherry-pick 期间只有 2 处真实 main↔win7 分歧需手工解决**（其余均为跨层依赖造成的假冲突）：

- **A15 / `backend/tools/file_tool.py`**：main 有 M1 workspace 边界强制 +
  `MAX_WRITE_SIZE_BYTES`，win7 走 M3 `policy.workspace_root`。
  解法：保留 main 的 M1 守卫，叠加 A15 的 `.py` 语法检查，输出统一走 `result` 字典。
- **A8 / `.github/workflows/release.yml`**：main 有 release-tier 自动化
  （rc.1 稳定化分支 / promote-stable / finalize，调用 `scripts/release/release_branches.py`），
  win7 线没有。解法：保留 main 全部 step，追加 A8 的 Windows 稳定命名产物 step。

---

## 4. 独立分支（基于 origin/main，可并行开 PR）

| 分支 | 优化项 | commits | 备注 |
| --- | --- | --- | --- |
| `feat/code-diff-visualization` | A17 | 1 | **PR #240 已开** |
| `feat/tool-chain-tracking-a19` | A19 | 1 | **PR #241 已开** |
| `chore/harden-supply-chain-a30` | A30 | 1 | |
| `docs/ui-mocks-a10` | A10 | 1 | |
| `docs/optimization-plan-2026-07-30` | *(规划文档)* | 1 | 含本状态文档 |
| `feat/context-compaction-a12` | A12 | 1 | **须先于 A28 合并** |
| `feat/branch-summarizer-a28` | A28 | 2 | 含 A12，依赖上一行 |
| `feat/context-snapshot-a18` | A18 | 1 | |
| `feat/emacs-keybindings-u20` | U20 | 1 | |
| `feat/html-session-export-u18` | U18 | 1 | |
| `feat/humanized-tool-titles-u8` | U8 | 1 | |
| `feat/live-dot-attn-badge-u9` | U9 | 1 | |
| `feat/persona-manifest-a5` | A5 | 1 | |
| `feat/right-rail-u7` | U7 | 1 | |
| `feat/session-tree-visualization` | U19 | 1 | A24 未合并时线性降级 |
| `feat/skill-auto-activation-a16` | A16 | 2 | 含 review 修复 commit |
| `feat/sticky-unlock-chips` | U10 | 1 | |
| `feat/suspend-resume-a4` | A4 | 1 | |
| `feat/tool-concurrency-a6` | A6 / A21 | 1 | A21 已并入 A6 实现 |
| `feat/two-step-delete-u12` | U12 | 1 | |
| `feat/u11-drained-toast` | U11 | 1 | |
| `test/hermetic-e2e-a3` | A3(完整) | 1 | |

---

## 5. 冲突矩阵与建议合并顺序

### 5.1 已知冲突

| 冲突对 | 冲突文件 | 说明 |
| --- | --- | --- |
| A6 ↔ A19 | `backend/core/legacy/agent.py` | A6 重写 run_loop（+364/−134），A19 仅 +41 行 |
| 堆叠链 ↔ A6 | `backend/core/legacy/agent.py` | 同上 |
| 堆叠链 ↔ A19 | `backend/core/legacy/agent.py` | 同上 |
| 堆叠链 ↔ A17 | `agent.py` `tools/base.py` `tools/file_tool.py` `package*.json` | A17 也改工具执行路径 |
| 堆叠链 ↔ A18 | `backend/api/legacy_routes.py` | 路由注册位置 |
| 堆叠链 ↔ A30 | `release.yml` `.gitignore` `package.json` | A30 也改 release workflow |
| 堆叠链 ↔ U7 | `Layout.tsx` `package*.json` | U2 hover-peek 也改 Layout |
| 堆叠链 ↔ U19 | `src/widgets/session/index.ts` | 导出清单 |
| 堆叠链 ↔ U11 | `src/index.css` | 样式追加位置 |
| 堆叠链 ↔ A3 | `.gitignore` `package.json` | |

**与堆叠链完全无冲突**：A5 A12 A16 A28 U8 U9 U10 U12 U18 U20 A4 A10 + 文档分支。

### 5.2 建议合并顺序

1. **先合无冲突独立分支**（12 个）：A10 A16 A5 A12 → A28 U8 U9 U10 U12 U18 U20 A4 + 文档分支
2. **再合堆叠链 S1→S9**（9 个 PR，严格按序）
3. **然后 A19**（PR #241，改动小，rebase 到堆叠链之上）
4. **然后 A6**（rebase 到 A19 之上，`agent.py` 需人工对齐 run_loop）
5. **最后剩余有冲突项**：A17（PR #240）、A18、A30、U7、U19、U11、A3

理由：`backend/core/legacy/agent.py` 是热点文件（堆叠链 / A6 / A19 / A17 都改），
先落地大块（堆叠链），再让小改动 rebase 上去，冲突面最小。

---

## 6. 跳过项

| 项 | 理由 |
| --- | --- |
| **A11** 本地 STT Sidecar | 需 1–2 月，涉及 Rust crate + whisper-rs + 跨平台打包 |
| **A22** 70+ 扩展示例 | 需持续实践积累，非一次性实施项 |
| **A27** 工具执行钩子 | main 已有 M6 用户钩子（`backend/hooks/config.py` + `runner.py`，pre-hook 支持 deny/modify-args + schema 复验，post-hook 已就位），A27 是同一想法在 win7 线的另一套实现；且其 `_execute_with_hooks()` 整段替换工具分发会**删除 main 的 M1 权限执行器**（enforcement-before-dispatch）与 M2b ask_user 特判，属权限绕过风险。唯一副本保留在 `feat/llm-provider-abstraction` 分支（未推送）。 |

另跳过 2 个 commit：`75abd8d`（A12 重复，blob 与 `4cd876f` 完全相同）、
`ea197b3`（win7 专属版本号 bump，按双分支隔离规则不移植）。

---

## 7. 回滚与保留物

| 项 | 位置 |
| --- | --- |
| 整形前全部分支 tip | `refs/backup/*`（24 个）+ `/tmp/sage-branch-backup-2026-07-31.txt` |
| 主 worktree 清理前快照 | `/tmp/sage-dirty-worktree-2026-07-31.tar.gz` |
| win7 线原始载体分支 | `chore/win7-bump-beta.2`、`feat/llm-provider-abstraction`（**勿删**，含 A27 唯一副本） |

`git branch -f <branch> refs/backup/<branch>` 可逐个还原。

---

## 8. 遗留 TODO / 风险

- [ ] **A15 副作用**：`WriteFileTool` 用 `py_compile.compile(..., doraise=True)` 做语法检查，
      默认会在目标目录写出 `__pycache__/*.pyc`——写工具产生了非预期的额外文件。
      建议改用 `ast.parse()`（无副作用）或显式传 `cfile` 到临时目录。**（MEDIUM）**
- [ ] **A6 ↔ A19 run_loop 对齐**：合并时需人工确认 A6 的并发改写没有破坏 A19 的
      工具链事件发射时序。
- [ ] **全量测试未跑**：本次会话只做分支整形，未在整合状态下跑 vitest + pytest 全量。
      建议在堆叠链 S9 合并后建一个集成分支跑一次。
- [ ] **U19 依赖 A24**：A24（会话分支树）在堆叠链 S9，U19 在独立分支且已做线性降级；
      两者都合并后应回归验证树形渲染真正生效。
