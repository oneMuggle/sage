# ask_user_question 提问限制 UI 可配置化

> 分支：`feat/ask-user-configurable-limits`（基于 `main`）
> worktree：`.worktrees/feat-ask-user-configurable-limits`
> 关联前序：
> - [`2026-10-27_planner-scout-iteration-knobs.md`](./2026-10-27_planner-scout-iteration-knobs.md)（编排旋钮 UI 化的现成模式与 `LEGAL_ORCH_KEYS` 回归教训）
> - [`2026-08-17_max-iterations-configurability.md`](./2026-08-17_max-iterations-configurability.md)（ReAct 上限通用可配置化）

## 1. 背景与目标

### 1.1 背景

Sage 自身的 AI agent 缺少与用户交互的工具，导致 LLM 推理过程中遇到需要澄清的点时无法向用户提问。补齐 `ask_user_question` 工具后，工具内又有若干**硬编码**限制，用户无法按场景调整：

| 限制 | 硬编码位置 | 硬编码值 | 后果 |
|---|---|---|---|
| 连续未应答上限 | `backend/core/legacy/agent.py` | `MAX_CONSECUTIVE_UNANSWERED_QUESTIONS = 3` | 提问太啰嗦时无法调低 |
| 每题最少选项数 | `backend/tools/ask_user_tool.py` | `MIN_OPTIONS = 2` | 需要三选一/四选一时 LLM 给不出足够选项 |
| 每题最多选项数 | `backend/tools/ask_user_tool.py` | `MAX_OPTIONS = 4` | 选项多于 4 个时被硬拒 |
| 提示词澄清指引 | `backend/agents/profiles.py` | 「至多 2 个问题」 | 系统提示词与用户期望不符 |
| 单轮澄清上限 | `backend/orchestration/plan_preflight.py` | `MAX_CLARIFY_QUESTIONS = 3` | 计划前置阶段澄清问题被截断 |

用户诉求：**在设置页里能动态修改这些限制**，且改完立即生效（不必重启后端）。

### 1.2 目标

1. 上述 5 个限制全部改为由 `app_settings.orch` JSON blob 驱动，落到设置页「编排 → 提问限制」分区。
2. 每个消费方在**每次检查时**重新读取设置 → 运行时改设置立即生效。
3. 任何读取失败（DB 挂、键缺失、类型错误）都**回落到原硬编码常量**，行为与今天逐字节一致。
4. 不新增 API 端点、不新增 preference 表键、不做数据迁移。

## 2. 现状调研

### 2.1 键位矩阵（改动前）

| 前端键 | `orch_settings._RAW_KEYS` | `LEGAL_ORCH_KEYS` | `ALIASES`(snake) | `types.ts` | UI 入口 | 消费点 |
|---|---|---|---|---|---|---|
| `maxConsecutiveUnansweredQuestions` | — | — | — | — | — | 硬编码常量 3 |
| `minOptionsPerQuestion` | — | — | — | — | — | 硬编码常量 2 |
| `maxOptionsPerQuestion` | — | — | — | — | — | 硬编码常量 4 |
| `maxClarifyQuestionsInPrompt` | — | — | — | — | — | 硬编码文案「至多 2 个问题」 |
| `maxClarifyQuestionsPerRound` | — | — | — | — | — | 硬编码常量 3 |

### 2.2 可复用模式

与 `maxScoutIterations` / `maxPlannerIterations`（PR #2592）完全同构：

- 后端：`OrchSettings` dataclass + `_RAW_KEYS` camelCase 映射 + `load_orch_settings()` 类型守卫 + 下界钳制。
- 前端：`OrchestrationTab.tsx` 的 `NumberField`（空输入守卫、`min` 校验）+ `setOrch` 部分更新。
- 契约：`backend/tests/contract/test_settings_schema_parity.py::test_legal_orch_keys_is_stable` 硬编码键集，必须与 `LEGAL_ORCH_KEYS` 同步。
- 机械守卫：`test_legal_keys_survive_relay_snake_roundtrip` 要求 `LEGAL_*_KEYS` 里每个多词 camelCase 键都有 snake 别名。

## 3. 技术方案

### 3.1 配置面（6 处联动 + 消费方 + 白名单）

