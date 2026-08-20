# Win7 Memory Manager Initialization and SSL Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复生产工具注册缺少 `memory_manager` 注入的问题，并确保 Win7 打包 Python 始终携带可用的 `certifi` CA bundle。

**Architecture:** 在两个生产工具注册入口完成统一的 memory-manager wiring；通过 Win7 requirements 和 bundle verify 保证 `certifi` 被打进 embeddable Python；在 backend 启动阶段用一个小型、可测试的 bootstrap 函数将 `certifi.where()` 设置为 SSL 环境变量，同时保留用户已有环境变量。extractor 复用 session-specific provider 不在本计划内，作为后续独立设计。

**Tech Stack:** Python 3.8/3.11, FastAPI, httpx 0.26.0, certifi, pytest, pytest-asyncio, PowerShell, Git cherry-pick。

## Global Constraints

- Win7 后端测试和打包相关 Python 命令必须使用 `/home/fz/anaconda3/envs/sage-backend-py38/bin/python` 或等价的 `sage-backend-py38` 环境。
- main 后端测试必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python` 或等价的 `sage-backend` 环境。
- `release/win7` 与 `main` 不合并；只使用独立 commit cherry-pick 同步通用修复。
- 不修改 `backend/requirements.txt` 或 main 专属文件时的 Win7 版本约束；Win7 依赖只写入 `requirements-py38.txt`。
- 不覆盖用户已有的 `SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE` 或 `CURL_CA_BUNDLE` 环境变量，使用 `setdefault` 语义。
- 不把 extractor 复用当前 session provider、显式 `httpx verify` 改造或其他架构重构混入本计划。
- 每个任务先写失败测试，再写最小实现；每个任务完成后单独 commit，commit message 使用 Conventional Commits。

---

## 文件结构与职责

| 文件 | 角色 |
|---|---|
| `backend/core/legacy/agent.py` | legacy `SageAgent` 创建内置工具后的 memory-manager 注入 |
| `backend/adapters/out/tool/inproc_adapter.py` | hex/in-process 工具注册后的 memory-manager 注入 |
| `backend/tests/integration/test_memory_tool_injection.py` | 两个生产注册入口的 wiring 回归测试 |
| `backend/requirements-py38.txt` | Win7 embeddable Python 的依赖清单，新增 certifi |
| `scripts/bundle-python.ps1` | Win7 bundle 后的 certifi/import canary 验证 |
| `backend/main.py` | SSL CA bootstrap 函数及应用启动时调用 |
| `backend/tests/unit/test_ssl_bootstrap.py` | certifi 可用、用户 override、缺失/无效 certifi 的单测 |
| `docs/superpowers/specs/2026-08-20-win7-memory-manager-init-design.md` | 已批准的设计依据，不在实施中重写 |
| `docs/superpowers/specs/README.md` | spec 目录索引，实施完成后补充本设计链接 |

---

### Task 1: Wire `memory_manager` into all production memory tools

**Files:**
- Modify: `backend/core/legacy/agent.py:255-271`
- Modify: `backend/adapters/out/tool/inproc_adapter.py:50-72`
- Create: `backend/tests/integration/test_memory_tool_injection.py`

**Interfaces:**
- Consumes: `backend.memory.registry.get_memory_manager()`, `ToolRegistry.list()`, `MemorySearchTool.set_memory_manager()`, `MemorySaveTool.set_memory_manager()`。
- Produces: every `MemorySearchTool` and `MemorySaveTool` created by either production registry path has a non-`None` manager before execution; bare `SageAgent` remains unchanged and does not register memory tools。

- [ ] **Step 1: Inspect the existing constructors and test isolation**

Confirm before editing that `SageAgent.__init__` constructs `self.memory_manager` in the non-bare branch, that `ToolRegistry.list()` returns tool instances, and that `setup_test_db` resets the memory singleton. Use the existing fake-manager tests in `backend/tests/unit/test_memory_tool.py` as the behavioral reference.

- [ ] **Step 2: Write failing integration tests for the legacy path**

Create a test that constructs a non-bare `SageAgent` with the smallest valid arguments used by existing agent tests, filters `agent.tool_registry.list()` for `MemorySearchTool` and `MemorySaveTool`, and asserts both have `tool.memory is not None` and `tool.memory is agent.memory_manager`. Add a separate test that constructs `SageAgent(bare=True)` and asserts no memory tools are registered, preserving the intentional lightweight path.

```python
from backend.core.legacy.agent import SageAgent
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool


