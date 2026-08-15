# Wave 3 · 编排深化实现计划（P2-7/8/9/10 + 计划卡接线 + resume）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Wave 3 全部 5 项承接项 —— 派发 task_id 对齐（P2-7）、确定性模板（P2-8）、执行参数配置化（P2-9）、休眠层 API lane 可执行 + board 端点（P2-10）、计划卡视图接线 + 取消执行 + 模板选择器 + resume plan_override 恢复流。

**Architecture:** 按 spec（`docs/superpowers/specs/2026-08-14-orchestration-wave3-design.md`，commit `4ae6a4cd`）拆 3 个 PR 递进合入：
- **PR A（后端结构）**：P2-7 计划权威 task_id + P2-8 模板 + P2-9 配置化 + run 级 cancel 端点 + resume 后端 bits（original_request 列 / plan_override / run_id）。
- **PR B（休眠层）**：`POST /orchestration/lanes?wait=true` 真实执行（复用 LaneExecutor + SubagentRunner）+ 提取 `review.py` 公共验证环 + `GET /orchestration/board`。
- **PR C（前端）**：PlanCard/PlanCardList 视图接线（三态 ProgressSection）+ 取消执行按钮 + 模板选择器 + resume 恢复流（plan_override 逐字恢复）。

**Tech Stack:** Python 3.11（conda `sage-backend`）+ FastAPI + SQLite；TypeScript + React（Vite/Electron 双入口）+ Vitest。

## Global Constraints

- 后端 Python 一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，**绝不污染 base/系统 Python**。
- 分支：所有改动在 feature 分支上（`feat/orch-wave3-pr-a` 等），PR squash merge 到 main；**严禁删/合 release/win7 分支**（本波只碰 main，不 cherry-pick）。
- 测试基线：pytest 全量 **≥3706**、vitest 全量 **≥1239**、`typecheck:electron`（electron 改动必跑，wave2 教训）+ `tsc` 0 错。
- **Spec 偏差（计划审批后新发现，实施时以本计划为准）**：
  1. **§3.3「PreferenceKey 白名单不变」是错的**：`backend/data/settings_canonicalizer.py` 的 `LEGAL_TOP_KEYS` + `validate_settings_shape` 会 400 拒收新增的 `orch` 顶层键，契约测试 `test_settings_schema_parity.py::test_legal_top_keys_matches_appsettings_interface` 要求 `LEGAL_TOP_KEYS == EXPECTED_TOP_KEYS` 严格相等。加 `orch` 必须同步：`LEGAL_TOP_KEYS` += `"orch"`、新增 `LEGAL_ORCH_KEYS` + `validate_settings_shape` 校验分支、契约测试 `EXPECTED_TOP_KEYS` += `"orch"` + 新增 `test_legal_orch_keys_is_stable`。
  2. **§3.2 模板 `gather-analyze-report` 的 `gather`/`analyze` 角色不存在**：`get_enabled_agent()`（SQLite）只认默认角色 `coordinator/researcher/coder/memory_manager/writer/reviewer`。若照 spec 用 gather/analyze，`_is_dispatchable_agent` 恒 False → 角色 hint 全失效（模板退化成纯顺序拆解）。本计划改为**内置模板全部用可派发角色**：`research-write` = researcher→writer（与 spec 一致）；`gather-analyze-report` = researcher（收集）→ researcher（分析）→ writer（报告）。`_is_dispatchable_agent` 回退逻辑仍保留（测试用合成模板证明）。
  3. **§5.3 resume 后端 bits（original_request 列、resume 响应字段、ChatRequest plan_override/run_id、legacy wiring）归入 PR A**（spec 原文归 PR C），使 PR C 为纯前端。spec §2 依赖描述据此：PR C 依赖 PR A 的 A9/A10。
  4. **§3.1 不做构造参数 `plan_json`**：dispatcher 始终在**首 dispatch 时从 `orch_runs` 读 plan_json** 建 `_plan_by_id`（DB 单源），计划卡 `update_plan` 落库后首 dispatch 即读到编辑后计划。
  5. **§3.1 review 门（`_next_task_index >= total_tasks`）在计划权威下失效**：计划匹配任务不再递增 `_next_task_index`，该门永不满足。改为 `_plan_by_id` 非空时用 `plan 全部 task_id 已派发` 判覆盖，否则回退旧门。
- `orchestration_mode` 透传沿用现有 `ChatConfig.orchestrationMode` 通道（`agent_chat_stream` invoke payload），模板模式值形如 `"template:research-write"`。
- 消息/进度报告用中文。

---

# PR A — 后端结构

按 A1→A12 顺序实施，每 task 独立可测可提交。**PR A 分支：`feat/orch-wave3-pr-a`。**

## Task A1: `orch_settings.py` 配置化数据类

**Files:**
- Create: `backend/orchestration/orch_settings.py`
- Test: `backend/tests/unit/test_orch_settings.py`

**Interfaces:**
- Produces: `OrchSettings` dataclass（6 字段，默认 `max_concurrent_subagents=4` / `max_aggregate_chars=120*1024` / `max_subagent_result_chars=50*1024` / `max_retries=2` / `max_lane_iterations=8` / `scratch_root="orch_scratch"`）、`load_orch_settings() -> OrchSettings`（读 `SettingsRepository().get_json("app_settings")` 的 `orch` 段，camelCase keys，单键类型守卫，缺省回落默认值）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_orch_settings.py
"""P2-9 — orch_settings 配置化：默认值 + app_settings 覆盖 + 缺 orch 段回落。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.orchestration.orch_settings import OrchSettings, load_orch_settings


def test_defaults_when_no_app_settings():
    """SettingsRepository 无数据 / 抛错 → 全默认。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = None
        s = load_orch_settings()
    assert s == OrchSettings()
    assert s.max_concurrent_subagents == 4
    assert s.max_aggregate_chars == 120 * 1024
    assert s.scratch_root == "orch_scratch"


def test_overrides_from_app_settings_orch_section():
    """app_settings.orch 段覆盖对应键（camelCase 键名）。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConcurrentSubagents": 8,
                "maxRetries": 3,
                "scratchRoot": "custom_scratch",
            }
        }
        s = load_orch_settings()
    assert s.max_concurrent_subagents == 8
    assert s.max_retries == 3
    assert s.scratch_root == "custom_scratch"
    # 未覆盖键回落默认
    assert s.max_aggregate_chars == 120 * 1024
    assert s.max_lane_iterations == 8


def test_bad_typed_keys_fall_back_per_key():
    """单个坏键（非目标类型）只回落该键默认，不整段丢弃。"""
    with patch("backend.orchestration.orch_settings.SettingsRepository") as repo_cls:
        repo_cls.return_value.get_json.return_value = {
            "orch": {
                "maxConcurrentSubagents": "8",  # str 而非 int → 回落
                "maxSubagentResultChars": 30_000,  # 合法
            }
        }
        s = load_orch_settings()
    assert s.max_concurrent_subagents == 4
    assert s.max_subagent_result_chars == 30_000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.orchestration.orch_settings'`

- [ ] **Step 3: 写最小实现**

```python
# backend/orchestration/orch_settings.py
"""``orch_settings`` — 编排执行参数配置化（P2-9）。

从持久化 ``app_settings`` 读 ``orch`` 段（camelCase keys，与前端
``OrchSettings`` interface 对齐）。旧设置无 orch 段 → 全默认，绝不抛穿。
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from backend.data.settings_repo import SettingsRepository

#: app_settings.orch 段的 camelCase key → OrchSettings 字段名映射。
#: 与前端 src/entities/setting/types.ts 的 OrchSettings interface 对齐。
_RAW_KEYS = {
    "maxConcurrentSubagents": "max_concurrent_subagents",
    "maxAggregateChars": "max_aggregate_chars",
    "maxSubagentResultChars": "max_subagent_result_chars",
    "maxRetries": "max_retries",
    "maxLaneIterations": "max_lane_iterations",
    "scratchRoot": "scratch_root",
}


@dataclass
class OrchSettings:
    max_concurrent_subagents: int = 4
    max_aggregate_chars: int = 120 * 1024
    max_subagent_result_chars: int = 50 * 1024
    max_retries: int = 2
    max_lane_iterations: int = 8
    scratch_root: str = "orch_scratch"


def load_orch_settings() -> OrchSettings:
    """从持久化 app_settings 读 orch 段，缺省回落默认值。

    单键读取 + 类型守卫：orch 段是用户可控 JSON，单个坏键只回落该键默认，
    不因一个坏键把整段丢弃（防御 load_orch_settings 上游的脏数据）。
    """
    try:
        raw = SettingsRepository().get_json("app_settings") or {}
        orch = raw.get("orch", {}) if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 — 读配置失败回落默认，绝不抛穿
        orch = {}
    settings = OrchSettings()
    for camel, field_name in _RAW_KEYS.items():
        value = orch.get(camel)
        current = getattr(settings, field_name)
        if value is None:
            continue
        if isinstance(current, int):
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            settings = replace(settings, **{field_name: value})
        elif isinstance(current, str) and isinstance(value, str):
            settings = replace(settings, **{field_name: value})
    return settings
```

- [ ] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_settings.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/orch_settings.py backend/tests/unit/test_orch_settings.py
git commit -m "feat(orch): P2-9 编排参数配置化 — OrchSettings 数据类 + load_orch_settings"
```

---

## Task A2: ChatDispatcher 构造注入 OrchSettings

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py:35-62`（模块常量）、`:115-153`（`__init__`）、`:266`（RecoveryPolicy）、`:293-296`（MAX_LANE_ITERATIONS）、`:311`（SCRATCH_ROOT）
- Modify: `backend/api/legacy_routes.py:1760`（装配 `settings=load_orch_settings()`）
- Test: `backend/tests/unit/test_chat_dispatcher.py`（构造默认不传 → 回落默认）

**Interfaces:**
- Consumes: `load_orch_settings()` from A1。
- Produces: `ChatDispatcher.__init__(..., settings: Optional[OrchSettings] = None)` — `self.settings = settings or load_orch_settings()`；模块常量改实例引用（`_semaphore`、`_aggregate` 截断、`RecoveryPolicy.max_retries`、`MAX_LANE_ITERATIONS`、`SCRATCH_ROOT`）。**模块常量保留**（`MAX_OUTPUT_PREVIEW_CHARS=500` 不配置化，spec §3.3 只列 5 个数值键 + scratch_root）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher.py（追加）
"""P2-9 — dispatcher 注入 OrchSettings：构造注入覆盖默认；缺省回落。"""
import asyncio

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.orch_settings import OrchSettings


def test_dispatcher_injects_settings():
    """构造传入 settings → 实例用它（semaphore/retry/scratch）。"""
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
        settings=OrchSettings(max_concurrent_subagents=1, scratch_root="custom"),
    )
    assert d._semaphore._value == 1
    assert d.settings.scratch_root == "custom"


def test_dispatcher_defaults_settings_when_omitted():
    """不传 settings → load_orch_settings() 回落默认。"""
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    assert d.settings.max_concurrent_subagents == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -k "inject or defaults" -v`
Expected: FAIL — `ChatDispatcher.__init__() got an unexpected keyword argument 'settings'` / `AttributeError: 'ChatDispatcher' object has no attribute 'settings'`

- [ ] **Step 3: 写最小实现**

`chat_dispatcher.py` `__init__` 签名增参数并在构造体顶部初始化：

```python
def __init__(
    self,
    stream_id: str,
    entry_queue: Any,
    run_id: Optional[str] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    total_tasks: Optional[int] = None,
    settings: Optional[OrchSettings] = None,
) -> None:
    ...
    # P2-9 (2026-08-14): 执行参数配置化 —— 模块常量改实例引用。
    self.settings = settings or load_orch_settings()
    ...
    self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_subagents)
```

模块顶部 import 补 `from backend.orchestration.orch_settings import OrchSettings, load_orch_settings`（放在既有 import 块末尾）。

将以下模块常量的**使用点**改为 `self.settings.*`（常量定义保留，避免破坏其它引用，A2 只改 use-site）：
- `_run_subagent` 内 `RecoveryPolicy(on_failure="retry", max_retries=2)` → `max_retries=self.settings.max_retries`
- `_run_subagent` 内 `if iterations >= MAX_LANE_ITERATIONS:` 及错误消息里的 `MAX_LANE_ITERATIONS` → `self.settings.max_lane_iterations`
- `_aggregate` 内 `MAX_SUBAGENT_RESULT_CHARS` / `MAX_AGGREGATE_CHARS` → `self.settings.max_subagent_result_chars` / `self.settings.max_aggregate_chars`
- `_scratch_dir_for` 内 `SCRATCH_ROOT` → `self.settings.scratch_root`

`legacy_routes.py` 装配处（`:1760` `ChatDispatcher(` 调用）增：

```python
dispatcher = ChatDispatcher(
    stream_id=stream_id,
    entry_queue=entry.queue,
    run_id=run_id,
    llm_config=llm_config,
    total_tasks=len(plan_tasks),
    settings=load_orch_settings(),
)
```

（`load_orch_settings` 在 legacy_routes 顶部 import：`from backend.orchestration.orch_settings import load_orch_settings`，放在 `from backend.orchestration.chat_dispatcher import _classify_orchestration_mode` 附近。）

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -k "inject or defaults" -v`
Expected: 2 passed
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py backend/tests/unit/test_chat_dispatcher_persistence.py backend/tests/unit/test_chat_dispatcher_resume.py -q`
Expected: 全绿（settings 注入不破坏既有构造）

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/api/legacy_routes.py backend/tests/unit/test_chat_dispatcher.py
git commit -m "feat(orch): P2-9 dispatcher 注入 OrchSettings — 并发/截断/重试/迭代/scratch 全参数化"
```

---

## Task A3: `dispatch_subagents` 工具 schema 加必填 task_id

**Files:**
- Modify: `backend/tools/subagent_tool.py:25-43`（`INPUT_SCHEMA`）
- Modify: `backend/tools/subagent_tool.py` 模块 docstring（`[{agent_id, goal}]` → `[{task_id, agent_id, goal}]`）
- Test: `backend/tests/unit/test_subagent_tool.py`

**Interfaces:**
- Produces: `INPUT_SCHEMA` 的 tasks.items 增 `"task_id": {"type": "string"}`，`required` 变 `["agent_id", "goal", "task_id"]`（conductor 必须回传计划编号；dispatcher 端仍对缺 task_id 宽容 — 见 A4）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_subagent_tool.py（追加）
"""P2-7 — dispatch_subagents schema 要求每任务带 task_id。"""
from backend.tools.subagent_tool import INPUT_SCHEMA


def test_input_schema_requires_task_id():
    """task_id 必填，与 agent_id/goal 同列 required。"""
    items = INPUT_SCHEMA["properties"]["tasks"]["items"]
    assert "task_id" in items["properties"]
    assert items["properties"]["task_id"] == {"type": "string"}
    assert items["required"] == ["agent_id", "goal", "task_id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_tool.py -k task_id -v`
Expected: FAIL — `'task_id' not in items["properties"]`

- [ ] **Step 3: 写最小实现**

`backend/tools/subagent_tool.py`：

```python
INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    # P2-7 (2026-08-14): conductor 必须回传计划编号 task_id
                    #（task_plan 事件的 t1..tN），dispatcher 据此与权威计划对齐。
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "goal": {"type": "string", "maxLength": 2000},
                },
                "required": ["agent_id", "goal", "task_id"],
            },
        }
    },
    "required": ["tasks"],
}
```

docstring 同步把 `[{agent_id, goal}]` 改成 `[{task_id, agent_id, goal}]`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_tool.py -v`
Expected: 全绿（既有 schema 结构断言若断言 `required == ["agent_id","goal"]` 会失败 → 同步更新该断言为三键）
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/tools/subagent_tool.py backend/tests/unit/test_subagent_tool.py
git commit -m "feat(orch): P2-7 dispatch_subagents schema 必填 task_id"
```