| 序号 | 文件 | 改动 |
|---|---|---|
| 1 | `backend/orchestration/orch_settings.py` | `_RAW_KEYS` 增加 5 键；`OrchSettings` 增加 5 个 `int` 字段（默认 3/2/4/2/3）；`_INT_MIN_BOUNDS` 全为 1 |
| 2 | `backend/data/settings_canonicalizer.py` | `LEGAL_ORCH_KEYS` 补 5 键；`ALIASES` 补 5 条 snake→camel |
| 3 | `backend/tools/ask_user_tool.py` | `_load_ask_user_limits()` 动态读 `min/maxOptionsPerQuestion`；`_validate_options()` 用动态值；**JSON schema 也动态**（见 3.2 决策 4） |
| 4 | `backend/core/legacy/agent.py` | `_load_max_consecutive_unanswered()` 动态读；`run_loop` 每次检查前重新读 |
| 5 | `backend/agents/profiles.py` | `_CLARIFY_GUIDANCE_PROMPT_TEMPLATE` + `{max_questions}` 占位；`_build_clarify_guidance()` 插值；`build_system_base()` 追加 |
| 6 | `backend/orchestration/plan_preflight.py` | `_load_max_clarify_questions_per_round()` 动态读；提示词注入与 `questions[:max_clarify]` 切片都用它 |
| 7 | `backend/tools/config_tool.py` | `_ALLOWED_ORCH_FIELDS` 补 5 键；`_ORCH_INTEGER_RANGES` 补 5 区间；`_validate_ask_user_cross_fields()` 跨字段校验（**在合并后的 orch 上**） |
| 8 | `backend/api/hex_routes.py` | `PUT /settings` 在 `validate_settings_shape` 后、`repo.set_json` 前调 `_validate_ask_user_cross_fields`（API 直写路径护栏） |
| 9 | `src/entities/setting/types.ts` | `OrchSettings` 接口 + `DEFAULT_ORCH_SETTINGS` 增 5 键 |
| 10 | `src/pages/settings/OrchestrationTab.tsx` | 新增「提问限制」section，5 个 `NumberField`（min/max 双向绑定） |
| 11 | `src/pages/settings/settingsSearchIndex.ts` | 增 5 条搜索索引 |
| 12 | `backend/tests/contract/test_settings_schema_parity.py` | `test_legal_orch_keys_is_stable` 钉住集补 5 键 |

### 3.2 关键设计决策

1. **Pattern A：复用 `app_settings.orch` JSON blob。** 不开新 API、不加新表键、不迁移。缺键 → dataclass 默认值 = 原硬编码值 → 老部署行为不变。
2. **fail-safe 回落。** 每个消费方的读取都包在 `try/except Exception` 里，抛错返回原常量，绝不把异常抛穿到调用方。
3. **不缓存。** 每次检查都重读 → 改设置立即生效，无需重启后端。
4. **schema 与运行期校验保持一致（2026-10-28 review 修订）。** 原决策为「schema 静态 2-4，只有运行期动态」——**已推翻**。若用户把 `minOptionsPerQuestion` 调到 3，静态 schema 仍写 2-4，LLM 按 schema 出 2 选项会被运行期拒掉，整轮提问静默失败。故 `_build_schema()` 改为读当前配置，`minItems`/`maxItems`/description 全部动态。工具契约随用户设置变化是可接受的——约束本就由用户定义，schema 撒谎才是 bug。
5. **跨字段校验放「合并后」。** `_prepare_settings_update` 在 `{**orch, **updates}` 上比较 `min ≤ max`；只比提交值会漏过「库里 min=5、max=3，用户只改 max」这种自相矛盾组合。缺键回落 `OrchSettings()` 数据类默认值（2 / 4）而非跳过比较——跳过会让 agent 第一次只提交 `min=5` 落库后与默认 `max=4` 矛盾。
6. **UI + 后端双保险。** 前端 `NumberField` 的 `min`/`max` 双向绑定（min 字段 `max={maxOptionsPerQuestion}`，max 字段 `min={minOptionsPerQuestion}`）；后端 `PUT /settings`（`backend/api/hex_routes.py`）在 `validate_settings_shape` 之后、`repo.set_json` 之前调 `_validate_ask_user_cross_fields`，违反返回 422 + `detail.field`。
7. **0 值一律拒绝。** 这 5 个限制的 0 值无意义（0 轮提问 / 0 个选项）。UI `min={1}`，后端整数区间下界 1，`load_orch_settings` 对脏数据钳到 1。

### 3.3 不做的事（YAGNI）

- 不做 per-agent / per-profile 的粒度覆盖 —— 现阶段全局够用。
- 不做历史值回填 / 迁移脚本 —— dataclass 默认值即等价物。
- 不做 schema 的「静态快照 + 运行时覆盖」双轨 —— 已证明会产出矛盾契约（见 3.2 决策 4）。

## 4. 实施步骤

- [x] **步骤 1**：写计划文档（本文件）
- [x] **步骤 2**：后端 `orch_settings.py` 增加 5 字段 + `_RAW_KEYS` + 下界钳制
- [x] **步骤 3**：后端 `settings_canonicalizer.py` 补 `LEGAL_ORCH_KEYS` + `ALIASES`
- [x] **步骤 4**：`ask_user_tool.py` 动态选项数校验（schema 与运行期同步动态）
- [x] **步骤 5**：`agent.py` 动态连续未应答上限
- [x] **步骤 6**：`profiles.py` 动态澄清指引文案
- [x] **步骤 7**：`plan_preflight.py` 动态单轮澄清上限
- [x] **步骤 8**：`config_tool.py` 补白名单 + 整数区间 + 跨字段校验（合并后比较）
- [x] **步骤 9**：前端 `types.ts` + `OrchestrationTab.tsx`「提问限制」section + `settingsSearchIndex.ts`
- [x] **步骤 10**：契约测试钉住集补键
- [x] **步骤 11**：编写测试（3 个后端新文件 + `OrchestrationTab.test.tsx` 7 例）
- [x] **步骤 12**：code review（`everything-claude-code:code-reviewer`）→ 3 HIGH / 2 MEDIUM / 3 LOW，全部 HIGH + MEDIUM 已修
- [x] **步骤 13**：本地验证（pytest + vitest + tsc + ruff）—— 目标测试 188 例全绿，ruff 干净，tsc 无错
- [ ] **步骤 14**：提交 + PR

