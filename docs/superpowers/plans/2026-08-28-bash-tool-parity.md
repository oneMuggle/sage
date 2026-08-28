# Bash 命令行工具对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 sage 的 shell 执行工具从「拒绝一切含 shell 操作符的命令」升级为对齐 Claude Code Bash tool 的完整能力：真实 shell 语法、后台执行 + 输出轮询 + 终止、有界输出、进程组回收、跨平台 shell 探测。

**Architecture:** 删除 `TerminalTool` 内部的粗粒度硬拦截（`_is_dangerous`），让危险命令判定收敛到既有的 `bash_validation.validate_bash` + `PermissionEnforcer` 分层安全模型。工具重命名为 `bash`，新增 `bash_output` / `kill_shell` 两个配套工具管理后台 shell。子进程原语（临时文件输出、有界读取、进程组终止）从 `repl_tool.py` 提取到共享模块，两个工具共用。

**Tech Stack:** Python 3.8+ 兼容标准库（`subprocess` / `tempfile` / `threading` / `shutil` / `uuid` / `functools` / `dataclasses`）；pytest；前端 TypeScript + vitest。

**Spec:** `docs/superpowers/specs/2026-08-28-bash-tool-parity-design.md`

## Global Constraints

- **Python 版本**：代码必须同时在 Python 3.11（`main` 分支）与 Python 3.8（`release/win7` 分支）运行。用 `typing.Dict` / `typing.List` / `typing.Optional` / `typing.Tuple`，**不用** PEP 585（`list[x]`）或 PEP 604（`X | Y`）的运行时形式。`from __future__ import annotations` 只让注解变字符串，`isinstance()` 和 `dataclass` 字段的运行时求值仍会在 3.8 崩溃 —— 项目历史上已因此踩过坑。
- **后端 Python 环境**：所有 pytest / ruff 命令必须用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不要用系统 `python3`（会 `ModuleNotFoundError: No module named 'fastapi'`）。
- **ruff 配置**：`backend/ruff.toml`，`line-length = 100`。`T20`（禁 print）、`ERA`（禁注释掉的代码）、`PTH`、`SIM`、`RET`、`PT`（pytest 风格）均启用。`UP006/UP007/UP035` 已禁用，正是为上面的 Py3.8 兼容。
- **工作目录**：pytest 与 vitest 都从**仓库根** `/home/fz/project/sage` 运行。`cd backend` 后跑 vitest 会报 `No test files found`。
- **代码注释**：默认不写注释。只在 WHY 不显然时写一行（隐藏约束、反直觉行为、特定 bug 的规避）。不写「这段代码做什么」。
- **语言**：docstring 与用户可见错误信息用中文，与现有 `backend/tools/` 各模块一致。
- **不加向后兼容 shim**：`terminal` 工具名不保留别名（项目 CLAUDE.md 与全局规范均要求）。唯一例外是 `src/shared/lib/humanize.ts` 的 `case 'terminal'`，那是历史会话数据的渲染兼容，不是工具别名。
- **提交粒度**：每个 Task 结束提交一次，conventional commits（`feat:` / `refactor:` / `test:` / `docs:`）。
- **分支**：`feat/bash-tool-parity`（已创建，spec 已提交在 `35faeed7`）。

---

## File Structure

**新建：**

| 文件 | 责任 | 行数预估 |
|---|---|---|
| `backend/tools/subprocess_util.py` | 子进程原语：临时输出文件、有界读取、进程组终止。无业务逻辑。 | ~90 |
| `backend/tools/shell_resolver.py` | 跨平台 shell 探测，返回 `ShellSpec`。纯函数 + 进程内缓存。 | ~80 |
| `backend/tools/bash_session.py` | 后台 shell 注册表（线程安全单例）+ 增量读游标。 | ~180 |
| `backend/tools/bash_tool.py` | `BashTool` / `BashOutputTool` / `KillShellTool` 三个工具类。 | ~280 |

**新建测试：**

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/test_subprocess_util.py` | 有界读取、截断标记、进程组终止 |
| `backend/tests/unit/test_shell_resolver.py` | POSIX / Git Bash / PowerShell 三路径 |
| `backend/tests/unit/test_bash_session.py` | 注册/查表/增量游标/容量上限/未知 id |
| `backend/tests/unit/test_bash_tool.py` | 同步执行 + 后台三工具端到端 |

**删除：**

- `backend/tools/terminal.py` → 被 `bash_tool.py` 取代
- `backend/tests/unit/test_terminal.py` → 被 `test_bash_tool.py` 取代

**修改：**

| 文件 | 改动 |
|---|---|
| `backend/tools/repl_tool.py` | 三个内部函数改为从 `subprocess_util` import |
| `backend/tools/__init__.py` | import / `register_all_tools` / `__all__` |
| `backend/tools/permissions.py:71` | `TOOL_CAPABILITIES` 三项 |
| `backend/domain/risk.py:47-48` | `SHELL_TOOLS` / `WRITE_TOOLS` |
| `backend/agents/profiles.py:109` | coder profile 工具列表 |
| `backend/orchestration/permission.py:58-63` | 注释中的工具名 |
| `src/shared/lib/humanize.ts:73-79` | 新增三个 case |
| `docs/technical/README.md` | 新增第 44 章条目 |
| `docs/technical/44-bash-tool.md` | 新建技术文档章节 |

**测试引用面修改**（Task 6 统一处理）：`test_risk.py`、`test_permission.py`、`test_permissions_enforcer.py`、`test_inproc_tool_adapter.py`、`test_hooks.py`、`test_agent_permission_flow.py`、`test_hooks_integration.py`。

---

## Task 1: 提取共享子进程原语

`repl_tool.py` 已经解决了「有界读输出 + 杀进程组」这两个问题，`bash_tool` 需要同样的能力。这个 Task 是**纯移动**：把三个函数搬到新模块，`repl_tool` 改为 import。零行为变化 —— `repl_tool` 的现有 15 个测试就是回归门禁。

**Files:**
- Create: `backend/tools/subprocess_util.py`
- Create: `backend/tests/unit/test_subprocess_util.py`
- Modify: `backend/tools/repl_tool.py:26-52`（imports + 常量）、`:80-127`（删除被搬走的三个函数）

**Interfaces:**
- Consumes: 无（本 Task 是起点）
- Produces:
  - `make_temp_output_file(prefix: str = "sage_") -> str`
  - `read_capped_output(file_path: str, cap: int, offset: int = 0) -> Tuple[str, bool, int]` — 返回 `(文本, 是否截断, 新偏移)`
  - `kill_process_tree(process: subprocess.Popen) -> None`
  - `unlink_quietly(path: str) -> None`

  注意 `read_capped_output` 比 `repl_tool` 原版多了 `offset` 参数与返回的新偏移 —— Task 3 的后台增量读需要它。`offset=0` 时行为与原版一致（读文件开头）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_subprocess_util.py`：

```python
"""subprocess_util 共享子进程原语单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backend.tools.subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    unlink_quietly,
)

pytestmark = pytest.mark.unit


def test_make_temp_output_file_creates_empty_readable_file():
    """建出的文件存在且为空。"""
    # Arrange / Act
    path = make_temp_output_file()

    # Assert
    try:
        assert os.path.exists(path)
        with open(path, "rb") as handle:
            assert handle.read() == b""
    finally:
        unlink_quietly(path)


def test_read_capped_output_returns_full_text_under_cap():
    """内容小于上限 → 完整返回, 未截断, 偏移等于字节数。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"hello world")

    # Act
    try:
        text, truncated, offset = read_capped_output(path, cap=1024)
    finally:
        unlink_quietly(path)

    # Assert
    assert text == "hello world"
    assert truncated is False
    assert offset == 11


def test_read_capped_output_truncates_beyond_cap():
    """内容超上限 → 截断标记 + 文本长度不超上限余量。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"y" * 5000)

    # Act
    try:
        text, truncated, offset = read_capped_output(path, cap=100)
    finally:
        unlink_quietly(path)

    # Assert
    assert truncated is True
    assert "已截断" in text
    assert offset == 100


def test_read_capped_output_honors_offset_for_incremental_reads():
    """从 offset 起读 → 只拿新增部分（后台增量读的核心语义）。"""
    # Arrange
    path = make_temp_output_file()
    with open(path, "wb") as handle:
        handle.write(b"first")

    # Act
    try:
        text1, _, offset1 = read_capped_output(path, cap=1024)
        with open(path, "ab") as handle:
            handle.write(b"second")
        text2, _, offset2 = read_capped_output(path, cap=1024, offset=offset1)
    finally:
        unlink_quietly(path)

    # Assert
    assert text1 == "first"
    assert text2 == "second"
    assert offset2 == 11


def test_read_capped_output_missing_file_returns_error_text_not_raise():
    """文件不存在 → 返回错误说明文本, 不抛异常（清理路径不允许崩）。"""
    # Arrange / Act
    text, truncated, offset = read_capped_output("/nonexistent/path/xyz", cap=1024)

    # Assert
    assert "读取子进程输出失败" in text
    assert truncated is False
    assert offset == 0


def test_kill_process_tree_kills_grandchild_on_posix(tmp_path):
    """POSIX: 杀进程组连孙进程一起收（孙进程不留下 marker 文件）。"""
    # Arrange
    if os.name == "nt":
        pytest.skip("进程组语义仅在 POSIX 验证")
    marker = tmp_path / "orphan.txt"
    child_code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"\"import time; time.sleep(3); open({str(marker)!r}, 'w').write('orphan')\"])\n"
        "time.sleep(5)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.5)

    # Act
    kill_process_tree(process)

    # Assert
    time.sleep(4)
    assert not marker.exists(), "孙进程存活并写了 marker → 进程组未被完整终止"


def test_unlink_quietly_on_missing_path_does_not_raise():
    """删不存在的文件静默返回。"""
    # Arrange / Act / Assert — 不抛即通过
    unlink_quietly("/nonexistent/path/xyz")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py -q
```

Expected: 收集失败，`ModuleNotFoundError: No module named 'backend.tools.subprocess_util'`

- [ ] **Step 3: 创建 subprocess_util.py**