---

## Task A4: ChatDispatcher 计划权威 dispatch（三态路由 + review 门适配）

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py:155-242`（`dispatch()`）、`__init__`（`_plan_by_id` / `_plan_loaded` / `_dispatched_plan_ids`）
- Test: `backend/tests/unit/test_chat_dispatcher_plan_authority.py`（新建）

**Interfaces:**
- Consumes: `self._orch_run_repo`（既有）、`plan_json`（init_orch_run 落库，DB 单源）。
- Produces:
  - `self._plan_by_id: Dict[str, dict]`（task_id → `{"agent_id","goal","depends_on",...}`），首 dispatch 读库缓存。
  - `self._dispatched_plan_ids: Set[str]`（已派发且匹配计划的 task_id）。
  - `_ensure_plan_loaded()`：首 dispatch 时从 `self._orch_run_repo.get(self.run_id)` 读 `plan_json.tasks` 建索引；读库失败/空 → `_plan_by_id` 保持空（后续走未知/缺省路由）。
  - `dispatch()` 三态路由：**匹配计划**（`raw["task_id"] in _plan_by_id`）→ goal/agent 以计划为准 + 记入 `_dispatched_plan_ids`；**未知 task_id**（不在计划）→ 回退 tool-passed 值；**缺 task_id** → 自分配 `t{_next_task_index+1}`（计数器仅作缺省）。
  - review 门：`_plan_by_id` 非空 → 计划全部 task_id 已派发才触发；否则回退 `_next_task_index >= total_tasks`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher_plan_authority.py
"""P2-7 — 计划权威派发：匹配用计划 goal/agent、未知回退 tool 值、缺省自分配。"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher


def _mk_dispatcher(tmp_path, monkeypatch, plan_json: str):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    d.init_orch_run(session_id="s-1", plan_json=plan_json)
    return d


async def _drain(d: ChatDispatcher):
    """让 dispatch 直接执行（不真跑子 agent）：mock _run_subagent。"""
    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
    d._run_subagent = fake_run


@pytest.mark.asyncio()
async def test_plan_matched_task_uses_plan_goal_agent(tmp_path, monkeypatch):
    """task_id 匹配计划 → goal/agent 以计划为准（覆盖 tool-passed 值）。"""
    plan = json.dumps(
        {
            "tasks": [
                {"task_id": "t1", "agent_id": "writer", "goal": "计划目标1"},
                {"task_id": "t2", "agent_id": "researcher", "goal": "计划目标2"},
            ],
            "reasoning": "",
        },
        ensure_ascii=False,
    )
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    # conductor 故意传错 goal/agent —— 计划权威应覆盖
    out = await d.dispatch(
        [{"task_id": "t1", "agent_id": "wrong", "goal": "错误目标"},
         {"task_id": "t2", "agent_id": "wrong", "goal": "错误目标"}]
    )
    assert d._states["t1"].goal == "计划目标1"
    assert d._states["t1"].agent_id == "writer"
    assert d._states["t2"].goal == "计划目标2"
    assert "ok" in out


@pytest.mark.asyncio()
async def test_unknown_task_id_falls_back_to_tool_values(tmp_path, monkeypatch):
    """未知 task_id（不在计划）→ 回退 tool-passed 值，允许动态加任务。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    await d.dispatch([{"task_id": "t9", "agent_id": "researcher", "goal": "动态任务"}])
    assert d._states["t9"].goal == "动态任务"
    assert d._states["t9"].agent_id == "researcher"


@pytest.mark.asyncio()
async def test_missing_task_id_auto_assigns(tmp_path, monkeypatch):
    """缺 task_id（malformed/旧客户端）→ 自分配 t{next}，跳过计划已占编号。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    await d.dispatch([{"agent_id": "researcher", "goal": "无编号"}])
    assigned = [k for k in d._states if k.startswith("t") and d._states[k].goal == "无编号"]
    # 计划权威下 t1 已被计划占用 → 自分配跳过 → t2（不撞计划编号）
    assert assigned == ["t2"]
    assert d._states["t1"].agent_id == "writer"  # 计划 t1 未被缺省分配覆盖

@pytest.mark.asyncio()
async def test_plan_by_id_built_once_at_first_dispatch(tmp_path, monkeypatch):
    """_plan_by_id 只建一次：首 dispatch 后缓存，后续复用（编辑在首派发前生效）。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    # 首派发前改库 → 首派发读到编辑后计划
    repo = d._orch_run_repo
    run = repo.get("orch-test")
    run.plan_json = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "coder", "goal": "编辑后"}], "reasoning": ""})
    repo.upsert(run)
    await d.dispatch([{"task_id": "t1", "agent_id": "wrong", "goal": "x"}])
    assert d._states["t1"].goal == "编辑后"
    assert d._states["t1"].agent_id == "coder"
    # 首派发后再改库 → 缓存不重建：第二次派发仍用首次索引
    run = repo.get("orch-test")
    run.plan_json = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "再改"}], "reasoning": ""})
    repo.upsert(run)
    await d.dispatch([{"task_id": "t1", "agent_id": "wrong", "goal": "x"}])
    assert d._states["t1"].goal == "编辑后"  # 缓存生效，不读到"再改"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_plan_authority.py -v`
Expected: FAIL — 现 dispatch 忽略 task_id，全部重编号（`t1/t2` 错位 / 计划目标不生效）。

- [ ] **Step 3: 写最小实现**

`__init__` 末尾追加：

```python
# P2-7 (2026-08-14): 计划权威 —— 首 dispatch 从 orch_runs.plan_json 读权威
# 计划建索引；_dispatched_plan_ids 记录已派发的计划 task_id（review 门用）。
self._plan_by_id: Dict[str, dict] = {}
self._plan_loaded = False
self._dispatched_plan_ids: Set[str] = set()
```

`dispatch()` 头部（`if self._first_dispatch_at is None:` 块之后）插入：

```python
self._ensure_plan_loaded()
```

新增方法（放在 `dispatch` 之前）：

```python
def _ensure_plan_loaded(self) -> None:
    """首 dispatch 时从 orch_runs.plan_json 读权威计划建索引（DB 单源）。

    计划卡 update_plan 在派发前落库 → 首派发即读到编辑后计划。读库失败/空 →
    _plan_by_id 保持空，后续走未知/缺省路由（不强制闭环）。只建一次。
    """
    if self._plan_loaded:
        return
    self._plan_loaded = True
    try:
        run = self._orch_run_repo.get(self.run_id)
        if run and run.plan_json:
            raw = json.loads(run.plan_json)
            tasks = raw.get("tasks", []) if isinstance(raw, dict) else []
            self._plan_by_id = {
                t["task_id"]: t
                for t in tasks
                if isinstance(t, dict) and t.get("task_id")
            }
    except Exception as exc:  # noqa: BLE001 — 读库失败降级，不阻塞派发
        logger.warning("计划权威索引构建失败 run=%s err=%s", self.run_id, exc)
```

`dispatch()` 主循环改为三态路由：

```python
states: List[ChatTaskState] = []
for raw in tasks:
    raw_task_id = raw.get("task_id")
    if raw_task_id and raw_task_id in self._plan_by_id:
        # P2-7 计划权威：goal/agent 以计划为准（覆盖 tool-passed；计划卡编辑
        # 在派发前生效的杠杆点）。depends_on 直接随 plan_json 透传（A4 不用）。
        plan_item = self._plan_by_id[raw_task_id]
        task_id = raw_task_id
        agent_id = str(plan_item.get("agent_id", raw.get("agent_id", "primary")))
        goal = str(plan_item.get("goal", raw.get("goal", "")))
        self._dispatched_plan_ids.add(task_id)
    elif raw_task_id:
        # 未知 task_id（不在计划）→ 回退 tool-passed 值，允许 conductor 动态加任务。
        task_id = raw_task_id
        agent_id = str(raw.get("agent_id", "primary"))
        goal = str(raw.get("goal", ""))
    else:
        # 缺 task_id（malformed/旧客户端）→ 自分配（保留 _next_task_index 作缺省计数器）。
        # 跳过循环：候选号撞计划编号或已用状态则递增（计划权威下 t1..tN 已占用）。
        task_id = f"t{self._next_task_index + 1}"
        while task_id in self._plan_by_id or task_id in self._states:
            self._next_task_index += 1
            task_id = f"t{self._next_task_index + 1}"
        self._next_task_index += 1
        agent_id = str(raw.get("agent_id", "primary"))
        goal = str(raw.get("goal", ""))
    state = ChatTaskState(task_id=task_id, agent_id=agent_id, goal=goal)
    self._states[state.task_id] = state
    states.append(state)
    self._emit_task_status(state)  # queued
```

（删除原 `try/except KeyError` 占位分支 —— 现在 `raw.get("agent_id", ...)` 永不 KeyError；malformed 输入由三态路由的缺省分支兜底。）

review 门改为：

```python
if self.total_tasks and not self._reviewed:
    if self._plan_by_id:
        # 计划权威下：计划全部 task_id 已派发 → 触发验证环
        plan_covered = set(self._plan_by_id).issubset(self._dispatched_plan_ids)
    else:
        # 无计划（DB 空/读失败）→ 回退旧门（计数器覆盖 total）
        plan_covered = self._next_task_index >= self.total_tasks
    if plan_covered:
        self._reviewed = True
        try:
            review = await self._run_review(aggregated)
            aggregated = aggregated + review["block"]
        except Exception as exc:  # noqa: BLE001 — 复核失败降级
            self._reviewed = False
            logger.warning("编排复核失败，跳过验证: %s", exc)
```

`chat_dispatcher.py` 顶部 import 补 `from typing import Set`（若无）与 `import json`（若无）。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_plan_authority.py -v`
Expected: 4 passed（缺省自分配断言 `t2`：计划占用 t1 → 跳过循环生效）
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py backend/tests/unit/test_chat_dispatcher_review_event.py backend/tests/integration/test_chat_orchestration_stream.py -q`
Expected: 全绿（既有 dispatch 测试若传无 task_id 的 tasks → 走自分配分支，编号从 t1 起，语义不变）

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/tests/unit/test_chat_dispatcher_plan_authority.py
git commit -m "feat(orch): P2-7 计划权威 dispatch — 三态路由 + review 门按计划覆盖"
```

---

## Task A5: `templates.py` 内置模板

**Files:**
- Create: `backend/orchestration/templates.py`
- Test: `backend/tests/unit/test_templates.py`

**Interfaces:**
- Produces: `TemplateStage`（id/agent_id/goal/depends_on）、`OrchestrationTemplate`（id/name/description/stages）、`BUILTIN_TEMPLATES: Dict[str, OrchestrationTemplate]`（`research-write` 2 stage + `gather-analyze-report` 3 stage）、`get_template(tid) -> Optional[OrchestrationTemplate]`、`list_templates() -> List[dict]`（`{id, name, description, stages: [id,...]}`）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_templates.py
"""P2-8 — 内置确定性模板：get/list + 结构。"""
from backend.orchestration.templates import BUILTIN_TEMPLATES, get_template, list_templates


def test_builtin_research_write():
    t = get_template("research-write")
    assert t is not None
    assert [s.id for s in t.stages] == ["t1", "t2"]
    assert t.stages[0].agent_id == "researcher"
    assert t.stages[1].agent_id == "writer"
    assert t.stages[1].depends_on == ["t1"]
    assert "{request}" in t.stages[0].goal


def test_builtin_gather_analyze_report():
    t = get_template("gather-analyze-report")
    assert t is not None
    assert [s.id for s in t.stages] == ["t1", "t2", "t3"]
    assert t.stages[2].depends_on == ["t1", "t2"]
    # 全 stage 用可派发角色（偏差 2：gather/analyze 不存在 → researcher/writer）
    assert all(s.agent_id in {"researcher", "writer", "coder", "reviewer"} for s in t.stages)


def test_get_unknown_returns_none():
    assert get_template("nope") is None


def test_list_templates_metadata():
    listed = {t["id"]: t for t in list_templates()}
    assert set(listed) == {"research-write", "gather-analyze-report"}
    assert listed["research-write"]["stages"] == ["t1", "t2"]
    assert listed["research-write"]["name"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.orchestration.templates'`

- [ ] **Step 3: 写最小实现**

```python
# backend/orchestration/templates.py
"""``templates`` — 确定性编排模板（P2-8）。

``orchestration_mode="template:<id>"`` 走模板拆解：阶段 goal 可含 ``{request}``
占位符，运行时 ``str.replace`` 替换（同 classify 模式，防 .format() 抛错）。
**review 不进模板** —— 现有 P0-2 验证环自动兜底，模板含 review stage 会双重评审。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TemplateStage:
    id: str            # t1..tN（模板内序号，depends_on 引用它）
    agent_id: str      # 建议角色（需可派发，否则 planner 回退 primary）
    goal: str          # 可含 {request} 占位符
    depends_on: List[str] = field(default_factory=list)


@dataclass
class OrchestrationTemplate:
    id: str
    name: str
    description: str
    stages: List[TemplateStage]


BUILTIN_TEMPLATES: Dict[str, OrchestrationTemplate] = {
    "research-write": OrchestrationTemplate(
        id="research-write",
        name="调研与写作",
        description="researcher 调研 → writer 成文（两阶段串行）",
        stages=[
            TemplateStage(
                id="t1",
                agent_id="researcher",
                goal="调研 {request}，收集事实与数据，产出结构化要点",
            ),
            TemplateStage(
                id="t2",
                agent_id="writer",
                goal="基于调研要点撰写完整成文：{request}",
                depends_on=["t1"],
            ),
        ],
    ),
    "gather-analyze-report": OrchestrationTemplate(
        id="gather-analyze-report",
        name="收集-分析-报告",
        description="researcher 收集 → researcher 分析 → writer 报告（三阶段串行）",
        stages=[
            TemplateStage(
                id="t1",
                agent_id="researcher",
                goal="收集与 {request} 相关的资料、数据与引用",
            ),
            TemplateStage(
                id="t2",
                agent_id="researcher",
                goal="分析已收集资料，提炼洞察与结论：{request}",
                depends_on=["t1"],
            ),
            TemplateStage(
                id="t3",
                agent_id="writer",
                goal="将分析结论整理成结构化报告：{request}",
                depends_on=["t1", "t2"],
            ),
        ],
    ),
}


def get_template(template_id: str) -> Optional[OrchestrationTemplate]:
    return BUILTIN_TEMPLATES.get(template_id)


def list_templates() -> List[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "stages": [s.id for s in t.stages],
        }
        for t in BUILTIN_TEMPLATES.values()
    ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_templates.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/templates.py backend/tests/unit/test_templates.py
git commit -m "feat(orch): P2-8 内置确定性模板 — research-write + gather-analyze-report"
```

---

## Task A6: `Planner.decompose_from_template`

**Files:**
- Modify: `backend/orchestration/planner.py`（新增方法）
- Test: `backend/tests/unit/test_templates.py`（追加 decompose 测试）

**Interfaces:**
- Consumes: `get_template`（A5）、`_is_dispatchable_agent`（既有 F4）、`self.task_registry` / `self.team_registry`。
- Produces: `Planner.decompose_from_template(template_id: str, request: str) -> Plan`（模板不存在 → `ValueError`；`reasoning=f"template: {template_id}"`；stage `{request}` 用 str.replace，无占位符追加 `\n目标: {request}`；`agent_hint` 仅当 `_is_dispatchable_agent` 为真时写入；`depends_on` 在 task 创建后解析）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_templates.py（追加）
"""P2-8 — decompose_from_template：确定性拆解 + 角色校验 + 依赖解析。"""
import pytest

from backend.orchestration.planner import Planner
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry
from backend.orchestration.templates import OrchestrationTemplate, TemplateStage


def _planner():
    return Planner(
        task_registry=TaskRegistry(),
        team_registry=TeamRegistry(),
        llm_client=None,  # 模板不走 LLM，auto_configure 亦关
        auto_configure=False,
    )