### 4.1 code review 修复记录（2026-10-28）

| 级别 | 问题 | 修复 |
|---|---|---|
| HIGH-1 | UI 跨字段校验只单向（min 字段无 `max` 约束） | `OrchestrationTab.tsx` min 字段加 `max={settings.orch.maxOptionsPerQuestion}`；后端 `hex_routes.py` PUT 路径加 `_validate_ask_user_cross_fields` 护栏（422） |
| HIGH-2 | schema 静态 2-4 与运行期动态校验矛盾 | `ask_user_tool.py` `_build_schema()` 改为读当前配置；测试改名 `test_tool_schema_reflects_current_settings` + 新增 `test_tool_schema_dynamic_when_settings_change` |
| HIGH-3 | `plan_preflight._CLARIFY_PROMPT` 硬编码「2-4 个选项」 | 改 `{min_opts}-{max_opts}` 占位，`_clarify()` 注入当前配置值 |
| MEDIUM-2 | `_validate_ask_user_cross_fields` 缺键时跳过比较 | 缺键回落 `OrchSettings()` 数据类默认值再比较；测试改名 `test_config_tool_cross_field_check_defaults_non_int` |

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 新键漏加 `LEGAL_ORCH_KEYS` | 编排 Tab 任一保存静默 400（前端 `catch{}` 吞掉） | parity test 钉住；code review 逐点核 6 处 |
| 新键漏加 `ALIASES` snake 别名 | relay 往返后翻不回 camel → 400 | `test_legal_keys_survive_relay_snake_roundtrip` 机械守卫覆盖 |
| `config_tool._ALLOWED_ORCH_FIELDS` 漏键 | agent 自我配置工具报「越权字段」 | code review 专项核对；本次已修（首版遗漏） |
| 跨字段校验只看提交值 | 落库自相矛盾（min > max） | 校验放 `_prepare_settings_update` 的**合并后**字典 |
| 设置读取抛错 | 提问功能整体挂掉 | 5 个消费方全部 try/except fail-safe 回落 |
| 用户把限制调得极端（min=10 / max=1） | LLM 无法给出合规选项，工具持续被拒 | 后端跨字段校验拦住 min>max；下界 ≥1 |
| 动态限制与静态 schema 不一致 | 模型按 schema 提 2 选项但用户设 min=3 → 反复被拒 | **已修**：schema 改为动态（3.2 决策 4），schema 与运行期同源 |
| py38 兼容 | release/win7 后端 Python 3.8 | 本次无新语法（dataclass 字段、f-string、try/except） |
| 分支同步 | 双分支长期共存，win7 需同样能力 | 合并到 main 后 cherry-pick 到 `release/win7`（pydantic v1/v2 差异本次为零） |

## 6. 测试计划

- **后端单测**：`test_orch_settings_ask_user.py`（14 例：默认/覆盖/坏类型逐键回落/下界钳制/4 个消费方动态读取与回落）、`test_ask_user_tool_dynamic_validation.py`（5 例：动态上下界/默认不变/读取失败回落/schema 反映设置/schema 随设置动态）、`test_config_tool_ask_user.py`（8 例 + 1 参数化：白名单/区间/非 int/越界/min>max/合并后比较/缺键回落默认值）。
- **前端单测**：`OrchestrationTab.test.tsx` 新增 `describe('OrchestrationTab — 提问限制 (2026-10-28)')` 7 例：五输入渲染/默认值对齐后端/部分更新契约/拒绝 0/UI 跨字段约束/澄清两旋钮。
- **契约测试**：`test_legal_orch_keys_is_stable` 覆盖 5 新键；`test_legal_keys_survive_relay_snake_roundtrip` 覆盖 snake 别名。
- **手动验证**：设置页改值 → 后端 GET `/settings` 确认 `orch.maxOptionsPerQuestion` 持久化 → 触发一次含澄清的 Run 观察行为变化。

## 7. 用户可见说明

设置页「编排 → 提问限制」分区包含 5 个旋钮：

- **连续未应答上限**（默认 3）：连续多少次提问都没人应答后放弃。
- **每题最少选项数**（默认 2）/ **每题最多选项数**（默认 4）：必须满足「最少 ≤ 最多」。
- **提示词澄清问题上限**（默认 2）：系统提示词里告诉 LLM「至多 N 个问题」。
- **单轮澄清问题上限**（默认 3）：计划前置阶段一轮最多问几个澄清问题。
