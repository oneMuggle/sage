# Win7 "记忆管理器未初始化" + SSL 缺失 修复 — Design Spec

**日期**：2026-08-20
**作者**：Claude + 用户
**目的**：解决 Sage Win7 安装版用户实测报告的"记忆管理器未初始化"以及潜在的 Win7 打包 Python 缺 CA 证书导致 LLM 调用 SSL 失败的连锁问题。
**范围**：3 个独立修复点（PR-A / PR-B / PR-C），合并为单个 PR。
**决策**：合并为 1 个 PR / 全做 / 同步 cherry-pick PR-A + PR-C 到 main / Bug D（extractor 复用 session provider）作为 follow-up 不入本 fix。

---

## 1. 背景

用户在 v0.4.9-alpha.1-win7（基于最新 GitHub release 下载）装机后实测报告：
- UI 显示 **"记忆管理器未初始化"** 错误
- 任何调用 `memory_search` / `memory_save` 工具的对话全部失败
- 后端日志出现 `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate` + `HTTP 502 Bad Gateway` + `LLMError` + `LLM 事实提取失败，降级为关键词提取`

经代码级定位（Explore agent 全仓扫描），确认是 **2 个独立 bug 叠加**导致用户看到的症状：

### Bug A: 工具注册时 `memory_manager` 未注入（PR-A，对应原 PR-C）

| 项 | 详情 |
|---|---|
| 错误串 | `"记忆管理器未初始化"` |
| 抛出位置 | `backend/tools/memory_tool.py:57` (`MemorySearchTool.execute`)、`:128` (`MemorySaveTool.execute`) |
| 根因 | `memory_manager` 默认 `None`；生产代码 0 处调 `set_memory_manager()` |
| 触发路径 | `register_all_tools()` 注入工具 → LLM 调 `memory_search`/`memory_save` → 工具 `execute()` 内 `if self.memory is None` 分支 → 返回 `ToolResult(success=False, error="记忆管理器未初始化")` |

**生产代码的两个调用点**：
1. `backend/core/legacy/agent.py:270` — `SageAgent.__init__`
2. `backend/adapters/out/tool/inproc_adapter.py:71` — `InprocToolAdapter.__init__`

两者都 `register_all_tools(registry)` 之后**没有任何代码**把 `get_memory_manager()` 注入到工具实例。**唯一**调过 `set_memory_manager()` 的代码在 `backend/tests/unit/test_memory_tool.py` 里（`:93, :159`），所以测试通过但生产崩。

### Bug B: Win7 打包 Python 缺 certifi（PR-B）

| 项 | 详情 |
|---|---|
| 失败位置 | `httpx` 默认 `verify=True` 调 `https://api.openai.com` |
| 根因 | `backend/requirements-py38.txt` / `requirements.txt` / `requirements-bundled.txt` 三份依赖清单**全都没有 `certifi`**；Win7 嵌入的 Python embeddable 因此不包含 `cacert.pem`，`ssl.create_default_context()` 拿不到 CA bundle |
| 默认目标 | `backend/core/legacy/llm_client.py:83`：`base_url = "https://api.openai.com/v1"`（硬编码，无 env override） |
| 触发路径 | `_build_lifecycle_extractor()` (`main.py:149-161`) 用 `HttpxLLMAdapter()` 默认配置 → 后台 `MemoryExtractor._extract_with_llm` → `LLMClient.chat` → `httpx.AsyncClient(verify=True)` 调 OpenAI → `CERTIFICATE_VERIFY_FAILED` → `httpx.HTTPStatusError`/`ConnectError` → 重抛 `LLMError` |

### 为什么 Bug B 单独不爆"未初始化"

`MemoryLifecycleManager` 在 `lifecycle.py:214-216` 已经 `try/except` 吞了 extractor 的失败，只打 `"LLM 事实提取失败，降级为关键词提取"` 日志，**不冒泡到 UI**。所以 Bug B 单独只产生一条 warning 日志 + 主对话 LLM 也可能受影响，但不会显示"未初始化"。

### 两个 bug 叠加的真实症状