```python
"""子进程执行共享原语（bash_tool 与 repl_tool 共用）。

三件事在两个工具里需求完全相同，因此收在一处：

- **输出走临时文件**：子进程 stdout/stderr 重定向到磁盘而非父进程 PIPE。
  PIPE 会无限缓冲——命令打印几个 GB 就撑爆后端内存；临时文件把父进程
  内存占用固定为一次读取的上限。
- **有界读取**：只读前 ``cap`` 字节（可从 ``offset`` 起，供后台增量轮询）。
- **杀进程组**：POSIX 下 ``os.killpg`` 连孙进程一起收；Windows 退化为
  ``process.kill()``（杀不到孙进程，已知限制）。调用方必须以
  ``start_new_session=True`` 启动进程，否则 POSIX 上拿不到独立进程组。
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import tempfile
from typing import Tuple

logger = logging.getLogger(__name__)

#: 读输出时多读的字节数——超过上限 1 字节即判定截断
_OUTPUT_OVERREAD_MARGIN = 1

#: 杀进程组后回收子进程的宽限超时（秒）
_REAP_TIMEOUT_SECONDS = 5.0


def make_temp_output_file(prefix: str = "sage_") -> str:
    """建一个承接子进程输出的空临时文件，返回路径（调用方负责删除）。"""
    handle = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".out", delete=False)
    handle.close()
    return handle.name


def read_capped_output(file_path: str, cap: int, offset: int = 0) -> Tuple[str, bool, int]:
    """从 ``offset`` 起读至多 ``cap`` 字节；返回 ``(文本, 是否截断, 新偏移)``。

    父进程内存占用恒定 ≤ ``cap`` + margin——子进程打印多少都不全量读。
    ``offset`` 支持后台 shell 的增量轮询：调用方存下返回的新偏移，下次
    从那里继续。

    读取失败（文件被删、权限变更等）返回说明文本而非抛异常——本函数常在
    清理路径调用，不允许崩。
    """
    try:
        with open(file_path, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(cap + _OUTPUT_OVERREAD_MARGIN)
    except OSError as exc:
        return f"[读取子进程输出失败: {exc}]", False, offset
    if len(raw) <= cap:
        return raw.decode("utf-8", errors="replace"), False, offset + len(raw)
    capped = raw[:cap].decode("utf-8", errors="replace")
    cap_kib = cap // 1024
    return (
        f"{capped}\n...[输出超过 {cap_kib} KiB 上限，已截断]",
        True,
        offset + cap,
    )


def kill_process_tree(process: subprocess.Popen) -> None:
    """杀整个进程组（POSIX）或进程自身（Windows 尽力，杀不到孙进程）。"""
    try:
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # 组号拿不到（极端竞态）→ 退化只杀子进程本体
                process.kill()
        else:
            process.kill()
    except Exception:  # noqa: BLE001 — 清理路径：杀失败也不允许抛出
        logger.debug("子进程终止失败", exc_info=True)
    try:
        process.communicate(timeout=_REAP_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — 同上
        logger.debug("子进程回收失败", exc_info=True)


def unlink_quietly(path: str) -> None:
    """删临时文件；不存在/被占用等一律静默（清理路径不报错）。"""
    with contextlib.suppress(OSError):
        os.unlink(path)


__all__ = [
    "make_temp_output_file",
    "read_capped_output",
    "kill_process_tree",
    "unlink_quietly",
]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py -q
```

Expected: 7 passed（POSIX 上；Windows 上 6 passed 1 skipped）

- [ ] **Step 5: 改 repl_tool.py 复用新模块**

在 `backend/tools/repl_tool.py` 中做三处改动。

改动 A —— 替换 import 段（原第 26-38 行）：

```python
import logging
import subprocess
import sys
import tempfile
import time
from typing import Tuple

from .base import BaseTool, ToolResult, ToolSchema
from .subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    unlink_quietly,
)

logger = logging.getLogger(__name__)
```

（删掉了 `contextlib` / `os` / `signal` —— 搬走的函数带走了它们的用途；`Tuple` 保留给下面的包装函数。）

改动 B —— 删除原第 48-52 行的两个常量：

```python
#: 读输出临时文件时多读的字节数——超过上限 1 字节即判定截断
_OUTPUT_OVERREAD_MARGIN = 1

#: 杀进程组后回收子进程的宽限超时（秒）
_REAP_TIMEOUT_SECONDS = 5.0
```

它们现在住在 `subprocess_util` 里。`MAX_OUTPUT_BYTES = 100 * 1024` **保留** —— repl 的 schema 描述承诺了 100 KiB，不改。

改动 C —— 删除原第 80-127 行的 `_make_temp_output_file` / `_read_capped_output` / `_kill_process_tree` / `_unlink_quietly` 四个函数定义，替换为两个薄包装：

```python
def _make_temp_output_file() -> str:
    """建一个承接子进程输出的空临时文件（repl 前缀）。"""
    return make_temp_output_file(prefix="sage_repl_")


def _read_capped_output(file_path: str) -> Tuple[str, bool]:
    """读输出文件前 ``MAX_OUTPUT_BYTES`` 字节；返回 (文本, 是否截断)。"""
    text, truncated, _offset = read_capped_output(file_path, cap=MAX_OUTPUT_BYTES)
    return text, truncated
```

保留这两个薄包装而不是让调用点直接改用新函数，是因为 `_read_capped_output` 的两处调用点期望二元组，且 `test_repl_tool.py` 已有的断言（`MAX_OUTPUT_BYTES` 常量、截断标记文案）继续成立。

改动 D —— 把 `_kill_process_tree(process)` 的两处调用改为 `kill_process_tree(process)`，`_unlink_quietly(path)` 的调用改为 `unlink_quietly(path)`。用 grep 找全：

```bash
cd /home/fz/project/sage && grep -n "_kill_process_tree\|_unlink_quietly" backend/tools/repl_tool.py
```

- [ ] **Step 6: 运行 repl 回归测试**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_repl_tool.py -q
```

Expected: 全部通过（改动前的基线数量，`-q` 输出末行确认）。若 `test_repl_huge_output_capped_at_100kib` 失败，检查截断标记文案 —— 新函数用 `f"...[输出超过 {cap_kib} KiB 上限，已截断]"`，测试断言的是 `"已截断" in stdout`，应当仍匹配。

- [ ] **Step 7: lint**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/subprocess_util.py tools/repl_tool.py tests/unit/test_subprocess_util.py
```

Expected: `All checks passed!`

- [ ] **Step 8: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/subprocess_util.py backend/tools/repl_tool.py backend/tests/unit/test_subprocess_util.py
git commit -m "refactor(tools): 提取子进程原语到 subprocess_util 供 bash 工具复用

有界读输出与杀进程组的实现原本只在 repl_tool 内，bash 工具需要同一套
能力。read_capped_output 增加 offset 参数以支持后台 shell 的增量轮询。"
```

---

## Task 2: 跨平台 shell 探测

**Files:**
- Create: `backend/tools/shell_resolver.py`
- Create: `backend/tests/unit/test_shell_resolver.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ShellSpec` — frozen dataclass，字段 `executable: str`、`args_prefix: Tuple[str, ...]`、`kind: str`（取值 `"bash"` / `"sh"` / `"powershell"`）
  - `resolve_shell() -> ShellSpec` — 带 `lru_cache`，进程内探测一次
  - `resolve_shell_uncached() -> ShellSpec` — 无缓存版本，测试用
  - `SHELL_FALLBACK_NOTE: str` — PowerShell 降级时放进工具结果的提示文案

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_shell_resolver.py`：

```python
"""shell_resolver 跨平台 shell 探测单元测试。

全部用 monkeypatch 模拟 os.name / 文件存在性 / shutil.which，
不依赖运行测试的机器上实际装了什么。
"""

from __future__ import annotations

import pytest

from backend.tools import shell_resolver
from backend.tools.shell_resolver import resolve_shell_uncached

pytestmark = pytest.mark.unit


def test_posix_prefers_bin_bash(monkeypatch):
    """POSIX: /bin/bash 存在 → 用它, args_prefix 为 -c。"""
    # Arrange
    monkeypatch.setattr(shell_resolver.os, "name", "posix")
    monkeypatch.setattr(shell_resolver.os.path, "exists", lambda p: p == "/bin/bash")

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == "/bin/bash"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_posix_falls_back_to_bin_sh(monkeypatch):
    """POSIX: 无 /bin/bash → 退 /bin/sh。"""
    # Arrange
    monkeypatch.setattr(shell_resolver.os, "name", "posix")
    monkeypatch.setattr(shell_resolver.os.path, "exists", lambda p: p == "/bin/sh")

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == "/bin/sh"
    assert spec.kind == "sh"


def test_windows_uses_bash_from_path(monkeypatch):
    """Windows: PATH 里有 bash → 用它（Git Bash 常见形态）。"""
    # Arrange
    monkeypatch.setattr(shell_resolver.os, "name", "nt")
    monkeypatch.setattr(
        shell_resolver.shutil, "which", lambda name: r"C:\Git\bin\bash.exe" if name == "bash" else None
    )

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == r"C:\Git\bin\bash.exe"
    assert spec.args_prefix == ("-c",)
    assert spec.kind == "bash"


def test_windows_probes_program_files_git(monkeypatch):
    """Windows: PATH 无 bash → 探测 Program Files 下的 Git Bash。"""
    # Arrange
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    monkeypatch.setattr(shell_resolver.os, "name", "nt")
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: None)
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    monkeypatch.setattr(shell_resolver.os.path, "exists", lambda p: p == git_bash)

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.executable == git_bash
    assert spec.kind == "bash"


def test_windows_falls_back_to_powershell(monkeypatch):
    """Windows: 找不到任何 bash → 退 PowerShell, kind 标记降级。"""
    # Arrange
    monkeypatch.setattr(shell_resolver.os, "name", "nt")
    monkeypatch.setattr(shell_resolver.shutil, "which", lambda name: None)
    monkeypatch.setattr(shell_resolver.os.path, "exists", lambda p: False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)

    # Act
    spec = resolve_shell_uncached()

    # Assert
    assert spec.kind == "powershell"
    assert spec.args_prefix == ("-NoProfile", "-Command")


def test_resolve_shell_caches_result(monkeypatch):
    """resolve_shell 带缓存: 第二次调用不再探测文件系统。"""
    # Arrange
    shell_resolver.resolve_shell.cache_clear()
    calls = []

    def _counting_exists(path):
        calls.append(path)
        return path == "/bin/bash"

    monkeypatch.setattr(shell_resolver.os, "name", "posix")
    monkeypatch.setattr(shell_resolver.os.path, "exists", _counting_exists)

    # Act
    first = shell_resolver.resolve_shell()
    probe_count = len(calls)
    second = shell_resolver.resolve_shell()

    # Assert
    assert first == second
    assert len(calls) == probe_count, "第二次调用重新探测了文件系统"
    shell_resolver.resolve_shell.cache_clear()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_shell_resolver.py -q
```

Expected: 收集失败，`ModuleNotFoundError: No module named 'backend.tools.shell_resolver'`

- [ ] **Step 3: 创建 shell_resolver.py**

