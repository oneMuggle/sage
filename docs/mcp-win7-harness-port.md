# 移植 main 的 Harness 组件可观测性到 win7

- 日期：2026-10-21
- 分支：`feat/win7-harness-20261021` → 基 `chore/win7-align-b5-20261021`（PR #2275）
- 移植源：main `4c9335025`（PR #2214「阶段 1 — Harness 组件可观测性 M1-M9」）

## 1. 起因

B5 批次把 `src/**` 对齐 main 后，`tsc` 报：

```
src/pages/settings/Settings.tsx(20,34): error TS2307:
Cannot find module '../../widgets/harness/HarnessDashboard'
```

追查发现 `HarnessDashboard.tsx` 与 `shared/api/harnessApi.ts` 都是 main 在
**merge-base 之后**新增的文件，而 parity 的差异清单是 merge-base 相对口径，
**根本看不到它们**。B5 当时的处理是保留 win7 版 `Settings.tsx` 并记为待办；
本批补齐。

harness 是一个自洽特性：工具/技能每次调用写入 `harness_components` 表，
累积 `usage_count` / `success_rate` / `avg_latency_ms`，
供 `GET /api/v1/harness/components` 消费，Settings 里有仪表盘页面。

## 2. 移植面（25 文件）

| 类别 | 文件 |
|---|---|
| 后端新增（8） | `ports/harness_port.py`、`domain/harness_component.py`、`adapters/out/harness/{__init__,sqlite_adapter}.py`、`application/services/harness_{recorder,service}.py`、`api/harness_routes.py`、`tests/unit/test_harness.py` |
| 后端接线（5） | `main.py`、`data/database.py`、`core/legacy/agent.py`、`adapters/out/tool/inproc_adapter.py`、`tools/skill_tool.py` |
| 前端新增（4） | `entities/harness/types.ts`、`shared/api/harnessApi.ts`、`widgets/harness/HarnessDashboard.tsx` + 测试 |
| 前端接线（5） | `pages/settings/Settings.tsx`、`settingsNavigation.ts`、`settingsSearchIndex.ts`、`i18n/locales/{zh,en}/chatAndSider.ts` |
| 其他（2） | `architecture-baseline.json`、方案文档 |

## 3. 三个逻辑文件不能整文件替换

`git cherry-pick -n 4c9335025` 在 4 个文件冲突。
关键判断：**不能取 main 版本**，因为 win7 侧这些文件含 main 没有的 alpha.36 Bug 修复：