def test_non_bare_agent_injects_its_memory_manager():
    agent = SageAgent(bare=False)
    memory_tools = [
        tool
        for tool in agent.tool_registry.list()
        if isinstance(tool, (MemorySearchTool, MemorySaveTool))
    ]

    assert {type(tool) for tool in memory_tools} == {MemorySearchTool, MemorySaveTool}
    assert all(tool.memory is agent.memory_manager for tool in memory_tools)


def test_bare_agent_does_not_register_memory_tools():
    agent = SageAgent(bare=True)

    assert not any(
        isinstance(tool, (MemorySearchTool, MemorySaveTool))
        for tool in agent.tool_registry.list()
    )
```

Adapt only the constructor arguments required by the actual signature; do not bypass the production constructor or manually call `set_memory_manager()` in the test.

- [ ] **Step 3: Run the legacy tests and verify the new test fails**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/integration/test_memory_tool_injection.py::test_non_bare_agent_injects_its_memory_manager -q
```

Expected: FAIL because the registered memory tools currently have `memory is None`. The bare-agent test may pass before implementation and is a regression guard.

- [ ] **Step 4: Write the minimal legacy-path implementation**

In the non-bare branch immediately after:

```python
register_all_tools(self.tool_registry, policy=policy)
```

import `MemorySearchTool` and `MemorySaveTool`, then set each memory tool's manager. Use the already-created `self.memory_manager` as the source of truth; do not call the registry singleton a second time in this path:

```python
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

register_all_tools(self.tool_registry, policy=policy)
for tool in self.tool_registry.list():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(self.memory_manager)
```

Keep the injection inside the non-bare branch so bare agents retain their current no-memory behavior.

- [ ] **Step 5: Write a failing integration test for `InprocToolAdapter`**

Add a test that constructs `InprocToolAdapter(registry=None)`, obtains the underlying registered memory tools through the adapter's registry as exposed by the existing test conventions (or use the registry object passed into the adapter if the current API does not expose it), and asserts both memory tools have a non-`None` manager. The test must exercise the constructor's `register_all_tools()` branch, not manually register tools.

```python
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter


def test_inproc_adapter_injects_memory_manager():
    adapter = InprocToolAdapter()
    memory_tools = [
        tool
        for tool in adapter._registry.list()
        if isinstance(tool, (MemorySearchTool, MemorySaveTool))
    ]

    assert {type(tool) for tool in memory_tools} == {MemorySearchTool, MemorySaveTool}
    assert all(tool.memory is not None for tool in memory_tools)
```

Use the existing private-registry testing style if present; do not introduce a public API solely for this test.

- [ ] **Step 6: Run the new test to verify it fails**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/integration/test_memory_tool_injection.py::test_inproc_adapter_injects_memory_manager -q
```

Expected: FAIL because `InprocToolAdapter` currently registers tools without setting a manager.

- [ ] **Step 7: Write the minimal in-process implementation**

In `InprocToolAdapter.__init__`, immediately after:

```python
register_all_tools(self._registry, policy=self._policy)
```

retrieve the shared manager once and inject it into every registered memory tool:

```python
from backend.memory.registry import get_memory_manager
from backend.tools.memory_tool import MemorySaveTool, MemorySearchTool

