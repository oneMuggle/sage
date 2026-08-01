# Artifacts Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Sage Chat 页面添加右侧抽屉面板(Progress + Artifacts),让用户能查看 AI 工具调用进度和生成的文件产物。

**Architecture:** 全栈追踪方案。后端在写文件工具(`WriteFileTool`)执行成功后,通过 `current_tool_context()` 拿到 session_id,记录产物到 `artifacts` 表;暴露 3 个 REST API(list/content/reveal)。前端在 Chat 页面右侧加抽屉式 RightPanel,内含 Progress 面板(实时显示流式状态)和 Artifacts 面板(文件列表 + 多格式预览)。

**Tech Stack:**
- 后端: Python 3.11, FastAPI, **同步 sqlite3**(项目现有 `Database` 类,非 aiosqlite)
- 前端: React 18, TypeScript, Vitest, @testing-library/react
- 测试: pytest(后端,位于 `backend/tests/`), vitest(前端)

## Global Constraints

- 后端 Python 必须在 `sage-backend` conda 环境运行:`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest ...`
- **数据库是同步 sqlite3**:`backend/data/database.py` 的 `Database` 类,`get_database() -> Database`(同步),`db.get_connection()` 返回 `sqlite3.Connection`,`row_factory = sqlite3.Row`(行按列名访问)。迁移是 `init_db()` 内的内联 `CREATE TABLE IF NOT EXISTS`,**没有独立 migration 文件**。
- **数据模块命名约定 `*_repo.py`**(如 `session_repo.py`),用 `@dataclass` 模型 + `from_row`/`to_dict`,同步函数。本功能数据模块命名为 `artifact_repo.py`。
- **后端测试位于 `backend/tests/{unit,api,integration}/`**,共享 fixture 在 `backend/tests/conftest.py`:autouse `setup_test_db` 给每个测试独立临时 DB;异步 HTTP 客户端 fixture 名为 **`client`**(httpx AsyncClient + ASGITransport)。
- **路由注册模式**:router 自身 `prefix` 不含 `/api/v1`(如 `APIRouter(prefix="/sessions/{session_id}/artifacts")`),在 `backend/main.py` 用 `app.include_router(router, prefix="/api/v1")` 添加。
- **前端 `ToolCall` 类型**(`src/shared/lib/store.ts`):`{ id?: string; name: string; args: Record<string, unknown>; result?: string; metadata?: {...} }`。**没有 `status` 字段**,`id` 可选。
- 前端测试覆盖率 ≥80%;前端测试遵循 `src/widgets/chat/__tests__/` 现有模式。
- 所有 commit 遵循 conventional commits 格式。
- API 路径最终为 `/api/v1/sessions/{session_id}/artifacts...`。
- 文件大小限制:文本预览 500KB(截断),图片 10MB(超限报错)。

---

## Task 1: 数据库 — 在 init_db() 添加 artifacts 表

**Files:**
- Modify: `backend/data/database.py`(在 `init_db()` 内追加 `CREATE TABLE IF NOT EXISTS artifacts`)
- Test: `backend/tests/unit/test_artifacts_schema.py`

**Interfaces:**
- Produces: `artifacts` 表 `(id TEXT PK, session_id TEXT NOT NULL, tool_call_id TEXT, path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER DEFAULT 0, created_at INTEGER NOT NULL)` + 索引 `idx_artifacts_session(session_id, created_at DESC)`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_artifacts_schema.py
from backend.data.database import get_database


def test_artifacts_table_exists():
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["name"] == "artifacts"


def test_artifacts_table_columns():
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(artifacts)")
    cols = {r["name"] for r in cursor.fetchall()}
    assert {"id", "session_id", "tool_call_id", "path", "name", "kind", "size", "created_at"} <= cols
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifacts_schema.py -v`
Expected: FAIL(表不存在)

- [ ] **Step 3: 在 init_db() 追加建表语句**

读取 `backend/data/database.py`,在 `init_db()` 方法内、其他 `CREATE TABLE IF NOT EXISTS` 语句附近(如 `tool_usage` 表之后)追加:

```python
        # 产物表:追踪 AI 工具调用(write_file)生成的文件
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_call_id TEXT,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_session
            ON artifacts(session_id, created_at DESC)
        """)
```

注意:遵循该方法内既有缩进与 `cursor.execute` 风格;若方法末尾有 `conn.commit()`,无需额外提交(沿用现有提交点)。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifacts_schema.py -v`
Expected: PASS(2 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/data/database.py backend/tests/unit/test_artifacts_schema.py
git commit -m "feat(db): add artifacts table for tracking AI tool outputs"
```

---

## Task 2: 后端 — artifact_repo 数据访问

**Files:**
- Create: `backend/data/artifact_repo.py`
- Test: `backend/tests/unit/test_artifact_repo.py`

**Interfaces:**
- Consumes: `get_database()`(同步)
- Produces(模块级同步函数,风格对齐 `session_repo.py`):
  - `@dataclass Artifact`(字段 id, session_id, tool_call_id, path, name, kind, size, created_at;含 `from_row`、`to_dict`)
  - `record_artifact(session_id, path, name, kind, size, tool_call_id=None) -> str`(返回 artifact id)
  - `list_artifacts(session_id) -> list[Artifact]`(按 created_at 降序)
  - `get_artifact(artifact_id) -> Artifact | None`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_artifact_repo.py
from backend.data import artifact_repo


def test_record_artifact_returns_id():
    aid = artifact_repo.record_artifact(
        session_id="sess_001",
        path="/tmp/test.md",
        name="test.md",
        kind="markdown",
        size=100,
        tool_call_id="call_001",
    )
    assert isinstance(aid, str)
    assert aid.startswith("art_")


def test_list_artifacts_recent_first():
    a1 = artifact_repo.record_artifact("sess_001", "/tmp/a.md", "a.md", "markdown", 10)
    a2 = artifact_repo.record_artifact("sess_001", "/tmp/b.md", "b.md", "markdown", 20)
    items = artifact_repo.list_artifacts("sess_001")
    assert [a.id for a in items] == [a2, a1]


def test_list_artifacts_filters_by_session():
    artifact_repo.record_artifact("sess_001", "/tmp/a.md", "a.md", "markdown", 10)
    artifact_repo.record_artifact("sess_002", "/tmp/b.md", "b.md", "markdown", 20)
    items = artifact_repo.list_artifacts("sess_001")
    assert len(items) == 1
    assert items[0].path == "/tmp/a.md"


def test_get_artifact_found():
    aid = artifact_repo.record_artifact("sess_001", "/tmp/x.md", "x.md", "markdown", 50)
    found = artifact_repo.get_artifact(aid)
    assert found is not None
    assert found.name == "x.md"
    assert found.to_dict()["kind"] == "markdown"


def test_get_artifact_missing_returns_none():
    assert artifact_repo.get_artifact("nonexistent") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_repo.py -v`
Expected: FAIL(module not found)

- [ ] **Step 3: 实现 artifact_repo**

```python
# backend/data/artifact_repo.py
"""
产物仓储层
负责追踪 AI 工具调用生成的文件产物 (artifacts 表 CRUD)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database


