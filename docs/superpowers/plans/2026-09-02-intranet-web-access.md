# 内网 Web 访问 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让内网（无公网出口）用户能用 Sage 按地址读网页、下载文件，同时用一个显式的网络模式门禁让搜索类出网工具在内网模式下对 LLM 不可见。

**Architecture:** 新增 `NetworkPolicy` 领域对象（frozen dataclass，纯查询方法），配置存 `preferences` KV 表。工具注册期读策略决定 `web_search` / `web_fetch` / `http_download` 是否注册；执行期读策略做 host 白名单校验。`web_fetch` 的正文抽取重写为 stdlib `html.parser` 栈式实现（不引入 lxml，理由见 Task 3），附带编码嗅探。新增 `http_download` 流式落盘工具。

**Tech Stack:** Python 3.8/3.11 双兼容标准库（`html.parser` / `email.message` / `urllib.parse` / `ipaddress` / `dataclasses` / `enum`）；`httpx==0.26.0`；pytest + respx；前端 TypeScript + React + vitest。

**Spec:** `docs/superpowers/specs/2026-09-02-intranet-web-access-design.md`

## Global Constraints

- **Python 版本**：代码必须同时在 Python 3.11（`main`）与 Python 3.8（`release/win7`）运行。注解用 `typing.Dict` / `List` / `Optional` / `Tuple` / `Union`，**不用** PEP 585（`list[x]`）或 PEP 604（`X | Y`）的运行时形式。`from __future__ import annotations` 只让注解变字符串，`isinstance()` 与 `dataclass` 字段的运行时求值在 3.8 仍会崩。
- **ruff 已为此禁用 UP006/UP007/UP035**（`backend/ruff.toml:64-66`），所以写 `typing.List` 不会被自动改回去。不需要在新文件加 `# ruff: noqa: UP006...`，全局配置已覆盖。
- **后端 Python 环境**：所有 pytest / ruff 命令用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不要用系统 `python3`（会 `ModuleNotFoundError: No module named 'fastapi'`）。
- **pytest 工作目录**：从 `backend/` 目录运行（`backend/pytest.ini` 的 `testpaths = tests`）。vitest 从仓库根运行。
- **ruff 配置**：`backend/ruff.toml`，`line-length = 100`，`E501` 已忽略。`T20`（禁 print）、`ERA`（禁注释掉的代码）、`PT`（pytest 风格）、`PTH`、`SIM`、`RET`、`PL` 启用。
- **domain 层零外部依赖**：`backend/domain/` 只能 import 标准库。`backend/pyproject.toml` 的 import-linter 契约把 `backend.domain` 定为最内层，违反会让 CI 红。
- **不新增第三方依赖**：`backend/requirements.txt` 不改。特别是**不引入 lxml** —— Task 3 的原型验证证明它与栈式实现在嵌套表格上产出不一致，而 `requirements.txt` 不声明它会让结果取决于环境里碰巧装了什么。
- **代码注释**：默认不写。只在 WHY 不显然时写一行（隐藏约束、反直觉行为、特定 bug 的规避）。不写「这段代码做什么」。
- **语言**：docstring 与用户可见错误信息用中文，与现有 `backend/tools/` 各模块一致。
- **不加向后兼容 shim**：不保留旧工具别名，不加 feature flag。
- **提交粒度**：每个 Task 结束提交一次，conventional commits。
- **分支**：实施时从 `main` 切 `feat/intranet-web-access`（spec 已在 `docs/intranet-web-access-spec` 分支的 `46c05c09`）。

---

## File Structure

**新建（后端）：**

| 文件 | 责任 | 行数预估 |
|---|---|---|
| `backend/domain/network_policy.py` | `NetworkMode` 枚举 + `NetworkPolicy` frozen dataclass。纯查询，零外部依赖。 | ~130 |
| `backend/tools/network_config.py` | 从 `preferences` KV 加载 `NetworkPolicy`，失败 fail-safe 到 ONLINE。 | ~55 |
| `backend/wiki/html_extract.py` | HTML → `{title, text, links, tables}` + 编码嗅探。stdlib 栈式实现，纯函数无 IO。 | ~230 |
| `backend/tools/download_tool.py` | `HttpDownloadTool`：流式落盘 + 双重大小上限 + 文件名净化。 | ~170 |

**新建（前端）：**

| 文件 | 责任 | 行数预估 |
|---|---|---|
| `src/pages/settings/NetworkTab.tsx` | 模式下拉 + 两个 host 列表编辑器。 | ~180 |

**新建测试：**

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/test_network_policy.py` | 通配匹配、非法通配拒绝、TLS 子集校验、三模式门禁、空白名单 fail-closed |
| `backend/tests/unit/test_network_config.py` | JSON 损坏 / mode 非法 / 类型错误 → fail-safe ONLINE |
| `backend/tests/unit/test_html_extract.py` | script/style 内容剥离、相对链接绝对化、表格抽取、嵌套表格不串味、畸形标记不崩、GBK/GB18030 解码 |
| `backend/tests/unit/test_download_tool.py` | 流式落盘、Content-Length 撒谎、路径边界、文件名净化、无 workspace 拒绝 |
| `src/pages/settings/__tests__/NetworkTab.test.tsx` | 模式切换写 KV、host 增删、空白名单提示 |

**修改：**

| 文件 | 改动 |
|---|---|
| `backend/tools/web_tool.py` | `WebFetchTool` 接抽取层 + 编码嗅探 + `NetworkPolicy` 校验；`WebSearchTool` 不改内部逻辑 |
| `backend/tools/__init__.py` | `register_all_tools` 条件注册三个出网工具 |
| `backend/tools/agent_tool.py` | `build_readonly_tool_registry` 同样门禁 |
| `backend/domain/risk.py` | `EXTERNAL_TOOLS` 加 `http_download` |
| `backend/data/settings_repo.py` | `KEYS` 加 `network_policy` |
| `backend/agents/profiles.py` | researcher 的 `tools` 加 `http_download` |
| `backend/tests/unit/test_tools_registry.py` | 内置工具集合断言适配条件注册 |
| `backend/tests/unit/test_risk.py` | 验收表加 `http_download → EXTERNAL` |
| `src/pages/settings/Settings.tsx` | tabs 加"网络" |
| `src/shared/api/settingsClient.ts` | `PreferenceKey` 加 `network_policy` |
| `src/shared/lib/i18n/{zh,en}.ts` | 文案 |

**任务依赖：**

```
Task 1 (NetworkPolicy 领域模型)
   └─> Task 2 (加载器 + KV 白名单)
          ├─> Task 4 (web_fetch 重写)  <── Task 3 (html_extract，可与 1/2 并行)
          ├─> Task 5 (http_download)
          └─> Task 7 (前端 NetworkTab，只需 Task 2 落库的 key)
Task 4 + Task 5
   └─> Task 6 (条件注册 + risk 表 + profiles + 既有测试适配)
```

Task 3 不依赖任何前序任务，可与 Task 1/2 并行。Task 6 是收口任务：只有它同时
需要 `web_fetch` 与 `http_download` 都已就位。

---

## Task 1: NetworkPolicy 领域模型

**Files:**
- Create: `backend/domain/network_policy.py`
- Test: `backend/tests/unit/test_network_policy.py`

**Interfaces:**
- Consumes: 无（domain 层，只用标准库）
- Produces:
  - `NetworkMode(str, Enum)`：`ONLINE = "online"` / `INTRANET = "intranet"` / `OFFLINE = "offline"`
  - `NetworkPolicy` frozen dataclass，字段 `mode: NetworkMode`、`allowed_hosts: Tuple[str, ...]`、`insecure_tls_hosts: Tuple[str, ...]`
  - `NetworkPolicy.search_enabled() -> bool`
  - `NetworkPolicy.fetch_enabled() -> bool`
  - `NetworkPolicy.check_host(url: str) -> Optional[str]`（返回中文拒绝原因，`None` 放行）
  - `NetworkPolicy.allows_insecure_tls(url: str) -> bool`
  - `NetworkPolicy.from_config(cfg: Dict[str, Any]) -> NetworkPolicy`（classmethod）
  - 模块级 `normalize_host(value: str) -> str`、`host_matches(host: str, pattern: str) -> bool`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_network_policy.py`：

```python
"""NetworkPolicy 领域模型单元测试。"""

import pytest

from backend.domain.network_policy import (
    NetworkMode,
    NetworkPolicy,
    host_matches,
    normalize_host,
)

pytestmark = [pytest.mark.unit]


def test_default_is_online_with_no_hosts():
    policy = NetworkPolicy()
    assert policy.mode is NetworkMode.ONLINE
    assert policy.allowed_hosts == ()
    assert policy.insecure_tls_hosts == ()


def test_normalize_host_lowercases_and_strips_trailing_dot():
    assert normalize_host("A.CNKI.NET.") == "a.cnki.net"
    assert normalize_host("  Docs.Example.Internal  ") == "docs.example.internal"


def test_host_matches_exact():
    assert host_matches("docs.example.internal", "docs.example.internal") is True
    assert host_matches("other.example.internal", "docs.example.internal") is False


def test_host_matches_wildcard_covers_apex_and_all_depths():
    assert host_matches("cnki.net", "*.cnki.net") is True
    assert host_matches("a.cnki.net", "*.cnki.net") is True
    assert host_matches("b.a.cnki.net", "*.cnki.net") is True


def test_host_matches_wildcard_rejects_suffix_confusion():
    # evilcnki.net 不是 cnki.net 的子域，不能因字符串后缀相同就命中
    assert host_matches("evilcnki.net", "*.cnki.net") is False


@pytest.mark.parametrize("bad", ["*", "*.net", "*.", "*.internal", "a.*.net", "*cnki.net"])
def test_overbroad_or_malformed_wildcard_is_rejected(bad):
    with pytest.raises(ValueError, match="通配"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=(bad,))


def test_empty_host_entry_is_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("   ",))


def test_multi_label_wildcard_apex_is_accepted():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("*.a.b.c",))
    assert policy.check_host("https://x.a.b.c/p") is None


def test_insecure_tls_host_must_be_covered_by_allowed_hosts():
    with pytest.raises(ValueError, match="insecure_tls_hosts"):
        NetworkPolicy(
            mode=NetworkMode.INTRANET,
            allowed_hosts=("docs.example.internal",),
            insecure_tls_hosts=("other.example.internal",),
        )


def test_insecure_tls_host_covered_by_wildcard_is_accepted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET,
        allowed_hosts=("*.example.internal",),
        insecure_tls_hosts=("docs.example.internal",),
    )
    assert policy.allows_insecure_tls("https://docs.example.internal/a") is True
    assert policy.allows_insecure_tls("https://other.internal/a") is False


def test_search_enabled_only_in_online():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).search_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).search_enabled() is False
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).search_enabled() is False


def test_fetch_enabled_in_online_and_intranet():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).fetch_enabled() is False


def test_check_host_online_always_allows_ignoring_allowed_hosts():
    policy = NetworkPolicy(mode=NetworkMode.ONLINE, allowed_hosts=("only.example.internal",))
    assert policy.check_host("https://anything.example.com/p") is None


def test_check_host_intranet_allows_whitelisted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET, allowed_hosts=("*.example-mirror.internal",)
    )
    assert policy.check_host("https://a.example-mirror.internal/p") is None


def test_check_host_intranet_rejects_non_whitelisted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET, allowed_hosts=("*.example-mirror.internal",)
    )
    reason = policy.check_host("https://evil.example.com/p")
    assert reason is not None
    assert "白名单" in reason


def test_check_host_intranet_with_empty_whitelist_rejects_everything():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET)
    assert policy.check_host("https://anything.internal/p") is not None


def test_check_host_offline_rejects():
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE, allowed_hosts=("a.internal",))
    assert policy.check_host("https://a.internal/p") is not None


def test_check_host_rejects_url_without_hostname():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("a.internal",))
    assert policy.check_host("not-a-url") is not None


def test_from_config_reads_all_fields():
    policy = NetworkPolicy.from_config(
        {
            "mode": "intranet",
            "allowed_hosts": ["*.example.internal"],
            "insecure_tls_hosts": ["docs.example.internal"],
        }
    )
    assert policy.mode is NetworkMode.INTRANET
    assert policy.allowed_hosts == ("*.example.internal",)
    assert policy.insecure_tls_hosts == ("docs.example.internal",)


def test_from_config_missing_fields_fall_back_to_defaults():
    policy = NetworkPolicy.from_config({})
    assert policy.mode is NetworkMode.ONLINE
    assert policy.allowed_hosts == ()


def test_from_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="NetworkMode"):
        NetworkPolicy.from_config({"mode": "carrier-pigeon"})


@pytest.mark.parametrize("bad", [42, {"a": 1}, "docs.example.internal"])
def test_from_config_rejects_non_list_host_field(bad):
    """裸字符串也要拒：tuple("a.b") 会拆成单字符元组，静默污染白名单。"""
    with pytest.raises(TypeError, match="allowed_hosts"):
        NetworkPolicy.from_config({"allowed_hosts": bad})


def test_from_config_rejects_non_string_host_entry():
    with pytest.raises(TypeError, match="条目"):
        NetworkPolicy.from_config({"allowed_hosts": ["ok.internal", 5]})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_network_policy.py -v
```

预期：collection error，`ModuleNotFoundError: No module named 'backend.domain.network_policy'`

- [ ] **Step 3: 实现领域模型**

创建 `backend/domain/network_policy.py`：

