# 端点优先级故障转移 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Sage 聊天链路实现按优先级的端点故障转移：单端点失败时自动切换下一优先级端点，附带健康监控、冷却与 failback。

**Architecture:** 设置层新增 `endpoints[].priority` 与顶层 `failover` 配置；`llm_factory` 把可用端点构成 `endpoint_chain` 注入 `LLMConfig`；`LLMClient.chat()` / `chat_stream_events()` 在现有重试循环外增加 hop 循环；`backend/services/endpoint_health.py` 记录健康状态，`endpoint_probe.py` 后台探测失败端点；前端设置页提供优先级排序、故障转移开关与健康状态，聊天重试横幅展示切换事件。

**Tech Stack:** FastAPI + Pydantic(1/2 双兼容) + httpx（后端）；React + TypeScript + Vitest（前端）；pytest（后端测试）。

**Spec:** `docs/superpowers/specs/2026-11-26-endpoint-failover-design.md`

## Global Constraints

- Python 3.8 兼容（release/win7）：不用 `match`、PEP 604 `X | Y` 注解、`dict[str, X]` 运行期语法；沿用 `from __future__ import annotations` + `typing.Optional/List/Dict`。
- `ruff check` 必须通过（ERA001 中文注释、Q000 双引号、UP006/UP007 在 py38 测试文件用 `# ruff: noqa` 头放行）。
- 故障转移默认关闭：`failover.enabled=false` 时 `endpoint_chain` 不注入，现有行为零变化。
- 流式「首字后不重试/不切换」契约不可破坏。
- 单文件 800 行上限：`src/pages/settings/EndpointsTab.tsx` 当前 779 行，必须先拆出编辑器组件再新增 UI。
- 所有后端命令使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。
- 工作目录：`/home/fz/project/sage/.worktrees/feat-endpoint-failover-priority`（后端端口 8959 / 前端 1614）。

---

### Task 1: 设置数据模型（后端白名单 + 前端类型 + 契约测试）

**Files:**
- Modify: `backend/data/settings_canonicalizer.py`（白名单与 shape 校验）
- Modify: `backend/api/settings_models.py`（`EndpointPayload.priority`、`SettingsPayload/LegacySettingsPayload.failover`）
- Modify: `backend/tests/contract/test_settings_schema_parity.py`
- Create: `backend/tests/unit/test_settings_failover_fields.py`
- Modify: `src/entities/setting/types.ts`（`FailoverSettings`、`EndpointConfig.priority?`、`AppSettings.failover`、默认值）
- Modify: `src/entities/setting/storage.ts`（`TOP_KEYS` / `ENDPOINT_KEYS` 白名单）
- Create: `src/tests/settingsFailoverFields.test.ts`

**Interfaces:**
- Produces（后端）：`LEGAL_FAILOVER_KEYS`、`FAILOVER_INT_RANGES`；canonicalizer 接受 `failover{enabled,probeIntervalMs,cooldownMs,consecutiveFailThreshold}` 与 `endpoints[].priority`。
- Produces（前端）：`FailoverSettings`、`DEFAULT_FAILOVER_SETTINGS`、`EndpointConfig.priority?: number`、`AppSettings.failover`。

- [ ] **Step 1: 写失败的后端测试**

```python
# backend/tests/unit/test_settings_failover_fields.py
import pytest
from backend.data.settings_canonicalizer import validate_settings_shape

def _base():
    return {"endpoints": [{"id": "e1", "name": "a", "baseUrl": "http://x", "priority": 2}]}

def test_priority_and_failover_accepted():
    settings = _base()
    settings["failover"] = {
        "enabled": True, "probeIntervalMs": 300000,
        "cooldownMs": 60000, "consecutiveFailThreshold": 2,
    }
    validate_settings_shape(settings)  # 不抛

@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.5])
def test_priority_must_be_positive_int(bad):
    settings = _base()
    settings["endpoints"][0]["priority"] = bad
    with pytest.raises(ValueError):
        validate_settings_shape(settings)

def test_unknown_failover_key_rejected():
    settings = _base()
    settings["failover"] = {"enabled": True, "foo": 1}
    with pytest.raises(ValueError):
        validate_settings_shape(settings)

@pytest.mark.parametrize(
    "key,value",
    [("probeIntervalMs", 1000), ("cooldownMs", 100),
     ("consecutiveFailThreshold", 0), ("consecutiveFailThreshold", 11),
     ("enabled", "yes")],
)
def test_failover_values_validated(key, value):
    settings = _base()
    settings["failover"] = {key: value}
    with pytest.raises(ValueError):
        validate_settings_shape(settings)
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_failover_fields.py -q`
Expected: FAIL（`priority`/`failover` 被拒）。

- [ ] **Step 3: 实现 canonicalizer**

```python
# settings_canonicalizer.py —— LEGAL_TOP_KEYS 增 "failover"
# LEGAL_ENDPOINT_KEYS 增 "priority"
LEGAL_FAILOVER_KEYS: FrozenSet[str] = frozenset(
    {"enabled", "probeIntervalMs", "cooldownMs", "consecutiveFailThreshold"}
)
FAILOVER_INT_RANGES = {
    "probeIntervalMs": (30_000, 86_400_000),
    "cooldownMs": (5_000, 3_600_000),
    "consecutiveFailThreshold": (1, 10),
}
```

```python
# validate_settings_shape() 内，endpoints 循环中：
priority = ep.get("priority")
if priority is not None:
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
        raise ValueError(f"endpoints[{i}].priority must be a positive integer")

# validate_settings_shape() 内，wiki 校验之后：
failover = settings.get("failover")
if failover is not None and not isinstance(failover, dict):
    raise ValueError("failover is not a dict")
failover = failover or {}
bad_failover = [k for k in failover if k not in LEGAL_FAILOVER_KEYS]
if bad_failover:
    raise ValueError(
        f"unknown failover field {bad_failover[0]!r}; "
        f"allowed: {sorted(LEGAL_FAILOVER_KEYS)}"
    )
if "enabled" in failover and not isinstance(failover["enabled"], bool):
    raise ValueError("failover.enabled must be a boolean")
for key, (lo, hi) in FAILOVER_INT_RANGES.items():
    if key in failover:
        value = failover[key]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise ValueError(f"failover.{key} must be an integer in [{lo}, {hi}]")
```

- [ ] **Step 4: 更新 settings_models.py**

```python
# EndpointPayload 内：
priority: Optional[int] = None  # noqa: N815 — 1 = 最高优先级（failover 开启时生效）

# SettingsPayload 与 LegacySettingsPayload 内（两处）：
failover: Optional[dict] = None
```

- [ ] **Step 5: 更新契约测试**

```python
# test_settings_schema_parity.py
# EXPECTED_TOP_KEYS 增 "failover"
# test_legal_endpoint_keys_is_stable 集合增 "priority"
```

- [ ] **Step 6: 前端类型与白名单**

```ts
// src/entities/setting/types.ts
export interface FailoverSettings {
  enabled: boolean;
  probeIntervalMs: number;
  cooldownMs: number;
  consecutiveFailThreshold: number;
}
export const DEFAULT_FAILOVER_SETTINGS: FailoverSettings = {
  enabled: false,
  probeIntervalMs: 300_000,
  cooldownMs: 60_000,
  consecutiveFailThreshold: 2,
};
// EndpointConfig 增（可选，兼容旧数据）：
priority?: number;
// AppSettings 增：
failover: FailoverSettings;
// DEFAULT_SETTINGS 增：
failover: DEFAULT_FAILOVER_SETTINGS,
```

```ts
// src/entities/setting/storage.ts
// TOP_KEYS 增 'failover'
// ENDPOINT_KEYS 增 'priority'
```

- [ ] **Step 7: 前端测试**

```ts
// src/tests/settingsFailoverFields.test.ts
import { describe, expect, it } from 'vitest';
import { DEFAULT_FAILOVER_SETTINGS, DEFAULT_SETTINGS } from '../entities/setting/types';

describe('failover settings defaults', () => {
  it('defaults failover to disabled with sane intervals', () => {
    expect(DEFAULT_FAILOVER_SETTINGS.enabled).toBe(false);
    expect(DEFAULT_FAILOVER_SETTINGS.probeIntervalMs).toBe(300_000);
    expect(DEFAULT_FAILOVER_SETTINGS.cooldownMs).toBe(60_000);
    expect(DEFAULT_FAILOVER_SETTINGS.consecutiveFailThreshold).toBe(2);
    expect(DEFAULT_SETTINGS.failover).toEqual(DEFAULT_FAILOVER_SETTINGS);
  });
});
```

