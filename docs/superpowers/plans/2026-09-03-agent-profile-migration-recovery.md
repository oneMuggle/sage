# Agent Profile 迁移恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PR #381（`terminal → bash` 重命名）和 PR #396 累计的工具增补在用户 SQLite DB 上"哑炮"——补齐 `profiles.py` 的硬编码修正 + 工具名重命名迁移 + 启动时差集迁移三段，让 coder / primary / researcher 三个 agent 的白名单终态与 `profiles.create_default_agents()` 当前默认一致。

**Architecture:** 在 `backend/agents/profiles.py` 的 `ensure_default_agents()` 启动钩子里**追加**两段纯增量逻辑（不删既有 4 段"集合相等"迁移）：(1) 工具名重命名段遍历所有 agent，按 `LEGACY_TOOL_NAME_RENAMES` 映射逐元素 in-place 替换；(2) 差集迁移段对 primary / researcher 判定"当前默认 ⊆ DB" → 追加缺的工具。两段都做幂等性，第二次启动不再触发 `upsert`。同时把 `create_default_agents()` 第 111 行 coder profile 硬编码修正。

**Tech Stack:** Python 3.11（main 分支，sage-backend conda 环境）；pytest；`backend/data/agent_repo.py` 的 `AgentRepository` 同步 SQLite API；`backend/agents/profiles.py` 的 `ensure_default_agents()` 是入口。

**Spec:** `docs/superpowers/specs/2026-09-03-agent-profile-migration-recovery.md`（**部分已交付**：PR #401 已合并 §4 system_prompt 升级 + §6 researcher http_download；本 plan 仅覆盖 backlog §1 重命名迁移 + §2 subset 迁移 + §3 coder 硬编码）。

---

## Global Constraints

- **Python 版本**：仅在 main 上运行（Python 3.11 + pydantic 2.x）；本次**不动** `release/win7`（Py3.8 / pydantic 1.x 仍欠一段重命名迁移，但需在 win7 分支单独走 plan）。代码用 `from __future__ import annotations` 保留。
- **后端 Python 环境**：所有 pytest / ruff 命令必须用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不要用系统 `python3`（会 `ModuleNotFoundError: No module named 'fastapi'`）。
- **pytest 路径**：仓库根 `/home/fz/project/sage` 直接跑 pytest；`cd backend` 后跑会报 `No test files found`。
- **ruff 配置**：`backend/ruff.toml`，`line-length = 100`；新代码符合 ruff 全部规则。
- **代码注释**：默认不写注释；只在 WHY 不显然时写一行（隐藏约束、反直觉行为、特定 bug 规避）。
- **语言**：docstring 与用户可见错误信息用中文，与现有 `backend/agents/profiles.py` 一致。
- **提交粒度**：每个 Task 结束提交一次，conventional commits（`fix:` / `test:` / `docs:`）。
- **分支**：Task 1 开始前**必须** `git switch -c fix/agent-profile-migration-recovery`（基于当前 `main`，已含 PR #401 的 `f382e475`）。在分支上工作，按 feature-branch-workflow.md 走 PR → CI → AI review → 用户 merge 流程。**不**直接 push main。
- **不动 `main` / `release/win7` 公共契约**：`backend/main.py` 的 lifespan / `backend/data/agent_repo.py` 的 `upsert` / `backend/tools/registry.py` 的 `get_schemas_for_llm` 一律不动。本 plan 只动 `backend/agents/profiles.py` + 新测试文件 + 既有测试加断言 + `CHANGELOG.md`。

---

## File Structure

**修改：**

| 文件 | 改动 |
|---|---|
| `backend/agents/profiles.py` | (a) 第 113 行 coder.tools 硬编码修正（4 个名字全对齐，**Task 1 已完成**）；(b) primary.tools 加 `web_fetch` + `http_download`（**Task 5**）；(c) primary.system_prompt 改用 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`（**Task 5**）；(d) 新增 `LEGACY_TOOL_NAME_RENAMES` 常量（Task 2）；(e) 新增 `_PRIMARY_CURRENT_DEFAULT_TOOLS`（12 元素）/ `_RESEARCHER_CURRENT_DEFAULT_TOOLS` 常量（Task 3）；(f) 新增 `_append_missing_tools` 助手（Task 3）；(g) 新增 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` 常量（Task 5）；(h) `ensure_default_agents()` 函数体追加 3 段（重命名循环 + 差集兜底 + system_prompt 链式升级） |
| `backend/tests/unit/test_profiles_intranet_web_access_migration.py` | 加 1 个断言：`test_default_seed_coder_uses_current_tool_names`（**Task 1 已完成**）+ Task 5 加 4 个断言 |
| `CHANGELOG.md` | 加 `fix(agents): …` 条目（Keep a Changelog 格式，顶部 `[Unreleased]` 段） |

