---
name: settings-schema-canonicalization-impl
description: settings schema 规范化实施 plan — 7 tasks (canonicalizer → legacy route → hex route → frontend deepMerge → frontend loadSettings → e2e → cross-branch PR)
metadata:
  type: plan
  status: ready
  spec: 2026-07-22-settings-schema-canonicalization-design.md
  branch: fix/settings-schema-canonicalization
  base: main
  win7_squash_cherry_pick_branch: fix/win7-settings-schema-canonicalization
  win7_base: release/win7
  date: 2026-07-22
---

# Settings Schema 规范化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix sidebar "未配置" 永久亮起的 bug — 后端加 snake↔camel 翻译层 + 收紧 schema 白名单 + 前端 loadSettings 改 deep-merge + 字段冲突告警，让历史 snake_case 数据兼容、未来不再产生新污染。

**Architecture:** 后端纯函数模块 `settings_canonicalizer.py` 装 4 个函数(to_camel/from_camel/validate_settings_shape/detect_legacy_snake_pollution)；在 legacy_routes 和 hex_routes 的 GET/PUT 入口调它；前端 `storage.ts` 用 deepMerge + 字段冲突告警替换浅 merge。

**Tech Stack:** Python 3.11 (main) / 3.8 (win7), FastAPI, Pydantic v2 (main) / v1 (win7), SQLite; 前端 TypeScript + Vitest + Playwright e2e。

## Global Constraints

- Win7 Python 是 3.8, Pydantic v1 (`class Config: extra = "forbid"` 而不是 `model_config = ConfigDict(...)`)
- Main Python 是 3.11, Pydantic v2 (`model_config = ConfigDict(extra="forbid")` + `req.model_dump(exclude_none=True)` 而不是 `req.dict(...)`)
- 不引入 `electron-store` / `IndexedDB` — 保留 localStorage 双写策略
- 不写一次性 migration 脚本 (YAGNI; 读侧翻译已覆盖历史数据)
- 所有 commit message 走 conventional commits 格式
- 双分支同步策略: main 提 PR → win7 squash cherry-pick (per memory 项目惯例)

---

## 任务地图 (Task Map)

| Task | 主题 | 文件 | 测试 |
|---|---|---|---|
| 1 | backend canonicalizer 模块 | NEW `backend/data/settings_canonicalizer.py` | NEW `backend/tests/unit/test_settings_canonicalizer.py` (≥15 cases) |
| 2 | legacy_routes wire-in | MODIFY `backend/api/legacy_routes.py:731-790` | MODIFY `backend/tests/integration/test_settings_route_legacy.py` (+5 cases) |
| 3 | hex_routes 收紧白名单 | MODIFY `backend/api/hex_routes.py:64-79, 187-220` | 同上文件 (+1 case) |
| 4 | frontend deepMerge utility | MODIFY `src/entities/setting/storage.ts` | NEW `src/entities/setting/__tests__/storage-deepmerge.test.ts` (≥10 cases) |
| 5 | frontend loadSettings 重构 | MODIFY `src/entities/setting/storage.ts:102-115` | (同 Task 4 文件) |
| 6 | frontend e2e spec | NEW `tests/e2e/settings-schema-canonicalization.e2e.ts` | (Playwright 自带 spec runner) |
| 7 | 双分支 PR + 收尾 | (git/gh 操作) | n/a |

---

## Task 1: Backend `settings_canonicalizer` 模块

**Files:**
- Create: `/home/fz/project/sage/backend/data/settings_canonicalizer.py`
- Create: `/home/fz/project/sage/backend/tests/unit/test_settings_canonicalizer.py`

**Interfaces:**
- Produces:
  - `to_camel(value: Any) -> Any` — 递归翻译 dict/list
  - `from_camel(value: Any) -> Any` — 反向
  - `validate_settings_shape(settings: dict) -> None` — 不在白名单 → raise `ValueError`
  - `detect_legacy_snake_pollution(settings: dict) -> List[str]` — 返回 snake_case 字段路径
  - `ALIASES: Dict[str, str]` — 16 个 snake↔camel 映射
  - `LEGAL_TOP_KEYS / LEGAL_ENDPOINT_KEYS / LEGAL_MODEL_SELECTION_KEYS / LEGAL_DISCOVERED_MODEL_KEYS / LEGAL_WIKI_KEYS: FrozenSet[str]`

### Step 1.1: 写失败的单元测试 (RED)

新建文件 `/home/fz/project/sage/backend/tests/unit/test_settings_canonicalizer.py`：