```python
"""网络访问策略领域模型（内网 Web 访问）。

三种模式决定出网工具的注册与 host 准入：

- ``ONLINE``：现状 —— 搜索可用，任意地址可访问（``allowed_hosts`` 不参与判定）。
- ``INTRANET``：搜索不注册；取页/下载仅允许 ``allowed_hosts`` 命中的 host。
- ``OFFLINE``：三个出网工具全部不注册。

**领域纯净性**：仅依赖标准库，不读文件/时钟/网络。配置加载由
``backend.tools.network_config`` 负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


class NetworkMode(str, Enum):
    """网络模式 —— 决定出网工具的注册与 host 准入。"""

    ONLINE = "online"
    INTRANET = "intranet"
    OFFLINE = "offline"


def normalize_host(value: str) -> str:
    """归一化 host：去空白、转小写、去尾点。

    尾点是合法的 FQDN 写法（``a.cnki.net.``），不归一化会让 ``A.CNKI.NET.``
    绕过白名单。
    """
    return value.strip().lower().rstrip(".")


def host_matches(host: str, pattern: str) -> bool:
    """判定 host 是否命中 pattern（精确或 ``*.`` 通配）。

    ``*.cnki.net`` 命中 ``cnki.net`` 自身及任意层级子域。后缀混淆
    （``evilcnki.net``）不命中 —— 通配比对的是"以 ``.cnki.net`` 结尾"，
    不是"以 ``cnki.net`` 结尾"。
    """
    host = normalize_host(host)
    pattern = normalize_host(pattern)
    if not pattern.startswith("*."):
        return host == pattern
    apex = pattern[2:]
    return host == apex or host.endswith("." + apex)


def _validate_pattern(pattern: str) -> None:
    """通配必须是 ``*.`` 前缀且 apex 至少两段，否则白名单形同虚设。

    先判 ``"*" in normalized`` 而非 ``startswith("*.")``：``normalize_host``
    的 ``rstrip(".")`` 会把 ``"*."`` 削成 ``"*"``，用 startswith 判断会让
    ``"*"`` 和 ``"*."`` 都走"非通配"早退分支被放行。
    """
    normalized = normalize_host(pattern)
    if not normalized:
        raise ValueError("host 条目不能为空")
    if "*" not in normalized:
        return
    if not normalized.startswith("*."):
        raise ValueError(f"通配 host {pattern!r} 格式非法：只支持 ``*.`` 前缀")
    apex = normalized[2:]
    if "*" in apex:
        raise ValueError(f"通配 host {pattern!r} 格式非法：``*`` 只能出现一次")
    if apex.count(".") < 1:
        raise ValueError(
            f"通配 host {pattern!r} 过宽：``*.`` 后至少需要两段域名（如 ``*.cnki.net``）"
        )


def _coerce_hosts(value: Any, field: str) -> Tuple[str, ...]:
    """把配置里的 host 列表强制成 ``Tuple[str, ...]``，类型不对就抛。

    不能直接 ``tuple(value)``：dict 会静默变成 key 元组（``{"a": 1}`` →
    ``("a",)``），裸字符串会被拆成单字符元组（``"a.internal"`` → ``("a",
    ".", "i", ...)``）。两种都会让白名单变成一堆无意义条目。
    """
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} 必须是字符串列表")
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field} 条目必须是字符串，得到 {type(item).__name__}")
    return tuple(value)


@dataclass(frozen=True)
class NetworkPolicy:
    """出网访问策略（不可变）。

    Fields:
        mode:               网络模式。
        allowed_hosts:      host 白名单，支持 ``*.`` 前缀通配。仅 ``INTRANET``
                            模式参与判定。
        insecure_tls_hosts: 允许跳过 TLS 校验的 host（内网自签证书）。每一项
                            都必须被 ``allowed_hosts`` 覆盖。
    """

    mode: NetworkMode = NetworkMode.ONLINE
    allowed_hosts: Tuple[str, ...] = ()
    insecure_tls_hosts: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for pattern in self.allowed_hosts:
            _validate_pattern(pattern)
        for pattern in self.insecure_tls_hosts:
            _validate_pattern(pattern)
            if not any(host_matches(pattern, allowed) for allowed in self.allowed_hosts):
                raise ValueError(
                    f"insecure_tls_hosts 条目 {pattern!r} 未被 allowed_hosts 覆盖："
                    "关闭 TLS 校验不能作用于白名单外的 host"
                )

    def search_enabled(self) -> bool:
        """``web_search`` 是否注册。"""
        return self.mode is NetworkMode.ONLINE

    def fetch_enabled(self) -> bool:
        """``web_fetch`` / ``http_download`` 是否注册。"""
        return self.mode is not NetworkMode.OFFLINE

    def check_host(self, url: str) -> Optional[str]:
        """执行期 host 准入。返回中文拒绝原因；``None`` 表示放行。"""
        if self.mode is NetworkMode.ONLINE:
            return None
        if self.mode is NetworkMode.OFFLINE:
            return "network_mode_offline: 当前为气隙模式，禁止一切出网访问"
        hostname = urlparse(url).hostname
        if not hostname:
            return f"invalid_url: 无法从 {url!r} 解析主机名"
        if any(host_matches(hostname, pattern) for pattern in self.allowed_hosts):
            return None
        return (
            f"host_not_allowed: {hostname} 不在内网白名单中"
            "（在设置 → 网络中添加后可访问）"
        )

    def allows_insecure_tls(self, url: str) -> bool:
        """该 URL 的 host 是否豁免 TLS 校验。"""
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        return any(host_matches(hostname, pattern) for pattern in self.insecure_tls_hosts)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> NetworkPolicy:
        """从已解析的 dict 构造，缺字段回退默认。

        非法 ``mode`` 抛 ``ValueError``，host 列表类型不对抛 ``TypeError``；
        两者都由 ``network_config.load_network_policy`` 捕获并 fail-safe。
        """
        defaults = cls()
        raw_mode = cfg.get("mode")
        mode = NetworkMode(raw_mode) if raw_mode is not None else defaults.mode
        return cls(
            mode=mode,
            allowed_hosts=_coerce_hosts(cfg.get("allowed_hosts"), "allowed_hosts"),
            insecure_tls_hosts=_coerce_hosts(
                cfg.get("insecure_tls_hosts"), "insecure_tls_hosts"
            ),
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_network_policy.py -v
```

预期：全部 PASS

- [ ] **Step 5: 跑 ruff 与 import-linter**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check domain/network_policy.py tests/unit/test_network_policy.py
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m importlinter.cli lint --config pyproject.toml
```

预期：ruff 无告警；import-linter `hexagonal-architecture` 契约 KEPT

- [ ] **Step 6: 提交**

```bash
git add backend/domain/network_policy.py backend/tests/unit/test_network_policy.py
git commit -m "feat(domain): 网络访问策略领域模型（online/intranet/offline + host 白名单）"
```

---

## Task 2: 策略加载器 + preferences KV 白名单

**Files:**
- Create: `backend/tools/network_config.py`
- Modify: `backend/data/settings_repo.py:18-33`（`KEYS` frozenset 加 `network_policy`）
- Test: `backend/tests/unit/test_network_config.py`

**Interfaces:**
- Consumes: Task 1 的 `NetworkPolicy` / `NetworkMode` / `NetworkPolicy.from_config`
- Produces:
  - `SETTINGS_KEY_NETWORK_POLICY = "network_policy"`（模块级常量）
  - `load_network_policy(repo: Optional[Any] = None) -> NetworkPolicy`

**为什么合并两件事：** 加载器的测试需要 `SettingsRepository` 能接受
`network_policy` 这个 key，否则 `repo.set_json` 抛 `ValueError: key not in whitelist`。
白名单是加载器的前置配置，不构成独立的可评审交付物。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_network_config.py`：

```python
"""network_config 加载器单元测试。

配置读取失败必须 fail-safe 到 ONLINE（即现状行为）—— 读不出配置不应该
把用户既有能力锁死。
"""

import pytest

from backend.domain.network_policy import NetworkMode
from backend.tools.network_config import (
    SETTINGS_KEY_NETWORK_POLICY,
    load_network_policy,
)

pytestmark = [pytest.mark.unit]


class _FakeRepo:
    """最小 SettingsRepository 替身：只实现 get()。"""

    def __init__(self, raw):
        self._raw = raw

    def get(self, key):
        assert key == SETTINGS_KEY_NETWORK_POLICY
        return self._raw


def test_missing_key_returns_online_default():
    policy = load_network_policy(repo=_FakeRepo(None))
    assert policy.mode is NetworkMode.ONLINE
    assert policy.allowed_hosts == ()


def test_valid_json_is_parsed():
    policy = load_network_policy(
        repo=_FakeRepo(
            '{"mode": "intranet", "allowed_hosts": ["*.example.internal"],'
            ' "insecure_tls_hosts": ["docs.example.internal"]}'
        )
    )
    assert policy.mode is NetworkMode.INTRANET
    assert policy.allowed_hosts == ("*.example.internal",)
    assert policy.insecure_tls_hosts == ("docs.example.internal",)


def test_malformed_json_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo("{not json"))
    assert policy.mode is NetworkMode.ONLINE


def test_non_object_json_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('["a", "b"]'))
    assert policy.mode is NetworkMode.ONLINE


def test_unknown_mode_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "carrier-pigeon"}'))
    assert policy.mode is NetworkMode.ONLINE


def test_wrong_field_type_falls_back_to_online():
    policy = load_network_policy(repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": 42}'))
    assert policy.mode is NetworkMode.ONLINE


def test_bare_string_host_field_falls_back_to_online():
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": "a.internal"}')
    )
    assert policy.mode is NetworkMode.ONLINE


def test_overbroad_wildcard_in_stored_config_falls_back_to_online():
    """__post_init__ 的 ValueError 也要被兜住，不能让坏配置炸掉工具注册。"""
    policy = load_network_policy(
        repo=_FakeRepo('{"mode": "intranet", "allowed_hosts": ["*.net"]}')
    )
    assert policy.mode is NetworkMode.ONLINE


def test_repo_raising_falls_back_to_online():
    class _BrokenRepo:
        def get(self, key):
            raise RuntimeError("db gone")

    policy = load_network_policy(repo=_BrokenRepo())
    assert policy.mode is NetworkMode.ONLINE


def test_network_policy_key_is_in_settings_repo_whitelist():
    from backend.data.settings_repo import SettingsRepository

    assert SETTINGS_KEY_NETWORK_POLICY in SettingsRepository.KEYS
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_network_config.py -v
```

预期：collection error，`ModuleNotFoundError: No module named 'backend.tools.network_config'`

- [ ] **Step 3: 实现加载器**

创建 `backend/tools/network_config.py`：

```python
"""从 preferences KV 加载 ``NetworkPolicy``。

存储位置是 ``preferences`` 表的 ``network_policy`` key（JSON 字符串），与
``permission_mode`` 同一套 KV 机制 —— 不走 ``app_settings`` blob，避免碰
``LEGAL_TOP_KEYS`` 白名单与前后端三处同步。

**fail-safe 方向**：任何读取/解析/校验失败都回退 ``ONLINE``（现状行为）。
配置读不出来时不应该把用户的既有能力锁死。这与
``load_tool_policy_from_config`` 的降级口径一致。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.domain.network_policy import NetworkPolicy

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_NETWORK_POLICY = "network_policy"


def load_network_policy(repo: Optional[Any] = None) -> NetworkPolicy:
    """读取网络策略；任何失败回退 ``NetworkPolicy()``（ONLINE）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    try:
        if repo is None:
            # 惰性 import 避免 tools ↔ data 循环依赖（与 permissions.py 同手法）
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_NETWORK_POLICY)
    except Exception:  # noqa: BLE001 — 配置读取失败绝不阻断工具注册
        logger.warning("网络策略读取失败，回退 online 模式", exc_info=True)
        return NetworkPolicy()

    if not raw:
        return NetworkPolicy()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("网络策略 JSON 解析失败，回退 online 模式")
        return NetworkPolicy()

    if not isinstance(parsed, dict):
        logger.warning("网络策略不是 JSON 对象，回退 online 模式")
        return NetworkPolicy()

    try:
        return NetworkPolicy.from_config(parsed)
    except (ValueError, TypeError):
        logger.warning("网络策略字段非法，回退 online 模式")
        return NetworkPolicy()
```

- [ ] **Step 4: 把 key 加进 preferences 白名单**

修改 `backend/data/settings_repo.py`，在 `KEYS` frozenset 的 `"hooks",` 之后加：

```python
            # 内网 Web 访问: 网络模式 + host 白名单 (JSON)
            # 见 backend/tools/network_config.py
            "network_policy",
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_network_config.py -v
```

预期：全部 PASS

- [ ] **Step 6: 跑 ruff**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/network_config.py data/settings_repo.py tests/unit/test_network_config.py
```

预期：无告警

- [ ] **Step 7: 提交**

```bash
git add backend/tools/network_config.py backend/data/settings_repo.py backend/tests/unit/test_network_config.py
git commit -m "feat(tools): 网络策略从 preferences KV 加载（失败 fail-safe 到 online）"
```

---

## Task 3: HTML 抽取层 + 编码嗅探

**Files:**
- Create: `backend/wiki/html_extract.py`
- Test: `backend/tests/unit/test_html_extract.py`

**Interfaces:**
- Consumes: 无（纯函数模块，只用标准库）
- Produces:
  - `ExtractedPage` dataclass：`title: str`、`text: str`、`links: List[Dict[str, str]]`、`tables: List[List[List[str]]]`
  - `extract(html: str, base_url: str) -> ExtractedPage`
  - `decode_html(body: bytes, content_type: Optional[str] = None) -> Tuple[str, str]`（返回 `(文本, 实际使用的编码名)`）
  - `charset_from_content_type(content_type: Optional[str]) -> Optional[str]`

**设计变更（原型验证结论）：** spec §2 写的是"stdlib 主路径 + lxml 可选加速，
schema 一致"。原型对比后**放弃 lxml 双实现**，只保留 stdlib：

- lxml 的 `text_content()` 在**嵌套表格**上会把内层表格的文字并进外层单元格
  （`<td>外<table><tr><td>内</td>...` → lxml 得 `["外内", "右"]`，stdlib 得
  `["外", "右"]` 加独立的内层表）。这是 DOM 语义的必然结果，不是可修的 bug ——
  要对齐就得给 lxml 路径手写等价的栈式遍历，那 lxml 就没意义了。
- lxml 在空文档上抛 `etree.ParserError: Document is empty`，需要额外分支。
- 实测收益有限：79 KB 页面（500 行表格 + 500 链接 + 500 段落）stdlib 44.8 ms、
  lxml 22.5 ms。省下的 22 ms 相对于一次网络请求可忽略。

**两条路径产出不一致的双实现，比单实现慢一点更糟** —— 用户装没装 lxml 会改变
抽取结果，而 `requirements.txt` 并不声明它，等于结果取决于环境里碰巧有什么。
故 spec §2 的"双实现"一段在实施后需回写更正。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_html_extract.py`：

