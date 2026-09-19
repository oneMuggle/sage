# 任务层级化实施计划

> **状态**：已完成（2026-09-19，9/9 Task 落地；ledger 见 .superpowers/sdd/2026-09-19-task-hierarchy/progress.md）
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现增量任务层级模型，支持 `parent_task_id` 和 `depth` 字段，前后端完整透传，前端展示可折叠树形任务视图。

**Architecture:** 保留现有平铺任务列表和 `depends_on` DAG。`parent_task_id` 仅表达归属和展示层级，不参与调度。数据库使用幂等迁移添加可空列，旧数据默认作为根任务。前端通过 `parent_task_id` 构建树形索引并渲染。

**Tech Stack:** Python 3.10+、SQLite、React 18+、TypeScript 5+、FastAPI

**Spec:** docs/superpowers/specs/2026-09-19-task-hierarchy-design.md

## Global Constraints

- `parent_task_id` 必须引用同一计划中存在的任务
- 任务不能以自己为父任务
- 父链不能形成环
- `depth` 必须等于父任务深度加一，根任务为零
- 最大深度 `MAX_TASK_DEPTH = 8`
- 所有新字段均可空或有默认值，旧数据无需迁移
- `parent_task_id` 不参与调度，`depends_on` 继续负责拓扑排序

---

### Task 1: 数据库迁移（添加 parent_task_id 和 depth 列）

**Files:**
- Modify: `backend/data/database.py:1420-1430`
- Test: `backend/tests/unit/test_orch_task_repo.py`

**Interfaces:**
- Consumes: 现有 `orch_tasks` 表结构
- Produces: `orch_tasks` 表增加 `parent_task_id TEXT NULL` 和 `depth INTEGER NOT NULL DEFAULT 0` 列

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_orch_task_repo.py

def test_orch_tasks_schema_has_parent_and_depth_columns(tmp_path, monkeypatch):
    """orch_tasks 表必须包含 parent_task_id 和 depth 列。"""
    from backend.data import database as db_mod
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(orch_tasks)")
    columns = {row["name"]: row["type"] for row in cursor.fetchall()}
    
    assert "parent_task_id" in columns
    assert columns["parent_task_id"] == "TEXT"
    assert "depth" in columns
    assert columns["depth"] == "INTEGER"
```

- [x] **Step 2: 运行测试验证失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-task-replan-capability
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_task_repo.py::test_orch_tasks_schema_has_parent_and_depth_columns -v
```

Expected: FAIL with "parent_task_id" not in columns

- [x] **Step 3: 实现数据库迁移**

```python
# backend/data/database.py，在 orch_tasks 表定义后添加

# 任务层级化 (2026-09-19): 添加 parent_task_id 和 depth 列
# 幂等迁移：检查列是否存在，不存在则添加
cursor.execute("PRAGMA table_info(orch_tasks)")
_existing_cols = {row["name"] for row in cursor.fetchall()}
if "parent_task_id" not in _existing_cols:
    cursor.execute("ALTER TABLE orch_tasks ADD COLUMN parent_task_id TEXT NULL")
if "depth" not in _existing_cols:
    cursor.execute("ALTER TABLE orch_tasks ADD COLUMN depth INTEGER NOT NULL DEFAULT 0")
```

- [x] **Step 4: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_task_repo.py::test_orch_tasks_schema_has_parent_and_depth_columns -v
```

Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/data/database.py backend/tests/unit/test_orch_task_repo.py
git commit -m "feat(orchestration): 添加 orch_tasks parent_task_id 和 depth 列"
```

---

### Task 2: TaskPlanItem 类型扩展

**Files:**
- Modify: `src/shared/api/types.ts:319-326`
- Modify: `src/shared/api/llmStream.ts:33-40`
- Test: `src/shared/api/__tests__/types.test.ts`

**Interfaces:**
- Consumes: 现有 `TaskPlanItem` 接口
- Produces: `TaskPlanItem` 增加 `parent_task_id?: string | null` 和 `depth?: number`

- [x] **Step 1: 写失败测试**

```typescript
// src/shared/api/__tests__/types.test.ts

import { TaskPlanItem } from "../types";

describe("TaskPlanItem", () => {
  it("supports optional parent_task_id and depth", () => {
    const item: TaskPlanItem = {
      task_id: "t1",
      agent_id: "researcher",
      goal: "test",
      parent_task_id: null,
      depth: 0,
    };
    expect(item.parent_task_id).toBeNull();
    expect(item.depth).toBe(0);
  });

  it("allows omitting parent_task_id and depth for backward compatibility", () => {
    const item: TaskPlanItem = {
      task_id: "t1",
      agent_id: "researcher",
      goal: "test",
    };
    expect(item.parent_task_id).toBeUndefined();
    expect(item.depth).toBeUndefined();
  });
});
```

- [x] **Step 2: 运行测试验证失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-task-replan-capability
npm run test:run -- src/shared/api/__tests__/types.test.ts
```

Expected: FAIL with TypeScript compilation error

- [x] **Step 3: 扩展 TaskPlanItem 类型**

```typescript
// src/shared/api/types.ts

export interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
  depends_on?: string[];
  parent_task_id?: string | null;
  depth?: number;
}
```

- [x] **Step 4: 同步 llmStream.ts 的类型**

```typescript
// src/shared/api/llmStream.ts

export interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
  depends_on?: string[];
  parent_task_id?: string | null;
  depth?: number;
}
```

- [x] **Step 5: 运行测试验证通过**

```bash
npm run test:run -- src/shared/api/__tests__/types.test.ts
```

Expected: PASS

- [x] **Step 6: 提交**

```bash
git add src/shared/api/types.ts src/shared/api/llmStream.ts src/shared/api/__tests__/types.test.ts
git commit -m "feat(shared): 扩展 TaskPlanItem 支持 parent_task_id 和 depth"
```

---

### Task 3: 计划规范化器（校验父引用、环、深度）

**Files:**
- Create: `backend/orchestration/plan_hierarchy.py`
- Test: `backend/tests/unit/test_plan_hierarchy.py`

**Interfaces:**
- Consumes: `TaskPlanItem[]`
- Produces: 校验后的 `TaskPlanItem[]`（带规范化的 `depth`）
- Raises: `HierarchyError`（父引用非法、自环、父环、超深）

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_plan_hierarchy.py

import pytest
from backend.orchestration.plan_hierarchy import normalize_task_hierarchy, HierarchyError

def test_normalize_root_task_depth_is_zero():
    """根任务的 depth 应为 0。"""
    plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "g1"},
    ]
    result = normalize_task_hierarchy(plan)
    assert result[0]["depth"] == 0
    assert result[0].get("parent_task_id") is None

def test_normalize_child_task_depth_is_parent_plus_one():
    """子任务的 depth 应为父任务 depth + 1。"""
    plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "g1"},
        {"task_id": "t2", "agent_id": "writer", "goal": "g2", "parent_task_id": "t1"},
    ]
    result = normalize_task_hierarchy(plan)
    assert result[0]["depth"] == 0
    assert result[1]["depth"] == 1
    assert result[1]["parent_task_id"] == "t1"

def test_normalize_rejects_invalid_parent_reference():
    """parent_task_id 引用不存在的任务应拒绝。"""
    plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "g1", "parent_task_id": "t99"},
    ]
    with pytest.raises(HierarchyError, match="parent.*not found"):
        normalize_task_hierarchy(plan)

def test_normalize_rejects_self_reference():
    """任务不能以自己为父任务。"""
    plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "g1", "parent_task_id": "t1"},
    ]
    with pytest.raises(HierarchyError, match="self-reference"):
        normalize_task_hierarchy(plan)

def test_normalize_rejects_parent_cycle():
    """父链不能形成环。"""
    plan = [
        {"task_id": "t1", "agent_id": "a", "goal": "g1", "parent_task_id": "t2"},
        {"task_id": "t2", "agent_id": "b", "goal": "g2", "parent_task_id": "t1"},
    ]
    with pytest.raises(HierarchyError, match="cycle"):
        normalize_task_hierarchy(plan)

def test_normalize_rejects_exceeding_max_depth():
    """depth 超过 MAX_TASK_DEPTH 应拒绝。"""
    from backend.orchestration.plan_hierarchy import MAX_TASK_DEPTH
    
    plan = []
    for i in range(MAX_TASK_DEPTH + 2):
        task = {"task_id": f"t{i}", "agent_id": "a", "goal": f"g{i}"}
        if i > 0:
            task["parent_task_id"] = f"t{i-1}"
        plan.append(task)
    
    with pytest.raises(HierarchyError, match="exceeds max depth"):
        normalize_task_hierarchy(plan)

def test_normalize_preserves_existing_fields():
    """规范化不应修改其他字段。"""
    plan = [
        {
            "task_id": "t1",
            "agent_id": "researcher",
            "goal": "g1",
            "depends_on": ["t2"],
            "parent_task_id": None,
        },
        {"task_id": "t2", "agent_id": "writer", "goal": "g2"},
    ]
    result = normalize_task_hierarchy(plan)
    assert result[0]["depends_on"] == ["t2"]
    assert result[0]["goal"] == "g1"
```

- [x] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_plan_hierarchy.py -v
```

Expected: FAIL with ModuleNotFoundError: No module named 'backend.orchestration.plan_hierarchy'

- [x] **Step 3: 实现计划规范化器**

```python
# backend/orchestration/plan_hierarchy.py

"""任务层级规范化器。

校验 parent_task_id 引用合法性、父环、最大深度，并规范化 depth 字段。
"""

from typing import Any, Dict, List, Optional

MAX_TASK_DEPTH = 8


class HierarchyError(ValueError):
    """任务层级校验失败。"""