@dataclass
class Artifact:
    """产物数据模型"""

    id: str
    session_id: str
    path: str
    name: str
    kind: str
    size: int
    created_at: int
    tool_call_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Artifact":
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            path=row["path"],
            name=row["name"],
            kind=row["kind"],
            size=row["size"] or 0,
            created_at=row["created_at"],
            tool_call_id=row["tool_call_id"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "created_at": self.created_at,
        }


def record_artifact(
    session_id: str,
    path: str,
    name: str,
    kind: str,
    size: int,
    tool_call_id: Optional[str] = None,
) -> str:
    """记录一个新产物,返回 artifact id。"""
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    created_at = int(time.time() * 1000)
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO artifacts
            (id, session_id, tool_call_id, path, name, kind, size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, session_id, tool_call_id, path, name, kind, size, created_at),
    )
    conn.commit()
    return artifact_id


def list_artifacts(session_id: str) -> List[Artifact]:
    """列出指定 session 的所有产物,按 created_at 降序。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    )
    return [Artifact.from_row(row) for row in cursor.fetchall()]


def get_artifact(artifact_id: str) -> Optional[Artifact]:
    """根据 id 查找产物,不存在返回 None。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
    row = cursor.fetchone()
    return Artifact.from_row(row) if row else None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_repo.py -v`
Expected: PASS(5 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/data/artifact_repo.py backend/tests/unit/test_artifact_repo.py
git commit -m "feat(backend): add artifact_repo with record/list/get operations"
```

---

## Task 3: 后端 — artifact 文件读取与 reveal

**Files:**
- Create: `backend/data/artifact_reader.py`
- Test: `backend/tests/unit/test_artifact_reader.py`

**Interfaces:**
- Consumes: `artifact_repo.get_artifact()`
- Produces(同步函数):
  - `read_text(artifact_id, max_bytes=500_000) -> dict`:`{ok, kind, content, truncated}` 或 `{ok: False, error}`
  - `read_image(artifact_id, max_bytes=10_000_000) -> dict`:`{ok, kind, data_url}` 或 `{ok: False, error}`
  - `reveal_in_file_manager(artifact_id) -> dict`:`{ok}` 或 `{ok: False, error}`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_artifact_reader.py
from pathlib import Path
from unittest.mock import patch

from backend.data import artifact_reader, artifact_repo


def test_read_text_markdown(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "doc.md", "markdown", 14)

    result = artifact_reader.read_text(aid)

    assert result["ok"] is True
    assert result["kind"] == "markdown"
    assert result["content"] == "# Hello\n\nWorld"
    assert result["truncated"] is False


def test_read_text_truncates_long_content(tmp_path):
    f = tmp_path / "big.md"
    f.write_text("x" * 600_000, encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "big.md", "markdown", 600_000)

    result = artifact_reader.read_text(aid)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["content"]) <= 500_000


def test_read_text_missing_file(tmp_path):
    aid = artifact_repo.record_artifact("sess_001", str(tmp_path / "gone.md"), "gone.md", "markdown", 0)
    result = artifact_reader.read_text(aid)
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_read_text_missing_artifact():
    result = artifact_reader.read_text("nonexistent")
    assert result["ok"] is False


def test_read_image_returns_data_url(tmp_path):
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    f = tmp_path / "pixel.png"
    f.write_bytes(png_bytes)
    aid = artifact_repo.record_artifact("sess_001", str(f), "pixel.png", "image", len(png_bytes))

    result = artifact_reader.read_image(aid)

    assert result["ok"] is True
    assert result["kind"] == "image"
    assert result["data_url"].startswith("data:image/png;base64,")


def test_reveal_in_file_manager(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("test", encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "doc.md", "markdown", 4)

    with patch("subprocess.run", return_value=None) as mock_run:
        result = artifact_reader.reveal_in_file_manager(aid)

    assert result["ok"] is True
    mock_run.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_reader.py -v`
Expected: FAIL(module not found)

- [ ] **Step 3: 实现 artifact_reader**

```python
# backend/data/artifact_reader.py
"""读取 artifact 文件内容并支持在文件管理器中显示。"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from backend.data import artifact_repo

MAX_TEXT_BYTES = 500_000
MAX_IMAGE_BYTES = 10_000_000

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def read_text(artifact_id: str, max_bytes: int = MAX_TEXT_BYTES) -> dict:
    """读取文本类产物内容,超长截断。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "binary file cannot be previewed"}

    encoded = text.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")

    return {"ok": True, "kind": artifact.kind, "content": text, "truncated": truncated}


def read_image(artifact_id: str, max_bytes: int = MAX_IMAGE_BYTES) -> dict:
    """读取图片类产物,返回 base64 data URL。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    if path.stat().st_size > max_bytes:
        return {"ok": False, "error": "file too large"}

    mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"ok": True, "kind": "image", "data_url": f"data:{mime};base64,{data}"}


def reveal_in_file_manager(artifact_id: str) -> dict:
    """在系统文件管理器中显示文件(macOS/Windows/Linux)。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact.path)
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=True)
        elif sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{path}"], check=True)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_reader.py -v`
