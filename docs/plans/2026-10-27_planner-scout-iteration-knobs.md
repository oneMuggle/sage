# Planner / Scout 迭代上限 UI 可调 + orch 白名单回归修复

> 分支：`feat/planner-iteration-knob`（基于 `release/win7`）
> 关联计划：
> - [`2026-10-27_orchestration-research-dispatch-optimization.md`](./2026-10-27_orchestration-research-dispatch-optimization.md)（编排调研/派发优化总方案，阶段 2.1 将消费本旋钮）
> - [`2026-08-17_max-iterations-configurability.md`](./2026-08-17_max-iterations-configurability.md)（ReAct 上限通用可配置化前序；本文件聚焦 Scout/Planner）

## 1. 背景与目标

### 1.1 背景

- 编排管线 `classify → plan_preflight(澄清+侦察) → Planner → PlanApprovalBar` 中，**Planner 目前是单次 `llm_client.complete(prompt)` 调用，没有 ReAct 循环**；总方案建议在阶段 2.1 为其接入只读工具并运行 ReAct 循环，硬上限拟定为 `MAX_PLANNER_ITERATIONS = 8`。
- **Scout 的迭代预算 `SCOUT_MAX_ITERATIONS = 4` 硬编码**在 `plan_preflight.py`，用户无法按模型能力/网络环境调整。
- 编排设置（`OrchSettings`）已有成熟的 UI 可调模式（`NumberField` + `_RAW_KEYS` + `LEGAL_ORCH_KEYS`），新旋钮复用该模式，不新增配置通道。

### 1.2 目标

1. 新增 `maxScoutIterations`（默认 4）与 `maxPlannerIterations`（默认 8）两个 UI 旋钮，持久化到 `app_settings.orch`。
2. `maxScoutIterations` **立即生效**：Scout 的 `run_loop(max_iterations=...)` 读取该值。
3. `maxPlannerIterations` **预配置**：Planner 阶段 2.1 接入 ReAct 后直接消费；UI 文案明确标注当前为单次拆解。
4. 修复实测发现的 **`maxToolCallsPerRun` 白名单回归**：该键已存在于 `OrchSettings` / `types.ts` / UI，但漏加 `LEGAL_ORCH_KEYS`，导致编排 Tab 任一保存返回 400 且被前端静默吞掉（main + release/win7 双分支均受影响）。

## 2. 现状调研

### 2.1 键位矩阵（改动前）

| 前端键 | `orch_settings._RAW_KEYS` | `LEGAL_ORCH_KEYS` | `types.ts` | UI 入口 | 消费点 |
|---|---|---|---|---|---|
| `maxSubagentIterations` | ✅ | ✅ | ✅ | ✅ | `agent_tool.py` |
| `maxToolCallsPerRun` | ✅ | ❌ **缺失** | ✅ | ✅ | `resolve_tool_call_budget()` |
| `maxScoutIterations` | — | — | — | — | 硬编码 `SCOUT_MAX_ITERATIONS=4` |
| `maxPlannerIterations` | — | — | — | — | 尚无 ReAct 循环 |

### 2.2 回归实测

```text
>>> validate_settings_shape({"orch": {"maxToolCallsPerRun": 100}})
ValueError: unknown orch field 'maxToolCallsPerRun'
```

前端 `storage.ts:283` 在**每次保存**时合并 `DEFAULT_ORCH_SETTINGS`（含 `maxToolCallsPerRun: 100`），因此编排 Tab 任意一次保存都会带上该键 → 400。`saveSettings` 的 `catch {}` 只 warn，用户无感知。

### 2.3 现有可复用模式

- 后端：`OrchSettings` dataclass + `_RAW_KEYS` camelCase 映射 + 类型守卫（`load_orch_settings`）。
- 前端：`OrchestrationTab.tsx` 的 `NumberField`（空输入守卫、`min` 校验）+ `setOrch` 部分更新。
- 契约：`backend/tests/contract/test_settings_schema_parity.py::test_legal_orch_keys_is_stable` 硬编码键集，必须与 `LEGAL_ORCH_KEYS` 同步。

## 3. 技术方案

### 3.1 配置面（6 处联动）