```python
"""html_extract 单元测试：正文抽取 + 编码嗅探。

只有 stdlib 一条实现路径（见 Task 3 的"设计变更"说明）—— 不做 lxml 双实现，
因为两者在嵌套表格上产出不同，而 requirements.txt 并不声明 lxml，结果会取决于
环境里碰巧装了什么。
"""

import pytest

from backend.wiki.html_extract import (
    ExtractedPage,
    charset_from_content_type,
    decode_html,
    extract,
)

pytestmark = [pytest.mark.unit]

_PAGE = """<html><head><title>  知网 检索  </title>
<style>.a{color:red}</style><script>var x="不该出现";</script></head>
<body><h1>文献列表</h1><p>共 2 条结果&amp;更多</p>
<noscript>请开启 JS</noscript>
<table><tr><th>标题</th><th>作者</th></tr>
<tr><td>论文 A</td><td>张三</td></tr></table>
<a href="/detail?id=1">论文 A 详情</a>
<a href="javascript:void(0)">脚本链接</a>
<a href="#frag">锚点</a>
</body></html>"""

_BASE = "https://mirror.example.internal/search"


def test_title_is_whitespace_normalized():
    assert extract(_PAGE, _BASE).title == "知网 检索"


def test_script_style_noscript_content_is_dropped():
    text = extract(_PAGE, _BASE).text
    assert "不该出现" not in text
    assert "color:red" not in text
    assert "请开启" not in text


def test_text_keeps_visible_content_and_decodes_entities():
    text = extract(_PAGE, _BASE).text
    assert "文献列表" in text
    assert "共 2 条结果&更多" in text


def test_relative_links_are_absolutized():
    links = extract(_PAGE, _BASE).links
    assert {"text": "论文 A 详情", "url": "https://mirror.example.internal/detail?id=1"} in links


@pytest.mark.parametrize("noise", ["javascript:void(0)", "#frag"])
def test_non_navigational_links_are_skipped(noise):
    urls = [link["url"] for link in extract(_PAGE, _BASE).links]
    assert all(noise not in url for url in urls)


def test_tables_become_nested_lists():
    assert extract(_PAGE, _BASE).tables == [
        [["标题", "作者"], ["论文 A", "张三"]]
    ]


def test_empty_html_yields_empty_page():
    page = extract("", _BASE)
    assert page == ExtractedPage(title="", text="", links=[], tables=[])


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<table><tr><td>单元格<a href="/x">链</table>', [[["单元格链"]]]),
        ("<table><tr><td>孤儿", [[["孤儿"]]]),
        ("<table><td>无 tr</td></table>", []),
        ("<tr><td>无 table</td></tr>", []),
        ("<table></table>", []),
        (
            "<table><tr><td><table><tr><td>内</td></tr></table></td></tr></table>",
            [[["内"]]],
        ),
    ],
)
def test_malformed_table_markup_does_not_crash(html, expected):
    assert extract(html, _BASE).tables == expected


def test_nested_tables_are_kept_separate():
    """内层表格的文字不能并进外层单元格 —— 这是不用 lxml 的原因（见设计变更）。"""
    html = "<table><tr><td>外<table><tr><td>内</td></tr></table></td><td>右</td></tr></table>"
    assert extract(html, _BASE).tables == [[["内"]], [["外", "右"]]]


# ---------- 编码嗅探 ----------


def test_charset_from_content_type_reads_param():
    assert charset_from_content_type("text/html; charset=GBK") == "GBK"


@pytest.mark.parametrize("value", [None, "", "text/html"])
def test_charset_from_content_type_absent(value):
    assert charset_from_content_type(value) is None


@pytest.mark.parametrize(
    ("encoding", "content_type"),
    [
        ("gbk", "text/html; charset=GBK"),
        ("gb18030", "text/html"),
        ("utf-8", "text/html; charset=utf-8"),
        ("utf-8", None),
    ],
)
def test_decode_html_recovers_chinese(encoding, content_type):
    body = "知网检索结果".encode(encoding)
    text, _used = decode_html(body, content_type)
    assert "知网检索结果" in text


def test_decode_html_uses_meta_charset_when_header_silent():
    body = b'<meta charset="gbk">' + "知网".encode("gbk")
    text, used = decode_html(body, "text/html")
    assert "知网" in text
    assert used == "gbk"


def test_decode_html_uses_meta_http_equiv():
    body = (
        b'<meta http-equiv="Content-Type" content="text/html; charset=gb2312">'
        + "知网".encode("gbk")
    )
    text, used = decode_html(body, None)
    assert "知网" in text
    assert used == "gb2312"


def test_decode_html_survives_unknown_codec_in_header():
    body = "知网".encode("gb18030")
    text, used = decode_html(body, "text/html; charset=nonexistent-codec")
    assert "知网" in text
    assert used == "gb18030"


def test_decode_html_empty_body():
    text, used = decode_html(b"", "text/html")
    assert text == ""
    assert used == "utf-8"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_html_extract.py -v
```

预期：collection error，`ModuleNotFoundError: No module named 'backend.wiki.html_extract'`

- [ ] **Step 3: 实现抽取层（第一部分：数据结构 + 编码嗅探）**

创建 `backend/wiki/html_extract.py`：

```python
"""HTML 正文抽取 + 编码嗅探（纯函数，无 IO）。

``web_fetch`` 原先把整页 HTML 前 10000 字符丢给 LLM，内网知网/万方镜像的
详情页大半是 ``<script>`` 与内联样式，等于用 token 换噪音。本模块把页面拆成
title / text / links / tables 四段，调用方按需取。

**为什么不用 lxml**：``requirements.txt`` 不声明 lxml，装没装取决于环境里碰巧
有什么传递依赖。更要紧的是 lxml 的 ``text_content()`` 在嵌套表格上会把内层
文字并进外层单元格，与本模块的栈式实现产出不同 —— 两条产出不一致的路径比
单实现慢一点更糟。实测 79 KB 页面 stdlib 44.8 ms、lxml 22.5 ms，省下的时间
相对一次网络请求可忽略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.message import Message
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

#: 这些标签的**内容**整段丢弃，不只是剥标签
SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})

#: 这些标签前后插换行，避免正文粘成一坨
BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "blockquote", "pre", "td", "th",
    }
)

#: 非导航链接：点了不会跳到新文档，收进 links 只是噪音
_NON_NAVIGATIONAL_PREFIXES = ("javascript:", "#", "mailto:", "tel:", "data:")

_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I)

#: 无显式声明时的试解顺序。gb18030 是 GBK 超集，能解 GBK 也能解 GB2312
_FALLBACK_CHAIN = ("utf-8", "gb18030")

#: meta charset 只在文档头部找，避免正文里的字面量误导
_META_SNIFF_BYTES = 4096


@dataclass
class ExtractedPage:
    """抽取结果。四段独立，调用方按 ``mode`` 取用。"""

    title: str = ""
    text: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)


def charset_from_content_type(content_type: Optional[str]) -> Optional[str]:
    """从 ``Content-Type`` 头解析 charset 参数。

    用 ``email.message.Message`` 而非手写 split —— 它正确处理带引号的值与
    多参数（``text/html; charset="gbk"; boundary=x``）。
    """
    if not content_type:
        return None
    msg = Message()
    msg["content-type"] = content_type
    value = msg.get_param("charset")
    if not value:
        return None
    return str(value).strip() or None


def _charset_from_meta(head: bytes) -> Optional[str]:
    """从文档头部的 ``<meta charset>`` / ``<meta http-equiv>`` 取编码名。"""
    match = _META_CHARSET_RE.search(head)
    if not match:
        return None
    return match.group(1).decode("ascii", errors="ignore") or None


def decode_html(body: bytes, content_type: Optional[str] = None) -> Tuple[str, str]:
    """把响应字节解成文本。返回 ``(文本, 实际使用的编码名)``。

    优先级：``Content-Type`` 头 → ``<meta charset>`` → utf-8 → gb18030 →
    utf-8 且 ``errors="replace"``。绝不因编码问题抛异常。
    """
    for candidate in (
        charset_from_content_type(content_type),
        _charset_from_meta(body[:_META_SNIFF_BYTES]),
    ):
        if not candidate:
            continue
        try:
            return body.decode(candidate, errors="replace"), candidate.lower()
        except LookupError:
            # 服务器声明了 Python 不认识的编码名，继续往下试
            continue
    for candidate in _FALLBACK_CHAIN:
        try:
            return body.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace"), "utf-8"
```

- [ ] **Step 4: 实现抽取层（第二部分：stdlib 解析器）**

追加到 `backend/wiki/html_extract.py`：

```python
class _Collector(HTMLParser):
    """一趟遍历同时收 title / text / links / tables。

    表格状态用显式的 ``_flush_*`` 方法收尾而不是只在 endtag 里处理 ——
    内网镜像站的 HTML 经常不闭合 ``</table>``，只靠 endtag 会丢掉整张表。
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._skip_depth = 0
        self._in_title = False
        self.title = ""
        self._chunks: List[str] = []
        self.links: List[Dict[str, str]] = []
        self._link_href: Optional[str] = None
        self._link_text: List[str] = []
        self.tables: List[List[List[str]]] = []
        self._table_stack: List[List[List[str]]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            self._link_href = dict(attrs).get("href")
            self._link_text = []
        elif tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        if tag in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "a":
            self._flush_link()
        elif tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag == "table":
            self._flush_table()
        if tag in BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self._chunks.append(data)
        if self._link_href is not None:
            self._link_text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _flush_link(self) -> None:
        href = self._link_href
        self._link_href = None
        if not href:
            return
        href = href.strip()
        if not href or href.startswith(_NON_NAVIGATIONAL_PREFIXES):
            return
        text = " ".join("".join(self._link_text).split())
        self.links.append({"text": text, "url": urljoin(self._base_url, href)})

    def _flush_cell(self) -> None:
        if self._cell is None or self._row is None:
            return
        self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row and self._table_stack:
            self._table_stack[-1].append(self._row)
        self._row = None

    def _flush_table(self) -> None:
        self._flush_row()
        if not self._table_stack:
            return
        finished = self._table_stack.pop()
        if finished:
            self.tables.append(finished)

    def close(self) -> None:
        super().close()
        if self._link_href is not None:
            self._flush_link()
        while self._table_stack:
            self._flush_table()

    def collected_text(self) -> str:
        raw = "".join(self._chunks)
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def extract(html: str, base_url: str) -> ExtractedPage:
    """把 HTML 拆成 title / text / links / tables 四段。"""
    collector = _Collector(base_url)
    collector.feed(html)
    collector.close()
    return ExtractedPage(
        title=" ".join(collector.title.split()),
        text=collector.collected_text(),
        links=collector.links,
        tables=collector.tables,
    )
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_html_extract.py -v
```

预期：全部 PASS

- [ ] **Step 6: 跑 ruff**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check wiki/html_extract.py tests/unit/test_html_extract.py
```

预期：无告警

- [ ] **Step 7: 回写 spec §2 更正双实现描述**

spec `docs/superpowers/specs/2026-09-02-intranet-web-access-design.md` §2 的
"双实现，schema 一致"整段已被本任务的原型验证推翻。把那段替换为：

```markdown
**只用 stdlib，不做 lxml 双实现。** 原型对比发现 lxml 的 `text_content()`
在嵌套表格上会把内层表格的文字并进外层单元格（`<td>外<table>...<td>内` →
lxml 得 `["外内", "右"]`，栈式实现得 `["外", "右"]` 加独立内层表），这是 DOM
语义的必然结果而非可修的 bug。加上 `requirements.txt` 并不声明 lxml，保留双
路径等于让抽取结果取决于环境里碰巧装了什么。实测 79 KB 页面 stdlib 44.8 ms、
lxml 22.5 ms，省下的时间相对一次网络请求可忽略。
```

同时把 §2 表格上方一行的 `extract(html, base_url)` 说明保持不变（签名未变）。

- [ ] **Step 8: 提交**

```bash
git add backend/wiki/html_extract.py backend/tests/unit/test_html_extract.py \
  docs/superpowers/specs/2026-09-02-intranet-web-access-design.md
git commit -m "feat(wiki): HTML 正文抽取 + 编码嗅探（stdlib 栈式实现）

原型验证推翻 spec 的 lxml 双实现方案：lxml text_content() 在嵌套表格上
把内层文字并进外层单元格，与栈式实现产出不一致；requirements.txt 不声明
lxml，双路径会让结果取决于环境。spec §2 已同步更正。"
```

---

## Task 4: web_fetch 接抽取层 + host 门禁

**Files:**
- Modify: `backend/tools/web_tool.py:145-246`（`WebFetchTool` 整个类）
- Test: `backend/tests/unit/test_web_tool.py`（扩充，保留全部既有测试）

**Interfaces:**
- Consumes:
  - Task 1: `NetworkPolicy`、`NetworkMode`
  - Task 2: `load_network_policy(repo=None) -> NetworkPolicy`
  - Task 3: `extract(html, base_url) -> ExtractedPage`、`decode_html(body, content_type) -> Tuple[str, str]`
- Produces:
  - `WebFetchTool.__init__(policy=None, network_policy=None)` —— `network_policy` 为
    `None` 时**每次 execute 现读**（用户改白名单立即生效）；显式传入则固定（测试用）
  - `web_fetch` schema 新增 `mode` 参数：`"text"`（默认）/ `"links"` / `"tables"` / `"raw"`
  - 返回 `content` 结构：`{url, status_code, content_type, encoding, mode, title?, content, links?, tables?}`

**关键约束：** 既有 12 个测试全部保留且必须继续通过 —— `online` 模式行为不变是
spec §4 的硬要求。`_literal_ip` / `_all_public` / `_validate_subagent_url` /
`_validate_subagent_redirect` 四个方法**一个字都不要动**（`release/win7` 分支在
`_literal_ip` 有 IPv4-mapped IPv6 解包的分支专属修改，动了会 cherry-pick 冲突）。

- [ ] **Step 1: 写失败测试（追加到既有文件末尾）**

在 `backend/tests/unit/test_web_tool.py` 末尾追加：

```python
# ---------- 网络模式门禁（Task 4） ----------