def normalize_task_hierarchy(
    plan: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """校验并规范化任务层级。

    Args:
        plan: 平铺任务列表，每个任务可包含 parent_task_id

    Returns:
        规范化后的任务列表（带 depth 字段）

    Raises:
        HierarchyError: 校验失败
    """
    # 构建 task_id 索引
    task_map = {task["task_id"]: task for task in plan}
    
    # 校验 parent_task_id 引用
    for task in plan:
        parent_id = task.get("parent_task_id")
        if parent_id is None:
            continue
        
        # 自引用检查
        if parent_id == task["task_id"]:
            raise HierarchyError(
                f"Task {task['task_id']} has self-reference parent_task_id"
            )
        
        # 引用存在性检查
        if parent_id not in task_map:
            raise HierarchyError(
                f"Task {task['task_id']} references non-existent parent {parent_id}"
            )
    
    # 计算 depth 并检测环
    depth_cache: Dict[str, int] = {}
    
    def compute_depth(task_id: str, visited: set) -> int:
        if task_id in depth_cache:
            return depth_cache[task_id]
        
        task = task_map[task_id]
        parent_id = task.get("parent_task_id")
        
        if parent_id is None:
            depth = 0
        else:
            # 环检测
            if parent_id in visited:
                cycle = " -> ".join([task_id, parent_id] + list(visited))
                raise HierarchyError(f"Parent cycle detected: {cycle}")
            
            visited.add(task_id)
            parent_depth = compute_depth(parent_id, visited)
            depth = parent_depth + 1
        
        # 深度检查
        if depth > MAX_TASK_DEPTH:
            raise HierarchyError(
                f"Task {task_id} depth {depth} exceeds max depth {MAX_TASK_DEPTH}"
            )
        
        depth_cache[task_id] = depth
        return depth
    
    # 为所有任务计算 depth
    for task in plan:
        compute_depth(task["task_id"], set())
    
    # 写入规范化结果
    result = []
    for task in plan:
        normalized = dict(task)
        normalized["depth"] = depth_cache[task["task_id"]]
        result.append(normalized)
    
    return result
```

- [x] **Step 4: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_plan_hierarchy.py -v
```

Expected: PASS (all 7 tests)

- [x] **Step 5: 提交**

```bash
git add backend/orchestration/plan_hierarchy.py backend/tests/unit/test_plan_hierarchy.py
git commit -m "feat(orchestration): 添加任务层级规范化器"
```

---

### Task 4: ChatTaskState 和事件透传

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py:150-175`
- Modify: `backend/orchestration/chat_dispatcher.py:1314-1370`
- Test: `backend/tests/unit/test_chat_dispatcher_hierarchy.py`

**Interfaces:**
- Consumes: `ChatTaskState`, `_emit_task_status()`, `_persist_task_state()`
- Produces: `ChatTaskState` 增加 `parent_task_id`（来自计划），`task_status` 事件携带层级字段

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_chat_dispatcher_hierarchy.py

import asyncio
import json

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


def test_dispatcher_reads_parent_task_id_from_plan(tmp_path, monkeypatch):
    """dispatcher 应从计划读取 parent_task_id 并写入 ChatTaskState。"""
    plan = json.dumps({
        "tasks": [
            {"task_id": "t1", "agent_id": "researcher", "goal": "g1"},
            {"task_id": "t2", "agent_id": "writer", "goal": "g2", "parent_task_id": "t1"},
        ],
        "reasoning": "",
    }, ensure_ascii=False)
    
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    d._ensure_plan_loaded()
    
    assert d._plan_by_id["t2"]["parent_task_id"] == "t1"


def test_dispatcher_emits_parent_task_id_in_task_status(tmp_path, monkeypatch):
    """task_status 事件应携带 parent_task_id 和 depth。"""
    plan = json.dumps({
        "tasks": [
            {"task_id": "t1", "agent_id": "researcher", "goal": "g1"},
            {"task_id": "t2", "agent_id": "writer", "goal": "g2", "parent_task_id": "t1"},
        ],
        "reasoning": "",
    }, ensure_ascii=False)
    
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    
    events = []
    d.entry_queue.put_nowait = lambda evt: events.append(evt)
    
    from backend.orchestration.chat_dispatcher import ChatTaskState
    state = ChatTaskState(
        task_id="t2",
        agent_id="writer",
        goal="g2",
        parent_task_id="t1",
    )
    state.status = "queued"
    
    d._emit_task_status(state)
    
    assert len(events) == 1
    event = events[0]
    assert event["parent_task_id"] == "t1"
    assert event["depth"] == 1  # 应自动计算


def test_dispatcher_persists_parent_task_id_to_orch_tasks(tmp_path, monkeypatch):
    """_persist_task_state 应将 parent_task_id 写入 orch_tasks。"""
    plan = json.dumps({"tasks": [], "reasoning": ""})
    
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    
    from backend.orchestration.chat_dispatcher import ChatTaskState
    state = ChatTaskState(
        task_id="t1",
        agent_id="researcher",
        goal="g1",
        parent_task_id=None,
    )
    state.status = "done"
    state.output = "result"
    state.started_at = 1000.0
    state.finished_at = 2000.0
    
    d._persist_task_state(state)
    
    task = d._orch_task_repo.get("t1")
    assert task is not None
    assert task.parent_task_id is None
    assert task.depth == 0
```

- [x] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_hierarchy.py -v
```

Expected: FAIL with AttributeError: 'ChatTaskState' object has no attribute 'parent_task_id'

- [x] **Step 3: 扩展 ChatTaskState 增加 parent_task_id**

```python
# backend/orchestration/chat_dispatcher.py，在 ChatTaskState dataclass 定义处

@dataclass
class ChatTaskState:
    task_id: str
    agent_id: str
    goal: str
    output_schema: Optional[Dict[str, Any]] = None
    parent_task_id: Optional[str] = None  # 任务层级：父任务 ID
    status: str = "queued"
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    retry_count: int = 0
    followup_degraded: bool = False
    retry_of: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
```

- [x] **Step 4: 在 dispatch 中读取 parent_task_id 并写入 ChatTaskState**

```python
# backend/orchestration/chat_dispatcher.py，在 dispatch() 方法中构建 ChatTaskState 的位置

# 从计划读取层级字段
plan_parent = plan_item.get("parent_task_id") if plan_item else None

state = ChatTaskState(
    task_id=task_id,
    agent_id=agent_id,
    goal=goal,
    output_schema=output_schema,
    parent_task_id=plan_parent,  # 新增
    followup_degraded=followup_degraded,
    parent_tool_call_id=self._current_tool_call_id,
)
```

- [x] **Step 5: 在 _emit_task_status 中透传层级字段**

```python
# backend/orchestration/chat_dispatcher.py，_emit_task_status 方法

def _emit_task_status(self, state: ChatTaskState) -> None:
    event: Dict[str, Any] = {
        "state": "task_status",
        "run_id": self.run_id,
        "task_id": state.task_id,
        "status": state.status,
        "agent_id": state.agent_id,
        "goal": state.goal,
        "error": state.error,
        "retry_count": state.retry_count,
        "output_preview": self._preview(state),
        "parent_tool_call_id": state.parent_tool_call_id,
    }
    
    # 透传层级字段
    if state.parent_task_id is not None:
        event["parent_task_id"] = state.parent_task_id
        # 计算 depth（从计划读取或默认 0）
        plan_item = self._plan_by_id.get(state.task_id, {})
        event["depth"] = plan_item.get("depth", 0)
    
    try:
        self.entry_queue.put_nowait(event)
    except Exception:
        logger.debug("task_status 推送失败（队列满/关闭），忽略")
    
    self._persist_task_state(state)
```

- [x] **Step 6: 在 _persist_task_state 中写入层级字段**

```python
# backend/orchestration/chat_dispatcher.py，_persist_task_state 方法

def _persist_task_state(self, state: ChatTaskState) -> None:
    terminal = state.status in ("done", "failed", "cancelled")
    
    parent_task_id = state.parent_task_id
    depth = 0
    if parent_task_id is not None:
        plan_item = self._plan_by_id.get(state.task_id, {})
        depth = plan_item.get("depth", 0)
    
    self._orch_task_repo.upsert_state(
        task_id=state.task_id,
        run_id=self.run_id,
        agent_id=state.agent_id,
        goal=state.goal,
        status=state.status,
        retry_count=state.retry_count,
        error=state.error,
        output_preview=self._preview(state),
        started_at=int(state.started_at * 1000) if state.started_at else None,
        finished_at=int(state.finished_at * 1000) if state.finished_at else None,
        used_tokens=self._task_tokens_used(state.task_id) if terminal else None,
        duration_ms=(
            int((state.finished_at - state.started_at) * 1000)
            if terminal and state.started_at and state.finished_at
            else None
        ),
        parent_task_id=parent_task_id,  # 新增
        depth=depth,  # 新增
    )
```

- [x] **Step 7: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher_hierarchy.py -v
```

Expected: PASS (all 3 tests)

- [x] **Step 8: 提交**

```bash
git add backend/orchestration/chat_dispatcher.py backend/tests/unit/test_chat_dispatcher_hierarchy.py
git commit -m "feat(orchestration): ChatTaskState 和事件透传层级字段"
```

---

### Task 5: OrchTaskRepository 读写新字段

**Files:**
- Modify: `backend/data/orch_task_repo.py:18-35`
- Modify: `backend/data/orch_task_repo.py:43-100`
- Modify: `backend/data/orch_task_repo.py:118-138`
- Test: `backend/tests/unit/test_orch_task_repo.py`

**Interfaces:**
- Consumes: `OrchTask` dataclass, `upsert_state()` 方法
- Produces: `OrchTask` 增加 `parent_task_id` 和 `depth`，`upsert_state()` 接受并写入这两个字段

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_orch_task_repo.py

def test_upsert_state_with_parent_and_depth(tmp_path, monkeypatch):
    """upsert_state 应能写入和读取 parent_task_id 和 depth。"""
    from backend.data.orch_task_repo import OrchTaskRepository
    from backend.data import database as db_mod
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    repo = OrchTaskRepository()
    repo.upsert_state(
        task_id="t1",
        run_id="r1",
        agent_id="researcher",
        goal="g1",
        status="done",
        parent_task_id=None,
        depth=0,
    )
    
    task = repo.get("t1")
    assert task is not None
    assert task.parent_task_id is None
    assert task.depth == 0
    
    repo.upsert_state(
        task_id="t2",
        run_id="r1",
        agent_id="writer",
        goal="g2",
        status="running",
        parent_task_id="t1",
        depth=1,
    )
    
    task = repo.get("t2")
    assert task is not None
    assert task.parent_task_id == "t1"
    assert task.depth == 1


def test_get_returns_defaults_for_missing_columns(tmp_path, monkeypatch):
    """旧行缺失 parent_task_id/depth 时应返回默认值。"""
    from backend.data import database as db_mod
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    # 手动插入一行不含新字段的记录（模拟旧数据）
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO orch_tasks (task_id, run_id, agent_id, goal, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("t_old", "r1", "researcher", "old_goal", "done"),
    )
    conn.commit()
    
    from backend.data.orch_task_repo import OrchTaskRepository
    repo = OrchTaskRepository()
    task = repo.get("t_old")
    
    assert task is not None
    assert task.parent_task_id is None
    assert task.depth == 0
```

- [x] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_task_repo.py::test_upsert_state_with_parent_and_depth -v
```

Expected: FAIL with TypeError: upsert_state() got an unexpected keyword argument 'parent_task_id'

- [x] **Step 3: 扩展 OrchTask dataclass**

```python
# backend/data/orch_task_repo.py

@dataclass
class OrchTask:
    task_id: str
    run_id: str
    agent_id: str
    goal: str
    status: str = "queued"
    retry_count: int = 0
    revision: int = 0
    error: Optional[str] = None
    output_preview: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    scratch_dir: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    used_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    parent_task_id: Optional[str] = None  # 新增
    depth: int = 0  # 新增
```

- [x] **Step 4: 扩展 upsert_state 方法**

```python
# backend/data/orch_task_repo.py，upsert_state 方法

def upsert_state(
    self,
    task_id: str,
    run_id: str,
    agent_id: str,
    goal: str,
    status: str,
    retry_count: int = 0,
    error: Optional[str] = None,
    output_preview: Optional[str] = None,
    blocked_by: Optional[List[str]] = None,
    scratch_dir: Optional[str] = None,
    started_at: Optional[int] = None,
    finished_at: Optional[int] = None,
    used_tokens: Optional[int] = None,
    duration_ms: Optional[int] = None,
    parent_task_id: Optional[str] = None,  # 新增
    depth: int = 0,  # 新增
) -> None:
    conn = self.db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO orch_tasks (
            task_id, run_id, agent_id, goal, status, retry_count,
            error, output_preview, blocked_by, scratch_dir,
            started_at, finished_at, used_tokens, duration_ms,
            parent_task_id, depth
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            status=excluded.status,
            retry_count=excluded.retry_count,
            error=excluded.error,
            output_preview=excluded.output_preview,
            started_at=excluded.started_at,
            finished_at=excluded.finished_at,
            used_tokens=excluded.used_tokens,
            duration_ms=excluded.duration_ms,
            parent_task_id=excluded.parent_task_id,
            depth=excluded.depth
        """,
        (
            task_id,
            run_id,
            agent_id,
            goal,
            status,
            retry_count,
            error,
            output_preview,
            json.dumps(blocked_by) if blocked_by is not None else None,
            scratch_dir,
            started_at,
            finished_at,
            used_tokens,
            duration_ms,
            parent_task_id,  # 新增
            depth,  # 新增
        ),
    )
    conn.commit()
```

- [x] **Step 5: 扩展 _row_to_task 方法**

```python
# backend/data/orch_task_repo.py，_row_to_task 方法

def _row_to_task(self, row: Any) -> OrchTask:
    blocked_by = json.loads(row["blocked_by"]) if row["blocked_by"] else None
    _cols = set(row.keys())
    return OrchTask(
        task_id=row["task_id"],
        run_id=row["run_id"],
        agent_id=row["agent_id"],
        goal=row["goal"],
        status=row["status"],
        retry_count=row["retry_count"],
        revision=row["revision"] if "revision" in _cols else 0,
        error=row["error"],
        output_preview=row["output_preview"],
        blocked_by=blocked_by,
        scratch_dir=row["scratch_dir"],
        used_tokens=row["used_tokens"] if "used_tokens" in _cols else None,
        duration_ms=row["duration_ms"] if "duration_ms" in _cols else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        parent_task_id=row["parent_task_id"] if "parent_task_id" in _cols else None,  # 新增
        depth=row["depth"] if "depth" in _cols else 0,  # 新增
    )
```

- [x] **Step 6: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch_task_repo.py::test_upsert_state_with_parent_and_depth backend/tests/unit/test_orch_task_repo.py::test_get_returns_defaults_for_missing_columns -v
```

Expected: PASS (both tests)

- [x] **Step 7: 提交**

```bash
git add backend/data/orch_task_repo.py backend/tests/unit/test_orch_task_repo.py
git commit -m "feat(data): OrchTaskRepository 支持 parent_task_id 和 depth"
```

---

### Task 6: add_task_to_plan 工具增强

**Files:**
- Modify: `backend/tools/replan_tool.py:120-180`
- Test: `backend/tests/unit/test_replan_tool.py`

**Interfaces:**
- Consumes: `ChatDispatcher.add_task_to_plan()`, `normalize_task_hierarchy()`
- Produces: `add_task_to_plan` 工具接受可选 `parent_task_id` 参数

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_replan_tool.py

def test_add_task_with_parent_task_id(tmp_path, monkeypatch):
    """add_task_to_plan 应支持 parent_task_id 参数。"""
    import asyncio
    import json
    from backend.data import database as db_mod
    from backend.orchestration.chat_dispatcher import ChatDispatcher
    from backend.tools.replan_tool import AddTaskToPlanTool
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    
    plan = json.dumps({
        "tasks": [
            {"task_id": "t1", "agent_id": "researcher", "goal": "g1"},
        ],
        "reasoning": "",
    })
    
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="r1")
    d.init_orch_run(session_id="s1", plan_json=plan)
    
    tool = AddTaskToPlanTool(d)
    result = tool.execute(
        task_id="t2",
        goal="g2",
        agent_id="writer",
        depends_on=[],
        parent_task_id="t1",
    )
    
    assert result["success"] is True
    assert "t2" in d._plan_by_id
    assert d._plan_by_id["t2"]["parent_task_id"] == "t1"
    assert d._plan_by_id["t2"]["depth"] == 1


def test_add_task_rejects_invalid_parent(tmp_path, monkeypatch):
    """add_task_to_plan 应拒绝不存在的 parent_task_id。"""
    import asyncio
    import json
    from backend.data import database as db_mod
    from backend.orchestration.chat_dispatcher import ChatDispatcher
    from backend.tools.replan_tool import AddTaskToPlanTool
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    
    plan = json.dumps({"tasks": [], "reasoning": ""})
    
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="r1")
    d.init_orch_run(session_id="s1", plan_json=plan)
    
    tool = AddTaskToPlanTool(d)
    result = tool.execute(
        task_id="t1",
        goal="g1",
        agent_id="researcher",
        depends_on=[],
        parent_task_id="t99",
    )
    
    assert result["success"] is False
    assert "parent" in result["error"].lower()
```

- [x] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_replan_tool.py::test_add_task_with_parent_task_id -v
```

Expected: FAIL with TypeError: execute() got an unexpected keyword argument 'parent_task_id'

- [x] **Step 3: 扩展 AddTaskToPlanTool execute 方法**

```python
# backend/tools/replan_tool.py，AddTaskToPlanTool.execute 方法

def execute(self, **kwargs: Any) -> ToolResult:
    """添加新任务到计划。"""
    task_id = kwargs.get("task_id")
    goal = kwargs.get("goal")
    agent_id = kwargs.get("agent_id")
    depends_on = kwargs.get("depends_on") or []
    parent_task_id = kwargs.get("parent_task_id")  # 新增
    
    if not task_id or not goal or not agent_id:
        return ToolResult(success=False, error="task_id, goal, agent_id are required")
    
    # 调用 dispatcher 的 add_task_to_plan（需要先在 Task 7 中实现）
    try:
        result = self._dispatcher.add_task_to_plan(
            task_id=task_id,
            goal=goal,
            agent_id=agent_id,
            depends_on=depends_on,
            parent_task_id=parent_task_id,  # 新增
        )
        return ToolResult(success=True, content=result)
    except Exception as e:
        return ToolResult(success=False, error=str(e))
```

- [x] **Step 4: 在 ChatDispatcher.add_task_to_plan 中接受 parent_task_id**

```python
# backend/orchestration/chat_dispatcher.py，add_task_to_plan 方法

def add_task_to_plan(
    self,
    task_id: str,
    goal: str,
    agent_id: str,
    depends_on: Optional[List[str]] = None,
    parent_task_id: Optional[str] = None,  # 新增
) -> Dict[str, Any]:
    """添加新任务到计划。"""
    from backend.orchestration.plan_hierarchy import normalize_task_hierarchy, HierarchyError
    
    depends_on = depends_on or []
    
    # 构建新任务
    new_task = {
        "task_id": task_id,
        "goal": goal,
        "agent_id": agent_id,
        "depends_on": depends_on,
    }
    if parent_task_id is not None:
        new_task["parent_task_id"] = parent_task_id
    
    # 将新任务加入计划列表
    plan_list = list(self._plan_by_id.values())
    plan_list.append(new_task)
    
    # 规范化层级（校验父引用、环、深度）
    try:
        normalized_plan = normalize_task_hierarchy(plan_list)
    except HierarchyError as e:
        return {"success": False, "error": str(e)}
    
    # 更新内存计划
    self._plan_by_id = {task["task_id"]: task for task in normalized_plan}
    
    # 持久化到 plan_json
    plan_json = json.dumps({"tasks": normalized_plan, "reasoning": ""})
    run = self._orch_run_repo.get(self.run_id)
    if run:
        run.plan_json = plan_json
        self._orch_run_repo.upsert(run)
    
    return {"success": True, "task_id": task_id}
```

- [x] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_replan_tool.py::test_add_task_with_parent_task_id backend/tests/unit/test_replan_tool.py::test_add_task_rejects_invalid_parent -v
```

Expected: PASS (both tests)

- [x] **Step 6: 提交**

```bash
git add backend/tools/replan_tool.py backend/orchestration/chat_dispatcher.py backend/tests/unit/test_replan_tool.py
git commit -m "feat(orchestration): add_task_to_plan 支持 parent_task_id"
```

---

### Task 7: Planner 集成层级规范化

**Files:**
- Modify: `backend/orchestration/planner.py:150-200`
- Test: `backend/tests/unit/test_planner_hierarchy.py`

**Interfaces:**
- Consumes: `normalize_task_hierarchy()`, `TaskPlanItem[]`
- Produces: Planner 输出规范化后的计划（带 `depth`）

- [x] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_planner_hierarchy.py

import pytest
from backend.orchestration.planner import Planner
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry


class MockLLMClient:
    def __init__(self, response: str):
        self.response = response
    
    async def complete(self, prompt: str) -> str:
        return self.response


@pytest.mark.asyncio
async def test_planner_normalizes_hierarchy(tmp_path, monkeypatch):
    """Planner 应调用 normalize_task_hierarchy 并返回带 depth 的计划。"""
    from backend.data import database as db_mod
    
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    # Mock LLM 返回带 parent_task_id 的计划
    llm_response = """
    {
        "tasks": [
            {"task_id": "t1", "agent_id": "researcher", "goal": "research"},
            {"task_id": "t2", "agent_id": "writer", "goal": "write", "parent_task_id": "t1"}
        ],
        "reasoning": "test"
    }
    """
    
    planner = Planner(
        task_registry=TaskRegistry(),
        team_registry=TeamRegistry(),
        llm_client=MockLLMClient(llm_response),
    )
    
    plan = await planner.decompose_request("test request")
    
    assert plan is not None
    assert len(plan.tasks) == 2
    # 验证 depth 已规范化
    task_map = {t.task_id: t for t in plan.tasks}
    assert task_map["t1"].depth == 0
    assert task_map["t2"].depth == 1
```

- [x] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_planner_hierarchy.py::test_planner_normalizes_hierarchy -v
```

Expected: FAIL with AttributeError: 'Task' object has no attribute 'depth'

- [x] **Step 3: 扩展 Task dataclass**

```python
# backend/orchestration/models.py，Task dataclass

@dataclass
class Task:
    task_id: str
    name: str
    description: str
    task_type: str = "general"
    status: TaskStatus = TaskStatus.CREATED
    priority: int = 0
    executor_type: str = "agent"
    parameters: Dict[str, Any] = field(default_factory=dict)
    packet: Optional["TaskPacket"] = None
    blocks: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    result: Optional[Any] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    team_id: Optional[str] = None
    parent_task_id: Optional[str] = None  # 新增
    depth: int = 0  # 新增
```

- [x] **Step 4: 在 Planner.decompose_request 中调用规范化器**

```python
# backend/orchestration/planner.py，decompose_request 方法

async def decompose_request(self, request: str) -> Optional[Plan]:
    """使用 LLM 将请求分解为任务计划。"""
    from backend.orchestration.plan_hierarchy import normalize_task_hierarchy, HierarchyError
    
    # ... 现有 LLM 调用逻辑 ...
    
    # 假设 raw_tasks 是从 LLM 解析出的任务列表
    # 规范化层级
    try:
        normalized_tasks = normalize_task_hierarchy(raw_tasks)
    except HierarchyError as e:
        logger.warning(f"Task hierarchy normalization failed: {e}")
        # fail-open: 降级为平铺计划
        normalized_tasks = raw_tasks
    
    # 构建 Task 对象
    tasks = []
    for task_dict in normalized_tasks:
        task = Task(
            task_id=task_dict["task_id"],
            name=task_dict.get("name", task_dict["goal"]),
            description=task_dict.get("description", task_dict["goal"]),
            task_type=task_dict.get("task_type", "general"),
            parameters={"agent_hint": task_dict.get("agent_id")},
            blocked_by=task_dict.get("blocked_by", []),
            parent_task_id=task_dict.get("parent_task_id"),  # 新增
            depth=task_dict.get("depth", 0),  # 新增
        )
        tasks.append(task)
    
    # ... 返回 Plan ...
```

- [x] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_planner_hierarchy.py::test_planner_normalizes_hierarchy -v
```

Expected: PASS

- [x] **Step 6: 提交**

```bash
git add backend/orchestration/models.py backend/orchestration/planner.py backend/tests/unit/test_planner_hierarchy.py
git commit -m "feat(orchestration): Planner 集成层级规范化"
```

---

### Task 8: 前端树形渲染

**Files:**
- Modify: `src/widgets/chat/progress/TaskTreeSection.tsx:1-200`
- Create: `src/widgets/chat/progress/TaskTreeNode.tsx`
- Test: `src/widgets/chat/__tests__/TaskTreeHierarchy.test.tsx`

**Interfaces:**
- Consumes: `TaskPlanItem[]`（带 `parent_task_id` 和 `depth`）
- Produces: 树形任务视图（支持折叠/展开）

- [x] **Step 1: 写失败测试**

```typescript
// src/widgets/chat/__tests__/TaskTreeHierarchy.test.tsx

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskTreeSection } from "../progress/TaskTreeSection";
import type { TaskBoard } from "../../../features/send-message/useChat";