register_all_tools(self._registry, policy=self._policy)
memory_manager = get_memory_manager()
for tool in self._registry.list():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(memory_manager)
```

Do not alter behavior when a caller supplies an existing registry; the adapter must not silently mutate externally-owned registrations unless the existing constructor contract already does so.

- [ ] **Step 8: Run the complete Task 1 test set**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/integration/test_memory_tool_injection.py \
  backend/tests/unit/test_memory_tool.py -q
```

Expected: all tests pass, including the existing negative tests that intentionally verify an unconfigured standalone memory tool still returns `未初始化`.

- [ ] **Step 9: Commit the production wiring**

```bash
git add backend/core/legacy/agent.py \
  backend/adapters/out/tool/inproc_adapter.py \
  backend/tests/integration/test_memory_tool_injection.py
git commit -m "fix(memory): inject manager into registered memory tools"
```

---

### Task 2: Bundle and verify certifi on Win7

**Files:**
- Modify: `backend/requirements-py38.txt:29-33`
- Modify: `scripts/bundle-python.ps1:261-268`

**Interfaces:**
- Consumes: Win7 `requirements-py38.txt` used by `scripts/bundle-python.ps1`.
- Produces: the bundled interpreter can import `certifi`, resolve `certifi.where()`, and report a non-empty CA file during the existing fail-fast verification step.

- [ ] **Step 1: Add the Win7 dependency declaration**

Add an explicit, Python-3.8-compatible certifi requirement in the HTTP section:

```text
certifi>=2024.7.4  # CA bundle required by httpx in the Win7 embeddable Python
```

Do not add main requirements in this task; main dependency synchronization is handled after the Win7 branch commit is available.

- [ ] **Step 2: Extend the bundle canary before implementation verification**

Update the PowerShell verification command to import `certifi`, print its version and path, and fail naturally if the path is missing or empty. Preserve all existing canary imports (`fastapi`, `pydantic`, `jieba`, `hnswlib`, `sage_core`, `backend.main`). Use a Python expression that checks `os.path.isfile(certifi.where())` and `os.path.getsize(...) > 0` rather than only importing the module.

```powershell
$verifyCode = "import sys, os, certifi; ca=certifi.where(); assert os.path.isfile(ca) and os.path.getsize(ca) > 0, ca; print(f'Python {sys.version}'); print(f'certifi {certifi.__version__} @ {ca} ({os.path.getsize(ca)} bytes)'); import fastapi; import pydantic; import jieba; import hnswlib; import sage_core; import backend.main; print('All critical imports successful (certifi + hnswlib + sage_core + backend.main OK)')"
$verifyOutput = & $EmbedPython -c $verifyCode 2>&1
```

Keep the existing `$verifyExit` handling and failure message so a missing CA bundle blocks release packaging.

- [ ] **Step 3: Run static validation of the PowerShell change**

If PowerShell is available, run:

```bash
pwsh -NoProfile -Command "\$null = [System.Management.Automation.Language.Parser]::ParseFile('scripts/bundle-python.ps1', [ref]\$null, [ref]\$null); if (\$?) { 'PowerShell syntax parsed' }"
```

If `pwsh` is unavailable on Linux, inspect the generated `$verifyCode` quoting and record the local limitation; do not install packages into the system or conda base environment.

- [ ] **Step 4: Verify the dependency and canary text**

Run:

```bash
grep -n "certifi" backend/requirements-py38.txt scripts/bundle-python.ps1
```

Expected: one dependency declaration and one verification reference. If the Win7 bundling environment is available, run the full script in its supported CI/Windows environment; otherwise leave the actual embeddable download/build to CI.

- [ ] **Step 5: Commit the Win7 packaging fix**

```bash
git add backend/requirements-py38.txt scripts/bundle-python.ps1
git commit -m "fix(win7): bundle certifi for httpx SSL verification"
```

---

### Task 3: Add safe SSL CA bootstrap and tests

**Files:**
- Modify: `backend/main.py:1-14` and application startup wiring
- Create: `backend/tests/unit/test_ssl_bootstrap.py`