- 用户看到的"未初始化"**完全来自 Bug A**
- Bug B 是同时存在的独立问题：用户当前用的是内网 `http://` 端点（log 显示 `http://7.35.190.11:62202/...`）→ 主对话走 `llm_proxy` 转发没受影响；但后台 extractor 仍走默认 OpenAI → 即使没爆用户也会看到那条 warning；任何**用 HTTPS OpenAI 的用户在 Win7 装机后立即会主对话爆**。
- 修 Bug A 立刻消除用户报告的"未初始化"；修 Bug B 是治本，把"Win7 用户用 OpenAI 必爆"这个潜在风险也堵掉。

---

## 2. 目标

三个修复全部合并到 `release/win7`，并在 main 分支 cherry-pick PR-A + PR-C + certifi 依赖清单（PR-B 不需要 cherry-pick 因为 win7 专属）。效果：
- Win7 用户装机后**任何代码路径**调用 `memory_search` / `memory_save` 工具都不再返回"未初始化"
- 即使用户配置了 `https://` 远程 LLM 端点，Win7 打包 Python 也能正常验证 SSL（不再 `CERTIFICATE_VERIFY_FAILED`）
- main 分支用户体验同改善（PR-A 是 web 通用 bug；PR-C 是保险丝）

完成后可出 `v0.4.10-alpha.1-win7` 或合并到下一次 win7 LTS 滚动发布。

---

## 3. 设计

### PR-A: MemorySearchTool / MemorySaveTool 注入 `memory_manager`

**改动文件**：
- `backend/core/legacy/agent.py:255-271`
- `backend/adapters/out/tool/inproc_adapter.py:50-72`

**当前行为**：
```python
# agent.py:260-271
self.memory_manager = MemoryManager(working, episodic, semantic)
self.tool_registry = ToolRegistry()
register_all_tools(self.tool_registry, policy=policy)
# ❌ 没接 set_memory_manager()
```

```python
# inproc_adapter.py:60-71
self._registry = registry if registry is not None else _ToolRegistry()
# ...
if registry is None:
    from backend.tools import register_all_tools
    register_all_tools(self._registry, policy=self._policy)
# ❌ 没接 set_memory_manager()
```

**修复**：

```python
# agent.py:270 之后新增
from backend.memory.registry import get_memory_manager
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

register_all_tools(self.tool_registry, policy=policy)
# PR-A fix: 注入全局 memory_manager 单例到所有 memory 工具
_memory_manager = self.memory_manager or get_memory_manager()
for tool in self.tool_registry.list():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(_memory_manager)
```

```python
# inproc_adapter.py:71 之后新增
from backend.memory.registry import get_memory_manager
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

register_all_tools(self._registry, policy=self._policy)
# PR-A fix: hex 路径也注入 memory_manager
_memory_manager = get_memory_manager()
for tool in self._registry.list():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(_memory_manager)
```

**为什么不用 `set_memory_manager()` 在测试里那种用法**：测试是直接 new `MemorySearchTool(memory_manager=...)` 然后调 `set_memory_manager`。生产代码是 `register_all_tools()` 内批量注册再后处理，更稳。

**为什么双路径都要改**：
- `agent.py` 是 legacy 路径（`/chat/stream` 走这里）
- `inproc_adapter.py` 是 hex 路径（其他 endpoint 走这里）
- 任一路径漏了，那个路径仍会爆"未初始化"

**bare 模式（`agent.py:255` `if bare:` 分支）**：bare 模式跳过 `register_all_tools()` 也跳过 memory stack，所以**不需要**改 bare 分支。

**测试**：

| 测试 | 文件 | 覆盖 |
|---|---|---|
| 新增 | `backend/tests/integration/test_memory_tool_injection.py` | 启动 `SageAgent` 后断言 `MemorySearchTool.memory is not None` 且 `isinstance(tool.memory, MemoryManager)` |
| 新增 | 同上 | 启动 `InprocToolAdapter()` 后断言 `MemorySearchTool.memory is not None` |
| 现有 | `backend/tests/unit/test_memory_tool.py` | 单元级 `set_memory_manager()` 行为（无需改） |
| 现有 | `backend/tests/integration/test_chat_office_tools.py:281-306` | 注册表构造路径（无需改） |

**风险**：启动期多遍历一次工具列表（< 30 个工具），开销可忽略。`self.memory_manager or get_memory_manager()` 的 `or` 保证 `SageAgent` 内已经构造好的实例优先，避免重复构造。

### PR-B: Win7 打包 Python 注入 certifi