describe("TaskTreeSection with hierarchy", () => {
  it("renders tasks as tree with parent-child relationships", () => {
    const board: TaskBoard = {
      runId: "r1",
      plan: [
        { task_id: "t1", agent_id: "researcher", goal: "Research" },
        { task_id: "t2", agent_id: "writer", goal: "Write", parent_task_id: "t1", depth: 1 },
        { task_id: "t3", agent_id: "editor", goal: "Edit", parent_task_id: "t1", depth: 1 },
      ],
      statuses: {},
      progress: { total: 3, done: 0, running: 0, queued: 3, failed: 0, cancelled: 0 },
    };
    
    render(<TaskTreeSection board={board} />);
    
    // t1 应为根节点，无缩进
    const t1 = screen.getByText("Research");
    expect(t1.closest("[data-depth='0']")).toBeTruthy();
    
    // t2 和 t3 应为子节点，有一级缩进
    const t2 = screen.getByText("Write");
    expect(t2.closest("[data-depth='1']")).toBeTruthy();
    
    const t3 = screen.getByText("Edit");
    expect(t3.closest("[data-depth='1']")).toBeTruthy();
  });

  it("supports collapse and expand for parent tasks", async () => {
    const user = userEvent.setup();
    const board: TaskBoard = {
      runId: "r1",
      plan: [
        { task_id: "t1", agent_id: "researcher", goal: "Research" },
        { task_id: "t2", agent_id: "writer", goal: "Write", parent_task_id: "t1", depth: 1 },
      ],
      statuses: {},
      progress: { total: 2, done: 0, running: 0, queued: 2, failed: 0, cancelled: 0 },
    };
    
    render(<TaskTreeSection board={board} />);
    
    // 默认展开
    expect(screen.getByText("Write")).toBeVisible();
    
    // 点击折叠按钮
    const collapseButton = screen.getByLabelText("Collapse Research");
    await user.click(collapseButton);
    
    // 子任务应隐藏
    expect(screen.queryByText("Write")).not.toBeVisible();
  });

  it("renders legacy plans without hierarchy as flat list", () => {
    const board: TaskBoard = {
      runId: "r1",
      plan: [
        { task_id: "t1", agent_id: "researcher", goal: "Research" },
        { task_id: "t2", agent_id: "writer", goal: "Write" },
      ],
      statuses: {},
      progress: { total: 2, done: 0, running: 0, queued: 2, failed: 0, cancelled: 0 },
    };
    
    render(<TaskTreeSection board={board} />);
    
    // 两个任务都应为根节点
    const t1 = screen.getByText("Research");
    const t2 = screen.getByText("Write");
    expect(t1.closest("[data-depth='0']")).toBeTruthy();
    expect(t2.closest("[data-depth='0']")).toBeTruthy();
  });

  it("handles missing parent by treating task as root", () => {
    const board: TaskBoard = {
      runId: "r1",
      plan: [
        { task_id: "t1", agent_id: "researcher", goal: "Research" },
        { task_id: "t2", agent_id: "writer", goal: "Write", parent_task_id: "t99", depth: 1 },
      ],
      statuses: {},
      progress: { total: 2, done: 0, running: 0, queued: 2, failed: 0, cancelled: 0 },
    };
    
    render(<TaskTreeSection board={board} />);
    
    // t2 的父不存在，应降级为根节点
    const t2 = screen.getByText("Write");
    expect(t2.closest("[data-depth='0']")).toBeTruthy();
  });
});
```

- [x] **Step 2: 运行测试验证失败**

```bash
npm run test:run -- src/widgets/chat/__tests__/TaskTreeHierarchy.test.tsx
```

Expected: FAIL with TypeScript errors or test failures

- [x] **Step 3: 实现 TaskTreeNode 组件**

```typescript
// src/widgets/chat/progress/TaskTreeNode.tsx