@pytest.mark.asyncio()
async def test_decompose_from_template_resolves_stages():
    plan = await _planner().decompose_from_template("research-write", "写一篇报告")
    assert plan.reasoning == "template: research-write"
    assert len(plan.tasks) == 2
    by_stage = {plan.tasks[0].name: plan.tasks[0], plan.tasks[1].name: plan.tasks[1]}
    # {request} 已替换
    assert "写一篇报告" in plan.tasks[0].description
    assert plan.tasks[1].blocked_by == [plan.tasks[0].task_id]
    # 角色 hint 可派发 → 写入
    assert plan.tasks[0].parameters.get("agent_hint") == "researcher"
    assert plan.tasks[1].parameters.get("agent_hint") == "writer"


@pytest.mark.asyncio()
async def test_decompose_from_template_skips_undispatchable_role():
    """非法角色（F4 回退）→ 不写 agent_hint。"""
    p = _planner()
    t = OrchestrationTemplate(
        id="t-invalid",
        name="非法角色模板",
        description="",
        stages=[TemplateStage(id="t1", agent_id="ghost_agent", goal="做 {request}")],
    )
    # 直接 monkeypatch 内置表，避免污染全局
    import backend.orchestration.templates as tmpl

    orig = tmpl.BUILTIN_TEMPLATES
    tmpl.BUILTIN_TEMPLATES = {**orig, "t-invalid": t}
    try:
        plan = await p.decompose_from_template("t-invalid", "目标")
    finally:
        tmpl.BUILTIN_TEMPLATES = orig
    assert plan.tasks[0].parameters.get("agent_hint") is None
    assert "目标" in plan.tasks[0].description


@pytest.mark.asyncio()
async def test_decompose_from_template_unknown_raises():
    with pytest.raises(ValueError):
        await _planner().decompose_from_template("nope", "目标")


@pytest.mark.asyncio()
async def test_decompose_from_template_no_placeholder_appends_goal():
    """stage goal 无 {request} → 追加目标行。"""
    plan = await _planner().decompose_from_template("research-write", "写报告")
    # 内置模板都带占位符；用一个合成 stage 验证追加逻辑
    assert "写报告" in plan.tasks[0].description  # 内置 {request} 路径已覆盖
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_templates.py -k decompose -v`
Expected: FAIL — `AttributeError: 'Planner' object has no attribute 'decompose_from_template'`

- [ ] **Step 3: 写最小实现**

`backend/orchestration/planner.py` 新增方法（放 `decompose_request` 之后）：

```python
async def decompose_from_template(
    self,
    template_id: str,
    request: str,
) -> Plan:
    """按内置模板确定性拆解（P2-8）—— 不走 LLM，可复现。

    模板不存在 → ``ValueError``（caller 降级 single）。stage goal 的
    ``{request}`` 用 ``str.replace`` 替换（同 classify，防 .format() 抛错）；
    无占位符则追加 ``\n目标: {request}``。``agent_hint`` 仅当角色可派发时
    写入（复用 F4 校验，否则回退 conductor 默认角色）。
    """
    import uuid

    from backend.orchestration.templates import get_template

    template = get_template(template_id)
    if template is None:
        raise ValueError(f"unknown orchestration template: {template_id}")

    team = self.team_registry.create_team(
        name=f"Template {template.name}: {request[:50]}",
        metadata={
            "original_request": request,
            "source": "template",
            "template": template_id,
        },
    )

    created_tasks: List[Task] = []
    stage_to_task: Dict[str, str] = {}
    for stage in template.stages:
        goal = (
            stage.goal.replace("{request}", request)
            if "{request}" in stage.goal
            else f"{stage.goal}\n目标: {request}"
        )
        parameters: Dict[str, Any] = {}
        if _is_dispatchable_agent(stage.agent_id):
            parameters["agent_hint"] = stage.agent_id
        task = Task(
            task_id=f"task-{uuid.uuid4().hex[:12]}",
            name=stage.id,  # 模板 stage 序号 t1..tN（depends_on 引用它）
            description=goal,
            task_type="general",
            parameters=parameters,
            blocked_by=[],
            team_id=team.team_id,
        )
        self.task_registry.create_task(task)
        created_tasks.append(task)
        stage_to_task[stage.id] = task.task_id
        self.team_registry.add_task(team.team_id, task.task_id)

    # 第二遍：stage.id 依赖 → 真实 task_id（只引更早任务，保 DAG）。
    created_by_id = {t.task_id: t for t in created_tasks}
    for stage, task in zip(template.stages, created_tasks):
        resolved = [stage_to_task[dep] for dep in stage.depends_on if dep in stage_to_task]
        if not resolved:
            continue
        task.blocked_by = resolved
        self.task_registry.repo.update(task)
        for dep_id in resolved:
            dep_task = created_by_id.get(dep_id)
            if dep_task is not None and task.task_id not in dep_task.blocks:
                dep_task.blocks.append(task.task_id)
                self.task_registry.repo.update(dep_task)

    return Plan(
        plan_id=f"plan-{uuid.uuid4().hex[:12]}",
        team_id=team.team_id,
        tasks=created_tasks,
        original_request=request,
        reasoning=f"template: {template_id}",
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_templates.py -v`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/planner.py backend/tests/unit/test_templates.py
git commit -m "feat(orch): P2-8 Planner.decompose_from_template — 确定性拆解"
```

---

## Task A7: legacy_routes 模板模式集成

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py:65-93`（`_classify_orchestration_mode` 加 `template:` 前缀分支）
- Modify: `backend/api/legacy_routes.py:1728-1749`（multi 分支按 template_id 分流 decompose）
- Test: `backend/tests/integration/test_chat_orchestration_stream.py`

**Interfaces:**
- Consumes: `decompose_from_template`（A6）。
- Produces: `_classify_orchestration_mode` 对 `orchestration_mode.startswith("template:")` 直接返回 `"multi"`（模板即强制编排，跳过二分类）；legacy multi 分支 `template_id = data.orchestration_mode.split(":", 1)[1]`，模板不存在 → `logger.warning` + 降级 single。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_chat_orchestration_stream.py（追加）
"""P2-8 — orchestration_mode=template:<id> 走模板拆解。"""
import asyncio

from backend.orchestration.chat_dispatcher import _classify_orchestration_mode


@pytest.mark.asyncio()
async def test_classify_template_prefix_is_multi():
    """template: 前缀 → 直接 multi（跳过 LLM 二分类）。"""
    mode = await _classify_orchestration_mode("随便一句话", "template:research-write", llm_client=None)
    assert mode == "multi"


@pytest.mark.asyncio()
async def test_classify_unknown_template_still_multi():
    """未知模板 id 也判 multi（降级在 decompose 层，不在这里）。"""
    mode = await _classify_orchestration_mode("x", "template:nope", llm_client=None)
    assert mode == "multi"
```

（full-stream 模板集成：若 test_chat_orchestration_stream.py 已有完整 SSE 测试骨架，补一条 `orchestration_mode="template:research-write"` 的 task_plan 事件断言 `len(plan)==2` 且 `goal` 含用户请求。若骨架复杂，仅保留上面的 classify 单测 + 下 Step 3 的手工验证即可。）

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -k template -v`
Expected: FAIL — `_classify_orchestration_mode` 返回 single（未识别前缀）

- [ ] **Step 3: 写最小实现**

`chat_dispatcher.py` `_classify_orchestration_mode` 开头加：

```python
# P2-8 (2026-08-14): template:<id> 即强制编排 —— 跳过 LLM 二分类。
# 模板存在性在 decompose_from_template 校验（不存在 → 降级 single）。
if orchestration_mode.startswith("template:"):
    return "multi"
if orchestration_mode == "force_multi":
    return "multi"
```

`legacy_routes.py` multi 分支拆解处（`plan = await Planner(...).decompose_request(data.message)` 前）改：

```python
# P2-8 (2026-08-14): orchestration_mode=template:<id> → 确定性模板拆解。
orchestration_mode = data.orchestration_mode or "auto"
template_id = (
    orchestration_mode.split(":", 1)[1]
    if orchestration_mode.startswith("template:")
    else None
)
try:
    if template_id is not None:
        plan = await Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
            llm_client=build_llm_client_from_settings(),
        ).decompose_from_template(template_id, data.message)
    else:
        plan = await Planner(
            task_registry=TaskRegistry(),
            team_registry=TeamRegistry(),
            llm_client=build_llm_client_from_settings(),
        ).decompose_request(data.message)
    plan_tasks = list(plan.tasks if plan else [])
except Exception as exc:  # noqa: BLE001 — 模板/规划失败降级 single
    if template_id is not None:
        logger.warning("编排模板 %s 拆解失败，降级 single: %s", template_id, exc)
    else:
        logger.warning("编排规划失败，降级 single: %s", exc)
    mode = "single"
    plan_tasks = []
```

（下游 `len(plan_tasks) <= 1 → single`、plan_block、init_orch_run、task_plan/task_progress 全复用既有逻辑，模板 tasks 结构与 decompose_request 同构。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -k template -v`
Expected: 2 passed
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/api/legacy_routes.py backend/tests/integration/test_chat_orchestration_stream.py
git commit -m "feat(orch): P2-8 orchestration_mode=template:<id> 集成 legacy 路由"
```

---

## Task A8: run 级取消（注册表 + Event + 端点）

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py`（`_ACTIVE_DISPATCHERS` 模块级注册表 + `_cancelled` Event + `cancel()` + `_run_one` 开头检查）
- Modify: `backend/api/legacy_routes.py`（构造后注册 + `finally` 注销）
- Modify: `backend/api/orch_routes.py`（新增 `POST /runs/{run_id}/cancel`）
- Test: `backend/tests/unit/test_chat_dispatcher_cancel.py`（新建）+ integration

**Interfaces:**
- Produces:
  - `_ACTIVE_DISPATCHERS: Dict[str, "ChatDispatcher"]`（模块级；legacy 构造后 `[run_id]=dispatcher`，producer `finally` 中 `pop`）。
  - `ChatDispatcher.cancel() -> bool`（`_cancelled` asyncio.Event 幂等 set；已 set 返回 False）。
  - `_run_one`：`async with self._semaphore:` **之后**、`state.status="running"` 前判 `self._cancelled.is_set()` → `state.status="cancelled"; state.error="cancelled by user"; _emit_task_status; return`（排队等槽的任务拿到槽后短路；running 子任务已过守卫不硬杀）。
  - `dispatch()` 的 `asyncio.gather` 过滤 `status not in ("failed", "cancelled")`。
  - `POST /api/v1/orch/runs/{run_id}/cancel`：404（run 不存在）/ 409（终态：cancelled/completed/failed）/ `repo.update_status(run_id, "cancelled")` + `_ACTIVE_DISPATCHERS.get(run_id)?.cancel()`（同步 set，无需 await）/ 返回 `{"ok": True, "run_id", "status": "cancelled"}`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher_cancel.py
"""P2-9/PR A — run 级取消：queued 转 cancelled、幂等、running 不硬杀。"""
from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher


def _init_tmp_db(tmp_path, monkeypatch):
    """SAGE_DB_PATH 隔离 —— 经 dispatch() 会触发 orch_repo 落库，指向 tmp 而非真实 data。"""
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "cancel.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio()
async def test_cancel_is_idempotent():
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    assert d.cancel() is True
    assert d.cancel() is False  # 已 set
    assert d._cancelled.is_set()


@pytest.mark.asyncio()
async def test_cancel_before_dispatch_skips_queued_in_gather(tmp_path, monkeypatch):
    """dispatch 前 cancel → 全部 queued 转 cancelled，不做任何子任务。

    注：_run_one 是 dispatch() 内的嵌套闭包，不能 `await d._run_one(state)` 直接调
    （AttributeError）—— 一律经 dispatch() 走 gather 触发。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    ran = []

    async def fake_run(state):
        ran.append(state.task_id)

    d._run_subagent = fake_run
    d.cancel()
    await d.dispatch([{"task_id": "t1", "agent_id": "r", "goal": "g"}])
    assert ran == []  # 守卫在 acquire 后拦截，未调 _run_subagent
    assert d._states["t1"].status == "cancelled"
    assert d._states["t1"].error == "cancelled by user"


@pytest.mark.asyncio()
async def test_cancel_during_run_short_circuits_queued(tmp_path, monkeypatch):
    """cancel 在 t1 running 时到达 → t1 放行完成；排队等槽的 t2 拿到槽后短路为 cancelled。

    复现信号量竞态：守卫若只在 `_run_one` 入口判取消，排队在信号量上的 t2
    已在 cancel 前越过守卫，拿到槽后会照跑。守卫必须在 acquire 之后（见 Step 3）。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    d._semaphore = asyncio.Semaphore(1)  # 单槽 → t2 在信号量上排队
    t1_started = asyncio.Event()
    release_t1 = asyncio.Event()
    ran = []

    async def fake_run(state):
        ran.append(state.task_id)
        if state.task_id == "t1":
            t1_started.set()          # t1 已进入执行
            await release_t1.wait()   # 阻塞让 t2 排队
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    dispatch_task = asyncio.create_task(
        d.dispatch(
            [
                {"task_id": "t1", "agent_id": "r", "goal": "g1"},
                {"task_id": "t2", "agent_id": "r", "goal": "g2"},
            ]
        )
    )
    await t1_started.wait()  # 确定性：t1 running，t2 已阻塞在信号量上
    d.cancel()               # 取消在 t1 running 时到达
    release_t1.set()
    await dispatch_task
    assert d._states["t1"].status == "done"  # running 子任务不硬杀
    assert d._states["t2"].status == "cancelled"
    assert d._states["t2"].error == "cancelled by user"
    assert ran == ["t1"]  # t2 未调 _run_subagent
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_cancel.py -v`
Expected: FAIL — `AttributeError: 'ChatDispatcher' object has no attribute 'cancel'` / cancelled 任务仍会跑。

- [ ] **Step 3: 写最小实现**

`chat_dispatcher.py` 模块级（`ChatDispatcher` 类定义前）：

```python
# P2-9 (2026-08-14): 进程内活动 dispatcher 注册表 —— 供 run 级 cancel 端点
# 定位并置位取消事件。producer 在构造后注册、finally 注销（长连接结束即删）。
_ACTIVE_DISPATCHERS: Dict[str, "ChatDispatcher"] = {}
```

`__init__` 末尾：

```python
# P2-9 (2026-08-14): 取消事件 —— cancel() 幂等 set；_run_one 开头检查。
self._cancelled = asyncio.Event()
```

新增方法：

```python
def cancel(self) -> bool:
    """置位取消事件。幂等：已 set 返回 False，否则 True。"""
    if self._cancelled.is_set():
        return False
    self._cancelled.set()
    return True
```

`_run_one` 守卫放 `async with self._semaphore:` 内、`state.status = "running"` 前（acquire 之后判）：

```python
async def _run_one(state: ChatTaskState) -> None:
    async with self._semaphore:
        # P2-9 (2026-08-14): 取消后 queued 任务不再启动（转 cancelled）。守卫在
        # acquire 之后 —— 排队等槽的任务 cancel 前已越过入口，拿到槽后再判一次
        # 才真正短路；running 子任务已过守卫不硬杀（SubagentRunner 无中断通道），
        # 尽力放行，已完成结果仍入聚合。
        if self._cancelled.is_set():
            state.status = "cancelled"
            state.error = "cancelled by user"
            self._emit_task_status(state)
            return
        ...