```python
"""跨平台 shell 探测。

模型写出的命令按 POSIX shell 语法（``&&`` ``|`` ``$()``）组织，所以优先
找真 bash：POSIX 上是 ``/bin/bash``，Windows 上是 Git Bash。Windows 找不到
bash 时退 PowerShell，此时把 ``SHELL_FALLBACK_NOTE`` 放进工具结果——让模型
知道语法可能不适用，而不是对着看不懂的报错反复重试。

``release/win7`` 分支尤其依赖 PowerShell 降级路径：Win7 机器未必装 Git。

探测结果进程内缓存一次（``resolve_shell``）。测试用 ``resolve_shell_uncached``
绕过缓存。
"""

from __future__ import annotations

import functools
import os
import shutil
from dataclasses import dataclass
from typing import Optional, Tuple

#: PowerShell 降级时放进 ToolResult.content 的提示，供模型调整命令写法
SHELL_FALLBACK_NOTE = (
    "未找到 bash（已尝试 PATH 与 Git for Windows 安装目录），"
    "改用 PowerShell 执行。bash 专有语法（&&、||、$()、管道到 sh）可能不生效，"
    "请改用 PowerShell 等价写法。"
)

_POSIX_CANDIDATES: Tuple[Tuple[str, str], ...] = (
    ("/bin/bash", "bash"),
    ("/bin/sh", "sh"),
)

#: Git for Windows 默认安装位置下的 bash 相对路径
_GIT_BASH_RELATIVE = os.path.join("Git", "bin", "bash.exe")


@dataclass(frozen=True)
class ShellSpec:
    """一次 shell 调用需要的全部信息。

    Attributes:
        executable:  shell 可执行文件路径
        args_prefix: 命令前的固定参数（bash 为 ``("-c",)``）
        kind:        ``"bash"`` / ``"sh"`` / ``"powershell"``
    """

    executable: str
    args_prefix: Tuple[str, ...]
    kind: str

    @property
    def is_fallback(self) -> bool:
        """是否为 PowerShell 降级（调用方据此附加 SHELL_FALLBACK_NOTE）。"""
        return self.kind == "powershell"


def _resolve_posix() -> ShellSpec:
    for path, kind in _POSIX_CANDIDATES:
        if os.path.exists(path):
            return ShellSpec(executable=path, args_prefix=("-c",), kind=kind)
    # 连 /bin/sh 都没有的 POSIX 系统极罕见；仍返回 /bin/sh 让 Popen 报
    # 具体的 FileNotFoundError，比在这里抛一个更模糊的异常有用。
    return ShellSpec(executable="/bin/sh", args_prefix=("-c",), kind="sh")


def _find_windows_bash() -> Optional[str]:
    from_path = shutil.which("bash")
    if from_path:
        return from_path
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_key)
        if not base:
            continue
        candidate = os.path.join(base, _GIT_BASH_RELATIVE)
        if os.path.exists(candidate):
            return candidate
    return None


def _resolve_windows() -> ShellSpec:
    bash_path = _find_windows_bash()
    if bash_path:
        return ShellSpec(executable=bash_path, args_prefix=("-c",), kind="bash")
    powershell = shutil.which("powershell") or "powershell.exe"
    return ShellSpec(
        executable=powershell,
        args_prefix=("-NoProfile", "-Command"),
        kind="powershell",
    )


def resolve_shell_uncached() -> ShellSpec:
    """探测可用 shell（不走缓存）。"""
    if os.name == "nt":
        return _resolve_windows()
    return _resolve_posix()


@functools.lru_cache(maxsize=1)
def resolve_shell() -> ShellSpec:
    """探测可用 shell（进程内缓存一次）。"""
    return resolve_shell_uncached()


__all__ = [
    "ShellSpec",
    "SHELL_FALLBACK_NOTE",
    "resolve_shell",
    "resolve_shell_uncached",
]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_shell_resolver.py -q
```

Expected: 6 passed

- [ ] **Step 5: lint + 提交**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/shell_resolver.py tests/unit/test_shell_resolver.py
cd /home/fz/project/sage
git add backend/tools/shell_resolver.py backend/tests/unit/test_shell_resolver.py
git commit -m "feat(tools): 跨平台 shell 探测（POSIX bash / Git Bash / PowerShell 降级）"
```

---

## Task 3: 后台 shell 注册表

**Files:**
- Create: `backend/tools/bash_session.py`
- Create: `backend/tests/unit/test_bash_session.py`

**Interfaces:**
- Consumes: `subprocess_util.make_temp_output_file` / `read_capped_output` / `kill_process_tree` / `unlink_quietly`（Task 1）
- Produces:
  - `MAX_BACKGROUND_SESSIONS: int = 32`
  - `BashSession` — dataclass（可变，游标要更新），字段 `shell_id` / `process` / `command` / `stdout_path` / `stderr_path` / `stdout_offset` / `stderr_offset` / `started_at`
  - `BashSessionRegistry` 类，方法：
    - `register(process, command, stdout_path, stderr_path) -> BashSession` — 容量满抛 `SessionLimitExceeded`
    - `get(shell_id: str) -> Optional[BashSession]`
    - `read_increment(shell_id: str, cap: int) -> Optional[Dict[str, Any]]` — 返回 `{"status", "exit_code", "stdout", "stderr", "truncated"}`；未知 id 返回 `None`
    - `terminate(shell_id: str, cap: int) -> Optional[Dict[str, Any]]` — 杀进程 + 读残余 + 清文件 + 移除；未知 id 返回 `None`
    - `count() -> int`
    - `clear() -> None` — 测试用，杀掉全部并清空
  - `SessionLimitExceeded` 异常类
  - `get_registry() -> BashSessionRegistry` — 模块级单例访问器

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_bash_session.py`：

```python
"""bash_session 后台 shell 注册表单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backend.tools.bash_session import (
    MAX_BACKGROUND_SESSIONS,
    BashSessionRegistry,
    SessionLimitExceeded,
    get_registry,
)
from backend.tools.subprocess_util import make_temp_output_file

pytestmark = pytest.mark.unit

READ_CAP = 30 * 1024


def _spawn(registry, code: str):
    """起一个后台 python 子进程并注册，返回 BashSession。"""
    stdout_path = make_temp_output_file(prefix="sage_test_")
    stderr_path = make_temp_output_file(prefix="sage_test_")
    out_handle = open(stdout_path, "wb")  # noqa: SIM115
    err_handle = open(stderr_path, "wb")  # noqa: SIM115
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=out_handle,
            stderr=err_handle,
            start_new_session=True,
        )
    finally:
        out_handle.close()
        err_handle.close()
    return registry.register(process, code, stdout_path, stderr_path)


@pytest.fixture()
def registry():
    reg = BashSessionRegistry()
    yield reg
    reg.clear()


def test_register_assigns_hex_shell_id(registry):
    """注册返回的 shell_id 是纯 hex（不可能构成路径片段）。"""
    # Arrange / Act
    session = _spawn(registry, "print('x')")

    # Assert
    assert len(session.shell_id) == 32
    assert all(c in "0123456789abcdef" for c in session.shell_id)


def test_get_unknown_shell_id_returns_none(registry):
    """未知 shell_id → None（调用方转成明确错误）。"""
    # Arrange / Act / Assert
    assert registry.get("deadbeef") is None


def test_read_increment_unknown_id_returns_none_without_filesystem_access(registry):
    """路径穿越形态的 shell_id 只是查表 miss，不触碰文件系统。"""
    # Arrange / Act
    result = registry.read_increment("../../etc/passwd", cap=READ_CAP)

    # Assert
    assert result is None


def test_read_increment_reports_running_then_exited(registry):
    """进程存活 → status=running, exit_code=None；退出后 → exited + 退出码。"""
    # Arrange
    session = _spawn(registry, "import sys; sys.stdout.write('done'); sys.exit(3)")

    # Act
    deadline = time.monotonic() + 10
    while session.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    after = registry.read_increment(session.shell_id, cap=READ_CAP)

    # Assert
    assert after is not None
    assert after["status"] == "exited"
    assert after["exit_code"] == 3
    assert "done" in after["stdout"]


def test_read_increment_is_incremental_across_calls(registry):
    """两次读不重复返回同一段输出（游标推进）。"""
    # Arrange
    code = (
        "import sys, time\n"
        "sys.stdout.write('first'); sys.stdout.flush()\n"
        "time.sleep(1.5)\n"
        "sys.stdout.write('second'); sys.stdout.flush()\n"
    )
    session = _spawn(registry, code)

    # Act
    time.sleep(0.6)
    first = registry.read_increment(session.shell_id, cap=READ_CAP)
    time.sleep(1.5)
    second = registry.read_increment(session.shell_id, cap=READ_CAP)

    # Assert
    assert first is not None and second is not None
    assert "first" in first["stdout"]
    assert "first" not in second["stdout"], "第二次读重复返回了已读内容"
    assert "second" in second["stdout"]


def test_terminate_kills_running_process_and_removes_session(registry):
    """terminate 杀掉存活进程并从表中移除。"""
    # Arrange
    session = _spawn(registry, "import time; time.sleep(30)")
    shell_id = session.shell_id
    stdout_path = session.stdout_path

    # Act
    result = registry.terminate(shell_id, cap=READ_CAP)

    # Assert
    assert result is not None
    assert result["killed"] is True
    assert registry.get(shell_id) is None
    assert registry.count() == 0
    assert not os.path.exists(stdout_path), "临时输出文件未清理"


def test_terminate_unknown_id_returns_none(registry):
    """未知 shell_id → None。"""
    # Arrange / Act / Assert
    assert registry.terminate("nope", cap=READ_CAP) is None


def test_terminate_already_exited_session_is_not_an_error(registry):
    """已退出的会话调用 terminate = 收尾清理，不报错。"""
    # Arrange
    session = _spawn(registry, "import sys; sys.exit(0)")
    deadline = time.monotonic() + 10
    while session.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)

    # Act
    result = registry.terminate(session.shell_id, cap=READ_CAP)

    # Assert
    assert result is not None
    assert result["exit_code"] == 0
    assert registry.count() == 0


def test_register_beyond_limit_raises(registry):
    """容量满 → SessionLimitExceeded（防模型无限起进程）。"""
    # Arrange
    for _ in range(MAX_BACKGROUND_SESSIONS):
        _spawn(registry, "import time; time.sleep(30)")

    # Act / Assert
    with pytest.raises(SessionLimitExceeded):
        _spawn(registry, "import time; time.sleep(30)")


def test_get_registry_returns_process_singleton():
    """get_registry 每次返回同一实例。"""
    # Arrange / Act / Assert
    assert get_registry() is get_registry()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_session.py -q
```

Expected: `ModuleNotFoundError: No module named 'backend.tools.bash_session'`

- [ ] **Step 3: 创建 bash_session.py（第一部分：数据结构与注册）**

```python
"""后台 shell 会话注册表。

``bash(run_in_background=True)`` 起的进程活在这里，``bash_output`` 轮询增量
输出，``kill_shell`` 终止并清理。

**shell_id 绝不参与路径构造**。临时输出文件的路径在注册时由
``tempfile`` 生成并存进会话记录；读取只用 shell_id **查表**取路径。若把
shell_id 拼进路径，``shell_id="../../etc/passwd"`` 就成了任意文件读取。

**线程安全**：工具在 ``asyncio.to_thread``（InprocToolAdapter）或
``run_in_executor``（legacy agent 循环）线程里执行，注册表用 ``RLock``
保护——``terminate`` 内部会调用同样加锁的辅助方法。

**已知限制：后端重启后残留进程成为孤儿。** 注册表是进程内存态，不持久化。
这是有意的取舍——持久化需要引入 storage 依赖与表迁移，超出当前需求。
容量上限 ``MAX_BACKGROUND_SESSIONS`` 限制单次运行期间的泄漏规模。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .subprocess_util import kill_process_tree, read_capped_output, unlink_quietly

logger = logging.getLogger(__name__)

#: 同时存在的后台 shell 上限——防止模型无限起进程耗尽 fd / 内存
MAX_BACKGROUND_SESSIONS = 32

STATUS_RUNNING = "running"
STATUS_EXITED = "exited"


class SessionLimitExceeded(RuntimeError):
    """后台会话数已达 ``MAX_BACKGROUND_SESSIONS``。"""


@dataclass
class BashSession:
    """一个后台 shell 的全部状态。

    ``stdout_offset`` / ``stderr_offset`` 是增量读游标，由
    ``BashSessionRegistry.read_increment`` 推进。
    """

    shell_id: str
    process: subprocess.Popen
    command: str
    stdout_path: str
    stderr_path: str
    stdout_offset: int = 0
    stderr_offset: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def status(self) -> str:
        return STATUS_RUNNING if self.process.poll() is None else STATUS_EXITED
```