Expected: PASS(6 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/data/artifact_reader.py backend/tests/unit/test_artifact_reader.py
git commit -m "feat(backend): add artifact_reader for read/reveal operations"
```

---

## Task 4: 后端 — API 路由

**Files:**
- Create: `backend/api/artifact_routes.py`
- Modify: `backend/main.py`(import + `app.include_router(artifact_router, prefix="/api/v1")`)
- Test: `backend/tests/api/test_artifact_routes.py`

**Interfaces:**
- Consumes: `artifact_repo`, `artifact_reader`
- Produces(router `prefix="/sessions/{session_id}/artifacts"`,注册时加 `/api/v1`):
  - `GET /api/v1/sessions/{session_id}/artifacts` → `{artifacts: [...]}`
  - `GET /api/v1/sessions/{session_id}/artifacts/{artifact_id}/content` → 文本或图片内容
  - `POST /api/v1/sessions/{session_id}/artifacts/{artifact_id}/reveal` → `{ok}`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/api/test_artifact_routes.py
import pytest

from backend.data import artifact_repo


@pytest.mark.asyncio
async def test_list_artifacts_empty(client):
    resp = await client.get("/api/v1/sessions/sess_test/artifacts")
    assert resp.status_code == 200
    assert resp.json() == {"artifacts": []}


@pytest.mark.asyncio
async def test_list_artifacts_returns_recorded(client):
    artifact_repo.record_artifact("sess_test", "/tmp/a.md", "a.md", "markdown", 10)
    resp = await client.get("/api/v1/sessions/sess_test/artifacts")
    assert resp.status_code == 200
    items = resp.json()["artifacts"]
    assert len(items) == 1
    assert items[0]["name"] == "a.md"


@pytest.mark.asyncio
async def test_content_404_for_missing(client):
    resp = await client.get("/api/v1/sessions/sess_test/artifacts/nope/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_content_404_for_wrong_session(client):
    aid = artifact_repo.record_artifact("sess_a", "/tmp/a.md", "a.md", "markdown", 10)
    resp = await client.get(f"/api/v1/sessions/sess_other/artifacts/{aid}/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reveal_404_for_missing(client):
    resp = await client.post("/api/v1/sessions/sess_test/artifacts/nope/reveal")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_artifact_routes.py -v`
Expected: FAIL(404,路由未注册)

- [ ] **Step 3: 实现 artifact_routes**

```python
# backend/api/artifact_routes.py
"""Artifact(产物)相关 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.data import artifact_reader, artifact_repo

router = APIRouter(prefix="/sessions/{session_id}/artifacts", tags=["artifacts"])


@router.get("")
def list_artifacts(session_id: str) -> dict:
    """列出指定 session 的所有产物。"""
    items = artifact_repo.list_artifacts(session_id)
    return {"artifacts": [a.to_dict() for a in items]}


@router.get("/{artifact_id}/content")
def get_artifact_content(session_id: str, artifact_id: str) -> dict:
    """读取产物内容:文本返回 content,图片返回 data_url。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.kind == "image":
        return artifact_reader.read_image(artifact_id)
    return artifact_reader.read_text(artifact_id)


@router.post("/{artifact_id}/reveal")
def reveal_artifact(session_id: str, artifact_id: str) -> dict:
    """在系统文件管理器中显示产物。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return artifact_reader.reveal_in_file_manager(artifact_id)
```

- [ ] **Step 4: 在 main.py 注册路由**

读取 `backend/main.py`,在其他 `from backend.api.X_routes import router as X_router` 附近添加 import:
```python
from backend.api.artifact_routes import router as artifact_router
```
在其他 `app.include_router(..., prefix="/api/v1")` 附近添加:
```python
app.include_router(artifact_router, prefix="/api/v1")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_artifact_routes.py -v`
Expected: PASS(5 tests)

- [ ] **Step 6: 提交**

```bash
git add backend/api/artifact_routes.py backend/main.py backend/tests/api/test_artifact_routes.py
git commit -m "feat(api): add artifact routes (list/content/reveal)"
```

---

## Task 5: 后端 — 在 WriteFileTool 拦截写操作记录产物

**Files:**
- Modify: `backend/tools/file_tool.py`(`WriteFileTool.execute()` 成功写入后记录产物)
- Test: `backend/tests/unit/test_artifact_interception.py`

**Interfaces:**
- Consumes: `artifact_repo.record_artifact()`, `current_tool_context()`(`backend/tools/context.py`,返回含 `session_id` 的 `ToolExecutionContext` 或 `None`)
- Produces: 模块级辅助 `detect_artifact_kind(path) -> str`;`WriteFileTool.execute()` 写入成功后(返回 `ToolResult(success=True)` 前)尝试记录产物,失败静默(不阻断写入)

**关键事实(已核实):**
- `WriteFileTool.execute(self, path, content, append=False, **kwargs)` 位于 `backend/tools/file_tool.py`,写入成功后构造 `result = {"path": str(file_path.resolve()), "bytes_written": content_bytes, "mode": mode}` 并 `return ToolResult(success=True, content=result)`。
- session_id 通过 `from backend.tools.context import current_tool_context` 获取:`ctx = current_tool_context()`,若 `ctx is not None` 则 `ctx.session_id`。上下文中**没有** tool_call_id,传 `None`。
- 拦截必须 try/except 包裹,记录失败绝不影响写入结果。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_artifact_interception.py
from backend.tools import file_tool
from backend.tools.context import ToolExecutionContext, set_tool_context, reset_tool_context
from backend.data import artifact_repo


def test_detect_artifact_kind():
    assert file_tool.detect_artifact_kind("a.md") == "markdown"
    assert file_tool.detect_artifact_kind("a.py") == "code"
    assert file_tool.detect_artifact_kind("a.png") == "image"
    assert file_tool.detect_artifact_kind("a.csv") == "csv"
    assert file_tool.detect_artifact_kind("a.json") == "code"
    assert file_tool.detect_artifact_kind("a.unknown") == "text"


def test_write_file_records_artifact(tmp_path):
    from backend.tools.file_tool import WriteFileTool

    target = tmp_path / "out.md"
    tool = WriteFileTool()  # 无 policy => 跳过 workspace 边界检查

    ctx = ToolExecutionContext(
        session_id="sess_intercept",
        stream_id="stream_1",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        result = tool.execute(path=str(target), content="# Hi")
    finally:
        reset_tool_context(token)

    assert result.success is True
    artifacts = artifact_repo.list_artifacts("sess_intercept")
    assert len(artifacts) == 1
    assert artifacts[0].name == "out.md"
    assert artifacts[0].kind == "markdown"


def test_write_file_without_context_does_not_record(tmp_path):
    from backend.tools.file_tool import WriteFileTool

    target = tmp_path / "no_ctx.md"
    tool = WriteFileTool()
    result = tool.execute(path=str(target), content="x")

    assert result.success is True
    # 无上下文时不记录(任何 session 都没有该产物)
    assert artifact_repo.list_artifacts("sess_none") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_interception.py -v`
Expected: FAIL(`detect_artifact_kind` 不存在)

- [ ] **Step 3: 在 file_tool.py 添加辅助函数与拦截**

在 `backend/tools/file_tool.py` 顶部 import 区添加:
```python
from backend.data import artifact_repo
from backend.tools.context import current_tool_context
```

在模块级(如 `_contains_binary_marker` 附近)添加:
```python
def detect_artifact_kind(path: str) -> str:
    """根据文件扩展名检测产物类型。"""
    ext = Path(path).suffix.lower()
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".css", ".html", ".sh"):
        return "code"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
        return "image"
    if ext in (".csv", ".tsv"):
        return "csv"
    return "text"


def _record_artifact_safely(resolved_path: str, size: int) -> None:
    """写入成功后记录产物;任何失败都静默,不影响写入结果。"""
    try:
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return
        p = Path(resolved_path)
        artifact_repo.record_artifact(
            session_id=ctx.session_id,
            path=str(p),
            name=p.name,
            kind=detect_artifact_kind(resolved_path),
            size=size,
        )
    except Exception:  # noqa: BLE001 — 记录产物失败绝不阻断写入
        logger.debug("write_file: 记录产物失败", exc_info=True)
```

在 `WriteFileTool.execute()` 中,构造 `result` 字典之后、`return ToolResult(success=True, content=result)` 之前,插入:
```python
            # 记录产物(供 Chat 右侧 Artifacts 面板展示)
            _record_artifact_safely(result["path"], content_bytes)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_interception.py -v`
Expected: PASS(3 tests)

- [ ] **Step 5: 运行 file_tool 相关回归测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -k "file_tool or write_file or file" -v 2>&1 | tail -25`
Expected: 无回归失败

- [ ] **Step 6: 提交**

```bash
git add backend/tools/file_tool.py backend/tests/unit/test_artifact_interception.py
git commit -m "feat(tools): record artifacts when write_file succeeds"
```

---

## Task 6: 前端 — artifact API 客户端

**Files:**
- Create: `src/features/artifacts/artifactApi.ts`
- Test: `src/features/artifacts/__tests__/artifactApi.test.ts`

**Interfaces:**
- Consumes: `fetch`
- Produces:
  - `interface Artifact { id; session_id; tool_call_id: string | null; path; name; kind; size; created_at }`
  - `interface ArtifactContent { ok; error?; kind?; content?; data_url?; truncated? }`
  - `listArtifacts(sessionId): Promise<Artifact[]>`
  - `readArtifactContent(sessionId, artifactId): Promise<ArtifactContent>`
  - `revealArtifact(sessionId, artifactId): Promise<{ok; error?}>`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/artifactApi.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { listArtifacts, readArtifactContent, revealArtifact } from '../artifactApi';

describe('artifactApi', () => {
  beforeEach(() => vi.resetAllMocks());

  it('listArtifacts returns artifacts array', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ artifacts: [{ id: 'a1', name: 'test.md', kind: 'markdown' }] }),
    });
    const result = await listArtifacts('sess_001');
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/sessions/sess_001/artifacts');
  });

  it('listArtifacts returns [] when artifacts missing', async () => {
    global.fetch = vi.fn().mockResolvedValue({ json: async () => ({}) });
    expect(await listArtifacts('s')).toEqual([]);
  });

  it('readArtifactContent fetches content endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true, kind: 'markdown', content: '# Hi', truncated: false }),
    });
    const result = await readArtifactContent('sess_001', 'a1');
    expect(result.content).toBe('# Hi');
    expect(global.fetch).toHaveBeenCalledWith('/api/v1/sessions/sess_001/artifacts/a1/content');
  });

  it('revealArtifact posts to reveal endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({ json: async () => ({ ok: true }) });
    const result = await revealArtifact('sess_001', 'a1');
    expect(result.ok).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts/a1/reveal',
      expect.objectContaining({ method: 'POST' })
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/artifactApi.test.ts`
Expected: FAIL(module not found)

- [ ] **Step 3: 实现 artifactApi**

```typescript
// src/features/artifacts/artifactApi.ts

export type ArtifactKind = 'markdown' | 'code' | 'image' | 'csv' | 'json' | 'text';

export interface Artifact {
  id: string;
  session_id: string;
  tool_call_id: string | null;
  path: string;
  name: string;
  kind: ArtifactKind;
  size: number;
  created_at: number;
}

export interface ArtifactContent {
  ok: boolean;
  error?: string;
  kind?: string;
  content?: string;
  data_url?: string;
  truncated?: boolean;
}

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts`);
  const data = await res.json();
  return data.artifacts ?? [];
}

export async function readArtifactContent(
  sessionId: string,
  artifactId: string
): Promise<ArtifactContent> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts/${artifactId}/content`);
  return res.json();
}