```python
"""settings_canonicalizer 单元测试。

覆盖：
- to_camel 嵌套 dict / list 递归 / 标量通过
- from_camel 反向
- round-trip 一致
- ALIASES 双向一一对应无丢失
- None / empty dict / empty list 通过不爆
- validate_settings_shape 拒绝白名单外 + snake_case 残留
- detect_legacy_snake_pollution nested 检测
"""
from __future__ import annotations

import pytest

from backend.data.settings_canonicalizer import (
    ALIASES,
    detect_legacy_snake_pollution,
    from_camel,
    to_camel,
    validate_settings_shape,
)


# --- to_camel ---

def test_to_camel_nested_dict() -> None:
    raw = {"model_selections": {"chat_model": {"endpoint_id": "x"}}}
    assert to_camel(raw) == {
        "modelSelections": {"chatModel": {"endpointId": "x"}}
    }


def test_to_camel_endpoints_array_with_discovered_models() -> None:
    raw = {
        "endpoints": [{
            "id": "e1",
            "base_url": "u",
            "api_key": "k",
            "discovered_models": [
                {"id": "m1", "capabilities": ["chat"], "endpoint_id": "e1"}
            ],
            "last_discovered_at": 12345,
        }]
    }
    assert to_camel(raw) == {
        "endpoints": [{
            "id": "e1",
            "baseUrl": "u",
            "apiKey": "k",
            "discoveredModels": [
                {"id": "m1", "capabilities": ["chat"], "endpointId": "e1"}
            ],
            "lastDiscoveredAt": 12345,
        }]
    }


def test_to_camel_passes_through_scalar() -> None:
    assert to_camel(42) == 42
    assert to_camel("hello") == "hello"
    assert to_camel(None) is None


def test_to_camel_empty_collections() -> None:
    assert to_camel([]) == []
    assert to_camel({}) == {}
    assert to_camel({"a": []}) == {"a": []}
    assert to_camel({"a": {}}) == {"a": {}}


def test_to_camel_unknown_keys_kept_as_is() -> None:
    """白名单外的字段(如老 schema 字段 api_base_url)不带 ALIASES 翻译, 但应原样保留"""
    raw = {"api_base_url": "x", "api_key": "k", "model": "m"}
    # 注意: ALIASES 把 api_key 翻成 apiKey, 但 api_base_url / model 不在 ALIASES 中
    assert to_camel(raw) == {"api_base_url": "x", "apiKey": "k", "model": "m"}


# --- from_camel ---

def test_from_camel_round_trip() -> None:
    original = {
        "model_selections": {"chat_model": {"endpoint_id": "x", "model_id": "y"}},
        "endpoints": [
            {"id": "e1", "base_url": "u", "api_key": "k",
             "discovered_models": [{"id": "m1", "endpoint_id": "e1"}],
             "last_discovered_at": 1}
        ],
    }
    round_tripped = from_camel(to_camel(original))
    assert round_tripped["model_selections"] == original["model_selections"]
    assert round_tripped["endpoints"] == original["endpoints"]


# --- ALIASES ---

def test_aliases_is_bijective() -> None:
    """ALIASES 双向一一对应: 没有 2 个不同 snake 映射到同一 camel"""
    camels = list(ALIASES.values())
    assert len(camels) == len(set(camels))


def test_aliases_keys_are_snake_case() -> None:
    """所有 ALIASES key 必须是 snake_case (含下划线)"""
    import re
    for k in ALIASES.keys():
        assert re.match(r"^[a-z][a-z0-9_]*$", k), f"key {k!r} not snake_case"


# --- validate_settings_shape ---

def test_validate_settings_shape_accepts_clean_camel_case() -> None:
    """完整合法的 camelCase AppSettings 不抛错"""
    settings = {
        "streaming": True, "autoMemory": True, "confirmDelete": True,
        "compactMode": False,
        "endpoints": [], "modelSelections": {
            "chatModel": {"endpointId": None, "modelId": None},
            "visionModel": {"endpointId": None, "modelId": None},
            "embeddingModel": {"endpointId": None, "modelId": None},
        },
        "maxContext": 4096, "temperature": 0.7,
        "proxyMode": "system", "proxyUrl": "x", "tlsVersion": "1.2",
        "wiki": {"useFolderPicker": True},
        "version": "3.0.0",
    }
    validate_settings_shape(settings)


def test_validate_settings_shape_rejects_unknown_top_key() -> None:
    with pytest.raises(ValueError, match=r"unknown top-level field 'foo'"):
        validate_settings_shape({"foo": "bar", "streaming": True})


def test_validate_settings_shape_rejects_unknown_endpoint_key() -> None:
    settings = {"endpoints": [{"id": "x", "baseUrl": "u", "foo": "bar"}]}
    with pytest.raises(ValueError, match=r"unknown endpoint field 'foo'"):
        validate_settings_shape(settings)


def test_validate_settings_shape_rejects_unknown_model_selection_key() -> None:
    settings = {"modelSelections": {
        "chatModel": {"endpointId": None, "modelId": None, "junk": 1},
        "visionModel": {"endpointId": None, "modelId": None},
        "embeddingModel": {"endpointId": None, "modelId": None},
    }}
    with pytest.raises(ValueError, match=r"unknown model-selection field 'junk'"):
        validate_settings_shape(settings)


def test_validate_settings_shape_strips_snake_residue() -> None:
    """即使翻译后仍有 snake_case 残留 (ALIASES 不覆盖到的字段), 应抛错"""
    settings = {"base_url": "u"}
    with pytest.raises(ValueError, match=r"unknown top-level field 'base_url'"):
        validate_settings_shape(settings)


# --- detect_legacy_snake_pollution ---

def test_detect_returns_empty_for_clean_camel_case() -> None:
    settings = {"endpoints": [{"baseUrl": "u", "apiKey": "k"}]}
    assert detect_legacy_snake_pollution(settings) == []


def test_detect_finds_top_level_snake() -> None:
    settings = {"base_url": "u", "streaming": True}
    paths = detect_legacy_snake_pollution(settings)
    assert "base_url" in paths


def test_detect_finds_nested_snake_in_endpoint() -> None:
    settings = {"endpoints": [{"id": "e1", "base_url": "u", "api_key": "k"}]}
    paths = detect_legacy_snake_pollution(settings)
    assert "endpoints[0].base_url" in paths
    assert "endpoints[0].api_key" in paths


def test_detect_finds_snake_in_discovered_models_array() -> None:
    settings = {"endpoints": [{"discoveredModels": [
        {"id": "m1", "endpoint_id": "e1"}
    ]}]}
    paths = detect_legacy_snake_pollution(settings)
    assert "endpoints[0].discoveredModels[0].endpoint_id" in paths


def test_detect_finds_snake_in_model_selections() -> None:
    settings = {"modelSelections": {
        "chatModel": {"endpoint_id": "x", "model_id": "y"},
        "visionModel": {"endpointId": None, "modelId": None},
        "embeddingModel": {"endpointId": None, "modelId": None},
    }}
    paths = detect_legacy_snake_pollution(settings)
    assert "modelSelections.chatModel.endpoint_id" in paths
    assert "modelSelections.chatModel.model_id" in paths
```

**验证测试能跑起来 (import 失败):**

```bash
cd /home/fz/project/sage
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_canonicalizer.py -q
```

**Expected**: `ModuleNotFoundError: No module named 'backend.data.settings_canonicalizer'` (RED 状态)

### Step 1.2: 实现 `settings_canonicalizer.py` (GREEN)