- [ ] **Step 4: 追加注册表类**

在 `bash_session.py` 末尾追加：

```python
class BashSessionRegistry:
    """线程安全的后台会话表。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, BashSession] = {}
        self._lock = threading.RLock()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def register(
        self,
        process: subprocess.Popen,
        command: str,
        stdout_path: str,
        stderr_path: str,
    ) -> BashSession:
        """登记一个已启动的后台进程；容量满抛 ``SessionLimitExceeded``。"""
        with self._lock:
            if len(self._sessions) >= MAX_BACKGROUND_SESSIONS:
                raise SessionLimitExceeded(
                    f"后台 shell 数已达上限 {MAX_BACKGROUND_SESSIONS}，"
                    "请先用 kill_shell 结束不需要的会话"
                )
            session = BashSession(
                shell_id=uuid.uuid4().hex,
                process=process,
                command=command,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            self._sessions[session.shell_id] = session
            logger.info("注册后台 shell: %s (%s)", session.shell_id, command[:80])
            return session

    def get(self, shell_id: str) -> Optional[BashSession]:
        with self._lock:
            return self._sessions.get(shell_id)

    def read_increment(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        """读取自上次调用以来的新增输出；未知 shell_id 返回 ``None``。"""
        with self._lock:
            session = self._sessions.get(shell_id)
            if session is None:
                return None
            payload = self._drain(session, cap)
            payload["shell_id"] = shell_id
            return payload

    def terminate(self, shell_id: str, cap: int) -> Optional[Dict[str, Any]]:
        """杀进程 + 读残余输出 + 删临时文件 + 移除会话。

        已退出的会话走同一路径（``kill_process_tree`` 对死进程是空操作），
        因此"终止已结束的会话"等价于收尾清理，不是错误。
        """
        with self._lock:
            session = self._sessions.pop(shell_id, None)
            if session is None:
                return None
            kill_process_tree(session.process)
            payload = self._drain(session, cap)
            payload["shell_id"] = shell_id
            payload["killed"] = True
            unlink_quietly(session.stdout_path)
            unlink_quietly(session.stderr_path)
            logger.info("终止后台 shell: %s", shell_id)
            return payload

    def clear(self) -> None:
        """杀掉并清空全部会话（测试与进程收尾用）。"""
        with self._lock:
            for shell_id in list(self._sessions):
                self.terminate(shell_id, cap=1024)

    def _drain(self, session: BashSession, cap: int) -> Dict[str, Any]:
        """读增量输出并推进游标（调用方已持锁）。"""
        stdout, out_truncated, session.stdout_offset = read_capped_output(
            session.stdout_path, cap=cap, offset=session.stdout_offset
        )
        stderr, err_truncated, session.stderr_offset = read_capped_output(
            session.stderr_path, cap=cap, offset=session.stderr_offset
        )
        status = session.status()
        return {
            "status": status,
            "exit_code": session.process.returncode if status == STATUS_EXITED else None,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": out_truncated or err_truncated,
        }


_REGISTRY = BashSessionRegistry()


def get_registry() -> BashSessionRegistry:
    """进程级单例注册表。"""
    return _REGISTRY


__all__ = [
    "MAX_BACKGROUND_SESSIONS",
    "STATUS_RUNNING",
    "STATUS_EXITED",
    "BashSession",
    "BashSessionRegistry",
    "SessionLimitExceeded",
    "get_registry",
]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_session.py -q
```

Expected: 10 passed

若 `test_register_beyond_limit_raises` 跑得慢（起 32 个 python 进程），这是预期的；该测试约需 2-4 秒。

- [ ] **Step 6: lint + 提交**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/bash_session.py tests/unit/test_bash_session.py
cd /home/fz/project/sage
git add backend/tools/bash_session.py backend/tests/unit/test_bash_session.py
git commit -m "feat(tools): 后台 shell 会话注册表（增量读游标 + 容量上限 32）

shell_id 只用于查表，绝不参与路径构造——否则 shell_id='../../etc/passwd'
即为任意文件读取。"
```

---

## Task 4: BashTool 同步执行

这是本计划的核心价值：删掉 shell 操作符硬拦截，让 `ls | head`、`cd x && make` 真正能跑。

**Files:**
- Create: `backend/tools/bash_tool.py`
- Create: `backend/tests/unit/test_bash_tool.py`
- Delete: `backend/tools/terminal.py`
- Delete: `backend/tests/unit/test_terminal.py`

**Interfaces:**
- Consumes:
  - `subprocess_util.make_temp_output_file(prefix)` / `read_capped_output(path, cap, offset)` / `kill_process_tree(process)` / `unlink_quietly(path)`（Task 1）
  - `shell_resolver.resolve_shell() -> ShellSpec` / `SHELL_FALLBACK_NOTE`（Task 2）
  - `base.BaseTool` / `ToolResult` / `ToolSchema`、`BaseTool._enforce_workspace(path)`、`domain.risk.RiskClass`
- Produces:
  - `BashTool` — `schema.name == "bash"`，`risk = RiskClass.EXEC`
  - `BASH_DEFAULT_TIMEOUT_SECONDS = 120.0`、`BASH_MIN_TIMEOUT_SECONDS = 1.0`、`BASH_MAX_TIMEOUT_SECONDS = 600.0`
  - `BASH_MAX_OUTPUT_BYTES = 30 * 1024`
  - `clamp_bash_timeout(value: float) -> float`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_bash_tool.py`：

```python
"""BashTool 同步执行单元测试。

重点覆盖改动前被硬拦截的 shell 操作符命令——那是本次改动的核心价值。
"""

from __future__ import annotations

import pytest

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.bash_tool import (
    BASH_MAX_OUTPUT_BYTES,
    BASH_MAX_TIMEOUT_SECONDS,
    BASH_MIN_TIMEOUT_SECONDS,
    BashTool,
    clamp_bash_timeout,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool():
    return BashTool()


# ---------- Schema 与风险声明 ----------


def test_bash_schema_name_and_params(tool):
    """工具名为 bash（对齐 Claude Code），参数含 run_in_background。"""
    # Arrange / Act
    schema = tool.schema

    # Assert
    assert schema.name == "bash"
    props = schema.parameters["properties"]
    assert set(props) == {"command", "cwd", "timeout", "run_in_background"}
    assert schema.parameters["required"] == ["command"]


def test_bash_declares_exec_risk(tool):
    """risk=EXEC 让权限引擎按 shell 工具门控。"""
    # Arrange / Act / Assert
    assert tool.risk is RiskClass.EXEC


# ---------- 核心价值：shell 操作符不再被拦截 ----------


@pytest.mark.parametrize(
    ("command", "expected_fragment"),
    [
        ("echo hello | tr a-z A-Z", "HELLO"),
        ("true && echo chained", "chained"),
        ("echo first; echo second", "second"),
        ("echo $(echo substituted)", "substituted"),
    ],
)
def test_bash_executes_shell_operator_commands(tool, command, expected_fragment):
    """管道/串联/分号/命令替换全部可执行（改动前一律被拒）。"""
    # Arrange / Act
    result = tool.execute(command=command)

    # Assert
    assert result.success is True, result.error
    assert result.content["exit_code"] == 0
    assert expected_fragment in result.content["stdout"]


def test_bash_redirect_writes_file(tool, tmp_path):
    """重定向写文件后再读回（改动前 > 被当作危险操作符）。"""
    # Arrange
    target = tmp_path / "out.txt"

    # Act
    result = tool.execute(command=f"echo written > {target} && cat {target}")

    # Assert
    assert result.success is True, result.error
    assert "written" in result.content["stdout"]


# ---------- 退出码语义 ----------


def test_bash_nonzero_exit_still_reports_success(tool):
    """非零退出 → success=True + exit_code，让模型看到 stderr 自行纠错。"""
    # Arrange / Act
    result = tool.execute(command="echo oops >&2; exit 7")

    # Assert
    assert result.success is True
    assert result.content["exit_code"] == 7
    assert "oops" in result.content["stderr"]


def test_bash_unknown_command_reports_nonzero_exit_not_tool_failure(tool):
    """不存在的可执行文件是命令失败而非工具故障。"""
    # Arrange / Act
    result = tool.execute(command="this_command_does_not_exist_12345")

    # Assert
    assert result.success is True
    assert result.content["exit_code"] != 0


# ---------- cwd ----------


def test_bash_runs_in_given_cwd(tool, tmp_path):
    """cwd 参数生效。"""
    # Arrange / Act
    result = tool.execute(command="pwd", cwd=str(tmp_path))

    # Assert
    assert result.success is True
    out = result.content["stdout"].strip()
    assert str(tmp_path.resolve()) in out or str(tmp_path) in out


def test_bash_rejects_cwd_outside_workspace(tmp_path):
    """policy.workspace_root 绑定后，cwd 越界被拒且命令不执行。"""
    # Arrange
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = BashTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = tool.execute(command="pwd", cwd=str(outside))

    # Assert
    assert result.success is False
    assert "path_outside_workspace" in result.error


def test_bash_defaults_cwd_to_workspace_root(tmp_path):
    """未传 cwd 时默认落在 workspace_root。"""
    # Arrange
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = BashTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = tool.execute(command="pwd")

    # Assert
    assert result.success is True
    assert str(workspace.resolve()) in result.content["stdout"]


# ---------- 超时 ----------


def test_bash_timeout_kills_and_reports_failure(tool):
    """超时 → success=False，错误含超时秒数。"""
    # Arrange / Act
    result = tool.execute(command="sleep 30", timeout=1)

    # Assert
    assert result.success is False
    assert "超时" in result.error


def test_bash_timeout_kills_grandchild_process(tool, tmp_path):
    """超时杀整个进程组：后台孙进程不得存活写 marker。"""
    # Arrange
    import os
    import time

    if os.name == "nt":
        pytest.skip("进程组语义仅在 POSIX 验证")
    marker = tmp_path / "orphan.txt"
    command = f"(sleep 3; echo orphan > {marker}) & sleep 30"

    # Act
    result = tool.execute(command=command, timeout=1)

    # Assert
    assert result.success is False
    time.sleep(4)
    assert not marker.exists(), "孙进程存活 → 进程组未被完整终止"


def test_clamp_bash_timeout_clamps_out_of_range():
    """越界超时被夹到区间内。"""
    # Arrange / Act / Assert
    assert clamp_bash_timeout(0.1) == BASH_MIN_TIMEOUT_SECONDS
    assert clamp_bash_timeout(99_999) == BASH_MAX_TIMEOUT_SECONDS
    assert clamp_bash_timeout(60) == 60.0


# ---------- 输出上限 ----------


def test_bash_huge_output_is_capped(tool):
    """输出远超上限 → 截断标记 + truncated=True，父进程内存有界。"""
    # Arrange
    import sys

    command = f"{sys.executable} -c \"import sys; sys.stdout.write('y' * (5 * 1024 * 1024))\""

    # Act
    result = tool.execute(command=command)

    # Assert
    assert result.success is True
    assert result.content["truncated"] is True
    assert len(result.content["stdout"].encode("utf-8")) <= BASH_MAX_OUTPUT_BYTES + 100
    assert "已截断" in result.content["stdout"]


# ---------- 结果元数据 ----------


def test_bash_result_reports_shell_and_duration(tool):
    """content 带 shell 种类与耗时，便于模型与用户理解执行环境。"""
    # Arrange / Act
    result = tool.execute(command="echo x")

    # Assert
    assert result.content["shell"] in {"bash", "sh", "powershell"}
    assert result.content["duration_seconds"] >= 0
    assert "cwd" in result.content


# ---------- 参数校验 ----------


def test_bash_empty_command_rejected(tool):
    """空命令 → 明确错误，不起子进程。"""
    # Arrange / Act
    result = tool.execute(command="   ")

    # Assert
    assert result.success is False
    assert "command" in result.error


def test_bash_unknown_kwarg_rejected(tool):
    """未知参数 → 明确错误（模型拼错参数名时立刻可见）。"""
    # Arrange / Act
    result = tool.execute(command="echo x", shel="bash")

    # Assert
    assert result.success is False
    assert "shel" in result.error
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_tool.py -q
```