def _intranet(*hosts):
    return NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=hosts)


def test_web_fetch_intranet_allows_whitelisted_host():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/p").mock(
            return_value=Response(
                200,
                text="<html><title>镜像站</title><body><p>正文内容</p></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/p")

    assert result.success is True
    assert result.content["title"] == "镜像站"
    assert "正文内容" in result.content["content"]


def test_web_fetch_intranet_rejects_non_whitelisted_host():
    tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
    result = tool.execute(url="https://evil.example.com/p")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_intranet_with_empty_whitelist_rejects_everything():
    tool = WebFetchTool(network_policy=NetworkPolicy(mode=NetworkMode.INTRANET))
    result = tool.execute(url="https://anything.internal/p")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_offline_rejects():
    tool = WebFetchTool(network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE))
    result = tool.execute(url="https://anything.internal/p")

    assert result.success is False
    assert "network_mode_offline" in result.error


def test_web_fetch_online_ignores_allowed_hosts():
    """online 模式下 allowed_hosts 不参与判定 —— 填了白名单不该收紧访问范围。"""
    policy = NetworkPolicy(mode=NetworkMode.ONLINE, allowed_hosts=("only.internal",))
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/p").mock(return_value=Response(200, text="<html><body>ok</body></html>"))
        tool = WebFetchTool(network_policy=policy)
        result = tool.execute(url="https://example.com/p")

    assert result.success is True


def test_web_fetch_intranet_whitelisted_private_ip_bypasses_public_ip_check():
    """内网 host 解析出私有 IP 是预期的，白名单命中就不该被公网规则拦。"""
    with respx.mock(base_url="http://10.10.0.5", assert_all_called=False) as mock:
        mock.get("/p").mock(return_value=Response(200, text="<html><body>内网页</body></html>"))
        tool = WebFetchTool(
            policy=ToolPolicy(subagent_only=True),
            network_policy=_intranet("10.10.0.5"),
        )
        result = tool.execute(url="http://10.10.0.5/p")

    assert result.success is True
    assert "内网页" in result.content["content"]


def test_web_fetch_intranet_redirect_target_must_also_pass_whitelist():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://mirror.example.internal/r").mock(
            return_value=Response(302, headers={"location": "https://evil.example.com/x"})
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/r")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_loads_policy_from_settings_when_not_injected(monkeypatch):
    """未注入 network_policy 时每次 execute 现读 —— 改白名单立即生效。"""
    calls = []

    def _fake_load():
        calls.append(1)
        return NetworkPolicy(mode=NetworkMode.OFFLINE)

    monkeypatch.setattr("backend.tools.web_tool.load_network_policy", _fake_load)
    tool = WebFetchTool()

    first = tool.execute(url="https://a.internal/p")
    second = tool.execute(url="https://b.internal/p")

    assert first.success is False
    assert second.success is False
    assert len(calls) == 2
```

- [ ] **Step 2: 写抽取模式与编码测试（继续追加）**

继续在 `backend/tests/unit/test_web_tool.py` 末尾追加：

```python
# ---------- 抽取模式与编码（Task 4） ----------

_MIRROR_PAGE = (
    "<html><head><title>知网检索</title></head><body>"
    "<table><tr><th>标题</th></tr><tr><td>论文甲</td></tr></table>"
    '<a href="/detail?id=9">详情</a>'
    "<p>摘要正文</p></body></html>"
)