**Interfaces:**
- Consumes: optional installed `certifi` package and process environment.
- Produces: `configure_ssl_ca_bundle()` (or an equivalent private helper with the exact tested signature) that returns the selected CA path or `None`, sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, and `CURL_CA_BUNDLE` only when a valid certifi file exists, and never overwrites pre-existing values.

- [ ] **Step 1: Define the helper contract in the failing tests**

Create tests around a small helper rather than reloading the entire FastAPI module for every case. The helper should accept injectable certifi/path dependencies so tests do not mutate real process configuration:

```python
def test_configure_ssl_ca_bundle_sets_missing_variables(monkeypatch, tmp_path):
    ca_file = tmp_path / "cacert.pem"
    ca_file.write_text("CA CERTIFICATE\n", encoding="utf-8")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

    selected = configure_ssl_ca_bundle(lambda: str(ca_file))

    assert selected == str(ca_file)
    assert os.environ["SSL_CERT_FILE"] == str(ca_file)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(ca_file)
    assert os.environ["CURL_CA_BUNDLE"] == str(ca_file)


def test_configure_ssl_ca_bundle_preserves_user_values(monkeypatch, tmp_path):
    ca_file = tmp_path / "cacert.pem"
    ca_file.write_text("CA CERTIFICATE\n", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", "custom-ssl.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "custom-requests.pem")
    monkeypatch.setenv("CURL_CA_BUNDLE", "custom-curl.pem")

    selected = configure_ssl_ca_bundle(lambda: str(ca_file))

    assert selected == str(ca_file)
    assert os.environ["SSL_CERT_FILE"] == "custom-ssl.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "custom-requests.pem"
    assert os.environ["CURL_CA_BUNDLE"] == "custom-curl.pem"


def test_configure_ssl_ca_bundle_ignores_missing_or_empty_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.pem"
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    assert configure_ssl_ca_bundle(lambda: str(missing)) is None
    assert "SSL_CERT_FILE" not in os.environ

    empty = tmp_path / "empty.pem"
    empty.touch()
    assert configure_ssl_ca_bundle(lambda: str(empty)) is None
    assert "SSL_CERT_FILE" not in os.environ


def test_configure_ssl_ca_bundle_handles_certifi_error(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    assert configure_ssl_ca_bundle(lambda: (_ for _ in ()).throw(ImportError())) is None
    assert "SSL_CERT_FILE" not in os.environ
```

The implementation may use a callable parameter solely for testability, e.g. `where: Callable[[], str]`, while production startup passes `certifi.where`. Keep the public surface private if the module convention supports it.

- [ ] **Step 2: Run the bootstrap tests and verify they fail**

Run with the project backend environment:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_ssl_bootstrap.py -q
```

Expected: FAIL because the helper does not yet exist.

- [ ] **Step 3: Implement the helper with explicit validity checks**

Add a small helper near the top of `backend/main.py` after the module docstring and before importing modules that construct HTTP clients:

```python
from collections.abc import Callable
from typing import Optional


def configure_ssl_ca_bundle(where: Callable[[], str]) -> Optional[str]:
    try:
        ca_path = where()
    except Exception:
        return None
    if not os.path.isfile(ca_path) or os.path.getsize(ca_path) <= 0:
        return None
    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(variable, ca_path)
    return ca_path
```

Use a guarded certifi import at module import/startup time:

```python
try:
    import certifi
except ImportError:
    certifi = None

if certifi is not None:
    configure_ssl_ca_bundle(certifi.where)
```

Use the Python-version-compatible typing/import idiom already used by the target branch; do not introduce PEP 604 syntax into the Python 3.8 branch. Do not use a bare `del` cleanup for names that may not have been assigned after an import failure.

- [ ] **Step 4: Run the bootstrap tests and verify they pass**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_ssl_bootstrap.py -q
```

Expected: all four bootstrap tests PASS.