- [ ] **Step 8: 运行全部相关测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_failover_fields.py backend/tests/contract/test_settings_schema_parity.py -q
npx vitest run src/tests/settingsFailoverFields.test.ts
```
Expected: 全绿。

- [ ] **Step 9: Commit**

```bash
git add backend/data/settings_canonicalizer.py backend/api/settings_models.py backend/tests/contract/test_settings_schema_parity.py backend/tests/unit/test_settings_failover_fields.py src/entities/setting/types.ts src/entities/setting/storage.ts src/tests/settingsFailoverFields.test.ts
git commit -m "feat(settings): add endpoint priority and failover settings schema"
```

---

### Task 2: 端点健康注册表

**Files:**
- Create: `backend/services/endpoint_health.py`
- Create: `backend/tests/unit/test_endpoint_health.py`

**Interfaces:**
- Produces: `FailoverConfig`（`enabled/probe_interval_ms/cooldown_ms/consecutive_fail_threshold`）、`load_failover_config() -> FailoverConfig`、`EndpointHealthState`、`EndpointHealthRegistry`（`record_success(endpoint_id)`、`record_failure(endpoint_id, reason)`、`record_failover(endpoint_id)`、`is_available(endpoint_id) -> bool`、`snapshot(endpoint_ids=None) -> List[Dict[str, Any]]`、`configure(threshold=, cooldown_s=)`、`reset()`）、`get_health_registry()`、`reset_health_registry()`。
- 常量：`HEALTHY="healthy"`、`DEGRADED="degraded"`、`FAILED="failed"`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_endpoint_health.py
from backend.services.endpoint_health import (
    DEGRADED, FAILED, HEALTHY, EndpointHealthRegistry,
)

def test_state_machine_and_recovery():
    now = {"t": 1000.0}
    reg = EndpointHealthRegistry(threshold=2, cooldown_s=60, clock=lambda: now["t"])
    reg.record_failure("ep1", "timeout")
    assert reg.get("ep1").status == DEGRADED
    reg.record_failure("ep1", "timeout")
    assert reg.get("ep1").status == FAILED
    assert reg.is_available("ep1") is False
    now["t"] += 61
    assert reg.is_available("ep1") is True  # 被动 failback：冷却期满允许重试
    reg.record_success("ep1")
    state = reg.get("ep1")
    assert state.status == HEALTHY and state.consecutive_failures == 0
    assert state.last_failure_reason is None

def test_snapshot_includes_requested_endpoints_as_healthy():
    reg = EndpointHealthRegistry()
    reg.record_failure("ep1", "rate_limited")
    snap = {s["endpointId"]: s for s in reg.snapshot(["ep1", "ep2"])}
    assert snap["ep1"]["status"] == DEGRADED
    assert snap["ep2"]["status"] == HEALTHY

def test_record_failover_counter():
    reg = EndpointHealthRegistry()
    reg.record_failover("ep1")
    assert reg.snapshot(["ep1"])[0]["failoverCount"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_health.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
# backend/services/endpoint_health.py
"""Endpoint health registry used by LLM failover."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
FAILED = "failed"

DEFAULT_THRESHOLD = 2
DEFAULT_COOLDOWN_S = 60.0
DEFAULT_PROBE_INTERVAL_MS = 300_000
FAILOVER_INT_RANGES = {
    "probeIntervalMs": (30_000, 86_400_000),
    "cooldownMs": (5_000, 3_600_000),
    "consecutiveFailThreshold": (1, 10),
}


@dataclass
class FailoverConfig:
    enabled: bool = False
    probe_interval_ms: int = DEFAULT_PROBE_INTERVAL_MS
    cooldown_ms: int = 60_000
    consecutive_fail_threshold: int = DEFAULT_THRESHOLD


def _coerce_int(value: Any, default: int, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    lo, hi = FAILOVER_INT_RANGES[key]
    if not lo <= value <= hi:
        return default
    return value


def load_failover_config() -> FailoverConfig:
    """Read ``app_settings.failover`` defensively; never raises."""
    raw: Dict[str, Any] = {}
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        data = SettingsRepository().get_json("app_settings")
        if isinstance(data, dict):
            raw = to_camel(data).get("failover") or {}
    except Exception as exc:  # noqa: BLE001 — config read must not break chat
        logger.debug("failover config unavailable: %s", exc)
        return FailoverConfig()
    if not isinstance(raw, dict):
        return FailoverConfig()
    return FailoverConfig(
        enabled=raw.get("enabled") is True,
        probe_interval_ms=_coerce_int(
            raw.get("probeIntervalMs"), DEFAULT_PROBE_INTERVAL_MS, "probeIntervalMs"
        ),
        cooldown_ms=_coerce_int(raw.get("cooldownMs"), 60_000, "cooldownMs"),
        consecutive_fail_threshold=_coerce_int(
            raw.get("consecutiveFailThreshold"),
            DEFAULT_THRESHOLD,
            "consecutiveFailThreshold",
        ),
    )


@dataclass
class EndpointHealthState:
    endpoint_id: str
    status: str = HEALTHY
    consecutive_failures: int = 0
    last_failure_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_failure_reason: Optional[str] = None
    failover_count: int = 0


class EndpointHealthRegistry:
    def __init__(
        self,
        threshold: int = DEFAULT_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._clock = clock or time.time
        self._states: Dict[str, EndpointHealthState] = {}

    def configure(self, *, threshold: Optional[int] = None, cooldown_s: Optional[float] = None) -> None:
        if threshold is not None:
            self._threshold = max(1, int(threshold))
        if cooldown_s is not None:
            self._cooldown_s = max(0.0, float(cooldown_s))

    def get(self, endpoint_id: str) -> EndpointHealthState:
        state = self._states.get(endpoint_id)
        if state is None:
            state = EndpointHealthState(endpoint_id=endpoint_id)
            self._states[endpoint_id] = state
        return state

    def record_success(self, endpoint_id: Optional[str]) -> None:
        if not endpoint_id:
            return
        state = self.get(endpoint_id)
        state.status = HEALTHY
        state.consecutive_failures = 0
        state.last_success_at = self._clock()
        state.last_failure_reason = None

    def record_failure(self, endpoint_id: Optional[str], reason: str) -> None:
        if not endpoint_id:
            return
        state = self.get(endpoint_id)
        state.consecutive_failures += 1
        state.last_failure_at = self._clock()
        state.last_failure_reason = reason
        state.status = FAILED if state.consecutive_failures >= self._threshold else DEGRADED

    def record_failover(self, endpoint_id: Optional[str]) -> None:
        if not endpoint_id:
            return
        self.get(endpoint_id).failover_count += 1

    def is_available(self, endpoint_id: Optional[str]) -> bool:
        if not endpoint_id:
            return True
        state = self._states.get(endpoint_id)
        if state is None or state.status != FAILED:
            return True
        if state.last_failure_at is None:
            return True
        return (self._clock() - state.last_failure_at) >= self._cooldown_s

    def snapshot(self, endpoint_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        ids = list(endpoint_ids or [])
        for endpoint_id in self._states:
            if endpoint_id not in ids:
                ids.append(endpoint_id)
        out: List[Dict[str, Any]] = []
        for endpoint_id in ids:
            state = self.get(endpoint_id)
            out.append(
                {
                    "endpointId": endpoint_id,
                    "status": state.status,
                    "consecutiveFailures": state.consecutive_failures,
                    "lastFailureAt": state.last_failure_at,
                    "lastSuccessAt": state.last_success_at,
                    "lastFailureReason": state.last_failure_reason,
                    "failoverCount": state.failover_count,
                }
            )
        return out

    def reset(self) -> None:
        self._states.clear()


_registry: Optional[EndpointHealthRegistry] = None


def get_health_registry() -> EndpointHealthRegistry:
    global _registry
    if _registry is None:
        _registry = EndpointHealthRegistry()
    return _registry


def reset_health_registry() -> None:
    global _registry
    _registry = None
```