```

`dispatch()` 的 gather 过滤：

```python
await asyncio.gather(
    *(_run_one(s) for s in states if s.status not in ("failed", "cancelled"))
)
```

`legacy_routes.py` 构造 dispatcher 后注册：

```python
from backend.orchestration.chat_dispatcher import ChatDispatcher, _ACTIVE_DISPATCHERS  # 顶部 import 补充
...
dispatcher = ChatDispatcher(...)
_ACTIVE_DISPATCHERS[run_id] = dispatcher
agent.tool_registry.register(DispatchSubagentsTool(dispatcher))
```

`finally:` 块（`:2076`，tool context reset 处）注销：

```python
finally:
    if run_id:
        _ACTIVE_DISPATCHERS.pop(run_id, None)
    # 既有 reset_tool_context 等逻辑保留
```

`backend/api/orch_routes.py` 新增端点：

```python
class CancelRunResponse(BaseModel):
    ok: bool
    run_id: str
    status: str


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
@with_db_lock
def cancel_run(run_id: str, body: Optional[CancelRunRequest] = None) -> CancelRunResponse:
    """Run 级取消：置 cancelled + 停 dispatcher 新任务（running 不硬杀）。"""
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in ("cancelled", "completed", "failed"):
        raise HTTPException(status_code=409, detail=f"run already in terminal state: {run.status}")
    repo.update_status(run_id, "cancelled")
    # 进程内注册表定位 dispatcher 并置位（同步 set event，无需 await）。
    try:
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    except Exception:  # noqa: BLE001 — 注册表命中失败不阻塞状态落库
        pass
    return CancelRunResponse(ok=True, run_id=run_id, status="cancelled")


class CancelRunRequest(BaseModel):
    reason: str = "user_cancelled"
```

（`CancelRunRequest` 定义放 `CancelRunResponse` 旁；body 为可选 —— FastAPI 对 `body: Optional[X] = None` 默认放行空 body。）

`repo.update_status` 见 A9（本 task 依赖其存在；先实现 A9 的 repo 方法或在本 task 内一并加，推荐本 task 直接加，A9 只做列迁移）。

- [ ] **Step 4: 跑测试确认通过 + 端点集成验证**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_cancel.py -v`
Expected: 3 passed
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -q`
Expected: 全绿
（端点级验证：`backend/tests/integration` 加一条 cancel 全链路 —— 见 Step 1 若已建 `test_cancel_endpoint_lifecycle`，则 Step 3 需同步 `repo.update_status` 落库断言。）

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/api/legacy_routes.py backend/api/orch_routes.py backend/data/orch_run_repo.py backend/tests/unit/test_chat_dispatcher_cancel.py
git commit -m "feat(orch): run 级取消 — 注册表 + 幂等 Event + POST /orch/runs/{id}/cancel"
```

---

## Task A9: `original_request` 列迁移 + `repo.update_status` + resume 响应字段

**Files:**
- Modify: `backend/data/database.py`（orch_runs 表后加 ALTER TABLE 迁移）
- Modify: `backend/data/orch_run_repo.py`（`OrchRun.original_request` + upsert/get/list + `update_status`）
- Modify: `backend/orchestration/chat_dispatcher.py:334-347`（`init_orch_run` 增 `original_request` 参数）
- Modify: `backend/api/legacy_routes.py`（`init_orch_run(..., original_request=data.message)`）
- Modify: `backend/api/orch_routes.py`（`OrchRunDetail.original_request` + `ResumeResponse.original_request` + `resume_run` 传值）
- Test: `backend/tests/unit/test_chat_dispatcher_persistence.py`（追加）

**Interfaces:**
- Produces: `orch_runs.original_request TEXT`（新库 CREATE 含列；旧库 PRAGMA + ALTER）；`OrchRun.original_request: Optional[str] = None`；`repo.update_status(run_id, status)`（不动 final_summary）；`ChatDispatcher.init_orch_run(session_id, plan_json, original_request="")`；`ResumeResponse.original_request: str`；`OrchRunDetail.original_request: Optional[str]`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher_persistence.py（追加）
"""Wave 3 A9 — original_request 列 + update_status。"""
import asyncio

from backend.data import database as db_mod


def test_init_orch_run_persists_original_request(tmp_path, monkeypatch):
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    dispatcher.init_orch_run(
        session_id="s-1",
        plan_json='{"tasks":[],"reasoning":""}',
        original_request="帮我写一份报告",
    )
    fetched = dispatcher._orch_run_repo.get("orch-test")
    assert fetched is not None
    assert fetched.original_request == "帮我写一份报告"


def test_update_status_changes_status_only(tmp_path, monkeypatch):
    """update_status 改 status，不清 final_summary。"""
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    repo = OrchRunRepository()
    repo.upsert(OrchRun(run_id="r1", session_id="s1", status="running", created_at=1, plan_json="{}"))
    repo.finalize("r1", "completed", "summary")
    repo.update_status("r1", "cancelled")
    fetched = repo.get("r1")
    assert fetched.status == "cancelled"
    assert fetched.final_summary == "summary"


def test_old_db_migrates_original_request_column(tmp_path, monkeypatch):
    """既有库缺列 → ALTER TABLE 幂等补列。"""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE orch_runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'running', created_at INTEGER NOT NULL, "
        "plan_json TEXT NOT NULL, final_summary TEXT, dispatched_at INTEGER)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.data.orch_run_repo import OrchRunRepository

    repo = OrchRunRepository()
    repo.upsert(OrchRun(run_id="r1", session_id="s1", status="running", created_at=1, plan_json="{}"))
    fetched = repo.get("r1")
    assert fetched is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_persistence.py -k "original or update_status or migrate" -v`
Expected: FAIL — `original_request` 键不存在 / `update_status` 不存在 / SQLite 报错 unknown column。

- [ ] **Step 3: 写最小实现**

`database.py` 在 `CREATE TABLE orch_runs` + index 之后、`CREATE TABLE orch_tasks` 之前插入：

```python
# Wave 3 A9 (2026-08-14): original_request 列 —— resume plan_override 恢复流
# 用（前端 resumeRun 要拿原始请求逐字重发）。既有库 ALTER 补列，幂等。
cursor.execute("PRAGMA table_info(orch_runs)")
_orch_cols = {row[1] for row in cursor.fetchall()}
if "original_request" not in _orch_cols:
    cursor.execute("ALTER TABLE orch_runs ADD COLUMN original_request TEXT")
```

并把 `CREATE TABLE orch_runs` 定义加上 `original_request TEXT`（新库直接建）。

`orch_run_repo.py`：

```python
@dataclass
class OrchRun:
    ...
    dispatched_at: Optional[int] = None
    # Wave 3 A9 (2026-08-14): resume 恢复流的原始请求（前端逐字重发）。
    original_request: Optional[str] = None
```

`upsert` SQL 加列：

```python
INSERT INTO orch_runs (run_id, session_id, status, created_at, plan_json, final_summary, dispatched_at, original_request)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(run_id) DO UPDATE SET
    session_id=excluded.session_id,
    status=excluded.status,
    plan_json=excluded.plan_json,
    final_summary=excluded.final_summary,
    dispatched_at=excluded.dispatched_at,
    original_request=excluded.original_request
```

元组末尾加 `run.original_request`。`get`/`list` 构造加 `original_request=row["original_request"]`。

新增（若 A8 已按 3.4 一并添加，此处跳过即可，方法签名一致）：

```python
def update_status(self, run_id: str, status: str) -> None:
    """仅改 status，不动 final_summary（cancel 场景不覆盖既有 summary）。"""
    conn = self.db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orch_runs SET status = ? WHERE run_id = ?", (status, run_id))
    conn.commit()
```

`chat_dispatcher.py` `init_orch_run`：

```python
def init_orch_run(self, session_id: str, plan_json: str, original_request: str = "") -> None:
    ...
    self._orch_run_repo.upsert(OrchRun(
        run_id=self.run_id,
        session_id=session_id or "",
        status="running",
        created_at=int(time.time() * 1000),
        plan_json=plan_json,
        original_request=original_request or None,
    ))
```

`legacy_routes.py` init 调用处加 `original_request=data.message`（两处：decompose 路径 + A10 的 override 路径）。

`orch_routes.py`：

```python
class OrchRunDetail(BaseModel):
    ...
    tasks: List[Dict[str, Any]]
    # Wave 3 A9: resume 恢复流原始请求
    original_request: Optional[str] = None


class ResumeResponse(BaseModel):
    ok: bool
    new_run_id: str
    session_id: str
    plan: List[Dict[str, Any]]
    original_request: Optional[str] = None
```

`get_run` 返回值加 `original_request=run.original_request`；`resume_run` 加 `original_request=run.original_request`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_persistence.py -k "original or update_status or migrate" -v`
Expected: 3 passed
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q`
Expected: 全绿（SQL 改动会影响所有 repo 测试，重点看 orch_run_repo / persistence）

- [ ] **Step 5: Commit**

```bash
git add backend/data/database.py backend/data/orch_run_repo.py backend/orchestration/chat_dispatcher.py backend/api/legacy_routes.py backend/api/orch_routes.py backend/tests/unit/test_chat_dispatcher_persistence.py
git commit -m "feat(orch): original_request 列迁移 + repo.update_status + resume 响应字段"
```

---

## Task A10: `ChatRequest.plan_override`/`run_id` + legacy 恢复流 wiring

**Files:**
- Modify: `backend/api/legacy_routes.py:161-204`（`ChatRequest` 增字段）+ multi 分支（override 路径）
- Modify: `backend/api/orch_routes.py`（resume 已含 original_request — A9）
- Test: `backend/tests/unit/test_chat_dispatcher_resume.py`（追加）+ integration

**Interfaces:**
- Produces:
  - `ChatRequest.plan_override: Optional[List[Dict[str, Any]]] = None`（非空 → 跳过 LLM 拆解，直接建 dispatcher + 注入计划块 + 推 task_plan；`total_tasks=len(plan_override)`；override items 自带 task_id，task_plan 事件**不重新 enumerate**）。
  - `ChatRequest.run_id: Optional[str] = None`（复用 resume 返回的 `new_run_id`；`ChatDispatcher(run_id=...)` 用该 id，`init_orch_run` 覆盖占位行，dispatcher 首 dispatch 从该 run 的 plan_json 读权威计划 = override plan）。
  - `orchestration_mode` 视为 `force_multi`（override 非空时跳过 classify）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher_resume.py（追加）
"""Wave 3 A10 — plan_override 跳过拆解，task_id 沿用不重枚举。"""
import asyncio

from backend.orchestration.chat_dispatcher import ChatDispatcher


@pytest.mark.asyncio()
async def test_override_run_uses_provided_run_id_and_plan():
    """override 建 dispatcher 用 run_id，首 dispatch 读到 override plan。"""
    # 走 legacy 的 override 路径不在这里（那是集成）；这里验证 ChatDispatcher
    # 在 run_id 已存在、plan_json=override 时，三态路由匹配 override task_id。
    from backend.data import database as db_mod

    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-reused")
    d.init_orch_run(
        session_id="s-1",
        plan_json='{"tasks":[{"task_id":"t1","agent_id":"writer","goal":"恢复目标"}],"reasoning":""}',
        original_request="原始请求",
    )
    d._ensure_plan_loaded()  # 同步方法（A4 定义）—— 手动触发索引构建，非 await
    # 直接测计划索引已建
    assert "t1" in d._plan_by_id
    assert d._plan_by_id["t1"]["goal"] == "恢复目标"
```

（真正的 override 流在 legacy_routes — Step 3 后加集成测试：`POST /chat/stream` 带 `plan_override=[{task_id:"t1",agent_id:"researcher",goal:"G"}]` + `run_id` → 断言首个事件是 `task_plan` 且 `plan[0].task_id=="t1"`、`total_tasks==1`。集成骨架若复杂，按 Step 4 的手工验证兜底。）

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_resume.py -k override -v`
Expected: FAIL — `ChatRequest` 无 plan_override（422）/ `_plan_by_id` 不存在（A4 前）。

- [ ] **Step 3: 写最小实现**

`legacy_routes.py` `ChatRequest` 增：

```python
# Wave 3 A10 (2026-08-14): resume 恢复流 —— plan_override 非空时跳过 LLM
# 拆解，直接用存储计划建 dispatcher；run_id 复用 resume 返回的 new_run_id。
plan_override: Optional[List[Dict[str, Any]]] = None
run_id: Optional[str] = None
```

classify 处（`mode = await _classify_orchestration_mode(...)` 前）短路：

```python
# A10: plan_override 非空 → 视为 force_multi，跳过语义判定。
if data.plan_override:
    mode = "multi"