- [ ] **Step 5: Run relevant import and backend regression tests**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/test_memory_tool.py \
  backend/tests/unit/test_ssl_bootstrap.py \
  backend/tests/integration/test_memory_tool_injection.py \
  backend/tests/memory/test_lifecycle_extractor_wiring.py -q
```

Expected: all selected tests pass and `backend.main` imports successfully. If the branch's test markers or fixture setup require a narrower invocation, record the exact failure and adjust only the command, not the test assertions.

- [ ] **Step 6: Commit the SSL bootstrap**

```bash
git add backend/main.py backend/tests/unit/test_ssl_bootstrap.py
git commit -m "fix(backend): bootstrap SSL CA bundle from certifi"
```

---

### Task 4: Update docs, review, and prepare the main synchronization

**Files:**
- Modify: `docs/superpowers/specs/README.md`
- Create: `docs/superpowers/ideas/2026-08-20-extractor-session-provider.md`
- Review: all files changed by Tasks 1–3

**Interfaces:**
- Consumes: the approved design spec and the three implementation commits.
- Produces: indexed spec, explicit follow-up idea, clean Win7 branch, and a cherry-pick recipe for main.

- [x] **Step 1: Add the new spec to the specs index**

Append a row to `docs/superpowers/specs/README.md` in date order:

```markdown
| 2026-08-20 | [Win7 Memory Manager Initialization and SSL Fix](./2026-08-20-win7-memory-manager-init-design.md) | memory tool 注入、Win7 certifi 打包与 SSL CA bootstrap |
```

- [x] **Step 2: Record the extractor follow-up without implementing it**

Create `docs/superpowers/ideas/2026-08-20-extractor-session-provider.md` with exactly these decisions:

```markdown
# MemoryExtractor 复用当前 Session LLM Provider

## 背景
`_build_lifecycle_extractor()` 和 legacy `ChatService._extract_and_store_memory()` 当前使用默认 `HttpxLLMAdapter()`，没有继承当前对话传入的 `llm_config` / provider URL。内网 OpenAI-compatible endpoint 因此可能出现主对话走内网、后台 extractor 仍走默认 OpenAI 的不一致。

## 后续目标
让 extractor 通过显式注入的 session/provider LLM client 运行，并为 provider 切换、异步提取和失败降级补充单测与集成测试。

## 本次不做
本 follow-up 不修改当前修复中的 memory-tool wiring、Win7 certifi 依赖或 SSL bootstrap。
```

- [ ] **Step 3: Run formatting, lint, and changed-test checks**

Run the branch-supported checks using the Win7 environment for backend Python:

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/test_memory_tool.py \
  backend/tests/unit/test_ssl_bootstrap.py \
  backend/tests/integration/test_memory_tool_injection.py \
  backend/tests/memory/test_lifecycle_extractor_wiring.py -q
ruff check backend/core/legacy/agent.py \
  backend/adapters/out/tool/inproc_adapter.py \
  backend/main.py \
  backend/tests/unit/test_ssl_bootstrap.py \
  backend/tests/integration/test_memory_tool_injection.py
```

Expected: tests and Ruff pass. If the repository's Ruff config rejects the Python 3.8-compatible import style, follow the existing branch style without changing behavior.

- [ ] **Step 4: Review the complete diff and security-sensitive boundaries**

Run:

```bash
git diff --check
git diff release/win7...HEAD --stat
git diff release/win7...HEAD -- backend/core/legacy/agent.py backend/adapters/out/tool/inproc_adapter.py backend/main.py scripts/bundle-python.ps1
```

Confirm:
- no secrets or internal endpoint values were added to source/docs;
- `setdefault` preserves user certificate overrides;
- bare agents and externally supplied registries retain their prior contract;
- the bundle canary fails on missing/empty CA files;
- no extractor session-provider implementation slipped into the branch.

- [ ] **Step 5: Commit docs/index changes**