def test_web_fetch_decodes_gbk_page():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/gbk").mock(
            return_value=Response(
                200,
                content=_MIRROR_PAGE.encode("gbk"),
                headers={"content-type": "text/html; charset=GBK"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/gbk")

    assert result.success is True
    assert result.content["encoding"] == "gbk"
    assert "摘要正文" in result.content["content"]


@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        ("text", (), ("links", "tables")),
        ("links", ("links",), ("tables",)),
        ("tables", ("tables",), ("links",)),
    ],
)
def test_web_fetch_mode_controls_returned_sections(mode, present, absent):
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/p").mock(
            return_value=Response(
                200,
                text=_MIRROR_PAGE,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/p", mode=mode)

    assert result.success is True
    for key in present:
        assert key in result.content
    for key in absent:
        assert key not in result.content


def test_web_fetch_links_are_absolutized():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/list").mock(
            return_value=Response(
                200, text=_MIRROR_PAGE, headers={"content-type": "text/html"}
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/list", mode="links")

    urls = [link["url"] for link in result.content["links"]]
    assert "https://mirror.example.internal/detail?id=9" in urls


def test_web_fetch_tables_become_nested_lists():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/t").mock(
            return_value=Response(
                200, text=_MIRROR_PAGE, headers={"content-type": "text/html"}
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/t", mode="tables")

    assert result.content["tables"] == [[["标题"], ["论文甲"]]]


def test_web_fetch_raw_mode_returns_unextracted_html():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/raw").mock(
            return_value=Response(
                200,
                text="<html><script>x=1</script>H</html>",
                headers={"content-type": "text/html"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/raw", mode="raw")

    assert result.success is True
    assert "<script>" in result.content["content"]


def test_web_fetch_rejects_unknown_mode():
    tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
    result = tool.execute(url="https://mirror.example.internal/p", mode="telepathy")

    assert result.success is False
    assert "mode" in result.error


def test_web_fetch_non_html_content_type_skips_extraction():
    """JSON / 纯文本响应不该被当 HTML 抽取 —— 直接给原文。"""
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/api").mock(
            return_value=Response(
                200,
                content=b'{"total": 2}',
                headers={"content-type": "application/json"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/api")

    assert result.success is True
    assert result.content["content"] == '{"total": 2}'
    assert "title" not in result.content


def test_web_fetch_max_length_truncates_extracted_text():
    long_body = (
        '<html><head><meta charset="utf-8"></head><body><p>'
        + ("甲" * 5000)
        + "</p></body></html>"
    )
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/long").mock(
            return_value=Response(200, text=long_body, headers={"content-type": "text/html"})
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/long", max_length=100)

    assert len(result.content["content"]) == 100
```

同时把该测试文件顶部的 import 区（`backend.domain.tool_policy` 那一行之后）补上：

```python
from backend.domain.network_policy import NetworkMode, NetworkPolicy
```

- [ ] **Step 3: 运行新测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_web_tool.py -v -k "intranet or offline or online_ignores or gbk or mode_controls or absolutized or nested_lists or raw_mode or unknown_mode or non_html or truncates_extracted or loads_policy"
```

预期：`TypeError: WebFetchTool.__init__() got an unexpected keyword argument 'network_policy'`

- [ ] **Step 4: 改 web_tool.py 的 import 与构造器**

在 `backend/tools/web_tool.py` 顶部，把 `from typing import Optional, Set, Union` 改为：

```python
from typing import Any, Dict, Optional, Set, Union
```

在 `from backend.domain.risk import RiskClass` 之后插入：

```python
from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools.network_config import load_network_policy
from backend.wiki.html_extract import decode_html, extract
```

把 `WebFetchTool.__init__`（`web_tool.py:151-157`）替换为：

```python
    #: mode 合法取值。text 只给正文，links/tables 额外带对应段，raw 给原始 HTML
    VALID_MODES = ("text", "links", "tables", "raw")

    #: 只对这些 content-type 做 HTML 抽取；JSON / 纯文本直接给原文
    _HTML_CONTENT_TYPES = ("text/html", "application/xhtml")

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        # None 表示"每次 execute 现读 settings"——用户改白名单立即生效，不必
        # 重开会话。显式传入则固定（测试注入用）。
        self._network_policy = network_policy
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            trust_env=not self._policy.subagent_only,
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()
```

- [ ] **Step 5: 改 schema 加 mode 参数**

把 `WebFetchTool._build_schema`（`web_tool.py:189-201`）替换为：

```python
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description=(
                "获取网页内容并抽取正文。mode=text 返回正文（默认），"
                "links 额外返回页面链接列表，tables 额外返回表格（文献列表页用），"
                "raw 返回未处理的原始 HTML。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"},
                    "mode": {
                        "type": "string",
                        "enum": list(self.VALID_MODES),
                        "description": "抽取模式 (默认 text)",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "正文最大长度 (默认 10000)",
                    },
                },
                "required": ["url"],
            },
        )
```

- [ ] **Step 6: 重写 execute + 两个辅助方法**

把 `WebFetchTool.execute`（`web_tool.py:203-246`）整体替换为：

```python
    def execute(
        self, url: str, mode: str = "text", max_length: int = 10000, **kwargs
    ) -> ToolResult:
        """获取网页并按 ``mode`` 抽取。

        Args:
            url:        网页 URL
            mode:       ``text`` / ``links`` / ``tables`` / ``raw``
            max_length: 正文最大长度
        """
        if mode not in self.VALID_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 mode {mode!r}，可选：{', '.join(self.VALID_MODES)}",
            )
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        network_policy = self._effective_network_policy()
        host_rejection = network_policy.check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        # 非 online 模式下 host 已过白名单，跳过公网 IP 校验：内网地址解析出
        # 私有 IP 是预期的。online 模式 check_host 恒放行，走原有校验不变。
        gated_by_whitelist = network_policy.mode is not NetworkMode.ONLINE
        if self._policy.subagent_only and not gated_by_whitelist:
            validation_error = self._validate_subagent_url(url)
            if validation_error:
                return ToolResult(success=False, error=validation_error)

        try:
            response = self.client.get(url)
            redirect_error = self._check_redirect(response, network_policy, gated_by_whitelist)
            if redirect_error:
                return ToolResult(success=False, error=redirect_error)
            response.raise_for_status()
            return ToolResult(success=True, content=self._render(url, response, mode, max_length))
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"获取网页失败: {str(e)}")

    def _check_redirect(
        self,
        response: httpx.Response,
        network_policy: NetworkPolicy,
        gated_by_whitelist: bool,
    ) -> Optional[str]:
        """重定向目标校验。返回拒绝原因；``None`` 表示放行。"""
        if not response.is_redirect:
            return None
        location = response.headers.get("location", "")
        if gated_by_whitelist:
            return network_policy.check_host(location)
        if self._policy.subagent_only:
            return self._validate_subagent_redirect(location)
        return None

    def _render(
        self, url: str, response: httpx.Response, mode: str, max_length: int
    ) -> Dict[str, Any]:
        """把响应渲染成工具结果的 ``content`` dict。"""
        content_type = response.headers.get("content-type", "")
        text, encoding = decode_html(response.content, content_type)
        result: Dict[str, Any] = {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "encoding": encoding,
            "mode": mode,
        }

        is_html = any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES)
        if mode == "raw" or not is_html:
            result["content"] = text[:max_length]
            return result

        page = extract(text, url)
        result["title"] = page.title
        result["content"] = page.text[:max_length]
        if mode == "links":
            result["links"] = page.links[: self._policy.max_result_items]
        elif mode == "tables":
            result["tables"] = page.tables[: self._policy.max_result_items]
        return result
```

- [ ] **Step 7: 运行全部 web_tool 测试**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_web_tool.py -v
```

预期：全部 PASS，**包含**原有 12 个测试（`online` 无回归是硬要求）。

注意两个原有测试的行为边界：`test_web_fetch_success` 的 mock 带
`content-type: text/html; charset=utf-8`，会走抽取分支 —— 它断言
`"hello" in result.content["content"]`，抽取后正文仍是 `hello`，通过。
`test_web_fetch_truncates_by_max_length` 的 mock **不带** content-type，走
"非 HTML → 给原文"分支，`len(...) == 100` 成立。

- [ ] **Step 8: 跑 ruff**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/web_tool.py tests/unit/test_web_tool.py
```

预期：无告警

- [ ] **Step 9: 提交**

```bash
git add backend/tools/web_tool.py backend/tests/unit/test_web_tool.py
git commit -m "feat(tools): web_fetch 接正文抽取 + 编码嗅探 + 内网 host 门禁"
```

---

## Task 5: http_download 流式下载工具

**Files:**
- Create: `backend/tools/download_tool.py`
- Test: `backend/tests/unit/test_download_tool.py`

**Interfaces:**
- Consumes:
  - Task 1: `NetworkPolicy`、`NetworkMode`
  - Task 2: `load_network_policy(repo=None) -> NetworkPolicy`
- Produces:
  - `HttpDownloadTool(BaseTool)`，工具名 `http_download`，`risk = RiskClass.EXTERNAL`
  - `HttpDownloadTool.__init__(policy=None, network_policy=None)`
  - `HttpDownloadTool.execute(url, filename=None, max_bytes=MAX_DOWNLOAD_BYTES, **kwargs)`
  - 模块级 `MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024`
  - 模块级 `derive_filename(url: str, disposition: Optional[str] = None) -> str`
  - 模块级 `sanitize_filename(name: Optional[str]) -> str`

**设计要点（均已原型验证）：**

1. **`workspace_root` 为 `None` 时直接拒绝**。`BaseTool._enforce_workspace` 在
   未绑定时返回 `None`（放行，见 `backend/tools/base.py:125-127`），legacy 聊天
   链路无 workspace 绑定时确实是 `None`。下载的字节来自网络，写入位置不确定的
   风险比 `office_create_tool` 的"未绑定零行为变化"取向更高，故这里 fail-closed。
2. **双重大小上限**。先看 `Content-Length`，超限立即拒；再在流式写入时累计实际
   字节，超限中断并删半成品 —— `Content-Length` 是服务器说的，不可信。原型验证：
   声明 10 字节实发 5000 字节的响应会在写入阶段中断且不留文件。
3. **文件名净化用 `email.message.Message.get_filename()`**，它同时处理
   `filename="x"` 与 RFC 5987 的 `filename*=UTF-8''%E8%AE%BA%E6%96%87.pdf`。
   注意 `get_param("filename*")` 恒返回 `None`，必须用 `get_filename()`。
4. 落盘后调 `_record_artifact_safely`（复用 `backend/tools/file_tool.py:107`）挂进
   Artifacts 面板。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_download_tool.py`：

```python
"""http_download 单元测试：流式落盘 + 大小上限 + 路径边界 + 文件名净化。"""

from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools.download_tool import (
    HttpDownloadTool,
    derive_filename,
    sanitize_filename,
)

pytestmark = [pytest.mark.unit]

_BASE = "https://mirror.example.internal"


def _tool(tmp_path, **kw):
    return HttpDownloadTool(
        policy=ToolPolicy(workspace_root=str(tmp_path)),
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        ),
        **kw,
    )


def test_schema_declares_url_required():
    tool = HttpDownloadTool()
    assert tool.schema.name == "http_download"
    assert tool.schema.parameters["required"] == ["url"]


def test_download_streams_to_workspace(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(
            return_value=Response(200, content=b"%PDF-1.4 body", headers={"content-length": "13"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    written = tmp_path / "paper.pdf"
    assert written.read_bytes() == b"%PDF-1.4 body"
    assert result.content["bytes_written"] == 13
    assert result.content["filename"] == "paper.pdf"


def test_download_rejects_when_declared_length_exceeds_cap(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/big.pdf").mock(
            return_value=Response(200, content=b"X" * 10, headers={"content-length": "999999"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/big.pdf", max_bytes=1000)

    assert result.success is False
    assert "content_length_exceeds_limit" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_aborts_and_cleans_when_server_lies_about_length(tmp_path):
    """Content-Length 是服务器说的，不可信 —— 按实际字节数中断并删半成品。"""
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/liar.pdf").mock(
            return_value=Response(200, content=b"X" * 5000, headers={"content-length": "10"})
        )
        result = _tool(tmp_path).execute(url=f"{_BASE}/liar.pdf", max_bytes=1000)

    assert result.success is False
    assert "download_exceeds_limit" in result.error
    assert list(tmp_path.iterdir()) == []


def test_download_without_content_length_still_works(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/nolen.bin").mock(return_value=Response(200, content=b"Y" * 50))
        result = _tool(tmp_path).execute(url=f"{_BASE}/nolen.bin")

    assert result.success is True
    assert (tmp_path / "nolen.bin").stat().st_size == 50


def test_download_requires_bound_workspace():
    """workspace_root 未绑定 → 拒绝。_enforce_workspace 此时会放行，不能只靠它。"""
    tool = HttpDownloadTool(
        policy=ToolPolicy(),
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        ),
    )
    result = tool.execute(url=f"{_BASE}/x.pdf")

    assert result.success is False
    assert "workspace_not_bound" in result.error


def test_download_rejects_absolute_filename(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="/etc/passwd")

    assert result.success is False
    assert "filename_must_be_relative" in result.error


def test_download_rejects_filename_escaping_workspace(tmp_path):
    result = _tool(tmp_path).execute(url=f"{_BASE}/x.pdf", filename="../../escape.bin")

    assert result.success is False
    assert "path_outside_workspace" in result.error or "filename" in result.error


def test_download_honors_network_policy(tmp_path):
    result = _tool(tmp_path).execute(url="https://evil.example.com/x.pdf")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_download_offline_mode_rejects(tmp_path):
    tool = HttpDownloadTool(
        policy=ToolPolicy(workspace_root=str(tmp_path)),
        network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE),
    )
    result = tool.execute(url=f"{_BASE}/x.pdf")

    assert result.success is False
    assert "network_mode_offline" in result.error


def test_download_http_error_leaves_no_file(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/missing.pdf").mock(return_value=Response(404, content=b"nope"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/missing.pdf")

    assert result.success is False
    assert list(tmp_path.iterdir()) == []


def test_download_network_exception_is_wrapped(tmp_path):
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/oops.pdf").mock(side_effect=httpx.ConnectError("conn refused"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/oops.pdf")

    assert result.success is False
    assert "失败" in result.error


def test_download_does_not_overwrite_existing_file(tmp_path):
    (tmp_path / "paper.pdf").write_bytes(b"original")
    with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
        mock.get("/paper.pdf").mock(return_value=Response(200, content=b"new"))
        result = _tool(tmp_path).execute(url=f"{_BASE}/paper.pdf")

    assert result.success is True
    assert (tmp_path / "paper.pdf").read_bytes() == b"original"
    # 冲突时落到带后缀的新名字，不覆盖原文件
    assert result.content["filename"] != "paper.pdf"
    assert Path(result.content["path"]).read_bytes() == b"new"


# ---------- 文件名净化 ----------


@pytest.mark.parametrize(
    ("url", "disposition", "expected"),
    [
        (f"{_BASE}/files/论文A.pdf", None, "论文A.pdf"),
        (f"{_BASE}/d?id=1", None, "d"),
        (f"{_BASE}/a/../../etc/passwd", None, "passwd"),
        (f"{_BASE}/x.pdf", 'attachment; filename="../../etc/passwd"', "passwd"),
        (f"{_BASE}/x.pdf", 'attachment; filename="报告 2026.docx"', "报告 2026.docx"),
        (f"{_BASE}/x.pdf", "attachment; filename*=UTF-8''%E8%AE%BA%E6%96%87.pdf", "论文.pdf"),
        (f"{_BASE}/x.pdf", 'attachment; filename="C:\\Windows\\evil.exe"', "evil.exe"),
        (f"{_BASE}/x.pdf", 'attachment; filename="..."', "download.bin"),
        (f"{_BASE}/", None, "download.bin"),
        (f"{_BASE}/%2e%2e%2f%2e%2e%2fpasswd", None, "passwd"),
    ],
)
def test_derive_filename(url, disposition, expected):
    assert derive_filename(url, disposition) == expected


@pytest.mark.parametrize("name", ["/etc/passwd", "..\\..\\evil", "a/b/c.txt"])
def test_sanitize_filename_strips_path_separators(name):
    out = sanitize_filename(name)
    assert "/" not in out
    assert "\\" not in out
    assert ".." not in out


def test_sanitize_filename_removes_nul_byte():
    assert sanitize_filename("a\x00b.pdf") == "ab.pdf"


def test_sanitize_filename_caps_length():
    assert len(sanitize_filename("L" * 300 + ".pdf")) == 120
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_download_tool.py -v
```

预期：collection error，`ModuleNotFoundError: No module named 'backend.tools.download_tool'`

- [ ] **Step 3: 实现文件名净化（第一部分）**

创建 `backend/tools/download_tool.py`：

```python
"""http_download —— 流式下载文件到工作区。

与 ``bash`` + ``curl`` 的区别：走 EXTERNAL 风险类而非 EXEC，落盘路径受工作区
边界约束，且有双重大小上限。

**为什么不只依赖 ``_enforce_workspace``**：它在 ``policy.workspace_root`` 为
``None`` 时返回 ``None``（放行），而 legacy 聊天链路在会话无 workspace 绑定时
确实是 ``None``。下载的字节来自网络，写入位置不确定的风险高于本地文件操作，
所以这里未绑定就直接拒。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from email.message import Message
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import httpx

from backend.domain.network_policy import NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.network_config import load_network_policy

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 单文件默认上限 100 MiB。文献 PDF 通常几 MB，留足余量
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

#: 流式写入的块大小
_CHUNK_BYTES = 64 * 1024

#: 文件名保留：ASCII 字母数字 + 点 + 下划线 + 连字符 + 空格 + CJK
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\u4e00-\u9fff\- ]")

_FALLBACK_NAME = "download.bin"

#: 文件名长度上限，给冲突后缀留余量（Windows MAX_PATH 与 ext4 255 字节都够）
_MAX_NAME_CHARS = 120


def sanitize_filename(name: Optional[str]) -> str:
    """把任意来源的文件名净化成安全的 basename。

    剥路径分隔符（正反斜杠都算）、NUL 字节、首尾点与空格；不安全字符换下划线。
    净化后为空或全是下划线则回退 ``download.bin``。
    """
    if not name:
        return _FALLBACK_NAME
    cleaned = unicodedata.normalize("NFC", name).replace("\x00", "")
    # 反斜杠先转正斜杠，让 PurePosixPath 能剥掉 Windows 风格路径
    cleaned = PurePosixPath(cleaned.replace("\\", "/")).name
    cleaned = _UNSAFE_NAME_RE.sub("_", cleaned).strip(" .")
    if not cleaned or set(cleaned) <= {"_"}:
        return _FALLBACK_NAME
    return cleaned[:_MAX_NAME_CHARS]


def _filename_from_disposition(value: Optional[str]) -> Optional[str]:
    """从 ``Content-Disposition`` 取文件名。

    用 ``Message.get_filename()`` 而非 ``get_param("filename")``：前者同时处理
    ``filename="x"`` 与 RFC 5987 的 ``filename*=UTF-8''%XX``（后者对 ``filename*``
    恒返回 ``None``，会漏掉所有中文附件名）。
    """
    if not value:
        return None
    msg = Message()
    msg["content-disposition"] = value
    name = msg.get_filename()
    return str(name) if name else None


def derive_filename(url: str, disposition: Optional[str] = None) -> str:
    """决定落盘文件名：``Content-Disposition`` 优先，否则取 URL path 末段。"""
    from_header = _filename_from_disposition(disposition)
    if from_header:
        return sanitize_filename(from_header)
    from_url = PurePosixPath(unquote(urlparse(url).path)).name
    return sanitize_filename(from_url)


def _unique_path(directory: Path, filename: str) -> Path:
    """避开同名文件。``a.pdf`` 冲突则依次试 ``a-1.pdf`` / ``a-2.pdf``。"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        alternative = directory / f"{stem}-{index}{suffix}"
        if not alternative.exists():
            return alternative
    raise OSError(f"无法为 {filename!r} 找到可用文件名（同名文件过多）")
```

- [ ] **Step 4: 实现工具类（第二部分）**

追加到 `backend/tools/download_tool.py`：

```python
class HttpDownloadTool(BaseTool):
    """http_download —— 流式下载到工作区。"""

    # 出网 + 写盘，取更严的语义：只读模式禁止，交互模式询问
    risk = RiskClass.EXTERNAL

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._network_policy = network_policy
        self.client = httpx.Client(
            timeout=self._policy.timeout_seconds,
            follow_redirects=True,
            trust_env=not self._policy.subagent_only,
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="http_download",
            description=(
                "下载文件到工作区。适用于文献 PDF、资源站附件等。"
                "filename 省略时从 URL 或 Content-Disposition 推断；"
                "只接受工作区内的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "文件 URL"},
                    "filename": {
                        "type": "string",
                        "description": "工作区内的相对文件名 (省略则自动推断)",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": f"大小上限 (默认 {MAX_DOWNLOAD_BYTES})",
                    },
                },
                "required": ["url"],
            },
        )

    def execute(
        self,
        url: str,
        filename: Optional[str] = None,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
        **kwargs,
    ) -> ToolResult:
        """下载 ``url`` 到工作区。

        Args:
            url:       文件 URL
            filename:  工作区内相对文件名；``None`` 则自动推断
            max_bytes: 大小上限（声明值与实际字节双重校验）
        """
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False,
                error="workspace_not_bound: 下载需要先绑定工作区（会话未绑定时不允许写盘）",
            )

        if filename is not None:
            if Path(filename).is_absolute():
                return ToolResult(
                    success=False,
                    error="filename_must_be_relative: 只接受工作区内的相对文件名",
                )
            blocked = self._enforce_workspace(str(Path(root) / filename))
            if blocked is not None:
                return blocked

        host_rejection = self._effective_network_policy().check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        try:
            return self._stream_to_disk(url, filename, max_bytes, Path(root))
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"下载失败: {str(e)}")

    def _stream_to_disk(
        self, url: str, filename: Optional[str], max_bytes: int, root: Path
    ) -> ToolResult:
        """边下边写。返回成功或失败的 ``ToolResult``。"""
        with self.client.stream("GET", url) as response:
            response.raise_for_status()

            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                return ToolResult(
                    success=False,
                    error=(
                        f"content_length_exceeds_limit: 服务器声明 {declared} 字节，"
                        f"超过上限 {max_bytes}"
                    ),
                )

            name = sanitize_filename(filename) if filename else derive_filename(
                url, response.headers.get("content-disposition")
            )
            root.mkdir(parents=True, exist_ok=True)
            target = _unique_path(root, name)

            written = 0
            try:
                with open(target, "wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK_BYTES):
                        written += len(chunk)
                        # Content-Length 是服务器说的，不可信；按实际字节兜底
                        if written > max_bytes:
                            raise _DownloadTooLarge(written)
                        handle.write(chunk)
            except _DownloadTooLarge as exc:
                target.unlink(missing_ok=True)
                return ToolResult(
                    success=False,
                    error=f"download_exceeds_limit: 实际接收 {exc.written} 字节，超过上限 {max_bytes}",
                )
            except Exception:
                target.unlink(missing_ok=True)
                raise

        self._record_artifact(str(target), written)
        return ToolResult(
            success=True,
            content={
                "url": url,
                "path": str(target),
                "filename": target.name,
                "bytes_written": written,
                "content_type": response.headers.get("content-type", ""),
            },
            output=str(target),
        )

    @staticmethod
    def _record_artifact(path: str, size: int) -> None:
        """挂进 Artifacts 面板；失败静默（不影响下载结果）。"""
        try:
            from backend.tools.file_tool import _record_artifact_safely

            _record_artifact_safely(path, size)
        except Exception:  # noqa: BLE001 — 记录产物失败绝不阻断下载
            logger.debug("http_download: 记录产物失败", exc_info=True)


class _DownloadTooLarge(Exception):
    """内部信号：实际字节数超过上限。不外泄给调用方。"""

    def __init__(self, written: int) -> None:
        super().__init__(f"download exceeded limit at {written} bytes")
        self.written = written
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_download_tool.py -v
```

预期：全部 PASS

- [ ] **Step 6: 跑 ruff**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/download_tool.py tests/unit/test_download_tool.py
```

预期：无告警。若报 `PTH123`（`open()` → `Path.open()`）—— 该规则已在
`backend/ruff.toml` 的 ignore 列表里，不会触发。

- [ ] **Step 7: 提交**

```bash
git add backend/tools/download_tool.py backend/tests/unit/test_download_tool.py
git commit -m "feat(tools): http_download 流式下载（双重大小上限 + 工作区边界 + 文件名净化）"
```

---

## Task 6: 条件注册收口

**Files:**
- Modify: `backend/tools/__init__.py:29-50, 88-119`
- Modify: `backend/tools/agent_tool.py:80-87, 183-194`
- Modify: `backend/domain/risk.py:52`（`EXTERNAL_TOOLS`）
- Modify: `backend/agents/profiles.py:98`（researcher 的 `tools`）
- Modify: `backend/tests/unit/test_tools_registry.py:175-195`
- Modify: `backend/tests/unit/test_risk.py:238-245`
- Test: `backend/tests/unit/test_tool_registration_gating.py`（新）

**Interfaces:**
- Consumes:
  - Task 1: `NetworkPolicy`、`NetworkMode`
  - Task 2: `load_network_policy`
  - Task 4: `WebFetchTool(policy=..., network_policy=...)`
  - Task 5: `HttpDownloadTool(policy=..., network_policy=...)`
- Produces:
  - `register_all_tools(registry, policy=None, network_policy=None)` —— 新增第三参数
  - `build_readonly_tool_registry(policy=None, network_policy=None)` —— 新增第二参数
  - `SUBAGENT_TOOL_WHITELIST` 加 `"http_download"`

**为什么这是收口任务：** 只有它同时需要 `web_fetch` 与 `http_download` 都已就位。
注册决策必须在注册时读策略 —— 这是"LLM 根本看不见"的唯一实现方式（返回"该模式
不可用"只会让模型多烧一轮迭代并可能重试）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_tool_registration_gating.py`：

```python
"""网络模式对工具注册的门禁（Task 6）。

注册期决策而非执行期报错：LLM 看到工具就会试，返回"该模式不可用"只是多烧一轮
迭代。参照 registry.get_schemas_for_llm 对 requires_tool_context 的处理方式。
"""

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.agent_tool import SUBAGENT_TOOL_WHITELIST, build_readonly_tool_registry

pytestmark = [pytest.mark.unit]

_OUTBOUND = ("web_search", "web_fetch", "http_download")


def _names(policy):
    registry = ToolRegistry()
    register_all_tools(registry, network_policy=policy)
    return set(registry.list_names())


def test_online_registers_all_outbound_tools():
    names = _names(NetworkPolicy(mode=NetworkMode.ONLINE))
    for tool in _OUTBOUND:
        assert tool in names


def test_intranet_hides_web_search_but_keeps_fetch_and_download():
    names = _names(
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",))
    )
    assert "web_search" not in names
    assert "web_fetch" in names
    assert "http_download" in names


def test_offline_hides_all_outbound_tools():
    names = _names(NetworkPolicy(mode=NetworkMode.OFFLINE))
    for tool in _OUTBOUND:
        assert tool not in names


def test_non_outbound_tools_survive_every_mode():
    """门禁只影响出网工具，本地工具在任何模式下都在。"""
    for mode in (NetworkMode.ONLINE, NetworkMode.INTRANET, NetworkMode.OFFLINE):
        names = _names(NetworkPolicy(mode=mode))
        for tool in ("read_file", "write_file", "bash", "calculator", "memory_search"):
            assert tool in names, f"{tool} 在 {mode.value} 模式下消失了"


def test_gating_applies_to_subagent_registry():
    """子代理路径同样过门禁 —— 否则 agent 工具能绕过网络模式。"""
    registry = build_readonly_tool_registry(
        network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE)
    )
    names = set(registry.list_names())
    assert "web_search" not in names
    assert "web_fetch" not in names
    assert "read_file" in names


def test_subagent_intranet_keeps_fetch():
    registry = build_readonly_tool_registry(
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        )
    )
    names = set(registry.list_names())
    assert "web_search" not in names
    assert "web_fetch" in names


def test_http_download_is_in_subagent_whitelist():
    assert "http_download" in SUBAGENT_TOOL_WHITELIST


def test_default_none_policy_reads_settings(monkeypatch):
    """network_policy=None 时从 settings 读 —— 生产路径不显式传参。"""
    calls = []

    def _fake_load():
        calls.append(1)
        return NetworkPolicy(mode=NetworkMode.OFFLINE)

    monkeypatch.setattr("backend.tools.load_network_policy", _fake_load)
    registry = ToolRegistry()
    register_all_tools(registry)

    assert calls, "register_all_tools 未读取网络策略"
    assert "web_search" not in registry.list_names()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_tool_registration_gating.py -v
```

预期：`TypeError: register_all_tools() got an unexpected keyword argument 'network_policy'`

- [ ] **Step 3: 改 register_all_tools**

在 `backend/tools/__init__.py` 顶部 import 区，把
`from .web_tool import WebFetchTool, WebSearchTool` 改为：

```python
from backend.domain.network_policy import NetworkPolicy

from .download_tool import HttpDownloadTool
from .network_config import load_network_policy
from .web_tool import WebFetchTool, WebSearchTool
```

把 `register_all_tools` 的签名与出网工具注册段（`backend/tools/__init__.py:32-50`）
替换为：

```python
def register_all_tools(
    registry: ToolRegistry,
    policy: Optional[ToolPolicy] = None,
    network_policy: Optional[NetworkPolicy] = None,
) -> None:
    """
    注册所有内置工具到注册表

    Args:
        registry: 工具注册表
        policy:   M2 工具策略（缺省 ``ToolPolicy()``）；透传给每个内置工具。
        network_policy: 网络策略；``None`` 时从 settings 读。决定三个出网工具
            是否注册 —— 内网/气隙模式下不注册比返回错误更省 token，因为 LLM
            看到工具就会试（与 ``get_schemas_for_llm`` 隐藏 office 工具同理）。
    """
    policy = policy or ToolPolicy()
    network_policy = network_policy if network_policy is not None else load_network_policy()
    registry.register(BashTool(policy=policy))
    # 后台 shell 生命周期：bash(run_in_background=true) 起的进程由这两个工具
    # 轮询与终止。bash_output 归 READ（只读已捕获输出），kill_shell 归 WRITE。
    registry.register(BashOutputTool(policy=policy))
    registry.register(KillShellTool(policy=policy))
    registry.register(ReadFileTool(policy=policy))
    registry.register(WriteFileTool(policy=policy))
    registry.register(ListDirTool(policy=policy))
    if network_policy.search_enabled():
        registry.register(WebSearchTool(policy=policy))
    if network_policy.fetch_enabled():
        registry.register(WebFetchTool(policy=policy, network_policy=network_policy))
        registry.register(HttpDownloadTool(policy=policy, network_policy=network_policy))
    registry.register(CalculatorTool(policy=policy))
```

`__all__` 列表（`backend/tools/__init__.py:88-119`）里在 `"WebFetchTool",` 之后加：

```python
    "HttpDownloadTool",
```

- [ ] **Step 4: 改子代理注册路径**

在 `backend/tools/agent_tool.py`，把 `SUBAGENT_TOOL_WHITELIST`（`agent_tool.py:80-87`）
替换为：

```python
SUBAGENT_TOOL_WHITELIST: Tuple[str, ...] = (
    "read_file",
    "list_dir",
    "web_search",
    "web_fetch",
    "http_download",
    "memory_search",
    "calculator",
)
```

顶部 import 区，把 `from backend.tools.web_tool import WebFetchTool, WebSearchTool` 改为：

```python
from backend.domain.network_policy import NetworkPolicy
from backend.tools.download_tool import HttpDownloadTool
from backend.tools.network_config import load_network_policy
from backend.tools.web_tool import WebFetchTool, WebSearchTool
```

把 `build_readonly_tool_registry`（`agent_tool.py:183-194`）替换为：

```python
def build_readonly_tool_registry(
    policy: Optional[ToolPolicy] = None,
    network_policy: Optional[NetworkPolicy] = None,
) -> ToolRegistry:
    """Build the restricted read-only registry given to sub-agents.

    ``network_policy`` 缺省从 settings 读；出网工具按模式门禁 —— 子代理路径
    不过门禁的话，agent 工具就成了绕过网络模式的后门。
    """
    policy, owned_root = _subagent_policy(policy)
    network_policy = network_policy if network_policy is not None else load_network_policy()
    registry = ToolRegistry()
    registry.register(ReadFileTool(policy=policy, enforce_workspace=True))
    registry.register(ListDirTool(policy=policy, enforce_workspace=True))
    if network_policy.search_enabled():
        registry.register(WebSearchTool(policy=policy))
    if network_policy.fetch_enabled():
        registry.register(WebFetchTool(policy=policy, network_policy=network_policy))
        registry.register(HttpDownloadTool(policy=policy, network_policy=network_policy))
    registry.register(MemorySearchTool(policy=policy))
    registry.register(CalculatorTool(policy=policy))
    registry._owned_workspace_root = owned_root  # noqa: SLF001 — lifecycle metadata
    return registry
```

- [ ] **Step 5: 加 risk 兜底表条目**

在 `backend/domain/risk.py`，把 `EXTERNAL_TOOLS`（`risk.py:52`）改为：

```python
EXTERNAL_TOOLS = frozenset({"web_search", "web_fetch", "http_download"})
```

- [ ] **Step 6: 加 researcher profile 白名单**

在 `backend/agents/profiles.py:98`，把 researcher 的 `tools` 改为：

```python
            tools=["web_search", "web_fetch", "http_download", "memory_search"],
```

- [ ] **Step 7: 适配两处既有测试**

`backend/tests/unit/test_risk.py:238-245` 的验收表里，在 `"web_fetch": RiskClass.EXTERNAL,`
之后加一行：

```python
            "http_download": RiskClass.EXTERNAL,
```

`backend/tests/unit/test_tools_registry.py:175-195` 的
`test_register_all_tools_registers_builtin_set` 整个替换为：

```python
def test_register_all_tools_registers_builtin_set():
    """register_all_tools 注册所有内置工具（online 模式，出网工具齐全）"""
    from backend.domain.network_policy import NetworkMode, NetworkPolicy
    from backend.tools import register_all_tools

    reg = ToolRegistry()
    register_all_tools(reg, network_policy=NetworkPolicy(mode=NetworkMode.ONLINE))

    expected = {
        "bash",
        "bash_output",
        "kill_shell",
        "read_file",
        "write_file",
        "list_dir",
        "web_search",
        "web_fetch",
        "http_download",
        "calculator",
        "memory_search",
        "memory_save",
    }
    assert expected.issubset(set(reg.list_names()))
```

显式传 `network_policy` 而不依赖 settings：这个测试断言的是"内置工具集合完整"，
不该受运行环境里 KV 表内容影响。

- [ ] **Step 8: 运行受影响的全部测试**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  tests/unit/test_tool_registration_gating.py \
  tests/unit/test_tools_registry.py \
  tests/unit/test_risk.py \
  tests/unit/test_web_tool.py \
  tests/unit/test_download_tool.py \
  tests/unit/test_agent_tool.py \
  tests/unit/test_inproc_tool_adapter.py -v
```

预期：全部 PASS。`test_agent_tool.py` 与 `test_inproc_tool_adapter.py` 是回归检查
—— 它们走 `build_readonly_tool_registry` 与 `InprocToolAdapter`，新参数有默认值
不该破坏它们。

- [ ] **Step 9: 跑全量后端测试 + coverage 门禁**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest --cov --cov-report=term --cov-fail-under=80 -q
```

预期：全绿且 coverage ≥ 80%。若有 `test_permission.py` / `test_permissions_enforcer.py`
/ `test_skills_search.py` / `test_nudge_guard.py` 因工具集合变化而失败，读失败断言
判断是"硬编码了工具名列表"（改列表）还是"真的行为回归"（修实现）。

- [ ] **Step 10: 跑 ruff 与 import-linter**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m importlinter.cli lint --config pyproject.toml
```

预期：ruff 无告警；`hexagonal-architecture` 契约 KEPT。

- [ ] **Step 11: 提交**

```bash
git add backend/tools/__init__.py backend/tools/agent_tool.py backend/domain/risk.py \
  backend/agents/profiles.py backend/tests/unit/test_tool_registration_gating.py \
  backend/tests/unit/test_tools_registry.py backend/tests/unit/test_risk.py
git commit -m "feat(tools): 出网工具按网络模式条件注册（含子代理路径）"
```

---

## Task 7: 前端网络设置 Tab

**Files:**
- Create: `src/pages/settings/NetworkTab.tsx`
- Create: `src/pages/settings/__tests__/NetworkTab.test.tsx`
- Modify: `src/shared/api/settingsClient.ts:23-31`（`PreferenceKey` 联合类型）
- Modify: `src/pages/settings/Settings.tsx:12-18, 24-31, 62-74`
- Modify: `src/shared/lib/i18n/zh.ts`、`src/shared/lib/i18n/en.ts`

**Interfaces:**
- Consumes: Task 2 落库的 `preferences` key `network_policy`（JSON 字符串）
- Produces:
  - `NetworkTab` React 组件（无 props，自己读写 KV）
  - `NETWORK_MODES = ['online', 'intranet', 'offline'] as const`
  - `export type NetworkMode = (typeof NETWORK_MODES)[number]`

**为什么独立成 tab 而非塞进 GeneralTab：** `GeneralTab.tsx` 已 287 行，host 列表
的增删 UI 会让它继续膨胀。走 `permission_mode` 同样的 KV 读写路径
（`settingsClient.getPreference` / `setPreference`），不碰 `app_settings` blob。

- [ ] **Step 1: 写失败测试**

创建 `src/pages/settings/__tests__/NetworkTab.test.tsx`：

```tsx
// @vitest-environment jsdom
/**
 * NetworkTab 契约（内网 Web 访问 Task 7）。
 *
 * 配置走 preferences KV 的 network_policy key（JSON 字符串），与
 * permission_mode 同一路径 —— 不进 app_settings blob（后者有 LEGAL_TOP_KEYS
 * 白名单，加字段要同步改前后端三处）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { NetworkTab } from '../NetworkTab';

const mocks = vi.hoisted(() => ({
  getPreference: vi.fn(),
  setPreference: vi.fn(),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getPreference: (...args: unknown[]) => mocks.getPreference(...args),
    setPreference: (...args: unknown[]) => mocks.setPreference(...args),
  },
}));

function renderTab(): void {
  render(
    <I18nProvider>
      <NetworkTab />
    </I18nProvider>,
  );
}

function lastSavedPolicy(): Record<string, unknown> {
  const calls = mocks.setPreference.mock.calls;
  expect(calls.length).toBeGreaterThan(0);
  const [key, value] = calls[calls.length - 1];
  expect(key).toBe('network_policy');
  return JSON.parse(value as string);
}

describe('NetworkTab', () => {
  beforeEach(() => {
    mocks.getPreference.mockReset();
    mocks.setPreference.mockReset();
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);
  });

  it('defaults to online when no stored policy', async () => {
    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('online');
    });
  });

  it('loads stored mode and hosts', async () => {
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({
        mode: 'intranet',
        allowed_hosts: ['*.example.internal', 'docs.example.internal'],
        insecure_tls_hosts: ['docs.example.internal'],
      }),
    );
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('intranet');
    });
    expect(screen.getByText('*.example.internal')).toBeTruthy();
    expect(screen.getByText('docs.example.internal')).toBeTruthy();
  });

  it('persists mode change as JSON under network_policy key', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('network-mode-select'), {
      target: { value: 'intranet' },
    });

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    expect(lastSavedPolicy().mode).toBe('intranet');
  });

  it('adds an allowed host', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('allowed-host-input'), {
      target: { value: '*.example.internal' },
    });
    fireEvent.click(screen.getByTestId('allowed-host-add'));

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    expect(lastSavedPolicy().allowed_hosts).toEqual(['*.example.internal']);
  });

  it('rejects an overbroad wildcard without saving', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('allowed-host-input'), {
      target: { value: '*.net' },
    });
    fireEvent.click(screen.getByTestId('allowed-host-add'));

    expect(screen.getByTestId('allowed-host-error')).toBeTruthy();
    expect(mocks.setPreference).not.toHaveBeenCalled();
  });

  it('removes an allowed host and drops the TLS exemption it covered', async () => {
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({
        mode: 'intranet',
        allowed_hosts: ['docs.example.internal'],
        insecure_tls_hosts: ['docs.example.internal'],
      }),
    );
    renderTab();
    await waitFor(() => screen.getByTestId('allowed-host-remove-0'));

    fireEvent.click(screen.getByTestId('allowed-host-remove-0'));

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    const saved = lastSavedPolicy();
    expect(saved.allowed_hosts).toEqual([]);
    // 后端 __post_init__ 要求 insecure_tls_hosts ⊆ allowed_hosts，
    // 留着孤儿条目会让整份配置被拒并 fail-safe 回 online
    expect(saved.insecure_tls_hosts).toEqual([]);
  });

  it('refuses a TLS exemption not covered by allowed_hosts', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    fireEvent.change(screen.getByTestId('insecure-tls-input'), {
      target: { value: 'rogue.example.internal' },
    });
    fireEvent.click(screen.getByTestId('insecure-tls-add'));

    expect(screen.getByTestId('insecure-tls-error')).toBeTruthy();
    expect(mocks.setPreference).not.toHaveBeenCalled();
  });

  it('warns when intranet mode has an empty whitelist', async () => {
    mocks.getPreference.mockResolvedValue(JSON.stringify({ mode: 'intranet' }));
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('empty-whitelist-warning')).toBeTruthy();
    });
  });

  it('hides host editors in online mode', async () => {
    renderTab();
    await waitFor(() => screen.getByTestId('network-mode-select'));

    expect(screen.queryByTestId('allowed-host-input')).toBeNull();
  });

  it('survives malformed stored JSON by falling back to online', async () => {
    mocks.getPreference.mockResolvedValue('{not json');
    renderTab();

    await waitFor(() => {
      expect(screen.getByTestId('network-mode-select')).toHaveValue('online');
    });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npx vitest run src/pages/settings/__tests__/NetworkTab.test.tsx
```

预期：`Failed to resolve import "../NetworkTab"`

- [ ] **Step 3: 实现 host 校验与持久化逻辑**

创建 `src/pages/settings/NetworkTab.tsx`（第一部分）：

```tsx
/**
 * Settings 页面 - 网络 Tab（内网 Web 访问）
 *
 * 配置走 preferences KV 的 network_policy key（JSON 字符串），与 permission_mode
 * 同一路径。不进 app_settings blob —— 后者有 LEGAL_TOP_KEYS 白名单校验，加顶层
 * 字段要同步改前端 AppSettings、后端白名单、契约测试三处。
 */

import { useEffect, useState } from 'react';

import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

/** 与后端 NetworkMode 枚举值一致（backend/domain/network_policy.py） */
export const NETWORK_MODES = ['online', 'intranet', 'offline'] as const;
export type NetworkMode = (typeof NETWORK_MODES)[number];

interface NetworkPolicyPayload {
  mode: NetworkMode;
  allowed_hosts: string[];
  insecure_tls_hosts: string[];
}

const DEFAULT_POLICY: NetworkPolicyPayload = {
  mode: 'online',
  allowed_hosts: [],
  insecure_tls_hosts: [],
};

function normalizeHost(value: string): string {
  return value.trim().toLowerCase().replace(/\.+$/, '');
}

/**
 * 与后端 host_matches 同语义：`*.` 通配命中 apex 自身及任意层级子域。
 * 后缀混淆（evilcnki.net vs *.cnki.net）不命中。
 */
function hostMatches(host: string, pattern: string): boolean {
  const h = normalizeHost(host);
  const p = normalizeHost(pattern);
  if (!p.startsWith('*.')) return h === p;
  const apex = p.slice(2);
  return h === apex || h.endsWith(`.${apex}`);
}

/**
 * 与后端 _validate_pattern 同语义。返回 null 表示合法，否则返回 i18n key。
 *
 * 先判是否含 `*` 再看前缀：normalizeHost 的尾点剥离会把 `*.` 变成 `*`，
 * 只用 startsWith('*.') 判断会让 `*` 和 `*.` 双双漏过。
 */
function validatePattern(raw: string): TranslationKey | null {
  const value = normalizeHost(raw);
  if (!value) return 'settings.network.error.empty';
  if (!value.includes('*')) return null;
  if (!value.startsWith('*.')) return 'settings.network.error.wildcard_format';
  const apex = value.slice(2);
  if (apex.includes('*')) return 'settings.network.error.wildcard_format';
  if (!apex.includes('.')) return 'settings.network.error.wildcard_too_broad';
  return null;
}

function parsePolicy(raw: string | null): NetworkPolicyPayload {
  if (!raw) return DEFAULT_POLICY;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_POLICY;
    const candidate = parsed as Partial<NetworkPolicyPayload>;
    const mode = (NETWORK_MODES as readonly string[]).includes(candidate.mode ?? '')
      ? (candidate.mode as NetworkMode)
      : 'online';
    return {
      mode,
      allowed_hosts: Array.isArray(candidate.allowed_hosts)
        ? candidate.allowed_hosts.filter((h): h is string => typeof h === 'string')
        : [],
      insecure_tls_hosts: Array.isArray(candidate.insecure_tls_hosts)
        ? candidate.insecure_tls_hosts.filter((h): h is string => typeof h === 'string')
        : [],
    };
  } catch {
    // 坏 JSON 回退 online —— 与后端 load_network_policy 的 fail-safe 方向一致
    return DEFAULT_POLICY;
  }
}
```

- [ ] **Step 4: 实现列表编辑子组件**

追加到 `src/pages/settings/NetworkTab.tsx`：

```tsx
interface HostListEditorProps {
  testIdPrefix: string;
  label: string;
  hint: string;
  hosts: string[];
  onAdd: (host: string) => TranslationKey | null;
  onRemove: (index: number) => void;
}

function HostListEditor({
  testIdPrefix,
  label,
  hint,
  hosts,
  onAdd,
  onRemove,
}: HostListEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<TranslationKey | null>(null);

  const handleAdd = (): void => {
    const rejection = onAdd(draft);
    setError(rejection);
    if (!rejection) setDraft('');
  };

  return (
    <div className="space-y-2 py-3 border-b border-border">
      <div className="text-sm text-text">{label}</div>
      <div className="text-xs text-muted">{hint}</div>

      <div className="flex items-center gap-2">
        <input
          data-testid={`${testIdPrefix}-input`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAdd();
          }}
          placeholder="*.example.internal"
          className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
        <button
          type="button"
          data-testid={`${testIdPrefix}-add`}
          onClick={handleAdd}
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
        >
          {t('settings.network.host.add')}
        </button>
      </div>

      {error && (
        <div data-testid={`${testIdPrefix}-error`} className="text-xs text-error">
          {t(error)}
        </div>
      )}

      {hosts.length === 0 ? (
        <div className="text-xs text-muted">{t('settings.network.host.empty')}</div>
      ) : (
        <ul className="space-y-1">
          {hosts.map((host, index) => (
            <li
              key={host}
              className="flex items-center justify-between px-2 py-1 text-xs bg-surface rounded-radius-sm"
            >
              <span className="text-text font-mono">{host}</span>
              <button
                type="button"
                data-testid={`${testIdPrefix}-remove-${index}`}
                onClick={() => onRemove(index)}
                className="text-error hover:text-red-700 transition-colors"
              >
                {t('settings.network.host.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 实现主组件**

追加到 `src/pages/settings/NetworkTab.tsx`：

```tsx
export function NetworkTab() {
  const { t } = useI18n();
  const [policy, setPolicy] = useState<NetworkPolicyPayload>(DEFAULT_POLICY);

  useEffect(() => {
    let cancelled = false;
    void settingsClient.getPreference('network_policy').then((raw) => {
      if (!cancelled) setPolicy(parsePolicy(raw));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = (next: NetworkPolicyPayload): void => {
    setPolicy(next);
    void settingsClient.setPreference('network_policy', JSON.stringify(next), 'network');
  };

  const handleModeChange = (mode: NetworkMode): void => {
    persist({ ...policy, mode });
  };

  const addAllowedHost = (raw: string): TranslationKey | null => {
    const rejection = validatePattern(raw);
    if (rejection) return rejection;
    const host = normalizeHost(raw);
    if (policy.allowed_hosts.some((existing) => normalizeHost(existing) === host)) {
      return 'settings.network.error.duplicate';
    }
    persist({ ...policy, allowed_hosts: [...policy.allowed_hosts, host] });
    return null;
  };

  const removeAllowedHost = (index: number): void => {
    const allowed = policy.allowed_hosts.filter((_, i) => i !== index);
    // 后端 __post_init__ 要求 insecure_tls_hosts ⊆ allowed_hosts；留下孤儿条目
    // 会让整份配置被拒并 fail-safe 回 online，所以同步剔除失去覆盖的豁免项。
    const insecure = policy.insecure_tls_hosts.filter((host) =>
      allowed.some((pattern) => hostMatches(host, pattern)),
    );
    persist({ ...policy, allowed_hosts: allowed, insecure_tls_hosts: insecure });
  };

  const addInsecureTlsHost = (raw: string): TranslationKey | null => {
    const rejection = validatePattern(raw);
    if (rejection) return rejection;
    const host = normalizeHost(raw);
    if (!policy.allowed_hosts.some((pattern) => hostMatches(host, pattern))) {
      return 'settings.network.error.tls_not_covered';
    }
    if (policy.insecure_tls_hosts.some((existing) => normalizeHost(existing) === host)) {
      return 'settings.network.error.duplicate';
    }
    persist({ ...policy, insecure_tls_hosts: [...policy.insecure_tls_hosts, host] });
    return null;
  };

  const removeInsecureTlsHost = (index: number): void => {
    persist({
      ...policy,
      insecure_tls_hosts: policy.insecure_tls_hosts.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="space-y-2">
      <SettingRow
        label={t('settings.network.mode')}
        desc={t(`settings.network.mode.${policy.mode}.desc` as TranslationKey)}
      >
        <select
          data-testid="network-mode-select"
          aria-label={t('settings.network.mode')}
          value={policy.mode}
          onChange={(e) => handleModeChange(e.target.value as NetworkMode)}
          className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        >
          {NETWORK_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {t(`settings.network.mode.${mode}` as TranslationKey)}
            </option>
          ))}
        </select>
      </SettingRow>

      {policy.mode === 'intranet' && policy.allowed_hosts.length === 0 && (
        <div
          data-testid="empty-whitelist-warning"
          className="px-3 py-2 text-xs text-warning bg-surface rounded-radius-sm"
        >
          {t('settings.network.empty_whitelist_warning')}
        </div>
      )}

      {policy.mode === 'intranet' && (
        <>
          <HostListEditor
            testIdPrefix="allowed-host"
            label={t('settings.network.allowed_hosts')}
            hint={t('settings.network.allowed_hosts.hint')}
            hosts={policy.allowed_hosts}
            onAdd={addAllowedHost}
            onRemove={removeAllowedHost}
          />
          <HostListEditor
            testIdPrefix="insecure-tls"
            label={t('settings.network.insecure_tls')}
            hint={t('settings.network.insecure_tls.hint')}
            hosts={policy.insecure_tls_hosts}
            onAdd={addInsecureTlsHost}
            onRemove={removeInsecureTlsHost}
          />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 6: 加 PreferenceKey 与 i18n 文案**

`src/shared/api/settingsClient.ts` 的 `PreferenceKey` 联合类型末尾加：

```typescript
  | 'network_policy';
```

（原 `| 'permission_rules';` 改为 `| 'permission_rules'`，分号移到新行末尾。）

`src/shared/lib/i18n/zh.ts` 加：

```typescript
  'settings.network.mode': '网络模式',
  'settings.network.mode.online': '联网（默认）',
  'settings.network.mode.online.desc': '搜索可用，可访问任意地址',
  'settings.network.mode.intranet': '内网',
  'settings.network.mode.intranet.desc': '搜索工具不加载；仅可访问白名单内的主机',
  'settings.network.mode.offline': '气隙',
  'settings.network.mode.offline.desc': '禁止一切出网访问，所有联网工具都不加载',
  'settings.network.allowed_hosts': '主机白名单',
  'settings.network.allowed_hosts.hint':
    '支持 *. 前缀通配（如 *.cnki.net，匹配该域及其所有子域）。通配后至少需要两段域名。',
  'settings.network.insecure_tls': '跳过 TLS 校验的主机',
  'settings.network.insecure_tls.hint':
    '内网自签证书专用。只能填写已在主机白名单覆盖范围内的地址。',
  'settings.network.host.add': '添加',
  'settings.network.host.remove': '移除',
  'settings.network.host.empty': '尚未添加',
  'settings.network.empty_whitelist_warning':
    '内网模式下白名单为空，当前禁止访问任何地址。请添加需要访问的主机。',
  'settings.network.error.empty': '主机不能为空',
  'settings.network.error.wildcard_format': '通配格式非法，只支持 *. 前缀且只能出现一次',
  'settings.network.error.wildcard_too_broad': '通配范围过宽，*. 后至少需要两段域名',
  'settings.network.error.duplicate': '该主机已在列表中',
  'settings.network.error.tls_not_covered': '该主机不在白名单覆盖范围内，请先添加到主机白名单',
```

`src/shared/lib/i18n/en.ts` 加对应英文键（键名完全一致）：

```typescript
  'settings.network.mode': 'Network mode',
  'settings.network.mode.online': 'Online (default)',
  'settings.network.mode.online.desc': 'Search available, any address reachable',
  'settings.network.mode.intranet': 'Intranet',
  'settings.network.mode.intranet.desc':
    'Search tool not loaded; only whitelisted hosts reachable',
  'settings.network.mode.offline': 'Air-gapped',
  'settings.network.mode.offline.desc': 'All outbound access blocked; no network tools loaded',
  'settings.network.allowed_hosts': 'Host allowlist',
  'settings.network.allowed_hosts.hint':
    'Supports *. prefix wildcards (e.g. *.cnki.net matches the domain and all subdomains). At least two labels required after *.',
  'settings.network.insecure_tls': 'Hosts skipping TLS verification',
  'settings.network.insecure_tls.hint':
    'For intranet self-signed certificates. Must already be covered by the host allowlist.',
  'settings.network.host.add': 'Add',
  'settings.network.host.remove': 'Remove',
  'settings.network.host.empty': 'None yet',
  'settings.network.empty_whitelist_warning':
    'Intranet mode with an empty allowlist blocks every address. Add the hosts you need.',
  'settings.network.error.empty': 'Host cannot be empty',
  'settings.network.error.wildcard_format':
    'Invalid wildcard: only a single leading *. is supported',
  'settings.network.error.wildcard_too_broad':
    'Wildcard too broad: at least two labels required after *.',
  'settings.network.error.duplicate': 'Host already in the list',
  'settings.network.error.tls_not_covered':
    'Host is not covered by the allowlist; add it to the host allowlist first',
```

- [ ] **Step 7: 挂进 Settings 页面**

`src/pages/settings/Settings.tsx` 三处改动：

import 区加（`import { ModelsTab } ...` 之后，保持字母序）：

```typescript
import { NetworkTab } from './NetworkTab';
```

tab 联合类型（`Settings.tsx:18`）改为：

```typescript
type SettingsTab = 'general' | 'endpoints' | 'models' | 'memory' | 'network' | 'mcp' | 'evolution';
```

tabs 数组（`Settings.tsx:24-31`）在 `{ key: 'memory', label: '记忆' },` 之后加：

```typescript
    { key: 'network', label: '网络' },
```

渲染区（`Settings.tsx:69-72` 之间）在 memory 与 mcp 之间加：

```tsx
            {activeTab === 'network' && <NetworkTab />}
```

- [ ] **Step 8: 运行测试确认通过**

```bash
npx vitest run src/pages/settings/__tests__/NetworkTab.test.tsx
```

预期：全部 PASS

- [ ] **Step 9: 跑全量前端检查**

```bash
npx vitest run src/pages/settings
npx tsc --noEmit -p tsconfig.json
npx eslint src/pages/settings/NetworkTab.tsx src/pages/settings/Settings.tsx src/shared/api/settingsClient.ts
```

预期：测试全绿；tsc 无错误；eslint 无告警。

`TranslationKey` 从 `zh.ts` 推导（`src/shared/lib/i18n/index.tsx:12`），且
`translations` 声明为 `Record<Locale, Record<TranslationKey, string>>`
（`index.tsx:16`）—— 所以 `en.ts` 漏键会在 `tsc --noEmit` 阶段报错，不需要额外的
键同步测试。`text-warning` 类已在 `tailwind.config.js:44` 定义。

- [ ] **Step 10: 提交**

```bash
git add src/pages/settings/NetworkTab.tsx src/pages/settings/Settings.tsx \
  src/pages/settings/__tests__/NetworkTab.test.tsx \
  src/shared/api/settingsClient.ts src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(settings): 网络模式与主机白名单设置页"
```

---

## 收尾：双分支落地与文档归档

Task 1-7 全绿后执行。这不是独立的实施任务，是交付前的收口清单。

- [ ] **Step 1: 全量验证**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest --cov --cov-report=term --cov-fail-under=80 -q
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check .
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m importlinter.cli lint --config pyproject.toml
npx vitest run
npx tsc --noEmit -p tsconfig.json
npx eslint . --ignore-pattern dist-electron
```

- [ ] **Step 2: 手动验证内网模式（桌面端）**

按 `.claude/CLAUDE.md` 的正常模式启动，**不要**手启后端（会导致 token 失配 401）：

```bash
npm run dev                                    # 后台，Vite 1420
./node_modules/.bin/electron --no-sandbox .    # 自带 spawnBackend
```

验证清单：

1. 设置 → 网络：切到「内网」，白名单为空时应显示警告条
2. 加一条 `*.example.internal`，警告消失
3. 尝试加 `*.net` → 报「通配范围过宽」，不落库
4. 在「跳过 TLS 校验的主机」里加 `rogue.other.internal` → 报「不在白名单覆盖范围内」
5. 移除 `*.example.internal` → 已有的 TLS 豁免项应同步消失
6. 切「气隙」模式后开新会话，问 LLM「你有哪些工具」→ 回答里不应出现
   `web_search` / `web_fetch` / `http_download`
7. 切回「联网」模式开新会话 → 三个工具重新出现

第 6/7 步是本功能的核心价值验证：注册期门禁生效意味着 LLM **根本看不到**工具，
而不是调用后收到错误。

- [ ] **Step 3: 更新 spec 状态与技术手册**

spec `docs/superpowers/specs/2026-09-02-intranet-web-access-design.md` 顶部
`> 状态: 设计中` 改为 `> 状态: 已实施`。

按项目文档规范（`feature-development.md`），功能完成后把内容并入技术手册。新建
`docs/technical/46-intranet-web-access.md`，内容为：网络模式三档语义、host 白名单
通配规则、`web_fetch` 的四种 mode、`http_download` 的边界约束、配置存储位置
（`preferences` KV 的 `network_policy`）。并在 `docs/technical/README.md` 的章节
目录追加一行。

**不删** spec（`docs/superpowers/specs/README.md` 的归档策略：spec 永久保留作为
"设计 vs 实际"对比基线）。**删除**本 plan 文件 —— `docs/superpowers/plans/` 只保留
进行中的计划。

- [ ] **Step 4: 更新 CHANGELOG**

`CHANGELOG.md` 的 `[Unreleased]` 段 `### Added` 下加：

```markdown
- feat: 网络模式门禁（online/intranet/offline）+ 主机白名单，内网环境下搜索工具不加载
- feat: web_fetch 正文抽取（text/links/tables/raw 四模式）+ GBK/GB18030 编码嗅探
- feat: http_download 流式下载工具（工作区边界 + 双重大小上限）
```

- [ ] **Step 5: 开 PR 到 main**

```bash
git push -u origin feat/intranet-web-access
gh pr create --title "feat: 内网 Web 访问（网络模式门禁 + 取页下载）" --body "$(cat <<'EOF'
## Summary
- 新增 `NetworkPolicy` 领域模型：online / intranet / offline 三模式 + host 白名单（`*.` 通配）
- 出网工具按模式**条件注册** —— 内网/气隙下 LLM 根本看不到 `web_search`，不会白试
- `web_fetch` 接正文抽取（stdlib 栈式实现）+ 编码嗅探，不再把整页 HTML 丢给模型
- 新增 `http_download`：流式落盘、工作区边界、双重大小上限、文件名净化

## Test plan
- [ ] backend pytest 全绿，coverage ≥ 80%
- [ ] ruff + import-linter 通过
- [ ] vitest + tsc + eslint 通过
- [ ] 桌面端手动验证：三种模式切换、白名单增删校验、气隙模式下工具对 LLM 不可见
EOF
)"
```

- [ ] **Step 6: cherry-pick 到 release/win7**

**必须**等 main 的 PR 合并后再做。按项目 CLAUDE.md 的双分支约束：不 merge，只
cherry-pick，且手动验证兼容性。

```bash
git switch release/win7
git pull --rebase origin release/win7
git switch -c fix/win7-intranet-web-access
git cherry-pick <main 上的各个 commit sha>
```

py3.8 适配检查（本计划的代码已按 `typing.*` 写，理论上零改动）：

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  tests/unit/test_network_policy.py tests/unit/test_network_config.py \
  tests/unit/test_html_extract.py tests/unit/test_download_tool.py \
  tests/unit/test_web_tool.py tests/unit/test_tool_registration_gating.py -v
```

已核实可用的 3.8 API：`Path.unlink(missing_ok=True)`（3.8 起有，仓库现有代码
`backend/api/wiki_routes.py:66` 已在用）、`html.parser.HTMLParser`、
`email.message.Message.get_filename()`、`httpx.Client.stream`。

**冲突预警**：`backend/tools/web_tool.py` 的 `_literal_ip` 在 win7 分支有
IPv4-mapped IPv6 解包的分支专属修改。本计划 Task 4 明确不动该方法，所以
cherry-pick 时该处应无冲突；若有，保留 win7 版本的 `_literal_ip` 实现。

---

## Self-Review 结论

**Spec 覆盖检查**（逐节对照 `2026-09-02-intranet-web-access-design.md`）：

| Spec 节 | 实现任务 |
|---|---|
| §1 网络策略领域模型 | Task 1 |
| §1.1 三个设计决定 | Task 1（通配校验、TLS 子集）+ Task 6（条件注册） |
| §1.2 风险分级不降级 | Task 6 Step 5（`EXTERNAL_TOOLS` 加 `http_download`） |
| §1.3 preferences KV 存储 | Task 2 Step 4 + Task 7 Step 6 |
| §1.4 加载器 fail-safe | Task 2 |
| §2 HTML 抽取层 | Task 3（**设计变更**：放弃 lxml 双实现，见 Task 3 说明） |
| §2.1 编码嗅探 | Task 3 |
| §3 下载工具 | Task 5 |
| §3.1 未绑定工作区拒绝 | Task 5 Step 4（`workspace_not_bound`） |
| §4 SSRF 防护扩面 | Task 4 Step 6（按模式分岔 + 重定向校验） |
| §4.1 空白名单 fail-closed | Task 1（`check_host`）+ Task 7（UI 警告条） |
| §5 四条注册路径 | Task 6（① ② 直接改，③ ④ 转调 ①） |
| §5.1 两种时机 | Task 4/5（执行期现读）+ Task 6（注册期读） |
| §5.2 不塞进 ToolPolicy | Task 4/5/6（独立参数） |
| §5.3 profile 白名单 | Task 6 Step 6 |
| §6 文件清单 | 全部任务覆盖 |
| §7 测试策略 | 各任务 Step 1 + Task 6 Step 7（既有测试适配） |
| §8 双分支落地 | 收尾 Step 6 |

无遗漏。

**类型一致性检查**：

- `NetworkPolicy` / `NetworkMode` 在 Task 1 定义，Task 2/4/5/6 消费，命名一致
- `load_network_policy(repo=None)` 在 Task 2 定义，Task 4/5/6 以无参调用（默认
  `repo=None`），一致
- `extract(html, base_url) -> ExtractedPage` 在 Task 3 定义，Task 4 `_render` 消费，一致
- `decode_html(body, content_type) -> Tuple[str, str]` 在 Task 3 定义，Task 4
  `_render` 解包为 `(text, encoding)`，一致
- `derive_filename` / `sanitize_filename` 在 Task 5 定义并自测，一致
- 前端 `NetworkMode` 字面量联合（`'online' | 'intranet' | 'offline'`）与后端
  `NetworkMode` 枚举值字符串一致
- Task 7 的 `hostMatches` / `validatePattern` 与 Task 1 的 `host_matches` /
  `_validate_pattern` 同语义（前端做即时反馈，后端做权威校验）

**已在原型中验证过的代码**：Task 1 的通配匹配与校验、Task 3 的完整抽取器与编码
嗅探、Task 5 的流式下载/大小上限/文件名净化/唯一路径。这些不是纸上推演。