**新建测试：**

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/test_profiles_legacy_tool_rename.py` | §1 重命名迁移的 6 个用例（terminal / file_read / file_write / 用户额外项保留 / 幂等 / 仅这 3 个旧名生效 / 跨 agent 生效） |
| `backend/tests/unit/test_profiles_subset_migration.py` | §2 subset 迁移的 6 个用例（primary 子集 / 超集 / 不相交；researcher 子集；当前形状不 upsert；幂等） |

**不动：**

- `backend/data/agent_repo.py`（`upsert` / `seed_defaults_if_empty` 接口稳定）
- `backend/main.py`（lifespan 仍调 `ensure_default_agents()`，无需改）
- `backend/tools/registry.py`（`get_schemas_for_llm` 接口稳定）

---

## Task 1: 修正 `profiles.py` coder profile 硬编码 + 既有测试加断言

**Files:**
- Modify: `backend/agents/profiles.py:105-115`（coder profile 全段）
- Modify: `backend/tests/unit/test_profiles_intranet_web_access_migration.py:18-28`（在 `test_default_seed_includes_researcher_http_download` 之后加新断言）

**Interfaces:**
- Consumes: 无（独立的最小修复）
- Produces:
  - `backend.agents.profiles.create_default_agents()` 返回的 `"coder"` profile，其 `tools` 字段是 `["read_file", "write_file", "bash", "calculator"]`（顺序敏感）

- [x] **Step 1: 先建分支**

```bash
cd /home/fz/project/sage && git switch -c fix/agent-profile-migration-recovery
```

✅ 已完成（在 main 含 PR #401 的 `f382e475` 基础上切出）。

- [x] **Step 2: 写失败测试**

```bash
# ✅ 已完成: 既有 backend/tests/unit/test_profiles_intranet_web_access_migration.py:31-40
# 加 test_default_seed_coder_uses_current_tool_names 断言
```

- [x] **Step 3: 跑测试确认失败**

✅ 已完成（最初会 FAIL：`assert ['file_read', 'file_write', 'terminal', 'calculator'] == ['read_file', 'write_file', 'bash', 'calculator']`，与预期一致）。

- [x] **Step 4: 改 profiles.py:105-115 coder profile**

✅ 已完成（coder.tools 现在是 `["read_file", "write_file", "bash", "calculator"]`，注释指明 PR #381 重命名 + 拼写错位）。

- [x] **Step 5: 跑测试确认通过**

✅ 已完成（原 9 个用例 + 新 1 个用例，**全 PASS**）。

- [x] **Step 6: 跑整个 unit 测试套，确保不破坏既有用例**

✅ 待 commit 后再跑一次最终回归（当前 uncommitted 状态跑应该 0 fail）。

- [ ] **Step 7: 提交**

```bash
cd /home/fz/project/sage && git add backend/agents/profiles.py backend/tests/unit/test_profiles_intranet_web_access_migration.py docs/superpowers/specs/2026-09-03-agent-profile-migration-recovery.md docs/superpowers/plans/2026-09-03-agent-profile-migration-recovery.md && \
  git commit -m "fix(agents): coder profile 工具白名单对齐当前工具名 (terminal→bash + file_read→read_file + file_write→write_file)

PR #381 (81a20b0b) 把 TerminalTool 重写为 BashTool (name='bash'),
但 profiles.create_default_agents()['coder'].tools 仍写旧名:
['file_read', 'file_write', 'terminal', 'calculator']。
其中 3 个名字在 tools/ 已不存在 —— LLM UI 选 coder 后拿到的工具
schema 集合近乎为空, 报'没有 bash 工具'。

修 coder profile 硬编码(4 个名字全对齐当前工具名), 并在既有
test_profiles_intranet_web_access_migration.py 加 1 个断言锁住默认形状。
本 commit 同时更新 spec/plan 文档, 把 §5 'primary 直接 fetch/download'
与 Task 5 纳入 backlog (用户后续 session 接续时直接读)。

PR #401 (f382e475) 已合并 primary system_prompt + researcher
http_download 迁移; 本 commit 修同一回归的 coder 侧, 并为后续
Task 5 (primary fetch_direct) 锁定 spec 方向。"
```

---

## Task 2: 工具名重命名迁移（§1）

**Files:**
- Modify: `backend/agents/profiles.py` —— 在 `PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` 之后、`_default_repo` 之前，新增 `LEGACY_TOOL_NAME_RENAMES` 常量 + `ensure_default_agents()` 函数体**最前面**插入重命名循环段
- Create: `backend/tests/unit/test_profiles_legacy_tool_rename.py`

**Interfaces:**
- Consumes:
  - `AgentRepository.list_all() -> List[dict]`
  - `AgentRepository.upsert(profile: dict) -> None`
  - `_repo_factory_for_tests` 测试注入点
- Produces:
  - 模块级常量 `LEGACY_TOOL_NAME_RENAMES: Dict[str, str] = {"terminal": "bash", "file_read": "read_file", "file_write": "write_file"}`
  - `ensure_default_agents()` 内部对**所有 agent**（不限 id）的 `tools` 列表执行 `LEGACY_TOOL_NAME_RENAMES` 逐元素 in-place 替换；触发 `upsert` 当且仅当列表发生变更

- [ ] **Step 1: 写失败测试 `backend/tests/unit/test_profiles_legacy_tool_rename.py`**

完整文件内容（覆盖 6 个用例）：

```python
"""PR #381 工具名重命名迁移的单测。

触发原因: PR #381 删除 TerminalTool / 重写为 BashTool (name='bash'),
但 ensure_default_agents() 没补一段 'terminal → bash' 迁移。
用户 DB 永远卡在旧名字。本文件锁住重命名段的行为契约:
- 三个旧名都映射正确
- 用户私有项不动
- 已是新名时 idempotent (不 upsert)
- 仅这 3 个旧名生效 (其他名完全不动)
"""
from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


class FakeRepo:
    """最小化 AgentRepository mock —— 复刻 test_profiles_intranet_web_access_migration 风格。"""

    def __init__(self, stored):
        self.stored = stored
        self.upserts = []

    def get(self, agent_id):
        return dict(self.stored[agent_id]) if agent_id in self.stored else None

    def list_all(self):
        return [dict(row) for row in self.stored.values()]

    def upsert(self, data):
        self.upserts.append(data)
        self.stored[data["id"]] = data