**改动文件**：
- `backend/requirements-py38.txt`（新增）
- `scripts/bundle-python.ps1:261-263`（verify step 增加 certifi 检查）

**改动**：

```diff
# backend/requirements-py38.txt (在 "# HTTP" 段附近)
 # HTTP
 httpx==0.26.0
 python-multipart==0.0.9  # required for FastAPI File() / Form() in legacy_routes.py
+certifi>=2024.7.4  # PR-B: SSL CA bundle for httpx; required on Win7 bundled Python
```

```diff
# scripts/bundle-python.ps1 (现有 verify 之后追加)
 Write-Host "Testing Python imports (backend.main + sage_core canaries)..." -ForegroundColor Green
 $EmbedPython = Join-Path $PythonDir "python.exe"
-$verifyOutput = & $EmbedPython -c "import sys; print(f'Python {sys.version}'); import fastapi; import pydantic; import jieba; import hnswlib; import sage_core; import backend.main; print('All critical imports successful (hnswlib + sage_core + backend.main OK)')" 2>&1
+$verifyOutput = & $EmbedPython -c "import sys, os, certifi; print(f'Python {sys.version}'); print(f'certifi {certifi.__version__} @ {certifi.where()} ({os.path.getsize(certifi.where())} bytes)'); import fastapi; import pydantic; import jieba; import hnswlib; import sage_core; import backend.main; print('All critical imports successful (hnswlib + sage_core + backend.main OK)')" 2>&1
 $verifyExit = $LASTEXITCODE
```

**为什么 `>=2024.7.4`**：certifi 2024-07-04 包含当前所有常用 CA 根证书，且体积最小（~280KB）。用 `>=` 而非 `==` 避免和 main 分支强绑版本号。

**为什么不在 main 分支 cherry-pick**：
- main 分支用 `scripts/bundle-python-main.ps1`（conda-based 打包，certifi 通过 conda-forge 自动带入）
- 仅 Win7 embeddable 需要显式列出

**测试**：
- `scripts/bundle-python.ps1` 的 verify step 加了 certifi 路径/字节输出 → CI 阶段必验证
- 手动验证：装 Win7 包后 `resources/python/python.exe -c "import certifi; print(certifi.where())"` 应输出非空路径

**风险**：打包体积增加 ~280KB（cacert.pem），可接受。

### PR-C: `backend/main.py` 启动时 SSL 环境变量兜底

**改动文件**：`backend/main.py:1-13`（在所有 import 之前）

**当前行为**：`backend/main.py` 顶部 0 个 SSL 相关设置。embeddable Python 的 `ssl.create_default_context()` 在没有 `certifi` 数据时会回退到系统 trust store，Win7 上系统 trust store 通常是空的或不全。

**修复**：

```python
# backend/main.py 最顶部（第 1 行之前，在文件 docstring 之后）
"""
Sage - 记忆型 AI 桌面助手
FastAPI 后端入口
"""
# PR-C: SSL CA bundle bootstrap. Embeddable Python on Win7 LTS does not
# include a CA trust store by default; without this, httpx (verify=True) cannot
# reach https://*.openai.com etc. and the user sees SSL 502 → "memory
# manager not initialized" downstream. Try certifi first; fall back silently
# (httpx will use system trust store if certifi is unavailable or empty).
import os as _ssl_bootstrap_os
try:
    import certifi as _ssl_bootstrap_certifi
    _ssl_bootstrap_ca = _ssl_bootstrap_certifi.where()
    if _ssl_bootstrap_os.path.exists(_ssl_bootstrap_ca) and _ssl_bootstrap_os.path.getsize(_ssl_bootstrap_ca) > 0:
        _ssl_bootstrap_os.environ.setdefault("SSL_CERT_FILE", _ssl_bootstrap_ca)
        _ssl_bootstrap_os.environ.setdefault("REQUESTS_CA_BUNDLE", _ssl_bootstrap_ca)
        _ssl_bootstrap_os.environ.setdefault("CURL_CA_BUNDLE", _ssl_bootstrap_ca)
except Exception:
    pass  # certifi not installed yet — httpx will surface a clearer error later
del _ssl_bootstrap_os, _ssl_bootstrap_certifi, _ssl_bootstrap_ca  # hygiene
```

**为什么用 `_ssl_bootstrap_*` 前缀**：避免污染 module namespace；`del` 保证不暴露内部变量。

