# Skill Curator 生命周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 为每个技能计算生命周期三态 `active / stale / archived`（经 `GET /api/v1/skills` 透出、前端 SkillCard badge 展示），并提供可逆的软归档动作（`POST /api/v1/skills/{name}/archive`）。归档技能从 `auto_activate` 与 slash 候选排除。分类是 `last_used_at` 的纯函数 + 读取时即时计算，**无后台 worker**；归档状态持久化到 DB + adapter 内存热缓存。

**Architecture:** 新增 `backend/skills/lifecycle.py`（`classify_lifecycle` 纯函数 + `SkillLifecycleStore` 薄存储 + 全局单例，仿 `backend/skills/usage.py`）；`database.py` 新增 `skill_lifecycle` 表。`InprocSkillAdapter` 增加内存 `_archived: Set[str]`（启动 hydrate + 写时双写 DB）、`set_archived/is_archived/lifecycle_map`，并在 `list_skills_extended` 注入 `lifecycle` 字段、在 `auto_activate`/slash 排除归档技能。路由层加 `archive` 端点（仿 toggle）。前端 `Skill` 类型 + `skillsApi.archive` + Electron `archive_skill` IPC + `SkillCard` badge/按钮 + `Skills` handler。

**Tech Stack:** Python 3.11 + SQLite（裸 SQL，仿 SkillUsageStore）+ FastAPI（pydantic `StrictBool`）；前端 React + TypeScript + Tailwind + vitest/RTL。测试不用 freezegun，相对时间戳 + 真实临时 SQLite（沿用 PR #271 / wake_scheduler 范式）。

**Spec:** `docs/superpowers/specs/2026-08-02-skill-curator-lifecycle-design.md`

## Global Constraints

- **无后台 worker**：active/stale 读取时即时算（`classify_lifecycle` 纯函数对 `now` 比较 `last_used_at`），不新增 lifespan/start/stop。brainstorming 已对比三方案定 A（spec §6.1）。
- **best-effort 契约**：`SkillLifecycleStore` 所有 DB 操作失败只 `logger.warning`，绝不外抛；策展状态不得影响技能主流程（与 `SkillUsageStore` 同契约）。
- **DB 真相 + 内存热缓存**：`skill_lifecycle` 表是持久真相（重启不丢）；`adapter._archived: Set` 是热缓存，`auto_activate`（每轮对话）/ slash / list 读它零 DB。启动 `_hydrate_archived_from_db` 回填，写时双写。
- **归档 = 软标记，可逆，文件不动**：不移动 SKILL.md、不写回 frontmatter、不物理删除。区别于 `delete`。
- **archived 与 enabled 正交**：可用性 = `enabled ∧ ¬archived`；`unarchive` 不改动 `enabled`。
- **builtin 可归档**（非破坏可逆，区别于 delete 对 builtin 的硬保护）。
- **不复用死表 `skills`**（database.py:280-300，无读写）；`success_count` 不入分类（恒等于 use_count，无真实失败率数据）。
- **六边形纯净**：`backend/skills/lifecycle.py` 不 import FastAPI（仅惰性 import `backend.data.database`，同 usage.py）。
- **前端文案硬编码中文**（Skills 页未接 i18n，保持一致）。
- **Python 环境**：所有 pytest 用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`（conda `sage-backend`，Py3.11）。前端 `cd /home/fz/project/sage && npm run test`。

---

### Task 1: `skill_lifecycle` 表 + `SkillLifecycleStore` + `classify_lifecycle` + 单测

**Files:**
- Create: `backend/skills/lifecycle.py`
- Modify: `backend/data/database.py`（`init_db()`，skill_usage 索引之后 ~line 317）
- Modify: `backend/tests/conftest.py`（`setup_test_db` 加 `reset_lifecycle_store`）
- Test: `backend/tests/unit/test_skill_lifecycle.py`

**Interfaces:**
- Produces（供 Task 2/3/4 依赖）:
  - `classify_lifecycle(last_used_at_ms: Optional[int], archived: bool, now_ms: int, stale_threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS) -> str` — 纯函数，返回 `"active"/"stale"/"archived"`
  - `DEFAULT_STALE_THRESHOLD_MS`（30 天）、`LIFECYCLE_ACTIVE/STALE/ARCHIVED` 常量
  - `SkillLifecycleStore.set_archived(name, archived: bool) -> None`（UPSERT，best-effort）
  - `SkillLifecycleStore.get_archived_names() -> Set[str]`（best-effort，失败空集）
  - `SkillLifecycleStore.is_archived(name) -> bool`
  - `get_lifecycle_store(db=None) -> SkillLifecycleStore`、`reset_lifecycle_store() -> None`

- [x] **Step 1: 建表 — `database.py` `init_db()` 追加（line 317 skill_usage 索引之后，preferences 表之前）**

```python
        # 技能生命周期（curator）表：归档软标记（spec 2026-08-02-skill-curator-lifecycle）。
        # 独立于 skill_usage —— 从未使用的技能无 usage 行但同样可归档，需以 name
        # 独立寻址。archived_at 记归档时刻（ms epoch），未归档为 NULL。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_lifecycle (
                name TEXT PRIMARY KEY,
                archived INTEGER DEFAULT 0,
                archived_at INTEGER
            )
        """)
```

- [x] **Step 2: 写失败测试 `backend/tests/unit/test_skill_lifecycle.py`**

```python
"""Unit tests for skill lifecycle — classify_lifecycle 纯函数 + SkillLifecycleStore。