Expected: `ModuleNotFoundError: No module named 'backend.tools.bash_tool'`

- [ ] **Step 3: 创建 bash_tool.py（模块头 + BashTool 骨架）**

```python
"""bash 工具 —— 执行 shell 命令（对齐 Claude Code Bash tool）。

与被它取代的 ``TerminalTool`` 的关键差别：**不在工具内做危险命令拦截**。
旧实现拒绝一切含 shell 操作符（``| && ; > $()``）的命令，把安全性换成了
几乎不可用——``ls | head`` 这种命令都跑不了。

危险判定现在只有一处来源：``backend.tools.bash_validation.validate_bash``
的三档风险 + ``PermissionEnforcer`` 的模式矩阵与审批闸口。那条链比旧的
子串黑名单更严——DESTRUCTIVE 命令即使在 ``full_access`` 模式、即使有
显式 allow 规则也强制走用户确认。

其余设计要点：

- 输出走临时文件并只读前 30 KiB（父进程内存有界，见 ``subprocess_util``）
- ``start_new_session=True`` + 超时杀进程组（连孙进程）
- shell 由 ``shell_resolver`` 探测；Windows 无 bash 时降级 PowerShell 并
  在结果里标注，让模型知道 bash 语法可能不适用
- **cwd 无状态**：每次调用可传，不跨调用记忆。工具实例可能被主 agent 与
  ``AgentTool`` 派生的子代理共享，持久化 cwd 会让一方 ``cd`` 静默改变另一方
  的视角，且该状态不出现在审批摘要里。模型要切目录直接写 ``cd x && ...``。
- 命令非零退出仍 ``success=True``：模型需要看到 stderr 自行纠错，把编译
  失败当成工具故障会让它无法诊断。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .shell_resolver import SHELL_FALLBACK_NOTE, ShellSpec, resolve_shell
from .subprocess_util import (
    kill_process_tree,
    make_temp_output_file,
    read_capped_output,
    unlink_quietly,
)

logger = logging.getLogger(__name__)

BASH_DEFAULT_TIMEOUT_SECONDS = 120.0
BASH_MIN_TIMEOUT_SECONDS = 1.0
BASH_MAX_TIMEOUT_SECONDS = 600.0

#: stdout / stderr 各自的输出截断上限（30 KiB）
BASH_MAX_OUTPUT_BYTES = 30 * 1024

_TEMP_PREFIX = "sage_bash_"


def clamp_bash_timeout(value: float) -> float:
    """把超时夹到 ``[BASH_MIN, BASH_MAX]`` 区间。"""
    return min(max(float(value), BASH_MIN_TIMEOUT_SECONDS), BASH_MAX_TIMEOUT_SECONDS)
```

- [ ] **Step 4: 追加 BashTool 类**

在 `bash_tool.py` 末尾追加：

```python
class BashTool(BaseTool):
    """在 shell 中执行命令（同步或后台）。"""

    risk = RiskClass.EXEC

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash",
            description=(
                "在 shell 中执行命令并返回 stdout/stderr/exit_code。"
                "支持完整 shell 语法：管道 |、串联 && ||、重定向 > >>、命令替换 $()。"
                "需要切换目录时写 `cd <dir> && <command>`（cwd 参数不跨调用保留）。"
                f"默认超时 {BASH_DEFAULT_TIMEOUT_SECONDS:.0f} 秒"
                f"（上限 {BASH_MAX_TIMEOUT_SECONDS:.0f}）。"
                "长时间运行的命令（开发服务器、watch 模式）设 run_in_background=true，"
                "用 bash_output 读取输出、kill_shell 结束。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "cwd": {
                        "type": "string",
                        "description": "工作目录（可选，默认工作区根目录；不跨调用保留）",
                    },
                    "timeout": {
                        "type": "number",
                        "description": (
                            f"超时秒数（默认 {BASH_DEFAULT_TIMEOUT_SECONDS:.0f}，"
                            f"上限 {BASH_MAX_TIMEOUT_SECONDS:.0f}；后台执行时忽略）"
                        ),
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "true 则立即返回 shell_id，不等待命令结束",
                    },
                },
                "required": ["command"],
            },
        )

    def execute(
        self,
        command: str = "",
        cwd: Optional[str] = None,
        timeout: float = BASH_DEFAULT_TIMEOUT_SECONDS,
        run_in_background: bool = False,
        **kwargs,
    ) -> ToolResult:
        """执行命令。

        Returns:
            同步：``content`` 含 ``exit_code`` / ``stdout`` / ``stderr`` /
            ``duration_seconds`` / ``truncated`` / ``shell`` / ``cwd``。
            命令非零退出仍 ``success=True``；超时或启动失败 ``success=False``。
        """
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(
                success=False,
                error=(
                    f"未知参数: {names}"
                    "（合法参数: command, cwd, timeout, run_in_background）"
                ),
            )
        if not isinstance(command, str) or not command.strip():
            return ToolResult(success=False, error="command 不能为空")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
            return ToolResult(success=False, error="timeout 必须是数字")

        resolved_cwd, rejection = self._resolve_cwd(cwd)
        if rejection is not None:
            return rejection

        shell = resolve_shell()
        if run_in_background:
            return self._run_background(command, resolved_cwd, shell)
        return self._run_foreground(command, resolved_cwd, shell, clamp_bash_timeout(timeout))

    def _resolve_cwd(self, cwd: Optional[str]) -> Tuple[Optional[str], Optional[ToolResult]]:
        """确定工作目录；越界返回拒绝结果。

        显式传入的 cwd 走 workspace 守卫；未传时用 ``policy.workspace_root``
        （已在边界内，无需再校验），未绑定 workspace 则返回 ``None``
        让 ``Popen`` 继承进程 cwd。
        """
        if cwd is None:
            return self._policy.workspace_root, None
        guard = self._enforce_workspace(cwd)
        if guard is not None:
            return None, guard
        return cwd, None

    def _decorate(self, content: Dict[str, Any], shell: ShellSpec, cwd: Optional[str]) -> Dict[str, Any]:
        """给结果补上执行环境元数据。"""
        content["shell"] = shell.kind
        content["cwd"] = cwd or os.getcwd()
        if shell.is_fallback:
            content["shell_fallback"] = SHELL_FALLBACK_NOTE
        return content

    def _spawn(
        self, command: str, cwd: Optional[str], shell: ShellSpec
    ) -> Tuple[subprocess.Popen, str, str]:
        """启动子进程，输出重定向到临时文件。返回 ``(进程, stdout 路径, stderr 路径)``。

        调用方负责在失败/结束时删除这两个临时文件。
        """
        stdout_path = make_temp_output_file(prefix=_TEMP_PREFIX)
        stderr_path = make_temp_output_file(prefix=_TEMP_PREFIX)
        # 刻意不用 with：句柄要跨越 Popen 存活，启动后立即关闭（子进程已继承 fd）
        out_handle = open(stdout_path, "wb")  # noqa: SIM115
        err_handle = open(stderr_path, "wb")  # noqa: SIM115
        try:
            process = subprocess.Popen(
                [shell.executable, *shell.args_prefix, command],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out_handle,
                stderr=err_handle,
                start_new_session=True,
            )
        except OSError:
            unlink_quietly(stdout_path)
            unlink_quietly(stderr_path)
            raise
        finally:
            out_handle.close()
            err_handle.close()
        return process, stdout_path, stderr_path

    def _run_foreground(
        self, command: str, cwd: Optional[str], shell: ShellSpec, timeout: float
    ) -> ToolResult:
        started = time.monotonic()
        try:
            process, stdout_path, stderr_path = self._spawn(command, cwd, shell)
        except OSError as exc:
            return ToolResult(success=False, error=f"shell 子进程启动失败: {exc}")

        try:
            timed_out = False
            try:
                # stdout/stderr 都重定向到文件 → communicate 返回 (None, None)，
                # 只借它做"等待 + 超时"语义；退出码走 process.returncode
                process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_process_tree(process)

            duration = time.monotonic() - started
            if timed_out:
                return ToolResult(
                    success=False,
                    error=f"命令执行超时（{timeout:g} 秒），子进程组已被终止",
                )

            stdout, out_truncated, _ = read_capped_output(stdout_path, cap=BASH_MAX_OUTPUT_BYTES)
            stderr, err_truncated, _ = read_capped_output(stderr_path, cap=BASH_MAX_OUTPUT_BYTES)
            return ToolResult(
                success=True,
                content=self._decorate(
                    {
                        "exit_code": process.returncode,
                        "stdout": stdout,
                        "stderr": stderr,
                        "duration_seconds": round(duration, 3),
                        "truncated": out_truncated or err_truncated,
                    },
                    shell,
                    cwd,
                ),
            )
        finally:
            unlink_quietly(stdout_path)
            unlink_quietly(stderr_path)

    def _run_background(
        self, command: str, cwd: Optional[str], shell: ShellSpec
    ) -> ToolResult:
        """Task 5 实现。"""
        raise NotImplementedError
```

这个桩是刻意的任务边界：Task 4 的测试全部走同步路径，不触发它；Task 5 紧接着
用真实实现替换。schema 已经声明了 `run_in_background` 参数，因为改 schema 和
改实现属于同一个语义单元，拆开反而让 Task 4 的 schema 断言需要写两遍。

- [ ] **Step 5: 删除旧工具与旧测试**

```bash
cd /home/fz/project/sage
git rm backend/tools/terminal.py backend/tests/unit/test_terminal.py
```