**为什么 `setdefault` 而非 `=`**：用户可能用环境变量指定自己的证书（开发 / 公司内网 CA），我们不应该覆盖。

**为什么 `try/except` 吞错**：certifi 可能在打包遗漏时缺失；我们不想因为 certifi 缺失就让整个 backend 启动失败——httpx 后续会自己报错，错误信息至少明确。

**为什么三个环境变量都设**：
- `SSL_CERT_FILE` 是 Python `ssl` 模块和 httpx 的官方查找路径
- `REQUESTS_CA_BUNDLE` 是 requests/urllib3 用
- `CURL_CA_BUNDLE` 是 libcurl / aiohttp 用

`setdefault` 保证已有值不被破坏。

**测试**：

```python
# backend/tests/unit/test_ssl_bootstrap.py (新增)
def test_ssl_cert_env_var_set_when_certifi_present(monkeypatch):
    monkeypatch.setattr("os.environ", {})  # 清空
    monkeypatch.setitem(os.environ, "SSL_CERT_FILE", "")  # 但保留 key
    # ... 重 import main 模块 ...
    assert "SSL_CERT_FILE" in os.environ
    assert os.environ["SSL_CERT_FILE"].endswith("cacert.pem")
    assert os.path.getsize(os.environ["SSL_CERT_FILE"]) > 1000

def test_ssl_cert_env_var_preserves_user_override(monkeypatch):
    custom = "/path/to/custom.pem"
    monkeypatch.setenv("SSL_CERT_FILE", custom)
    # ... 重 import main ...
    assert os.environ["SSL_CERT_FILE"] == custom

def test_ssl_cert_handles_missing_certifi(monkeypatch):
    # 模拟 certifi 不存在的场景
    monkeypatch.setattr(sys, "modules", {k: v for k, v in sys.modules.items() if k != "certifi"})
    # ... 重 import main ...
    # 不抛错，环境变量不强制设置
```

**风险**：
- 把 `os.environ.setdefault` 加到启动最早期，可能在 `pytest` fixture / 测试隔离上有副作用 → 测试用 `monkeypatch.setattr("os.environ", {})` 隔离
- `del` 在 import time 删变量——CPython 优化掉这些 del 是常数级开销，可忽略

**cherry-pick 到 main**：
- main 分支虽然 conda 自带 certifi，但**仍然需要这个修复**——任何内网 / 离线环境如果用 `pip install` 缺少 certifi，主对话会爆。main 同步这个修复是低风险高收益。

---

## 4. 不在本 fix 范围

### Bug D: `MemoryExtractor` 用全局默认 LLM（extractor 不复用 session provider）

- 路径：`backend/main.py:149-161` (`_build_lifecycle_extractor()`) + `backend/application/services/chat_service.py:614-638` (`_extract_and_store_memory()`)
- 现状：两个 extractor 都用 `HttpxLLMAdapter()` 默认配置，**忽略**前端传的 `X-LLM-Provider-Url` / per-request `llm_config`
- 表现：用户配的是内网 provider，但后台记忆提取仍走 OpenAI 默认 → SSL 502 → 静默降级
- **为什么不入本 fix**：
  1. PR-A + PR-B + PR-C 已经覆盖了症状（"未初始化" 消除 + Win7 SSL 修好）
  2. extractor 复用 session provider 是**架构改动**：要把 session 解析、配置查找、LLM 客户端工厂全部串起来，超出 bug 修复范围
  3. 单独可测、单独可发：可以独立 PR，单独 review
- **作为 follow-up**：记到 `docs/superpowers/ideas/2026-08-20-extractor-session-provider.md`，下个迭代处理

### Bug E: `OpenAIProvider` / `HttpxLLMAdapter` 没显式 `verify=certifi.where()`

- 路径：`backend/core/legacy/llm_client.py:148`、`backend/adapters/out/llm/openai.py:189`、`backend/api/llm_proxy_routes.py:243, 328`
- 现状：所有 `httpx.AsyncClient(verify=True)` 都没显式指定证书
- **为什么不入本 fix**：
  1. PR-C 用环境变量兜底已经覆盖了所有 SSL 验证路径
  2. 显式 `verify=certifi.where()` 是更好的实践但**不是修复当前 bug 的必要条件**
  3. 改动扩散到 4 个文件，需要各自测试覆盖
- **作为 follow-up**：和 Bug D 一起进 follow-up PR