不用 freezegun：classify 用注入的 now_ms + 相对时间戳；store 用 autouse 临时 SQLite。
"""

from unittest.mock import Mock

from backend.skills.lifecycle import (
    DEFAULT_STALE_THRESHOLD_MS,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_STALE,
    SkillLifecycleStore,
    classify_lifecycle,
    get_lifecycle_store,
    reset_lifecycle_store,
)

_DAY = 24 * 60 * 60 * 1000
_NOW = 100 * _DAY  # 任意固定"当前"基准


# ---------- classify_lifecycle（纯函数） ---------- #


def test_archived_takes_priority():
    """archived=True 优先于 active/stale（即使最近用过）。"""
    assert classify_lifecycle(_NOW, True, _NOW) == LIFECYCLE_ARCHIVED


def test_never_used_is_stale():
    """last_used_at=None（usage 表无行）→ stale。"""
    assert classify_lifecycle(None, False, _NOW) == LIFECYCLE_STALE


def test_recent_use_is_active():
    """阈值内用过 → active。"""
    assert classify_lifecycle(_NOW - 1 * _DAY, False, _NOW) == LIFECYCLE_ACTIVE


def test_old_use_is_stale():
    """超阈值 → stale。"""
    assert classify_lifecycle(_NOW - 60 * _DAY, False, _NOW) == LIFECYCLE_STALE


def test_boundary_at_threshold_is_active():
    """恰在阈值边界（距今 == 阈值）→ active（<= 语义）。"""
    assert classify_lifecycle(_NOW - DEFAULT_STALE_THRESHOLD_MS, False, _NOW) == LIFECYCLE_ACTIVE
    assert classify_lifecycle(_NOW - DEFAULT_STALE_THRESHOLD_MS - 1, False, _NOW) == LIFECYCLE_STALE


def test_custom_threshold():
    """自定义阈值生效（7 天）。"""
    seven_days = 7 * _DAY
    assert classify_lifecycle(_NOW - 3 * _DAY, False, _NOW, seven_days) == LIFECYCLE_ACTIVE
    assert classify_lifecycle(_NOW - 10 * _DAY, False, _NOW, seven_days) == LIFECYCLE_STALE


# ---------- SkillLifecycleStore（真实临时 SQLite，autouse setup_test_db） ---------- #


def test_set_archived_roundtrip():
    store = get_lifecycle_store()
    store.set_archived("search", True)
    assert store.is_archived("search")
    assert "search" in store.get_archived_names()


def test_unarchive_removes():
    store = get_lifecycle_store()
    store.set_archived("search", True)
    store.set_archived("search", False)
    assert not store.is_archived("search")
    assert "search" not in store.get_archived_names()


def test_persists_across_store_instances():
    """DB 是持久真相：新 store 实例（同库）仍读到归档态。"""
    get_lifecycle_store().set_archived("coder", True)
    reset_lifecycle_store()
    assert "coder" in get_lifecycle_store().get_archived_names()


def test_is_archived_unknown_name_false():
    assert not get_lifecycle_store().is_archived("never-archived")


def test_get_archived_names_best_effort_on_db_error():
    """DB 异常 → 返回空集，不外抛。"""
    bad = SkillLifecycleStore(db=Mock(get_connection=Mock(side_effect=RuntimeError("boom"))))
    assert bad.get_archived_names() == set()
    assert bad.is_archived("x") is False
```

- [x] **Step 3: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_lifecycle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.skills.lifecycle'`

- [x] **Step 4: 写最小实现 `backend/skills/lifecycle.py`**

```python
"""技能生命周期（curator）— active/stale/archived 三态分类 + 归档持久化。

设计要点（spec 2026-08-02-skill-curator-lifecycle）
----------------------------------------------------

- **读取时即时计算**：active/stale 是 ``last_used_at`` 与当前时间的纯函数比较，
  不落库、无后台 worker。archived 是用户显式软标记，持久化到 ``skill_lifecycle``
  表（重启不丢）。
- **best-effort**：DB 读写失败只 warning，绝不外抛 —— 策展状态是辅助数据，
  不得影响技能主流程（与 ``SkillUsageStore`` 同契约）。
- **六边形纯净**：不依赖 FastAPI，仅惰性 import ``backend.data.database``。
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Set

logger = logging.getLogger(__name__)

# active/stale 分界阈值（默认 30 天）。v1 固定常量；settings 可配留待后续。
DEFAULT_STALE_THRESHOLD_MS = 30 * 24 * 60 * 60 * 1000

# 生命周期三态
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_STALE = "stale"
LIFECYCLE_ARCHIVED = "archived"


def _now_ms() -> int:
    """当前时间（ms epoch）。"""
    return int(time.time() * 1000)