else:
    try:
        mode = await _classify_orchestration_mode(
            data.message,
            data.orchestration_mode or "auto",
            llm_client=build_llm_client_from_settings(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("编排语义判定失败，降级 single: %s", exc)
        mode = "single"
```

multi 分支头部（`plan = await Planner(...)` 之前）加 override 分流：

```python
if data.plan_override:
    # A10: override 路径 —— items 自带 task_id，直接透传，不重枚举。
    plan_tasks = data.plan_override
    run_id = data.run_id or f"orch-{uuid.uuid4()}"
else:
    # 既有 decompose / template 路径（A7 已改 template 分流）
    ...
    plan_tasks = list(plan.tasks if plan else [])
    run_id = f"orch-{uuid.uuid4()}"
if len(plan_tasks) <= 1 and not data.plan_override:
    mode = "single"
if mode == "multi":
    ...
```

但 plan_block / init / task_plan 仍假设 `plan_tasks` 是 Task 对象（用 `t.parameters.get("agent_hint")`、`t.name`、`t.description`、`t.blocked_by`）。**override 路径是 dict**，为避免把既有路径的 Task 假设全改掉，在 override 分支把 dict 归一成与 task_plan 同构的 `plan_items`，并让 plan_block / init / task_plan 消费统一 `plan_items`：

```python
# 归一为 {task_id, agent_id, goal, depends_on} 列表 —— 下游 plan_block / init / 事件同构。
plan_items: List[Dict[str, Any]]
if data.plan_override:
    plan_items = [
        {
            "task_id": str(it["task_id"]),
            "agent_id": str(it.get("agent_id", "primary")),
            "goal": str(it.get("goal", "")),
            "depends_on": list(it.get("depends_on") or []),
        }
        for it in data.plan_override
    ]
else:
    plan_items = [
        {
            "task_id": f"t{i}",
            "agent_id": t.parameters.get("agent_hint", "primary"),
            "goal": t.description or t.name,
            "depends_on": list(t.blocked_by),
        }
        for i, t in enumerate(plan_tasks, 1)
    ]
```

然后把既有 plan_block / init_orch_run / task_plan / task_progress 四处对 `plan_tasks` 的遍历改成消费 `plan_items`：

```python
plan_block = "\n".join(
    f"- {i}. [{it['agent_id']}] {it['goal']}"
    for i, it in enumerate(plan_items, 1)
)
...
# reasoning 捕获：override 路径 plan 未定义 → "plan_override"；decompose 路径
# plan.reasoning（可为空串）。避免 override 路径直接引用 plan 抛 NameError。
reasoning = "plan_override" if data.plan_override else (plan.reasoning if plan else "")
dispatcher.init_orch_run(
    session_id=data.session_id,
    plan_json=json.dumps(
        {"tasks": plan_items, "reasoning": reasoning},
        ensure_ascii=False,
    ),
    original_request=data.message,
)
await entry.queue.put({"state": "task_plan", "run_id": run_id, "plan": plan_items})
await entry.queue.put({"state": "task_progress", "run_id": run_id, "total": len(plan_items), ...})
```

> 注意：`plan` 变量只在 decompose 路径赋值；override 路径未定义 → 用捕获的 `reasoning` 变量（"plan_override"），不要在 override 路径直接引用 `plan.reasoning`（会 NameError）。`plan_items` 分支后的所有消费都用统一变量 `plan_items`/`reasoning`（如上）。

`dispatcher.total_tasks` 用 `len(plan_items)`（构造处 `total_tasks=len(plan_items)`）。

- [ ] **Step 4: 跑测试确认通过 + 手工验证**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_resume.py -k override -v`
Expected: passed
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -q`
Expected: 全绿（既有 decompose 路径的 task_plan 事件文本从 `[{agent_hint}] name: description` 变成 `[{agent_id}] goal` —— 若集成测试断言旧文本需同步更新；语义等价）
Run（手工冒烟）：`curl -X POST http://127.0.0.1:8765/api/v1/chat/stream` 带 `plan_override=[{"task_id":"t1","agent_id":"researcher","goal":"G"}]` + `run_id="orch-xxx"`，观察 NDJSON 首事件为 task_plan 且 task_id=t1。

- [ ] **Step 5: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/unit/test_chat_dispatcher_resume.py backend/tests/integration/test_chat_orchestration_stream.py
git commit -m "feat(orch): plan_override/run_id 恢复流 — 跳过拆解沿用 override task_id"
```

---

## Task A11: 前端 `OrchSettings` 类型 + canonicalizer 白名单 + 契约测试

**Files:**
- Modify: `src/entities/setting/types.ts`（`SETTINGS_VERSION '3.0.0'→'4.0.0'`、`OrchSettings` interface、`AppSettings.orch`、`DEFAULT_SETTINGS.orch`）
- Modify: `src/entities/setting/storage.ts`（`mergeWithDefaults` 加 `orch` 嵌套 merge —— 防部分更新丢键）
- Modify: `backend/data/settings_canonicalizer.py`（`LEGAL_TOP_KEYS` += `"orch"`、新增 `LEGAL_ORCH_KEYS`、`validate_settings_shape` 校验分支）
- Modify: `backend/tests/contract/test_settings_schema_parity.py`（`EXPECTED_TOP_KEYS` += `"orch"`、新增 `test_legal_orch_keys_is_stable`）
- Test: `backend/tests/contract/test_settings_schema_parity.py` + vitest storage 测试

**Interfaces:**
- Produces: 前端 `OrchSettings {maxConcurrentSubagents, maxAggregateChars, maxSubagentResultChars, maxRetries, maxLaneIterations}`（**不含 scratchRoot** —— scratch_root 仅后端配置，spec 偏差见 Global Constraints 项 3.3）；`AppSettings.orch: OrchSettings`；`SETTINGS_VERSION='4.0.0'`。

- [ ] **Step 1: 写失败测试（契约先行）**

`backend/tests/contract/test_settings_schema_parity.py` 更新（先改期望值让它红）：

```python
EXPECTED_TOP_KEYS = frozenset(
    {
        "streaming", "autoMemory", "confirmDelete", "endpoints", "modelSelections",
        "maxContext", "temperature", "wiki", "version", "orch",
    }
)


def test_legal_orch_keys_is_stable() -> None:
    """LEGAL_ORCH_KEYS 是前端 OrchSettings 6 键（含 scratchRoot，后端存）。"""
    assert frozenset(
        {
            "maxConcurrentSubagents",
            "maxAggregateChars",
            "maxSubagentResultChars",
            "maxRetries",
            "maxLaneIterations",
            "scratchRoot",
        }
    ) == LEGAL_ORCH_KEYS
```

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/contract/test_settings_schema_parity.py -v`
Expected: FAIL — `LEGAL_TOP_KEYS != EXPECTED_TOP_KEYS`（后端还没加 orch）。

- [ ] **Step 2: 写前端类型 + 后端 canonicalizer**

`src/entities/setting/types.ts`：

```ts
export const SETTINGS_VERSION = '4.0.0';

// Wave 3 P2-9 (2026-08-14): 编排执行参数（前端 UI 渲染 5 个数值；scratchRoot
// 仅后端配置，不在此 interface —— 见 storage 层注释）。
export interface OrchSettings {
  maxConcurrentSubagents: number; // 4
  maxAggregateChars: number;      // 120 * 1024
  maxSubagentResultChars: number; // 50 * 1024
  maxRetries: number;             // 2
  maxLaneIterations: number;      // 8
}

export interface AppSettings {
  ...
  // Wave 3 P2-9
  orch: OrchSettings;
  // Internal
  version: string;
}

export const DEFAULT_ORCH_SETTINGS: OrchSettings = {
  maxConcurrentSubagents: 4,
  maxAggregateChars: 120 * 1024,
  maxSubagentResultChars: 50 * 1024,
  maxRetries: 2,
  maxLaneIterations: 8,
};

export const DEFAULT_SETTINGS: AppSettings = {
  ...
  orch: DEFAULT_ORCH_SETTINGS,
  version: SETTINGS_VERSION,
};
```

`src/entities/setting/storage.ts` `mergeWithDefaults`：

```ts
function mergeWithDefaults(partial: Partial<AppSettings>): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    endpoints: partial.endpoints ?? DEFAULT_SETTINGS.endpoints,
    modelSelections: partial.modelSelections ?? DEFAULT_SETTINGS.modelSelections,
    // 嵌套 merge：部分 orch 更新不丢其余键（同 endpoints 的既有 bug 防护）。
    orch: { ...DEFAULT_ORCH_SETTINGS, ...(partial.orch ?? {}) },
    version: partial.version ?? SETTINGS_VERSION,
  };
}
```

`backend/data/settings_canonicalizer.py`：

```python
LEGAL_TOP_KEYS: FrozenSet[str] = frozenset(
    {
        "streaming", "autoMemory", "confirmDelete", "endpoints", "modelSelections",
        "maxContext", "temperature", "wiki", "version",
        # Wave 3 P2-9 (2026-08-14): 编排执行参数段。
        "orch",
    }
)
LEGAL_ORCH_KEYS: FrozenSet[str] = frozenset(
    {
        "maxConcurrentSubagents",
        "maxAggregateChars",
        "maxSubagentResultChars",
        "maxRetries",
        "maxLaneIterations",
        "scratchRoot",
    }
)
```

`validate_settings_shape` 加：

```python
orch = settings.get("orch") or {}
if not isinstance(orch, dict):
    raise ValueError("orch is not a dict")
bad_orch = [k for k in orch if k not in LEGAL_ORCH_KEYS]
if bad_orch:
    raise ValueError(
        f"unknown orch field {bad_orch[0]!r}; allowed: {sorted(LEGAL_ORCH_KEYS)}"
    )
```

- [ ] **Step 3: 跑契约测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/contract/test_settings_schema_parity.py -v`
Expected: 全绿（含新 `test_legal_orch_keys_is_stable`）

- [ ] **Step 4: 前端 vitest（storage 嵌套 merge）**

`src/entities/setting/__tests__/storage.test.ts`（或既有 storage 测试）追加：

```ts
test('mergeWithDefaults merges orch nested, not replaces', () => {
  const { mergeWithDefaults } = require('../storage');
  const merged = mergeWithDefaults({ orch: { maxRetries: 5 } });
  expect(merged.orch.maxRetries).toBe(5);
  expect(merged.orch.maxConcurrentSubagents).toBe(4); // 其余键保持默认
});
```

（若 `mergeWithDefaults` 未导出，导出一个测试钩子或改用 settings load 的集成断言。）

Run: `cd /home/fz/project/sage && npx vitest run src/entities/setting`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/entities/setting/types.ts src/entities/setting/storage.ts backend/data/settings_canonicalizer.py backend/tests/contract/test_settings_schema_parity.py src/entities/setting/__tests__
git commit -m "feat(settings): P2-9 orch 段类型 + canonicalizer 白名单 + 契约测试"
```

---

## Task A12: GeneralTab 编排设置 section

**Files:**
- Modify: `src/pages/settings/GeneralTab.tsx`
- Modify: `src/locales/zh-CN.json`（`settings.*` 段 i18n keys）
- Test: `src/pages/settings/__tests__/GeneralTab.test.tsx`（或既有 settings 测试）

**Interfaces:**
- Consumes: `useSettings().updateSettings`、`settings.orch`（A11）。
- Produces: GeneralTab 增「编排（Orchestration）」section，渲染 5 个数字输入，`updateSettings({ orch: { ...settings.orch, [k]: v } })`。

- [ ] **Step 1: 写失败测试**

```ts
// src/pages/settings/__tests__/GeneralTab.orch.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GeneralTab } from '../GeneralTab';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { ...DEFAULT_SETTINGS, orch: { ...DEFAULT_SETTINGS.orch, maxRetries: 2 } },
    updateSettings: vi.fn(),
    resetSettings: vi.fn(),
  }),
}));

vi.mock('../../../shared/lib/i18n', () => ({ useI18n: () => ({ t: (k: string) => k }) }));

describe('GeneralTab 编排 section', () => {
  it('渲染 5 个编排数值输入', () => {
    render(<GeneralTab resetSettings={() => {}} />);
    expect(screen.getByTestId('orch-max-concurrent')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-aggregate')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-subagent-result')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-retries')).toBeInTheDocument();
    expect(screen.getByTestId('orch-max-lane-iterations')).toBeInTheDocument();
  });

  it('修改数值调 updateSettings 且保留其余 orch 键', async () => {
    const updateSettings = vi.fn();
    vi.mocked(useSettings).mockReturnValue({ ... });
    render(<GeneralTab resetSettings={() => {}} />);
    fireEvent.change(screen.getByTestId('orch-max-retries'), { target: { value: '5' } });
    expect(updateSettings).toHaveBeenCalledWith({
      orch: expect.objectContaining({ maxRetries: 5, maxConcurrentSubagents: 4 }),
    });
  });
});
```

（vitest mock 细节按项目既有测试风格调整；核心断言是「部分更新保留其余 orch 键」。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/pages/settings/__tests__/GeneralTab.orch.test.tsx`
Expected: FAIL — GeneralTab 无 orch section / 无对应 data-testid。

- [ ] **Step 3: 写最小实现**

`GeneralTab.tsx`（import `useSettings` 已具备；`SettingRow` 已导入）在「数据」section 前插：

```tsx
<section data-testid="orch-settings-section">
  <h3 className="text-sm font-semibold text-text mb-3">{t('settings.section.orch')}</h3>
  <NumberField
    label="最大并发子任务数"
    dataTestId="orch-max-concurrent"
    value={settings.orch.maxConcurrentSubagents}
    onChange={(v) => updateSettings({ orch: { ...settings.orch, maxConcurrentSubagents: v } })}
  />
  <NumberField
    label="聚合结果上限（字符）"
    dataTestId="orch-max-aggregate"
    value={settings.orch.maxAggregateChars}
    onChange={(v) => updateSettings({ orch: { ...settings.orch, maxAggregateChars: v } })}
  />
  <NumberField
    label="单结果截断上限（字符）"
    dataTestId="orch-max-subagent-result"
    value={settings.orch.maxSubagentResultChars}
    onChange={(v) => updateSettings({ orch: { ...settings.orch, maxSubagentResultChars: v } })}
  />
  <NumberField
    label="子任务重试次数"
    dataTestId="orch-max-retries"
    value={settings.orch.maxRetries}
    onChange={(v) => updateSettings({ orch: { ...settings.orch, maxRetries: v } })}
  />
  <NumberField
    label="Lane 迭代上限"
    dataTestId="orch-max-lane-iterations"
    value={settings.orch.maxLaneIterations}
    onChange={(v) => updateSettings({ orch: { ...settings.orch, maxLaneIterations: v } })}
  />
</section>
```

`NumberField` 组件（GeneralTab 内局部定义，复用既有 select 的 border className 模式）：

```tsx
function NumberField({
  label,
  dataTestId,
  value,
  onChange,
}: {
  label: string;
  dataTestId: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <SettingRow label={label}>
      <input
        type="number"
        data-testid={dataTestId}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n >= 0) onChange(Math.floor(n));
        }}
        className="w-32 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </SettingRow>
  );
}
```

i18n：`src/locales/zh-CN.json` 的 `settings.section` 段加 `"orch": "编排（Orchestration）"`；en 同步加 `"Orchestration"`。

- [ ] **Step 4: 跑测试确认通过 + 前端回归**

Run: `cd /home/fz/project/sage && npx vitest run src/pages/settings/__tests__/GeneralTab.orch.test.tsx`
Expected: 2 passed
Run: `cd /home/fz/project/sage && npx vitest run src/pages/settings src/entities/setting`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/pages/settings/GeneralTab.tsx src/locales/zh-CN.json src/locales/en.json src/pages/settings/__tests__
git commit -m "feat(settings): P2-9 GeneralTab 编排 section — 5 个数字输入 + i18n"
```

---

### PR A 收尾验证

```bash
# 全量后端
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q
# 全量前端 + 类型
cd /home/fz/project/sage && npx vitest run && npm run tsc && npm run typecheck:electron
```

期望：pytest ≥3706 全绿（含新 ~20）、vitest ≥1239、tsc 0 错、typecheck:electron 0 错。**electron 改动（orchRunClient / settings）必须跑 typecheck:electron**（wave2 教训）。

---

# PR B — 休眠层（P2-10）

**分支：`feat/orch-wave3-pr-b`**（依赖 PR A 的 `load_orch_settings`）。

## Task B1: 提取 `review.py` 公共验证环

**Files:**
- Create: `backend/orchestration/review.py`
- Modify: `backend/orchestration/chat_dispatcher.py`（`_run_review` 委托 `run_review`；`_parse_assertions`/`_review_block` 移到 review.py 并委托）
- Test: `backend/tests/unit/test_chat_dispatcher_review_event.py`（回归不改变行为）

**Interfaces:**
- Produces: `backend/orchestration/review.py`：
  - `parse_assertions(raw: str) -> List[Assertion]`（从 ChatDispatcher._parse_assertions 原样搬移）
  - `build_review_block(verdict, count, note="") -> str`（搬移 _review_block）
  - `async run_review(*, run_id, aggregated, task_registry, lane_registry, event_recorder, llm_config, max_chars=50*1024, emit_review=None) -> Dict[str, Any]`，返回 `{"verdict", "block", "assertion_count"}`，内部建 lane/task、`run_lane_with_retry`、`submit_with_report`、0-parse→fail、`emit_review(task_id, verdict, count, summary)` 回调（ChatDispatcher 传 `self._emit_task_review`）。
- ChatDispatcher._run_review 改为薄委托（保持 P0-2 语义与异常降级不变）。

- [x] **Step 1: 写失败测试（先建 review.py 的空壳，再测行为）**