---

## 5. 双分支策略

### release/win7 (主目标)

新分支 `fix/win7-memory-manager-init`（基于 `release/win7`），3 个修复 + 3 个 commit：

```
fix/win7-memory-manager-init
├── commit 1 (PR-A)  fix(memory): inject memory_manager into MemorySearchTool/SaveTool
├── commit 2 (PR-B)  fix(win7): add certifi to requirements-py38.txt + verify
└── commit 3 (PR-C)  fix(backend): SSL CA bundle bootstrap via certifi env vars
```

**PR** → release/win7，CI 5/5+skip 全跑通后合。

### main (同步 cherry-pick)

新分支 `fix/main-memory-manager-init`（基于 `main`），cherry-pick commit 1 (PR-A) + commit 3 (PR-C) + 对 main 依赖清单的等价改动：

```
fix/main-memory-manager-init
├── cherry-pick commit 1 (PR-A)  fix(memory): inject memory_manager
├── cherry-pick commit 3 (PR-C)  fix(backend): SSL CA bundle bootstrap
└── commit N (新写)             chore(requirements): add certifi to requirements.txt + requirements-bundled.txt
```

**PR** → main，CI 5/5 全跑通后合。

**为什么不 cherry-pick PR-B**：PR-B 的改动只在 `requirements-py38.txt`（win7 专属）和 `scripts/bundle-python.ps1`（win7 打包脚本），main 用 `requirements.txt` + `bundle-python-main.ps1`，所以 PR-B 不需要 cherry-pick。但 main 也需要 certifi，所以单独写一个 commit 把 certifi 加到 main 的依赖清单。

---

## 6. 验证

| 阶段 | 验证方法 | 通过标准 |
|---|---|---|
| 单测 | `pytest backend/tests/unit/test_memory_tool.py`（现有）+ `pytest backend/tests/unit/test_ssl_bootstrap.py`（新增）+ `pytest backend/tests/integration/test_memory_tool_injection.py`（新增） | 全绿 |
| 集成 | `pytest backend/tests/integration/` 全跑 | 全绿，无回归 |
| Win7 打包 | CI 跑 `scripts/bundle-python.ps1` | certifi verify 通过；总包大小 +280KB ± 50KB |
| E2E | 在 Win7 装机上跑：① 启动 → ② 在对话里触发 `memory_search` 工具 → ③ 不再显示"未初始化"；④ 配 `https://api.openai.com` → ⑤ 主对话 SSL 不再 502；⑥ 后台 extractor 不再降级 warning | 全部 ✓ |
| 跨分支 | release/win7 PR + main PR 都合并后 | `git log --grep "memory-manager-init"` 在两个分支都查到 |

### 验证步骤（手动）

**Win7 装机后**：
```bash
# 1. 验证 certifi 在打包 Python 里
"C:\Program Files\Sage\resources\python\python.exe" -c "
import certifi, os
p = certifi.where()
print('certifi:', certifi.__version__, p)
print('size:', os.path.getsize(p))
print('exists:', os.path.exists(p))
"
# 期望：输出非空路径，size > 100000

# 2. 验证 SSL bootstrap 设置了环境变量
"C:\Program Files\Sage\resources\python\python.exe" -c "
import os
print('SSL_CERT_FILE:', os.environ.get('SSL_CERT_FILE'))
print('REQUESTS_CA_BUNDLE:', os.environ.get('REQUESTS_CA_BUNDLE'))
"
# 期望：都指向打包 python 的 certifi cacert.pem

# 3. 直接调 OpenAI 验证 SSL
"C:\Program Files\Sage\resources\python\python.exe" -c "
import httpx
r = httpx.get('https://api.openai.com', timeout=5)
print('openai.com:', r.status_code)
"
# 期望：200（不抛 SSL 错）

# 4. UI 里调用 memory_search 工具
# 期望：返回结果，不显示"未初始化"
```

---