- [ ] **Step 4: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_health.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/services/endpoint_health.py backend/tests/unit/test_endpoint_health.py
git commit -m "feat(failover): add endpoint health registry with cooldown and snapshot"
```

---

### Task 3: 端点链构建（llm_factory）

**Files:**
- Modify: `backend/orchestration/llm_factory.py`
- Modify: `backend/core/legacy/llm_client.py`（仅新增 `EndpointHop` dataclass）
- Create: `backend/tests/unit/test_llm_factory_failover.py`

**Interfaces:**
- Consumes: `get_health_registry()`（Task 2）。
- Produces: `build_endpoint_chain(endpoints, *, primary_endpoint_id, primary_model, fallback_model=None, health=None) -> List[EndpointHop]`、`attach_endpoint_chain(cfg) -> dict`；`load_llm_config_for_chat()` 返回值在 failover 开启时含 `endpoint_chain`。

- [ ] **Step 1: 在 llm_client.py 加入 EndpointHop**

```python
@dataclass(frozen=True)
class EndpointHop:
    """One endpoint in the failover chain (see EndpointConfig.priority)."""

    endpoint_id: Optional[str] = None
    endpoint_name: Optional[str] = None
    base_url: str = ""
    api_key: str = ""
    provider: str = "openai"
    model: str = ""
    fallback_model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    thinking_budget: Optional[int] = None
```

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/unit/test_llm_factory_failover.py
from backend.services.endpoint_health import EndpointHealthRegistry
from backend.orchestration.llm_factory import build_endpoint_chain

def _ep(eid, priority=None, models=("m1",), model_id=""):
    ep = {
        "id": eid, "name": eid, "baseUrl": f"http://{eid}",
        "apiKey": "k", "protocol": "openai-compatible",
        "modelId": model_id,
        "discoveredModels": [{"id": m, "capabilities": [], "endpointId": eid} for m in models],
    }
    if priority is not None:
        ep["priority"] = priority
    return ep

def test_chain_orders_primary_then_priority():
    eps = [_ep("low", 3), _ep("high", 1), _ep("mid", 2)]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="low", primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert [h.endpoint_id for h in chain] == ["low", "high", "mid"]

def test_same_model_preferred_over_endpoint_default():
    eps = [_ep("a"), _ep("b", models=("m2",), model_id="m2")]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="a", primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert chain[1].model == "m2"

def test_same_name_model_used_when_available():
    eps = [_ep("a"), _ep("b", models=("m1", "m2"))]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="a", primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert chain[1].model == "m1"

def test_endpoint_without_model_is_skipped():
    eps = [_ep("a"), _ep("b", models=())]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="a", primary_model="m1",
        health=EndpointHealthRegistry(),
    )
    assert [h.endpoint_id for h in chain] == ["a"]

def test_cooling_failed_endpoint_moves_last():
    health = EndpointHealthRegistry(threshold=1, cooldown_s=60)
    health.record_failure("high", "timeout")
    eps = [_ep("primary", 2), _ep("high", 1), _ep("third", 3)]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="primary", primary_model="m1", health=health,
    )
    assert [h.endpoint_id for h in chain] == ["primary", "third", "high"]

def test_fallback_model_only_on_primary_hop():
    eps = [_ep("a"), _ep("b")]
    chain = build_endpoint_chain(
        eps, primary_endpoint_id="a", primary_model="m1",
        fallback_model="mini", health=EndpointHealthRegistry(),
    )
    assert chain[0].fallback_model == "mini"
    assert chain[1].fallback_model is None
```

- [ ] **Step 3: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_factory_failover.py -q`
Expected: FAIL（`build_endpoint_chain` 不存在）。

- [ ] **Step 4: 实现构链**

```python
# llm_factory.py 追加
def _protocol_to_provider(protocol: str) -> str:
    return (
        "ollama" if protocol == "ollama"
        else "anthropic" if protocol == "anthropic"
        else "gemini" if protocol == "gemini"
        else "custom"
    )


def _resolve_hop_model(endpoint: Dict[str, Any], current_model: Optional[str]) -> Optional[str]:
    discovered = endpoint.get("discoveredModels") or []
    if current_model and isinstance(discovered, list):
        for model in discovered:
            if isinstance(model, dict) and model.get("id") == current_model:
                return current_model
    model_id = endpoint.get("modelId")
    if isinstance(model_id, str) and model_id.strip():
        return model_id.strip()
    if isinstance(discovered, list) and discovered and isinstance(discovered[0], dict):
        first = discovered[0].get("id")
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


def build_endpoint_chain(
    endpoints: List[Dict[str, Any]],
    *,
    primary_endpoint_id: Optional[str],
    primary_model: Optional[str],
    fallback_model: Optional[str] = None,
    health: Optional[Any] = None,
) -> List[Any]:
    """Build priority-ordered EndpointHop list; primary hop first when available."""
    from backend.core.legacy.llm_client import EndpointHop

    if health is None:
        from backend.services.endpoint_health import get_health_registry

        health = get_health_registry()

    candidates: List[Tuple[Any, ...]] = []
    for index, ep in enumerate(endpoints or []):
        if not isinstance(ep, dict):
            continue
        protocol = ep.get("protocol") or "openai-compatible"
        if protocol not in _SUPPORTED_PROTOCOLS or not ep.get("baseUrl"):
            continue
        if not _endpoint_has_required_api_key(ep, protocol=protocol):
            continue
        model = _resolve_hop_model(ep, primary_model)
        if not model:
            continue
        endpoint_id = ep.get("id")
        is_primary = bool(primary_endpoint_id) and endpoint_id == primary_endpoint_id
        available = health.is_available(endpoint_id)
        priority = ep.get("priority")
        priority_key = (
            priority
            if isinstance(priority, int) and not isinstance(priority, bool) and priority > 0
            else 10 ** 6
        )
        sort_key = (0 if available else 1, 0 if is_primary else 1, priority_key, index)
        candidates.append((sort_key, ep, model, is_primary, protocol, endpoint_id))

    candidates.sort(key=lambda item: item[0])
    chain = []
    for _key, ep, model, is_primary, protocol, endpoint_id in candidates:
        chain.append(
            EndpointHop(
                endpoint_id=endpoint_id if isinstance(endpoint_id, str) else None,
                endpoint_name=ep.get("name") if isinstance(ep.get("name"), str) else None,
                base_url=ep["baseUrl"],
                api_key=ep.get("apiKey") or "",
                provider=_protocol_to_provider(protocol),
                model=model,
                fallback_model=fallback_model if is_primary else None,
                reasoning_effort=ep.get("reasoningEffort"),
                thinking_budget=ep.get("thinkingBudget"),
            )
        )
    return chain