```
win7 HEAD   有 12 处 `alpha.36 (Bug`
origin/main 只有 4 处
```

例如 `inproc_adapter.py` 的 **alpha.36 (Bug #1)**：分发前先过 `schema.required` 校验，
把 `TypeError "execute() missing 1 required positional argument"` 收敛成中文 + tool_name
文案，不泄漏 Python 内部错误到 LLM 输出；main 版完全没有这段，也没有配套的
`except TypeError` 兜底分支。整文件替换会**静默丢掉**这些修复。

> 佐证：win7 侧有 `backend/tests/unit/test_inproc_adapter_required_validation.py`
> 这个 **win7-only** 测试文件，专门锁住该行为。若整替 main 版，它会立刻变红。

改为**外科式嫁接**（`graft_harness2.py`，锚点定位 + 唯一性断言）：

### 3.1 `inproc_adapter.py`

取 main 的 probe 骨架（`probe = HarnessProbe("tool", name)` → `try: with probe:`
→ `finally: await probe.aemit()`），回填 win7 三处 alpha.36 增量：

- 函数签名的 `# noqa: PLR0911`（win7 多了 return 分支）
- `validate_required_args` 校验块（14 行）
- `except TypeError` 兜底分支（10 行，缩进 8 → 16 以匹配 `with probe:` 内层）

### 3.2 `skill_tool.py`

以 win7 为基底插入 probe 结构。
**不引入 main 的 `script=script` 参数** —— win7 的 `_invoke` 签名没有它，
那是 main 后续演进的另一个特性，引进来会破坏调用契约。

### 3.3 `main.py`

三处插入：

- `harness_routes` 的 import（按字母序落在 `hex_routes` 前）
- lifespan 里的 recorder 装配块（缩进 8，因 win7 该段包在 `try:` 内，main 是 4）
- `app.include_router(harness_router, ...)`（跟在 `artifact_router` 之后，与 main 一致）

## 4. 嫁接正确性的验证方法

不能只看「测试通过」。把嫁接后的 `execute` 函数体与 main 版做
**去缩进 unified diff**，剩余差异应当**正好等于**已知的 win7 独有增量：

```
-async def execute(...): # noqa: PLR0911 (...)     ← win7 多
-# alpha.36 (Bug #1): ... required_error 校验块     ← win7 多（14 行）
-except TypeError as exc: ... 兜底分支              ← win7 多（10 行）
```

probe 结构部分**零差异** → 骨架完整取自 main。

## 5. `architecture-baseline.json` 是行数棘轮，不能整替

该文件把路径映射到**基线行数**，`scripts/architecture-check.mjs` 只在文件
**超过**基线时报警（棘轮协议）。main 的值反映 main 的文件长度
（`main.py`：main 1292 行 vs win7 1613 行），整替会让棘轮失真。

处理：恢复 win7 基线，只更新 harness 实际影响的条目：

| 文件 | 原基线 | 新基线 |
|---|---:|---:|
| `backend/core/legacy/agent.py` | 3018 | 3043 |
| `backend/data/database.py` | 2033 | 2095 |
| `backend/main.py` | 1594 | 1614 |
| `src/features/send-message/useChat.ts` | 803 | 810 |

最后一项与 harness 无关，是 **B5 的遗漏**：B5 覆盖了 `useChat.ts`（803 → 810 行）
但当时没跑 architecture 闸门。已 amend 到 B5 分支（`588570ea3`），本分支 rebase 其后。

## 6. 验证

| 闸门 | 结果 |
|---|---|
| py38 `py_compile`（9 文件） | OK |
| py38 模块 `import`（含 `HarnessProbe` 符号存在性） | OK |
| 嫁接语义 diff（§4） | 仅剩已知 alpha.36 三处 |
| `pytest backend/tests/unit/test_harness.py` | **31 passed** |
| `pytest unit -k "inproc or skill or agent_tool or tool_exec or permission"` | 889 passed / 1 failed（既存红） |
| win7-only 测试（含 `test_inproc_adapter_required_validation`） | **32 passed** |
| `pytest backend/tests --collect-only` | **11448 collected**，无收集错误 |
| `ruff check`（全部涉及文件） | All checks passed |
| `scripts/check_py38_compat.py` | 1614 files / **0 violations** |
| `node scripts/architecture-check.mjs` | EXIT=0 |
| `tsc --noEmit` | **0 错误** |
| `vitest run src/widgets/harness src/pages/settings` | **28 files passed** |
| CI（workflow_dispatch） | Architecture check / count-lines / Electron build ×2 均 success |

### 既存红（不归因本次）

`test_skill_discovery::TestSkillDiscoveryService::test_default_skills_dir`
在干净 win7（`003a2053b`）上同样失败，已复核确认。

## 7. 未纳入

`electron/__tests__/wire/harness.ts` 在 main 上存在，但**不属于** harness 提交
（由 `a618367ba` #1899 引入的 wire 测试基建）。win7 没有 `electron/__tests__/wire/`
目录 —— 那是 B6（`electron/*`）批次的范围。

## 8. 方法沉淀

1. **parity 清单有 merge-base 盲区**：main 新增文件对旧文件的引用看不见，
   必须靠 `tsc` / `--collect-only` 在编译期与收集期兜住。
2. **「两边都有差异」≠「可以取任一边」**：先数特征标记（如 `alpha.36 (Bug`）
   判断哪侧承载了独有修复，再决定替换还是嫁接。
   **`win7-only` 的测试文件是判断依据**——它锁住了 win7 独有的行为契约。
3. **嫁接必须做语义 diff 验证**，而不只是「测试通过」——
   期望差异集合应当能被逐条解释。
4. **棘轮型基线文件按本分支实际值更新**，绝不整文件替换。
5. **`workflow_dispatch` 不满足 `pull_request` 的 `if` 条件**，
   backend job 会 `skipped`；要用 CI 验后端必须走真实 PR 事件。