import { useState } from "react";
import type { TaskPlanItem, TaskStatusValue } from "../../../shared/api/types";

interface TaskTreeNodeProps {
  task: TaskPlanItem;
  status?: { status: TaskStatusValue; [key: string]: any };
  children?: TaskTreeNodeProps[];
  depth: number;
}

export function TaskTreeNode({ task, status, children = [], depth }: TaskTreeNodeProps) {
  const [collapsed, setCollapsed] = useState(false);
  const hasChildren = children.length > 0;
  
  return (
    <div data-depth={depth} style={{ marginLeft: depth * 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {hasChildren && (
          <button
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? `Expand ${task.goal}` : `Collapse ${task.goal}`}
            style={{ cursor: "pointer", background: "none", border: "none" }}
          >
            {collapsed ? "▶" : "▼"}
          </button>
        )}
        <span>{task.agent_id}</span>
        <span>{task.goal}</span>
        {status && <span>({status.status})</span>}
      </div>
      
      {!collapsed && hasChildren && (
        <div>
          {children.map((child) => (
            <TaskTreeNode key={child.task.task_id} {...child} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [x] **Step 4: 重构 TaskTreeSection 使用树形结构**

```typescript
// src/widgets/chat/progress/TaskTreeSection.tsx

import { useMemo } from "react";
import type { TaskBoard } from "../../../features/send-message/useChat";
import type { TaskPlanItem } from "../../../shared/api/types";
import { TaskTreeNode } from "./TaskTreeNode";

interface TaskTreeSectionProps {
  board: TaskBoard;
}

interface TreeNode {
  task: TaskPlanItem;
  children: TreeNode[];
  depth: number;
}

function buildTree(plan: TaskPlanItem[]): TreeNode[] {
  // 构建 task_id 到节点的映射
  const nodeMap = new Map<string, TreeNode>();
  for (const item of plan) {
    nodeMap.set(item.task_id, {
      task: item,
      children: [],
      depth: item.depth ?? 0,
    });
  }
  
  // 构建树结构
  const roots: TreeNode[] = [];
  for (const item of plan) {
    const node = nodeMap.get(item.task_id)!;
    const parentId = item.parent_task_id;
    
    if (parentId && nodeMap.has(parentId)) {
      // 找到父节点，加入其 children
      nodeMap.get(parentId)!.children.push(node);
    } else {
      // 无父节点或父节点不存在，作为根节点
      node.depth = 0; // 降级为根
      roots.push(node);
    }
  }
  
  return roots;
}

export function TaskTreeSection({ board }: TaskTreeSectionProps) {
  const treeNodes = useMemo(() => buildTree(board.plan), [board.plan]);
  
  return (
    <div data-testid="task-tree">
      {treeNodes.map((node) => (
        <TaskTreeNode
          key={node.task.task_id}
          task={node.task}
          status={board.statuses[node.task.task_id]}
          children={node.children}
          depth={node.depth}
        />
      ))}
    </div>
  );
}
```

- [x] **Step 5: 运行测试验证通过**

```bash
npm run test:run -- src/widgets/chat/__tests__/TaskTreeHierarchy.test.tsx
```

Expected: PASS (all 4 tests)

- [x] **Step 6: 提交**

```bash
git add src/widgets/chat/progress/TaskTreeNode.tsx src/widgets/chat/progress/TaskTreeSection.tsx src/widgets/chat/__tests__/TaskTreeHierarchy.test.tsx
git commit -m "feat(ui): 前端任务树形渲染"
```

---

### Task 9: 集成测试和回归

**Files:**
- Create: `backend/tests/integration/test_task_hierarchy_integration.py`
- Test: 运行所有编排和前端测试

**Interfaces:**
- Consumes: 所有已实现的功能
- Produces: 端到端验证层级化功能

- [x] **Step 1: 写集成测试**

```python
# backend/tests/integration/test_task_hierarchy_integration.py

import asyncio
import json

import pytest

from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.plan_hierarchy import normalize_task_hierarchy
from backend.orchestration.planner import Planner
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry


@pytest.mark.asyncio
async def test_full_hierarchy_flow(tmp_path, monkeypatch):
    """端到端验证：Planner 生成层级 → dispatcher 派发 → orch_tasks 持久化。"""
    # 设置数据库
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    # 创建 dispatcher
    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="r1",
    )
    dispatcher.init_orch_run(session_id="s1", plan_json="{}")
    
    # 模拟计划（带层级）
    plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "Research"},
        {"task_id": "t2", "agent_id": "writer", "goal": "Write", "parent_task_id": "t1"},
        {"task_id": "t3", "agent_id": "editor", "goal": "Edit", "parent_task_id": "t2"},
    ]
    
    # 规范化层级
    normalized = normalize_task_hierarchy(plan)
    
    # 验证 depth
    assert normalized[0]["depth"] == 0
    assert normalized[1]["depth"] == 1
    assert normalized[2]["depth"] == 2
    
    # 更新计划
    plan_json = json.dumps({"tasks": normalized, "reasoning": ""})
    run = dispatcher._orch_run_repo.get("r1")
    run.plan_json = plan_json
    dispatcher._orch_run_repo.upsert(run)
    
    # 加载计划
    dispatcher._ensure_plan_loaded()
    
    # 验证 dispatcher 读取了层级字段
    assert dispatcher._plan_by_id["t2"]["parent_task_id"] == "t1"
    assert dispatcher._plan_by_id["t3"]["depth"] == 2
    
    # 模拟派发 t2（写入 orch_tasks）
    from backend.orchestration.chat_dispatcher import ChatTaskState
    
    state = ChatTaskState(
        task_id="t2",
        agent_id="writer",
        goal="Write",
        parent_task_id="t1",
    )
    state.status = "done"
    state.started_at = 1000.0
    state.finished_at = 2000.0
    
    dispatcher._persist_task_state(state)
    
    # 验证 orch_tasks 持久化了层级字段
    task = dispatcher._orch_task_repo.get("t2")
    assert task is not None
    assert task.parent_task_id == "t1"
    assert task.depth == 1


def test_add_task_with_hierarchy_integration(tmp_path, monkeypatch):
    """集成测试：动态添加带层级的新任务。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    
    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="r1",
    )
    
    initial_plan = json.dumps({
        "tasks": [
            {"task_id": "t1", "agent_id": "researcher", "goal": "Research"},
        ],
        "reasoning": "",
    })
    dispatcher.init_orch_run(session_id="s1", plan_json=initial_plan)
    
    # 动态添加子任务
    result = dispatcher.add_task_to_plan(
        task_id="t2",
        goal="Write",
        agent_id="writer",
        depends_on=[],
        parent_task_id="t1",
    )
    
    assert result["success"] is True
    
    # 验证计划已更新
    assert "t2" in dispatcher._plan_by_id
    assert dispatcher._plan_by_id["t2"]["parent_task_id"] == "t1"
    assert dispatcher._plan_by_id["t2"]["depth"] == 1
    
    # 验证 plan_json 已持久化
    run = dispatcher._orch_run_repo.get("r1")
    plan_data = json.loads(run.plan_json)
    task_map = {t["task_id"]: t for t in plan_data["tasks"]}
    assert task_map["t2"]["parent_task_id"] == "t1"
```

- [x] **Step 2: 运行集成测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_task_hierarchy_integration.py -v
```

Expected: PASS (both tests)

- [x] **Step 3: 运行所有编排后端测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_orch*.py backend/tests/unit/test_chat_dispatcher*.py backend/tests/unit/test_planner*.py backend/tests/unit/test_plan_hierarchy.py backend/tests/unit/test_replan_tool.py -v --tb=short
```

Expected: All tests PASS

- [x] **Step 4: 运行所有前端测试**

```bash
npm run test:run -- --testPathPattern="TaskTree|types"
```

Expected: All tests PASS

- [x] **Step 5: 运行 TypeScript 类型检查**

```bash
npx tsc --noEmit
```

Expected: No errors

- [x] **Step 6: 运行 Ruff 检查**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/
```

Expected: No errors

- [x] **Step 7: 提交集成测试**

```bash
git add backend/tests/integration/test_task_hierarchy_integration.py
git commit -m "test(orchestration): 添加任务层级化集成测试"
```

- [x] **Step 8: 创建 PR**

```bash
git push origin HEAD
gh pr create --title "feat: 任务层级化支持" --body "实现增量任务层级模型，支持 parent_task_id 和 depth 字段..."
```

---

## 实施总结

本计划共 9 个任务，按照 TDD 方式逐步实施：

1. 数据库迁移（添加列）
2. 类型扩展（前后端共享）
3. 计划规范化器（校验逻辑）
4. ChatTaskState 和事件透传
5. OrchTaskRepository 读写新字段
6. add_task_to_plan 工具增强
7. Planner 集成层级规范化
8. 前端树形渲染
9. 集成测试和回归

每个任务都有独立的测试验证，确保增量交付和快速反馈。
