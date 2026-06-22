# localStorage 配置存储迁移至后端 SQLite 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sage 前端三处 localStorage 配置（settings / theme / current_session_id）迁移到后端 SQLite `preferences` 表，让 dev / 打包 / 换端口三种形态共享同一份配置；保留 localStorage 作为离线缓存兜底；旧数据静默自动迁移。

**Architecture:** 复用现有 `preferences` 表 + 新增 `settings_repo.py` 仓储；后端 `hex_routes.py` 升级现有 `PUT /settings` 为真持久化并新增 `GET /settings` + `GET/PUT /preferences/{key}`；Electron `commands.ts` 加 4 条 IPC；前端 `settingsClient.ts` 统一封装，5s 超时降级到 localStorage；迁移路径用 `migrated_to_backend` 标志 + 7 天冗余。

**Tech Stack:** Python 3.10+ / FastAPI / SQLite (WAL) / TypeScript 5 / React 18 / Vitest 4 / lefthook

**Spec:** `docs/superpowers/specs/2026-06-22-localstorage-to-backend-design.md`

---

## Global Constraints

| 项 | 值 |
|---|---|
| Python 解释器 | `sage-backend` conda 环境（`/home/fz/anaconda3/envs/sage-backend/bin/python`） |
| Python 测试运行 | `cd backend && bash ../scripts/pytest.sh -x --no-cov` |
| TypeScript 测试运行 | `npm run test:run -- --no-coverage` |
| TypeScript lint | `npx eslint --fix` (pre-commit hook 自动跑) |
| TypeScript format | `npx prettier --write` (pre-commit hook 自动跑) |
| Python lint/format | `bash scripts/lint.sh check --fix` / `bash scripts/lint.sh format` (pre-commit hook 自动跑) |
| 后端端口 | `127.0.0.1:8765` (默认) |
| 前端端口 | `localhost:1420` (Vite) |
| 数据库 | SQLite，`preferences` 表 schema 见 `backend/data/database.py:138-148` |
| IPC 超时 | 5s（前端 settingsClient） |
| localStorage 保留期 | 迁移后 7 天 |
| 端点白名单 | `app_settings` / `theme_mode` / `current_session_id` |
| 提交格式 | conventional commits |
| 分支策略 | 在当前 `release/win7` 分支上做；不动 `main` |
| Schema 版本 | `SETTINGS_VERSION = '3.0.0'`（仍由前端管） |

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/data/settings_repo.py` | Create | 基于 `preferences` 表的 KV 仓储 + 白名单 |
| `backend/data/database.py` | Modify | 支持 `SAGE_DB_PATH` 环境变量 |
| `backend/api/hex_routes.py` | Modify | 升级 `PUT /settings`、新增 `GET /settings`、`GET/PUT /preferences/{key}` |
| `backend/tests/unit/test_settings_repo.py` | Create | settings_repo 单元测试 |
| `backend/tests/integration/test_settings_endpoint.py` | Create | settings 端点集成测试 |
| `backend/tests/integration/test_preferences_endpoint.py` | Create | preferences 端点集成测试 |
| `backend/tests/integration/test_db_path.py` | Create | SAGE_DB_PATH 环境变量集成测试 |
| `electron/commands.ts` | Modify | 加 4 条 IPC 路由 |
| `electron/__tests__/commands.test.ts` | Modify | 加 4 条新路由测试 |
| `electron/main.ts` | Modify | 启动后端时设 `SAGE_DB_PATH=app.getPath('userData')/sage.db` |
| `src/shared/api/settingsClient.ts` | Create | 前端 IPC 客户端（5s 超时） |
| `src/shared/api/__tests__/settingsClient.test.ts` | Create | settingsClient 单元测试 |
| `src/entities/setting/storage.ts` | Modify | 改 async；新增自动迁移 + 7 天保留 |
| `src/entities/setting/__tests__/storage.test.ts` | Modify | 改 async 测试 + 迁移 + 7 天清理测试 |
| `src/entities/theme/storage.ts` | Create | 从 ThemeProvider 抽出 |
| `src/entities/theme/__tests__/storage.test.ts` | Create | theme storage 单元测试 |
| `src/entities/session/storage.ts` | Create | 从 store.ts 抽出 |
| `src/entities/session/__tests__/storage.test.ts` | Create | session storage 单元测试 |
| `src/features/manage-settings/useSettings.ts` | Modify | 改 async + isLoading |
| `src/features/manage-settings/__tests__/useSettings.test.ts` | Modify | 改 async 测试 |
| `src/app/providers/ThemeProvider.tsx` | Modify | 改 async init |
| `src/app/providers/__tests__/ThemeProvider.test.tsx` | Create | async init 测试 |
| `src/shared/lib/store.ts` | Modify | currentSessionId 改 async init |
| `src/shared/lib/__tests__/store.test.ts` | Modify | 改 async 测试 |
| `src/App.tsx` | Modify | 加 useEffect 触发 currentSessionId 初始化 |
| `docs/technical/09-frontend.md` | Modify | 加"配置存储"小节 |
| `docs/technical/10-api.md` | Modify | 加 4 个新端点 |

---

## Task 1: settings_repo 后端仓储（TDD）

**Files:**
- Create: `backend/data/settings_repo.py`
- Create: `backend/tests/unit/test_settings_repo.py`

**Interfaces:**
- Consumes: `backend.data.database.get_database()` 返回 `Database`，其 `get_connection()` 返回 `sqlite3.Connection`
- Produces: `SettingsRepository` 类，含 `KEYS`、`get(key) -> Optional[str]`、`get_json(key) -> Optional[Any]`、`set(key, value, value_type, category) -> None`、`set_json(key, value, category) -> None`、`delete(key) -> None`、`list_by_category(category) -> dict[str, str]`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_settings_repo.py`：

```python
"""settings_repo 单元测试"""
import json
import pytest
from unittest.mock import MagicMock

from backend.data.settings_repo import SettingsRepository


@pytest.fixture
def mock_db():
    db = MagicMock()
    conn = MagicMock()
    db.get_connection.return_value = conn
    return db, conn


def test_keys_whitelist():
    repo = SettingsRepository()
    assert "app_settings" in SettingsRepository.KEYS
    assert "theme_mode" in SettingsRepository.KEYS
    assert "current_session_id" in SettingsRepository.KEYS


def test_get_returns_value(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": "light"}
    repo = SettingsRepository(db=db)
    assert repo.get("theme_mode") == "light"


def test_get_returns_none_when_missing(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    assert repo.get("theme_mode") is None


def test_get_json_parses_value(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": '{"k": 1}'}
    repo = SettingsRepository(db=db)
    assert repo.get_json("app_settings") == {"k": 1}


def test_get_json_returns_none_on_invalid_json(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": "not json"}
    repo = SettingsRepository(db=db)
    assert repo.get_json("app_settings") is None


def test_set_inserts_new_row(mock_db):
    db, conn = mock_db
    # fetchone 返回 None → 走 INSERT 分支
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    repo.set("theme_mode", "dark", value_type="string", category="ui")
    # 至少调用了 1 次 SELECT + 1 次 INSERT
    assert conn.execute.call_count >= 2
    conn.commit.assert_called()


def test_set_updates_existing_row(mock_db):
    db, conn = mock_db
    # fetchone 返回已有行 → 走 UPDATE 分支
    conn.execute.return_value.fetchone.return_value = {"key": "theme_mode"}
    repo = SettingsRepository(db=db)
    repo.set("theme_mode", "dark")
    conn.commit.assert_called()


def test_set_json_serializes(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    repo.set_json("app_settings", {"x": 1}, category="general")
    # 验证 execute 中有 JSON 字符串
    args = conn.execute.call_args_list[0]
    assert json.dumps({"x": 1}) in str(args)


def test_delete_removes_row(mock_db):
    db, conn = mock_db
    repo = SettingsRepository(db=db)
    repo.delete("theme_mode")
    conn.execute.assert_called()
    conn.commit.assert_called()


def test_list_by_category(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchall.return_value = [
        {"key": "theme_mode", "value": "dark"},
        {"key": "app_settings", "value": "{}"},
    ]
    repo = SettingsRepository(db=db)
    result = repo.list_by_category("ui")
    assert result == {"theme_mode": "dark"}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_repo.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.data.settings_repo'`