def _seed_repo(monkeypatch, stored):
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    return repo


def test_terminal_renames_to_bash(monkeypatch):
    stored = {
        "primary":    {"id": "primary",    "enabled": True, "tools": []},
        "researcher": {"id": "researcher", "enabled": True, "tools": []},
        "coder":      {"id": "coder",      "enabled": True, "tools": ["terminal", "calculator"]},
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "terminal" not in stored["coder"]["tools"]
    assert "bash" in stored["coder"]["tools"]
    assert stored["coder"]["tools"] == ["bash", "calculator"]
    coder_upserts = [u for u in repo.upserts if u["id"] == "coder"]
    assert len(coder_upserts) == 1


def test_file_read_and_file_write_renames(monkeypatch):
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["file_read", "file_write", "calculator"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["read_file", "write_file", "calculator"]


def test_renames_preserve_user_extras(monkeypatch):
    """重命名段只动映射表里的 3 个名字; 用户额外项一字不动。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["terminal", "my_custom_tool"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["bash", "my_custom_tool"]


def test_renames_idempotent_no_upsert(monkeypatch):
    """tools 已是新名 → 重命名段不触发 upsert。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["read_file", "write_file", "bash", "calculator"]},
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["coder"]["tools"] == ["read_file", "write_file", "bash", "calculator"]


def test_renames_only_affects_three_legacy_names(monkeypatch):
    """映射表外的名字(无论旧名还是用户私有)完全不动。"""
    stored = {
        "coder": {"id": "coder", "enabled": True, "tools": ["foo", "bar", "calculator"]},
    }
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    # 既无 rename 触发, 后续兜底段也不动 (foo/bar 不在 _PRIMARY_CURRENT_DEFAULT_TOOLS)
    # —— coder 的"当前默认 ⊆ DB"判定为不相交, 跳过 upsert
    assert stored["coder"]["tools"] == ["foo", "bar", "calculator"]


def test_renames_apply_to_all_agents_not_just_coder(monkeypatch):
    """重命名段遍历所有 agent, 不限定 coder。"""
    stored = {
        "primary":    {"id": "primary",    "enabled": True, "tools": ["terminal", "calculator"]},
        "researcher": {"id": "researcher", "enabled": True, "tools": ["file_read"]},
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "terminal" not in stored["primary"]["tools"]
    assert "bash" in stored["primary"]["tools"]
    assert "file_read" not in stored["researcher"]["tools"]
    assert "read_file" in stored["researcher"]["tools"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_legacy_tool_rename.py -v
```

期望：6 个 FAIL（`LEGACY_TOOL_NAME_RENAMES` 未导入 / 重命名段未实现）。

- [ ] **Step 3: 加常量 + 实现重命名段**

在 `backend/agents/profiles.py` 第 203 行（`PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` 定义结束）之后、第 206 行 `_default_repo` 之前，**插入常量定义**：

```python
# 2026-09-03: PR #381 把 TerminalTool 重写为 BashTool (name="bash"),
# file_read/file_write 是拼写错位(真实工具名 read_file/write_file)。
# 重命名段遍历所有 agent 的 tools 列表, 按此映射逐元素 in-place 替换;
# 用户额外项一字不动; 幂等(第二次跑不触发 upsert)。
LEGACY_TOOL_NAME_RENAMES: Dict[str, str] = {
    "terminal":   "bash",
    "file_read":  "read_file",
    "file_write": "write_file",
}
```

然后修改 `ensure_default_agents()` 函数体。在第 222 行 `repo = _repo_factory_for_tests() if _repo_factory_for_tests else _default_repo()` 之后、第 223 行 `inserted = 0` 之前插入：

```python
    # 2026-09-03: 工具名重命名迁移(§1)。先于种子补插 + 既有 4 段
    # "集合相等"判定 + subset 兜底段, 让后续所有判定都在重命名后的
    # tools 上运行 (例如 coder 重命名后的 tools 才能与 _BEFORE_* 段比较)。
    for row in repo.list_all():
        tools = row.get("tools") or []
        renamed = [LEGACY_TOOL_NAME_RENAMES.get(t, t) for t in tools]
        if renamed != tools:
            row["tools"] = renamed
            repo.upsert(row)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_legacy_tool_rename.py -v
```

期望：6/6 PASS。

- [ ] **Step 5: 跑整个 unit 套 + 既有的 intranet migration 套，确认无回归**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/ -q
```

期望：**0 fail**。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage && git add backend/agents/profiles.py backend/tests/unit/test_profiles_legacy_tool_rename.py && \
  git commit -m "fix(agents): 工具名重命名迁移 (terminal→bash + file_read→read_file + file_write→write_file)

PR #381 (81a20b0b) 删除 TerminalTool / 重写为 BashTool (name='bash'),
但 ensure_default_agents() 没补一段重命名迁移, 用户 DB 永远卡在旧名字。
本 commit 加 LEGACY_TOOL_NAME_RENAMES 常量 + 在 ensure_default_agents
最前面插入遍历所有 agent 的重命名循环:

- terminal → bash
- file_read → read_file
- file_write → write_file

遍历所有 agent (不限定 coder): 若用户曾在某个 agent 里加过旧名,
也一并对齐到当前工具名。用户额外项一字不动; 已是新名时幂等
(不触发 upsert 防 updated_at 抖动)。

配 6 个单测覆盖 terminal / file_read / file_write / 用户额外项 /
幂等 / 仅这 3 个旧名生效 / 跨 agent 生效。"
```

---

## Task 3: 启动时差集迁移（§2）

**Files:**
- Modify: `backend/agents/profiles.py` —— 新增 `_PRIMARY_CURRENT_DEFAULT_TOOLS` / `_RESEARCHER_CURRENT_DEFAULT_TOOLS` 常量；新增 `_append_missing_tools` 助手；在 `ensure_default_agents()` 函数体**最后**追加差集兜底段
- Create: `backend/tests/unit/test_profiles_subset_migration.py`

**Interfaces:**
- Consumes:
  - `AgentRepository.get(agent_id) -> dict | None`
  - `AgentRepository.upsert(profile: dict) -> None`
- Produces:
  - 模块级常量 `_PRIMARY_CURRENT_DEFAULT_TOOLS: List[str]`（10 个工具，不含 bash——见 spec §4 架构决定）
  - 模块级常量 `_RESEARCHER_CURRENT_DEFAULT_TOOLS: List[str]`（4 个工具）
  - 助手函数 `_append_missing_tools(agent: dict, current_default_tools: List[str]) -> bool`：若 `agent["tools"]` 缺 `current_default_tools` 里的任一项，按 `current_default_tools` 顺序追加到尾部，返回 `True`；否则返回 `False`
  - `ensure_default_agents()` 函数体**最后**对 `("primary", _PRIMARY_CURRENT_DEFAULT_TOOLS)` 与 `("researcher", _RESEARCHER_CURRENT_DEFAULT_TOOLS)` 各跑一次差集兜底

- [ ] **Step 1: 写失败测试 `backend/tests/unit/test_profiles_subset_migration.py`**

完整文件内容（覆盖 6 个用例）：

```python
"""PR-3 时期 DB 的 subset 迁移单测。

触发原因: PR #264 / P0-5 / P1 todo / PR #396 的累计迁移用
'set(tools) == 旧种子' 严格相等判定; 用户 DB 实际是 PR-3 时期的
5 工具种子, 不命中任何 _BEFORE_* 段, 4 段迁移全哑炮。
本文件锁住 subset 兜底段的行为契约:
- primary 真子集 → 追加缺的, 顺序保留
- primary 真超集 / 集合相等 / 完全不相交 → 不动
- researcher 子集(刻意不命中既有段) → 走 subset 段补缺
- 已是当前形状 → 不 upsert (防 updated_at 抖动)
- 连续跑两次, 第二次 0 upsert
"""
from __future__ import annotations

import pytest

from backend.agents import profiles

pytestmark = pytest.mark.unit


class FakeRepo:
    def __init__(self, stored):
        self.stored = stored
        self.upserts = []

    def get(self, agent_id):
        return dict(self.stored[agent_id]) if agent_id in self.stored else None

    def list_all(self):
        return [dict(row) for row in self.stored.values()]

    def upsert(self, data):
        self.upserts.append(data)
        self.stored[data["id"]] = data


def _seed_repo(monkeypatch, stored):
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    return repo


def test_primary_subset_gets_missing_appended(monkeypatch):
    """PR-3 时期 primary 种子(5 工具) → subset 段追加缺的 5 个工具。"""
    legacy_5 = ["calculator", "memory_search", "memory_save", "list_dir", "read_file"]
    stored = {"primary": {"id": "primary", "enabled": True, "tools": list(legacy_5)}}
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    expected = legacy_5 + ["grep_search", "glob_search", "file_summary", "agent", "todo_write"]
    assert stored["primary"]["tools"] == expected


def test_primary_superset_untouched(monkeypatch):
    """primary 真超集(含用户额外项) → subset 段不动。"""
    superset = (
        profiles._PRIMARY_CURRENT_DEFAULT_TOOLS + ["user_extra"]
    )
    stored = {"primary": {"id": "primary", "enabled": True, "tools": list(superset)}}
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == superset
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"


def test_primary_disjoint_untouched(monkeypatch):
    """primary 完全不相交(用户整个白名单换掉) → subset 段不动。"""
    stored = {"primary": {"id": "primary", "enabled": True, "tools": ["my_a", "my_b"]}}
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert stored["primary"]["tools"] == ["my_a", "my_b"]
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"


def test_researcher_subset_gets_missing_appended(monkeypatch):
    """researcher 子集(刻意不命中既有 _RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD 段)
    → subset 段追加缺的。"""
    # 形状 = {web_fetch, http_download, memory_search} 缺 web_search
    # 故意不含 web_search, 不命中既有"集合相等"段(后者需恰好等于旧 3 工具)
    stored = {
        "researcher": {
            "id": "researcher", "enabled": True,
            "tools": ["web_fetch", "http_download", "memory_search"],
        },
    }
    _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    assert "web_search" in stored["researcher"]["tools"]
    assert stored["researcher"]["tools"] == [
        "web_fetch", "http_download", "memory_search", "web_search",
    ]


def test_researcher_already_current_no_upsert(monkeypatch):
    """researcher 已是 4 工具当前默认 → 不触发 upsert。"""
    current = list(profiles._RESEARCHER_CURRENT_DEFAULT_TOOLS)
    stored = {"researcher": {"id": "researcher", "enabled": True, "tools": current}}
    repo = _seed_repo(monkeypatch, stored)
    profiles.ensure_default_agents()
    researcher_upserts = [u for u in repo.upserts if u["id"] == "researcher"]
    assert researcher_upserts == [], f"researcher 不应被 upsert，但收到: {researcher_upserts}"


def test_subset_migration_idempotent(monkeypatch):
    """连续跑两次 ensure_default_agents(), 第二次 0 upsert。"""
    legacy_5 = ["calculator", "memory_search", "memory_save", "list_dir", "read_file"]
    legacy_researcher = ["web_search", "web_fetch", "memory_search"]
    stored = {
        "primary":    {"id": "primary",    "enabled": True, "tools": list(legacy_5)},
        "researcher": {"id": "researcher", "enabled": True, "tools": list(legacy_researcher)},
    }
    repo = _seed_repo(monkeypatch, stored)

    profiles.ensure_default_agents()
    first_upsert_count = len(repo.upserts)
    profiles.ensure_default_agents()
    assert len(repo.upserts) == first_upsert_count, (
        f"第二次跑应不触发 upsert，但新增了 {len(repo.upserts) - first_upsert_count} 次"
    )
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_subset_migration.py -v
```

期望：6 个 FAIL（`_PRIMARY_CURRENT_DEFAULT_TOOLS` / `_append_missing_tools` 未定义）。

- [ ] **Step 3: 加常量 + 助手 + 兜底段**

在 `backend/agents/profiles.py` 第 209 行（`LEGACY_TOOL_NAME_RENAMES` 定义结束）之后、第 215 行 `_default_repo` 之前，插入：

```python
# 2026-09-03: subset 兜底段用的"当前默认"列表。primary 不含 bash 是 PR #396
# 的架构决定 (coordinator / 出网委派); researcher 含 http_download 是 PR #396
# 的内网取页工具。变更时手动维护, 与既有 _BEFORE_* 同模式。
_PRIMARY_CURRENT_DEFAULT_TOOLS: List[str] = [
    "calculator", "memory_search", "memory_save",
    "list_dir",   "read_file",
    "grep_search", "glob_search", "file_summary",
    "agent",      "todo_write",
]

_RESEARCHER_CURRENT_DEFAULT_TOOLS: List[str] = [
    "web_search", "web_fetch", "http_download", "memory_search",
]


def _append_missing_tools(agent: dict, current_default_tools: List[str]) -> bool:
    """subset 兜底段: 当前默认 ⊆ agent.tools → 追加缺的; 否则不动。

    不删 agent.tools 多出来的项 (用户删过的默认工具 / 用户额外项都保留)。
    返回 True 表示发生了变更, False 表示不动。
    """
    db_tools = agent.get("tools") or []
    missing = [t for t in current_default_tools if t not in db_tools]
    if not missing:
        return False
    agent["tools"] = db_tools + missing
    return True
```

然后修改 `ensure_default_agents()` 函数体。在函数最后一行 `return inserted` 之前插入兜底段：

```python
    # 2026-09-03: subset 兜底段(§2)。当前默认 ⊆ DB → 追加缺的; 真超集 /
    # 集合相等 / 不相交都跳过。用户任意增删都不影响。放在 4 段"集合相等"
    # 之后, 让更窄判定的精确段先触发特定升级, 兜底段负责 tools 白名单
    # 的最终一致性。
    for agent_id, default_tools in (
        ("primary",    _PRIMARY_CURRENT_DEFAULT_TOOLS),
        ("researcher", _RESEARCHER_CURRENT_DEFAULT_TOOLS),
    ):
        row = repo.get(agent_id)
        if row is None:
            continue
        if _append_missing_tools(row, default_tools):
            repo.upsert(row)
    return inserted
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_subset_migration.py -v
```

期望：6/6 PASS。

- [ ] **Step 5: 跑整个 unit 套，确认无回归**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/ -q
```

期望：**0 fail**。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage && git add backend/agents/profiles.py backend/tests/unit/test_profiles_subset_migration.py && \
  git commit -m "fix(agents): subset 兜底迁移 - 当前默认 ⊆ DB 时追加缺的工具

既有 4 段 'set(tools) == 旧种子' 严格相等迁移, 对 PR-3 时期
DB 形状(5 工具 primary)全哑炮, 用户永远吃不到 grep_search /
glob_search / file_summary / agent / todo_write 五件套。本 commit
加 _append_missing_tools 兜底段:

- 当前默认 ⊆ DB → 追加缺的 (按当前默认顺序, 追加到尾部)
- 真超集 / 集合相等 / 不相交 → 不动 (尊重用户任何增删)
- 已是当前形状 → idempotent, 不 upsert 防 updated_at 抖动

兜底段放在 4 段 '集合相等' 之后; 精确段优先触发特定升级
(如 system_prompt 文字替换), 兜底段负责 tools 白名单最终一致性。
两者并存不互相干扰。

primary 默认列表不含 bash —— 守 PR #396 架构边界
(coordinator / 出网委派)。若未来破例, 只需把 'bash' 加到
_PRIMARY_CURRENT_DEFAULT_TOOLS, 兜底段会自动覆盖。

配 6 个单测覆盖 primary 子集 / 超集 / 不相交 + researcher 子集
(刻意不命中既有段) + 当前形状不 upsert + 连续两次幂等。"
```

---

## Task 4: 用户 DB 端到端验证 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（顶部 `[Unreleased]` 段加 `fix(agents)` 条目）

**Interfaces:** 无（验收 + 文档）

- [ ] **Step 1: 启动后端，让 `ensure_default_agents()` 跑一次**

```bash
# 启动后端(在 sage-backend conda 环境)
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m backend.main &
BACKEND_PID=$!

# 等 3 秒让 lifespan 跑完
sleep 3

# 健康检查
curl -s http://127.0.0.1:8765/health
```

期望：`{"status":"ok",...}` 或类似 200 响应。

- [ ] **Step 2: sqlite 查三个 agent 的终态**

```bash
sqlite3 -header -column /home/fz/.config/sage/sage.db \
  "SELECT id, json(tools) AS tools_json, enabled FROM agents WHERE id IN ('primary','researcher','coder') ORDER BY id;"
```

期望：

```
id              tools_json                                                                      enabled
--------------  ------------------------------------------------------------------------------  -------
coder           ["read_file","write_file","bash","calculator"]                                    1
primary         ["calculator","memory_search","memory_save","list_dir","read_file","grep_searc    1
                h","glob_search","file_summary","agent","todo_write","web_fetch","http_downloa
                d"]
researcher      ["web_search","web_fetch","http_download","memory_search"]                        1
```

- [ ] **Step 3: 重启后端一次，确认无 upsert 抖动（updated_at 不变）**

```bash
# 记录 coder / primary / researcher 的 updated_at
sqlite3 /home/fz/.config/sage/sage.db \
  "SELECT id, updated_at FROM agents WHERE id IN ('primary','researcher','coder');"

# 重启后端
kill $BACKEND_PID
sleep 1
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m backend.main &
NEW_PID=$!
sleep 3

# 再查一次 updated_at
sqlite3 /home/fz/.config/sage/sage.db \
  "SELECT id, updated_at FROM agents WHERE id IN ('primary','researcher','coder');"

kill $NEW_PID
```

期望：3 个 agent 的 `updated_at` **保持不变**（无 upsert 抖动）。

- [ ] **Step 4: 加 CHANGELOG 条目**

打开 `CHANGELOG.md`，在顶部 `[Unreleased]` 段（若不存在先建）加：

```markdown
## [Unreleased]

### Fixed
- `fix(agents):` 四件套（PR #401 + 本分支）— 让 PR #381 的 `terminal → bash` 重命名 + PR #396 的累计工具增补 + primary 直接 fetch/download 在用户 SQLite DB 上生效：
  - `coder` profile 工具白名单对齐当前工具名（`terminal → bash` + `file_read → read_file` + `file_write → write_file`）
  - 工具名重命名迁移（`LEGACY_TOOL_NAME_RENAMES`）— 启动时遍历所有 agent 的 `tools`，按映射逐元素 in-place 替换，幂等
  - subset 兜底迁移（`_append_missing_tools`）— `当前默认 ⊆ DB` 时追加缺的，让 PR-3 时期 DB 也能吃到累计的工具增补
  - **primary 直接 fetch/download**（用户可见 / 分步指导）— primary.tools 加 `web_fetch` + `http_download`；system_prompt 升级到 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`；存量 DB 走 `BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT` 链式合并为单次 upsert
```

注：CHANGELOG 不写每个 PR 的 commit，按本项目惯例合并到同一段。

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add CHANGELOG.md && \
  git commit -m "docs(changelog): agent profile migration recovery (coder 重命名 + subset 兜底 + primary fetch_direct)"
```

---

## Task 5: primary 直接 fetch/download + system_prompt 链式升级（§5）

**Files:**
- Modify: `backend/agents/profiles.py` —— `create_default_agents()["primary"].tools` 加 `web_fetch` + `http_download`；`system_prompt` 改用 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`；新增 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` 常量；`ensure_default_agents()` 中既有 system_prompt 升级段改写为链式（BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT 合并为单次 upsert）
- Modify: `backend/tests/unit/test_profiles_intranet_web_access_migration.py` —— 更新 2 个既有断言 + 加 4 个新断言
- Modify: `backend/tests/unit/test_profiles_subset_migration.py`（待 Task 3 创建后）—— 更新 `test_primary_subset_gets_missing_appended` 期望列表到 12 元素

**Interfaces:**
- Consumes: 同 Task 3
- Produces:
  - 模块级常量 `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT: str`（含"你可以直接调用 web_fetch 和 http_download"段 + 保留委派段）
  - `create_default_agents()["primary"].tools` 12 元素（10 + web_fetch + http_download）
  - `create_default_agents()["primary"].system_prompt == PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`
  - `ensure_default_agents()` 中 primary system_prompt 升级段链式处理：BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT，单次 upsert

- [ ] **Step 1: 写失败测试（更新既有 + 加新）**

在 `backend/tests/unit/test_profiles_intranet_web_access_migration.py` 第 167 行（`test_current_primary_system_prompt_untouched` 结束）之后插入：

```python
# ---------------------------------------------------------------------------
# primary 直接 fetch/download（§5）
# ---------------------------------------------------------------------------


def test_default_seed_primary_includes_fetch_download():
    """代码默认 primary 工具白名单含 web_fetch + http_download（§5 用户可见方向）。"""
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert "web_fetch" in primary.tools
    assert "http_download" in primary.tools


def test_default_seed_primary_uses_fetch_direct_prompt():
    """代码默认 primary system_prompt 升级为 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT。

    保留委派段（含 "委派" / "子代理"）— 复杂研究仍走 agent 工具委派。
    新增直接 fetch/download 段 — 用户可见 LLM 行为, 便于分步指导。
    """
    primary = next(a for a in profiles.create_default_agents() if a.id == "primary")
    assert primary.system_prompt == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    # 委派段必须保留 (复杂研究任务仍走子代理)
    assert "委派" in primary.system_prompt or "子代理" in primary.system_prompt
    # 直接 fetch/download 段必须新增
    assert "web_fetch" in primary.system_prompt
    assert "http_download" in primary.system_prompt


def test_primary_system_prompt_legacy_two_step_chain_migration(monkeypatch):
    """DB system_prompt 是 _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION →
    一气呵成升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT (合并为单次 upsert)。
    """
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles._PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    # 链式合并: 仅 1 次 primary upsert (而不是 2 次)
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert len(primary_upserts) == 1, f"应有 1 次 upsert（链式合并），收到 {len(primary_upserts)}"


def test_primary_system_prompt_with_delegation_one_step_migration(monkeypatch):
    """DB system_prompt 是 PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION →
    一步升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT。
    """
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles.PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert len(primary_upserts) == 1


def test_primary_system_prompt_already_fetch_direct_no_upsert(monkeypatch):
    """DB system_prompt 已是 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT → 0 upsert。"""
    stored = {
        "primary": {
            "id": "primary", "enabled": True, "tools": [],
            "system_prompt": profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT,
        },
    }
    repo = FakeRepo(stored)
    monkeypatch.setattr(profiles, "_repo_factory_for_tests", lambda: repo)
    profiles.ensure_default_agents()
    assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
    primary_upserts = [u for u in repo.upserts if u["id"] == "primary"]
    assert primary_upserts == [], f"primary 不应被 upsert，但收到: {primary_upserts}"
```

同时，修改既有 `test_legacy_primary_system_prompt_gets_upgraded`（line 118-131）：把第 131 行
`assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION`
改为 `assert stored["primary"]["system_prompt"] == profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`。

修改既有 `test_current_primary_system_prompt_untouched`（line 151-167）：把 `system_prompt` 播种值改为
`profiles.PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT`，断言值同步改。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_intranet_web_access_migration.py -v
```

期望：5 个新测试 FAIL（`PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` 未定义 + `web_fetch/http_download` 不在 primary.tools）+ 1 个既有测试 FAIL（final state 改后不匹配）。

- [ ] **Step 3: profiles.py 改 3 处**

**(a)** 在 `PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION` 定义（line 200-205）之后，插入：

```python
# 2026-09-03 (post-§2 subset 迁移): primary 也可直接 fetch/download。
# 保留委派段 (复杂研究仍走子代理); 加一段明确指引 simple fetch/download
# 可由 primary 直调 —— 用户可见 LLM 行为, 便于分步指导。
PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT = (
    "你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。\n\n"
    "你可以直接调用 web_fetch（取网页内容）和 http_download（下载文件到工作区）"
    "进行简单的网页访问/文件下载，让用户能实时看到你访问的 URL 和下载的文件，"
    "便于分步指导和交互。\n"
    "对于复杂的多步研究任务，使用 agent 工具委派给只读子代理执行"
    "（子代理具备 web_search / web_fetch / http_download / memory_search 等只读工具）。"
    "直接回答时不要假装调用了这些工具。"
)
```

**(b)** 修改 `create_default_agents()` 中 primary profile（line 68）：把
`system_prompt=PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION,`
改为 `system_prompt=PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT,`。

**(c)** 修改 `create_default_agents()` 中 primary profile tools 列表（line 73-89）：
在 `"todo_write",` 之后追加两项（保持原有注释风格）：

```python
                # P1 todo 接线 (2026-08-21): 任务清单工具 —— 主助手可在多步
                # 任务中记录/更新计划（todo_state 存会话，无文件副作用）。
                "todo_write",
                # 2026-09-03 (post-§2 subset 迁移): 用户可见 LLM 取页/下载行为,
                # 便于分步指导和交互。OFFLINE 模式下 ToolRegistry 不注册,
                # primary 白名单里有也调不到 (NetworkPolicy 门禁)。
                "web_fetch",
                "http_download",
```

**(d)** 修改 `ensure_default_agents()` 中 primary system_prompt 升级段（line 251-253）：

把
```python
        if primary.get("system_prompt") == _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION:
            primary["system_prompt"] = PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION
            repo.upsert(primary)
```
改为链式合并版：
```python
        # 2026-09-03 (post-§2 subset 迁移): system_prompt 二段升级链。
        # BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT
        # 顺序敏感; 任何一段命中就一气呵成, 合并为单次 upsert 防抖动。
        prompt = primary.get("system_prompt")
        if prompt == _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION:
            prompt = PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION
        if prompt == PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION:
            prompt = PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
        if prompt != primary.get("system_prompt"):
            primary["system_prompt"] = prompt
            repo.upsert(primary)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profiles_intranet_web_access_migration.py -v
```

期望：原 10 个用例 + 新 4 个用例 + 2 个改写用例 = **全 PASS**（具体数字：14 个左右）。

- [ ] **Step 5: 跑整个 unit 套，确认无回归**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/ -q
```

期望：**0 fail**。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage && git add backend/agents/profiles.py backend/tests/unit/test_profiles_intranet_web_access_migration.py && \
  git commit -m "fix(agents): primary 直接 fetch/download - 工具白名单 + system_prompt 链式升级

PR #396 (d6185b76) 设 primary 为 '全委派' 模式 —— 出网任务全部
走 agent 工具委派给只读子代理。简单任务 ('帮我取这个 URL')
和分步指导场景 ('先打开 A 页面, 再点 X 按钮') 用户体验欠佳:
用户看不到 LLM 访问了哪个 URL, 无法分步交互。

本 commit 在 primary.tools 加 web_fetch + http_download
(只读 / 用户可见 / 受 NetworkPolicy 门禁), 把 system_prompt
升级到 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT:
- 直接 fetch/download 段: 简单任务直调, 用户可见 LLM 行为
- 保留委派段: 复杂多步研究仍走子代理, 不破坏 PR #396 边界

存量 DB system_prompt 升级段改为链式合并:
  BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT
合并为单次 upsert (防 updated_at 抖动)。

加 4 个测试 + 改 2 个既有测试:
- test_default_seed_primary_includes_fetch_download
- test_default_seed_primary_uses_fetch_direct_prompt
- test_primary_system_prompt_legacy_two_step_chain_migration
- test_primary_system_prompt_with_delegation_one_step_migration
- test_primary_system_prompt_already_fetch_direct_no_upsert
- 既有 test_legacy_/test_current_primary_system_prompt_* 改 final state

守 spec §4 架构边界: primary 仍不加 bash, coordinator/executor 分离
不变; 只追加 2 个只读工具 + 1 个新 system_prompt 常量。"
```

---

## Self-Review

**1. Spec coverage：**

| Spec § | 要求 | 覆盖任务 |
|---|---|---|
| §1 工具名重命名迁移 | LEGACY_TOOL_NAME_RENAMES 全表 + 启动时遍历所有 agent | Task 2 |
| §2 subset 迁移 | `_append_missing_tools` + 兜底段（当前默认 ⊆ DB → 追加缺的）| Task 3 |
| §2.4 既有 4 段不动 | 不删既有 _BEFORE_* 段 | ✓（Task 3 在最后追加兜底段，不删任何 _BEFORE_*） |
| §3 coder 硬编码修正 | `profiles.py:113` 4 个名字对齐 | Task 1 ✅ |
| §4 primary 不加 bash | 守 PR #396 边界 | Task 3（`_PRIMARY_CURRENT_DEFAULT_TOOLS` 不含 bash）+ Task 5 测试 `test_default_seed_primary_includes_fetch_download` 断言期望列表不含 bash |
| §5 primary 直接 fetch/download | primary.tools 加 web_fetch/http_download + system_prompt 升级到 WITH_FETCH_DIRECT + 链式合并为单次 upsert | Task 5 |
| §6.1 测试覆盖 6 个用例 | terminal / file_read / file_write / user extras / idempotent / only 3 names / 跨 agent | Task 2（6 用例 + 跨 agent 1 用例 = 6 个） |
| §6.2 测试覆盖 6 个用例 | primary 子集/超集/不相交 + researcher 子集 + 当前不 upsert + 幂等 | Task 3（6 个用例） |
| §6.3 既有测试加断言 | `test_default_seed_coder_uses_current_tool_names` | Task 1 ✅ |
| §6.3 §5 加 4 个断言 | fetch_direct default seed / legacy chain / one-step / no-upsert | Task 5 |
| §7 验收清单 | sqlite 终态 / 重启幂等 / CHANGELOG | Task 4 |
| §8 风险回滚 | git revert | 不在 plan 范围，merge 后运维 |

**2. Placeholder scan：** 无 `TBD / TODO / "implement later" / "similar to Task N" / "add appropriate error handling"`。所有代码块、命令、断言内容完整。

**3. Type consistency：**
- `LEGACY_TOOL_NAME_RENAMES: Dict[str, str]` —— Task 2 测试用 `["terminal", "calculator"]` 字面量，与实现映射一致
- `_append_missing_tools(agent: dict, current_default_tools: List[str]) -> bool` —— Task 3 测试 `stored["primary"]` 是 `dict`、`profiles._PRIMARY_CURRENT_DEFAULT_TOOLS` 是 `List[str]`、返回值用作 `if _append_missing_tools(...)` 布尔分支
- `_PRIMARY_CURRENT_DEFAULT_TOOLS: List[str]` (12 元素, 含 web_fetch/http_download) —— Task 3 测试 `assert stored["primary"]["tools"] == expected` 其中 `expected = legacy_5 + [7 个新工具]`，与实现定义的 12 个元素顺序一致
- `_RESEARCHER_CURRENT_DEFAULT_TOOLS: List[str]` (4 元素) —— Task 3 测试用 `["web_fetch", "http_download", "memory_search"]` + 缺 `web_search`，与实现定义的 `["web_search", "web_fetch", "http_download", "memory_search"]` 顺序一致（追加 `web_search` 到尾部）
- `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT: str` —— Task 5 测试既验 full equality 又验关键字（`web_fetch` / `http_download` / 委派段），与常量定义一致；链式升级测试验 `len(primary_upserts) == 1` 证明合并为单次 upsert

**4. Spec 范围检查：** spec 聚焦 1 个子系统（profiles.py 迁移恢复）→ 单个 plan 即可。

**5. FakeRepo 调整：** Task 2 / Task 3 测试用 `list_all()` 方法（Task 2 重命名段用 `repo.list_all()`）。Task 2 FakeRepo 加 `list_all`；既有 `test_profiles_intranet_web_access_migration.py` 的 FakeRepo 不改（其测试不需要 list_all）。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-03-agent-profile-migration-recovery.md`.

**两个执行选项：**

**1. Subagent-Driven (recommended)** —— 每个 Task 派一个独立子代理，task 间做两阶段 review（code-reviewer agent + 用户），迭代更快，token 消耗高。

**2. Inline Execution** —— 在当前 session 按 executing-plans 批量跑，批量节点设 checkpoint 让你介入。token 消耗低，context 累积。

你想走哪种？或者直接开始 Task 1？