export async function revealArtifact(
  sessionId: string,
  artifactId: string
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts/${artifactId}/reveal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  return res.json();
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/artifactApi.test.ts`
Expected: PASS(4 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/artifactApi.ts src/features/artifacts/__tests__/artifactApi.test.ts
git commit -m "feat(frontend): add artifactApi client functions"
```

---

## Task 7: 前端 — useArtifacts hook

**Files:**
- Create: `src/features/artifacts/useArtifacts.ts`
- Test: `src/features/artifacts/__tests__/useArtifacts.test.ts`

**Interfaces:**
- Consumes: `listArtifacts`
- Produces: `useArtifacts(sessionId: string | null) => { artifacts: Artifact[]; loading: boolean; refresh: () => void }`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/useArtifacts.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({ listArtifacts: vi.fn() }));

import { useArtifacts } from '../useArtifacts';
import { listArtifacts } from '../artifactApi';

const mkArt = (id: string) => ({
  id, session_id: 's', tool_call_id: null, path: `/${id}.md`, name: `${id}.md`,
  kind: 'markdown' as const, size: 1, created_at: 1,
});

describe('useArtifacts', () => {
  beforeEach(() => vi.mocked(listArtifacts).mockReset());

  it('loads artifacts on mount', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([mkArt('a1')]);
    const { result } = renderHook(() => useArtifacts('sess_001'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.artifacts).toHaveLength(1);
  });

  it('does not load when sessionId is null', () => {
    const { result } = renderHook(() => useArtifacts(null));
    expect(result.current.artifacts).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(listArtifacts).not.toHaveBeenCalled();
  });

  it('refresh refetches', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([mkArt('a1')]);
    const { result } = renderHook(() => useArtifacts('sess_001'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(listArtifacts).toHaveBeenCalledTimes(1);
    result.current.refresh();
    await waitFor(() => expect(listArtifacts).toHaveBeenCalledTimes(2));
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/useArtifacts.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现 useArtifacts**

```typescript
// src/features/artifacts/useArtifacts.ts
import { useState, useEffect, useCallback } from 'react';
import { listArtifacts, type Artifact } from './artifactApi';

export function useArtifacts(sessionId: string | null) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      setArtifacts(await listArtifacts(sessionId));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { artifacts, loading, refresh };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/useArtifacts.test.ts`
Expected: PASS(3 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/useArtifacts.ts src/features/artifacts/__tests__/useArtifacts.test.ts
git commit -m "feat(frontend): add useArtifacts hook"
```

---

## Task 8: 前端 — useArtifactContent hook

**Files:**
- Create: `src/features/artifacts/useArtifactContent.ts`
- Test: `src/features/artifacts/__tests__/useArtifactContent.test.ts`

**Interfaces:**
- Consumes: `readArtifactContent`
- Produces: `useArtifactContent(sessionId: string, artifactId: string | null) => { content: ArtifactContent | null; loading: boolean }`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/useArtifactContent.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({ readArtifactContent: vi.fn() }));

import { useArtifactContent } from '../useArtifactContent';
import { readArtifactContent } from '../artifactApi';

describe('useArtifactContent', () => {
  beforeEach(() => vi.mocked(readArtifactContent).mockReset());

  it('loads content when artifactId set', async () => {
    vi.mocked(readArtifactContent).mockResolvedValue({
      ok: true, kind: 'markdown', content: '# Hello', truncated: false,
    });
    const { result } = renderHook(() => useArtifactContent('sess_001', 'a1'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.content?.content).toBe('# Hello');
  });

  it('clears content when artifactId null', () => {
    const { result } = renderHook(() => useArtifactContent('sess_001', null));
    expect(result.current.content).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(readArtifactContent).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/useArtifactContent.test.ts`
Expected: FAIL

- [ ] **Step 3: 实现 useArtifactContent**

```typescript
// src/features/artifacts/useArtifactContent.ts
import { useState, useEffect } from 'react';
import { readArtifactContent, type ArtifactContent } from './artifactApi';

export function useArtifactContent(sessionId: string, artifactId: string | null) {
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!artifactId) {
      setContent(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    readArtifactContent(sessionId, artifactId)
      .then((c) => { if (!cancelled) setContent(c); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId, artifactId]);

  return { content, loading };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/useArtifactContent.test.ts`
Expected: PASS(2 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/useArtifactContent.ts src/features/artifacts/__tests__/useArtifactContent.test.ts
git commit -m "feat(frontend): add useArtifactContent hook"
```

---

## Task 9: 前端 — ProgressSection 组件

**Files:**
- Create: `src/widgets/chat/progress/ProgressSection.tsx`
- Test: `src/widgets/chat/__tests__/ProgressSection.test.tsx`

**Interfaces:**
- Props:
  ```typescript
  interface ProgressSectionProps {
    iteration: number;
    streamingState: string | null;
    toolCalls: ToolCall[];   // 来自 shared/lib/store,字段 { id?; name; args; result? }
    isLoading: boolean;
  }
  ```
- **注意**:`ToolCall` 无 `status` 字段;此处 toolCalls 代表当前流式中观察到的工具调用,统一视为"进行中"。

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ProgressSection.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection', () => {
  it('shows iteration when > 0', () => {
    render(<ProgressSection iteration={3} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/第 3 轮/)).toBeInTheDocument();
  });

  it('hides iteration when 0', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.queryByText(/第 \d+ 轮/)).not.toBeInTheDocument();
  });

  it('shows thinking label while loading', () => {
    render(<ProgressSection iteration={0} streamingState="thinking" toolCalls={[]} isLoading />);
    expect(screen.getByText(/思考中/)).toBeInTheDocument();
  });

  it('shows idle state when not loading', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.getByText(/等待输入/)).toBeInTheDocument();
  });

  it('renders tool call names', () => {
    const toolCalls = [
      { id: 'tc1', name: 'write_file', args: {} },
      { id: 'tc2', name: 'search', args: {} },
    ];
    render(<ProgressSection iteration={1} streamingState="tool_call" toolCalls={toolCalls} isLoading />);
    expect(screen.getByText('write_file')).toBeInTheDocument();
    expect(screen.getByText('search')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 ProgressSection**

```tsx
// src/widgets/chat/progress/ProgressSection.tsx
import type { ToolCall } from '../../../shared/lib/store';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
}

const STATE_LABELS: Record<string, string> = {
  thinking: '思考中',
  tool_call: '调用工具',
  generating: '生成回复',
  idle: '空闲',
};

export function ProgressSection({
  iteration,
  streamingState,
  toolCalls,
  isLoading,
}: ProgressSectionProps) {
  const stateLabel = streamingState ? STATE_LABELS[streamingState] ?? streamingState : null;

  return (
    <div className="p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2">
        {isLoading && stateLabel && <span className="text-primary font-medium">{stateLabel}</span>}
        {iteration > 0 && <span className="text-text-secondary">第 {iteration} 轮</span>}
        {!isLoading && !stateLabel && <span className="text-muted">等待输入...</span>}
      </div>

      {toolCalls.length > 0 && (
        <div className="space-y-1">
          {toolCalls.map((tc, i) => (
            <div
              key={tc.id ?? `${tc.name}-${i}`}
              className="flex items-center gap-2 px-2 py-1 rounded text-xs bg-bg-hover"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="text-text-secondary">{tc.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ProgressSection.test.tsx`
Expected: PASS(5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/progress/ProgressSection.tsx src/widgets/chat/__tests__/ProgressSection.test.tsx
git commit -m "feat(frontend): add ProgressSection component"
```

---

## Task 10: 前端 — ArtifactRow 组件

**Files:**
- Create: `src/widgets/chat/artifacts/ArtifactRow.tsx`
- Test: `src/widgets/chat/__tests__/ArtifactRow.test.tsx`

**Interfaces:**
- Props: `{ artifact: Artifact; onSelect: (a: Artifact) => void }`

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactRow.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtifactRow } from '../artifacts/ArtifactRow';
import type { Artifact } from '../../../features/artifacts/artifactApi';

const sample: Artifact = {
  id: 'a1', session_id: 'sess_001', tool_call_id: null, path: '/tmp/test.md',
  name: 'test.md', kind: 'markdown', size: 1024, created_at: 1722500000000,
};

describe('ArtifactRow', () => {
  it('renders filename and formatted size', () => {
    render(<ArtifactRow artifact={sample} onSelect={() => {}} />);
    expect(screen.getByText('test.md')).toBeInTheDocument();
    expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<ArtifactRow artifact={sample} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith(sample);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactRow.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 ArtifactRow**

```tsx
// src/widgets/chat/artifacts/ArtifactRow.tsx
import { FileText, FileCode, FileImage, FileSpreadsheet, File } from 'lucide-react';
import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';

interface ArtifactRowProps {
  artifact: Artifact;
  onSelect: (artifact: Artifact) => void;
}

const KIND_ICONS: Record<ArtifactKind, typeof File> = {
  markdown: FileText,
  code: FileCode,
  image: FileImage,
  csv: FileSpreadsheet,
  json: FileCode,
  text: File,
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function ArtifactRow({ artifact, onSelect }: ArtifactRowProps) {
  const Icon = KIND_ICONS[artifact.kind] ?? File;
  return (
    <button
      className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-hover rounded text-left transition-colors"
      onClick={() => onSelect(artifact)}
    >
      <Icon className="w-4 h-4 text-text-secondary shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-text truncate">{artifact.name}</div>
        <div className="text-xs text-muted">{formatSize(artifact.size)}</div>
      </div>
    </button>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactRow.test.tsx`
Expected: PASS(2 tests)

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactRow.tsx src/widgets/chat/__tests__/ArtifactRow.test.tsx
git commit -m "feat(frontend): add ArtifactRow component"
```

---

## Task 11: 前端 — ArtifactsSection 组件

**Files:**
- Create: `src/widgets/chat/artifacts/ArtifactsSection.tsx`
- Test: `src/widgets/chat/__tests__/ArtifactsSection.test.tsx`

**Interfaces:**
- Props:
  ```typescript
  interface ArtifactsSectionProps {
    artifacts: Artifact[];
    loading: boolean;
    sessionId: string | null;
    onRefresh: () => void;
    onSelect: (a: Artifact) => void;
    onReveal: (a: Artifact) => void;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactsSection.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtifactsSection } from '../artifacts/ArtifactsSection';
import type { Artifact } from '../../../features/artifacts/artifactApi';

const arts: Artifact[] = [
  { id: 'a1', session_id: 's', tool_call_id: null, path: '/a.md', name: 'a.md', kind: 'markdown', size: 100, created_at: 1 },
  { id: 'a2', session_id: 's', tool_call_id: null, path: '/b.py', name: 'b.py', kind: 'code', size: 200, created_at: 2 },
];
const base = { loading: false, sessionId: 'sess_001', onRefresh: () => {}, onSelect: () => {}, onReveal: () => {} };

describe('ArtifactsSection', () => {
  it('shows empty state', () => {
    render(<ArtifactsSection artifacts={[]} {...base} />);
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  it('renders artifact list', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.getByText('b.py')).toBeInTheDocument();
  });

  it('calls onRefresh', () => {
    const onRefresh = vi.fn();
    render(<ArtifactsSection artifacts={[]} {...base} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole('button', { name: /刷新/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('asks to select session when sessionId null', () => {
    render(<ArtifactsSection artifacts={[]} {...base} sessionId={null} />);
    expect(screen.getByText(/请先选择会话/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactsSection.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 ArtifactsSection**

```tsx
// src/widgets/chat/artifacts/ArtifactsSection.tsx
import { RefreshCw, FolderOpen } from 'lucide-react';
import type { Artifact } from '../../../features/artifacts/artifactApi';
import { ArtifactRow } from './ArtifactRow';

interface ArtifactsSectionProps {
  artifacts: Artifact[];
  loading: boolean;
  sessionId: string | null;
  onRefresh: () => void;
  onSelect: (artifact: Artifact) => void;
  onReveal: (artifact: Artifact) => void;
}

export function ArtifactsSection({
  artifacts, loading, sessionId, onRefresh, onSelect, onReveal,
}: ArtifactsSectionProps) {
  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-end gap-1 px-2 py-1 border-b border-border">
        {artifacts.length > 0 && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
            title="在文件管理器中显示"
            onClick={() => onReveal(artifacts[0])}
          >
            <FolderOpen className="w-4 h-4" />
          </button>
        )}
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
          title="刷新"
          aria-label="刷新"
          onClick={onRefresh}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {artifacts.length === 0 ? (
          <div className="p-3 text-sm text-muted">暂无产物</div>
        ) : (
          <div className="divide-y divide-border">
            {artifacts.map((a) => (
              <ArtifactRow key={a.id} artifact={a} onSelect={onSelect} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactsSection.test.tsx`
Expected: PASS(4 tests)

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactsSection.tsx src/widgets/chat/__tests__/ArtifactsSection.test.tsx
git commit -m "feat(frontend): add ArtifactsSection component"
```

---

## Task 12: 前端 — ArtifactViewer 组件

**Files:**
- Create: `src/widgets/chat/artifacts/ArtifactViewer.tsx`
- Test: `src/widgets/chat/__tests__/ArtifactViewer.test.tsx`

**Interfaces:**
- Props: `{ artifact: Artifact; sessionId: string; onBack: () => void }`
- Consumes: `useArtifactContent`, `revealArtifact`

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactViewer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifactContent', () => ({ useArtifactContent: vi.fn() }));
vi.mock('../../../features/artifacts/artifactApi', () => ({ revealArtifact: vi.fn() }));

import { ArtifactViewer } from '../artifacts/ArtifactViewer';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import type { Artifact } from '../../../features/artifacts/artifactApi';

const sample: Artifact = {
  id: 'a1', session_id: 'sess_001', tool_call_id: null, path: '/tmp/test.md',
  name: 'test.md', kind: 'markdown', size: 1024, created_at: 1,
};

describe('ArtifactViewer', () => {
  it('renders breadcrumb', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Hello' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/产物/)).toBeInTheDocument();
    expect(screen.getByText('test.md')).toBeInTheDocument();
  });

  it('calls onBack', () => {
    vi.mocked(useArtifactContent).mockReturnValue({ content: null, loading: false });
    const onBack = vi.fn();
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: /返回/ }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders markdown content', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Title' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/Title/)).toBeInTheDocument();
  });

  it('renders image', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'image', data_url: 'data:image/png;base64,xxx' }, loading: false,
    });
    render(<ArtifactViewer artifact={{ ...sample, kind: 'image' }} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,xxx');
  });

  it('shows error state', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: false, error: 'File not found' }, loading: false,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/File not found/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactViewer.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 ArtifactViewer**

```tsx
// src/widgets/chat/artifacts/ArtifactViewer.tsx
import { ArrowLeft, Copy, FolderOpen } from 'lucide-react';
import type { Artifact } from '../../../features/artifacts/artifactApi';
import { revealArtifact } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';

interface ArtifactViewerProps {
  artifact: Artifact;
  sessionId: string;
  onBack: () => void;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c !== ''));
}

function CsvPreview({ text }: { text: string }) {
  const rows = parseCsv(text);
  if (rows.length === 0) return <div className="text-sm text-muted">空文件</div>;
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>{head.map((c, i) => <th key={i} className="border px-2 py-1 bg-bg-hover">{c}</th>)}</tr>
        </thead>
        <tbody>
          {body.slice(0, 500).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} className="border px-2 py-1">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {body.length > 500 && <div className="text-xs text-muted mt-2">仅显示前 500 行</div>}
    </div>
  );
}

export function ArtifactViewer({ artifact, sessionId, onBack }: ArtifactViewerProps) {
  const { content, loading } = useArtifactContent(sessionId, artifact.id);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button className="p-1.5 rounded hover:bg-bg-hover" onClick={onBack} aria-label="返回">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 text-sm">
          <span className="text-muted">产物</span>
          <span className="mx-1 text-muted">/</span>
          <span className="text-text">{artifact.name}</span>
        </div>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="复制路径"
          onClick={() => navigator.clipboard?.writeText(artifact.path)}
        >
          <Copy className="w-4 h-4" />
        </button>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          title="在文件管理器中显示"
          onClick={() => revealArtifact(sessionId, artifact.id)}
        >
          <FolderOpen className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-3">
        {loading ? (
          <div className="text-sm text-muted">加载中...</div>
        ) : !content || !content.ok ? (
          <div className="text-sm text-error">{content?.error ?? '加载失败'}</div>
        ) : content.kind === 'image' ? (
          <img src={content.data_url} alt={artifact.name} className="max-w-full" />
        ) : content.kind === 'code' || content.kind === 'json' ? (
          <pre className="whitespace-pre-wrap text-xs font-mono bg-bg-hover p-2 rounded">{content.content}</pre>
        ) : content.kind === 'csv' ? (
          <CsvPreview text={content.content ?? ''} />
        ) : (
          <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactViewer.test.tsx`
Expected: PASS(5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactViewer.tsx src/widgets/chat/__tests__/ArtifactViewer.test.tsx
git commit -m "feat(frontend): add ArtifactViewer with multi-format preview"
```

---

## Task 13: 前端 — RightPanel + RightPanelToggle 容器

**Files:**
- Create: `src/widgets/chat/RightPanel.tsx`
- Create: `src/widgets/chat/RightPanelToggle.tsx`
- Test: `src/widgets/chat/__tests__/RightPanel.test.tsx`

**Interfaces:**
- RightPanel Props:
  ```typescript
  interface RightPanelProps {
    open: boolean;
    onToggle: () => void;
    iteration: number;
    streamingState: string | null;
    toolCalls: ToolCall[];
    isLoading: boolean;
    sessionId: string | null;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/RightPanel.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../features/artifacts/useArtifacts', () => ({
  useArtifacts: vi.fn(() => ({ artifacts: [], loading: false, refresh: vi.fn() })),
}));

import { RightPanel } from '../RightPanel';

const props = {
  open: true, onToggle: vi.fn(), iteration: 0, streamingState: null,
  toolCalls: [], isLoading: false, sessionId: 'sess_001',
};

describe('RightPanel', () => {
  it('renders both tabs', () => {
    render(<RightPanel {...props} />);
    expect(screen.getByText('Progress')).toBeInTheDocument();
    expect(screen.getByText('Artifacts')).toBeInTheDocument();
  });

  it('switches to Artifacts tab', () => {
    render(<RightPanel {...props} />);
    fireEvent.click(screen.getByText('Artifacts'));
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 RightPanelToggle**

```tsx
// src/widgets/chat/RightPanelToggle.tsx
import { PanelRight } from 'lucide-react';

interface RightPanelToggleProps {
  open: boolean;
  onClick: () => void;
}

export function RightPanelToggle({ open, onClick }: RightPanelToggleProps) {
  return (
    <button
      className={
        'p-1.5 rounded hover:bg-bg-hover text-text-secondary transition-colors ' +
        (open ? 'bg-bg-hover' : '')
      }
      onClick={onClick}
      title={open ? '关闭右侧面板' : '打开右侧面板'}
      aria-label="切换右侧面板"
    >
      <PanelRight className="w-4 h-4" />
    </button>
  );
}
```

- [ ] **Step 4: 实现 RightPanel**

```tsx
// src/widgets/chat/RightPanel.tsx
import { useState } from 'react';
import type { ToolCall } from '../../shared/lib/store';
import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { ProgressSection } from './progress/ProgressSection';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ArtifactViewer } from './artifacts/ArtifactViewer';

interface RightPanelProps {
  open: boolean;
  onToggle: () => void;
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  sessionId: string | null;
}

type Tab = 'progress' | 'artifacts';

export function RightPanel({
  open, iteration, streamingState, toolCalls, isLoading, sessionId,
}: RightPanelProps) {
  const [tab, setTab] = useState<Tab>('progress');
  const [selected, setSelected] = useState<Artifact | null>(null);
  const { artifacts, loading, refresh } = useArtifacts(sessionId);

  return (
    <aside
      className={
        'fixed top-12 right-0 h-[calc(100vh-3rem)] w-80 bg-surface border-l border-border ' +
        'transform transition-transform duration-200 ease-in-out z-30 ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
    >
      {!selected && (
        <div className="flex border-b border-border">
          {(['progress', 'artifacts'] as Tab[]).map((t) => (
            <button
              key={t}
              className={
                'flex-1 py-2 text-sm font-medium transition-colors ' +
                (tab === t
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text')
              }
              onClick={() => setTab(t)}
            >
              {t === 'progress' ? 'Progress' : 'Artifacts'}
            </button>
          ))}
        </div>
      )}

      <div className="h-[calc(100%-2.5rem)]">
        {selected && sessionId ? (
          <ArtifactViewer artifact={selected} sessionId={sessionId} onBack={() => setSelected(null)} />
        ) : tab === 'progress' ? (
          <ProgressSection
            iteration={iteration}
            streamingState={streamingState}
            toolCalls={toolCalls}
            isLoading={isLoading}
          />
        ) : (
          <ArtifactsSection
            artifacts={artifacts}
            loading={loading}
            sessionId={sessionId}
            onRefresh={refresh}
            onSelect={setSelected}
            onReveal={(a) => sessionId && revealArtifact(sessionId, a.id)}
          />
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/RightPanel.test.tsx`
Expected: PASS(2 tests)

- [ ] **Step 6: 提交**

```bash
git add src/widgets/chat/RightPanel.tsx src/widgets/chat/RightPanelToggle.tsx src/widgets/chat/__tests__/RightPanel.test.tsx
git commit -m "feat(frontend): add RightPanel drawer container with tab switching"
```

---

## Task 14: 前端 — 确认 useChat 暴露 streamingToolCalls

**Files:**
- Modify(如需): `src/features/send-message/useChat.ts`

**Interfaces:**
- 确认 `useChat()` 返回值包含 `streamingToolCalls: ToolCall[]`(状态已存在于该 hook;仅需确保在 return 对象中导出)

- [ ] **Step 1: 检查现状**

Run: `grep -n "streamingToolCalls" src/features/send-message/useChat.ts`

确认 return 对象中是否已包含 `streamingToolCalls`。若已包含,本任务无需改动(在 report 中说明并跳过后续步骤)。

- [ ] **Step 2: 如未导出,在 return 中添加**

在 `useChat()` 的 return 对象中加入 `streamingToolCalls`。

- [ ] **Step 3: 运行 useChat 相关测试**

Run: `cd /home/fz/project/sage && npx vitest run src/features/send-message/`
Expected: 现有测试全部通过

- [ ] **Step 4: 提交(如有改动)**

```bash
git add src/features/send-message/useChat.ts
git commit -m "feat(frontend): expose streamingToolCalls from useChat hook"
```

---

## Task 15: 前端 — 集成 RightPanel 到 Chat.tsx

**Files:**
- Modify: `src/pages/Chat.tsx`

**Interfaces:**
- Consumes: `RightPanel`, `RightPanelToggle`, `useChat().streamingToolCalls`

- [ ] **Step 1: 添加 import 与状态**

在 `src/pages/Chat.tsx` 顶部 import 区添加:
```typescript
import { RightPanel } from '../widgets/chat/RightPanel';
import { RightPanelToggle } from '../widgets/chat/RightPanelToggle';
```
(`useState` 已在文件中导入,确认即可。)

在 `Chat` 组件内添加:
```typescript
const [rightPanelOpen, setRightPanelOpen] = useState(false);
```

- [ ] **Step 2: 从 useChat 解构 streamingToolCalls**

在现有 `useChat()` 解构中追加 `streamingToolCalls`(与 `iteration`、`streamingState` 同处)。

- [ ] **Step 3: 在头部工具栏加入切换按钮**

将页面头部 `<div className="h-12 flex items-center justify-between px-5 ...">` 内的右侧按钮区(`<div className="flex items-center gap-2">`)中,在"+ 新对话"按钮旁加入:
```tsx
<RightPanelToggle
  open={rightPanelOpen}
  onClick={() => setRightPanelOpen((v) => !v)}
/>
```

- [ ] **Step 4: 在组件末尾渲染 RightPanel**

在最外层 `<div className="flex-1 flex flex-col min-h-0">` 内、`<ChatInput ... />` 之后添加:
```tsx
<RightPanel
  open={rightPanelOpen}
  onToggle={() => setRightPanelOpen((v) => !v)}
  iteration={iteration}
  streamingState={streamingState}
  toolCalls={streamingToolCalls}
  isLoading={isLoading}
  sessionId={currentSessionId}
/>
```

- [ ] **Step 5: 运行全量前端测试**

Run: `cd /home/fz/project/sage && npx vitest run`
Expected: 全部通过

- [ ] **Step 6: 运行 typecheck**

Run: `cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | tail -20`
Expected: 无 error

- [ ] **Step 7: 提交**

```bash
git add src/pages/Chat.tsx
git commit -m "feat(frontend): integrate RightPanel into Chat page"
```

---

## Task 16: 全量测试与文档归档

**Files:**
- Create: `docs/technical/31-artifacts-panel.md`
- Modify: `docs/technical/README.md`(章节目录)

- [ ] **Step 1: 全量后端测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q 2>&1 | tail -20`
Expected: 全部通过

- [ ] **Step 2: 全量前端测试 + typecheck**

Run: `cd /home/fz/project/sage && npx vitest run 2>&1 | tail -20 && npx tsc --noEmit 2>&1 | tail -10`
Expected: 全部通过,无 type error

- [ ] **Step 3: 创建技术文档**

写入 `docs/technical/31-artifacts-panel.md`,内容涵盖:概述、架构图(WriteFileTool → artifact_repo → artifacts 表 → API → RightPanel)、后端模块(表/repo/reader/routes + 3 个 API 路径)、前端模块(hooks + 组件)、限制(文本 500KB/图片 10MB,kind 范围)、后续迭代(PDF/Excel 预览、跳转消息、搜索过滤)。遵循 `docs/technical/` 既有章节风格。

- [ ] **Step 4: 更新技术手册 README 章节目录**

读取 `docs/technical/README.md`,在章节目录表格追加一行:
```
| 31 | [Artifacts Panel](31-artifacts-panel.md) | Chat 右侧 Progress + Artifacts 抽屉面板 |
```
(编号与既有最大编号衔接,如有冲突按实际调整。)

- [ ] **Step 5: 提交**

```bash
git add docs/technical/31-artifacts-panel.md docs/technical/README.md
git commit -m "docs: add artifacts panel technical documentation"
```

- [ ] **Step 6: 删除本计划文件(归档)**

```bash
git rm docs/superpowers/plans/2026-08-01-artifacts-panel.md
git commit -m "chore: remove completed artifacts panel implementation plan"
```