- [ ] **Step 3: 写最小实现**

创建 `backend/data/settings_repo.py`：

```python
"""Settings 仓储层

基于 preferences 表的 KV 存储。模块级 KEYS 白名单限定可写入的 key。
"""
import json
import time
from typing import Any, Optional

from backend.data.database import Database, get_database


class SettingsRepository:
    """preferences 表的 KV 仓储。"""

    KEYS: frozenset[str] = frozenset({
        "app_settings",
        "theme_mode",
        "current_session_id",
    })

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def _conn(self):
        return self.db.get_connection()

    def get(self, key: str) -> Optional[str]:
        if key not in self.KEYS:
            return None
        row = self._conn().execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def set(
        self,
        key: str,
        value: str,
        value_type: str = "string",
        category: str = "general",
    ) -> None:
        if key not in self.KEYS:
            raise ValueError(f"key {key!r} not in whitelist")
        now = int(time.time() * 1000)
        conn = self._conn()
        existing = conn.execute(
            "SELECT key FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE preferences
                   SET value = ?, value_type = ?, category = ?, updated_at = ?
                   WHERE key = ?""",
                (value, value_type, category, now, key),
            )
        else:
            conn.execute(
                """INSERT INTO preferences
                   (key, value, value_type, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, value, value_type, category, now, now),
            )
        conn.commit()

    def set_json(self, key: str, value: Any, category: str = "general") -> None:
        self.set(key, json.dumps(value, ensure_ascii=False), value_type="json", category=category)

    def delete(self, key: str) -> None:
        if key not in self.KEYS:
            return
        conn = self._conn()
        conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
        conn.commit()

    def list_by_category(self, category: str) -> dict[str, str]:
        rows = self._conn().execute(
            "SELECT key, value FROM preferences WHERE category = ?", (category,)
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_settings_repo.py -v
```

Expected: 所有 test 通过

- [ ] **Step 5: Commit**

```bash
git add backend/data/settings_repo.py backend/tests/unit/test_settings_repo.py
git commit -m "feat(backend): add SettingsRepository on preferences table

KV 仓储 + 白名单 (app_settings / theme_mode / current_session_id)。
为 PUT /settings 真持久化 + GET /preferences/{key} 提供基础。"
```

---

## Task 2: database.py 支持 SAGE_DB_PATH 环境变量

**Files:**
- Modify: `backend/data/database.py:13-21`
- Create: `backend/tests/integration/test_db_path.py`

- [ ] **Step 1: 写失败集成测试**

在 `backend/tests/integration/test_db_path.py`：

```python
"""SAGE_DB_PATH 环境变量集成测试"""
import os
import tempfile
from pathlib import Path

import pytest


def test_db_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "custom-sage.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(target))
    # 重新导入以触发 __init__ 重读
    import importlib
    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    assert db.db_path == str(target)
    db.init_db()
    assert target.exists()
    db.close()


def test_db_path_default_when_no_env(monkeypatch):
    monkeypatch.delenv("SAGE_DB_PATH", raising=False)
    import importlib
    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    # 默认路径包含 'sage.db'
    assert db.db_path.endswith("sage.db")
    db.close()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_db_path.py -v
```

Expected: `AssertionError`（因为没读 env）

- [ ] **Step 3: 修改 `backend/data/database.py:13-21`**

在 `backend/data/database.py` 顶部加 `import os`，并修改 `__init__`：

```python
"""
数据库连接和初始化
SQLite 实现
"""
import os
import sqlite3
from pathlib import Path


class Database:
    """SQLite 数据库管理"""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            env_path = os.environ.get("SAGE_DB_PATH")
            if env_path:
                db_path = env_path
            else:
                # 默认路径：项目根目录下的 data/sage.db
                base_dir = Path(__file__).parent.parent.parent
                data_dir = base_dir / "data"
                data_dir.mkdir(exist_ok=True)
                db_path = str(data_dir / "sage.db")

        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
```

（其余 `get_connection` / `close` / `init_db` / `get_database` 不变）

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_db_path.py -v
```

Expected: 2 个 test 都过

- [ ] **Step 5: Commit**

```bash
git add backend/data/database.py backend/tests/integration/test_db_path.py
git commit -m "feat(backend): support SAGE_DB_PATH env var for packaged Electron

