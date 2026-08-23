# 编排 P2 批次实施计划（五项收尾）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成编排子系统剩余 5 项 P2：子任务 schema 结构化返回、SendMessage 式子代理续聊、worktree 级隔离、legacy 启发式编排器清理、LaneBoard API 层激活；全部在 main 合并后 cherry-pick 到 release/win7。

**Architecture:** 前四项集中在 `backend/orchestration/`（chat_dispatcher / subagent_runner / subagent_tool）与其工具层；第 5 项是后端小改 + Electron IPC + 前端接线。所有后端改动遵循现有"降级铁律"（推送/落库/隔离失败一律 logger.warning 不阻塞聊天）。

**Tech Stack:** Python 3.11 (FastAPI + pydantic 2.x)、React + TypeScript + Zustand、Electron IPC（commands.ts 声明式映射）、pytest + vitest。

**Spec:** 出处 `docs/superpowers/specs/2026-08-21-orchestration-p1-topology-todo-design.md` §14「非目标」清单（本计划即这五项的设计+实施合一文档）。

## Global Constraints（每个任务隐式遵守）

- **Python 环境**：一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`，禁止系统 python/pip。
- **py3.8 兼容**（win7 cherry-pick 前提）：禁 PEP 604 运行时 union（`X | Y` 注解仅限 `from __future__ import annotations` 下函数签名；isinstance 场景必须 `Union`/`Optional` 显式导入）；禁 `zip(strict=)`；禁 match 语句；模块级变量注解不得带 forward-ref 引号（Ruff UP037）。
- **降级铁律**：SSE 推送、落库、隔离措施失败 → `logger.warning/debug` + 功能降级，绝不抛穿阻塞聊天主流程。
- **事件协议兼容**：`task_status` 事件现有字段不得删除/改名；新字段只能追加（可选语义）。
- **代码规约**：函数 <50 行（复杂逻辑拆私有函数）；文件 <800 行；错误显式处理；无 console.log / print 调试语句；ruff + pytest 全绿才算完成。
- **测试命令**：
  - 后端单测：`cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/<file> -q`
  - lint：`cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .`
  - 前端：`npx vitest run <path>`、`npx tsc --noEmit`（在仓库根）。
- **提交规约**：conventional commits（feat:/refactor:/chore:）；中文正文可；不加 attribution 尾注。
- **分支**：全部工作在 `feat/orchestration-p2-batch` 分支（自 main 切出），5 个任务各 1 个 commit，最后开 1 个 PR。

---

### Task 1: 子任务 schema 结构化返回

**背景**：`ChatDispatcher._aggregate` 把子任务自由文本截断（50KB/项）拼进 conductor 上下文，总量兜底 120KB 再截——截断是症状缓解不是根源。给子任务加可选 `output_schema`，子 agent 按约定输出 JSON，校验通过后以紧凑 JSON 进聚合，信息密度大幅提高。

**Files:**
- Modify: `backend/tools/subagent_tool.py`（INPUT_SCHEMA.tasks.items 加 `output_schema`）
- Modify: `backend/orchestration/chat_dispatcher.py:113-125`（ChatTaskState 加字段）+ `dispatch()` 路由 + `_run_subagent` 传参
- Modify: `backend/orchestration/subagent_runner.py`（schema 注入 prompt + 结果提取校验）
- Test: `backend/tests/unit/test_subagent_runner.py`、`backend/tests/unit/test_subagent_tool.py`、`backend/tests/unit/test_chat_dispatcher.py`

**Interfaces:**
- Consumes: `backend/tools/structured_output_tool.py` 的 `validate_against_schema(data, schema) -> List[str]`（已存在，勿改其行为）。
- Produces: `ChatTaskState.output_schema: Optional[Dict[str, Any]]`；`SubagentRunner` 从 `task.parameters["output_schema"]`（dict 或 None）读取；dispatch items 支持可选键 `"output_schema"`（object）；runner 返回 dict 携带 `"messages"` 键（Task 2 消费）。

- [ ] **Step 1: 写失败测试 —— JSON 提取函数**

在 `backend/tests/unit/test_subagent_runner.py` 追加（import 区加 `from backend.orchestration.subagent_runner import extract_json_payload`）：

```python
class TestExtractJsonPayload:
    def test_pure_json(self):
        assert extract_json_payload('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        text = '前言\n```json\n{"a": 1}\n```\n后记'
        assert extract_json_payload(text) == {"a": 1}

    def test_embedded_json(self):
        text = '结果如下：\n{"a": {"b": 2}}\n以上。'
        assert extract_json_payload(text) == {"a": {"b": 2}}

    def test_non_json_returns_none(self):
        assert extract_json_payload("纯文本回复，没有 JSON") is None

    def test_invalid_json_returns_none(self):
        assert extract_json_payload('{"a": ') is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py::TestExtractJsonPayload -q`
Expected: FAIL（ImportError: cannot import name 'extract_json_payload'）

- [ ] **Step 3: 实现 extract_json_payload**

在 `backend/orchestration/subagent_runner.py` 加模块级函数：

```python
def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出文本提取 JSON object；三种形态依次尝试，失败返回 None。

    优先级：整段即 JSON > ``` 围栏 > 首个 ``{`` 到末个 ``}`` 子串。
    """
    candidate = (text or "").strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    fence_start = candidate.find("```json")
    if fence_start == -1:
        fence_start = candidate.find("```")
    if fence_start != -1:
        body_start = candidate.find("\n", fence_start)
        fence_end = candidate.find("```", fence_start + 3)
        if body_start != -1 and fence_end > body_start:
            try:
                parsed = json.loads(candidate[body_start + 1 : fence_end].strip())
                return parsed if isinstance(parsed, dict) else None
            except ValueError:
                pass
    brace_start = candidate.find("{")
    brace_end = candidate.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            parsed = json.loads(candidate[brace_start : brace_end + 1])
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            return None
    return None
```

模块顶部补 `import json`（现文件未导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_subagent_runner.py::TestExtractJsonPayload -q`
Expected: PASS

- [ ] **Step 5: 写失败测试 —— runner 的 schema 注入与校验降级**

在 `test_subagent_runner.py` 追加（沿用该文件既有 fake agent/event 桩模式）：

```python
@pytest.mark.asyncio()
async def test_output_schema_success_returns_compact_json():
    """声明 schema 且子 agent 输出合法 JSON → output 为紧凑 JSON 字符串。"""
    # 桩 run_loop yield DONE 事件，content 为围栏 JSON；
    # 断言 result["status"]=="succeeded" 且 output 为 separators=(",",":") 紧凑形式
    # 且返回 dict 含 "messages" 键


@pytest.mark.asyncio()
async def test_output_schema_violation_falls_back_to_raw():
    """schema 校验失败 → 降级返回原文（不 fail 任务）。"""
    ...

@pytest.mark.asyncio()
async def test_no_schema_keeps_raw_behavior():
    """未声明 schema → 与旧版行为一致（回归守卫）。"""
    ...
```

- [ ] **Step 6: 实现 runner 侧逻辑**

`SubagentRunner.__call__` 内：

1. `schema = task.parameters.get("output_schema")`（非 dict 视为 None）。
2. schema 存在时 user message content 追加：
   `\n\n输出格式硬性要求：你的最终回复必须只包含一个符合以下 JSON Schema 的 JSON 对象（可放在代码围栏中），不要输出其他文字。\n` + `json.dumps(schema, ensure_ascii=False)`
3. `collected` 拼接为 `raw_output` 后：schema 存在 → `payload = extract_json_payload(raw_output)`；
   - payload 非 None 且 `validate_against_schema(payload, schema)` 为空 → `return {"status": "succeeded", "output": json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "messages": messages}`
   - 否则 `logger.warning("子任务 %s 结构化输出校验失败，降级原文", getattr(task, "task_id", "?"))` → 走原文路径。
4. 无 schema → 原路径；返回值同样带 `"messages": messages` 键（Task 2 消费者本任务先行铺设）。

顶部 import：`import json`、`from backend.tools.structured_output_tool import validate_against_schema`。

- [ ] **Step 7: 跑 runner 测试确认通过**

Run: `pytest tests/unit/test_subagent_runner.py -q`
Expected: PASS（含存量测试）

- [ ] **Step 8: 写失败测试 —— 工具 schema 与 dispatcher 透传**

`test_subagent_tool.py` 追加：断言工具 schema 的 `tasks.items.properties` 含 `output_schema`（type=object）。

`test_chat_dispatcher.py` 追加：

```python
@pytest.mark.asyncio()
async def test_dispatch_passes_output_schema_to_subagent(monkeypatch):
    """tool-passed output_schema 进入 ChatTaskState 并写进 Task.parameters。"""
    captured = {}

    async def fake_run_subagent(state):
        captured["schema"] = state.output_schema
        return "ok"

    ...  # 构造 dispatcher（参考文件内既有 fixture），monkeypatch _run_subagent
    await dispatcher.dispatch([{"task_id": "t1", "agent_id": "primary",
                                "goal": "g", "output_schema": {"type": "object"}}])
    assert captured["schema"] == {"type": "object"}
```

- [ ] **Step 9: 实现透传**

1. `subagent_tool.py` INPUT_SCHEMA tasks items properties 加：
   `"output_schema": {"type": "object", "description": "可选 JSON Schema；子 agent 最终回复将被约束/校验为符合它的 JSON 对象"}`。
2. `chat_dispatcher.py`：`ChatTaskState` 加字段 `output_schema: Optional[Dict[str, Any]] = None`；`dispatch()` 三条路由统一取 `raw.get("output_schema")`（非 dict → None）传入构造。
3. `_run_subagent`：`state.output_schema` 非 None 时 `task.parameters["output_schema"] = state.output_schema`。

- [ ] **Step 10: 全量验证 + 提交**

Run: `pytest tests/unit/test_subagent_tool.py tests/unit/test_chat_dispatcher.py tests/unit/test_subagent_runner.py -q` 全绿 + `ruff check .` 干净。

```bash
git add -A && git commit -m "feat(orchestration): 子任务可选 output_schema 结构化返回（JSON 提取+校验，失败降级原文）"
```

---

### Task 2: SendMessage 式子代理续聊（followup_of）

**背景**：conductor 对已完成子任务追问时只能重新派遣全新 agent，丢失上下文。`SageAgent.run_loop(messages)` 无状态（messages 就地修改），续聊 = 保存已完成任务的 messages 历史 + 以新 user message 重放。

**Files:**
- Modify: `backend/tools/subagent_tool.py`（items 加 `followup_of`）
- Modify: `backend/orchestration/chat_dispatcher.py`（`_histories` 存储 + 路由 + 隐式依赖）
- Modify: `backend/orchestration/subagent_runner.py`（history 重放，常量 `MAX_REPLAY_MESSAGES = 20`）
- Test: `backend/tests/unit/test_chat_dispatcher.py`、`backend/tests/unit/test_subagent_tool.py`

**Interfaces:**
- Consumes: Task 1 铺设的 runner 返回值 `"messages"` 键。
- Produces: dispatch items 可选键 `"followup_of"`（string，须为本 run 内 status=done 的 task_id）；`ChatTaskState.parent_task_id: Optional[str] = None`；runner 读 `task.parameters["history"]`（List[Dict] 或缺失）。

- [ ] **Step 1: 写失败测试 —— followup 路由与隐式依赖**

`test_chat_dispatcher.py` 追加：

```python
@pytest.mark.asyncio()
async def test_followup_task_inherits_done_parent_history():
    """followup_of 指向已完成任务 → runner 收到父任务 history + 隐式拓扑依赖。"""
    # 构造 dispatcher；桩 _run_subagent 把 t1 跑成 done 并预埋 _histories["t1"]
    # 再 dispatch [{"task_id":"t2","agent_id":"primary","goal":"追问","followup_of":"t1"}]
    # 断言：state.parent_task_id == "t1"；task.parameters["history"]==预埋历史；
    #       monkeypatch topology.build_waves 捕获 deps_by_id 含 t2→t1

@pytest.mark.asyncio()
async def test_followup_invalid_parent_degrades_to_new_task():
    """followup_of 指向不存在/未完成任务 → 降级普通新任务，parent_task_id 为 None。"""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_chat_dispatcher.py -q -k followup`
Expected: FAIL

- [ ] **Step 3: 实现 dispatcher 侧**

1. `__init__` 加 `self._histories: Dict[str, List[Dict[str, Any]]] = {}`。
2. `dispatch()` 路由段（三条分支之后构造 `ChatTaskState(...)` 处）：读 `followup_of = raw.get("followup_of")`；有效判定 = `isinstance(followup_of, str) and followup_of in self._states and self._states[followup_of].status == "done"`；有效 → `parent_task_id=followup_of`；有值但无效 → `logger.warning` 后置 None（降级新任务）。
3. `deps_by_id` 构建段：`if state.parent_task_id and state.parent_task_id not in deps_by_id[state.task_id]: deps_by_id[state.task_id].append(state.parent_task_id)`（拓扑调度天然保证父任务先跑）。
4. `_run_one` 成功分支后存历史：`_run_subagent` 保持返回 str 兼容既有 monkeypatch 测试；历史改由 runner 结果落库——具体做法：`_run_subagent` 内 `result["result"].get("messages")` 非 None 时 `self._histories[state.task_id] = list(messages)`。
5. `_run_subagent`：`state.parent_task_id` 有效时 `task.parameters["history"] = self._histories.get(state.parent_task_id, [])`。

- [ ] **Step 4: 实现 runner 侧 history 重放**

`SubagentRunner.__call__`：

```python
history = task.parameters.get("history")
if isinstance(history, list) and history:
    # 裁剪：保留 system（首条）+ 最近 MAX_REPLAY_MESSAGES 条
    trimmed = history[1:][-MAX_REPLAY_MESSAGES:]
    messages = [history[0], *trimmed, {"role": "user", "content": goal}]
else:
    messages = [{"role": "system", "content": child_system}, {"role": "user", "content": goal}]
```

注意：重放路径不再重复注入 child_system（history 首条已是当时的 system）。返回值照旧携带 `"messages"`。

- [ ] **Step 5: 工具 schema + 描述**

`subagent_tool.py` items properties 加：
`"followup_of": {"type": "string", "description": "可选：要追问的已完成子任务 task_id（本 run 内）。设置后 goal 作为追问消息发给同一子代理上下文，而非开新任务"}`；
`_TOOL_DESCRIPTION` 尾部追加：「对已完成的子任务需要补充要求/追问时，传 followup_of=<已完成 task_id> 继续同一上下文。」

- [ ] **Step 6: 全量验证 + 提交**

Run: `pytest tests/unit/test_chat_dispatcher.py tests/unit/test_subagent_tool.py tests/unit/test_subagent_runner.py tests/unit/test_chat_dispatcher_topology.py -q` 全绿 + ruff 干净。

```bash
git add -A && git commit -m "feat(orchestration): dispatch_subagents 支持 followup_of 子代理续聊（父任务对话历史重放 + 隐式拓扑依赖）"
```

---

### Task 3: worktree 级隔离（可选开关，默认关）

**背景**：当前子任务写入锁进 `<data>/orch_scratch/<run>/<task>/`。开启 worktree 隔离后，若会话绑定了 git 仓库工作区，子任务在 workspace 的临时 detached worktree 副本中工作，不污染用户检出。`Lane.worktree` 字段已预留（models.py:215）。**范围界定：worktree 仅作隔离沙盒，产物不自动 merge 回主工作区（YAGNI）。**

**Files:**
- Create: `backend/orchestration/worktree.py`
- Modify: `backend/orchestration/orch_settings.py`（`worktree_isolation: bool = False` + `_RAW_KEYS` 加 `"worktreeIsolation"`；类型守卫需加 bool 分支——现有实现只处理 int/str）
- Modify: `backend/orchestration/chat_dispatcher.py`（构造参 `workspace_root` + `_run_subagent` 接线 + finally 清理）
- Modify: `backend/orchestration/subagent_runner.py`（workspace_dir 优先于 scratch_dir 作 policy root）
- Modify: `backend/api/legacy_routes.py`（multi 分支构造 dispatcher 处透传会话绑定 workspace_path）
- Modify: `src/entities/setting/types.ts`（OrchSettings interface 加 `worktreeIsolation: boolean`）
- Test: `backend/tests/unit/test_worktree.py`（新建）、`backend/tests/unit/test_chat_dispatcher.py`（增补）、orch_settings 既有测试补 bool 用例

**Interfaces:**
- Produces: `worktree.create_worktree(repo: Path, dest: Path) -> bool` / `remove_worktree(dest: Path) -> None` / `is_git_repo(path: Path) -> bool`；`ChatDispatcher.__init__(..., workspace_root: Optional[str] = None)`；`OrchSettings.worktree_isolation: bool`。

- [ ] **Step 1: 写失败测试 —— worktree.py 基础函数**

`backend/tests/unit/test_worktree.py` 新建（真实 git 子进程 + tmp_path）：

```python
"""worktree 隔离基础函数测试 —— 真实 git 子进程 + tmp 目录。"""
import subprocess
from pathlib import Path

import pytest

from backend.orchestration.worktree import create_worktree, is_git_repo, remove_worktree

pytestmark = pytest.mark.unit


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-q", "-m", "init"], check=True)


def test_is_git_repo_true_and_false(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert is_git_repo(repo) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(plain) is False


def test_create_and_remove_worktree(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    dest = tmp_path / "wt"
    assert create_worktree(repo, dest) is True
    assert (dest / ".git").exists()  # worktree 的 .git 是文件指针
    remove_worktree(dest)
    assert not dest.exists()


def test_create_worktree_on_non_repo_returns_false(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert create_worktree(plain, tmp_path / "wt") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_worktree.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 worktree.py**

```python
"""Git worktree 隔离 —— 编排子任务的可选文件系统隔离层（P2）。

开启 ``orch.worktreeIsolation`` 且会话绑定 git 仓库工作区时，每个子任务在
workspace 的 detached worktree 副本中工作（write_file 锁进副本），结束后
副本即弃。**产物不自动 merge 回主工作区** —— 本层只提供「不弄脏用户检出」
的隔离语义，聚合仍走子任务文本结果。

所有 git 调用 subprocess + 超时保护；任何失败静默降级（返回 False /
no-op），由调用方回落 scratch 目录隔离。
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_S = 30


def _run_git(args: List[str], cwd: Optional[Path] = None) -> bool:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("git %s 失败: %s", args[:2], exc)
        return False


def is_git_repo(path: Path) -> bool:
    return path.is_dir() and _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)


def create_worktree(repo: Path, dest: Path) -> bool:
    """从 repo HEAD 建 detached worktree 到 dest。失败返回 False。"""
    if not is_git_repo(repo) or dest.exists():
        return False
    ok = _run_git(["worktree", "add", "--detach", str(dest), "HEAD"], cwd=repo)
    if not ok:
        logger.warning("worktree 创建失败 repo=%s dest=%s", repo, dest)
    return ok


def remove_worktree(dest: Path) -> None:
    """强制移除 worktree（含未提交变更）；dest 不存在则 no-op。"""
    if not dest.exists():
        return
    if not _run_git(["worktree", "remove", "--force", str(dest)]):
        logger.warning("worktree 移除失败（将遗留目录）: %s", dest)
    _run_git(["worktree", "prune"])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/test_worktree.py -q` → PASS

- [ ] **Step 5: 写失败测试 —— dispatcher 接线**

`test_chat_dispatcher.py` 追加：

```python
@pytest.mark.asyncio()
async def test_worktree_isolation_wires_policy_when_enabled(monkeypatch, tmp_path):
    """开关开 + workspace 是 git repo → parameters 带 workspace_dir；任务结束清理副本。"""
    # monkeypatch chat_dispatcher 模块内 create_worktree/is_git_repo/remove_worktree
    # 为可控桩；settings=OrchSettings(worktree_isolation=True)；
    # dispatcher 构造传 workspace_root=str(tmp_path)。断言 fake_run_subagent 收到的
    # task.parameters 含 workspace_dir；dispatch 返回后 remove 桩被调用。


@pytest.mark.asyncio()
async def test_worktree_disabled_or_non_repo_falls_back(monkeypatch, tmp_path):
    """开关关 / 非 git repo → parameters 无 workspace_dir，行为同旧版。"""
```

- [ ] **Step 6: 实现 dispatcher 接线**

1. `__init__` 加参 `workspace_root: Optional[str] = None` → `self.workspace_root`；加 `self._worktree_dirs: List[Path] = []`。
2. `_run_subagent` 在 `scratch_dir.mkdir(...)` 之后：

```python
workspace_dir = None
if self.settings.worktree_isolation and self.workspace_root:
    from backend.orchestration.worktree import create_worktree, is_git_repo

    repo = Path(self.workspace_root)
    if is_git_repo(repo):
        wt = (
            Path(get_database().db_path).parent
            / "orch_worktrees" / self.run_id / state.task_id
        )
        if create_worktree(repo, wt):
            workspace_dir = wt
            self._worktree_dirs.append(wt)
    if workspace_dir is None:
        logger.warning("worktree 隔离不可用，子任务 %s 回落 scratch", state.task_id)
```

`parameters` dict 加 `"workspace_dir": str(workspace_dir) if workspace_dir else None`；`_run_subagent` finally 中 `for wt in list(self._worktree_dirs): remove_worktree(wt)` + 清空列表。
3. `SubagentRunner.__call__`：`ws = task.parameters.get("workspace_dir")`；`policy_root = ws or scratch_dir`；`policy = ToolPolicy(workspace_root=policy_root) if policy_root else None`。
4. producer 接线（`legacy_routes.py` multi 分支构造 `ChatDispatcher(...)` 处，约 L1930）：仿 L2048-2054 的 `get_workspace_binding(get_database().get_connection(), data.session_id)` 取 `binding.workspace_path`，非空则作为 `workspace_root=` 传入（try/except 降级不传）。

- [ ] **Step 7: 配置项 + 前端类型对齐**

1. `orch_settings.py`：dataclass 加 `worktree_isolation: bool = False`；`_RAW_KEYS` 加 `"worktreeIsolation": "worktree_isolation"`；`load_orch_settings` 类型守卫加分支 `elif isinstance(current, bool) and isinstance(value, bool): settings = replace(settings, **{field_name: value})`。
2. `src/entities/setting/types.ts` OrchSettings 加 `worktreeIsolation: boolean; // false`。
3. orch_settings 既有单测（grep `load_orch_settings` 定位）补 bool 解析用例。

- [ ] **Step 8: 全量验证 + 提交**

Run: `pytest tests/unit/test_worktree.py tests/unit/test_chat_dispatcher.py tests/unit/test_subagent_runner.py -q` + `npx tsc --noEmit` + ruff。

```bash
git add -A && git commit -m "feat(orchestration): 可选 worktree 级隔离（git 工作区子任务副本，orch.worktreeIsolation 默认关）"
```

---

### Task 4: legacy 启发式编排器清理

**背景**：`core/legacy/orchestrator.py`（AgentOrchestrator，关键词启发式分流，460 行）是聊天编排正式上线前的过渡实现，已被 ChatDispatcher 体系完全取代。唯一生产入口是非流式 `POST /chat` 的 `_should_use_orchestrator` 分支——该端点无任何前端/Electron 调用方（前端只走 `/chat/stream`）。win7 分支同名文件仅差一处 py3.8 zip 适配，删除型 cherry-pick 冲突面极小。

**Files:**
- Delete: `backend/core/legacy/orchestrator.py`
- Delete: `backend/tests/unit/test_orchestrator_dispatch.py`、`backend/tests/unit/test_orchestrator_parallel.py`
- Verify-then-delete: `backend/tests/unit/test_orchestrator_scheduling.py`（head -30 确认 import 自 core.legacy.orchestrator；若实际测 scheduler/ 其他组件则保留）
- Modify: `backend/tests/unit/test_chat_routing.py`（删 `_should_use_orchestrator` 三连测试 + orchestrator 两测试；保留 single-agent 测试改名 `test_chat_route_uses_single_agent`；docstring 同步改写）
- Modify: `backend/api/legacy_routes.py`（删 `_should_use_orchestrator` L127-145；`/chat` handler 删 orchestrator 分支 L1561-1599 恒走单 SageAgent；handler docstring 去"阶段 2 分流"段）
- Modify: `backend/core/__init__.py`（删 orchestrator 导出行与 `__all__` 两项）

**Interfaces:** 无新接口；纯减法。

- [ ] **Step 1: 引用面终检**

Run:
```bash
grep -rn "AgentOrchestrator\|_should_use_orchestrator\|core.legacy.orchestrator\|\bIntent\b" \
  /home/fz/project/sage/backend /home/fz/project/sage/src /home/fz/project/sage/electron \
  --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v "test_orchestrator"
```
Expected: 仅剩计划列出的修改点。若出现其他引用 → STOP 报告后再动。

- [ ] **Step 2: 删除文件与导出**

```bash
git rm backend/core/legacy/orchestrator.py backend/tests/unit/test_orchestrator_dispatch.py backend/tests/unit/test_orchestrator_parallel.py
# test_orchestrator_scheduling.py 先 head -30 验证归属再决定 git rm 或保留
```

编辑 `backend/core/__init__.py` 删除两行导出与 `__all__` 对应两项。

- [ ] **Step 3: 简化 /chat handler**

`legacy_routes.py`：删 `_should_use_orchestrator` 整个函数；`chat()` handler 删 `if _should_use_orchestrator(...):` 至 else 前整段（保留原 else 分支为主体），docstring 改为「发送聊天消息（单 agent；流式编排见 /chat/stream）」。

- [ ] **Step 4: 清理测试**

按 Files 节改写 `test_chat_routing.py`；保留的 single-agent 测试直接断言 `mock_agent.chat.called`。

- [ ] **Step 5: 全量验证 + 提交**

Run: `pytest tests/unit/test_chat_routing.py -q` + 全仓 `ruff check .` + `/home/fz/anaconda3/envs/sage-backend/bin/python -c "import backend.main"`（导入健全性）。

```bash
git add -A && git commit -m "refactor(orchestration): 下线 legacy 启发式 AgentOrchestrator（/chat 恒走单 agent，聊天编排由 ChatDispatcher 承担）"
```

---

### Task 5: LaneBoard API 层激活（board IPC + freshness 前端接线）

**背景**：数据层（lane_board.py）与 HTTP `GET /orchestration/board`（orchestration_router.py:392）早已就绪，但 Electron commands.ts 无 `orchestration_board` 映射、前端 `LaneBoard.tsx` 用 listLanes 自行分组，board 快照的 `freshness_summary` 与 projection 协商从未被消费。

**Files:**
- Modify: `backend/api/orchestration_router.py:392-398`（board 端点加 `view` query 参数）
- Modify: `electron/commands.ts`（orchestration 段加 `orchestration_board`）
- Modify: `src/shared/api/orchestrationClient.ts`（加 `getBoard(view?)`）
- Modify: `src/shared/api/types.ts`（加 `LaneFreshnessInfo` / `FreshnessSummaryInfo` / `LaneBoardEntry` / `LaneBoardSnapshot`）
- Modify: `src/shared/api/index.ts`（桶导出新类型名——教训：不补则 import 方 tsc 失败）
- Modify: `src/entities/orchestration/laneBoardStore.ts`（加 `boardSummary` 状态）
- Modify: `src/widgets/orchestration/LaneBoard.tsx`（头部渲染整体新鲜度徽章）+ i18n `zh.ts`/`en.ts`
- Test: `backend/tests/unit/test_board_endpoint.py`（增补 view 用例）、`src/shared/api/__tests__/orchestrationClient.test.ts`（增补 getBoard）

**Interfaces:**
- Backend: `GET /api/v1/orchestration/board?view=ops_full|ui_minimal`（默认 ops_full=现行为；ui_minimal 走既有 `LaneBoardSnapshot.project`；非法 view → 400）。
- Frontend: `orchestrationClient.getBoard(): Promise<LaneBoardSnapshot>`；store 暴露 `boardSummary: FreshnessSummaryInfo | null`。

- [ ] **Step 1: 后端失败测试**

`test_board_endpoint.py` 追加：

```python
def test_board_endpoint_ui_minimal_projection():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board", params={"view": "ui_minimal"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "ui_minimal"
    assert "redaction_provenance" in body


def test_board_endpoint_unknown_view_400():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board", params={"view": "bogus"})
    assert resp.status_code == 400
```

- [ ] **Step 2: 实现后端 view 参数**

`board()` 签名改 `async def board(view: str = Query(default="ops_full"))`：

```python
snapshot = builder.build_snapshot(actor="http-api")
if view == "ops_full":
    return snapshot.to_dict()
from backend.orchestration.lane_board import ProjectionRequest, UnsupportedViewError
try:
    return snapshot.project(
        ProjectionRequest(consumer="http-api", requested_view=view)
    ).to_dict()
except UnsupportedViewError:
    raise HTTPException(status_code=400, detail=f"unsupported board view: {view}")
```

Run: `pytest tests/unit/test_board_endpoint.py -q` → PASS

- [ ] **Step 3: IPC + client + 类型**

1. `commands.ts` orchestration 段加：
```typescript
orchestration_board: {
  method: 'GET',
  path: (a) => {
    const view = a?.view ? `?view=${encodeURIComponent(String(a.view))}` : '';
    return `/api/v1/orchestration/board${view}`;
  },
},
```
2. `types.ts` 加（对齐 lane_board.py to_dict 形态）：
```typescript
export interface LaneFreshnessInfo {
  lane_id: string;
  last_heartbeat_at: number | null;
  age_ms: number | null;
  level: 'fresh' | 'stale' | 'dead';
  reasons: string[];
}
export interface FreshnessSummaryInfo {
  total: number; fresh: number; stale: number; dead: number;
  overall_level: 'fresh' | 'stale' | 'dead';
}
export interface LaneBoardEntry {
  lane_id: string; task_id: string; agent_id?: string | null; status: string;
  freshness?: LaneFreshnessInfo; heartbeat_status?: string | null;
  last_event_at?: number; last_event_type?: string;
}
export interface LaneBoardSnapshot {
  schema_version: string; generated_at: number; generated_by: string;
  active: LaneBoardEntry[]; blocked: LaneBoardEntry[]; finished: LaneBoardEntry[];
  freshness_summary: FreshnessSummaryInfo;
  /** projection 响应独有 */
  view?: string;
  redaction_provenance?: Record<string, string>;
}
```
3. `index.ts` 桶导出四个新类型名。
4. `orchestrationClient.ts` 加：
```typescript
async getBoard(view: 'ops_full' | 'ui_minimal' = 'ops_full'): Promise<LaneBoardSnapshot> {
  return invoke<LaneBoardSnapshot>('orchestration_board', { view });
},
```

- [ ] **Step 4: store + UI**

1. `laneBoardStore.ts`：state 加 `boardSummary: FreshnessSummaryInfo | null`；`load()` 内 `listLanes` 成功后调 `getBoard('ops_full')`（try/catch 失败置 null，不阻塞 lanes 渲染——降级铁律的前端对应物）。
2. `LaneBoard.tsx`：三列上方加摘要行（`boardSummary` 非空时）：`通道 X · 新鲜 F / 陈旧 S / 失联 D`，overall_level 映射色徽章（fresh=green / stale=yellow / dead=red）。i18n key 走 `zh.ts` 既有 `orchestration.*` 前缀新增 3-4 个（`en.ts` 同步）。
3. vitest：`orchestrationClient.test.ts` 补 getBoard 用例（mock invoke 断言 cmd 名与参数）。

- [ ] **Step 5: 全量验证 + 提交**

Run: `pytest tests/unit/test_board_endpoint.py -q` + `npx vitest run src/shared/api/__tests__/orchestrationClient.test.ts` + `npx tsc --noEmit` + ruff。

```bash
git add -A && git commit -m "feat(orchestration): LaneBoard 快照激活 —— board view projection + Electron IPC + 前端 freshness 摘要"
```

---

## 合并与同步

- 5 个 commit 全绿后 push 分支、开 PR（base main），CI 绿 + code review 后 squash 合并。
- 合并后 cherry-pick 到 `release/win7`：主动 grep py3.10+ 特性（PEP 604 runtime union / zip(strict=) / match）；冲突预期在 `orch_settings.py` 与 `src/entities/setting/types.ts`。win7 侧用 `sage-backend-py38` 环境跑定向测试。
- 文档归档：功能并入 `docs/technical/42-chat-multi-agent-orchestration.md` 新 §16，删除本计划文件，README 章节简介如涉及则同步。