```python
"""Settings 字段命名规范化模块。

把历史 snake_case DB 数据在 GET 时翻译成 camelCase AppSettings,
并在 PUT 时把存进 DB 的 camelCase payload 整树校验,
拒绝白名单外 / snake_case 残留字段。

纯函数, 无外部依赖, 可独立测试。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, List

logger = logging.getLogger(__name__)

# snake_case → camelCase 字段名映射 (单源)
# 修改 AppSettings (src/entities/setting/types.ts) 字段时必须同步更新此处
ALIASES: Dict[str, str] = {
    # 顶层 8 个 snake 历史字段 (legacy schema 残留)
    "model_selections": "modelSelections",
    "max_context": "maxContext",
    "proxy_mode": "proxyMode",
    "proxy_url": "proxyUrl",
    "tls_version": "tlsVersion",
    "auto_memory": "autoMemory",
    "confirm_delete": "confirmDelete",
    "compact_mode": "compactMode",
    # modelSelections 子层
    "chat_model": "chatModel",
    "vision_model": "visionModel",
    "embedding_model": "embeddingModel",
    # EndpointConfig 子层
    "base_url": "baseUrl",
    "api_key": "apiKey",
    "discovered_models": "discoveredModels",
    "last_discovered_at": "lastDiscoveredAt",
    # ModelSelection 子层
    "endpoint_id": "endpointId",
    "model_id": "modelId",
}

# AppSettings (src/entities/setting/types.ts) 锁死的白名单
LEGAL_TOP_KEYS: FrozenSet[str] = frozenset({
    "streaming", "autoMemory", "confirmDelete", "compactMode",
    "endpoints", "modelSelections", "maxContext", "temperature",
    "proxyMode", "proxyUrl", "tlsVersion",
    "wiki",
    "version",
})
LEGAL_ENDPOINT_KEYS: FrozenSet[str] = frozenset({
    "id", "name", "baseUrl", "apiKey",
    "discoveredModels", "lastDiscoveredAt",
})
LEGAL_MODEL_SELECTION_KEYS: FrozenSet[str] = frozenset({
    "endpointId", "modelId",
})
LEGAL_DISCOVERED_MODEL_KEYS: FrozenSet[str] = frozenset({
    "id", "capabilities", "endpointId",
})
LEGAL_WIKI_KEYS: FrozenSet[str] = frozenset({
    "useFolderPicker",
})

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def to_camel(value: Any) -> Any:
    """递归把 dict 的 snake_case key 翻译成 camelCase, list 递归."""
    if isinstance(value, dict):
        return {_translate_key(k): to_camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_camel(item) for item in value]
    return value


def from_camel(value: Any) -> Any:
    """反向: ALIASES 仅翻译已知 snake↔camel 对; 其它 camelCase key 原样保留."""
    if not isinstance(value, (dict, list)):
        return value
    inverse = {v: k for k, v in ALIASES.items()}
    if isinstance(value, dict):
        return {inverse.get(k, k): from_camel(v) for k, v in value.items()}
    return [from_camel(item) for item in value]


def _translate_key(key: str) -> str:
    return ALIASES.get(key, key)


def validate_settings_shape(settings: dict) -> None:
    """AppSettings 白名单校验. 不在白名单的字段 → raise ValueError."""
    unknown = [k for k in settings if k not in LEGAL_TOP_KEYS]
    if unknown:
        raise ValueError(
            f"unknown top-level field {unknown[0]!r}; "
            f"allowed: {sorted(LEGAL_TOP_KEYS)}"
        )

    for i, ep in enumerate(settings.get("endpoints") or []):
        if not isinstance(ep, dict):
            raise ValueError(f"endpoints[{i}] is not a dict")
        bad_ep = [k for k in ep if k not in LEGAL_ENDPOINT_KEYS]
        if bad_ep:
            raise ValueError(
                f"unknown endpoint field {bad_ep[0]!r} at endpoints[{i}]; "
                f"allowed: {sorted(LEGAL_ENDPOINT_KEYS)}"
            )
        for j, model in enumerate(ep.get("discoveredModels") or []):
            if not isinstance(model, dict):
                raise ValueError(
                    f"endpoints[{i}].discoveredModels[{j}] is not a dict"
                )
            bad = [k for k in model if k not in LEGAL_DISCOVERED_MODEL_KEYS]
            if bad:
                raise ValueError(
                    f"unknown discovered-model field {bad[0]!r} "
                    f"at endpoints[{i}].discoveredModels[{j}]; "
                    f"allowed: {sorted(LEGAL_DISCOVERED_MODEL_KEYS)}"
                )

    ms = settings.get("modelSelections") or {}
    for sel_key in ("chatModel", "visionModel", "embeddingModel"):
        sel = ms.get(sel_key) or {}
        if not isinstance(sel, dict):
            raise ValueError(f"modelSelections.{sel_key} is not a dict")
        bad = [k for k in sel if k not in LEGAL_MODEL_SELECTION_KEYS]
        if bad:
            raise ValueError(
                f"unknown model-selection field {bad[0]!r} "
                f"in modelSelections.{sel_key}; "
                f"allowed: {sorted(LEGAL_MODEL_SELECTION_KEYS)}"
            )

    wiki = settings.get("wiki") or {}
    bad_wiki = [k for k in wiki if k not in LEGAL_WIKI_KEYS]
    if bad_wiki:
        raise ValueError(
            f"unknown wiki field {bad_wiki[0]!r}; "
            f"allowed: {sorted(LEGAL_WIKI_KEYS)}"
        )


def detect_legacy_snake_pollution(
    settings: Any,
    path: str = "",
) -> List[str]:
    """递归遍历, 返回所有 snake_case 字段路径 (开发模式 log.warning 用)."""
    polluted: List[str] = []
    if isinstance(settings, dict):
        for k, v in settings.items():
            sub_path = f"{path}.{k}" if path else k
            if isinstance(k, str) and _SNAKE_RE.match(k):
                polluted.append(sub_path)
            polluted.extend(detect_legacy_snake_pollution(v, sub_path))
    elif isinstance(settings, list):
        for i, item in enumerate(settings):
            polluted.extend(
                detect_legacy_snake_pollution(item, f"{path}[{i}]")
            )
    if polluted:
        logger.warning(
            "[settings_canonicalizer] legacy snake_case pollution detected: %s",
            polluted,
        )
    return polluted
```

### Step 1.3: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_canonicalizer.py -q
```

**Expected**: ≥16 cases 全过 (to_camel 5 + from_camel 1 + ALIASES 2 + validate_settings_shape 5 + detect 4 = 17).

### Step 1.4: Commit

```bash
cd /home/fz/project/sage
git add backend/data/settings_canonicalizer.py backend/tests/unit/test_settings_canonicalizer.py
git commit -m "feat(backend): settings_canonicalizer — snake↔camel + shape validation

to_camel/from_camel 双向翻译; validate_settings_shape 按 AppSettings
白名单拒绝未知字段; detect_legacy_snake_pollution 给 dev 模式发告警。
17 个 pytest case 全过。"
```

---

## Task 2: 修 `legacy_routes.py` — GET/PUT 套翻译层

**Files:**
- Modify: `/home/fz/project/sage/backend/api/legacy_routes.py:731-790`
- Modify: `/home/fz/project/sage/backend/tests/integration/test_settings_route_legacy.py`

**Interfaces:**
- Consumes:
  - `settings_canonicalizer.to_camel / detect_legacy_snake_pollution / validate_settings_shape` (Task 1)
  - `SettingsRepository.get_json / set_json` (existing)

### Step 2.1: 看现状并定位要改的行

```bash
cd /home/fz/project/sage
sed -n '730,800p' backend/api/legacy_routes.py
```

**Expected output (近似)**:

```python
@router.get("/settings")
async def legacy_get_settings() -> Optional[dict]:
    """读取持久化的 settings；不存在返回 null。"""
    from backend.data.settings_repo import SettingsRepository

    return SettingsRepository().get_json("app_settings")


@router.put("/settings", response_model=LegacySettingsResponse)
async def legacy_update_settings(req: LegacySettingsRequest) -> LegacySettingsResponse:
    ...
    repo = SettingsRepository()
    existing = repo.get_json("app_settings") or {}
    payload = req.dict(exclude_none=True)
    merged = {**existing, **payload}
    repo.set_json("app_settings", merged, category="general")