```python
# backend/tests/unit/test_review_module.py
"""Wave 3 B1 — run_review 模块化：验证环逻辑与 ChatDispatcher 解耦。"""
import asyncio
from unittest.mock import MagicMock

import pytest

from backend.orchestration.review import parse_assertions, run_review


def test_parse_assertions_module_function():
    """parse_assertions 从 dispatcher 搬出，行为不变。"""
    raw = "[FACT] 事实一 (confidence: 0.9)\n[GARBAGE] 无效行\n[NEGATIVE_EVIDENCE] 反例 (confidence: 0.8)"
    assertions = parse_assertions(raw)
    assert len(assertions) == 2
    assert assertions[0].type.value == "fact"
    assert assertions[1].confidence == 0.8


@pytest.mark.asyncio()
async def test_run_review_success_path():
    """reviewer 成功 → verdict/block/assertion_count；emit 回调被调。"""
    # 用 MagicMock 桩 LaneExecutor 依赖（execute_lane 返回 succeeded + output）
    from backend.orchestration.models import Assertion

    emitted = []

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": "[FACT] 复核通过 (confidence: 0.9)"}}

    import backend.orchestration.review as review_mod

    orig = review_mod.run_lane_with_retry
    review_mod.run_lane_with_retry = fake_run_lane
    try:
        outcome = await run_review(
            run_id="r1",
            aggregated="聚合内容",
            task_registry=MagicMock(),
            lane_registry=MagicMock(),
            event_recorder=MagicMock(),
            llm_config={"model": "x"},
            emit_review=lambda *a: emitted.append(a),
        )
    finally:
        review_mod.run_lane_with_retry = orig
    assert outcome["verdict"] == "pass"
    assert outcome["assertion_count"] == 1
    assert "复核结果" in outcome["block"]
    assert emitted  # emit_review 被调用
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_module.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: 写最小实现**

`backend/orchestration/review.py`（搬移 `_parse_assertions` / `_review_block` 逻辑 + 组装 `run_review`；逻辑与现 `ChatDispatcher._run_review` 逐行等价，仅依赖改参数传入）：

```python
"""``review`` — P0-2 验证环（Wave 3 B1 提取）。

ChatDispatcher._run_review 与 API lane（B2）共用：对聚合结果跑 reviewer
子 agent，产出 ReviewReport + verdict/assertion_count/block。不改变
ChatDispatcher 原有行为（reviewer 失败 → 由调用方捕获降级）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane, Task
from backend.orchestration.report_schema import Assertion, AssertionType
from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry

logger = logging.getLogger(__name__)


def parse_assertions(raw: str) -> List[Assertion]:
    """解析 reviewer 输出的 assertion 行 → ``list[Assertion]``（见原 dispatcher 文档）。"""
    pattern = re.compile(
        r"^\[(FACT|HYPOTHESIS|NEGATIVE_EVIDENCE)\]\s*(.+?)"
        r"(?:\s*\(confidence:\s*([0-9.]+)\))?\s*$"
    )
    assertions: List[Assertion] = []
    for line in raw.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        try:
            atype = AssertionType(m.group(1).lower())
        except ValueError:
            continue
        try:
            confidence = float(m.group(3)) if m.group(3) else 0.0
        except ValueError:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        try:
            assertions.append(Assertion(type=atype, statement=m.group(2), confidence=confidence))
        except ValueError:
            continue
    return assertions


def build_review_block(verdict: str, count: int, note: str = "") -> str:
    note_line = f"- 备注：{note}\n" if note else ""
    instruction = (
        "存在关键 NEGATIVE_EVIDENCE 或无可解析 assertion，请修复后再给出最终汇总。"
        if verdict == "fail"
        else "全部断言通过，可给出最终汇总。"
    )
    return (
        "\n\n## 复核结果（reviewer）\n\n"
        f"- verdict: {verdict}（{count} 条 assertion）\n{note_line}"
        f"- {instruction}"
    )


async def run_review(
    *,
    run_id: str,
    aggregated: str,
    task_registry: Any,
    lane_registry: Any,
    event_recorder: Any,
    llm_config: Any,
    max_chars: int = 50 * 1024,
    emit_review: Optional[Callable[[str, str, int, str], None]] = None,
) -> Dict[str, Any]:
    """reviewer 复核聚合 → ReviewReport + markdown 块（ChatDispatcher/API lane 共用）。"""
    review_goal = (
        "复核以下多 agent 子任务聚合结果，逐条给出 assertion。\n"
        + aggregated[:max_chars]
    )
    lane_id = f"lane-review-{run_id}"
    task_id = f"task-review-{run_id}"

    task = Task(
        task_id=task_id,
        name=f"Review {run_id}",
        description=review_goal,
        parameters={"goal": review_goal},
    )
    task_registry.create_task(task)
    task_registry.mark_running(task_id)
    lane = Lane(lane_id=lane_id, task_id=task_id, agent_id="reviewer", metadata={})
    lane_registry.create_lane(lane)

    executor = LaneExecutor(
        lane_registry=lane_registry,
        task_registry=task_registry,
        event_recorder=event_recorder,
        agent_runner=SubagentRunner(llm_config),
    )
    result = await run_lane_with_retry(executor, lane, "reviewer")
    if result.get("status") != "succeeded":
        raise RuntimeError(result.get("error", "reviewer 未产出内容"))
    raw = result["result"]["output"]

    assertions = parse_assertions(raw)
    executor.submit_with_report(lane_id, task_id, assertions, reviewer_id="reviewer")
    if len(assertions) == 0:
        verdict = "fail"
        review_note = "reviewer 未产出任何可解析 assertion"
    else:
        verdict = (
            "fail"
            if any(
                a.type == AssertionType.NEGATIVE_EVIDENCE and a.confidence >= 0.7
                for a in assertions
            )
            else "pass"
        )
        review_note = ""
    block = build_review_block(verdict, len(assertions), note=review_note)
    if emit_review is not None:
        emit_review(
            task_id,
            verdict,
            len(assertions),
            review_note or f"{verdict}（{len(assertions)} 条 assertion）",
        )
    logger.info("编排复核完成: verdict=%s, assertions=%d", verdict, len(assertions))
    return {"verdict": verdict, "block": block, "assertion_count": len(assertions)}
```

`chat_dispatcher.py`：
- `_run_review` 方法体替换为：

```python
async def _run_review(self, aggregated: str) -> dict:
    """P0-2 验证环 —— 委托 review.run_review（Wave 3 B1 提取，行为不变）。"""
    from backend.orchestration.review import run_review

    return await run_review(
        run_id=self.run_id,
        aggregated=aggregated,
        task_registry=self.task_registry,
        lane_registry=self.lane_registry,
        event_recorder=self.event_recorder,
        llm_config=self.llm_config,
        max_chars=MAX_SUBAGENT_RESULT_CHARS,
        emit_review=self._emit_task_review,
    )
```

- `_parse_assertions` / `_review_block` 改为薄委托（或直接删，若无其它调用点 —— 查证后删，测试若引用则同步改）：

```python
def _parse_assertions(self, raw: str) -> List[Assertion]:
    from backend.orchestration.review import parse_assertions

    return parse_assertions(raw)
```

- [x] **Step 4: 跑测试确认通过 + 回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_module.py backend/tests/unit/test_chat_dispatcher_review_event.py backend/tests/integration/test_chat_dispatcher_review_event_integration.py -v`
Expected: 全绿（重构不改变验证环行为）

- [x] **Step 5: Commit**

```bash
git add backend/orchestration/review.py backend/orchestration/chat_dispatcher.py backend/tests/unit/test_review_module.py
git commit -m "refactor(orch): 提取 review.py 公共验证环 — ChatDispatcher/API lane 共用"
```

---

## Task B2: `POST /orchestration/lanes?wait=true` 真实执行

**Files:**
- Modify: `backend/api/orchestration_router.py:220-299`（`create_lanes` 增 `wait` query 参数 + 执行分流）
- Modify: `backend/api/orchestration_router.py`（新增 `_execute_plan_lanes`）
- Modify: `backend/api/orchestration_router.py`（`CreateLanesOut` 增可选 `review` 字段）
- Test: `backend/tests/unit/test_orchestration_router_exec.py`（新建）

**Interfaces:**
- Consumes: `run_review`（B1）、`load_orch_settings()`（A1）、`LaneExecutor`/`SubagentRunner`/`run_lane_with_retry`（既有）。
- Produces:
  - `POST /orchestration/lanes?wait=false`（默认）：建 lanes 后 `asyncio.create_task(_execute_plan_lanes(...))` 后台执行，立即返回 `CreateLanesOut`（lanes queued/running）。
  - `?wait=true`：`await _execute_plan_lanes(...)`，返回的 lanes 带终态（done/failed）+ output/error；`CreateLanesOut.review: Optional[Dict]`。
  - `_execute_plan_lanes(*, plan, lanes, lane_registry, task_registry, event_recorder, llm_config)`（team_id 取 `plan.team_id`）：并行（`asyncio.Semaphore(max_concurrent_subagents)`）、每 lane 隔离 scratch、`mark_running`、`run_lane_with_retry`（max_lane_iterations 防御）、终态落库 + 事件；全部终态后 `run_review` 落 ReviewReport。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_orchestration_router_exec.py
"""Wave 3 B2 — API lane 真实执行：wait=true 同步终态 + review；wait=false 后台。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio()
async def test_execute_plan_lanes_parallel_terminal_states(tmp_path, monkeypatch):
    """_execute_plan_lanes：全部 lane 终态落库 + 聚合后跑 review。"""
    # _execute_plan_lanes 内部经 get_database().db_path 派生 scratch 根 + 读
    # orch_settings —— SAGE_DB_PATH 指到 tmp 隔离，避免写真实 data 目录。
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "b2.db"))
    from backend.data import database as db_mod
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.api.orchestration_router import _execute_plan_lanes
    from backend.orchestration.orch_settings import OrchSettings

    lane_registry = MagicMock()
    task_registry = MagicMock()
    event_recorder = MagicMock()
    lane_registry.list_all_lanes.return_value = []

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": f"out-{lane.lane_id}"}}

    # patch 目标 = _execute_plan_lanes 内部 lazy-import 的真实模块
    #（backend.api.orchestration_router.run_review 是无效目标）。
    with patch("backend.orchestration.subagent_runner.run_lane_with_retry", fake_run_lane), \
         patch("backend.orchestration.orch_settings.load_orch_settings", return_value=OrchSettings()), \
         patch("backend.orchestration.review.run_review", AsyncMock(return_value={"verdict": "pass", "block": "", "assertion_count": 1})):
        lanes = [
            MagicMock(lane_id="l1", task_id="task-1", agent_id="researcher", metadata={}, status=MagicMock()),
            MagicMock(lane_id="l2", task_id="task-2", agent_id="writer", metadata={}, status=MagicMock()),
        ]
        review = await _execute_plan_lanes(
            plan=MagicMock(team_id="team-1"),
            lanes=lanes,
            lane_registry=lane_registry,
            task_registry=task_registry,
            event_recorder=event_recorder,
            llm_config={"model": "x"},
        )
    # 每个 lane 都 mark_running + mark_completed
    assert task_registry.mark_running.call_count == 2
    assert task_registry.mark_completed.call_count == 2
    assert lane_registry.mark_completed.call_count == 2
    # 聚合后跑了 review（非 None = run_review 被调用过）
    assert review == {"verdict": "pass", "block": "", "assertion_count": 1}


@pytest.mark.asyncio()
async def test_create_lanes_router_exposes_wait_query():
    """路由层：/lanes POST 存在，且 handler 接受 wait query。

    不用 str(r.dependant.query_params)（FastAPI 内部结构随版本漂移）——
    用 inspect.signature 看端点签名最稳。
    """
    from inspect import signature

    from backend.api.orchestration_router import build_router

    router = build_router()
    lanes_post = [
        r for r in router.routes
        if getattr(r, "path", None) == "/lanes"
        and "POST" in (getattr(r, "methods", None) or set())
    ]
    assert len(lanes_post) == 1
    assert "wait" in signature(lanes_post[0].endpoint).parameters
```

（`_execute_plan_lanes` 为模块级函数即可被 import 测试；`wait=true` 的 HTTP 层用 `TestClient` 集成测试，见 Step 4。）

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_router_exec.py -v`
Expected: FAIL — `ImportError: cannot import name '_execute_plan_lanes'`

- [x] **Step 3: 写最小实现**

`orchestration_router.py`：

- `CreateLanesOut` 增：

```python
class CreateLanesOut(BaseModel):
    ok: bool
    team_id: str
    lanes: List[LaneOut]
    tasks: List[TaskOut]
    # Wave 3 B2 (2026-08-14): wait=true 时携带验证环结果（可选）。
    review: Optional[Dict[str, Any]] = None
```

- `create_lanes` 签名增 `wait: bool = False`（FastAPI query），建 lanes 后分流：

```python
    lanes_out: List[LaneOut] = []
    for task in plan.tasks:
        lane = await _create_lane_for_task(...)
        event_recorder.record(LaneEvent.STARTED, ...)
        refreshed = lane_registry.get_lane(lane.lane_id) or lane
        lanes_out.append(_to_lane_out(refreshed))

    # Wave 3 B2 (2026-08-14): P2-10 API lane 可执行 —— 默认后台异步，wait=true
    # 同步等终态（脚本/CI 用）。复用 ChatDispatcher 同款 LaneExecutor 语义。
    review: Optional[Dict[str, Any]] = None
    if wait:
        review = await _execute_plan_lanes(
            plan=plan,
            lanes=[lane_registry.get_lane(l.lane_id) for l in plan.tasks],
            lane_registry=lane_registry,
            task_registry=task_registry,
            event_recorder=event_recorder,
            llm_config=build_llm_client_from_settings(),
        )
        # 刷新 lanes 终态
        lanes_out = [
            _to_lane_out(lane_registry.get_lane(l.lane_id) or l)
            for l in lanes_out
        ]
    else:
        asyncio.create_task(
            _execute_plan_lanes(
                plan=plan,
                lanes=[lane_registry.get_lane(l.lane_id) for l in plan.tasks],
                lane_registry=lane_registry,
                task_registry=task_registry,
                event_recorder=event_recorder,
                llm_config=build_llm_client_from_settings(),
            )
        )

    return CreateLanesOut(
        ok=True,
        team_id=plan.team_id,
        lanes=lanes_out,
        tasks=[_to_task_out(t) for t in plan.tasks],
        review=review,
    )
```

- 新增模块级函数（`create_lanes` 之后）：

```python
async def _execute_plan_lanes(
    *,
    plan: Any,
    lanes: List[Any],
    lane_registry: Any,
    task_registry: Any,
    event_recorder: Any,
    llm_config: Any,
) -> Optional[Dict[str, Any]]:
    """并行执行 plan 的 lanes（ChatDispatcher._run_subagent 同款语义）。

    - 不强制 DAG 拓扑（与 ChatDispatcher 并行语义一致；spec §7.4 同）。
    - 每 lane 隔离 scratch 目录；run_lane_with_retry + max_lane_iterations 防御。
    - 全部终态后对聚合跑 review（B1 run_review），落 ReviewReport。
    返回 review outcome（wait=true 时携带），后台路径返回 None。
    """
    from backend.orchestration.executor import LaneExecutor
    from backend.orchestration.models import RecoveryPolicy, TaskPacket
    from backend.orchestration.orch_settings import load_orch_settings
    from backend.orchestration.review import run_review
    # run_lane_with_retry 必须 lazy import（模块顶部无此符号）—— 单测 patch
    # backend.orchestration.subagent_runner.run_lane_with_retry 即在调用时截获。
    from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry
    from backend.data.database import get_database
    from pathlib import Path

    settings = load_orch_settings()
    sem = asyncio.Semaphore(settings.max_concurrent_subagents)
    data_dir = Path(get_database().db_path).parent
    scratch_root_dir = data_dir / settings.scratch_root / f"api-{plan.team_id}"

    async def run_one(lane: Any) -> None:
        async with sem:
            task = task_registry.get_task(lane.task_id)
            if task is None:  # 防御：task 缺失 → lane failed
                lane_registry.mark_failed(lane.lane_id, error="task not found")
                return
            goal = task.description or ""
            task.packet = TaskPacket(
                objective=goal,
                recovery_policy=RecoveryPolicy(
                    on_failure="retry", max_retries=settings.max_retries
                ),
            )
            task_registry.repo.update(task)
            scratch_dir = scratch_root_dir / lane.lane_id
            scratch_dir.mkdir(parents=True, exist_ok=True)
            task_registry.mark_running(lane.task_id)
            lane_registry.mark_running(lane.lane_id)
            executor = LaneExecutor(
                lane_registry=lane_registry,
                task_registry=task_registry,
                event_recorder=event_recorder,
                agent_runner=SubagentRunner(llm_config),
            )
            result = await run_lane_with_retry(executor, lane, lane.agent_id)
            iterations = 0
            while result.get("status") == "retrying":
                iterations += 1
                if iterations >= settings.max_lane_iterations:
                    lane_registry.mark_failed(
                        lane.lane_id,
                        error=(
                            f"MAX_ITERATIONS_EXCEEDED: retry loop exceeded "
                            f"max_iterations={settings.max_lane_iterations}"
                        ),
                    )
                    task_registry.mark_failed(lane.task_id, error="max iterations")
                    return
                result = await run_lane_with_retry(executor, lane, lane.agent_id)
            if result.get("status") == "succeeded":
                lane_registry.mark_completed(lane.lane_id, result=result.get("result"))
                task_registry.mark_completed(lane.task_id, result=result.get("result"))
            else:
                err = result.get("error", "lane failed")
                lane_registry.mark_failed(lane.lane_id, error=err)
                task_registry.mark_failed(lane.task_id, error=err)

    await asyncio.gather(*(run_one(l) for l in lanes if l is not None))

    # 全部终态后聚合 + 验证环（ChatDispatcher 同款）。
    outputs = []
    for lane in lanes:
        if lane is None:
            continue
        task = task_registry.get_task(lane.task_id)
        if task is not None and getattr(task, "result", None) is not None:
            outputs.append(str(task.result))
        elif task is not None and getattr(task, "error", None):
            outputs.append(f"[failed] {task.error}")
    aggregated = "\n\n".join(outputs)
    if not aggregated:
        return None
    try:
        return await run_review(
            run_id=f"api-{plan.team_id}",
            aggregated=aggregated,
            task_registry=task_registry,
            lane_registry=lane_registry,
            event_recorder=event_recorder,
            llm_config=llm_config,
        )
    except Exception as exc:  # noqa: BLE001 — 复核失败降级不阻塞
        logger.warning("API lane review 失败: %s", exc)
        return None
```