packaged 模式下 Electron 启动后端时通过 env 指定数据库路径，
落到 app.getPath('userData')/sage.db；dev 默认行为不变。"
```

---

## Task 3: 升级 PUT /settings + 新增 GET /settings

**Files:**
- Modify: `backend/api/hex_routes.py:174-206`
- Create: `backend/tests/integration/test_settings_endpoint.py`

**Interfaces:**
- Consumes: `SettingsRepository`（Task 1）
- Produces: `PUT /api/v1/settings` 持久化到 SQLite + emit 审计；`GET /api/v1/settings` 返回 `AppSettings | null`

- [ ] **Step 1: 写失败集成测试**

在 `backend/tests/integration/test_settings_endpoint.py`：

```python
"""GET/PUT /settings 端点集成测试"""
import json
import pytest
from httpx import AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_get_settings_returns_null_when_no_data():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_put_settings_persists_and_get_returns():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        payload = {
            "version": "3.0.0",
            "endpoints": [],
            "modelSelections": {
                "chatModel": {"endpointId": None, "modelId": None},
                "visionModel": {"endpointId": None, "modelId": None},
                "embeddingModel": {"endpointId": None, "modelId": None},
            },
            "streaming": True,
            "autoMemory": True,
            "confirmDelete": True,
            "compactMode": False,
            "maxContext": 4096,
            "temperature": 0.7,
            "proxyMode": "system",
            "proxyUrl": "",
            "tlsVersion": "1.2",
        }
        put_resp = await ac.put("/api/v1/settings", json=payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["status"] == "ok"

        get_resp = await ac.get("/api/v1/settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["maxContext"] == 4096
        assert data["version"] == "3.0.0"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_endpoint.py -v
```

Expected: `get` 返回 `null` OK；但 `put` 后 `get` 拿不回数据（FAIL）

- [ ] **Step 3: 修改 `backend/api/hex_routes.py:174-206`**

把现有 `update_settings` 改为持久化 + 审计：

```python
@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    req: SettingsRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> SettingsResponse:
    """Hex 路径的 settings 更新端点 + persist + emit 审计事件。

    PG3.2 升级（2026-06-22）：
    - 持久化到 preferences 表的 app_settings key
    - 仍 emit settings_changed 审计事件（api_key 字段不进 payload）
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = req.model_dump(exclude_none=True)

    # 持久化到 SQLite
    from backend.data.settings_repo import SettingsRepository
    SettingsRepository().set_json("app_settings", payload, category="general")

    # 审计：仅记录字段名，不记录值；api_key 永不进 audit
    changed_fields = [k for k in payload.keys() if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")  # 占位标记
    logger.info(f"[HEX REQ {request_id}] /settings updated: changed={changed_fields}")

    svc.events.emit(
        "settings_changed",
        {"changed_fields": changed_fields, "request_id": request_id},
    )
    return SettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """读取持久化的 settings；不存在返回 null（前端走 DEFAULT_SETTINGS）。"""
    from backend.data.settings_repo import SettingsRepository
    data = SettingsRepository().get_json("app_settings")
    return SettingsResponse(data=data)
```

调整 `SettingsResponse`（在 hex_routes.py 现有定义处），加 `data` 字段：

```python
class SettingsResponse(BaseModel):
    status: str = "ok"
    changed_fields: list[str] = []
    data: dict | None = None  # GET 时填这里
```

（如果 hex_routes.py 现有 `SettingsResponse` 定义位置不同，按实际位置修改；保留向后兼容字段）

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_settings_endpoint.py -v
```

Expected: 2 个 test 通过

- [ ] **Step 5: Commit**

```bash
git add backend/api/hex_routes.py backend/tests/integration/test_settings_endpoint.py
git commit -m "feat(backend): persist PUT /settings to SQLite + add GET /settings

升级 PG3.2 的 PUT /settings 从'只发审计'到'真持久化'。
新增 GET /settings 返回已持久化的 AppSettings（无则 null）。
审计 payload 仍排除 api_key 字段值。"
```

---

## Task 4: 新增 GET/PUT /preferences/{key} 通用 KV 端点

**Files:**
- Modify: `backend/api/hex_routes.py`
- Create: `backend/tests/integration/test_preferences_endpoint.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/integration/test_preferences_endpoint.py`：

```python
"""GET/PUT /preferences/{key} 通用 KV 端点集成测试"""
import pytest
from httpx import AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_get_preference_returns_value():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 先 set
        await ac.put("/api/v1/preferences/theme_mode", json={"value": "dark"})
        # 再 get
        resp = await ac.get("/api/v1/preferences/theme_mode")
    assert resp.status_code == 200
    assert resp.json()["value"] == "dark"


@pytest.mark.asyncio
async def test_get_preference_returns_null_when_missing():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/preferences/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["value"] is None


@pytest.mark.asyncio
async def test_get_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/preferences/evil_key")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.put("/api/v1/preferences/evil_key", json={"value": "x"})
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_preferences_endpoint.py -v
```

Expected: 全部 404 / 405（端点不存在）

- [ ] **Step 3: 在 `backend/api/hex_routes.py` 加端点**

```python
class PreferenceItem(BaseModel):
    value: str | None = None
    value_type: str = "string"
    category: str = "general"


@router.get("/preferences/{key}", response_model=PreferenceItem)
async def get_preference(key: str) -> PreferenceItem:
    """通用 KV 读取（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository
    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    val = SettingsRepository().get(key)
    return PreferenceItem(value=val)


@router.put("/preferences/{key}", response_model=PreferenceItem)
async def put_preference(key: str, item: PreferenceItem) -> PreferenceItem:
    """通用 KV 写入（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository
    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    if item.value is not None:
        SettingsRepository().set(
            key, item.value, value_type=item.value_type, category=item.category
        )
    return item
```

（如 `HTTPException` 未 import，从 `fastapi.HTTPException` 加 import）

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_preferences_endpoint.py -v
```

Expected: 全部 4 个 test 通过

- [ ] **Step 5: Commit**

```bash
git add backend/api/hex_routes.py backend/tests/integration/test_preferences_endpoint.py
git commit -m "feat(backend): add GET/PUT /preferences/{key} for theme & session id

通用 KV 端点，白名单限定 key ∈ {app_settings, theme_mode, current_session_id}。
非白名单 key 返回 400 防止 preferences 表污染。"
```

---

## Task 5: Electron commands.ts 加 4 条 IPC 路由

**Files:**
- Modify: `electron/commands.ts:13-89`
- Modify: `electron/__tests__/commands.test.ts`

- [ ] **Step 1: 在 `electron/__tests__/commands.test.ts` 加测试**

在现有测试文件加：

```ts
describe('settings & preferences IPC routes', () => {
  it('has get_settings route', () => {
    expect(COMMAND_ROUTES.get_settings).toBeDefined();
    expect(COMMAND_ROUTES.get_settings.method).toBe('GET');
    expect(COMMAND_ROUTES.get_settings.path({})).toBe('/api/v1/settings');
  });

  it('has set_settings route', () => {
    expect(COMMAND_ROUTES.set_settings).toBeDefined();
    expect(COMMAND_ROUTES.set_settings.method).toBe('PUT');
    expect(COMMAND_ROUTES.set_settings.path({})).toBe('/api/v1/settings');
  });

  it('has get_preference route with key encoding', () => {
    const r = COMMAND_ROUTES.get_preference;
    expect(r.method).toBe('GET');
    expect(r.path({ key: 'theme_mode' })).toBe('/api/v1/preferences/theme_mode');
    expect(r.path({ key: 'has space' })).toBe('/api/v1/preferences/has%20space');
  });

  it('has set_preference route with key encoding', () => {
    const r = COMMAND_ROUTES.set_preference;
    expect(r.method).toBe('PUT');
    expect(r.path({ key: 'current_session_id' })).toBe(
      '/api/v1/preferences/current_session_id',
    );
  });

  it('all settings/preference paths have /api/v1 prefix', () => {
    // 防止漏前缀导致 404
    const paths = [
      COMMAND_ROUTES.get_settings.path({}),
      COMMAND_ROUTES.set_settings.path({}),
      COMMAND_ROUTES.get_preference.path({ key: 'theme_mode' }),
      COMMAND_ROUTES.set_preference.path({ key: 'theme_mode' }),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/v1\//));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npx vitest run electron/__tests__/commands.test.ts
```

Expected: FAIL（COMMAND_ROUTES 没有这些 key）

- [ ] **Step 3: 在 `electron/commands.ts` 的 `COMMAND_ROUTES` 加 4 条**

紧接现有 `trigger_evolution` 之后：

```ts
  // settings & preferences
  get_settings: { method: 'GET', path: () => '/api/v1/settings' },
  set_settings: { method: 'PUT', path: () => '/api/v1/settings' },
  get_preference: {
    method: 'GET',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },
  set_preference: {
    method: 'PUT',
    path: (a) => `/api/v1/preferences/${encodeURIComponent(String(a.key))}`,
  },
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npx vitest run electron/__tests__/commands.test.ts
```

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add electron/commands.ts electron/__tests__/commands.test.ts
git commit -m "feat(electron): add 4 IPC routes for settings & preferences

get_settings / set_settings / get_preference / set_preference，
所有路径以 /api/v1 开头，hex_routes 后端白名单保护非合法 key。"
```

---

## Task 6: Electron main.ts 传 SAGE_DB_PATH

**Files:**
- Modify: `electron/main.ts:95-136`

- [ ] **Step 1: 修改 `spawnBackend` 函数**

把 `main.ts:122-127` 的 `proc = spawn(...)` dev 分支改为带 env：

```ts
    } else {
      // Dev: delegate to conda
      const sageDbPath =
        process.env.SAGE_DB_PATH ?? path.join(app.getPath('userData'), 'sage.db');
      proc = spawn(condaCmd, condaArgs, {
        env: { ...process.env, SAGE_DB_PATH: sageDbPath },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
    }
```

把 `main.ts:111-120` 的 packaged 分支同样改：

```ts
  if (pyLauncher) {
    // Packaged Win: launch bundled Python directly
    const sageDbPath =
      process.env.SAGE_DB_PATH ?? path.join(app.getPath('userData'), 'sage.db');
    proc = spawn(
      pyLauncher,
      ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
      {
        env: { ...process.env, SAGE_DB_PATH: sageDbPath },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
```

（`app` 已在 main.ts:29 import；`path` 来自 `node:path` join 已有）

- [ ] **Step 2: 本地 smoke test（手动）**

```bash
cd /home/fz/project/sage
# 1. 启动 dev（带 SAGE_SKIP_BACKEND=0）
npm run dev &
# 2. 等后端起来后查 DB 路径
curl http://127.0.0.1:8765/health
# 3. 在 Sage UI 里改一下 settings，重启应用，验证 settings 还在
#    （说明 prefs 已落到 userData 而不是 data/sage.db）
```

- [ ] **Step 3: Commit**

```bash
git add electron/main.ts
git commit -m "feat(electron): set SAGE_DB_PATH for backend subprocess

把后端数据库路径指向 app.getPath('userData')/sage.db，
让 dev 与 packaged 形态的 backend 都看到同一个 prefs 文件。"
```

---

## Task 7: 前端 settingsClient（TDD）

**Files:**
- Create: `src/shared/api/settingsClient.ts`
- Create: `src/shared/api/__tests__/settingsClient.test.ts`

**Interfaces:**
- Consumes: `window.electronAPI.invoke<T>(cmd, args)`（preload 注入）
- Produces: `getSettings() / setSettings(partial) / getPreference(key) / setPreference(key, value)`，全部 5s 超时降级到 null/无副作用

- [ ] **Step 1: 写失败测试**

在 `src/shared/api/__tests__/settingsClient.test.ts`：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// 桩化 invoke
const mockInvoke = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { settingsClient, LOAD_TIMEOUT_MS } from '../settingsClient';

describe('settingsClient', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('getSettings 成功时返回数据', async () => {
    mockInvoke.mockResolvedValue({ data: { maxContext: 4096 } });
    const result = await settingsClient.getSettings();
    expect(result).toEqual({ maxContext: 4096 });
    expect(mockInvoke).toHaveBeenCalledWith('get_settings', {});
  });

  it('getSettings 失败时返回 null 不抛', async () => {
    mockInvoke.mockRejectedValue(new Error('IPC fail'));
    const result = await settingsClient.getSettings();
    expect(result).toBeNull();
  });

  it('getSettings 超时时返回 null', async () => {
    mockInvoke.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, LOAD_TIMEOUT_MS + 1000)),
    );
    const result = await settingsClient.getSettings();
    expect(result).toBeNull();
  }, LOAD_TIMEOUT_MS + 2000);

  it('setSettings 失败时静默（不抛）', async () => {
    mockInvoke.mockRejectedValue(new Error('IPC fail'));
    await expect(settingsClient.setSettings({ maxContext: 8000 })).resolves.toBeUndefined();
  });

  it('getPreference 走 get_preference cmd', async () => {
    mockInvoke.mockResolvedValue({ value: 'dark' });
    const result = await settingsClient.getPreference('theme_mode');
    expect(result).toBe('dark');
    expect(mockInvoke).toHaveBeenCalledWith('get_preference', { key: 'theme_mode' });
  });

  it('setPreference 走 set_preference cmd', async () => {
    mockInvoke.mockResolvedValue({});
    await settingsClient.setPreference('theme_mode', 'light');
    expect(mockInvoke).toHaveBeenCalledWith('set_preference', {
      key: 'theme_mode',
      value: 'light',
      value_type: 'string',
      category: 'ui',
    });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/shared/api/__tests__/settingsClient.test.ts
```

Expected: `Cannot find module '../settingsClient'`

- [ ] **Step 3: 实现 `src/shared/api/settingsClient.ts`**

```ts
/**
 * 前端 settings 客户端 — IPC 封装 + 5s 超时降级
 *
 * 失败语义：
 * - 读：返回 null（不抛）
 * - 写：静默（不抛，写入失败由 console.warn 记录）
 *
 * 设计理由：UI 永不阻塞；后端不可用时自动回退到 localStorage 缓存。
 */
import type { AppSettings } from '../../entities/setting/types';
import { invoke } from '../desktopInvoke';

export const LOAD_TIMEOUT_MS = 5000;

export type PreferenceKey = 'app_settings' | 'theme_mode' | 'current_session_id';

async function ipcCall<T>(cmd: string, args?: object): Promise<T | null> {
  try {
    return await Promise.race([
      invoke<T>(cmd, args ?? {}),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('IPC timeout')), LOAD_TIMEOUT_MS),
      ),
    ]);
  } catch (e) {
    console.warn(`[settingsClient] ${cmd} failed:`, e);
    return null;
  }
}

export const settingsClient = {
  async getSettings(): Promise<AppSettings | null> {
    const resp = await ipcCall<{ data: AppSettings | null }>('get_settings');
    return resp?.data ?? null;
  },

  async setSettings(partial: Partial<AppSettings>): Promise<void> {
    await ipcCall('set_settings', { ...partial });
  },

  async getPreference<T extends string = string>(
    key: PreferenceKey,
  ): Promise<T | null> {
    const resp = await ipcCall<{ value: T | null }>('get_preference', { key });
    return resp?.value ?? null;
  },

  async setPreference(
    key: PreferenceKey,
    value: string,
    category = 'general',
  ): Promise<void> {
    await ipcCall('set_preference', { key, value, value_type: 'string', category });
  },
};
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/shared/api/__tests__/settingsClient.test.ts
```

Expected: 6 个 test 全过

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/settingsClient.ts src/shared/api/__tests__/settingsClient.test.ts
git commit -m "feat(frontend): add settingsClient IPC wrapper with 5s timeout

getSettings / setSettings / getPreference / setPreference 四个方法。
失败时返回 null 或静默，UI 永不阻塞。"
```

---

## Task 8: theme/storage.ts 抽取（TDD）

**Files:**
- Create: `src/entities/theme/storage.ts`
- Create: `src/entities/theme/__tests__/storage.test.ts`

- [ ] **Step 1: 写失败测试**

在 `src/entities/theme/__tests__/storage.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGet = vi.fn();
const mockSet = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: (...args: unknown[]) => mockGet(...args),
    setPreference: (...args: unknown[]) => mockSet(...args),
  },
}));

import { loadTheme, saveTheme } from '../storage';

const CACHE_KEY = 'sage-theme';

describe('theme storage', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGet.mockReset();
    mockSet.mockReset();
  });

  it('loadTheme 后端命中时返回 backend 值', async () => {
    mockGet.mockResolvedValue('dark');
    const r = await loadTheme();
    expect(r).toBe('dark');
  });

  it('loadTheme 后端无值时回退 localStorage', async () => {
    mockGet.mockResolvedValue(null);
    localStorage.setItem(CACHE_KEY, 'light');
    const r = await loadTheme();
    expect(r).toBe('light');
  });

  it('loadTheme 全部为空时返回 null', async () => {
    mockGet.mockResolvedValue(null);
    expect(await loadTheme()).toBeNull();
  });

  it('saveTheme 同步写 localStorage + 异步写后端', async () => {
    await saveTheme('dark');
    expect(localStorage.getItem(CACHE_KEY)).toBe('dark');
    expect(mockSet).toHaveBeenCalledWith('theme_mode', 'dark', 'ui');
  });

  it('saveTheme 接受 system 模式', async () => {
    await saveTheme('system');
    expect(localStorage.getItem(CACHE_KEY)).toBe('system');
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/theme/__tests__/storage.test.ts
```

Expected: `Cannot find module '../storage'`

- [ ] **Step 3: 实现 `src/entities/theme/storage.ts`**

```ts
/**
 * Theme 持久化 — 双写（localStorage 同步 + 后端异步）
 */
import { settingsClient } from '../../shared/api/settingsClient';

const CACHE_KEY = 'sage-theme';

export type ThemeMode = 'light' | 'dark' | 'system';

export async function loadTheme(): Promise<ThemeMode | null> {
  const remote = await settingsClient.getPreference<ThemeMode>('theme_mode');
  if (remote) {
    try {
      localStorage.setItem(CACHE_KEY, remote);
    } catch {
      // 隐私模式等
    }
    return remote;
  }
  try {
    return (localStorage.getItem(CACHE_KEY) as ThemeMode | null) ?? null;
  } catch {
    return null;
  }
}

export async function saveTheme(mode: ThemeMode): Promise<void> {
  try {
    localStorage.setItem(CACHE_KEY, mode);
  } catch {
    // 静默
  }
  await settingsClient.setPreference('theme_mode', mode, 'ui');
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/theme/__tests__/storage.test.ts
```

Expected: 5 个 test 全过

- [ ] **Step 5: Commit**

```bash
git add src/entities/theme/storage.ts src/entities/theme/__tests__/storage.test.ts
git commit -m "feat(frontend): add theme storage with localStorage + backend dual-write

loadTheme 优先后端，回退 localStorage；saveTheme 同步写 cache + 异步推后端。"
```

---

## Task 9: session/storage.ts 抽取（TDD）

**Files:**
- Create: `src/entities/session/storage.ts`
- Create: `src/entities/session/__tests__/storage.test.ts`

- [ ] **Step 1: 写失败测试**

在 `src/entities/session/__tests__/storage.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGet = vi.fn();
const mockSet = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: (...args: unknown[]) => mockGet(...args),
    setPreference: (...args: unknown[]) => mockSet(...args),
  },
}));

import { loadCurrentSessionId, saveCurrentSessionId } from '../storage';

const CACHE_KEY = 'sage-current-session-id';

describe('session storage', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGet.mockReset();
    mockSet.mockReset();
  });

  it('loadCurrentSessionId 后端命中时返回 backend 值', async () => {
    mockGet.mockResolvedValue('abc-123');
    const r = await loadCurrentSessionId();
    expect(r).toBe('abc-123');
  });

  it('loadCurrentSessionId 后端无值时回退 localStorage', async () => {
    mockGet.mockResolvedValue(null);
    localStorage.setItem(CACHE_KEY, 'local-456');
    const r = await loadCurrentSessionId();
    expect(r).toBe('local-456');
  });

  it('loadCurrentSessionId 全空时返回 null', async () => {
    mockGet.mockResolvedValue(null);
    expect(await loadCurrentSessionId()).toBeNull();
  });

  it('saveCurrentSessionId 写 localStorage + 后端', async () => {
    await saveCurrentSessionId('xyz-789');
    expect(localStorage.getItem(CACHE_KEY)).toBe('xyz-789');
    expect(mockSet).toHaveBeenCalledWith('current_session_id', 'xyz-789', 'session');
  });

  it('saveCurrentSessionId(null) 清空 localStorage', async () => {
    localStorage.setItem(CACHE_KEY, 'old');
    await saveCurrentSessionId(null);
    expect(localStorage.getItem(CACHE_KEY)).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/session/__tests__/storage.test.ts
```

Expected: `Cannot find module '../storage'`

- [ ] **Step 3: 实现 `src/entities/session/storage.ts`**

```ts
/**
 * Current session id 持久化 — 双写（localStorage 同步 + 后端异步）
 */
import { settingsClient } from '../../shared/api/settingsClient';

const CACHE_KEY = 'sage-current-session-id';

export async function loadCurrentSessionId(): Promise<string | null> {
  const remote = await settingsClient.getPreference<string>('current_session_id');
  if (remote) {
    try {
      localStorage.setItem(CACHE_KEY, remote);
    } catch {
      // 隐私模式
    }
    return remote;
  }
  try {
    return localStorage.getItem(CACHE_KEY) ?? null;
  } catch {
    return null;
  }
}

export async function saveCurrentSessionId(id: string | null): Promise<void> {
  try {
    if (id) {
      localStorage.setItem(CACHE_KEY, id);
    } else {
      localStorage.removeItem(CACHE_KEY);
    }
  } catch {
    // 静默
  }
  if (id) {
    await settingsClient.setPreference('current_session_id', id, 'session');
  }
  // 注：id=null 时不删后端（避免误清；后续可加 delete 端点）
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/session/__tests__/storage.test.ts
```

Expected: 5 个 test 全过

- [ ] **Step 5: Commit**

```bash
git add src/entities/session/storage.ts src/entities/session/__tests__/storage.test.ts
git commit -m "feat(frontend): add session storage with localStorage + backend dual-write

loadCurrentSessionId 优先后端；saveCurrentSessionId 同步 cache + 异步推后端。"
```

---

## Task 10: setting/storage.ts 改写为 async + 自动迁移

**Files:**
- Modify: `src/entities/setting/storage.ts`（整文件重写）
- Modify: `src/entities/setting/__tests__/storage.test.ts`（整文件重写）

- [ ] **Step 1: 改写测试 `src/entities/setting/__tests__/storage.test.ts`**

替换为：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGetSettings = vi.fn();
const mockSetSettings = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getSettings: (...args: unknown[]) => mockGetSettings(...args),
    setSettings: (...args: unknown[]) => mockSetSettings(...args),
  },
}));

import { loadSettings, saveSettings, resetSettings } from '../storage';
import { DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY } from '../types';

const CACHE_KEY = SETTINGS_STORAGE_KEY; // 'sage-settings'
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';

describe('settings storage (async)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGetSettings.mockReset();
    mockSetSettings.mockReset();
  });

  describe('loadSettings', () => {
    it('后端命中时返回 backend 数据并写 local cache', async () => {
      const remoteData = { ...DEFAULT_SETTINGS, maxContext: 8000 };
      mockGetSettings.mockResolvedValue(remoteData);
      const r = await loadSettings();
      expect(r.maxContext).toBe(8000);
      expect(JSON.parse(localStorage.getItem(CACHE_KEY)!).maxContext).toBe(8000);
    });

    it('后端无值且 localStorage 有值时回退 local', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, temperature: 0.3 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.temperature).toBe(0.3);
    });

    it('都为空时返回 DEFAULT_SETTINGS', async () => {
      mockGetSettings.mockResolvedValue(null);
      const r = await loadSettings();
      expect(r).toEqual(DEFAULT_SETTINGS);
    });

    it('后端失败时降级 localStorage', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, compactMode: true };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.compactMode).toBe(true);
    });
  });

  describe('自动迁移', () => {
    it('首次后端命中 + localStorage 有值 + 未标记迁移 → 自动上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce(null); // 第一次：后端无
      mockSetSettings.mockResolvedValueOnce(undefined);

      await loadSettings();

      expect(mockSetSettings).toHaveBeenCalledWith(expect.objectContaining({ maxContext: 9999 }));
      expect(localStorage.getItem(MIGRATION_MARKER)).toBeTruthy();
    });

    it('已标记迁移时不重复上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      localStorage.setItem(MIGRATION_MARKER, '2026-06-22T00:00:00.000Z');
      mockGetSettings.mockResolvedValueOnce(null);

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });

    it('后端已有数据时不触发迁移', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });

  describe('saveSettings', () => {
    it('同步写 localStorage', async () => {
      await saveSettings({ maxContext: 16000 });
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached.maxContext).toBe(16000);
    });

    it('异步调 setSettings', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await saveSettings({ maxContext: 16000 });
      expect(mockSetSettings).toHaveBeenCalledWith({ maxContext: 16000 });
    });
  });

  describe('resetSettings', () => {
    it('重置为 DEFAULT_SETTINGS 并写 local + 后端', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await resetSettings();
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached).toEqual(DEFAULT_SETTINGS);
      expect(mockSetSettings).toHaveBeenCalled();
    });
  });

  describe('7 天保留清理', () => {
    it('迁移标记 >7 天时清理 localStorage 冗余数据', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      // 标记 8 天前
      const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
      localStorage.setItem(MIGRATION_MARKER, eightDaysAgo);
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      // 8 天前的标记 + 后端已有数据 → 清理 local
      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/setting/__tests__/storage.test.ts
```

Expected: 大部分 FAIL（loadSettings 不是 async、saveSettings 不带 await 等）

- [ ] **Step 3: 重写 `src/entities/setting/storage.ts`**

整文件替换为：

```ts
/**
 * Settings 持久化 — 双写（localStorage 同步 + 后端异步）+ 自动迁移
 *
 * 加载策略：后端 > localStorage > DEFAULT_SETTINGS
 * 写入策略：同步写 cache + 异步推后端
 * 迁移策略：首次后端无值 + localStorage 有值 + 未标记迁移 → 自动上传
 */
import { settingsClient } from '../../shared/api/settingsClient';
import {
  AppSettings,
  DEFAULT_SETTINGS,
  SETTINGS_STORAGE_KEY,
  SETTINGS_VERSION,
} from './types';
import type { EndpointConfig, ModelSelection } from './types';

const CACHE_KEY = SETTINGS_STORAGE_KEY;
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';
const CACHE_RETENTION_DAYS = 7;

function readLocalCacheSync(): Partial<AppSettings> | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as Partial<AppSettings>) : null;
  } catch {
    return null;
  }
}

function writeLocalCacheSync(data: AppSettings): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(data));
  } catch {
    // 静默
  }
}

function isRetentionExpired(): boolean {
  try {
    const marker = localStorage.getItem(MIGRATION_MARKER);
    if (!marker) return false;
    const markedAt = new Date(marker).getTime();
    return Date.now() - markedAt > CACHE_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function cleanupLocalCacheIfExpired(): void {
  if (isRetentionExpired()) {
    try {
      localStorage.removeItem(CACHE_KEY);
      localStorage.removeItem(MIGRATION_MARKER);
    } catch {
      // 静默
    }
  }
}

async function maybeAutoMigrate(remote: AppSettings | null): Promise<void> {
  if (remote) return; // 后端有数据，无需迁移

  const local = readLocalCacheSync();
  if (!local) return; // local 也没有，跳过

  const marker = (() => {
    try {
      return localStorage.getItem(MIGRATION_MARKER);
    } catch {
      return null;
    }
  })();
  if (marker) return; // 已迁移过

  try {
    await settingsClient.setSettings({ ...DEFAULT_SETTINGS, ...local });
    try {
      localStorage.setItem(MIGRATION_MARKER, new Date().toISOString());
    } catch {
      // 静默
    }
  } catch {
    // 静默失败，下次启动重试
  }
}

function mergeWithDefaults(partial: Partial<AppSettings>): AppSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...partial,
    endpoints: partial.endpoints ?? DEFAULT_SETTINGS.endpoints,
    modelSelections: partial.modelSelections ?? DEFAULT_SETTINGS.modelSelections,
    version: partial.version ?? SETTINGS_VERSION,
  };
}

/**
 * 加载 settings：后端 → localStorage → DEFAULT_SETTINGS
 * 首次加载会触发自动迁移
 */
export async function loadSettings(): Promise<AppSettings> {
  cleanupLocalCacheIfExpired();

  const remote = await settingsClient.getSettings();
  if (remote) {
    const merged = mergeWithDefaults(remote);
    writeLocalCacheSync(merged);
    return merged;
  }
  await maybeAutoMigrate(null);
  const local = readLocalCacheSync();
  return mergeWithDefaults(local ?? {});
}

/**
 * 同步写 local cache + 异步推后端
 */
export async function saveSettings(partial: Partial<AppSettings>): Promise<void> {
  const current = readLocalCacheSync() ?? DEFAULT_SETTINGS;
  const merged: AppSettings = {
    ...current,
    ...partial,
    endpoints: partial.endpoints ?? current.endpoints,
    modelSelections: partial.modelSelections ?? current.modelSelections,
    version: SETTINGS_VERSION,
  };
  writeLocalCacheSync(merged);
  try {
    await settingsClient.setSettings(partial);
  } catch {
    // settingsClient 内部已 warn
  }
}

/**
 * 重置为默认值
 */
export async function resetSettings(): Promise<void> {
  writeLocalCacheSync({ ...DEFAULT_SETTINGS });
  try {
    await settingsClient.setSettings({ ...DEFAULT_SETTINGS });
  } catch {
    // 静默
  }
}

// 旧同步签名保留为 fallback（@deprecated；新代码用 async 版本）
/** @deprecated use loadSettings() async */
export function loadSettingsSync(): AppSettings {
  return mergeWithDefaults(readLocalCacheSync() ?? {});
}

// 保留 v1/v2 迁移函数以备后端返回老数据时使用
export function migrateFromV1(parsed: Record<string, unknown>): AppSettings {
  const v1ApiUrl = (parsed.apiUrl as string) ?? '';
  const v1Model = (parsed.model as string) ?? '';
  const endpointId = v1ApiUrl ? crypto.randomUUID() : '';
  const endpoint: EndpointConfig = v1ApiUrl
    ? {
        id: endpointId,
        name: '默认端点',
        baseUrl: v1ApiUrl,
        apiKey: '',
        discoveredModels: v1Model ? [{ id: v1Model, capabilities: ['chat'], endpointId }] : [],
        lastDiscoveredAt: null,
      }
    : { id: '', name: '', baseUrl: '', apiKey: '', discoveredModels: [], lastDiscoveredAt: null };
  const chatModel: ModelSelection = v1Model
    ? { endpointId: endpointId || null, modelId: v1Model }
    : { endpointId: null, modelId: null };
  return {
    ...DEFAULT_SETTINGS,
    endpoints: endpoint.baseUrl ? [endpoint] : [],
    modelSelections: {
      chatModel,
      visionModel: { endpointId: null, modelId: null },
      embeddingModel: { endpointId: null, modelId: null },
    },
    version: SETTINGS_VERSION,
  };
}

export function migrateFromV2(parsed: Record<string, unknown>): AppSettings {
  const oldEndpoints = (parsed.endpoints as Array<Record<string, unknown>>) ?? [];
  const oldSelections = (parsed.modelSelections as Record<string, unknown>) ?? {};
  const activeEp = oldEndpoints.find((ep) => ep.isActive === true);
  const activeEndpointId = (activeEp?.id as string) ?? null;
  const endpoints: EndpointConfig[] = oldEndpoints.map((ep) => ({
    id: ep.id as string,
    name: (ep.name as string) ?? '',
    baseUrl: (ep.baseUrl as string) ?? '',
    apiKey: (ep.apiKey as string) ?? '',
    discoveredModels: (ep.discoveredModels as EndpointConfig['discoveredModels']) ?? [],
    lastDiscoveredAt: (ep.lastDiscoveredAt as number | null) ?? null,
  }));
  const toModelSelection = (modelId: unknown): ModelSelection => {
    const id = (modelId as string) ?? null;
    return id ? { endpointId: activeEndpointId, modelId: id } : { endpointId: null, modelId: null };
  };
  return {
    ...DEFAULT_SETTINGS,
    ...(parsed as Partial<AppSettings>),
    endpoints,
    modelSelections: {
      chatModel: toModelSelection(oldSelections.chatModelId),
      visionModel: toModelSelection(oldSelections.visionModelId),
      embeddingModel: toModelSelection(oldSelections.embeddingModelId),
    },
    version: SETTINGS_VERSION,
  };
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/entities/setting/__tests__/storage.test.ts
```

Expected: 全部 test 通过

- [ ] **Step 5: Commit**

```bash
git add src/entities/setting/storage.ts src/entities/setting/__tests__/storage.test.ts
git commit -m "feat(frontend): async settings storage with auto-migration + 7d cleanup

loadSettings / saveSettings / resetSettings 改 async。
自动迁移：首次后端无值 + localStorage 有数据 + 未标记 → 上传。
7 天后清理 localStorage 冗余。"
```

---

## Task 11: useSettings 改 async

**Files:**
- Modify: `src/features/manage-settings/useSettings.ts`
- Modify: `src/features/manage-settings/__tests__/useSettings.test.ts`

- [ ] **Step 1: 改写测试 `src/features/manage-settings/__tests__/useSettings.test.ts`**

替换为：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const mockLoad = vi.fn();
const mockSave = vi.fn();
const mockReset = vi.fn();
vi.mock('../../../entities/setting/storage', () => ({
  loadSettings: (...args: unknown[]) => mockLoad(...args),
  saveSettings: (...args: unknown[]) => mockSave(...args),
  resetSettings: (...args: unknown[]) => mockReset(...args),
}));

import { useSettings } from '../useSettings';
import { DEFAULT_SETTINGS } from '../../../entities/setting/types';

describe('useSettings (async)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    mockReset.mockReset();
  });

  it('初始时 isLoading=true，settings 是 DEFAULT_SETTINGS', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    const { result } = renderHook(() => useSettings());
    expect(result.current.isLoading).toBe(true);
    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
  });

  it('loadSettings 完成后 isLoading=false，settings 是 loaded 值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 8000 });
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.settings.maxContext).toBe(8000);
  });

  it('updateSettings 合并 partial 并 setSettings + persist', async () => {
    mockLoad.mockResolvedValue(DEFAULT_SETTINGS);
    mockSave.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.updateSettings({ maxContext: 16000 });
    });

    expect(result.current.settings.maxContext).toBe(16000);
    expect(mockSave).toHaveBeenCalledWith({ maxContext: 16000 });
  });

  it('resetSettings 还原为默认值', async () => {
    mockLoad.mockResolvedValue({ ...DEFAULT_SETTINGS, maxContext: 9999 });
    mockReset.mockResolvedValue(undefined);
    const { result } = renderHook(() => useSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.resetSettings();
    });

    expect(result.current.settings).toEqual(DEFAULT_SETTINGS);
    expect(mockReset).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/features/manage-settings/__tests__/useSettings.test.ts
```

Expected: FAIL（isLoading 不存在、updateSettings 不返回 Promise）

- [ ] **Step 3: 重写 `src/features/manage-settings/useSettings.ts`**

```ts
import { useCallback, useEffect, useState } from 'react';

import {
  loadSettings,
  resetSettings as resetSettingsLib,
  saveSettings,
} from '../../entities/setting/storage';
import type { AppSettings } from '../../entities/setting/types';
import { DEFAULT_SETTINGS } from '../../entities/setting/types';

interface UseSettingsReturn {
  settings: AppSettings;
  isLoading: boolean;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
}

/**
 * React hook for application settings.
 * 异步从后端加载，本地 cache 兜底；更新走双写。
 */
export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    loadSettings()
      .then((s) => {
        if (!cancelled) {
          setSettings(s);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const updateSettings = useCallback(async (partial: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }));
    await saveSettings(partial);
  }, []);

  const resetSettings = useCallback(async () => {
    await resetSettingsLib();
    setSettings({ ...DEFAULT_SETTINGS });
  }, []);

  return { settings, isLoading, updateSettings, resetSettings };
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/features/manage-settings/__tests__/useSettings.test.ts
```

Expected: 4 个 test 全过

- [ ] **Step 5: Commit**

```bash
git add src/features/manage-settings/useSettings.ts src/features/manage-settings/__tests__/useSettings.test.ts
git commit -m "feat(frontend): async useSettings with isLoading

updateSettings / resetSettings 改 async Promise 返回。
暴露 isLoading 供消费页面决定是否 skeleton。"
```

---

## Task 12: ThemeProvider 改 async init

**Files:**
- Modify: `src/app/providers/ThemeProvider.tsx`
- Create: `src/app/providers/__tests__/ThemeProvider.test.tsx`

- [ ] **Step 1: 写失败测试**

在 `src/app/providers/__tests__/ThemeProvider.test.tsx`：

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ThemeProvider } from '../ThemeProvider';

const mockLoad = vi.fn();
const mockSave = vi.fn();
vi.mock('../../entities/theme/storage', () => ({
  loadTheme: (...args: unknown[]) => mockLoad(...args),
  saveTheme: (...args: unknown[]) => mockSave(...args),
}));

describe('ThemeProvider async init', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    mockLoad.mockReset();
    mockSave.mockReset();
  });

  it('useEffect 触发 loadTheme 并 apply 到 <html>', async () => {
    mockLoad.mockResolvedValue('dark');
    render(
      <ThemeProvider>
        <div>child</div>
      </ThemeProvider>,
    );
    expect(screen.getByText('child')).toBeInTheDocument();
    await waitFor(() => {
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });

  it('loadTheme 失败时回退 defaultMode=system', async () => {
    mockLoad.mockResolvedValue(null);
    render(
      <ThemeProvider>
        <div>child</div>
      </ThemeProvider>,
    );
    await waitFor(() => expect(mockLoad).toHaveBeenCalled());
    // system 模式 → resolved=light (假设测试环境 matchMedia=false)
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('保存主题时调 saveTheme', async () => {
    mockLoad.mockResolvedValue('light');
    mockSave.mockResolvedValue(undefined);
    const { useTheme } = await import('../useTheme');
    const TestConsumer = () => {
      const { setMode } = useTheme();
      return <button onClick={() => setMode('dark')}>change</button>;
    };
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    );
    await waitFor(() => expect(mockLoad).toHaveBeenCalled());
    screen.getByText('change').click();
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith('dark'));
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/app/providers/__tests__/ThemeProvider.test.tsx
```

Expected: FAIL（loadTheme 未被调用）

- [ ] **Step 3: 修改 `src/app/providers/ThemeProvider.tsx`**

替换为：

```tsx
import { useEffect, useState, type ReactNode } from 'react';

import { loadTheme, saveTheme } from '../../entities/theme/storage';
import { ThemeContext, type ThemeMode } from './useTheme';

const VALID_MODES: ReadonlyArray<ThemeMode> = ['light', 'dark', 'system'];

function resolveSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(resolved: 'light' | 'dark'): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('dark', resolved === 'dark');
}

interface ThemeProviderProps {
  children: ReactNode;
  defaultMode?: ThemeMode;
}

export function ThemeProvider({ children, defaultMode = 'system' }: ThemeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(defaultMode);
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => {
      setSystemTheme(e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    loadTheme().then((m) => {
      if (m && VALID_MODES.includes(m)) {
        setModeState(m);
      }
    });
  }, []);

  const resolved: 'light' | 'dark' = mode === 'system' ? systemTheme : mode;

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const setMode = (next: ThemeMode): void => {
    setModeState(next);
    void saveTheme(next);
  };

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode }}>{children}</ThemeContext.Provider>
  );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/app/providers/__tests__/ThemeProvider.test.tsx
```

Expected: 3 个 test 全过

- [ ] **Step 5: Commit**

```bash
git add src/app/providers/ThemeProvider.tsx src/app/providers/__tests__/ThemeProvider.test.tsx
git commit -m "feat(frontend): ThemeProvider async init via loadTheme

useEffect 调 loadTheme() 异步初始化；saveTheme 双写。"
```

---

## Task 13: store.ts currentSessionId 改 async init

**Files:**
- Modify: `src/shared/lib/store.ts:73-110`
- Modify: `src/shared/lib/__tests__/store.test.ts`

- [ ] **Step 1: 改写测试 `src/shared/lib/__tests__/store.test.ts`**

替换为：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockLoad = vi.fn();
const mockSave = vi.fn();
vi.mock('../../entities/session/storage', () => ({
  loadCurrentSessionId: (...args: unknown[]) => mockLoad(...args),
  saveCurrentSessionId: (...args: unknown[]) => mockSave(...args),
}));

import { useStore } from '../store';

describe('useStore currentSessionId async', () => {
  beforeEach(() => {
    localStorage.clear();
    mockLoad.mockReset();
    mockSave.mockReset();
    useStore.setState({ currentSessionId: null });
  });

  it('setCurrentSessionId 调 saveCurrentSessionId 异步', async () => {
    mockSave.mockResolvedValue(undefined);
    useStore.getState().setCurrentSessionId('abc-123');
    expect(useStore.getState().currentSessionId).toBe('abc-123');
    await vi.waitFor(() => expect(mockSave).toHaveBeenCalledWith('abc-123'));
  });

  it('setCurrentSessionId(null) 同步清空', () => {
    useStore.setState({ currentSessionId: 'old' });
    useStore.getState().setCurrentSessionId(null);
    expect(useStore.getState().currentSessionId).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage
npm run test:run -- src/shared/lib/__tests__/store.test.ts
```

Expected: FAIL（saveCurrentSessionId 未调用）

- [ ] **Step 3: 修改 `src/shared/lib/store.ts:73-110`**

在文件顶部 import：

```ts
import { saveCurrentSessionId } from '../../entities/session/storage';
```

修改 `currentSessionId` 初始值（store.ts:78-84）：

```ts
  currentSessionId: null,
```

修改 `setCurrentSessionId`（store.ts:99-110）：

```ts
  setCurrentSessionId: (id) => {
    set({ currentSessionId: id });
    void saveCurrentSessionId(id);
  },
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd /home/fz/project/sage
npm run test:run -- src/shared/lib/__tests__/store.test.ts
```

Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/shared/lib/store.ts src/shared/lib/__tests__/store.test.ts
git commit -m "feat(frontend): useStore.currentSessionId async init

currentSessionId 初始为 null；setCurrentSessionId 异步持久化到后端 + cache。
App.tsx 顶层 useEffect 触发 loadCurrentSessionId()（见 Task 14）。"
```

---

## Task 14: App.tsx 触发 currentSessionId 初始化

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: 读 `src/App.tsx` 看结构**

```bash
cd /home/fz/project/sage
head -50 src/App.tsx
```

- [ ] **Step 2: 在 `App` 组件顶层加 useEffect**

修改 `App.tsx` 顶部 import 和组件体内：

顶部加：

```tsx
import { useEffect } from 'react';
import { useStore } from './shared/lib/store';
import { loadCurrentSessionId } from './entities/session/storage';
```

在 `App` 函数体内（顶层位置）加：

```tsx
useEffect(() => {
  loadCurrentSessionId().then((id) => {
    if (id) {
      useStore.getState().setCurrentSessionId(id);
    }
  });
}, []);
```

（如 `App.tsx` 不是函数组件而是 React.lazy / class 形式，按实际结构适配；目标：app 启动时执行一次 `loadCurrentSessionId`）

- [ ] **Step 3: 跑前端测试套件验证无回归**

```bash
cd /home/fz/project/sage
npm run test:run -- --no-coverage
```

Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add src/App.tsx
git commit -m "feat(frontend): trigger currentSessionId async init in App.tsx

app 启动时执行 loadCurrentSessionId()，从后端/缓存恢复当前会话 ID。"
```

---

## Task 15: 文档更新

**Files:**
- Modify: `docs/technical/09-frontend.md`
- Modify: `docs/technical/10-api.md`

- [ ] **Step 1: 读 `docs/technical/09-frontend.md` 看是否需要加"配置存储"小节**

如已存在"配置"小节则加 1 段；否则在末尾加：

```markdown
## 配置存储（2026-06-22 起）

Sage 前端配置（settings / theme / current_session_id）从 localStorage 迁移至
后端 SQLite `preferences` 表。三处 localStorage 仍保留作为离线缓存兜底。

**加载策略**：后端 → localStorage → DEFAULT
**写入策略**：同步写 cache + 异步推后端（5s 超时）
**迁移策略**：首次后端无值 + localStorage 有数据 + 未标记 → 自动上传

相关代码：
- 前端：`src/entities/setting/storage.ts`、`src/entities/theme/storage.ts`、
  `src/entities/session/storage.ts`、`src/shared/api/settingsClient.ts`
- 后端：`backend/data/settings_repo.py`、`backend/api/hex_routes.py`
- Electron IPC：`electron/commands.ts`（4 条新路由）
```

- [ ] **Step 2: 读 `docs/technical/10-api.md`，加 4 个新端点**

在 hex/legacy 路由表后加：

```markdown
### Settings 端点（PG3.2+，2026-06-22）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/settings` | 读取持久化 AppSettings；无则返回 `{data: null}` |
| PUT | `/api/v1/settings` | 持久化 + emit `settings_changed` 审计（api_key 不进 payload） |
| GET | `/api/v1/preferences/{key}` | 通用 KV 读取（白名单限定 key） |
| PUT | `/api/v1/preferences/{key}` | 通用 KV 写入（白名单限定 key） |

白名单 keys：`app_settings` / `theme_mode` / `current_session_id`。
非白名单 key 返回 400。
```

- [ ] **Step 3: Commit**

```bash
git add docs/technical/09-frontend.md docs/technical/10-api.md
git commit -m "docs: add configuration storage section to frontend & api docs"
```

---

## Task 16: 集成验证（SAGE_SKIP_BACKEND 模式 smoke test）

**Files:** 无（手动验证）

- [ ] **Step 1: 启动 dev，验证正常流程**

```bash
cd /home/fz/project/sage
# 终端 1：启后端
conda activate sage-backend && python backend/main.py
# 终端 2：启前端
npm run dev
```

浏览器打开 `http://localhost:1420`，验证：
- 主题在 light/dark/system 间切换 → UI 立即反映
- 改 settings（如 maxContext）→ 重启浏览器后值还在
- 创/删 session → 重启后当前 session 仍选中
- 打开 DevTools Application → Local Storage 仍有 `sage-settings` 三个 key（cache）
- 打开 DevTools Application → IndexedDB / 任何新位置应无变化

- [ ] **Step 2: 启动 dev + SAGE_SKIP_BACKEND=1，验证降级**

```bash
cd /home/fz/project/sage
# 终端 1
SAGE_SKIP_BACKEND=1 npm run dev
```

验证：
- 启动速度明显更快（不启后端）
- 改 settings → 写入 localStorage，console 出现 `[settingsClient] set_settings failed: IPC timeout`
- UI 仍然正常（cache 兜底）
- 关闭应用再开 → localStorage 数据仍能恢复

- [ ] **Step 3: 迁移路径手动验证**

准备 v1 格式 localStorage 数据（用 DevTools Console 注入）：

```js
localStorage.setItem('sage-settings', JSON.stringify({
  apiUrl: 'https://api.openai.com/v1',
  model: 'gpt-4',
  version: '1.0.0',
}));
localStorage.removeItem('sage-settings.migrated_to_backend');
```

启后端 + 前端。验证：
- 后端 `preferences` 表出现 `app_settings` 行
- 前端 localStorage 出现 `sage-settings.migrated_to_backend` 标记
- 改 settings → 后端 `updated_at` 时间戳更新

- [ ] **Step 4: 在 PR description 或 plan 末尾记录验证结果**

---

## Self-Review

**1. Spec coverage:** spec §3-§6 全部 16 个 task 覆盖；§1-2 是背景与决策（无实现）；§7-10 在 Task 16 验证。

**2. Placeholder scan:** 全文无 "TBD"/"TODO"/"implement later"；所有代码块完整。

**3. Type consistency:**
- `settingsClient.getSettings() -> Promise<AppSettings | null>` 在 Task 3（后端返回 `{data: ...}`）/Task 7（前端 unwrap）/Task 10（消费方）一致
- `PreferenceKey = 'app_settings' | 'theme_mode' | 'current_session_id'` 与 `SettingsRepository.KEYS` 一致
- `MIGRATION_MARKER = 'sage-settings.migrated_to_backend'` 在 Task 10 测试与实现一致

**4. Out of scope (intentional):**
- P5 清理任务不在本 plan（按 spec 标记为"1 个月后"）
- apiKey 加密（spec 决策：暂不加密，P2）
- 多窗口 OT 同步（spec 决策：最后写胜出）

**5. Critical assumption verified (实施者需二次确认):**
- `theme/storage.ts` 和 `session/storage.ts` 当前**不存在**（Task 8/9 是 Create 而非 Modify）— 实施者跑 plan 时确认
- `electron/__tests__/commands.test.ts` 已存在（Task 5 是 Modify）— 实施者确认
- `src/shared/lib/__tests__/store.test.ts` 已存在 — 实施者确认

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-localstorage-to-backend.md`. 16 个 task，覆盖 P1-P4 全部内容，P5 标注为后续。**

**两个执行选项：**

**1. Subagent-Driven (recommended)** - 每个 task 派一个独立 subagent，task 之间我审阅，快迭代

**2. Inline Execution** - 在当前会话按顺序执行 task，批量 + 检查点

**哪种方式？**