`test_terminal.py` 的用例已在 `test_bash_tool.py` 中被等价或更强的版本覆盖：
schema 断言 → `test_bash_schema_name_and_params`；echo 成功 → shell 操作符参数化用例；
cwd → `test_bash_runs_in_given_cwd`；超时 → `test_bash_timeout_kills_and_reports_failure`。
三个「危险命令被拦截」用例**有意不迁移** —— 那正是本次要删的层，同等保护由
`test_permissions_enforcer.py` 中既有的 DESTRUCTIVE 升级测试提供。

此时 `backend/tools/__init__.py` 仍 import `terminal`，下一步修。

- [ ] **Step 6: 更新 tools/__init__.py**

在 `backend/tools/__init__.py` 中：

替换 import（原第 27 行 `from .terminal import TerminalTool`）：

```python
from .bash_tool import BashTool
```

注意 isort 顺序 —— `from .bash_tool import BashTool` 应排在 `from .base import ...` 之前
（`bash_tool` < `base` 按字典序）。ruff 的 `I` 规则会检查，`--fix` 可自动排。

替换注册（原第 41 行 `registry.register(TerminalTool(policy=policy))`）：

```python
    registry.register(BashTool(policy=policy))
```

替换 `__all__` 中的 `"TerminalTool"` 为 `"BashTool"`。

- [ ] **Step 7: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_tool.py -q
```

Expected: 全部通过（POSIX 上 19 passed）。

若 `test_bash_huge_output_is_capped` 报「找不到解释器」，检查测试里的
`sys.executable` 是否被 shell 正确引用（路径含空格时需要加引号）。

- [ ] **Step 8: 提交**

```bash
cd /home/fz/project/sage
git add backend/tools/bash_tool.py backend/tools/__init__.py backend/tests/unit/test_bash_tool.py
git commit -m "feat(tools): bash 工具取代 terminal，放开 shell 操作符

旧 TerminalTool 拒绝一切含 | && ; > \$() 的命令，导致 ls | head 这类
最常见命令无法执行。危险判定收敛到 bash_validation + PermissionEnforcer
单一来源（该链更严：DESTRUCTIVE 在 full_access 下也强制审批）。
同时补齐有界输出、进程组回收、跨平台 shell 探测。"
```

---

## Task 5: 后台执行三工具

**Files:**
- Modify: `backend/tools/bash_tool.py`（实现 `_run_background`，追加两个工具类）
- Modify: `backend/tests/unit/test_bash_tool.py`（追加后台测试段）
- Modify: `backend/tools/__init__.py`（注册两个新工具）

**Interfaces:**
- Consumes:
  - Task 3 的 `bash_session.get_registry()` / `SessionLimitExceeded` / `MAX_BACKGROUND_SESSIONS`
  - Task 4 的 `BashTool._spawn` / `_decorate` / `BASH_MAX_OUTPUT_BYTES`
- Produces:
  - `BashOutputTool` — `schema.name == "bash_output"`，`risk = RiskClass.READ`
  - `KillShellTool` — `schema.name == "kill_shell"`，`risk = RiskClass.WRITE_LOCAL`

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/unit/test_bash_tool.py` 末尾追加。先在文件顶部的 import 段补上：

```python
from backend.tools.bash_session import get_registry
from backend.tools.bash_tool import BashOutputTool, KillShellTool
```

然后追加测试段：

```python
# ---------- 后台执行 ----------


@pytest.fixture()
def clean_registry():
    """每个后台测试用干净的全局注册表。"""
    registry = get_registry()
    registry.clear()
    yield registry
    registry.clear()


def _await_status(output_tool, shell_id, target, timeout=15.0):
    """轮询直到 status 变为 target，返回最后一次结果（超时则返回最后所见）。"""
    import time as _time

    deadline = _time.monotonic() + timeout
    last = None
    while _time.monotonic() < deadline:
        last = output_tool.execute(shell_id=shell_id)
        if last.content["status"] == target:
            return last
        _time.sleep(0.1)
    return last


def test_bash_background_returns_shell_id_immediately(tool, clean_registry):
    """run_in_background=true → 立即返回 shell_id + running 状态。"""
    # Arrange / Act
    result = tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert result.success is True, result.error
    assert result.content["status"] == "running"
    assert len(result.content["shell_id"]) == 32
    assert clean_registry.count() == 1


def test_bash_background_does_not_block(tool, clean_registry):
    """后台执行不等待命令结束（sleep 30 立刻返回）。"""
    # Arrange
    import time as _time

    started = _time.monotonic()

    # Act
    tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert _time.monotonic() - started < 5.0


def test_bash_output_reads_incrementally(tool, clean_registry):
    """bash_output 两次调用不重复返回同一段输出。"""
    # Arrange
    import time as _time

    output_tool = BashOutputTool()
    command = "echo first; sleep 2; echo second"
    spawned = tool.execute(command=command, run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    _time.sleep(0.8)
    first = output_tool.execute(shell_id=shell_id)
    _time.sleep(2.5)
    second = output_tool.execute(shell_id=shell_id)

    # Assert
    assert "first" in first.content["stdout"]
    assert "first" not in second.content["stdout"]
    assert "second" in second.content["stdout"]


def test_bash_output_reports_exit_code_after_completion(tool, clean_registry):
    """命令结束后 status=exited 且带 exit_code。"""
    # Arrange
    output_tool = BashOutputTool()
    spawned = tool.execute(command="exit 5", run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    final = _await_status(output_tool, shell_id, "exited")

    # Assert
    assert final.content["status"] == "exited"
    assert final.content["exit_code"] == 5


def test_bash_output_unknown_shell_id_errors(clean_registry):
    """未知 shell_id → 明确错误。"""
    # Arrange
    output_tool = BashOutputTool()

    # Act
    result = output_tool.execute(shell_id="0" * 32)

    # Assert
    assert result.success is False
    assert "shell_id" in result.error


def test_bash_output_path_traversal_shell_id_rejected(clean_registry, tmp_path):
    """路径穿越形态的 shell_id 只是查表 miss，不读任何文件。"""
    # Arrange
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    output_tool = BashOutputTool()

    # Act
    result = output_tool.execute(shell_id=f"../../{secret}")

    # Assert
    assert result.success is False
    assert result.content is None
    assert "classified" not in (result.error or "")


def test_kill_shell_terminates_running_command(tool, clean_registry):
    """kill_shell 终止后台命令并清空注册表。"""
    # Arrange
    kill_tool = KillShellTool()
    spawned = tool.execute(command="sleep 30", run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    result = kill_tool.execute(shell_id=shell_id)

    # Assert
    assert result.success is True
    assert result.content["killed"] is True
    assert clean_registry.count() == 0


def test_kill_shell_unknown_id_errors(clean_registry):
    """未知 shell_id → 明确错误。"""
    # Arrange
    kill_tool = KillShellTool()

    # Act
    result = kill_tool.execute(shell_id="f" * 32)

    # Assert
    assert result.success is False
    assert "shell_id" in result.error


def test_bash_background_rejects_beyond_session_limit(tool, clean_registry):
    """后台会话达上限 → 拒绝新建并提示用 kill_shell。"""
    # Arrange
    from backend.tools.bash_session import MAX_BACKGROUND_SESSIONS

    for _ in range(MAX_BACKGROUND_SESSIONS):
        tool.execute(command="sleep 30", run_in_background=True)

    # Act
    result = tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert result.success is False
    assert "kill_shell" in result.error


def test_background_tools_declare_expected_risk():
    """bash_output 只读输出（READ）；kill_shell 改系统状态（WRITE_LOCAL）。"""
    # Arrange / Act / Assert
    assert BashOutputTool().risk is RiskClass.READ
    assert KillShellTool().risk is RiskClass.WRITE_LOCAL
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_tool.py -q -k "background or bash_output or kill_shell"
```

Expected: `ImportError: cannot import name 'BashOutputTool'`

- [ ] **Step 3: 实现 _run_background**

把 `bash_tool.py` 里 Task 4 留下的 `NotImplementedError` 桩替换为：

```python
    def _run_background(
        self, command: str, cwd: Optional[str], shell: ShellSpec
    ) -> ToolResult:
        """启动后台 shell 并登记，立即返回 shell_id。

        后台进程**不受 timeout 约束**——这正是它存在的理由（开发服务器、
        watch 模式）。生命周期由 ``bash_output`` / ``kill_shell`` 管理。
        """
        registry = get_registry()
        if registry.count() >= MAX_BACKGROUND_SESSIONS:
            return ToolResult(
                success=False,
                error=(
                    f"后台 shell 数已达上限 {MAX_BACKGROUND_SESSIONS}，"
                    "请先用 kill_shell 结束不需要的会话"
                ),
            )
        try:
            process, stdout_path, stderr_path = self._spawn(command, cwd, shell)
        except OSError as exc:
            return ToolResult(success=False, error=f"shell 子进程启动失败: {exc}")

        try:
            session = registry.register(process, command, stdout_path, stderr_path)
        except SessionLimitExceeded as exc:
            # 上面的预检查与此处之间存在竞态窗口（并发 spawn）——注册失败必须
            # 回收已起的进程，否则它会成为无人可杀的孤儿。
            kill_process_tree(process)
            unlink_quietly(stdout_path)
            unlink_quietly(stderr_path)
            return ToolResult(success=False, error=str(exc))

        return ToolResult(
            success=True,
            content=self._decorate(
                {
                    "shell_id": session.shell_id,
                    "command": command,
                    "status": STATUS_RUNNING,
                },
                shell,
                cwd,
            ),
        )
```

并在 `bash_tool.py` 的 import 段补上：

```python
from .bash_session import (
    MAX_BACKGROUND_SESSIONS,
    STATUS_RUNNING,
    SessionLimitExceeded,
    get_registry,
)
```

（isort 顺序：`.bash_session` 排在 `.base` 之前。）

- [ ] **Step 4: 追加 BashOutputTool 与 KillShellTool**

在 `bash_tool.py` 末尾追加：

```python
class BashOutputTool(BaseTool):
    """读取后台 shell 自上次读取以来的新增输出。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash_output",
            description=(
                "读取后台 shell（bash 工具 run_in_background=true 启动）的新增输出。"
                "每次调用只返回上次读取之后的增量，并报告 status "
                "（running / exited）与 exit_code。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash 后台执行返回的 shell_id",
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(self, shell_id: str = "", **kwargs) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(success=False, error=f"未知参数: {names}（合法参数: shell_id）")
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 不能为空")

        payload = get_registry().read_increment(shell_id, cap=BASH_MAX_OUTPUT_BYTES)
        if payload is None:
            return ToolResult(
                success=False,
                error=f"未知 shell_id: {shell_id}（会话不存在或已被 kill_shell 结束）",
            )
        return ToolResult(success=True, content=payload)


class KillShellTool(BaseTool):
    """终止后台 shell 并清理其资源。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="kill_shell",
            description=(
                "终止后台 shell（bash 工具 run_in_background=true 启动）"
                "并返回其残余输出。已结束的会话调用此工具等价于收尾清理。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "bash 后台执行返回的 shell_id",
                    },
                },
                "required": ["shell_id"],
            },
        )

    def execute(self, shell_id: str = "", **kwargs) -> ToolResult:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            return ToolResult(success=False, error=f"未知参数: {names}（合法参数: shell_id）")
        if not isinstance(shell_id, str) or not shell_id.strip():
            return ToolResult(success=False, error="shell_id 不能为空")

        payload = get_registry().terminate(shell_id, cap=BASH_MAX_OUTPUT_BYTES)
        if payload is None:
            return ToolResult(
                success=False,
                error=f"未知 shell_id: {shell_id}（会话不存在或已被 kill_shell 结束）",
            )
        return ToolResult(success=True, content=payload)
```