def classify_lifecycle(
    last_used_at_ms: Optional[int],
    archived: bool,
    now_ms: int,
    stale_threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS,
) -> str:
    """计算技能生命周期态（纯函数，``now_ms`` 由调用方注入便于测试）。

    优先级 ``archived > active/stale``：

    - ``archived=True`` → ``"archived"``
    - ``last_used_at_ms is None``（从未使用，usage 表无行）→ ``"stale"``
    - 距今 ``<= stale_threshold_ms`` → ``"active"``
    - 距今 ``> stale_threshold_ms`` → ``"stale"``
    """
    if archived:
        return LIFECYCLE_ARCHIVED
    if last_used_at_ms is None:
        return LIFECYCLE_STALE
    if (now_ms - last_used_at_ms) <= stale_threshold_ms:
        return LIFECYCLE_ACTIVE
    return LIFECYCLE_STALE


class SkillLifecycleStore:
    """技能策展状态存储（SQLite ``skill_lifecycle`` 表）。best-effort。

    Example:
        >>> store = get_lifecycle_store()
        >>> store.set_archived("travel", True)
        >>> store.is_archived("travel")
        True
        >>> store.get_archived_names()
        {"travel"}
    """

    def __init__(self, db=None) -> None:
        """初始化策展状态存储。

        Args:
            db: Database 实例；缺省用全局 ``get_database()``。
        """
        self.db = db

    def _conn(self):
        """惰性绑定全局 Database 并返回连接（仿 SkillUsageStore）。"""
        if self.db is None:
            from backend.data.database import get_database

            self.db = get_database()
        return self.db.get_connection()

    def set_archived(self, name: str, archived: bool) -> None:
        """UPSERT 归档状态（归档写 ``archived_at``，取消置 NULL）。best-effort。"""
        if not name:
            return
        try:
            conn = self._conn()
            archived_at = _now_ms() if archived else None
            conn.execute(
                "INSERT INTO skill_lifecycle (name, archived, archived_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "archived = excluded.archived, archived_at = excluded.archived_at",
                (name, 1 if archived else 0, archived_at),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle persist failed for {name!r}: {exc}")

    def get_archived_names(self) -> Set[str]:
        """所有已归档技能名集合（批量左连接用，一次查询）。best-effort，失败空集。"""
        try:
            rows = self._conn().execute(
                "SELECT name FROM skill_lifecycle WHERE archived = 1"
            ).fetchall()
            return {row["name"] for row in rows}
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle read failed: {exc}")
            return set()

    def is_archived(self, name: str) -> bool:
        """单个技能是否已归档。best-effort，失败 False。"""
        try:
            row = self._conn().execute(
                "SELECT archived FROM skill_lifecycle WHERE name = ?", (name,)
            ).fetchone()
            return bool(row is not None and row["archived"])
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.warning(f"Skill lifecycle read failed for {name!r}: {exc}")
            return False


# 全局单例（与 get_usage_store 同模式）
_lifecycle_store: Optional[SkillLifecycleStore] = None


def get_lifecycle_store(db=None) -> SkillLifecycleStore:
    """获取全局 SkillLifecycleStore 单例。"""
    global _lifecycle_store
    if _lifecycle_store is None:
        _lifecycle_store = SkillLifecycleStore(db)
    return _lifecycle_store


def reset_lifecycle_store() -> None:
    """重置 SkillLifecycleStore 单例（仅用于测试）。"""
    global _lifecycle_store
    _lifecycle_store = None
```

- [x] **Step 5: conftest 重置单例（测试隔离）**

`backend/tests/conftest.py`，`setup_test_db` 内 `from backend.skills.usage import reset_usage_store`（~line 45）旁追加 import，并在 `reset_usage_store()`（~line 51）之后追加调用：

```python
    # SkillUsageStore 单例同理
    from backend.skills.usage import reset_usage_store

    # SkillLifecycleStore 单例同理（技能归档策展状态）
    from backend.skills.lifecycle import reset_lifecycle_store
    ...
    reset_usage_store()
    reset_lifecycle_store()
```

- [x] **Step 6: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_lifecycle.py -v`
Expected: PASS — 11/11 绿

- [x] **Step 7: Commit**

```bash
git add backend/skills/lifecycle.py backend/data/database.py backend/tests/unit/test_skill_lifecycle.py backend/tests/conftest.py
git commit -m "feat: 技能生命周期 classify_lifecycle + SkillLifecycleStore（软归档持久化）"
```

---

### Task 2: Adapter 集成 — 内存 `_archived` + hydrate + set/is_archived + lifecycle_map + list 字段

**Files:**
- Modify: `backend/adapters/out/skill/inproc.py`（top import 加 `import time` + `Set`；`__init__` 加 `_archived` + hydrate；新增方法；`list_skills_extended` 注入 lifecycle）
- Test: `backend/tests/unit/test_inproc_lifecycle.py`

**Interfaces:**
- Consumes: `classify_lifecycle` / `get_lifecycle_store`（Task 1）
- Produces:
  - `InprocSkillAdapter._archived: Set[str]`（`__init__` hydrate）
  - `set_archived(name, archived) -> bool`（False=技能不存在；DB+内存双写）
  - `is_archived(name) -> bool`（内存 O(1)）
  - `lifecycle_map() -> Dict[str, str]`（批量 name→lifecycle）
  - `list_skills_extended()` 每项新增 `lifecycle` 字段

- [x] **Step 1: 写失败测试 `backend/tests/unit/test_inproc_lifecycle.py`**

```python
"""Unit tests for InprocSkillAdapter lifecycle integration（归档 + 分类）。

用 4 个 builtin（search/writer/coder/travel）+ autouse 临时 DB；
reset_skill_adapter 保证 adapter 单例隔离。
"""

import pytest

import backend.adapters.out.skill.inproc as inproc_mod
from backend.adapters.out.skill.inproc import get_singleton


@pytest.fixture()
def adapter(reset_skill_adapter):
    return get_singleton()


def test_set_archived_and_is_archived(adapter):
    assert not adapter.is_archived("search")
    assert adapter.set_archived("search", True) is True
    assert adapter.is_archived("search")


def test_unarchive(adapter):
    adapter.set_archived("search", True)
    assert adapter.set_archived("search", False) is True
    assert not adapter.is_archived("search")


def test_set_archived_unknown_skill_returns_false(adapter):
    assert adapter.set_archived("no-such-skill", True) is False


def test_archive_persists_across_adapter_instances(adapter):
    """DB 真相：新 adapter 实例 hydrate 后仍归档（重启不丢）。"""
    adapter.set_archived("coder", True)
    inproc_mod._skill_adapter_singleton = None  # 强制重建
    assert get_singleton().is_archived("coder")


def test_lifecycle_map_active_stale_archived(adapter):
    adapter.bump_usage("search")  # 刚用 → active
    adapter.set_archived("coder", True)  # → archived
    m = adapter.lifecycle_map()
    assert m["search"] == "active"
    assert m["coder"] == "archived"
    assert m["travel"] == "stale"  # 从未用 → stale
    assert m["writer"] == "stale"


def test_list_skills_extended_includes_lifecycle(adapter):
    adapter.bump_usage("search")
    adapter.set_archived("coder", True)
    ext = {e["name"]: e for e in adapter.list_skills_extended()}
    assert ext["search"]["lifecycle"] == "active"
    assert ext["coder"]["lifecycle"] == "archived"
    assert ext["travel"]["lifecycle"] == "stale"
```

- [x] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_inproc_lifecycle.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'is_archived'`

- [x] **Step 3: 实现 — top import 调整**

`inproc.py` line 24-26，`from __future__ import annotations` 之后、`from typing import` 之前加 `import time`；typing import 补 `Set`：

```python
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
```

- [x] **Step 4: `__init__` 加 `_archived` + hydrate（line 89 `self._hydrate_usage_from_db()` 之后）**

```python
        # 归档策展状态（spec 2026-08-02-skill-curator-lifecycle）：DB 为持久真相，
        # 内存 Set 为热缓存（auto_activate / slash / list 读它，零 DB）；
        # 启动从 skill_lifecycle 表回填（重启不丢）。
        self._archived: Set[str] = set()
        self._hydrate_archived_from_db()
```

- [x] **Step 5: 新增方法（`_hydrate_usage_from_db` 之后，A16 段之前 ~line 219）**

```python
    # ========== Skill 生命周期 (curator): active/stale/archived ==========

    def _hydrate_archived_from_db(self) -> None:
        """从 ``skill_lifecycle`` 表回填归档集合（best-effort，重启不丢）。

        仅收 registry 中真实存在的技能（仿 ``_hydrate_usage_from_db``）。
        """
        try:
            from backend.skills.lifecycle import get_lifecycle_store

            for name in get_lifecycle_store().get_archived_names():
                if name and self._registry.exists(name):
                    self._archived.add(name)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            import logging

            logging.getLogger(__name__).debug(f"技能归档状态回填跳过: {exc}")

    def is_archived(self, name: str) -> bool:
        """技能是否已归档（内存热缓存，O(1)）。"""
        return name in self._archived

    def set_archived(self, name: str, archived: bool) -> bool:
        """设置归档状态。返回 False 表示技能名不存在（路由层 → 404）。

        DB 持久真相 + 内存热缓存双写（仿 ``set_enabled``，但持久化到
        ``skill_lifecycle`` 表，重启不丢）。DB 写失败只 warning（best-effort），
        内存态仍更新以保证本次会话一致。
        """
        if not self._registry.exists(name):
            return False
        try:
            from backend.skills.lifecycle import get_lifecycle_store

            get_lifecycle_store().set_archived(name, archived)
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            import logging

            logging.getLogger(__name__).warning(
                f"Skill lifecycle persist failed for {name!r}: {exc}"
            )
        if archived:
            self._archived.add(name)
        else:
            self._archived.discard(name)
        return True

    def lifecycle_map(self) -> Dict[str, str]:
        """批量计算全量 name → lifecycle（active/stale/archived）。

        active/stale 读取时即时算（对 ``now`` 比较 ``skill_usage.last_used_at``），
        archived 取内存缓存。供 ``list_skills_extended`` 一次性调用（非热路径）。
        """
        from backend.skills.lifecycle import classify_lifecycle
        from backend.skills.usage import get_usage_store

        usage = {row["name"]: row for row in get_usage_store().get_all()}
        now_ms = int(time.time() * 1000)
        result: Dict[str, str] = {}
        for name in self._registry.list_names():
            last = (usage.get(name) or {}).get("last_used_at")
            result[name] = classify_lifecycle(last, name in self._archived, now_ms)
        return result
```

- [x] **Step 6: `list_skills_extended` 注入 lifecycle 字段**

`list_skills_extended`（~line 394）：在 `from backend.skills.skill_md.skill import SkillMdSkill`（~line 410）之后、`result: List[Dict[str, Any]] = []` 之前加 `lifecycles = self.lifecycle_map()`；在循环内 `result.append(item)`（~line 449）之前加：

```python
        lifecycles = self.lifecycle_map()
        result: List[Dict[str, Any]] = []
        for schema in self._registry.list():
            ...
            # 生命周期态（active/stale/archived）— builtin 与 skillmd 一律计算
            item["lifecycle"] = lifecycles.get(schema.name, "stale")
            result.append(item)
        return result
```

- [x] **Step 7: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_inproc_lifecycle.py backend/tests/unit/test_skill_lifecycle.py -v`
Expected: PASS — 全绿

- [x] **Step 8: Commit**

```bash
git add backend/adapters/out/skill/inproc.py backend/tests/unit/test_inproc_lifecycle.py
git commit -m "feat: adapter 归档状态 + lifecycle_map + list_skills_extended 注入 lifecycle"
```

---

### Task 3: `auto_activate` + slash registry 排除归档技能

**Files:**
- Modify: `backend/adapters/out/skill/inproc.py`（`auto_activate` 过滤 + `list_slash_commands` / `execute_command` + `_command_archived` helper）
- Test: `backend/tests/unit/test_inproc_lifecycle.py`（扩展排除用例）

**Interfaces:**
- Consumes: `is_archived`（Task 2）
- Produces: 归档技能不进 `auto_activate` 候选、不出现在 `list_slash_commands`、`execute_command` 对归档命令抛 `LookupError`（路由 → 404）

- [x] **Step 1: 写失败测试（追加到 `test_inproc_lifecycle.py`）**

> ⚠️ 实施时核对：auto_activate / slash 排除需 SKILL.md 技能（builtin 无 `when_to_use`、不进 slash registry）。复用/构造带 `when_to_use` 与 `dispatch.user_invocable` 的 `SkillMdSkill`（`backend.skills.skill_md.skill.SkillMdDocument` + `SkillMdSkill`，`DispatchMode` 字段见 `backend/skills/skill_md/frontmatter.py`），注入自定义 registry：`InprocSkillAdapter(registry=custom_registry)`。若仓库已有 auto_activate / slash 测试 fixture（grep `auto_activate` / `SlashCommandRegistry` 测试），优先复用。下方为意图骨架：

```python
def test_auto_activate_excludes_archived():
    """归档的 SKILL.md 技能不出现在 auto_activate 命中。"""
    # 构造一个 when_to_use 命中 "deploy" 的 SkillMdSkill 注册到 registry
    adapter = _adapter_with_skillmd("deploy-skill", when_to_use="when user wants to deploy")
    assert "deploy-skill" in adapter.auto_activate("please deploy now").names
    adapter.set_archived("deploy-skill", True)
    assert "deploy-skill" not in adapter.auto_activate("please deploy now").names


def test_slash_excludes_archived():
    """归档的 user_invocable 技能不出现在 list_slash_commands，execute 抛 LookupError。"""
    adapter = _adapter_with_skillmd("review", user_invocable=True, user_invocable_name="/review")
    assert "/review" in adapter.list_slash_commands()
    adapter.set_archived("review", True)
    assert "/review" not in adapter.list_slash_commands()
    with pytest.raises(LookupError):
        import asyncio
        asyncio.run(adapter.execute_command("/review"))
```

（`_adapter_with_skillmd` 是测试 helper：构造 SkillMdDocument + SkillMdSkill，register 进新 SkillRegistry，返回 `InprocSkillAdapter(registry=...)`；需 `reset_lifecycle_store` 隔离。实施时按实际 DispatchMode/SkillMdDocument 字段定稿。）

- [x] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_inproc_lifecycle.py -v -k "archived"`
Expected: FAIL — 归档技能仍出现在 auto_activate / slash

- [x] **Step 3: `auto_activate` 过滤（~line 257，`if not self.is_enabled(...): continue` 之后）**

```python
                if not self.is_enabled(schema.name):
                    continue
                # 归档技能不参与自动激活（spec：可用性 = enabled ∧ ¬archived）
                if self.is_archived(schema.name):
                    continue
                doc = skill._doc
```

- [x] **Step 4: slash 排除 — `_command_archived` helper + `list_slash_commands` / `execute_command`**

`list_slash_commands`（~line 315）替换为：

```python
    def list_slash_commands(self) -> List[str]:
        """列出所有已注册的 slash command (M10)，排除已归档技能。"""
        return [
            cmd
            for cmd in self._slash_registry.list_commands()
            if not self._command_archived(cmd)
        ]

    def _command_archived(self, command: str) -> bool:
        """slash command 对应的技能是否已归档。"""
        resolved = self._slash_registry.resolve(command)
        return resolved is not None and self.is_archived(resolved.name)
```

`execute_command`（~line 276）函数体开头（委托 `self._slash_registry.execute_command` 之前）加 guard：

```python
        # 归档技能的 slash command 不可用（路由层转 404 command_not_found）
        if self._command_archived(command):
            raise LookupError(f"slash command archived: {command!r}")
        result = await self._slash_registry.execute_command(
            command_name=command,
            args=tuple(args),
        )
```

- [x] **Step 5: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_inproc_lifecycle.py -v`
Expected: PASS — 含排除用例全绿

- [x] **Step 6: Commit**

```bash
git add backend/adapters/out/skill/inproc.py backend/tests/unit/test_inproc_lifecycle.py
git commit -m "feat: auto_activate + slash registry 排除归档技能"
```

---

### Task 4: API 端点 `POST /skills/{name}/archive` + 集成测试

**Files:**
- Modify: `backend/api/legacy_routes.py`（toggle 端点 ~line 928 之后新增）
- Test: `backend/tests/integration/test_skills_archive_api.py`

**Interfaces:**
- Consumes: `adapter.set_archived`（Task 2）；`_skill_to_dict` 自动透出 `lifecycle`（Task 2 已注入 ext）
- Produces: `POST /api/v1/skills/{name}/archive {archived: bool}` → 200 完整 skill dict / 404 skill_not_found

- [x] **Step 1: 写失败测试 `backend/tests/integration/test_skills_archive_api.py`**

```python
"""Integration tests for POST /api/v1/skills/{name}/archive（软归档端点）。"""

import pytest


@pytest.mark.asyncio()
async def test_archive_and_unarchive_builtin(client, reset_skill_adapter):
    # 归档 builtin（允许，非破坏可逆）
    r = await client.post("/api/v1/skills/search/archive", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["lifecycle"] == "archived"

    # GET /skills 透出 lifecycle
    listing = await client.get("/api/v1/skills")
    by_name = {s["name"]: s for s in listing.json()}
    assert by_name["search"]["lifecycle"] == "archived"

    # 取消归档 → lifecycle 回到非 archived（search 从未 bump → stale）
    r2 = await client.post("/api/v1/skills/search/archive", json={"archived": False})
    assert r2.status_code == 200
    assert r2.json()["lifecycle"] != "archived"


@pytest.mark.asyncio()
async def test_archive_unknown_skill_404(client, reset_skill_adapter):
    r = await client.post("/api/v1/skills/no-such/archive", json={"archived": True})
    assert r.status_code == 404
    assert r.json()["detail"]["type"] == "skill_not_found"


@pytest.mark.asyncio()
async def test_archive_invalid_body_422(client, reset_skill_adapter):
    r = await client.post("/api/v1/skills/search/archive", json={"archived": "yes"})
    assert r.status_code == 422  # StrictBool 拒绝非布尔
```

- [x] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_skills_archive_api.py -v`
Expected: FAIL — 404（端点不存在）/ 405

- [x] **Step 3: 实现端点（`legacy_routes.py`，toggle 端点之后 ~line 929）**

```python
class SkillArchive(BaseModel):
    """``POST /skills/{name}/archive`` 请求体。"""

    archived: StrictBool


@router.post("/skills/{name}/archive")
async def archive_skill(name: str, data: SkillArchive):
    """归档 / 取消归档技能（软标记，可逆；区别于物理 delete）。

    - 200 + 完整 skill dict（含新 lifecycle）
    - 404 + 结构化 detail（技能名不存在）
    - 422（FastAPI 自动）— archived 缺失 / 类型错

    归档技能从 auto_activate / slash 候选排除（adapter 层），文件不动、可恢复。
    """
    adapter = _get_skill_adapter()
    if not adapter.set_archived(name, data.archived):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    # 返回完整 skill dict（与 toggle 一致）—— lifecycle 已由 list_skills_extended 注入
    ext = next((e for e in adapter.list_skills_extended() if e["name"] == name), None)
    assert ext is not None  # set_archived 已 guard
    return _skill_to_dict(ext, adapter.is_enabled(name), adapter.usage_count(name))
```

- [x] **Step 4: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_skills_archive_api.py -v`
Expected: PASS — 3/3 绿

- [x] **Step 5: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_skills_archive_api.py
git commit -m "feat: POST /skills/{name}/archive 软归档端点（可逆，透出 lifecycle）"
```

---

### Task 5: 前端 — 类型 + skillsApi.archive + Electron IPC + SkillCard badge/按钮 + Skills handler

**Files:**
- Modify: `src/shared/api/types.ts`（`Skill` 加 `lifecycle`，~line 296）
- Modify: `src/shared/api/skillsApi.ts`（加 `archive`）
- Modify: `electron/commands.ts`（加 `archive_skill` 命令，仿 `delete_skill` ~line 237）
- Modify: `src/widgets/skills/SkillCard.tsx`（badge + 归档按钮 + 弱化）
- Modify: `src/widgets/skills/SkillList.tsx`（透传 `lifecycle`/`onArchive`）
- Modify: `src/pages/Skills.tsx`（`handleArchive` + 透传）
- Test: `src/widgets/skills/__tests__/SkillCard.test.tsx`（扩展）+ `src/pages/__tests__/Skills.archive.test.tsx`（新增，仿 `Skills.delete.test.tsx`）

**Interfaces:**
- Consumes: `POST /skills/{name}/archive`（Task 4）+ GET /skills `lifecycle`（Task 2）
- Produces: 前端 badge（活跃/已冷/已归档）+ 归档/取消归档按钮 + optimistic 更新

- [x] **Step 1: 类型 — `types.ts` `Skill` 加字段**

```typescript
  lifecycle?: 'active' | 'stale' | 'archived';
```

- [x] **Step 2: `skillsApi.archive`（`delete` 方法之后）**

```typescript
  /**
   * 归档 / 取消归档技能（软标记，可逆；POST /api/v1/skills/{name}/archive）。
   * 归档技能从自动激活 / slash 候选排除，文件不动。
   */
  async archive(name: string, archived: boolean): Promise<Skill> {
    return withRetry(async () => {
      try {
        return await invoke<Skill>('archive_skill', { name, archived });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
```

- [x] **Step 3: Electron IPC — `electron/commands.ts` 加 `archive_skill`（仿 `delete_skill` ~line 237）**

> 实施时读 `electron/commands.ts:237` 的 `delete_skill` 定义，镜像其结构（HTTP method POST、path `/api/v1/skills/{name}/archive`、JSON body `{archived}`、返回透传）。命令名 `archive_skill`，参数 `{name, archived}`。

- [x] **Step 4: `SkillCard.tsx` — props + badge + 按钮 + 弱化**

props interface 加：

```typescript
  lifecycle?: 'active' | 'stale' | 'archived';
  onArchive?: (name: string, archived: boolean) => void;
```

destructure 补 `lifecycle, onArchive`。外层卡片 div className 追加归档弱化（现 ~line 49）：

```tsx
    <div
      className={`bg-surface rounded-lg shadow-md p-4 border-2 transition-all ${
        enabled ? 'border-primary' : 'border-border opacity-75'
      } ${lifecycle === 'archived' ? 'opacity-60' : ''}`}
    >
```

标题 chip 序列（`dispatchChip` 之后，~line 87）加 lifecycle badge：

```tsx
            {lifecycle && (
              <span
                className={`px-2 py-0.5 text-xs rounded-full ${
                  lifecycle === 'active'
                    ? 'bg-primary/20 text-primary'
                    : lifecycle === 'archived'
                      ? 'bg-accent/20 text-accent'
                      : 'bg-bg-subtle text-muted'
                }`}
              >
                {lifecycle === 'active' ? '活跃' : lifecycle === 'archived' ? '已归档' : '已冷'}
              </span>
            )}
```

右侧操作区（`TwoStepDelete` 旁，~line 127）加归档按钮：

```tsx
          {onArchive && (
            <button
              type="button"
              onClick={() => onArchive(name, lifecycle !== 'archived')}
              className="px-2 py-1 text-xs rounded border border-border text-text-secondary hover:text-text"
              aria-label={lifecycle === 'archived' ? `取消归档 ${name}` : `归档 ${name}`}
            >
              {lifecycle === 'archived' ? '取消归档' : '归档'}
            </button>
          )}
```

- [x] **Step 5: `SkillList.tsx` 透传 `lifecycle`/`onArchive`（仿现有 `onDelete` 透传）**

`SkillListProps` 加 `onArchive?: (name, archived) => void`；渲染 `SkillCard` 时传 `lifecycle={skill.lifecycle}` 与 `onArchive={onArchive}`。

- [x] **Step 6: `Skills.tsx` — `handleArchive`（仿 `handleDelete` 的 optimistic + 回滚 + toast）并透传**

```typescript
  const handleArchive = useCallback(
    async (name: string, archived: boolean) => {
      const prev = skills.find((s) => s.name === name)?.lifecycle;
      // optimistic
      setSkills((cur) =>
        cur.map((s) => (s.name === name ? { ...s, lifecycle: archived ? 'archived' : 'active' } : s)),
      );
      try {
        const updated = await skillsApi.archive(name, archived);
        setSkills((cur) => cur.map((s) => (s.name === name ? updated : s)));
        toast.success(archived ? `已归档 ${name}` : `已取消归档 ${name}`);
      } catch (error) {
        // 回滚到原 lifecycle
        setSkills((cur) => cur.map((s) => (s.name === name ? { ...s, lifecycle: prev } : s)));
        toast.error(`归档操作失败: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [skills],
  );
```

`<SkillList ... onArchive={handleArchive} />` 透传。（实施时按 `Skills.tsx` 现有 `handleDelete` / toast import 实际写法对齐。）

- [x] **Step 7: 前端测试**

`SkillCard.test.tsx` 追加：渲染 `lifecycle="active"/"stale"/"archived"` 分别出现「活跃/已冷/已归档」；`onArchive` 存在时渲染归档按钮，点击调 `onArchive(name, true)`；`lifecycle="archived"` 时按钮文案「取消归档」且点击调 `onArchive(name, false)`。

`Skills.archive.test.tsx`（仿 `Skills.delete.test.tsx`）：mock `skillsApi.archive` resolvedValueOnce → 点归档后列表 lifecycle 更新 + toast；rejectedOnce → 回滚 + 错误 toast；断言 `skillsApi.archive` 以 `(name, archived)` 被调。

- [x] **Step 8: 运行前端测试 + tsc**

Run:
```bash
cd /home/fz/project/sage && npm run test -- SkillCard Skills.archive
cd /home/fz/project/sage && npx tsc --noEmit
```
Expected: vitest 全绿，tsc 0 error

- [x] **Step 9: Commit**

```bash
git add src/shared/api/types.ts src/shared/api/skillsApi.ts electron/commands.ts \
  src/widgets/skills/SkillCard.tsx src/widgets/skills/SkillList.tsx src/pages/Skills.tsx \
  src/widgets/skills/__tests__/SkillCard.test.tsx src/pages/__tests__/Skills.archive.test.tsx
git commit -m "feat: 前端技能生命周期 badge + 归档/取消归档（optimistic + 回滚）"
```

---

### Task 6: 全量回归 + ruff + 冒烟 + PR

**Files:** 无新增（回归验证）

- [x] **Step 1: 后端全量测试 + ruff**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/skills/lifecycle.py \
  backend/adapters/out/skill/inproc.py backend/api/legacy_routes.py backend/data/database.py \
  backend/tests/conftest.py backend/tests/unit/test_skill_lifecycle.py \
  backend/tests/unit/test_inproc_lifecycle.py backend/tests/integration/test_skills_archive_api.py
```
Expected: pytest 全量 PASS（无回归），ruff 0 errors

- [x] **Step 2: 前端全量测试 + tsc**

Run:
```bash
cd /home/fz/project/sage && npm run test
cd /home/fz/project/sage && npx tsc --noEmit
```
Expected: vitest 全绿，tsc 0 error

- [x] **Step 3: 手动冒烟（run-desktop skill）**

启动桌面端 → 技能页：确认 active/stale/archived badge 正确；归档某技能后卡片弱化、badge 变「已归档」、该技能从自动激活/slash 消失；重启后端后归档态保持；点「取消归档」恢复。

- [x] **Step 4: push + 开 PR**

```bash
git push -u origin feat/skill-curator-lifecycle
gh pr create --title "feat: 技能生命周期 active/stale/archived + 软归档动作" \
  --body "建在 PR #269 skill_usage 之上的 Skill curator 生命周期。读取时即时分类（无 worker）+ 可逆软归档 + 前端 badge。Spec: docs/superpowers/specs/2026-08-02-skill-curator-lifecycle-design.md"
```

- [x] **Step 5: 监控 PR CI**

Run: `gh pr checks <pr-number> --watch`
Expected: 全绿（windows vcredist 若再 flaky → `gh run rerun --failed`）

---

## Self-Review

**Spec 覆盖对照：**

| Spec 要求 | 对应任务 |
|---|---|
| `skill_lifecycle` 表（name/archived/archived_at） | Task 1 Step 1 |
| `classify_lifecycle` 纯函数（archived 优先 / None→stale / 阈值边界） | Task 1（6 个纯函数用例） |
| `SkillLifecycleStore` best-effort + 单例 | Task 1（roundtrip / unarchive / 持久 / best-effort 用例） |
| conftest 重置单例 | Task 1 Step 5 |
| adapter `_archived` 内存缓存 + hydrate（重启不丢） | Task 2（`test_archive_persists_across_adapter_instances`） |
| `set_archived/is_archived/lifecycle_map` | Task 2 |
| `list_skills_extended` 注入 lifecycle | Task 2（`test_list_skills_extended_includes_lifecycle`） |
| auto_activate 排除归档 | Task 3 |
| slash registry 排除归档（list + execute） | Task 3 |
| `POST /skills/{name}/archive` + 404 + 422 + GET 透出 | Task 4 |
| 前端类型 / skillsApi / IPC / badge / 按钮 / handler | Task 5 |
| builtin 可归档 | Task 2/4（用例用 search/coder） |
| archived 与 enabled 正交（可用性 = enabled ∧ ¬archived） | Task 3（auto_activate 同时查 is_enabled + is_archived） |
| 无后台 worker（读时算） | 全程无 lifespan/worker 改动 |

**占位符检查：** Task 3 的 skill_md 测试 helper（`_adapter_with_skillmd`）与 Task 5 Step 3 的 Electron `archive_skill` 命令体为"实施时按实际字段/定义定稿"——因依赖 `DispatchMode`/`SkillMdDocument` 精确字段与 `electron/commands.ts:delete_skill` 现有结构，已标注核对点，非遗漏。其余代码块含完整实现。

**类型一致性：** `classify_lifecycle(last_used_at_ms, archived, now_ms, stale_threshold_ms)` 在 Task 1 定义、Task 2 `lifecycle_map` 调用，签名一致。`set_archived(name, archived) -> bool` / `is_archived(name) -> bool` 在 Task 2 定义、Task 3（排除）/Task 4（路由）引用，一致。`lifecycle` 字段名后端 `list_skills_extended`（Task 2）→ `_skill_to_dict` 透传（Task 4）→ 前端 `Skill.lifecycle`（Task 5）全程一致；三态字面量 `"active"/"stale"/"archived"` 前后端一致。

**实施时需核对的点（非阻塞）：**
1. Task 3 `SkillMdDocument`/`DispatchMode` 精确字段（`backend/skills/skill_md/skill.py:49` / `frontmatter.py`）与现有 auto_activate/slash 测试 fixture。
2. Task 5 `electron/commands.ts:237` `delete_skill` 命令结构（镜像为 `archive_skill`）。
3. Task 5 `Skills.tsx` 现有 `handleDelete`/`toast` 写法对齐。