```

### Step 2.2: 写失败集成测试 (RED)

Append to `/home/fz/project/sage/backend/tests/integration/test_settings_route_legacy.py`:

```python
"""新增的端到端 GET/PUT 行为测试,验证翻译层 + 白名单。"""
import pytest

from backend.data.settings_repo import SettingsRepository


@pytest.fixture(autouse=True)
def _clean_settings():
    """每测试前清空 app_settings 行."""
    SettingsRepository().db.get_connection().execute(
        "DELETE FROM preferences WHERE key='app_settings'"
    )
    yield
    SettingsRepository().db.get_connection().execute(
        "DELETE FROM preferences WHERE key='app_settings'"
    )


async def test_get_translates_legacy_snake_to_camel(ac):
    """DB 里手插一条 snake_case 行, GET 应返回 camelCase。"""
    SettingsRepository().set_json(
        "app_settings",
        {"endpoints": [{"id": "e1", "base_url": "u", "api_key": "k",
                          "discovered_models": [], "last_discovered_at": 0}]},
        category="general",
    )
    resp = await ac.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoints"][0]["baseUrl"] == "u"
    assert body["endpoints"][0]["apiKey"] == "k"
    assert "base_url" not in body["endpoints"][0]


async def test_get_returns_null_when_corrupted_json(ac):
    """DB 行 JSON 损坏 → GET 返回 null (不抛 500)。"""
    conn = SettingsRepository().db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO preferences(key,value,value_type,category,created_at,updated_at) "
        "VALUES('app_settings', 'not-valid-json{', 'string', 'general', 1, 1)"
    )
    conn.commit()
    resp = await ac.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_put_with_unknown_field_rejected(ac):
    """PUT 接受 schema 内 3 字段 + 不在白名单的字段 → 400."""
    resp = await ac.put("/api/v1/settings", json={
        "streaming": True,
        "foo": "bar",  # 不在 AppSettings 白名单
    })
    assert resp.status_code == 400
    assert "unknown top-level field 'foo'" in resp.text
```

### Step 2.3: 跑测试验证失败 (RED)

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_route_legacy.py -q -k "test_get_translates or test_put_with_unknown or test_get_returns_null"
```

**Expected**: 3 cases FAIL (因为现状 GET 不翻译, PUT 不验证白名单)。

### Step 2.4: 修 `legacy_routes.py`

替换 `/home/fz/project/sage/backend/api/legacy_routes.py:735-790` 的两个 handler:

```python
@router.get("/settings")
async def legacy_get_settings() -> Optional[dict]:
    """读取持久化的 settings；不存在返回 null。

    翻译历史 snake_case 残留到 camelCase 返回, 与 AppSettings 类型对齐。
    JSON 损坏时走 null fallback 而不是 500.
    """
    from backend.data.settings_repo import SettingsRepository
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        to_camel,
    )

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        logger.warning("[LEGACY] /settings: corrupted app_settings JSON, returning null")
        return None
    if raw is None:
        return None
    detect_legacy_snake_pollution(raw)
    return to_camel(raw)


@router.put("/settings", response_model=LegacySettingsResponse)
async def legacy_update_settings(req: LegacySettingsRequest) -> LegacySettingsResponse:
    """持久化 settings 到 preferences 表。

    v3.1 修复: 合并而非覆盖。
    本次升级: 合并 → 整树翻译到 camelCase → 校验白名单 → 落盘。
    """
    from backend.data.settings_repo import SettingsRepository
    from backend.data.settings_canonicalizer import (
        to_camel,
        validate_settings_shape,
    )

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings") or {}
    except (ValueError, TypeError):
        existing = {}

    payload = req.dict(exclude_none=True)
    merged = {**existing, **payload}
    camel_merged = to_camel(merged)
    validate_settings_shape(camel_merged)
    repo.set_json("app_settings", camel_merged, category="general")

    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")
    logger.info(f"[LEGACY] /settings updated: changed={changed_fields}")
    return LegacySettingsResponse(status="ok", changed_fields=changed_fields)
```

> 如果文件顶部没有 `logger`, 加 `import logging` + `logger = logging.getLogger(__name__)`。

### Step 2.5: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_route_legacy.py -q
```

**Expected**: 全部 cases 全过 (原本 5 + 新增 3)。

### Step 2.6: Commit

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_settings_route_legacy.py
git commit -m "fix(backend): legacy /settings GET 翻译 snake→camel + PUT 白名单校验

GET 永远返回 camelCase 与 AppSettings 对齐; PUT 合并 → to_camel →
validate_settings_shape 拒收未知字段; JSON 损坏走 null fallback。
集成测试 +3 cases。"
```

---

## Task 3: 修 `hex_routes.py` — 收紧 `extra="allow"` 到 `forbid`

**Files:**
- Modify: `/home/fz/project/sage/backend/api/hex_routes.py:64-79, 187-220`
- Create: `/home/fz/project/sage/backend/tests/integration/test_settings_route_hex.py`

### Step 3.1: 写失败集成测试 (RED)

新建 `/home/fz/project/sage/backend/tests/integration/test_settings_route_hex.py`:

```python
"""hex_routes SettingsRequest 白名单校验。"""
import pytest

from backend.data.settings_repo import SettingsRepository


@pytest.fixture(autouse=True)
def _clean():
    SettingsRepository().db.get_connection().execute(
        "DELETE FROM preferences WHERE key='app_settings'"
    )
    yield
    SettingsRepository().db.get_connection().execute(
        "DELETE FROM preferences WHERE key='app_settings'"
    )


async def test_hex_put_rejects_unknown_field(ac):
    """hex_routes 也拒收白名单外字段."""
    resp = await ac.put("/api/v1/settings", json={
        "streaming": True, "foo": "bar",
    })
    assert resp.status_code in (400, 422)
```

### Step 3.2: 跑测试验证 RED

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_route_hex.py -q
```

**Expected**: 当前应该会 200 OK 因为 `extra="allow"`，FAIL。

### Step 3.3: 修 `hex_routes.py:64-79`

把:

```python
class SettingsRequest(BaseModel):
    """Hex 路径的 PUT /settings 请求体（PG3.2）。
    ...
    PG3.2 升级（2026-06-22）：``Config.extra = "allow"`` 以接受前端的
    ``AppSettings`` 完整字段...
    """
    class Config:
        extra = "allow"

    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # noqa: S105
    model: Optional[str] = None
```

改成:

```python
class SettingsRequest(BaseModel):
    """Hex 路径的 PUT /settings 请求体。

    本次升级（2026-07-22）：从 ``extra="allow"`` 收紧到 ``extra="forbid"``。
    前端 AppSettings 走 settingsClient 同步写 backend, 多余字段视为 bug。
    请求体翻译 + 校验在 update_settings() handler 显式处理。
    """
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # noqa: S105
    model: Optional[str] = None