并把 `__all__` 补全：

```python
__all__ = [
    "BASH_DEFAULT_TIMEOUT_SECONDS",
    "BASH_MIN_TIMEOUT_SECONDS",
    "BASH_MAX_TIMEOUT_SECONDS",
    "BASH_MAX_OUTPUT_BYTES",
    "BashTool",
    "BashOutputTool",
    "KillShellTool",
    "clamp_bash_timeout",
]
```

- [ ] **Step 5: 注册两个新工具**

在 `backend/tools/__init__.py`：

import 段改为 `from .bash_tool import BashOutputTool, BashTool, KillShellTool`。

在 `register_all_tools` 中 `registry.register(BashTool(policy=policy))` 之后追加：

```python
    # 后台 shell 生命周期：bash(run_in_background=true) 起的进程由这两个工具
    # 轮询与终止。bash_output 归 READ（只读已捕获输出），kill_shell 归 WRITE。
    registry.register(BashOutputTool(policy=policy))
    registry.register(KillShellTool(policy=policy))
```

`__all__` 补上 `"BashOutputTool"` 与 `"KillShellTool"`。

- [ ] **Step 6: 运行完整 bash 测试**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_tool.py -q
```

Expected: 全部通过（POSIX 上 29 passed）。

- [ ] **Step 7: lint + 提交**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/bash_tool.py tools/__init__.py tests/unit/test_bash_tool.py
cd /home/fz/project/sage
git add backend/tools/bash_tool.py backend/tools/__init__.py backend/tests/unit/test_bash_tool.py
git commit -m "feat(tools): 后台执行 bash_output / kill_shell 三工具闭环

run_in_background 立即返回 shell_id，bash_output 增量轮询，kill_shell
终止清理。注册失败时回收已起进程，避免并发 spawn 竞态留下孤儿。"
```

---

## Task 6: 引用面同步与权限表更新

Task 4 已经改了 `tools/__init__.py`，但 `TOOL_CAPABILITIES`、`SHELL_TOOLS`、agent profile 和一批测试仍指向 `terminal`。这个 Task 把它们一次改完 —— 全量测试在这里第一次应当全绿。

**Files:**
- Modify: `backend/tools/permissions.py:52-87`
- Modify: `backend/domain/risk.py:47-48`
- Modify: `backend/agents/profiles.py:109`
- Modify: `backend/orchestration/permission.py:56-63`（注释）
- Modify: `backend/tests/unit/test_risk.py`
- Modify: `backend/tests/unit/test_permission.py`
- Modify: `backend/tests/unit/test_permissions_enforcer.py`
- Modify: `backend/tests/unit/test_inproc_tool_adapter.py`
- Modify: `backend/tests/unit/test_hooks.py`
- Modify: `backend/tests/integration/test_agent_permission_flow.py`
- Modify: `backend/tests/integration/test_hooks_integration.py`

**Interfaces:**
- Consumes: Task 4/5 的 `BashTool` / `BashOutputTool` / `KillShellTool` 工具名
- Produces: 全仓库对 shell 工具的引用统一为 `bash`

- [ ] **Step 1: 更新 TOOL_CAPABILITIES**

在 `backend/tools/permissions.py` 的 `TOOL_CAPABILITIES` 字典中，把
`"terminal": ToolCapability.EXECUTE,`（第 71 行）替换为：

```python
    "bash": ToolCapability.EXECUTE,
    # bash_output 归 READ：只读 bash 后台执行已捕获到临时文件的输出，
    # 零副作用，read_only 模式下应可用（否则模型无法看到自己起的后台任务）。
    "bash_output": ToolCapability.READ,
    # kill_shell 归 WRITE：终止进程是对系统状态的修改。
    "kill_shell": ToolCapability.WRITE,
```

- [ ] **Step 2: 更新 risk.py 按名兜底表**

在 `backend/domain/risk.py` 中：

```python
WRITE_TOOLS = frozenset({"write_file", "memory_save", "kill_shell"})
SHELL_TOOLS = frozenset({"bash"})
EXTERNAL_TOOLS = frozenset({"web_search", "web_fetch"})
```

（`bash_output` 不列 —— 兜底默认就是 READ。）

- [ ] **Step 3: 更新 agent profile**

`backend/agents/profiles.py:109`：

```python
            tools=["file_read", "file_write", "bash", "calculator"],
```

- [ ] **Step 4: 更新 orchestration/permission.py 注释**

第 56-63 行的注释里 `the real tool is named "terminal"` 与
`(terminal → EXECUTE, ...)` 两处提法改为 `bash`。这段注释解释的是
「旧列表写 execute/shell 而真实工具名不同」这个历史教训，把工具名更新为
`bash` 即可，不改逻辑（`classify_tool` 查的是同一张表）。

- [ ] **Step 5: 批量更新测试中的工具名**

以下位置的 `"terminal"` 字面量指代**真实的 shell 工具**（依赖它的
EXECUTE 能力或 EXEC 风险），必须改为 `"bash"`：

```bash
cd /home/fz/project/sage
sed -i 's/"terminal"/"bash"/g' \
  backend/tests/unit/test_permissions_enforcer.py \
  backend/tests/unit/test_inproc_tool_adapter.py \
  backend/tests/integration/test_agent_permission_flow.py
```

`test_risk.py` 手工改三处：

- 第 135-136 行 `overrides` lambda 与断言里的 `"terminal"` → `"bash"`
- 第 141 行断言 → `classify("bash", overrides=overrides) is RiskClass.EXEC`
- 第 214 行 `registry.classify("terminal")` → `registry.classify("bash")`
- 第 239 行 `expected` 字典里 `"terminal": RiskClass.EXEC` → `"bash": RiskClass.EXEC`，
  并追加两行：

```python
            "bash_output": RiskClass.READ,
            "kill_shell": RiskClass.WRITE_LOCAL,
```

`test_permission.py` 手工改：

- 全文 `engine.evaluate("terminal", ...)` → `engine.evaluate("bash", ...)`（9 处）
- 第 100 行 `tools.add("terminal")` → `tools.add("bash")`
- **删除**第 134-139 行的 `test_terminal_tool_shares_same_source` 整个方法 ——
  它断言 `TerminalTool.SHELL_OPERATORS == SHELL_OPERATORS`，而 `BashTool`
  有意不再持有该类属性（危险判定不在工具内）。`domain/shell.py` 的
  `has_shell_operators` 仍被 `PermissionEngine` 使用，同类的
  `TestHasShellOperators` 其余用例保留。

`test_hooks.py` 中的 `"terminal"` 是当**任意工具名**测试 hook 的 fnmatch
匹配（`("term*", "terminal", True)` 这类），改为 `"bash"` 需要同步改
pattern，收益为零 —— **不改**。

`test_agent_permission_flow.py` 的 `_terminal_call` 函数名可一并改为
`_bash_call`（sed 只改了字符串字面量）：

```bash
cd /home/fz/project/sage
sed -i 's/_terminal_call/_bash_call/g' backend/tests/integration/test_agent_permission_flow.py
```

`test_hooks_integration.py` 第 69、72 行：`_make_agent("terminal", ...)` 与
`agent.tool_registry.get("terminal")` → `"bash"`。

- [ ] **Step 6: 运行受影响测试**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_risk.py \
  backend/tests/unit/test_permission.py \
  backend/tests/unit/test_permissions_enforcer.py \
  backend/tests/unit/test_inproc_tool_adapter.py \
  backend/tests/integration/test_agent_permission_flow.py \
  backend/tests/integration/test_hooks_integration.py -q
```

Expected: 全部通过。

- [ ] **Step 7: 全量后端测试**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q 2>&1 | tail -20
```

Expected: 无 failure。若有失败，用 `grep -rn "terminal" <失败文件>` 找漏改的引用。

- [ ] **Step 8: lint + 提交**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .
cd /home/fz/project/sage
git add -u
git commit -m "refactor: 全仓库 shell 工具引用 terminal → bash

TOOL_CAPABILITIES 新增 bash_output(READ) / kill_shell(WRITE)；
risk 兜底表同步。删除 SHELL_OPERATORS 防漂移测试——BashTool 有意不再
持有该类属性，危险判定已收敛到 PermissionEnforcer。"
```

---

## Task 7: 前端工具调用渲染

`humanize.ts` 把工具调用翻译成用户可读的「动词 + 对象」。新工具名不加进去，
UI 会把 `bash` 渲染成 fallback（工具名原样显示）。

**Files:**
- Modify: `src/shared/lib/humanize.ts:72-79`
- Modify: `src/shared/lib/__tests__/humanize.test.ts:50-57` 附近

**Interfaces:**
- Consumes: Task 4/5 的工具名 `bash` / `bash_output` / `kill_shell`
- Produces: 无（终端消费者）

- [ ] **Step 1: 写失败测试**

在 `src/shared/lib/__tests__/humanize.test.ts` 的
`describe('humanizeToolCall — Sage backend tools', ...)` 块内，
把现有的 `renders terminal (Sage shell tool) with scope local` 用例
**保留不动**（旧会话数据仍存 `terminal`），在它之后插入：

```typescript
  it('renders bash with scope local', () => {
    expect(humanizeToolCall('bash', { command: 'npm run dev', cwd: '/x' })).toEqual({
      verb: 'Run',
      object: 'npm run dev',
      scope: 'local',
    });
  });

  it('renders bash background launch the same as foreground', () => {
    expect(
      humanizeToolCall('bash', { command: 'npm run dev', run_in_background: true }),
    ).toEqual({
      verb: 'Run',
      object: 'npm run dev',
      scope: 'local',
    });
  });

  it('renders bash_output with the shell id', () => {
    expect(humanizeToolCall('bash_output', { shell_id: 'abc123' })).toEqual({
      verb: 'Read output of',
      object: 'abc123',
      scope: 'local',
    });
  });

  it('renders kill_shell with the shell id', () => {
    expect(humanizeToolCall('kill_shell', { shell_id: 'abc123' })).toEqual({
      verb: 'Kill',
      object: 'abc123',
      scope: 'local',
    });
  });

  it('falls back to a placeholder when bash_output has no shell id', () => {
    expect(humanizeToolCall('bash_output', {})).toEqual({
      verb: 'Read output of',
      object: 'a background shell',
      scope: 'local',
    });
  });
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/lib/__tests__/humanize.test.ts
```

Expected: 4-5 个新用例失败（`bash` 走到 default 分支，返回工具名而非 `verb: 'Run'`）

- [ ] **Step 3: 更新 humanize.ts**

在 `src/shared/lib/humanize.ts` 的 `// ---- shell / code execution ----` 段，
把现有的