```bash
git add docs/superpowers/specs/README.md \
  docs/superpowers/ideas/2026-08-20-extractor-session-provider.md
git commit -m "docs: record memory provider follow-up and fix spec"
```

- [ ] **Step 6: Push the Win7 branch and open the PR**

Before pushing, confirm the branch is based on `release/win7` and contains only the intended commits:

```bash
git status --short
git log --oneline --decorate -4
git push -u origin fix/win7-memory-manager-init
gh pr create --base release/win7 --head fix/win7-memory-manager-init \
  --title "fix(win7): initialize memory tools and bundle SSL CA" \
  --body-file /tmp/win7-memory-manager-init-pr.md
```

The PR body must summarize the two independent root causes, list the three commits, and include the exact changed-test commands. Do not merge or delete `release/win7`.

- [ ] **Step 7: Prepare the main cherry-pick branch only after Win7 commits are stable**

After the Win7 branch commits exist (and before any merge if the user wants parallel PRs), create a separate local branch from current `main`:

```bash
git switch main
git switch -c fix/main-memory-manager-init
```

Cherry-pick only the memory wiring and SSL bootstrap commits. Resolve the commit IDs from the commit subjects rather than copying the Win7-only packaging commit:

```bash
MEMORY_WIRING_SHA="$(git log fix/win7-memory-manager-init --format=%H --grep='fix(memory): inject manager into registered memory tools' -1)"
SSL_BOOTSTRAP_SHA="$(git log fix/win7-memory-manager-init --format=%H --grep='fix(backend): bootstrap SSL CA bundle from certifi' -1)"
test -n "$MEMORY_WIRING_SHA" && test -n "$SSL_BOOTSTRAP_SHA"
git cherry-pick "$MEMORY_WIRING_SHA" "$SSL_BOOTSTRAP_SHA"
```

Then add `certifi` to both `backend/requirements.txt` and `backend/requirements-bundled.txt`, because main's bundle has its own manifest:

```text
certifi>=2024.7.4  # CA bundle required by httpx SSL verification
```

Run main's backend tests in `sage-backend`, then commit the dependency changes:

```bash
git add backend/requirements.txt backend/requirements-bundled.txt
git commit -m "build: include certifi in bundled backend dependencies"
```

Do not cherry-pick the Win7-only `requirements-py38.txt` or `scripts/bundle-python.ps1` commit into main.

- [ ] **Step 8: Run main verification and open the synchronization PR**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_memory_tool.py \
  backend/tests/unit/test_ssl_bootstrap.py \
  backend/tests/integration/test_memory_tool_injection.py -q
ruff check backend/core/legacy/agent.py \
  backend/adapters/out/tool/inproc_adapter.py \
  backend/main.py \
  backend/tests/unit/test_ssl_bootstrap.py \
  backend/tests/integration/test_memory_tool_injection.py
git diff --check
git push -u origin fix/main-memory-manager-init
```

Open a PR from `fix/main-memory-manager-init` to `main`, explicitly noting that it is a cherry-pick synchronization of the general memory wiring and SSL bootstrap, with main-specific certifi manifests.

---

## Final acceptance checklist

- [ ] Win7 branch has four focused commits: memory wiring, Win7 certifi/bundle verify, SSL bootstrap, docs/index.
- [ ] New integration tests prove both production registration paths inject a non-`None` memory manager.
- [ ] Existing standalone negative tests still prove an unconfigured tool reports `未初始化` rather than hiding invalid construction.
- [ ] SSL tests prove certifi setup, user override preservation, invalid file handling, and missing certifi handling.
- [ ] Win7 bundle verification imports certifi and rejects missing/empty `cacert.pem`.
- [ ] Relevant tests and Ruff pass in the correct Python environments.
- [ ] Win7 PR is opened against `release/win7`; main PR is opened against `main` via cherry-pick.
- [ ] No merge or deletion of `release/win7` is performed.
- [ ] Extractor provider propagation is documented as follow-up only.