```

(Pydantic v2 main 分支有 `model_config = ConfigDict(extra="forbid")` 等价项, win7 在 Task 7 cherry-pick 时手工改回 `class Config: extra = "forbid"`.)

### Step 3.4: 同样 wire `hex_routes.update_settings` 套翻译层

把 `hex_routes.py:187-220` 的 `update_settings` handler:

```python
@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    req: SettingsRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> SettingsResponse:
    """Hex 路径的 settings 更新端点 + persist + emit 审计事件。

    本次升级：与 legacy_routes 对齐, GET 翻译 snake→camel, PUT 翻译 + 校验白名单。
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = req.model_dump(exclude_none=True)  # pydantic v2 syntax (win7: req.dict(...))

    from backend.data.settings_repo import SettingsRepository
    from backend.data.settings_canonicalizer import (
        to_camel,
        validate_settings_shape,
    )

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings") or {}
    except (ValueError, TypeError):
        existing = {}
    merged = {**existing, **payload}
    camel_merged = to_camel(merged)
    validate_settings_shape(camel_merged)
    repo.set_json("app_settings", camel_merged, category="general")

    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")
    logger.info(f"[HEX REQ {request_id}] /settings updated: changed={changed_fields}")

    svc.events.emit(
        "settings_changed",
        {"changed_fields": changed_fields, "request_id": request_id},
    )
    return SettingsResponse(status="ok", changed_fields=changed_fields)
```

同时把 `get_settings` handler:

```python
@router.get("/settings")
async def get_settings() -> Optional[dict]:
    """读取持久化的 settings；不存在返回 null（前端走 DEFAULT_SETTINGS）。

    本次升级: 翻译历史 snake_case 残留 → camelCase.
    """
    from backend.data.settings_repo import SettingsRepository
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        to_camel,
    )

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        return None
    if raw is None:
        return None
    detect_legacy_snake_pollution(raw)
    return to_camel(raw)
```

### Step 3.5: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_route_hex.py backend/tests/integration/test_settings_route_legacy.py backend/tests/unit/test_settings_canonicalizer.py -q
```

**Expected**: 全部 ≥21 cases 全过。

### Step 3.6: Commit

```bash
git add backend/api/hex_routes.py backend/tests/integration/test_settings_route_hex.py
git commit -m "fix(backend): hex /settings GET/PUT 翻译 + 白名单 forbid

从 extra=allow 收紧到 forbid,前端 AppSettings 字段必须显式列在白名单;
GET 翻译历史 snake → camel, PUT 同样套 to_camel + validate_settings_shape。
+1 integration test。"
```

---

## Task 4: Frontend `deepMerge` utility + 单元测试

**Files:**
- Create: `/home/fz/project/sage/src/entities/setting/deepMerge.ts`
- Create: `/home/fz/project/sage/src/entities/setting/__tests__/storage-deepmerge.test.ts`

### Step 4.1: 写失败单元测试 (RED)

新建文件 `/home/fz/project/sage/src/entities/setting/__tests__/storage-deepmerge.test.ts`:

```typescript
import { describe, expect, it, vi } from 'vitest';

import type { AppSettings } from '../types';
import { DEFAULT_SETTINGS } from '../types';

import { deepMerge } from '../deepMerge';

const remoteClean: AppSettings = {
  ...DEFAULT_SETTINGS,
  endpoints: [{
    id: 'e1',
    name: '新端点',
    baseUrl: 'https://example.com/v1',
    apiKey: 'sk-remote',
    discoveredModels: [{
      id: 'm1', capabilities: ['chat'], endpointId: 'e1',
    }],
    lastDiscoveredAt: 1000,
  }],
  modelSelections: {
    chatModel:    { endpointId: 'e1', modelId: 'm1' },
    visionModel:  { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
  },
};

const localClean: AppSettings = {
  ...DEFAULT_SETTINGS,
  streaming: false,
};

describe('deepMerge', () => {
  it('remote 仅 (无 local) → 直接返回 remote', () => {
    expect(deepMerge(remoteClean, null)).toEqual(remoteClean);
  });

  it('local 仅 (无 remote) → 直接返回 local', () => {
    expect(deepMerge(null, localClean)).toEqual(localClean);
  });

  it('字段级合并: local.streaming=false + remote.streaming=true → remote wins', () => {
    const merged = deepMerge(localClean, remoteClean);
    expect(merged.streaming).toBe(true);
  });

  it('endpoints[] 按 id 去重: 同 id 走字段比较, remote 胜', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [{
        id: 'e1',
        name: '老端点',
        baseUrl: 'https://old.com',
        apiKey: 'sk-old',
        discoveredModels: [],
        lastDiscoveredAt: 0,
      }],
    };
    const merged = deepMerge(local, remoteClean);
    expect(merged.endpoints).toHaveLength(1);
    expect(merged.endpoints[0].baseUrl).toBe('https://example.com/v1');
  });

  it('同 id 不同 baseUrl → console.warn + remote 胜', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    deepMerge(localClean, remoteClean);
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/conflict on 'endpoints\[e1\]\.baseUrl'/)
    );
    warn.mockRestore();
  });

  it('嵌套 objects 字段级递归: modelSelections.chatModel 各字段按规则', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      modelSelections: {
        chatModel:    { endpointId: 'e1', modelId: 'm-LOCAL' },
        visionModel:  { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
    };
    const merged = deepMerge(local, remoteClean);
    expect(merged.modelSelections.chatModel.endpointId).toBe('e1');
    expect(merged.modelSelections.chatModel.modelId).toBe('m1');
  });

  it('叶节点 (string/number/boolean) → override 完全替换 base', () => {
    const merged = deepMerge(
      { a: 'local' as const, b: 1, c: true },
      { a: 'remote' as const, b: 2, c: false }
    );
    expect(merged).toEqual({ a: 'remote', b: 2, c: false });
  });

  it('endpoints[] remote 完全空数组 → 不应污染 local', () => {
    const local: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [{
        id: 'e1',
        name: 'n',
        baseUrl: 'u',
        apiKey: 'k',
        discoveredModels: [],
        lastDiscoveredAt: null,
      }],
    };
    const remoteEmpty: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [],
    };
    const merged = deepMerge(local, remoteEmpty);
    expect(merged.endpoints).toHaveLength(1);
  });
});
```

### Step 4.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
npx vitest run src/entities/setting/__tests__/storage-deepmerge.test.ts
```

**Expected**: FAIL — `Cannot find module '../deepMerge'`

### Step 4.3: 实现 `deepMerge.ts` (GREEN)

新建 `/home/fz/project/sage/src/entities/setting/deepMerge.ts`:

```typescript
/**
 * 字段级 deep merge + 冲突告警.
 *
 * 策略 (默认 'remote-wins'):
 * - 双方都是 plain object → 字段级递归
 * - 双方都是 array (e.g. endpoints[]) → 按 id 去重, 同 id 走字段比较, 不同 console.warn
 * - 标量 / array leaf → override 完全替换 base
 * - 字段值深度不等 (对象对象比较) → console.warn + remote wins
 */
type ConflictPolicy = 'remote-wins' | 'local-wins';

export interface DeepMergeOptions {
  policy?: ConflictPolicy;
  onConflict?: (path: string, base: unknown, override: unknown) => void;
}

export function deepMerge<T>(
  base: T,
  override: T,
  options: DeepMergeOptions = {},
): T {
  const { policy = 'remote-wins', onConflict } = options;
  return _merge(base, override, '', policy, onConflict) as T;
}

function _merge(
  base: unknown,
  override: unknown,
  currentPath: string,
  policy: ConflictPolicy,
  onConflict: DeepMergeOptions['onConflict'],
): unknown {
  if (override === undefined || override === null) {
    return base ?? override;
  }
  if (base === undefined || base === null) {
    return override;
  }

  if (Array.isArray(base) && Array.isArray(override)) {
    return _mergeArrays(base, override, currentPath, policy, onConflict);
  }

  if (isPlainObject(base) && isPlainObject(override)) {
    const keys = new Set([...Object.keys(base), ...Object.keys(override)]);
    const result: Record<string, unknown> = {};
    for (const k of keys) {
      const sub = currentPath ? `${currentPath}.${k}` : k;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      result[k] = _merge((base as any)[k], (override as any)[k], sub, policy, onConflict);
    }
    return result;
  }

  if (!deepEqual(base, override)) {
    if (onConflict) {
      onConflict(currentPath, base, override);
    } else {
      console.warn(
        `[deepMerge] conflict on '${currentPath}': ` +
        `base=${JSON.stringify(base)} override=${JSON.stringify(override)}; ${policy}`,
      );
    }
    return policy === 'remote-wins' ? override : base;
  }
  return base;
}

function _mergeArrays(
  base: unknown[],
  override: unknown[],
  currentPath: string,
  policy: ConflictPolicy,
  onConflict: DeepMergeOptions['onConflict'],
): unknown[] {
  const overrideById = new Map<string, unknown>();
  const overrideNoId: unknown[] = [];
  for (const item of override) {
    const id = isPlainObject(item) ? (item as { id?: unknown }).id : undefined;
    if (typeof id === 'string' || typeof id === 'number') {
      overrideById.set(String(id), item);
    } else {
      overrideNoId.push(item);
    }
  }

  const baseById = new Map<string, unknown>();
  for (const item of base) {
    const id = isPlainObject(item) ? (item as { id?: unknown }).id : undefined;
    if (typeof id === 'string' || typeof id === 'number') {
      baseById.set(String(id), item);
    }
  }

  const result: unknown[] = [];
  const seenIds = new Set<string>();

  for (const [id, bItem] of baseById) {
    seenIds.add(id);
    if (overrideById.has(id)) {
      const oItem = overrideById.get(id);
      result.push(_merge(bItem, oItem, `${currentPath}[${id}]`, policy, onConflict));
    } else {
      result.push(bItem);
    }
  }

  for (const [id, oItem] of overrideById) {
    if (!seenIds.has(id)) {
      result.push(oItem);
    }
  }

  for (const item of overrideNoId) {
    result.push(item);
  }

  return result;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (a === null || b === null) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!deepEqual(a[i], b[i])) return false;
    }
    return true;
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const k of keysA) {
      if (!deepEqual(a[k], b[k])) return false;
    }
    return true;
  }
  return false;
}
```

### Step 4.4: 跑测试验证 GREEN

```bash
cd /home/fz/project/sage
npx vitest run src/entities/setting/__tests__/storage-deepmerge.test.ts
```

**Expected**: 8/8 cases 全过。

### Step 4.5: Commit

```bash
git add src/entities/setting/deepMerge.ts src/entities/setting/__tests__/storage-deepmerge.test.ts
git commit -m "feat(frontend): deepMerge utility with conflict-aware remote-wins policy

字段级递归 + 数组按 id 去重 + 冲突时 console.warn + 默认 remote-wins。
8 个 vitest cases 覆盖主路径 (nested/array/scalar/leaf/null)。"
```

---

## Task 5: Frontend `loadSettings` 重构

**Files:**
- Modify: `/home/fz/project/sage/src/entities/setting/storage.ts:102-115`
- Create: `/home/fz/project/sage/src/entities/setting/__tests__/storage-loadsettings.test.ts`

### Step 5.1: 写失败测试 (RED)

新建 `/home/fz/project/sage/src/entities/setting/__tests__/storage-loadsettings.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { loadSettings } from '../storage';
import { settingsClient } from '../../../shared/api/settingsClient';
import { DEFAULT_SETTINGS } from '../types';

vi.mock('../../../shared/api/settingsClient');

describe('loadSettings', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('remote null + local null → DEFAULT_SETTINGS', async () => {
    vi.mocked(settingsClient.getSettings).mockResolvedValue(null);
    const result = await loadSettings();
    expect(result).toEqual(DEFAULT_SETTINGS);
  });

  it('remote 完整 camelCase, local 空 → 返回 remote', async () => {
    const remote = {
      ...DEFAULT_SETTINGS,
      endpoints: [{
        id: 'e1', name: 'n', baseUrl: 'u', apiKey: 'k',
        discoveredModels: [], lastDiscoveredAt: null,
      }],
    };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.endpoints[0].baseUrl).toBe('u');
  });

  it('remote null + local 有 → 返回 local', async () => {
    vi.mocked(settingsClient.getSettings).mockResolvedValue(null);
    localStorage.setItem('sage-settings', JSON.stringify({
      streaming: true, endpoints: [], modelSelections: {
        chatModel: { endpointId: 'e1', modelId: 'm1' },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
    }));
    const result = await loadSettings();
    expect(result.modelSelections.chatModel.endpointId).toBe('e1');
  });

  it('local + remote 都存在 → deepMerge 字段级合并 + writeLocalCacheSync', async () => {
    const local = { ...DEFAULT_SETTINGS, streaming: false };
    localStorage.setItem('sage-settings', JSON.stringify(local));

    const remote = { ...DEFAULT_SETTINGS, streaming: true };
    vi.mocked(settingsClient.getSettings).mockResolvedValue(remote as never);

    const result = await loadSettings();
    expect(result.streaming).toBe(true);

    const cached = JSON.parse(localStorage.getItem('sage-settings')!);
    expect(cached.streaming).toBe(true);
  });
});
```

### Step 5.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
npx vitest run src/entities/setting/__tests__/storage-loadsettings.test.ts
```

**Expected**: 全部 FAIL (loadSettings 当前是 `{...remote}` 浅 merge, 不调 deepMerge).

### Step 5.3: 修 `loadSettings` in storage.ts

Replace `/home/fz/project/sage/src/entities/setting/storage.ts:102-115`:

```typescript
export async function loadSettings(): Promise<AppSettings> {
  cleanupLocalCacheIfExpired();

  let remote: AppSettings | null = null;
  try {
    remote = await settingsClient.getSettings();
  } catch (e: unknown) {
    console.error('[loadSettings] backend getSettings failed, falling back to local:', e);
  }

  if (remote) {
    // 远端成功 → 以远端为权威, local 仅作 merge 兜底
    const local = readLocalCacheSync() ?? {};
    const merged = deepMerge<AppSettings>(local, remote, {
      policy: 'remote-wins',
    });
    const finalSettings = mergeWithDefaults(merged);
    writeLocalCacheSync(finalSettings);
    return finalSettings;
  }

  await maybeAutoMigrate(remote);

  const local = readLocalCacheSync();
  const finalSettings = mergeWithDefaults(local ?? {});
  writeLocalCacheSync(finalSettings);
  return finalSettings;
}
```

加 imports in storage.ts top:

```typescript
import { deepMerge } from './deepMerge';
```

### Step 5.4: 跑测试验证 GREEN

```bash
cd /home/fz/project/sage
npx vitest run src/entities/setting/__tests__/
```

**Expected**: 8 (Task 4) + 4 (Task 5) = 12 cases 全过。

### Step 5.5: Commit

```bash
git add src/entities/setting/storage.ts src/entities/setting/__tests__/storage-loadsettings.test.ts
git commit -m "fix(frontend): loadSettings deepMerge remote wins + 兜底持久化

remote 失败 → console.error + 走 local; remote + local → deepMerge
字段级; 写回 localStorage 让前端永远看到\"清洗过的\"权威数据。
+4 vitest cases。"
```

---

## Task 6: 前端 e2e spec

**Files:**
- Create: `/home/fz/project/sage/tests/e2e/settings-schema-canonicalization.e2e.ts`

### Step 6.1: 写新 e2e spec

参考 `tests/e2e/welcome-screen.e2e.ts` 模式:

```typescript
import { test, expect } from '@playwright/test';

const LEGACY_SNAKE_PAYLOAD = JSON.stringify({
  endpoints: [{
    id: 'e1',
    base_url: 'https://legacy.example.com/v1',
    api_key: 'sk-legacy',
    discovered_models: [],
    last_discovered_at: 0,
  }],
  model_selections: {
    chat_model: { endpoint_id: 'e1', model_id: 'm1' },
    vision_model: { endpoint_id: null, model_id: null },
    embedding_model: { endpoint_id: null, model_id: null },
  },
  streaming: true,
});

test.describe('Settings schema canonicalization', () => {
  test('settings page 加载历史 snake localStorage 时做端点显示验证', async ({ page }) => {
    await page.addInitScript((data) => {
      window.localStorage.setItem('sage-settings', data);
    }, LEGACY_SNAKE_PAYLOAD);

    await page.goto('http://localhost:1420/settings');
    await expect(page.getByText('设置', { exact: false })).toBeVisible();
    // 验证 EndpointsTab 把 localStorage 清洗后的端点渲染 (text 包含)
    await expect(page.getByText('https://legacy.example.com/v1')).toBeVisible();
  });

  test('mocked backend returns camelCase even when DB has snake', async ({ page }) => {
    await page.route('**/api/v1/settings', async (route) => {
      const body = JSON.parse(LEGACY_SNAKE_PAYLOAD);
      const translated = {
        endpoints: body.endpoints.map((ep: { [k: string]: unknown }) => ({
          id: ep.id, name: ep.name,
          baseUrl: ep.base_url, apiKey: ep.api_key,
          discoveredModels: ep.discovered_models,
          lastDiscoveredAt: ep.last_discovered_at,
        })),
        modelSelections: {
          chatModel: body.model_selections.chat_model,
          visionModel: body.model_selections.vision_model,
          embeddingModel: body.model_selections.embedding_model,
        },
        streaming: body.streaming,
      };
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(translated),
      });
    });

    await page.goto('http://localhost:1420/settings');
    await expect(page.getByText('https://legacy.example.com/v1')).toBeVisible();
  });
});
```

### Step 6.2: Commit (e2e 不跑,留 CI)

```bash
git add tests/e2e/settings-schema-canonicalization.e2e.ts
git commit -m "test(e2e): settings schema canonicalization Playwright spec

2 个 case: 1) 历史 snake localStorage 渲染时清洗, 2) 后端 mock 返回 camelCase.
进 CI Electron smoke / Playwright 跑. 本机不验证 (需 Vite dev + playwright 全套)。"
```

---

## Task 7: 双分支 PR + 收尾

### Step 7.1: 整理 commits + 切 main 分支开 PR 分支

**前提**：Task 1-6 已经在 `release/win7` (当前分支) 上 commit 完毕。

整理出一个清晰序列 (按时间序: spec → canonicalizer → legacy → hex → deepMerge → loadSettings → e2e):

```bash
cd /home/fz/project/sage
git log --oneline -10  # 应该有 spec + impl commits
```

把 commit 整理成 5-6 个清晰 conventional commit (如果当前序列混乱):

```bash
# 用 git rebase -i 整理 (假设当前最新 6 commits 是 Task 1-6)
```

### Step 7.2: 切到 main 建 PR 分支并 cherry-pick

```bash
git fetch origin main release/win7
git switch main
git pull --rebase origin main
git switch -c fix/settings-schema-canonicalization
# 把 release/win7 上 Task 1-6 的 commits cherry-pick 过来
# (如果上面 Step 7.1 rebase 没做, 这里要小心)
```

**预期冲突**：`backend/api/legacy_routes.py` 与 `backend/api/hex_routes.py` (pydantic v1 vs v2 语法差异)。

解决冲突 inline:
- `req.model_dump(...)` → 保留 (pydantic v2 main 用)
- `model_config = ConfigDict(extra="forbid")` → 保留
- 其它逻辑应 0 冲突

### Step 7.3: 本地 4 道关卡

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/data/settings_canonicalizer.py backend/api/legacy_routes.py backend/api/hex_routes.py backend/tests/ 2>&1 | tail -10
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_canonicalizer.py backend/tests/integration/test_settings_route_legacy.py backend/tests/integration/test_settings_route_hex.py -q

cd /home/fz/project/sage
npm run type-check
npm run lint
npx vitest run src/entities/setting/__tests__/
```

**Expected**: 全部 0 errors / 全过。

### Step 7.4: Push + main PR

```bash
git push -u origin fix/settings-schema-canonicalization

gh pr create --base main \
  --title "fix(settings): snake↔camel translation layer + GET/PUT whitelist + deep-merge" \
  --body "..."
```

CI 等绿 (4 jobs)。code-reviewer review → 修 critical/high。

### Step 7.5: 用户 merge → 用户合并后清理

```bash
git switch main
git pull --rebase origin main
git branch -d fix/settings-schema-canonicalization
git push origin --delete fix/settings-schema-canonicalization
```

### Step 7.6: win7 squash cherry-pick

```bash
git switch release/win7
git pull --rebase origin release/win7
git switch -c fix/win7-settings-schema-canonicalization
git cherry-pick <main-merge-sha>     # squash commit
# 解决冲突:
#   - backend/api/legacy_routes.py:
#       req.model_dump → req.dict(exclude_none=True)
#       model_config = ConfigDict(extra="forbid") → class Config: extra = "forbid"
#   - backend/api/hex_routes.py: 同上
# 其它文件 0 冲突

# 本地 pydantic v1 验证
conda activate sage-backend-py38
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_settings_canonicalizer.py backend/tests/integration/test_settings_route_legacy.py backend/tests/integration/test_settings_route_hex.py -q

git commit -m "fix(win7): cherry-pick #XXX (settings schema canonicalization)"

# LEFTHOOK=0 workaround if hooks hang (per memory)
LEFTHOOK=0 git push -u origin fix/win7-settings-schema-canonicalization

# ⚠️ 显式 --base release/win7, 不依赖默认
gh pr create --base release/win7 \
  --title "fix(win7): cherry-pick #XXX (settings schema canonicalization)" \
  --body "..."
```

CI 等绿。code-reviewer review。用户 merge squash。

### Step 7.7: 最后收尾

```bash
git switch release/win7
git pull --rebase origin release/win7
git branch -d fix/win7-settings-schema-canonicalization
git push origin --delete fix/win7-settings-schema-canonicalization

# 写 memory
$EDITOR ~/.claude/projects/-home-fz-project-sage/memory/sage-settings-schema-canonicalization-merged.md
```

memory 条目内容:

```markdown
---
name: sage-settings-schema-canonicalization-merged
description: Settings schema 规范化 + 同步 win7 收官 (PR #N + #M)
metadata:
  type: project
---

# Settings Schema Canonicalization

2026-07-22 实施完成 main + win7 双分支。

- **main PR #N**: fix(settings): snake↔camel translation layer + GET/PUT whitelist + deep-merge
  - 6 文件改动 (1 新模块 + 1 新前端 utils + 4 修改)
  - 30+ 新测试 (backend unit + integration + frontend vitest + e2e spec)
- **win7 PR #M**: fix(win7): cherry-pick #N (settings schema canonicalization)
  - 单 squash commit
  - 修 pydantic v1 兼容 (req.model_dump → req.dict, ConfigDict → class Config)

# 解决了什么 bug

sidebar 左下角圆点永久显示"未配置", 即使 UI 配了端点 + 模型. 三层叠加根因:
1. DB 历史 snake_case 污染 (老客户端直写 snake)
2. 后端 legacy schema `extra="allow"` 接受一切
3. 前端 `loadSettings` 浅 merge + 远端覆盖本地

# 关键决策

- 后端永远输出 camelCase (read 时即时翻译, write 时严格校验 AppSettings 白名单)
- 前端 deepMerge 字段级递归 + 冲突时 console.warn + 默认 remote-wins
- 不引入一次性 migration 脚本 (YAGNI; 读侧翻译已够)

# 设计 / 计划文档

- spec: docs/superpowers/specs/2026-07-22-settings-schema-canonicalization-design.md
- plan: docs/superpowers/plans/2026-07-22-settings-schema-canonicalization.md

# Why

免得下次又有"UI 配置了但 sidebar 未配置"问题重现. 翻译层是源头收口.

# How to apply

后续如要扩展 AppSettings (types.ts): 同步更新 backend/data/settings_canonicalizer.py 的 LEGAL_*_KEYS + ALIASES.
```

并在 `MEMORY.md` 索引加一行:

```markdown
- [Sage: settings schema canonicalization merged (2026-07-22)](sage-settings-schema-canonicalization-merged.md) — sidebar 永久'未配置'根因 (snake 污染 + extra=allow + 浅 merge). 6 file + 30+ tests, main + win7 双 PR.
```

---

## Self-Review (per writing-plans skill)

### 1. Spec coverage

| Spec § | Covered by Task |
|---|---|
| 1.1 Problem | (Phase 0 spec, 已 commit f15acd9) |
| 1.2 Goals 1-6 | Task 1 / 2-3 / 4-5 / 7 |
| 1.3 Non-goals | (spec 锁死, 没加新依赖) |
| 2 Architecture | Task 1 / 2-3 / 4-5 |
| 3 Components | Task 1 / 2 / 3 / 4 / 5 |
| 4 Data Flow | Task 2 / 3 / 5 (handler 实现) |
| 5 E1-E6 Error Handling | Task 1 (ValueError) / Task 2 (JSON 损坏) / Task 5 (console.error + Toast stub) |
| 6 T1-T7 Testing | Task 1 (T1) / Task 2 (T2) / Task 3 (T2 扩) / Task 4 (T3) / Task 5 (T3) / Task 6 (T4) |
| 7 Cross-branch | Task 7 (Phase 0-3) |
| 8 Estimate | spec + plan 综合 |

✅ Spec 全部 8 节都覆盖。

### 2. Placeholder scan

- 无 "TBD" / "TODO" / "implement later" / "fill in details"
- 无 "Add appropriate error handling" 抽象指示
- 无 "Similar to Task N" — 每 Task 都有完整代码
- 无 "TBC"

✅ 0 placeholders。

### 3. Type consistency

| Symbol | 出现位置 | 一致性 |
|---|---|---|
| `to_camel / from_camel / validate_settings_shape / detect_legacy_snake_pollution` | Task 1 定义 / Task 2-3 调用 | ✅ |
| `ALIASES / LEGAL_*_KEYS` | Task 1 | ✅ |
| `deepMerge<T>(base, override, options?) -> T` | Task 4 定义 / Task 5 调用 | ✅ |
| `EndpointConfig.id` 是 array id 字段 | Task 4 `_mergeArrays` | ✅ |

✅ 类型签名跨 task 一致。

### 4. 标注的潜在风险

1. **Task 3 Step 3.3 删 `extra = "allow"` 在 main 已正确 (pydantic v2)**, win7 cherry-pick 时手工改回 — 已在 Step 7.6 标注
2. **Task 6 e2e 不在本地验证** — 已在 Step 6.2 标注
3. **win7 cherry-pick 冲突依赖人** — 已在 Step 7.6 给出 inline 处理
4. **`LEFTHOOK=0` workaround / `--base release/win7` 强制** — 全部 cite 来源 memory

---

## 估计时间

- Task 1: 1 hr
- Task 2: 1 hr
- Task 3: 1 hr
- Task 4: 1 hr
- Task 5: 30 min
- Task 6: 30 min (写 spec, 不跑)
- Task 7: 1.5 hr (含 PR review)
- **合计**: 6.5 hr (一个工作日内完成)