def attach_endpoint_chain(cfg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Attach endpoint_chain when failover is enabled and more than one hop exists."""
    if not isinstance(cfg, dict):
        return cfg
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository
        from backend.services.endpoint_health import get_health_registry, load_failover_config

        config = load_failover_config()
        if not config.enabled:
            return cfg
        raw = SettingsRepository().get_json("app_settings")
        settings = to_camel(raw) if isinstance(raw, dict) else {}
        chain = build_endpoint_chain(
            settings.get("endpoints") or [],
            primary_endpoint_id=cfg.get("endpoint_id"),
            primary_model=cfg.get("model"),
            fallback_model=cfg.get("fallback_model"),
            health=get_health_registry(),
        )
        if len(chain) <= 1:
            return cfg
        return {**cfg, "endpoint_chain": chain}
    except Exception as exc:  # noqa: BLE001 — failover is optional
        logger.debug("llm_factory: endpoint chain unavailable: %s", exc)
        return cfg
```

`load_llm_config_for_chat()` 末尾改为：

```python
    merged = apply_auto_routing_overlay(
        merged, task_type=task_type, session_id=session_id, profile_model=profile_model
    )
    return attach_endpoint_chain(merged)
```

- [ ] **Step 5: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_factory_failover.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/core/legacy/llm_client.py backend/orchestration/llm_factory.py backend/tests/unit/test_llm_factory_failover.py
git commit -m "feat(failover): build priority-ordered endpoint chain from settings"
```

---

### Task 4: LLMClient 非流式跨端点故障转移

**Files:**
- Modify: `backend/core/legacy/llm_client.py`（`LLMConfig.endpoint_chain`、hop 客户端、`FailoverEvent`、`chat()` 外层 hop 循环、健康上报）
- Create: `backend/tests/unit/test_llm_client_failover.py`

**Interfaces:**
- Consumes: `EndpointHop`（Task 3）、`get_health_registry()`（Task 2）。
- Produces: `FailoverEvent`；`LLMClient.chat(..., failover_callback=None)`；`LLMConfig.endpoint_chain: List[EndpointHop]`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_llm_client_failover.py
# ruff: noqa: UP006, UP007, UP035, UP045 — py38 兼容
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import EndpointHop, FailoverEvent, LLMClient, LLMConfig
from backend.services.endpoint_health import get_health_registry, reset_health_registry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fast_retry_and_clean_health(monkeypatch):
    monkeypatch.setattr("backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 0.01)
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0.01")
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "2")
    reset_health_registry()
    yield
    reset_health_registry()


def _ok(model):
    resp = AsyncMock()
    resp.status_code = 200
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value={
        "model": model,
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })
    return resp


def _err(status):
    resp = AsyncMock()
    resp.status_code = status
    resp.text = "boom"
    resp.headers = {}
    resp.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("boom", request=AsyncMock(), response=resp)
    )
    return resp


def _client(chain):
    return LLMClient(LLMConfig(
        provider="openai", api_key="k1", base_url="http://primary",
        model="m1", endpoint_id="ep1", endpoint_chain=chain,
    ))


HOP2 = EndpointHop(
    endpoint_id="ep2", endpoint_name="Backup", base_url="http://backup",
    api_key="k2", provider="openai", model="m1",
)


@pytest.mark.asyncio()
async def test_rate_limited_primary_fails_over_to_next_endpoint():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(429))
    backup.post = AsyncMock(return_value=_ok("m1"))
    events = []
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        response = await client.chat(
            [{"role": "user", "content": "hi"}], failover_callback=events.append
        )
    assert response.content == "ok"
    assert backup.post.await_count == 1
    assert isinstance(events[0], FailoverEvent)
    assert events[0].from_endpoint == "ep1" and events[0].to_endpoint == "ep2"
    assert get_health_registry().get("ep1").status != "healthy"
    assert get_health_registry().get("ep2").status == "healthy"


@pytest.mark.asyncio()
async def test_auth_failure_switches_immediately_without_retry():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(401))
    backup.post = AsyncMock(return_value=_ok("m1"))
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert primary.post.await_count == 1  # 401 不重试
    assert backup.post.await_count == 1


@pytest.mark.asyncio()
async def test_all_hops_fail_raises_error_naming_attempt_count():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(500))
    backup.post = AsyncMock(return_value=_err(503))
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert "2" in exc_info.value.message  # 已尝试 2 个端点


@pytest.mark.asyncio()
async def test_usage_recorded_for_serving_hop(monkeypatch):
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(429))
    backup.post = AsyncMock(return_value=_ok("m1"))
    recorded = []

    class _Tracker:
        def record(self, *args, **kwargs):
            recorded.append(kwargs.get("endpoint_id"))

    monkeypatch.setattr(
        "backend.services.usage_tracker.usage_tracker", _Tracker(), raising=False
    )
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        await client.chat([{"role": "user", "content": "hi"}])
    assert recorded and recorded[-1] == "ep2"
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_failover.py -q`
Expected: FAIL（`endpoint_chain` 未生效、无 `failover_callback`）。

- [ ] **Step 3: 实现**

在 `LLMConfig` 末尾加：

```python
    endpoint_chain: List[EndpointHop] = field(default_factory=list)
```

在 `RetryAttemptStartedEvent` 之后加：

```python
@dataclass
class FailoverEvent:
    """端点故障转移事件（reason = 触发的 LLMErrorType.value）。"""

    from_endpoint: Optional[str]
    from_endpoint_name: Optional[str]
    to_endpoint: Optional[str]
    to_endpoint_name: Optional[str]
    reason: str
    hop_index: int
    total_hops: int
```

`LLMClient.__init__` 加 `self._hop_clients: Dict[str, httpx.AsyncClient] = {}`；
`close()` 关闭所有 hop 客户端。

新增方法：

```python
    def _failover_hops(self) -> List[EndpointHop]:
        chain = getattr(self.config, "endpoint_chain", None)
        if chain:
            return list(chain)
        return [EndpointHop(
            endpoint_id=self.config.endpoint_id,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            provider=self.config.provider,
            model=self.config.model,
            fallback_model=self.config.fallback_model,
            reasoning_effort=self.config.reasoning_effort,
            thinking_budget=self.config.thinking_budget,
        )]

    def _get_client_for_hop(self, hop: EndpointHop, *, primary: bool) -> httpx.AsyncClient:
        if primary:
            return self._get_client()
        key = hop.endpoint_id or hop.base_url
        cached = self._hop_clients.get(key)
        if cached is not None and not cached.is_closed:
            return cached
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.config.use_proxy:
            backend = (self.config.backend_url or "http://127.0.0.1:8765").rstrip("/")
            client_base_url = f"{backend}/api/v1/llm"
            headers["X-LLM-Provider-Url"] = hop.base_url
            token = os.environ.get("SAGE_LOCAL_AUTH_TOKEN")
            if token:
                headers["X-Sage-Local-Authorization"] = f"Bearer {token}"
        else:
            client_base_url = hop.base_url.rstrip("/")
            if client_base_url.endswith("/v1"):
                client_base_url = client_base_url[: -len("/v1")]
        if hop.api_key:
            headers["Authorization"] = f"Bearer {hop.api_key}"
        headers.update(self.config.extra_headers)
        client = httpx.AsyncClient(
            base_url=client_base_url,
            headers=headers,
            timeout=httpx.Timeout(self.config.timeout),
        )
        self._hop_clients[key] = client
        return client

    def _should_failover(self, llm_err: LLMError, *, nothing_yielded: bool = True) -> bool:
        if not nothing_yielded:
            return False
        if llm_err.type in _RETRYABLE_ERROR_TYPES or llm_err.type == LLMErrorType.AUTH_FAILED:
            return True
        return llm_err.status_code == 403

    @staticmethod
    def _record_hop_health(hop: EndpointHop, success: bool, reason: str = "") -> None:
        if not hop.endpoint_id:
            return
        try:
            from backend.services.endpoint_health import get_health_registry

            registry = get_health_registry()
            if success:
                registry.record_success(hop.endpoint_id)
            else:
                registry.record_failure(hop.endpoint_id, reason)
        except Exception:  # noqa: BLE001 — health bookkeeping must never break chat
            logger.debug("endpoint health update skipped", exc_info=True)

    def _build_request_body(self, hop, messages, tools, tool_choice, *, stream, include_usage):
        """Body as the current chat()/stream code builds it, but from *hop*."""
        body: Dict[str, Any] = {
            "model": hop.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if stream:
            body["stream"] = True
            if include_usage:
                body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        if hop.provider == "claude":
            body["max_tokens"] = self.config.max_tokens
        if hop.reasoning_effort is not None:
            body["reasoning_effort"] = hop.reasoning_effort
        if hop.thinking_budget is not None:
            body["thinking_budget"] = hop.thinking_budget
        return body
```

`chat()` 重构为外层 hop 循环（内层保留现有 while）：

```python
        hops = self._failover_hops()
        hop_index = 0
        hop_errors: List[str] = []
        while True:
            hop = hops[hop_index]
            client = self._get_client_for_hop(hop, primary=(hop_index == 0))
            body = self._build_request_body(
                hop, messages, tools, tool_choice, stream=False, include_usage=False
            )
            price_snapshot = _capture_price_snapshot(hop.endpoint_id, hop.model)
            dynamic_timeout = self.config.compute_dynamic_timeout(body["messages"])
            max_attempts, base_delay, max_delay, total_budget = _retry_settings()
            attempt = 0
            fallback_used = False
            retry_started = _retry_now()
            has_failed_once = False
            last_llm_err = None
            hop_failed = False
            while True:
                # —— 现有内层重试循环主体，唯一差异：body["model"] 初始为 hop.model ——
                ...
                except LLMError as llm_err:
                    ...  # 现有重试/fallback 逻辑；最终 raise 处改为 hop_failed = True; break
            if not hop_failed:
                self._record_hop_health(hop, True)
                break
            self._record_hop_health(hop, False, last_llm_err.type.value)
            hop_errors.append(
                f"{hop.endpoint_name or hop.endpoint_id or hop.base_url}: "
                f"{last_llm_err.message}"
            )
            if last_llm_err is not None and self._should_failover(last_llm_err) \
                    and hop_index + 1 < len(hops):
                next_hop = hops[hop_index + 1]
                try:
                    from backend.services.endpoint_health import get_health_registry
                    get_health_registry().record_failover(hop.endpoint_id)
                except Exception:  # noqa: BLE001
                    pass
                if failover_callback:
                    failover_callback(FailoverEvent(
                        from_endpoint=hop.endpoint_id,
                        from_endpoint_name=hop.endpoint_name,
                        to_endpoint=next_hop.endpoint_id,
                        to_endpoint_name=next_hop.endpoint_name,
                        reason=last_llm_err.type.value,
                        hop_index=hop_index,
                        total_hops=len(hops),
                    ))
                hop_index += 1
                continue
            if last_llm_err is not None and len(hops) > 1:
                raise LLMError(
                    last_llm_err.type,
                    f"{last_llm_err.message}（已尝试 {len(hops)} 个端点："
                    + "；".join(hop_errors) + "）",
                    status_code=last_llm_err.status_code,
                    retry_after=last_llm_err.retry_after,
                )
            raise last_llm_err
```

usage 记录使用 `hop.endpoint_id` / `body["model"]`；`chat()` 签名增加
`failover_callback: Optional[Callable[[FailoverEvent], None]] = None`。

- [ ] **Step 4: 运行新测试与回归**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_failover.py backend/tests/unit/test_llm_client_fallback.py backend/tests/unit/test_llm_retry.py backend/tests/unit/test_retry_resilience.py -q
```
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/core/legacy/llm_client.py backend/tests/unit/test_llm_client_failover.py
git commit -m "feat(failover): non-streaming endpoint failover in LLMClient"
```

---

### Task 5: LLMClient 流式跨端点故障转移

**Files:**
- Modify: `backend/core/legacy/llm_client.py`（`_chat_stream_events_raw`）
- Modify: `backend/tests/unit/test_llm_client_failover.py`（追加流式用例）

**Interfaces:**
- Produces: 流式事件 `("failover", FailoverEvent)`；首字前失败可跨跳，首字后不跨跳。

- [ ] **Step 1: 写失败测试**

```python
def _stream_ok(lines):
    class _Ctx:
        async def __aenter__(self):
            resp = AsyncMock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            resp.aiter_lines = lambda: _lines()
            return resp
        async def __aexit__(self, *args):
            return False
    async def _lines():
        for line in lines:
            yield line
    return _Ctx()


@pytest.mark.asyncio()
async def test_stream_fails_over_before_first_delta():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.stream = Mock(side_effect=httpx.ConnectError("down"))
    backup.stream = Mock(return_value=_stream_ok([
        'data: {"model":"m1","choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]))
    events = []
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        async for event in client.chat_stream_events([{"role": "user", "content": "hi"}]):
            events.append(event)
    kinds = [kind for kind, _ in events]
    assert "failover" in kinds
    assert ("content_delta", "ok") in events

@pytest.mark.asyncio()
async def test_stream_does_not_failover_after_first_delta():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()

    class _BrokenCtx:
        async def __aenter__(self):
            resp = AsyncMock()
            resp.status_code = 200
            resp.raise_for_status = Mock()
            async def _lines():
                yield 'data: {"model":"m1","choices":[{"delta":{"content":"partial"}}]}'
                raise httpx.ReadError("cut")
            resp.aiter_lines = lambda: _lines()
            return resp
        async def __aexit__(self, *args):
            return False

    primary.stream = Mock(return_value=_BrokenCtx())
    backup.stream = Mock(return_value=_stream_ok(["data: [DONE]"]))
    with patch.object(client, "_get_client", return_value=primary), \
         patch.object(client, "_get_client_for_hop", return_value=backup):
        with pytest.raises(LLMError):
            async for _ in client.chat_stream_events([{"role": "user", "content": "hi"}]):
                pass
    assert backup.stream.call_count == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_failover.py -k stream -q`
Expected: FAIL。

- [ ] **Step 3: 实现**

`_chat_stream_events_raw` 同样改为外层 hop 循环：body 通过
`_build_request_body(hop, messages, tools, tool_choice, stream=True, include_usage=True)`
构建；内层现有 while 保留。`nothing_yielded` 判定时：

- 若可跨跳：`_record_hop_health(hop, False, llm_err.type.value)`、`record_failover`、
  `yield ("failover", FailoverEvent(...))`，重置 `aggregator/content_parts/
  reasoning_parts/finish_reason/stream_usage`，`hop_index += 1; continue`；
- 若不可跨跳（已出首字或最后一跳）：`_record_hop_health(hop, False, ...)` 后 raise；
- 成功结束：`_record_hop_health(hop, True)`；usage 记录使用 `hop.endpoint_id`。

- [ ] **Step 4: 运行流式相关全部测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_failover.py backend/tests/unit/test_llm_client_stream_errors.py backend/tests/unit/test_llm_client_fallback.py backend/tests/unit/test_agent_retry_visibility.py -q
```
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/core/legacy/llm_client.py backend/tests/unit/test_llm_client_failover.py
git commit -m "feat(failover): streaming endpoint failover before first delta"
```

---

### Task 6: 健康探测服务与 lifespan 装配

**Files:**
- Create: `backend/services/endpoint_probe.py`
- Create: `backend/tests/unit/test_endpoint_probe.py`
- Modify: `backend/main.py`（lifespan 启停探测任务）

**Interfaces:**
- Produces: `probe_endpoint(endpoint, *, client=None) -> str`（`"success"|"failure"|"reachable"`）、`run_endpoint_probe_loop(stop_event=None)`、`start_endpoint_probe_task() -> asyncio.Task`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_endpoint_probe.py
# ruff: noqa: UP006, UP007, UP035, UP045 — py38 兼容
import httpx
import pytest

from backend.services.endpoint_health import FAILED, HEALTHY, get_health_registry, reset_health_registry
from backend.services.endpoint_probe import probe_endpoint

pytestmark = pytest.mark.unit

@pytest.fixture(autouse=True)
def _clean():
    reset_health_registry()
    yield
    reset_health_registry()

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))

@pytest.mark.asyncio()
async def test_404_is_reachable_not_failure():
    reg = get_health_registry()
    reg.record_failure("ep1", "timeout")
    async with _client(lambda req: httpx.Response(404)) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "reachable"
    assert reg.get("ep1").status == FAILED  # 状态未被改动

@pytest.mark.asyncio()
async def test_success_restores_health():
    reg = get_health_registry()
    reg.record_failure("ep1", "timeout")
    reg.record_failure("ep1", "timeout")
    async with _client(lambda req: httpx.Response(200, json={"data": []})) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "success"
    assert reg.get("ep1").status == HEALTHY

@pytest.mark.asyncio()
async def test_500_records_failure():
    reg = get_health_registry()
    async with _client(lambda req: httpx.Response(500)) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "failure"
    assert reg.get("ep1").consecutive_failures == 1

@pytest.mark.asyncio()
async def test_ollama_uses_api_tags():
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={})
    async with _client(handler) as client:
        await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "ollama"}, client=client
        )
    assert seen["path"] == "/api/tags"
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_probe.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
# backend/services/endpoint_probe.py
"""Lightweight background probes for degraded/failed LLM endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.services.endpoint_health import (
    DEGRADED,
    FAILED,
    get_health_registry,
    load_failover_config,
)

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 5.0
_SLEEP_CHUNK_S = 30.0


def _probe_url(endpoint: Dict[str, Any]) -> Optional[str]:
    base_url = endpoint.get("baseUrl")
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    base = base_url.rstrip("/")
    if (endpoint.get("protocol") or "openai-compatible") == "ollama":
        return f"{base}/api/tags"
    return f"{base}/models"


async def probe_endpoint(
    endpoint: Dict[str, Any],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Probe one endpoint; returns ``success`` / ``failure`` / ``reachable``."""
    endpoint_id = endpoint.get("id")
    url = _probe_url(endpoint)
    if not url:
        return "failure"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_S))
    headers: Dict[str, str] = {}
    api_key = endpoint.get("apiKey")
    if isinstance(api_key, str) and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    registry = get_health_registry()
    try:
        response = await client.get(url, headers=headers)
        status = response.status_code
        if status < 400:
            registry.record_success(endpoint_id)
            return "success"
        if status in (403, 404, 405):
            logger.debug("probe: endpoint %s reachable but %s not supported", endpoint_id, url)
            return "reachable"
        registry.record_failure(endpoint_id, "probe")
        return "failure"
    except Exception as exc:  # noqa: BLE001 — probe failure is data, not an error
        logger.debug("probe: endpoint %s failed: %s", endpoint_id, exc)
        registry.record_failure(endpoint_id, "probe")
        return "failure"
    finally:
        if owns_client:
            await client.aclose()


def _load_probe_candidates() -> List[Dict[str, Any]]:
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        settings = to_camel(raw) if isinstance(raw, dict) else {}
        endpoints = settings.get("endpoints") or []
        return [ep for ep in endpoints if isinstance(ep, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.debug("probe: settings unavailable: %s", exc)
        return []


async def run_endpoint_probe_loop(stop_event: Optional[asyncio.Event] = None) -> None:
    """Probe degraded/failed endpoints every ``failover.probeIntervalMs``."""
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        config = load_failover_config()
        registry = get_health_registry()
        registry.configure(
            threshold=config.consecutive_fail_threshold,
            cooldown_s=config.cooldown_ms / 1000.0,
        )
        if config.enabled:
            for endpoint in _load_probe_candidates():
                endpoint_id = endpoint.get("id")
                if not isinstance(endpoint_id, str):
                    continue
                state = registry.get(endpoint_id)
                if state.status not in (DEGRADED, FAILED):
                    continue
                await probe_endpoint(endpoint)
        remaining = config.probe_interval_ms / 1000.0
        while remaining > 0 and not stop_event.is_set():
            chunk = min(_SLEEP_CHUNK_S, remaining)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=chunk)
            except asyncio.TimeoutError:
                pass
            remaining -= chunk


def start_endpoint_probe_task() -> asyncio.Task:
    return asyncio.create_task(run_endpoint_probe_loop(), name="endpoint-probe")
```

- [ ] **Step 4: lifespan 装配（main.py）**

```python
    # 端点健康探测：仅探测 degraded/failed 端点，不消耗 token。
    endpoint_probe_task = start_endpoint_probe_task()
    app.state.endpoint_probe_task = endpoint_probe_task
```

（放在 `_deferred_task = asyncio.create_task(...)` 之前；`start_endpoint_probe_task`
从 `backend.services.endpoint_probe` 顶部导入。）

`yield` 之后：

```python
    endpoint_probe_task.cancel()
    with suppress(asyncio.CancelledError):
        await endpoint_probe_task
```

- [ ] **Step 5: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_probe.py -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/services/endpoint_probe.py backend/tests/unit/test_endpoint_probe.py backend/main.py
git commit -m "feat(failover): background health probes for failed endpoints"
```

---

### Task 7: 健康状态 API

**Files:**
- Create: `backend/api/endpoint_health_routes.py`
- Create: `backend/tests/unit/test_endpoint_health_routes.py`
- Modify: `backend/main.py`（挂载路由）

**Interfaces:**
- Produces: `GET /api/v1/endpoints/health` → `{"endpoints": [...]}`；`build_health_payload() -> Dict[str, Any]`（可单测）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_endpoint_health_routes.py
from unittest.mock import patch

from backend.api.endpoint_health_routes import build_health_payload
from backend.services.endpoint_health import get_health_registry, reset_health_registry

def test_payload_lists_configured_endpoints_with_health():
    reset_health_registry()
    get_health_registry().record_failure("ep1", "timeout")
    with patch(
        "backend.api.endpoint_health_routes._configured_endpoint_ids",
        return_value=["ep1", "ep2"],
    ):
        payload = build_health_payload()
    by_id = {row["endpointId"]: row for row in payload["endpoints"]}
    assert by_id["ep1"]["status"] == "degraded"
    assert by_id["ep2"]["status"] == "healthy"
    reset_health_registry()
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_health_routes.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现与挂载**

```python
# backend/api/endpoint_health_routes.py
"""Endpoint health snapshot API used by the settings UI."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from backend.services.endpoint_health import get_health_registry

router = APIRouter(tags=["endpoints"])


def _configured_endpoint_ids() -> List[str]:
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        settings = to_camel(raw) if isinstance(raw, dict) else {}
        endpoints = settings.get("endpoints") or []
        return [
            ep["id"]
            for ep in endpoints
            if isinstance(ep, dict) and isinstance(ep.get("id"), str)
        ]
    except Exception:  # noqa: BLE001 — health API degrades to empty list
        return []


def build_health_payload() -> Dict[str, Any]:
    return {
        "endpoints": get_health_registry().snapshot(_configured_endpoint_ids())
    }


@router.get("/endpoints/health")
def get_endpoints_health() -> Dict[str, Any]:
    return build_health_payload()
```

`main.py`：

```python
from backend.api.endpoint_health_routes import router as endpoint_health_router
...
app.include_router(endpoint_health_router, prefix="/api/v1")
```

- [ ] **Step 4: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_health_routes.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/api/endpoint_health_routes.py backend/tests/unit/test_endpoint_health_routes.py backend/main.py
git commit -m "feat(failover): expose endpoint health API"
```

---

### Task 8: 聊天链路 failover 事件（agent + 前端横幅）

**Files:**
- Modify: `backend/core/legacy/agent.py`（`run_loop` 流式事件映射）
- Modify: `src/shared/api/types/chatAndEventTypes.ts`（`RetryInfo` 扩展）
- Modify: `src/widgets/chat/RetryBanner.tsx`
- Create: `backend/tests/unit/test_agent_failover_event.py`
- Create: `src/widgets/chat/__tests__/RetryBanner.failover.test.tsx`（若目录不存在则放在现有 RetryBanner 测试同目录）

**Interfaces:**
- Consumes: `FailoverEvent`（Task 4/5）。
- Produces: `retry_info.kind = "failover"`、`from_endpoint/to_endpoint/from_endpoint_name/to_endpoint_name`。

- [ ] **Step 1: 后端测试**

```python
# backend/tests/unit/test_agent_failover_event.py
from backend.core.legacy.llm_client import FailoverEvent
from backend.core.legacy.agent import _failover_retry_info

def test_failover_event_maps_to_retry_info():
    info = _failover_retry_info(FailoverEvent(
        from_endpoint="ep1", from_endpoint_name="Primary",
        to_endpoint="ep2", to_endpoint_name="Backup",
        reason="timeout", hop_index=0, total_hops=2,
    ))
    assert info["kind"] == "failover"
    assert info["from_endpoint_name"] == "Primary"
    assert info["to_endpoint_name"] == "Backup"
    assert info["error_type"] == "timeout"
```

- [ ] **Step 2: 实现 agent 映射**

在 `agent.py` 的 `_retry_info_from_event` 附近新增：

```python
def _failover_retry_info(event: Any) -> Dict[str, Any]:
    """FailoverEvent → 前端 retry_info 载荷（state=retry, kind=failover）。"""
    return {
        "kind": "failover",
        "attempt": 0,
        "max_attempts": 0,
        "error_type": getattr(event, "reason", "unknown"),
        "error_message": "",
        "delay": 0,
        "from_endpoint": getattr(event, "from_endpoint", None),
        "to_endpoint": getattr(event, "to_endpoint", None),
        "from_endpoint_name": getattr(event, "from_endpoint_name", None),
        "to_endpoint_name": getattr(event, "to_endpoint_name", None),
        "hop_index": getattr(event, "hop_index", 0),
        "total_hops": getattr(event, "total_hops", 0),
    }
```

事件循环中紧跟 `elif evt_kind == "retry":` 分支之后加：

```python
                                    elif evt_kind == "failover":
                                        yield AgentEvent(
                                            state=AgentState.RETRY,
                                            iteration=i,
                                            retry_info=_failover_retry_info(payload),
                                            agent_id=self.agent_id,
                                        )
```

- [ ] **Step 3: 前端类型与横幅**

```ts
// chatAndEventTypes.ts RetryInfo 内追加：
  /** 2026-11-26: failover = 端点切换提示（无倒计时/尝试次数语义） */
  kind?: 'retry' | 'failover';
  from_endpoint?: string | null;
  to_endpoint?: string | null;
  from_endpoint_name?: string | null;
  to_endpoint_name?: string | null;
  hop_index?: number;
  total_hops?: number;
```

`RetryBanner.tsx` 在组件顶部判定（按现有 props 名称调整）：

```tsx
if (retryInfo.kind === 'failover') {
  const from = retryInfo.from_endpoint_name || retryInfo.from_endpoint || '主端点';
  const to = retryInfo.to_endpoint_name || retryInfo.to_endpoint || '备用端点';
  return (
    <div
      data-testid="failover-banner"
      className="flex items-center gap-2 text-xs text-amber-600"
    >
      <span>已自动切换到端点「{to}」</span>
      <span className="text-muted">（{from} 失败：{retryInfo.error_type}）</span>
    </div>
  );
}
```

（若组件使用 i18n，新增键 `chat.retry.failover_switched` / `failover_reason`，zh/en 同步。）

- [ ] **Step 4: 前端测试**

```tsx
// RetryBanner.failover.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RetryBanner } from '../RetryBanner';

describe('RetryBanner failover', () => {
  it('renders endpoint switch notice without countdown', () => {
    render(<RetryBanner retryInfo={{
      kind: 'failover', attempt: 0, max_attempts: 0,
      error_type: 'timeout', error_message: '', delay: 0,
      from_endpoint_name: 'Primary', to_endpoint_name: 'Backup',
    }} />);
    expect(screen.getByTestId('failover-banner')).toBeTruthy();
    expect(screen.getByText(/Backup/)).toBeTruthy();
  });
});
```

- [ ] **Step 5: 运行测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_failover_event.py -q
npx vitest run src/widgets/chat/__tests__/RetryBanner.failover.test.tsx
```

- [ ] **Step 6: Commit**

```bash
git add backend/core/legacy/agent.py backend/tests/unit/test_agent_failover_event.py src/shared/api/types/chatAndEventTypes.ts src/widgets/chat/RetryBanner.tsx src/widgets/chat/__tests__/RetryBanner.failover.test.tsx
git commit -m "feat(failover): surface endpoint switch events in chat retry banner"
```

---

### Task 9: 设置页（优先级排序 + 故障转移配置 + 健康状态）

**Files:**
- Create: `src/features/manage-endpoints/useEndpointHealth.ts`
- Modify: `src/features/manage-endpoints/api.ts`（`getEndpointHealth`）
- Create: `src/pages/settings/components/EndpointFailoverSection.tsx`
- Create: `src/pages/settings/components/EndpointEditors.tsx`（从 EndpointsTab 拆出 `ProbeStatusDisplay` 与 `QuotaEditor`）
- Create: `src/pages/settings/endpointPriority.ts`（纯函数 `moveEndpoint`，可测）
- Modify: `src/pages/settings/EndpointsTab.tsx`
- Modify: `src/shared/lib/i18n/locales/zh/settingsUi.ts`、`src/shared/lib/i18n/locales/en/settingsUi.ts`
- Create: `src/tests/endpointPriority.test.ts`

**Interfaces:**
- Produces: `moveEndpoint(endpoints, index, direction) -> EndpointConfig[]`（重排后 priority 1..N）；`useEndpointHealth(enabled) -> Record<string, EndpointHealthRow>`；`EndpointFailoverSection({settings, updateSettings})`。

- [ ] **Step 1: 写排序纯函数测试**

```ts
// src/tests/endpointPriority.test.ts
import { describe, expect, it } from 'vitest';
import { moveEndpoint } from '../pages/settings/endpointPriority';
import type { EndpointConfig } from '../entities/setting/types';

const ep = (id: string): EndpointConfig => ({
  id, name: id, baseUrl: '', apiKey: '', protocol: 'openai-compatible',
  modelId: '', localModelPath: '', discoveredModels: [], lastDiscoveredAt: null,
  reasoningEffort: null, thinkingBudget: null,
});

describe('moveEndpoint', () => {
  it('swaps neighbors and renumbers priorities', () => {
    const moved = moveEndpoint([ep('a'), ep('b'), ep('c')], 1, -1);
    expect(moved.map((e) => e.id)).toEqual(['b', 'a', 'c']);
    expect(moved.map((e) => e.priority)).toEqual([1, 2, 3]);
  });
  it('is a no-op at boundaries', () => {
    const input = [ep('a'), ep('b')];
    expect(moveEndpoint(input, 0, -1).map((e) => e.id)).toEqual(['a', 'b']);
    expect(moveEndpoint(input, 1, 1).map((e) => e.id)).toEqual(['a', 'b']);
  });
});
```

- [ ] **Step 2: 实现纯函数**

```ts
// src/pages/settings/endpointPriority.ts
import type { EndpointConfig } from '../../entities/setting/types';

export function moveEndpoint(
  endpoints: EndpointConfig[],
  index: number,
  direction: -1 | 1,
): EndpointConfig[] {
  const target = index + direction;
  if (index < 0 || index >= endpoints.length || target < 0 || target >= endpoints.length) {
    return endpoints.map((ep, i) => ({ ...ep, priority: i + 1 }));
  }
  const next = [...endpoints];
  [next[index], next[target]] = [next[target], next[index]];
  return next.map((ep, i) => ({ ...ep, priority: i + 1 }));
}
```

- [ ] **Step 3: 健康 API 客户端与 hook**

```ts
// api.ts
export interface EndpointHealthRow {
  endpointId: string;
  status: 'healthy' | 'degraded' | 'failed';
  consecutiveFailures: number;
  lastFailureAt: number | null;
  lastSuccessAt: number | null;
  lastFailureReason: string | null;
  failoverCount: number;
}

export async function getEndpointHealth(): Promise<EndpointHealthRow[]> {
  const res = await fetch('/api/v1/endpoints/health', {
    headers: authHeaders(),  // 复用该文件现有鉴权头辅助（实现时按现有模式）
  });
  if (!res.ok) throw new Error(`health ${res.status}`);
  const data = await res.json();
  return Array.isArray(data?.endpoints) ? data.endpoints : [];
}
```

```ts
// useEndpointHealth.ts
import { useEffect, useState } from 'react';
import { getEndpointHealth, type EndpointHealthRow } from './api';

export function useEndpointHealth(enabled: boolean): Record<string, EndpointHealthRow> {
  const [rows, setRows] = useState<Record<string, EndpointHealthRow>>({});
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = () => {
      void getEndpointHealth()
        .then((list) => {
          if (!cancelled) {
            setRows(Object.fromEntries(list.map((row) => [row.endpointId, row])));
          }
        })
        .catch(() => {});
    };
    load();
    const timer = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);
  return rows;
}
```

- [ ] **Step 4: 拆出编辑器组件降低行数**

把 `EndpointsTab.tsx` 中 `ProbeStatusDisplay` 与 `QuotaEditor` 原样移到
`src/pages/settings/components/EndpointEditors.tsx`（导出两者），EndpointsTab 改为导入。
完成后 `wc -l src/pages/settings/EndpointsTab.tsx` 应降到约 620 行。

- [ ] **Step 5: 故障转移设置组件**

```tsx
// EndpointFailoverSection.tsx
import { DEFAULT_FAILOVER_SETTINGS, type FailoverSettings } from '../../../entities/setting/types';

interface Props {
  settings: { failover: FailoverSettings };
  updateSettings: (partial: { failover?: FailoverSettings }) => void;
}

export function EndpointFailoverSection({ settings, updateSettings }: Props) {
  const value = settings.failover ?? DEFAULT_FAILOVER_SETTINGS;
  const patch = (partial: Partial<FailoverSettings>) =>
    updateSettings({ failover: { ...value, ...partial } });
  return (
    <div data-testid="endpoint-failover-section" className="p-4 border rounded-radius-sm bg-surface space-y-3">
      <label className="flex items-center gap-2 text-sm text-text">
        <input
          type="checkbox"
          data-testid="failover-enabled"
          checked={value.enabled}
          onChange={(e) => patch({ enabled: e.target.checked })}
        />
        启用端点故障转移
      </label>
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
        <label className="flex items-center gap-1">
          探测间隔（分钟）
          <input type="number" min={0.5} step={0.5}
            disabled={!value.enabled}
            value={value.probeIntervalMs / 60_000}
            onChange={(e) => patch({ probeIntervalMs: Math.round(Number(e.target.value) * 60_000) })}
            className="w-20 px-2 py-1 border border-border rounded-radius-sm bg-surface text-text" />
        </label>
        <label className="flex items-center gap-1">
          冷却期（秒）
          <input type="number" min={5} step={5}
            disabled={!value.enabled}
            value={value.cooldownMs / 1000}
            onChange={(e) => patch({ cooldownMs: Math.round(Number(e.target.value) * 1000) })}
            className="w-20 px-2 py-1 border border-border rounded-radius-sm bg-surface text-text" />
        </label>
        <label className="flex items-center gap-1">
          失败阈值
          <input type="number" min={1} max={10}
            disabled={!value.enabled}
            value={value.consecutiveFailThreshold}
            onChange={(e) => patch({ consecutiveFailThreshold: Math.round(Number(e.target.value)) })}
            className="w-16 px-2 py-1 border border-border rounded-radius-sm bg-surface text-text" />
        </label>
      </div>
    </div>
  );
}
```

（实现时按项目 i18n 规范把中文文案改为 `settings.endpoints.failover.*` 键，zh/en 同步添加。）

- [ ] **Step 6: 接入 EndpointsTab**

- 顶部（标题之后）渲染 `<EndpointFailoverSection settings={settings} updateSettings={updateSettings} />`；
- `const health = useEndpointHealth(settings.failover?.enabled === true);`
- 每行标题左侧加：

```tsx
<span className="text-[11px] px-1.5 py-0.5 rounded bg-bg-muted text-muted">
  P{ep.priority ?? '—'}
</span>
{health[ep.id] && (
  <span
    data-testid={`endpoint-health-${ep.id}`}
    className={clsx(
      'w-2 h-2 rounded-full',
      health[ep.id].status === 'healthy' && 'bg-green-500',
      health[ep.id].status === 'degraded' && 'bg-amber-500',
      health[ep.id].status === 'failed' && 'bg-red-500',
    )}
    title={`${health[ep.id].status}${health[ep.id].lastFailureReason ? ` · ${health[ep.id].lastFailureReason}` : ''}`}
  />
)}
```

- 每行操作区加向上/向下按钮：

```tsx
<button
  disabled={index === 0}
  onClick={() => updateSettings({ endpoints: moveEndpoint(settings.endpoints, index, -1) })}
  className="text-xs text-muted hover:text-text disabled:opacity-30"
  data-testid={`endpoint-up-${ep.id}`}
>↑</button>
<button
  disabled={index === settings.endpoints.length - 1}
  onClick={() => updateSettings({ endpoints: moveEndpoint(settings.endpoints, index, 1) })}
  className="text-xs text-muted hover:text-text disabled:opacity-30"
  data-testid={`endpoint-down-${ep.id}`}
>↓</button>
```

- `handleAdd` 中新端点设置 `priority: settings.endpoints.length + 1`。
- `settings.endpoints.map((ep) =>` 改为 `settings.endpoints.map((ep, index) =>`。

- [ ] **Step 7: 运行前端测试与类型检查**

```bash
npx vitest run src/tests/endpointPriority.test.ts src/tests/settingsFailoverFields.test.ts
npx tsc --noEmit
```

- [ ] **Step 8: Commit**

```bash
git add src/features/manage-endpoints/api.ts src/features/manage-endpoints/useEndpointHealth.ts src/pages/settings/components/EndpointFailoverSection.tsx src/pages/settings/components/EndpointEditors.tsx src/pages/settings/endpointPriority.ts src/pages/settings/EndpointsTab.tsx src/shared/lib/i18n/locales/zh/settingsUi.ts src/shared/lib/i18n/locales/en/settingsUi.ts src/tests/endpointPriority.test.ts
git commit -m "feat(failover): endpoint priority controls, failover settings and health badges"
```

---

### Task 10: 文档、全量验证与收尾

**Files:**
- Create: `docs/technical/XX-endpoint-failover.md`（编号按当时 README 尾部顺延）
- Modify: `docs/technical/README.md`（章节目录）
- Delete after merge: `docs/plans/2026-11-26_endpoint-failover.md`

- [ ] **Step 1: 写技术文档**：数据模型、触发语义（含流式契约）、健康状态机、探测与 failback、API 契约、UI 入口、测试与排障（如何判断为什么切换）。
- [ ] **Step 2: 更新 README 章节表**。
- [ ] **Step 3: 全量验证**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_endpoint_health.py backend/tests/unit/test_endpoint_probe.py backend/tests/unit/test_llm_factory_failover.py backend/tests/unit/test_llm_client_failover.py backend/tests/unit/test_endpoint_health_routes.py backend/tests/unit/test_agent_failover_event.py backend/tests/contract/test_settings_schema_parity.py backend/tests/unit/test_settings_failover_fields.py -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_fallback.py backend/tests/unit/test_llm_retry.py backend/tests/unit/test_retry_resilience.py backend/tests/unit/test_llm_client_stream_errors.py -q
npx vitest run src/tests/endpointPriority.test.ts src/tests/settingsFailoverFields.test.ts
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/services/endpoint_health.py backend/services/endpoint_probe.py backend/api/endpoint_health_routes.py backend/orchestration/llm_factory.py backend/core/legacy/llm_client.py
npm run build
```

- [ ] **Step 4: 架构棘轮/行数守卫**

```bash
wc -l src/pages/settings/EndpointsTab.tsx
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/architecture -q
```

（若仓库无 `backend/tests/architecture`，跑 CI 中对应的 ratchet 测试文件。）

- [ ] **Step 5: Commit 文档**

```bash
git add docs/technical/ docs/plans/2026-11-26_endpoint-failover.md docs/superpowers/specs/2026-11-26-endpoint-failover-design.md
git commit -m "docs(failover): archive endpoint failover technical guide"
```

- [ ] **Step 6: 推送与 PR**（用户已授权实施；按项目 feature 分支流程）

```bash
git push -u origin feat/endpoint-failover-priority
gh pr create --base main --head feat/endpoint-failover-priority \
  --title "feat(failover): endpoint priority failover with health monitoring" \
  --body "实现设计见 docs/superpowers/specs/2026-11-26-endpoint-failover-design.md。默认关闭；仅聊天链路。"
```

---

## Self-Review

- **Spec coverage**：数据模型（T1）、健康状态机（T2）、构链（T3）、非流式（T4）、流式（T5）、探测与 lifespan（T6）、health API（T7）、事件与横幅（T8）、设置页 UI（T9）、文档与验证（T10）。
- **Placeholder scan**：无 TBD；所有测试与实现均给出代码或明确修改点。`chat()` 的内层重试循环保持原文，仅改 raise→跳出与外层 hop 循环，实现时按 Step 3 的「实现说明」逐段替换。
- **Type consistency**：`EndpointHop` 字段（endpoint_id/endpoint_name/base_url/api_key/provider/model/fallback_model/reasoning_effort/thinking_budget）在 T3 创建、T4/T5 消费；`FailoverEvent` 字段在 T4 定义、T8 映射；`retry_info.kind="failover"` 前后端一致。
- **已知实现注意**：`usage_tracker` 为模块级单例，测试需 `monkeypatch.setattr` 到实际引用点（`backend.services.usage_tracker.usage_tracker` 在 llm_client 内是函数内导入，打桩路径以实现时所见为准）；`compute_dynamic_timeout` 仍用主模型估算（跨跳模型差异对超时影响可接受）。