## 7. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| PR-A: `self.memory_manager or get_memory_manager()` 在某种 race 下重复构造 | `self.memory_manager` 已经构造好的优先；race 几乎不存在（agent 构造是同步单线程） | revert PR-A commit |
| PR-B: certifi 版本冲突（如果用户自己装的 venv 有不同版本） | embeddable Python 是隔离的，与系统 venv 无关 | 删 `requirements-py38.txt` 的 certifi 行 |
| PR-C: 环境变量污染测试 | `monkeypatch.setattr("os.environ", {})` + 测试隔离；实际只在 import 时设一次 | 删 `backend/main.py` 顶部 SSL bootstrap 段 |
| cherry-pick 冲突：main 分支 agent.py / main.py 可能已经演进 | commit 单独 → 冲突时手动 rebase 单个 commit | 弃 PR 重开 |
| Win7 打包脚本 verify 失败阻断 release CI | verify step 设计原则是 fail-fast；certifi 必须有 | 修 certifi 安装逻辑而非绕过 verify |

---

## 8. 文件改动清单

| 文件 | 改动类型 | 范围 |
|---|---|---|
| `backend/core/legacy/agent.py` | 修改 | + 9 行（PR-A） |
| `backend/adapters/out/tool/inproc_adapter.py` | 修改 | + 9 行（PR-A） |
| `backend/main.py` | 修改 | + 18 行（PR-C） |
| `backend/requirements-py38.txt` | 修改 | + 1 行（PR-B） |
| `scripts/bundle-python.ps1` | 修改 | + 1 行（PR-B verify） |
| `backend/requirements.txt` | 修改 (main) | + 1 行（cherry-pick） |
| `backend/requirements-bundled.txt` | 修改 (main) | + 1 行（cherry-pick） |
| `backend/tests/integration/test_memory_tool_injection.py` | 新增 | ~ 80 行 |
| `backend/tests/unit/test_ssl_bootstrap.py` | 新增 | ~ 60 行 |
| `docs/superpowers/ideas/2026-08-20-extractor-session-provider.md` | 新增 | Bug D 跟进记录 |

总计 ~180 行代码改动 + 140 行测试。

---

## 9. 实施步骤（详细版到 plan 里）

1. **建分支**：`git switch -c fix/win7-memory-manager-init release/win7`
2. **PR-A 实现**：
   - `Edit backend/core/legacy/agent.py` 加注入循环
   - `Edit backend/adapters/out/tool/inproc_adapter.py` 加注入循环
   - `Write backend/tests/integration/test_memory_tool_injection.py`
3. **PR-A 验证**：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_memory_tool_injection.py -v`
4. **PR-A commit**：`fix(memory): inject memory_manager into MemorySearchTool/SaveTool`
5. **PR-B 实现**：
   - `Edit backend/requirements-py38.txt` 加 certifi 行
   - `Edit scripts/bundle-python.ps1` verify step 加 certifi 输出
6. **PR-B 验证**：本地跑 `pwsh scripts/bundle-python.ps1`（dry-run 模式或 CI 模拟）
7. **PR-B commit**：`fix(win7): bundle certifi CA bundle for httpx SSL verification`
8. **PR-C 实现**：
   - `Edit backend/main.py` 顶部加 SSL bootstrap 段
   - `Write backend/tests/unit/test_ssl_bootstrap.py`
9. **PR-C 验证**：`pytest backend/tests/unit/test_ssl_bootstrap.py -v` + `pytest backend/tests/ -v` 全跑无回归
10. **PR-C commit**：`fix(backend): bootstrap SSL CA bundle via certifi env vars`
11. **推送 + 开 PR**：`git push -u origin fix/win7-memory-manager-init` + `gh pr create`
12. **CI 监控**：`gh pr checks --watch`
13. **CI 绿后让用户 merge**
14. **main cherry-pick**：
    - 切换 main：`git switch main && git pull --rebase`
    - 建分支：`git switch -c fix/main-memory-manager-init`
    - cherry-pick commit 1 (PR-A) + commit 3 (PR-C)
    - 新写一个 commit 加 certifi 到 main 的 requirements.txt + requirements-bundled.txt
    - 推 + 开 PR
15. **Bug D follow-up**：建 `docs/superpowers/ideas/2026-08-20-extractor-session-provider.md`

---

## 10. 验收

- [ ] release/win7 PR 合入
- [ ] main PR 合入
- [ ] 新 win7 LTS 装机验证 4 步手动测试全 ✓
- [ ] CI 全绿无回归
- [ ] 用户在装机版实测："记忆管理器未初始化"消失 + SSL 不再 502
- [ ] Bug D follow-up 文档建好（不下沉到 TODO）
- [ ] 同步更新 `docs/superpowers/specs/README.md` 索引