| 序号 | 文件 | 改动 |
|---|---|---|
| 1 | `backend/orchestration/orch_settings.py` | `_RAW_KEYS` 增加 `maxScoutIterations` / `maxPlannerIterations`；`OrchSettings` 增加 `max_scout_iterations: int = 4`、`max_planner_iterations: int = 8`；`load_orch_settings` 对两键做下界钳制（≥1，含 warning 日志） |
| 2 | `backend/data/settings_canonicalizer.py` | `LEGAL_ORCH_KEYS` 补 `maxToolCallsPerRun`、`maxScoutIterations`、`maxPlannerIterations`；`ALIASES` 补 `max_tool_calls_per_run` / `max_scout_iterations` / `max_planner_iterations` + 修复同类回归 `max_iterations` / `log_timezone` / `use_folder_picker`（后 3 键为 relay 往返丢键的 pre-existing 回归） |
| 3 | `src/entities/setting/types.ts` | `OrchSettings` 接口 + `DEFAULT_ORCH_SETTINGS` 增加两键 |
| 4 | `src/pages/settings/OrchestrationTab.tsx` | "计划前置" section 增加两个 `NumberField`（`min={1}`）；审计快照接口与输出同步；`Planner 迭代预算` 行加"（预配置，暂未生效）"后缀；侦察预算 desc 去掉虚报的"调整范围 1-20"，标注"不受全局迭代上限影响" |
| 5 | `backend/orchestration/plan_preflight.py` | `_scout(..., max_iterations=...)`；`run_plan_preflight` 传 `settings.max_scout_iterations`；保留常量作默认值 |
| 6 | `backend/tests/contract/test_settings_schema_parity.py` | 稳定键集补 3 键；新增机械守卫 `test_legal_keys_survive_relay_snake_roundtrip` —— 校验白名单里所有多词 camel 键都有 snake 别名 |

### 3.2 消费语义

- **Scout**：`maxScoutIterations` 控制 `SageAgent.run_loop` 的 ReAct 预算。`min=1` 防止 `range(0)` 直接超限。
- **Planner**：当前单次调用，旋钮暂不生效；阶段 2.1 的 ReAct 循环将读取 `load_orch_settings().max_planner_iterations`。UI desc 明确写"预配置"。
- **0 值语义**：两者均**不**允许 0（`min=1`），与 `maxSubagentIterations` 一致；后端 `load_orch_settings` 在两键做下界钳制（0 / 负值 → 1 + warn 日志），API 直写脏数据也不让侦察静默失效。

### 3.3 不做的事（YAGNI）

- 不在本次实现 Planner ReAct 工具循环（属阶段 2.1，涉及提示词、工具白名单、e2e 评测）。
- 不改 `SCOUT_TIMEOUT_ENV`（已有 env 通道，无需 UI 化）。
- 不修 `types.ts` 与后端 `maxPrimaryIterations` 默认值漂移（前端 25 vs 后端 15）——独立问题，另开修复。

## 4. 实施步骤

- [x] **步骤 1**：写计划文档（本文件）
- [x] **步骤 2**：修复 `maxToolCallsPerRun` 白名单回归（canonicalizer + parity test）
- [x] **步骤 3**：后端新增 `max_scout_iterations` / `max_planner_iterations`（`orch_settings.py`）+ 下界钳制
- [x] **步骤 4**：前端新增两键（`types.ts` + `OrchestrationTab.tsx` + 审计快照）
- [x] **步骤 5**：`plan_preflight.py` 消费 `max_scout_iterations`
- [x] **步骤 6**：更新/新增测试（parity、orch_settings、plan_preflight、OrchestrationTab、settings_canonicalizer）
- [x] **步骤 7**：code review（`everything-claude-code:code-reviewer`）
  - 检出 **CRITICAL**：`maxIterations` 缺 snake 别名 → relay 往返后 400 → 编排 Tab 任一保存静默失败 + 两个新旋钮无法落库
  - 检出 **HIGH-2**：`logTimezone` / `useFolderPicker` 同类回归（通用 Tab / Wiki Tab 400）
  - 检出 **MEDIUM-1**：UI desc "调整范围 1-20" 无 `max` 强制
  - 检出 **MEDIUM-2**：后端不钳 0 / 负值 → 侦察静默失效