（`llm_config=None`（无配置）时 `SubagentRunner(None)` 会让 execute_lane 失败 → lane failed with 明确错误 —— 与 spec §4.1「无配置 → lane 直接 failed」一致，无需额外分支。）

- [x] **Step 4: 跑测试确认通过 + 集成**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orchestration_router_exec.py -v`
Expected: 2 passed
Run（HTTP 集成，`backend/tests/integration/test_orchestration_router_exec_integration.py` 或复用既有 lane e2e）：

```python
"""wait=true：TestClient POST /orchestration/lanes?wait=true → lanes 终态 + review 字段。"""
def test_create_lanes_wait_true_returns_terminal(tmp_path):
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as client:
        # 需要 app_settings 配置 LLM（否则 lane failed with 明确错误 —— 仍为终态）。
        resp = client.post("/api/v1/orchestration/lanes?wait=true", json={"goal": "写一段三行文字"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert all(l["status"] in ("done", "failed") for l in body["lanes"])
```

（若无 LLM 配置，断言改为「全部 lane 终态（done 或 failed）」，不要求全 done。）

- [x] **Step 5: Commit**

```bash
git add backend/api/orchestration_router.py backend/tests/unit/test_orchestration_router_exec.py backend/tests/integration/test_orchestration_router_exec_integration.py
git commit -m "feat(orch): P2-10 POST /orchestration/lanes?wait=true 真实执行 + review"
```

---

## Task B3: `GET /orchestration/board` 监控端点

**Files:**
- Modify: `backend/api/orchestration_router.py`（新增端点）
- Test: `backend/tests/unit/test_board_endpoint.py`

**Interfaces:**
- Produces: `GET /orchestration/board` → `LaneBoardBuilder.build_snapshot(actor="http-api").to_dict()`（lanes 分 active/blocked/finished + freshness_summary + 汇总）。

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_board_endpoint.py
"""Wave 3 B2 — GET /orchestration/board 返回 LaneBoard snapshot。"""
from fastapi.testclient import TestClient

from backend.main import app


def test_board_endpoint_shape():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"]
    assert body["generated_by"] == "http-api"
    for key in ("active", "blocked", "finished"):
        assert key in body
        assert isinstance(body[key], list)
    assert "freshness_summary" in body
```

- [x] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_board_endpoint.py -v`
Expected: FAIL — 404（无该端点）

- [x] **Step 3: 写最小实现**

`orchestration_router.py` `build_router()` 内 `cancel_lane` 之后加：

```python
@router.get("/board")
async def board() -> Dict[str, Any]:
    """LaneBoard 监控快照（M4 交付但未暴露 HTTP — P2-10 补暴露）。"""
    from backend.orchestration.lane_board import LaneBoardBuilder

    builder = LaneBoardBuilder(lane_registry=LaneRegistry())
    return builder.build_snapshot(actor="http-api").to_dict()
```

（`Dict` import 若缺则顶部补 `from typing import Dict`。）

- [x] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_board_endpoint.py -v`
Expected: 1 passed

- [x] **Step 5: Commit**

```bash
git add backend/api/orchestration_router.py backend/tests/unit/test_board_endpoint.py
git commit -m "feat(orch): P2-10 GET /orchestration/board — LaneBoard 监控端点"
```

---

### PR B 收尾验证

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q
cd /home/fz/project/sage && npx vitest run
```

期望：pytest 全绿、vitest 全绿、tsc 0 错。

---

# PR C — 前端（计划卡接线 + 取消执行 + 模板选择器 + resume 恢复流）

**分支：`feat/orch-wave3-pr-c`**（依赖 PR A 的 A9/A10 后端端点 + A11 类型）。

## Task C1: orchRunClient cancelRun + detail/resume 字段

**Files:**
- Modify: `src/shared/api/orchRunClient.ts`
- Test: `src/shared/api/__tests__/orchRunClient.test.ts`（或既有 client 测试）

**Interfaces:**
- Produces: `orchRunClient.cancelRun(runId) -> Promise<{ok, run_id, status}>`；`OrchRunDetail.original_request?: string`；`ResumeResponse.original_request?: string`。

- [ ] **Step 1: 写失败测试**

```ts
// src/shared/api/__tests__/orchRunClient.test.ts
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../desktopInvoke', () => ({ invoke: vi.fn() }));
import { invoke } from '../desktopInvoke';
import { orchRunClient } from '../orchRunClient';

describe('orchRunClient.cancelRun', () => {
  beforeEach(() => vi.clearAllMocks());
  it('调 orchestration_cancel_run IPC', async () => {
    vi.mocked(invoke).mockResolvedValue({ ok: true, run_id: 'r1', status: 'cancelled' });
    const resp = await orchRunClient.cancelRun('r1');
    expect(invoke).toHaveBeenCalledWith('orchestration_cancel_run', { run_id: 'r1' });
    expect(resp.status).toBe('cancelled');
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/orchRunClient.test.ts`
Expected: FAIL — `orchRunClient.cancelRun is not a function`

- [ ] **Step 3: 写最小实现**

```ts
export interface OrchRunDetail {
  run_id: string;
  session_id: string;
  status: string;
  created_at: number;
  plan: TaskPlanItem[];
  tasks: Array<Record<string, unknown>>;
  // Wave 3 A9 (2026-08-14): resume 恢复流原始请求。
  original_request?: string;
}

export interface ResumeResponse {
  ok: boolean;
  new_run_id: string;
  session_id: string;
  plan: TaskPlanItem[];
  original_request?: string;
}

export interface CancelRunResponse {
  ok: boolean;
  run_id: string;
  status: string;
}

export const orchRunClient = {
  ...
  // Wave 3 (2026-08-14): run 级取消（后端 POST /orch/runs/{id}/cancel）。
  cancelRun(runId: string): Promise<CancelRunResponse> {
    return invoke<CancelRunResponse>('orchestration_cancel_run', { run_id: runId });
  },
};
```

（IPC 名 `orchestration_cancel_run` 需与 electron 桥 `electron/main.ts` 的 ipcMain.handle 注册对应 —— A8 后端端点经 `orch_routes` 挂载，electron 侧 bridge 若按现有 `orchestration_list_runs` 等模式注册 `orchestration_cancel_run`，需同步加一行 handle。检查 `src/electron/` 或 `electron/` 的 ipcMain 注册，补对应 handler 调 `/orch/runs/{id}/cancel`。）

- [ ] **Step 4: 跑测试确认通过 + typecheck:electron**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/orchRunClient.test.ts`
Expected: passed
Run: `cd /home/fz/project/sage && npm run typecheck:electron`
Expected: 0 错

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/orchRunClient.ts src/shared/api/__tests__/orchRunClient.test.ts
git commit -m "feat(orch): orchRunClient.cancelRun + detail/resume original_request"
```

---

## Task C2: chatApi/chatStream/useChat planOverride + runId 透传 + resumeOrchestration + clearTaskBoard

**Files:**
- Modify: `src/shared/api/types.ts`（`ChatConfig` 增 `planOverride`/`runId`）
- Modify: `src/shared/api/chatApi.ts:120`（invoke payload 透传 `plan_override`/`run_id`）
- Modify: `src/features/send-message/useChat.ts`（`sendMessage` 5th 参 + `resumeOrchestration` + `clearTaskBoard`）
- Test: `src/shared/api/__tests__/chatApi.orchestration.test.ts` + `src/features/send-message/__tests__/useChat.resume.test.ts`（或既有）

**Interfaces:**
- Produces:
  - `ChatConfig.planOverride?: TaskPlanItem[]`、`ChatConfig.runId?: string`。
  - `chatStream` invoke payload 加 `plan_override: config?.planOverride ?? null`、`run_id: config?.runId ?? null`。
  - `useChat.sendMessage(content, sessionId?, officeRefs?, orchestrationMode?, opts?: { planOverride?; runId? })`，`config` 合并 opts。
  - `useChat.resumeOrchestration(runId)`：`resumeRun(runId)` → `sendMessage(resp.original_request ?? '', undefined, undefined, 'force_multi', { planOverride: resp.plan, runId: resp.new_run_id })`。
  - `useChat.clearTaskBoard()`：`setTaskBoard(null)`（取消执行后清板）。

- [ ] **Step 1: 写失败测试**

```ts
// src/shared/api/__tests__/chatApi.orchestration.test.ts（追加）
import { chatApi } from '../chatApi';
import { invoke } from '../desktopInvoke';

it('透传 plan_override/run_id 到 agent_chat_stream', async () => {
  vi.mocked(invoke).mockResolvedValue({ streamId: 's1' });
  const onEvent = vi.fn();
  await chatApi.chatStream('sid', 'msg', { onEvent }, {
    orchestrationMode: 'force_multi',
    planOverride: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
    runId: 'orch-reused',
  });
  expect(invoke).toHaveBeenCalledWith(
    'agent_chat_stream',
    expect.objectContaining({
      orchestrationMode: 'force_multi',
      plan_override: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }],
      run_id: 'orch-reused',
    }),
  );
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/chatApi.orchestration.test.ts`
Expected: FAIL — payload 无 `plan_override`/`run_id`。

- [ ] **Step 3: 写最小实现**

`src/shared/api/types.ts` `ChatConfig` 追加：

```ts
  /** Multi-Agent Orchestration: auto | force_multi | force_single | template:<id> */
  orchestrationMode?: string;
  // Wave 3 (2026-08-14): resume 恢复流 —— plan_override 逐字恢复（跳过 LLM 拆解）。
  planOverride?: TaskPlanItem[];
  runId?: string;
```

（`orchestrationMode` 类型从 `'auto'|'force_multi'|'force_single'` 放宽为 `string` 以容纳 `template:<id>`；后端 ChatRequest 本就 `Optional[str]`。）

`src/shared/api/chatApi.ts` invoke payload 加：

```ts
      orchestrationMode: config?.orchestrationMode ?? null,
      // Wave 3 A10 (2026-08-14): resume plan_override / run_id 透传。
      plan_override: config?.planOverride ?? null,
      run_id: config?.runId ?? null,
```

`src/features/send-message/useChat.ts`：

```ts
  const sendMessage = useCallback(
    async (
      content: string,
      sessionId?: string,
      officeRefs?: readonly ChatOfficeRef[],
      orchestrationMode?: ChatConfig['orchestrationMode'],
      opts?: { planOverride?: TaskPlanItem[]; runId?: string },
    ) => {
      ...
      const config: ChatConfig = {
        ...
        orchestrationMode,
        // Wave 3: resume 恢复流透传
        planOverride: opts?.planOverride,
        runId: opts?.runId,
      };
      ...
    },
    [...],
  );
```

新增（放在 `sendMessage` 之后）：

```ts
  /** Wave 3 (2026-08-14): resume 恢复流 —— resumeRun → sendMessage(original_request, plan_override)。 */
  const resumeOrchestration = useCallback(
    async (runId: string) => {
      const resp = await orchRunClient.resumeRun(runId);
      await sendMessage(resp.original_request ?? '', undefined, undefined, 'force_multi', {
        planOverride: resp.plan,
        runId: resp.new_run_id,
      });
    },
    [sendMessage],
  );

  /** Wave 3 (2026-08-14): 取消执行后清空任务板。 */
  const clearTaskBoard = useCallback(() => setTaskBoard(null), []);
```

顶部 import 补 `import { orchRunClient } from '../../shared/api/orchRunClient';`。export 补 `resumeOrchestration, clearTaskBoard`。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/chatApi.orchestration.test.ts`
Expected: passed
Run: `cd /home/fz/project/sage && npx vitest run src/features/send-message`
Expected: 全绿（`ChatConfig.orchestrationMode` 放宽为 string 可能影响既有断言类型，同步修）

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/types.ts src/shared/api/chatApi.ts src/features/send-message/useChat.ts src/shared/api/__tests__/chatApi.orchestration.test.ts
git commit -m "feat(orch): chatStream/useChat planOverride + runId 透传 + resumeOrchestration + clearTaskBoard"
```

---

## Task C3: ProgressSection 三态接线

**Files:**
- Modify: `src/widgets/chat/progress/ProgressSection.tsx`
- Modify: `src/widgets/chat/RightPanel.tsx`（透传 `onResumeRun`/`onCancelExecution` 到 ProgressSection）
- Modify: `src/pages/Chat.tsx`（从 useChat 取 `resumeOrchestration`/`clearTaskBoard` → 包成回调传 RightPanel）
- Test: `src/widgets/chat/__tests__/ProgressSection.test.tsx`

**Interfaces:**
- Consumes: `PlanCardList`（onResume）、`PlanCard`（runId/plan/locked/onCancel/onStart）、`TaskTreeSection`（既有）。
- Produces: ProgressSection 三态：`taskBoard == null` → PlanCardList；`taskBoard && !taskBoard.dispatchedAt` → PlanCard（未派发可编辑）；`taskBoard && taskBoard.dispatchedAt` → TaskTreeSection（执行中）。新 props：`onResumeRun?: (runId: string) => void`、`onCancelExecution?: (runId: string) => void`、`onStarted?: (runId: string, plan: TaskPlanItem[]) => void`（开始执行 → updatePlan 落库）。

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ProgressSection.test.tsx（追加）
import { render, screen } from '@testing-library/react';
import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection 三态', () => {
  it('taskBoard == null → 渲染 PlanCardList（历史记录）', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} taskBoard={null} onResumeRun={vi.fn()} />);
    expect(screen.getByTestId('plan-card-list')).toBeInTheDocument();
  });

  it('taskBoard 未派发 → 渲染 PlanCard（可编辑）', () => {
    const board = { runId: 'r1', plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }], statuses: {}, dispatchedAt: null };
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} taskBoard={board} onResumeRun={vi.fn()} />);
    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
  });

  it('taskBoard 已派发 → 渲染 TaskTreeSection', () => {
    const board = { runId: 'r1', plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }], statuses: {}, dispatchedAt: Date.now() };
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} taskBoard={board} onResumeRun={vi.fn()} />);
    // TaskTreeSection 的 data-testid（沿用既有）
    expect(screen.getByTestId('task-tree')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: FAIL — taskBoard==null 仍渲染 toolCalls 区 / 无 PlanCardList。

- [ ] **Step 3: 写最小实现**

`ProgressSection.tsx`：

```tsx
import { PlanCard } from '../../../components/PlanCard';
import { PlanCardList } from '../../../components/PlanCardList';
import type { TaskPlanItem } from '../../../shared/api/types';

interface ProgressSectionProps {
  ...
  taskBoard?: TaskBoard | null;
  // Wave 3 (2026-08-14): 历史恢复 / 计划卡接线回调。
  onResumeRun?: (runId: string) => void;
  onCancelExecution?: (runId: string) => void;
  onPlanStart?: (runId: string, plan: TaskPlanItem[]) => void;
}
```

渲染三态替换既有 `{taskBoard ? <TaskTreeSection/> : toolCalls}`：

```tsx
      {taskBoard == null ? (
        // Wave 3 (2026-08-14): 无编排任务 → 历史编排记录（恢复入口）。
        <PlanCardList onResume={onResumeRun ?? (() => {})} />
      ) : taskBoard.dispatchedAt ? (
        <TaskTreeSection board={taskBoard} />
      ) : (
        // Wave 3 (2026-08-14): 未派发 → 计划卡（可编辑 + 开始/取消）。
        <PlanCard
          runId={taskBoard.runId}
          plan={taskBoard.plan}
          locked={false}
          onCancel={() => onCancelExecution?.(taskBoard.runId)}
          onStart={(updated) => onPlanStart?.(taskBoard.runId, updated)}
        />
      )}
```

（顶部三态决策处 `hasTaskBoard` 语义调整：`showProgress` 仅在已派发时显示 5 元组，未派发显示「计划待执行」。）

`RightPanel.tsx` 增 props 透传：

```tsx
interface RightPanelProps {
  ...
  onResumeRun?: (runId: string) => void;
  onCancelExecution?: (runId: string) => void;
  onPlanStart?: (runId: string, plan: TaskPlanItem[]) => void;
}
// 传给 <ProgressSection ... onResumeRun={onResumeRun} onCancelExecution={onCancelExecution} onPlanStart={onPlanStart} />
```

`src/pages/Chat.tsx`：

```tsx
const { ..., resumeOrchestration, clearTaskBoard } = useChat();
const handlePlanStart = async (runId: string, plan: TaskPlanItem[]) => {
  try {
    await orchRunClient.updatePlan(runId, plan);
  } catch {
    // 409（派发竞态）→ 保持编辑态，TaskBoard 首 status 事件会锁
  }
};
<RightPanel
  ...
  taskBoard={taskBoard ?? null}
  onResumeRun={(runId) => { void resumeOrchestration(runId); }}
  onCancelExecution={(runId) => {
    void orchRunClient.cancelRun(runId).then(() => clearTaskBoard());
  }}
  onPlanStart={handlePlanStart}
/>
```

（`orchRunClient` import 到 Chat.tsx；C4 的 PlanCard 内部 `onCancel` 语义随 locked 切换 —— 见 C4。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: 3 passed（+ 既有用例全绿）
Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat src/components/PlanCard*`
Expected: 全绿（若 PlanCardList 的 onResume 签名变更，C5 一起改）

- [ ] **Step 5: Commit**

```bash
git add src/widgets/chat/progress/ProgressSection.tsx src/widgets/chat/RightPanel.tsx src/pages/Chat.tsx src/widgets/chat/__tests__/ProgressSection.test.tsx
git commit -m "feat(orch): ProgressSection 三态接线 — 历史/计划卡/任务树"
```

---

## Task C4: PlanCard 交互接线（开始执行 + 取消语义随 locked）

**Files:**
- Modify: `src/components/PlanCard.tsx`
- Modify: `src/components/PlanCardList.tsx`（onResume 签名加 originalRequest —— 见 C5）
- Test: `src/components/__tests__/PlanCard.test.tsx`

**Interfaces:**
- Consumes: `orchRunClient.cancelRun`（C1）。
- Produces: PlanCard 增 `runId` prop；取消按钮语义随 `locked` 切换：未派发 → `onCancel`（清 board，不调后端）；已派发 → 文案「取消执行」→ `orchRunClient.cancelRun(runId)` + `onCancelled` 回调。`onStart` 内 `updatePlan(runId, plan)` 落库 + 本地锁定。

- [ ] **Step 1: 写失败测试**

```tsx
// src/components/__tests__/PlanCard.test.tsx（追加）
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PlanCard } from '../PlanCard';

describe('PlanCard 接线', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  it('未派发：取消 → onCancel（不调后端）', () => {
    const onCancel = vi.fn();
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={onCancel} onStart={vi.fn()} />);
    fireEvent.click(screen.getByTestId('plan-cancel'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('已派发：按钮文案「取消执行」→ cancelRun + onCancelled', async () => {
    const onCancelled = vi.fn();
    const { orchRunClient } = require('../../shared/api/orchRunClient');
    vi.spyOn(orchRunClient, 'cancelRun').mockResolvedValue({ ok: true, run_id: 'r1', status: 'cancelled' });
    render(<PlanCard runId="r1" plan={plan} locked onCancel={() => {}} onStart={vi.fn()} onCancelled={onCancelled} />);
    expect(screen.getByTestId('plan-cancel')).toHaveTextContent('取消执行');
    fireEvent.click(screen.getByTestId('plan-cancel'));
    await waitFor(() => expect(orchRunClient.cancelRun).toHaveBeenCalledWith('r1'));
    expect(onCancelled).toHaveBeenCalled();
  });

  it('开始执行 → updatePlan 落库 + 本地锁定', async () => {
    const { orchRunClient } = require('../../shared/api/orchRunClient');
    vi.spyOn(orchRunClient, 'updatePlan').mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} onStart={vi.fn()} />);
    fireEvent.click(screen.getByTestId('plan-start'));
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledWith('r1', expect.any(Array)));
    // 锁定后开始按钮 disabled + 文案「已开始执行」
    await waitFor(() => expect(screen.getByTestId('plan-start')).toBeDisabled());
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/components/__tests__/PlanCard.test.tsx`
Expected: FAIL — 无 runId/onCancelled prop、取消不调 cancelRun、开始不 updatePlan。

- [ ] **Step 3: 写最小实现**

`PlanCard.tsx`：

```tsx
import { orchRunClient } from '../shared/api/orchRunClient';

interface PlanCardProps {
  runId: string;
  plan: TaskPlanItem[];
  locked: boolean;            // 派发后转 true（后端 update_plan 409）
  onCancel: () => void;       // 未派发：清 board
  onStart: (updatedPlan: TaskPlanItem[]) => void;
  onCancelled?: () => void;   // Wave 3：已派发取消成功后回调（清 board）
}

export function PlanCard({ runId, plan: initialPlan, locked, onCancel, onStart, onCancelled }: PlanCardProps) {
  const [items, setItems] = useState(initialPlan);
  // Wave 3: 本地锁定 —— onStart 落库后立即锁定（不等后端 dispatchedAt 事件）。
  const [locallyLocked, setLocallyLocked] = useState(false);
  const effectiveLocked = locked || locallyLocked;

  const handleStart = async () => {
    setLocallyLocked(true);
    try {
      await orchRunClient.updatePlan(runId, items);
    } catch {
      // 409（派发竞态）→ 后端已锁定，不抛（本地锁定保持，TaskBoard 会切树）。
    }
    onStart(items);
  };

  const handleCancel = () => {
    if (effectiveLocked) {
      // Wave 3: 已派发 → run 级取消（停新任务，不硬杀 running）。
      void orchRunClient.cancelRun(runId).then(() => onCancelled?.());
      return;
    }
    onCancel();  // 未派发：放弃本次编排（前端清 board，不调后端）
  };

  return (
    <div className="border rounded p-3 bg-bg-hover" data-testid="plan-card">
      <div className="flex justify-between mb-2">
        <h3 className="text-sm font-semibold">编排计划（{items.length} 项）</h3>
        <div className="flex gap-2">
          <button
            disabled={effectiveLocked}
            onClick={() => { void handleStart(); }}
            data-testid="plan-start"
            className="px-2 py-1 text-xs border rounded bg-primary/10 text-primary"
          >
            {effectiveLocked ? '已开始执行（计划锁定）' : '开始执行'}
          </button>
          <button
            onClick={handleCancel}
            data-testid="plan-cancel"
            className="px-2 py-1 text-xs border rounded"
          >
            {effectiveLocked ? '取消执行' : '取消'}
          </button>
        </div>
      </div>
      {items.map((item, idx) => (
        ... (textarea/删除按钮，disabled={effectiveLocked}，goal 编辑不变)
      ))}
    </div>
  );
}
```

（删除按钮守卫 `effectiveLocked || items.length <= 1` 沿用。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd /home/fz/project/sage && npx vitest run src/components/__tests__/PlanCard.test.tsx src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: 全绿（既有 PlanCard 8 单测若断言旧 props（无 runId）需同步加 runId）

- [ ] **Step 5: Commit**

```bash
git add src/components/PlanCard.tsx src/components/__tests__/PlanCard.test.tsx
git commit -m "feat(orch): PlanCard 接线 — 开始执行落库 + 取消语义随 locked"
```

---

## Task C5: PlanCardList 恢复流（original_request 逐字恢复）

**Files:**
- Modify: `src/components/PlanCardList.tsx`
- Test: `src/components/__tests__/PlanCardList.test.tsx`

**Interfaces:**
- Consumes: `onResume(runId)` 回调（C2 的 `resumeOrchestration`）。
- Produces: PlanCardList 的 `handleResume` 改为直接调 `onResume(runId)`（不再内部调 resumeRun —— resume 封装进 useChat.resumeOrchestration，见 C2）。`onResume` prop 签名变 `(runId: string) => void`。

- [ ] **Step 1: 写失败测试**

```tsx
// src/components/__tests__/PlanCardList.test.tsx（追加/更新）
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PlanCardList } from '../PlanCardList';
import { orchRunClient } from '../../shared/api/orchRunClient';

describe('PlanCardList 恢复流', () => {
  it('点击恢复 → onResume(runId) 交给 useChat.resumeOrchestration', async () => {
    const onResume = vi.fn();
    vi.spyOn(orchRunClient, 'listRuns').mockResolvedValue([
      { run_id: 'r1', session_id: 's1', status: 'completed', created_at: Date.now() },
    ]);
    render(<PlanCardList onResume={onResume} />);
    await waitFor(() => expect(screen.getByTestId('plan-resume-r1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('plan-resume-r1'));
    expect(onResume).toHaveBeenCalledWith('r1');
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/components/__tests__/PlanCardList.test.tsx`
Expected: FAIL — 现 handleResume 内部调 resumeRun 并回调 `(new_run_id, plan)`，与 `onResume(runId)` 不匹配。

- [ ] **Step 3: 写最小实现**

`PlanCardList.tsx`：

```tsx
interface PlanCardListProps {
  // Wave 3 (2026-08-14): onResume 改为交 runId 给 useChat.resumeOrchestration
  //（内部完成 resumeRun → sendMessage(original_request, plan_override)）。
  onResume: (runId: string) => void;
}

export function PlanCardList({ onResume }: PlanCardListProps) {
  const [runs, setRuns] = useState<OrchRunSummary[]>([]);

  useEffect(() => {
    orchRunClient.listRuns().then(setRuns);
  }, []);

  const handleResume = (runId: string) => onResume(runId);

  return ( ... 同既有渲染，onClick={() => handleResume(r.run_id)} ... );
}
```

（移除 `import { orchRunClient }` 的 resumeRun 依赖；`listRuns` 仍在组件内用。测试改 mock `orchRunClient.listRuns`。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd /home/fz/project/sage && npx vitest run src/components/__tests__/PlanCardList.test.tsx src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: 全绿（既有 PlanCardList 单测若 mock resumeRun 需改成 mock listRuns + onResume 断言）

- [ ] **Step 5: Commit**

```bash
git add src/components/PlanCardList.tsx src/components/__tests__/PlanCardList.test.tsx
git commit -m "feat(orch): PlanCardList 恢复流 — onResume(runId) 委托 useChat.resumeOrchestration"
```

---

## Task C6: 模板选择器（ChatInput 编排模式条）

**Files:**
- Modify: `src/widgets/chat/ChatInput.tsx`（或既有编排模式条所在组件）
- Modify: `src/locales/zh-CN.json` / `en.json`（`chat.*` i18n keys）
- Test: `src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx`（既有文件追加）

**Interfaces:**
- Produces: Chat 输入区上方编排模式下拉：「编排模式：自动 ▾」，选项：自动（LLM 二分类）/ 强制编排（LLM 拆解）/ `research-write` / `gather-analyze-report`。选模板 → `orchestrationMode = "template:<id>"` 经 `chatStream` payload 透传（既有 `orchestrationMode` 通道）。与斜杠命令并存（斜杠是临时 override，selector 是偏好，本波偏好只存组件 state —— YAGNI 不写 settings）。

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx（追加）
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInput } from '../ChatInput';

it('模板选择器选 research-write → orchestrationMode=template:research-write', () => {
  const onSend = vi.fn();
  render(<ChatInput onSend={onSend} ... />);
  fireEvent.change(screen.getByTestId('orch-mode-select'), { target: { value: 'template:research-write' } });
  fireEvent.click(screen.getByTestId('chat-send'));
  expect(onSend).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ orchestrationMode: 'template:research-write' }));
});
```

（`onSend` 实际签名按既有 ChatInput 测试风格调整；核心断言是 selector 值 → `orchestrationMode` 透传。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx`
Expected: FAIL — 无 `orch-mode-select`。

- [ ] **Step 3: 写最小实现**

ChatInput 组件内加编排模式条（放在输入框上方工具条，样式沿用既有工具条）：

```tsx
// 编排模式条：auto | force_multi | template:<id>
const [orchMode, setOrchMode] = useState<'auto' | 'force_multi' | string>('auto');
...
<div className="flex items-center gap-2 px-2 py-1 border-b border-border">
  <label className="text-xs text-text-tertiary">编排模式</label>
  <select
    data-testid="orch-mode-select"
    value={orchMode}
    onChange={(e) => setOrchMode(e.target.value)}
    className="px-2 py-0.5 text-xs border border-border rounded bg-bg text-text"
  >
    <option value="auto">自动（LLM 判定）</option>
    <option value="force_multi">强制编排（LLM 拆解）</option>
    <option value="template:research-write">模板：调研与写作</option>
    <option value="template:gather-analyze-report">模板：收集-分析-报告</option>
  </select>
</div>
```

发送时把 `orchMode` 并入 `chatStream` config：`orchestrationMode: orchMode === 'auto' ? 'auto' : orchMode`（保持既有 `undefined → null → auto` 语义）。i18n keys：`chat.orchMode.label` / `chat.orchMode.auto` / `chat.orchMode.forceMulti` / `chat.orchMode.templateResearchWrite` / `chat.orchMode.templateGatherAnalyzeReport`。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx`
Expected: passed
Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat`
Expected: 全绿（既有 ChatInput 测试不受影响 —— 新增 select 有独立 data-testid，默认值 auto 不改变既有发送行为）

- [ ] **Step 5: Commit**

```bash
git add src/widgets/chat/ChatInput.tsx src/locales/zh-CN.json src/locales/en.json src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx
git commit -m "feat(orch): 模板选择器 — ChatInput 编排模式条 + i18n"
```

---

### PR C 收尾验证

```bash
cd /home/fz/project/sage && npx vitest run
npm run tsc
npm run typecheck:electron   # electron 改动（orchRunClient/IPC）必须跑
npm run build:electron
```

期望：vitest 全绿（≥1239 + 新增 ~15）、tsc 0 错、typecheck:electron 0 错、electron build 通过。

---

## 全局回归 + 收尾（3 PR 全部合入后）

```bash
# 后端
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -q
# 前端
cd /home/fz/project/sage && npx vitest run && npm run tsc && npm run typecheck:electron
# ruff
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/ --fix
```

期望：pytest ≥3706（+~25 新用例）、vitest ≥1239（+~15）、tsc 0、typecheck:electron 0、ruff 0 错。

**文档归档**：`docs/technical/42`（编排章节）追加 Wave 3 小节（P2-7/8/9/10 + 计划卡接线 + resume），按用户 feature-development 规则把 `docs/plans/` 与本 spec/plan 的功能点并入技术手册后删除 plan 文件。

**记忆沉淀**：Wave 3 合并后更新 `sage-orchestration-plan-lifecycle-wave2` 或新建 wave3 memory，记录 PR 号、commit、测试数、CI 结果。