```typescript
    case 'terminal':
    case 'run_shell':
```

替换为（新增 `bash`，`terminal` 保留给历史会话数据）：

```typescript
    case 'bash':
    case 'terminal':
    case 'run_shell':
```

并在该 case 的 return 之后、`case 'repl'` 之前插入两个新 case：

```typescript
    case 'bash_output':
      return {
        verb: 'Read output of',
        object: trunc(strArg(a, 'shell_id', 'a background shell'), MAX_OBJECT),
        scope: 'local',
      };
    case 'kill_shell':
      return {
        verb: 'Kill',
        object: trunc(strArg(a, 'shell_id', 'a background shell'), MAX_OBJECT),
        scope: 'local',
      };
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/lib/__tests__/humanize.test.ts
```

Expected: 31 passed（原 26 + 新 5）

- [ ] **Step 5: 前端类型检查与 lint**

```bash
cd /home/fz/project/sage && npm run typecheck && npm run lint
```

Expected: 无错误。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage
git add src/shared/lib/humanize.ts src/shared/lib/__tests__/humanize.test.ts
git commit -m "feat(ui): humanize 渲染 bash / bash_output / kill_shell

保留 terminal case——历史会话记录里存的是旧工具名，删掉会让旧对话的
工具调用渲染成 fallback。"
```

---

## Task 8: 技术文档归档与全量验证

按项目规范（`~/.claude/rules/common/feature-development.md`），功能完成后要把
内容并入技术手册章节，并删除 `docs/plans/` 下的进行中计划。本计划位于
`docs/superpowers/plans/`（superpowers 工作流目录），保留作为执行记录。

**Files:**
- Create: `docs/technical/44-bash-tool.md`
- Modify: `docs/technical/README.md`（章节目录表追加一行）

**Interfaces:**
- Consumes: Task 1-7 的全部产出
- Produces: 无

- [ ] **Step 1: 写技术文档章节**

创建 `docs/technical/44-bash-tool.md`：

```markdown
# bash 命令行工具

> 对齐 Claude Code Bash tool 的 shell 执行能力。取代原 `terminal` 工具。

## 为什么重写

原 `TerminalTool` 在工具内部做危险命令拦截，规则之一是「含任何 shell
操作符（`| && ; > < $( ` 换行`）即拒绝」。后果是 `ls | head`、
`cd build && make`、`grep x f > out` 这类最常见的命令全部无法执行 ——
模型实际可用的 shell 面接近于空。

危险判定现在只有一处来源：

| 层 | 位置 | 职责 |
|---|---|---|
| 风险分级 | `backend/tools/bash_validation.py` | SAFE / SUSPICIOUS / DESTRUCTIVE 三档 |
| 权限裁决 | `backend/tools/permissions.py` `PermissionEnforcer` | 规则(deny>allow>ask) → DESTRUCTIVE 安全网 → 模式矩阵 |
| allowlist 防绕过 | `backend/adapters/out/permission/permission_engine.py` | 免审批 allowlist 前，含 shell 操作符的命令不自动放行 |

这条链比旧的子串黑名单更严：`validate_bash` 覆盖 `rm -fr` / `rm -r -f` /
`--recursive --force` 全部旗标变体，且 DESTRUCTIVE 命令即使在
`full_access` 模式、即使有显式 allow 规则也强制走用户审批。

## 三个工具

| 工具 | 能力 | 用途 |
|---|---|---|
| `bash` | EXECUTE | 执行命令（同步或后台） |
| `bash_output` | READ | 读后台 shell 的增量输出 |
| `kill_shell` | WRITE | 终止后台 shell 并清理 |

### bash

| 参数 | 默认 | 说明 |
|---|---|---|
| `command` | 必填 | 完整 shell 命令，允许管道/串联/重定向/命令替换 |
| `cwd` | `policy.workspace_root` | 工作目录；**不跨调用保留** |
| `timeout` | 120 秒 | 夹到 `[1, 600]`；后台执行时忽略 |
| `run_in_background` | `false` | `true` 则立即返回 `shell_id` |

同步返回 `{exit_code, stdout, stderr, duration_seconds, truncated, shell, cwd}`。

**命令非零退出仍 `success=True`** —— 模型需要看到 stderr 自行纠错；把编译
失败当成工具故障会让它无法诊断。只有超时、shell 找不到、进程启动失败才
`success=False`。

**cwd 无状态**是有意选择，而非疏漏。工具实例可能被主 agent 与 `AgentTool`
派生的子代理共享，持久化 cwd 会让一方 `cd` 静默改变另一方的视角，且该状态
不出现在任何审批摘要里。既然 shell 操作符已放开，切目录写 `cd x && ...` 即可。

### 后台执行

`bash(run_in_background=true)` 起的进程登记在
`backend/tools/bash_session.py` 的进程级注册表中，**不受 timeout 约束** ——
这正是它存在的理由（开发服务器、watch 模式）。

`bash_output` 每次只返回上次读取之后的**增量**输出（注册表为每个会话维护
stdout/stderr 读游标），并报告 `status`（`running` / `exited`）与
`exit_code`。

`shell_id` 是 `uuid4().hex`，**绝不参与路径构造** —— 临时输出文件路径在注册
时生成并存进会话记录，读取只用 `shell_id` 查表。若拼接路径，
`shell_id="../../etc/passwd"` 就成了任意文件读取。

## 已知限制

- **后端重启后后台进程成为孤儿**。注册表是进程内存态，不持久化。持久化
  需要引入 storage 依赖与表迁移，超出当前需求。容量上限 32
  （`MAX_BACKGROUND_SESSIONS`）限制单次运行期间的泄漏规模。
- **Windows 上杀不到孙进程**。`subprocess_util.kill_process_tree` 在
  Windows 退化为 `process.kill()`，与 `repl` 工具同源限制。

## 跨平台 shell 探测

`backend/tools/shell_resolver.py` 按序探测（结果进程内缓存一次）：

- POSIX：`/bin/bash` → `/bin/sh`
- Windows：PATH 中的 `bash` → `%PROGRAMFILES%\Git\bin\bash.exe` →
  `%PROGRAMFILES(X86)%\Git\bin\bash.exe`
- Windows 全失败：PowerShell（`-NoProfile -Command`），结果中带
  `shell_fallback` 提示，让模型知道 bash 语法可能不适用

`release/win7` 分支尤其依赖 PowerShell 降级路径 —— Win7 机器未必装 Git。

## 输出与进程回收

`backend/tools/subprocess_util.py` 提供 `bash` 与 `repl` 共用的原语：

- 子进程 stdout/stderr 重定向到**临时文件**而非父进程 PIPE。PIPE 会无限
  缓冲，命令打印几个 GB 就撑爆后端内存。
- 只读前 30 KiB（`bash`）/ 100 KiB（`repl`），超出加截断标记。
- `start_new_session=True` + 超时 `os.killpg` 杀整个进程组（连孙进程）。
```

- [ ] **Step 2: 在技术手册总览追加章节条目**

在 `docs/technical/README.md` 的章节表末尾（第 43 行 `| 43 | ... |` 之后）
追加：

```markdown
| 44   | [bash 命令行工具](./44-bash-tool.md) | 对齐 Claude Code Bash tool：放开 shell 操作符（危险判定收敛到 bash_validation + PermissionEnforcer）+ 后台执行三工具（bash/bash_output/kill_shell）+ 30 KiB 有界输出 + 进程组回收 + 跨平台 shell 探测（Git Bash / PowerShell 降级） |
```

- [ ] **Step 3: 全量后端测试**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q 2>&1 | tail -15
```

Expected: 无 failure、无 error。

- [ ] **Step 4: 全量前端测试 + 类型检查 + lint**

```bash
cd /home/fz/project/sage && npx vitest run 2>&1 | tail -10
cd /home/fz/project/sage && npm run typecheck
cd /home/fz/project/sage && npm run lint
```

Expected: 三项全绿。

- [ ] **Step 5: 后端 lint**

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: 确认无残留 terminal 工具引用**

```bash
cd /home/fz/project/sage && grep -rn "TerminalTool\|tools.terminal" --include=*.py backend/ | grep -v __pycache__
```

Expected: 无输出。

```bash
cd /home/fz/project/sage && grep -rn "'terminal'" src/shared/lib/humanize.ts
```

Expected: 一处（历史会话数据兼容的 `case 'terminal':`）。

- [ ] **Step 7: 提交**

```bash
cd /home/fz/project/sage
git add docs/technical/44-bash-tool.md docs/technical/README.md
git commit -m "docs(technical): 新增第 44 章 bash 命令行工具"
```

- [ ] **Step 8: 推分支并开 PR**

```bash
cd /home/fz/project/sage
git push -u origin feat/bash-tool-parity
gh pr create --title "feat(tools): bash 工具对齐 Claude Code，放开 shell 操作符" --body "$(cat <<'EOF'
## Summary

- 删除 `TerminalTool` 内的 shell 操作符硬拦截 —— 旧实现让 `ls | head`、`cd x && make` 这类最常见命令全部无法执行。危险判定收敛到 `bash_validation` + `PermissionEnforcer` 单一来源（该链更严：DESTRUCTIVE 在 `full_access` 下也强制审批）。
- 工具重命名 `terminal` → `bash`，新增 `bash_output` / `kill_shell` 支持后台执行（开发服务器、watch 模式）。
- 补齐 30 KiB 有界输出（原用 PIPE 无限缓冲，`find /` 可撑爆后端内存）、进程组回收（原只杀直接子进程）、跨平台 shell 探测（Git Bash → PowerShell 降级，服务 Win7 分支）。

设计文档：`docs/superpowers/specs/2026-08-28-bash-tool-parity-design.md`
技术手册：`docs/technical/44-bash-tool.md`

## Test plan

- [ ] `pytest backend/tests` 全绿
- [ ] `npx vitest run` 全绿
- [ ] `npm run typecheck && npm run lint` 全绿
- [ ] `ruff check .` 全绿
- [ ] 手工验证：桌面端对话中让模型跑 `ls | head`、`cd /tmp && pwd`，确认审批弹窗出现且批准后真正执行
- [ ] 手工验证：后台起 `npm run dev`，用 `bash_output` 轮询输出、`kill_shell` 终止
EOF
)"
```

---

## 待人工验证（不在自动化范围内）

计划的自动化测试覆盖不到以下几点，需要在 PR review 阶段手工确认：

1. **审批弹窗链路**：桌面端实际对话中，`bash` 调用在 `workspace_write` 模式下
   触发 `ApprovalDialog`，批准后命令真正执行，拒绝后不执行。
2. **后台任务的真实场景**：起 `npm run dev`，`bash_output` 能看到 Vite 启动
   日志，`kill_shell` 后端口释放。
3. **Windows / Win7 上的 shell 探测**：单测用 monkeypatch 模拟，实际 Windows
   机器上 Git Bash 与 PowerShell 降级路径需要真机验证。这一项在
   cherry-pick 到 `release/win7` 时必须做。