- [x] **步骤 8**：本地验证（pytest + vitest + tsc + lint）
  - pytest：202 passed（contract + unit 含新增 relay 往返 + clamp 守卫）
  - vitest：28 passed
  - tsc --noEmit：无类型错误
  - ruff：全绿（顺手修了 pre-existing 的 I001 import 排序 + PLR1714 set 成员判断）
- [x] **步骤 9**：提交 + PR
  - commit：`fix(settings): repair orch tab 400 regression + add scout/planner iteration knobs`
  - PR：[#2592](https://github.com/oneMuggle/sage/pull/2592)（base: `release/win7`）
- [x] **步骤 10**：CI 监控 + 合并（release/win7）
  - Architecture check 初版失败（两个 baselined 文件行数增长） → 拆分新测试到 `test_settings_relay_roundtrip.py` + ratchet 基线 802→823
  - CI 第二轮全绿（Architecture check / Backend py38 / Frontend / Electron × 2 / Smoke）
  - Squash 合并：`76f8091`（2026-10-27 09:08:58 UTC）；远程分支已删除
- [x] **步骤 11**：cherry-pick 到 `main`
  - 冲突适配：main 无 win7 专属 4 个 profile 迭代上限键 → 仅同步 6 条 ALIASES + 4 个白名单键；`max_subagent_iterations` 断言按 main 的 6（win7 是 10）；基线按 main 行数 ratchet（`settings_canonicalizer.py`: 811）
  - 本地验证：pytest 195 passed / vitest 18 passed / tsc 无错误 / ruff 全绿 / baseline 无增长
  - PR：[#2598](https://github.com/oneMuggle/sage/pull/2598)，CI 全绿后 squash 合并：`0736a6da9`

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 新键漏加 `LEGAL_ORCH_KEYS` | 编排 Tab 任一保存 400（本计划已复现一次） | parity test 同步补键；PR 检查清单固化 |
| 新键漏加 `ALIASES` snake 别名 | relay 往返后翻回不了 camel，validate 报 400 | 新增机械守卫 `test_legal_keys_survive_relay_snake_roundtrip` 覆盖全部 7 个 LEGAL_*_KEYS |
| 同回归类（maxIterations / logTimezone / useFolderPicker）pre-existing 故障 | 编排 / 通用 / Wiki 三个 Tab 保存都静默 400 | 同 PR 补齐 3 条 snake 别名 |
| `maxScoutIterations` 设得过大 | Scout 变慢、token 成本上升 | 默认 4；UI desc 标注"侦察要快"；后端 `SCOUT_TIMEOUT_ENV` 120s 墙钟硬护栏 |
| Planner 旋钮当前无效果 | 用户误以为已生效 | UI desc 明确"当前为单次拆解；ReAct 接入后生效"；审计快照加"（预配置，暂未生效）"后缀 |
| API 绕过 UI 写入 0 / 负值 | 侦察静默失效（无异常、无日志） | 后端 `load_orch_settings` 对两键做 ≥1 钳制 + warn 日志 |
| py38 兼容 | release/win7 后端使用 Python 3.8 | 本次无新语法（仅 dataclass 字段、dict 字面量、普通 logger.warning 调用） |
| 分支同步 | main 同样存在白名单回归 | 合并后 cherry-pick 到 main（main 的 ALIASES 状态需再核验） |

## 6. 测试计划

- **后端单测**：`load_orch_settings` 读取新键；`_scout` 使用传入的 `max_iterations`；0 / 负值下界钳制；relay 往返丢键回归；parity 键集；机械守卫（7 个 LEGAL_*_KEYS 全扫）。
- **前端单测**：两个新 `NumberField` 渲染、默认值、部分更新契约、空/负数/0 不提交。
- **契约测试**：`test_legal_orch_keys_is_stable` 覆盖 23 键；`test_legal_keys_survive_relay_snake_roundtrip` 覆盖所有多词 camel 键必须有 snake 别名。
- **手动验证**：设置页改动 → 重启后端 → GET `/settings` 确认 `orch.maxScoutIterations` 持久化。

