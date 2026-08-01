# Artifacts Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Sage Chat 页面添加右侧抽屉面板(Progress + Artifacts),让用户能查看 AI 工具调用进度和生成的文件产物。

**Architecture:** 全栈追踪方案。后端在工具执行层拦截写操作,记录产物到 `artifacts` 表;暴露 3 个 REST API(list/read/reveal)。前端在 Chat 页面右侧加抽屉式 RightPanel,内含 Progress 面板(实时显示流式状态)和 Artifacts 面板(文件列表 + 多格式预览)。

**Tech Stack:**
- 后端: Python 3.11, FastAPI, SQLite (aiosqlite)
- 前端: React 18, TypeScript, Vitest
- 测试: pytest (后端), vitest + Playwright (前端)

## Global Constraints

- 后端依赖必须在 `sage-backend` conda 环境(`/home/fz/anaconda3/envs/sage-backend/bin/python`)中运行
- 前端测试覆盖率 ≥80%
- 所有 commit 遵循 conventional commits 格式
- 代码风格遵循项目现有 `.claude/rules/common/coding-style.md` 规则
- 数据库迁移使用项目现有的 schema migration 模式
- API 路径使用 `/api/v1/` 前缀(项目既有约定)
- 文件大小限制:文本 500KB,二进制 10MB

---

## Task 1: 数据库迁移 - 添加 artifacts 表

**Files:**
- Create: `backend/data/migrations/006_add_artifacts_table.py`
- Modify: `backend/data/database.py:__init__` (注册新迁移)

**Interfaces:**
- Produces: `artifacts` 表,字段 `(id TEXT PK, session_id TEXT, tool_call_id TEXT, path TEXT, name TEXT, kind TEXT, size INTEGER, created_at INTEGER)`

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_artifacts_migration.py
import pytest
from backend.data.database import get_database

@pytest.mark.asyncio
async def test_artifacts_table_exists():
    db = await get_database()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "artifacts"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifacts_migration.py -v`
Expected: FAIL (table doesn't exist)

- [ ] **Step 3: 实现迁移文件**

```python
# backend/data/migrations/006_add_artifacts_table.py
"""添加 artifacts 表用于追踪 AI 工具调用生成的文件。"""

from __future__ import annotations
import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_call_id TEXT,
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id, created_at DESC)"
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    await db.execute("DROP INDEX IF EXISTS idx_artifacts_session")
    await db.execute("DROP TABLE IF EXISTS artifacts")
    await db.commit()
```

- [ ] **Step 4: 在 database.py 注册迁移**

读取 `backend/data/database.py` 中的迁移列表(类似 `migrations = [...]`),添加 `import backend.data.migrations.006_add_artifacts_table as m006` 并在列表中追加 `m006`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifacts_migration.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/data/migrations/006_add_artifacts_table.py backend/data/database.py tests/data/test_artifacts_migration.py
git commit -m "feat(db): add artifacts table for tracking AI tool outputs"
```

---

## Task 2: 后端 - artifact_store 基础操作

**Files:**
- Create: `backend/data/artifact_store.py`
- Test: `tests/data/test_artifact_store.py`

**Interfaces:**
- Consumes: `get_database()` from `backend.data.database`
- Produces:
  - `record(session_id, tool_call_id, path, name, kind, size) -> str` (返回 artifact id)
  - `list_for_session(session_id) -> list[ArtifactDict]`
  - `find_by_id(artifact_id) -> ArtifactDict | None`

- [ ] **Step 1: 写失败测试**

```python
# tests/data/test_artifact_store.py
import pytest
from backend.data import artifact_store


@pytest.mark.asyncio
async def test_record_artifact_returns_id():
    artifact_id = await artifact_store.record(
        session_id="sess_001",
        tool_call_id="call_001",
        path="/tmp/test.md",
        name="test.md",
        kind="markdown",
        size=100,
    )
    assert isinstance(artifact_id, str)
    assert len(artifact_id) > 0


@pytest.mark.asyncio
async def test_list_for_session_returns_recent_first():
    aid1 = await artifact_store.record("sess_001", None, "/tmp/a.md", "a.md", "markdown", 10)
    aid2 = await artifact_store.record("sess_001", None, "/tmp/b.md", "b.md", "markdown", 20)
    items = await artifact_store.list_for_session("sess_001")
    assert len(items) == 2
    assert items[0]["id"] == aid2  # 后插入的排在前面


@pytest.mark.asyncio
async def test_list_for_session_filters_by_session():
    await artifact_store.record("sess_001", None, "/tmp/a.md", "a.md", "markdown", 10)
    await artifact_store.record("sess_002", None, "/tmp/b.md", "b.md", "markdown", 20)
    items = await artifact_store.list_for_session("sess_001")
    assert len(items) == 1
    assert items[0]["path"] == "/tmp/a.md"


@pytest.mark.asyncio
async def test_find_by_id_returns_artifact():
    aid = await artifact_store.record("sess_001", None, "/tmp/x.md", "x.md", "markdown", 50)
    found = await artifact_store.find_by_id(aid)
    assert found is not None
    assert found["id"] == aid
    assert found["name"] == "x.md"


@pytest.mark.asyncio
async def test_find_by_id_returns_none_for_missing():
    found = await artifact_store.find_by_id("nonexistent_id")
    assert found is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifact_store.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 artifact_store**

```python
# backend/data/artifact_store.py
"""SQLite-backed artifact metadata store."""

from __future__ import annotations
import time
import uuid
from typing import Optional

from .database import get_database


async def record(
    session_id: str,
    tool_call_id: Optional[str],
    path: str,
    name: str,
    kind: str,
    size: int,
) -> str:
    """记录一个新的产物。返回 artifact id。"""
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    created_at = int(time.time() * 1000)
    db = await get_database()
    await db.execute(
        """
        INSERT INTO artifacts (id, session_id, tool_call_id, path, name, kind, size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, session_id, tool_call_id, path, name, kind, size, created_at),
    )
    await db.commit()
    return artifact_id


async def list_for_session(session_id: str) -> list[dict]:
    """列出指定 session 的所有产物,按 created_at 降序。"""
    db = await get_database()
    cursor = await db.execute(
        "SELECT id, session_id, tool_call_id, path, name, kind, size, created_at FROM artifacts WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row[0],
            "session_id": row[1],
            "tool_call_id": row[2],
            "path": row[3],
            "name": row[4],
            "kind": row[5],
            "size": row[6],
            "created_at": row[7],
        }
        for row in rows
    ]


async def find_by_id(artifact_id: str) -> Optional[dict]:
    """根据 id 查找产物。"""
    db = await get_database()
    cursor = await db.execute(
        "SELECT id, session_id, tool_call_id, path, name, kind, size, created_at FROM artifacts WHERE id = ?",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "tool_call_id": row[2],
        "path": row[3],
        "name": row[4],
        "kind": row[5],
        "size": row[6],
        "created_at": row[7],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifact_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/data/artifact_store.py tests/data/test_artifact_store.py
git commit -m "feat(backend): add artifact_store with record/list/find operations"
```

---

## Task 3: 后端 - artifact 文件读取与 reveal

**Files:**
- Create: `backend/data/artifact_reader.py`
- Test: `tests/data/test_artifact_reader.py`

**Interfaces:**
- Consumes: `artifact_store.find_by_id()`, workspace 路径检查
- Produces:
  - `read_text(artifact_id, max_bytes=500_000) -> dict` 返回 `{ok, kind, content, truncated}` 或 `{ok: false, error}`
  - `read_image(artifact_id, max_bytes=10_000_000) -> dict` 返回 `{ok, kind, data_url}` 或错误
  - `reveal_in_file_manager(artifact_id) -> dict` 返回 `{ok}` 或 `{ok: false, error}`

- [ ] **Step 1: 写失败测试**

```python
# tests/data/test_artifact_reader.py
import pytest
from pathlib import Path
from backend.data import artifact_store, artifact_reader


@pytest.mark.asyncio
async def test_read_text_markdown(tmp_path):
    # Arrange: 创建一个 markdown 文件并注册为 artifact
    f = tmp_path / "doc.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    aid = await artifact_store.record(
        "sess_001", None, str(f), "doc.md", "markdown", 14
    )

    # Act
    result = await artifact_reader.read_text(aid)

    # Assert
    assert result["ok"] is True
    assert result["kind"] == "markdown"
    assert result["content"] == "# Hello\n\nWorld"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_read_text_truncates_long_content(tmp_path):
    f = tmp_path / "big.md"
    f.write_text("x" * 600_000, encoding="utf-8")  # >500KB
    aid = await artifact_store.record("sess_001", None, str(f), "big.md", "markdown", 600_000)

    result = await artifact_reader.read_text(aid)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["content"]) == 500_000


@pytest.mark.asyncio
async def test_read_text_returns_error_for_missing_file(tmp_path):
    f = tmp_path / "missing.md"
    # 不写文件
    aid = await artifact_store.record("sess_001", None, str(f), "missing.md", "markdown", 0)

    result = await artifact_reader.read_text(aid)

    assert result["ok"] is False
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_read_image_returns_data_url(tmp_path):
    # 创建一个最小的有效 PNG (1x1 像素透明图)
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    f = tmp_path / "pixel.png"
    f.write_bytes(png_bytes)
    aid = await artifact_store.record("sess_001", None, str(f), "pixel.png", "image", len(png_bytes))

    result = await artifact_reader.read_image(aid)

    assert result["ok"] is True
    assert result["kind"] == "image"
    assert result["data_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_reveal_in_file_manager(tmp_path, mocker):
    f = tmp_path / "doc.md"
    f.write_text("test", encoding="utf-8")
    aid = await artifact_store.record("sess_001", None, str(f), "doc.md", "markdown", 4)

    # Mock subprocess.run 以避免实际调用系统命令
    mock_run = mocker.patch("subprocess.run", return_value=None)

    result = await artifact_reader.reveal_in_file_manager(aid)

    assert result["ok"] is True
    mock_run.assert_called_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifact_reader.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 artifact_reader**

```python
# backend/data/artifact_reader.py
"""读取 artifact 文件内容并支持 reveal in file manager。"""

from __future__ import annotations
import base64
import os
import subprocess
import sys
from pathlib import Path

from . import artifact_store

MAX_TEXT_BYTES = 500_000
MAX_IMAGE_BYTES = 10_000_000

# 扩展名 -> MIME type (图片)
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


async def read_text(artifact_id: str, max_bytes: int = MAX_TEXT_BYTES) -> dict:
    """读取文本类产物的内容。超长截断。"""
    artifact = await artifact_store.find_by_id(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact["path"])
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "binary file cannot be previewed"}

    truncated = len(text.encode("utf-8")) > max_bytes
    if truncated:
        text = text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")

    return {
        "ok": True,
        "kind": artifact["kind"],
        "content": text,
        "truncated": truncated,
    }


async def read_image(artifact_id: str, max_bytes: int = MAX_IMAGE_BYTES) -> dict:
    """读取图片类产物并返回 base64 data URL。"""
    artifact = await artifact_store.find_by_id(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact["path"])
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    size = path.stat().st_size
    if size > max_bytes:
        return {"ok": False, "error": "file too large"}

    mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "ok": True,
        "kind": "image",
        "data_url": f"data:{mime};base64,{data}",
    }


async def reveal_in_file_manager(artifact_id: str) -> dict:
    """在系统文件管理器中显示该文件。"""
    artifact = await artifact_store.find_by_id(artifact_id)
    if artifact is None:
        return {"ok": False, "error": "artifact not found"}

    path = Path(artifact["path"])
    if not path.is_file():
        return {"ok": False, "error": "file not found"}

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=True)
        elif sys.platform == "win32":
            # Windows: explorer /select,<path>
            subprocess.run(["explorer", f"/select,{path}"], check=True)
        else:
            # Linux: xdg-open 父目录
            subprocess.run(["xdg-open", str(path.parent)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/data/test_artifact_reader.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/data/artifact_reader.py tests/data/test_artifact_reader.py
git commit -m "feat(backend): add artifact_reader for read/reveal operations"
```

---

## Task 4: 后端 - API 路由

**Files:**
- Create: `backend/api/artifact_routes.py`
- Modify: `backend/main.py` (注册 router)
- Test: `tests/api/test_artifact_routes.py`

**Interfaces:**
- Consumes: `artifact_store`, `artifact_reader`
- Produces: 3 个 API 端点
  - `GET /api/v1/sessions/{session_id}/artifacts` → `{artifacts: [...]}`
  - `GET /api/v1/sessions/{session_id}/artifacts/{artifact_id}/content` → 文本或图片内容
  - `POST /api/v1/sessions/{session_id}/artifacts/{artifact_id}/reveal` → `{ok}`

- [ ] **Step 1: 写失败测试**

```python
# tests/api/test_artifact_routes.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_artifacts_endpoint(async_client: AsyncClient):
    response = await async_client.get("/api/v1/sessions/sess_test/artifacts")
    assert response.status_code == 200
    data = response.json()
    assert "artifacts" in data
    assert isinstance(data["artifacts"], list)


@pytest.mark.asyncio
async def test_get_artifact_content_returns_404_for_missing(async_client: AsyncClient):
    response = await async_client.get(
        "/api/v1/sessions/sess_test/artifacts/nonexistent_id/content"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reveal_artifact_returns_404_for_missing(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/sessions/sess_test/artifacts/nonexistent_id/reveal"
    )
    assert response.status_code == 404
```

注: 完整测试需要 fixture 提供一个已注册的 artifact。这里先验证 endpoint 存在且返回正确结构。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/api/test_artifact_routes.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 artifact_routes**

```python
# backend/api/artifact_routes.py
"""Artifact 相关的 API 路由。"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from backend.data import artifact_store, artifact_reader

router = APIRouter(prefix="/api/v1/sessions/{session_id}/artifacts", tags=["artifacts"])


@router.get("")
async def list_artifacts(session_id: str) -> dict:
    """列出指定 session 的所有产物。"""
    items = await artifact_store.list_for_session(session_id)
    return {"artifacts": items}


@router.get("/{artifact_id}/content")
async def get_artifact_content(session_id: str, artifact_id: str) -> dict:
    """读取产物内容。文本返回 content,图片返回 data_url。"""
    artifact = await artifact_store.find_by_id(artifact_id)
    if artifact is None or artifact["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact["kind"] == "image":
        return await artifact_reader.read_image(artifact_id)
    else:
        return await artifact_reader.read_text(artifact_id)


@router.post("/{artifact_id}/reveal")
async def reveal_artifact(session_id: str, artifact_id: str) -> dict:
    """在系统文件管理器中显示产物。"""
    artifact = await artifact_store.find_by_id(artifact_id)
    if artifact is None or artifact["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return await artifact_reader.reveal_in_file_manager(artifact_id)
```

- [ ] **Step 4: 在 main.py 注册路由**

读取 `backend/main.py`,找到其他 `app.include_router(...)` 调用,添加:
```python
from backend.api.artifact_routes import router as artifact_router
app.include_router(artifact_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/api/test_artifact_routes.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/api/artifact_routes.py backend/main.py tests/api/test_artifact_routes.py
git commit -m "feat(api): add artifact routes (list/content/reveal)"
```

---

## Task 5: 后端 - 拦截工具执行,记录产物

**Files:**
- Modify: `backend/chat/executors.py`
- Test: `tests/chat/test_artifact_interception.py`

**Interfaces:**
- Consumes: `artifact_store.record()`
- Produces: 当 `write_file` / `create_file` / `save_file` 工具执行成功后,自动记录产物

- [ ] **Step 1: 调查现有工具定义**

Run:
```bash
grep -rn "write_file\|create_file\|save_file" backend/chat/ --include="*.py" | grep -v test | head -10
```

识别工具名和参数结构(预期是 `{name: str, args: dict}` 形式)。

- [ ] **Step 2: 写失败测试**

```python
# tests/chat/test_artifact_interception.py
import pytest
from unittest.mock import AsyncMock
from pathlib import Path


@pytest.mark.asyncio
async def test_record_artifact_from_write_call(tmp_path, mocker):
    """当 write_file 工具执行成功后,应记录一个 artifact。"""
    # Mock artifact_store.record
    mock_record = mocker.patch(
        "backend.chat.executors.artifact_store.record",
        new=AsyncMock(return_value="art_test_123")
    )

    from backend.chat import executors

    # 创建临时文件
    target = tmp_path / "output.md"
    target.write_text("content", encoding="utf-8")

    # 调用记录函数(如果存在)
    if hasattr(executors, "record_artifact_from_path"):
        await executors.record_artifact_from_path(
            session_id="sess_test",
            tool_call_id="call_test",
            path=str(target),
        )
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["session_id"] == "sess_test"
        assert call_kwargs["path"] == str(target)
        assert call_kwargs["kind"] == "markdown"


@pytest.mark.asyncio
async def test_detect_kind_returns_correct_type():
    from backend.chat.executors import detect_artifact_kind
    assert detect_artifact_kind("file.md") == "markdown"
    assert detect_artifact_kind("script.py") == "code"
    assert detect_artifact_kind("image.png") == "image"
    assert detect_artifact_kind("data.csv") == "csv"
    assert detect_artifact_kind("unknown.xyz") == "text"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/chat/test_artifact_interception.py -v`
Expected: FAIL

- [ ] **Step 4: 在 executors.py 中添加辅助函数和拦截**

读取 `backend/chat/executors.py`,找到现有的工具执行函数。

在文件顶部添加:
```python
from backend.data import artifact_store
from pathlib import Path
```

添加辅助函数:
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


async def record_artifact_from_path(
    session_id: str,
    tool_call_id: str | None,
    path: str,
) -> str | None:
    """在文件写入成功后,记录到 artifacts 表。"""
    try:
        file_path = Path(path)
        if not file_path.is_file():
            return None
        size = file_path.stat().st_size
        return await artifact_store.record(
            session_id=session_id,
            tool_call_id=tool_call_id,
            path=str(file_path),
            name=file_path.name,
            kind=detect_artifact_kind(str(file_path)),
            size=size,
        )
    except Exception:
        # 不阻断工具执行
        return None
```

在写操作工具函数执行成功后,添加调用:
```python
# 在 write_file 工具执行成功后(找到现有的 write 逻辑结束位置)
await record_artifact_from_path(
    session_id=session_id,
    tool_call_id=tool_call_id,
    path=file_path,
)
```

(具体拦截位置需根据 executors.py 现有结构确定。优先拦截写文件类的工具,如 `write_file`。)

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/chat/test_artifact_interception.py -v`
Expected: PASS

- [ ] **Step 6: 运行全量后端测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -v`
Expected: 所有测试通过

- [ ] **Step 7: 提交**

```bash
git add backend/chat/executors.py tests/chat/test_artifact_interception.py
git commit -m "feat(chat): intercept write_file tool calls to record artifacts"
```

---

## Task 6: 前端 - artifact API 客户端

**Files:**
- Create: `src/features/artifacts/artifactApi.ts`
- Test: `src/features/artifacts/__tests__/artifactApi.test.ts`

**Interfaces:**
- Consumes: fetch API
- Produces:
  - `listArtifacts(sessionId: string): Promise<Artifact[]>`
  - `readArtifactContent(sessionId: string, artifactId: string): Promise<ArtifactContent>`
  - `revealArtifact(sessionId: string, artifactId: string): Promise<{ok: boolean}>`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/artifactApi.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { listArtifacts, readArtifactContent, revealArtifact } from '../artifactApi';

describe('artifactApi', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('listArtifacts fetches and returns artifacts', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ artifacts: [{ id: 'a1', name: 'test.md', kind: 'markdown' }] }),
    });

    const result = await listArtifacts('sess_001');

    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('a1');
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/sessions/sess_001/artifacts'
    );
  });

  it('readArtifactContent fetches content', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true, kind: 'markdown', content: '# Hello', truncated: false }),
    });

    const result = await readArtifactContent('sess_001', 'a1');

    expect(result.kind).toBe('markdown');
    expect(result.content).toBe('# Hello');
  });

  it('revealArtifact posts to reveal endpoint', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true }),
    });

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
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 artifactApi**

```typescript
// src/features/artifacts/artifactApi.ts

export interface Artifact {
  id: string;
  session_id: string;
  tool_call_id: string | null;
  path: string;
  name: string;
  kind: 'markdown' | 'code' | 'image' | 'csv' | 'json' | 'text';
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
  const res = await fetch(
    `/api/v1/sessions/${sessionId}/artifacts/${artifactId}/content`
  );
  return res.json();
}

export async function revealArtifact(
  sessionId: string,
  artifactId: string
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(
    `/api/v1/sessions/${sessionId}/artifacts/${artifactId}/reveal`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } }
  );
  return res.json();
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/artifactApi.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/artifactApi.ts src/features/artifacts/__tests__/artifactApi.test.ts
git commit -m "feat(frontend): add artifactApi client functions"
```

---

## Task 7: 前端 - useArtifacts hook

**Files:**
- Create: `src/features/artifacts/useArtifacts.ts`
- Test: `src/features/artifacts/__tests__/useArtifacts.test.ts`

**Interfaces:**
- Consumes: `artifactApi.listArtifacts`
- Produces: `{ artifacts: Artifact[], loading: boolean, refresh: () => void }`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/useArtifacts.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({
  listArtifacts: vi.fn(),
}));

import { useArtifacts } from '../useArtifacts';
import { listArtifacts } from '../artifactApi';

describe('useArtifacts', () => {
  beforeEach(() => {
    vi.mocked(listArtifacts).mockReset();
  });

  it('loads artifacts on mount', async () => {
    vi.mocked(listArtifacts).mockResolvedValue([
      { id: 'a1', session_id: 's1', tool_call_id: null, path: '/t.md', name: 't.md', kind: 'markdown', size: 10, created_at: 1 },
    ]);

    const { result } = renderHook(() => useArtifacts('sess_001'));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.artifacts).toHaveLength(1);
  });

  it('does not load when sessionId is null', async () => {
    const { result } = renderHook(() => useArtifacts(null));
    expect(result.current.artifacts).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(listArtifacts).not.toHaveBeenCalled();
  });

  it('refresh triggers refetch', async () => {
    let callCount = 0;
    vi.mocked(listArtifacts).mockImplementation(async () => {
      callCount++;
      return [{ id: `a${callCount}`, session_id: 's', tool_call_id: null, path: '/t.md', name: 't.md', kind: 'markdown', size: 1, created_at: callCount }];
    });

    const { result } = renderHook(() => useArtifacts('sess_001'));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(callCount).toBe(1);

    result.current.refresh();

    await waitFor(() => expect(callCount).toBe(2));
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
      const items = await listArtifacts(sessionId);
      setArtifacts(items);
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
Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/useArtifacts.ts src/features/artifacts/__tests__/useArtifacts.test.ts
git commit -m "feat(frontend): add useArtifacts hook"
```

---

## Task 8: 前端 - useArtifactContent hook

**Files:**
- Create: `src/features/artifacts/useArtifactContent.ts`
- Test: `src/features/artifacts/__tests__/useArtifactContent.test.ts`

**Interfaces:**
- Consumes: `artifactApi.readArtifactContent`
- Produces: `{ content: ArtifactContent | null, loading: boolean }`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/artifacts/__tests__/useArtifactContent.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../artifactApi', () => ({
  readArtifactContent: vi.fn(),
}));

import { useArtifactContent } from '../useArtifactContent';
import { readArtifactContent } from '../artifactApi';

describe('useArtifactContent', () => {
  beforeEach(() => {
    vi.mocked(readArtifactContent).mockReset();
  });

  it('loads content when artifactId is set', async () => {
    vi.mocked(readArtifactContent).mockResolvedValue({
      ok: true,
      kind: 'markdown',
      content: '# Hello',
      truncated: false,
    });

    const { result } = renderHook(() => useArtifactContent('sess_001', 'a1'));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.content?.content).toBe('# Hello');
  });

  it('clears content when artifactId is null', () => {
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
    setLoading(true);
    readArtifactContent(sessionId, artifactId)
      .then(setContent)
      .finally(() => setLoading(false));
  }, [sessionId, artifactId]);

  return { content, loading };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/features/artifacts/__tests__/useArtifactContent.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/features/artifacts/useArtifactContent.ts src/features/artifacts/__tests__/useArtifactContent.test.ts
git commit -m "feat(frontend): add useArtifactContent hook"
```

---

## Task 9: 前端 - ProgressSection 组件

**Files:**
- Create: `src/widgets/chat/progress/ProgressSection.tsx`
- Test: `src/widgets/chat/__tests__/ProgressSection.test.tsx`

**Interfaces:**
- Props:
  ```typescript
  interface ProgressSectionProps {
    iteration: number;
    streamingState: string | null;
    toolCalls: ToolCall[];
    isLoading: boolean;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ProgressSection.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ProgressSection } from '../progress/ProgressSection';

describe('ProgressSection', () => {
  it('shows iteration count when > 0', () => {
    render(<ProgressSection iteration={3} streamingState="thinking" toolCalls={[]} isLoading={true} />);
    expect(screen.getByText(/第 3 轮/)).toBeInTheDocument();
  });

  it('hides iteration when 0', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.queryByText(/第 \d+ 轮/)).not.toBeInTheDocument();
  });

  it('shows thinking state when loading', () => {
    render(<ProgressSection iteration={0} streamingState="thinking" toolCalls={[]} isLoading={true} />);
    expect(screen.getByText(/思考中/)).toBeInTheDocument();
  });

  it('shows empty state when idle', () => {
    render(<ProgressSection iteration={0} streamingState={null} toolCalls={[]} isLoading={false} />);
    expect(screen.getByText(/等待输入/)).toBeInTheDocument();
  });

  it('renders tool calls list', () => {
    const toolCalls = [
      { id: 'tc1', name: 'write_file' },
      { id: 'tc2', name: 'search' },
    ];
    render(<ProgressSection iteration={1} streamingState="tool_call" toolCalls={toolCalls} isLoading={true} />);
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
  const showIteration = iteration > 0;
  const stateLabel = streamingState ? STATE_LABELS[streamingState] ?? streamingState : null;

  return (
    <div className="p-3 space-y-2 text-sm">
      {/* Status row */}
      <div className="flex items-center gap-2">
        {isLoading && stateLabel && (
          <span className="text-primary font-medium">{stateLabel}</span>
        )}
        {showIteration && (
          <span className="text-text-secondary">第 {iteration} 轮</span>
        )}
        {!isLoading && !stateLabel && (
          <span className="text-muted">等待输入...</span>
        )}
      </div>

      {/* Tool calls list */}
      {toolCalls.length > 0 && (
        <div className="space-y-1">
          {toolCalls.map((tc) => (
            <div
              key={tc.id}
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
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/progress/ProgressSection.tsx src/widgets/chat/__tests__/ProgressSection.test.tsx
git commit -m "feat(frontend): add ProgressSection component"
```

---

## Task 10: 前端 - ArtifactRow 组件

**Files:**
- Create: `src/widgets/chat/artifacts/ArtifactRow.tsx`
- Test: `src/widgets/chat/__tests__/ArtifactRow.test.tsx`

**Interfaces:**
- Props:
  ```typescript
  interface ArtifactRowProps {
    artifact: Artifact;
    onSelect: (artifact: Artifact) => void;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactRow.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtifactRow } from '../artifacts/ArtifactRow';
import type { Artifact } from '../../../features/artifacts/artifactApi';

const sampleArtifact: Artifact = {
  id: 'a1',
  session_id: 'sess_001',
  tool_call_id: null,
  path: '/tmp/test.md',
  name: 'test.md',
  kind: 'markdown',
  size: 1024,
  created_at: 1722500000000,
};

describe('ArtifactRow', () => {
  it('renders filename and size', () => {
    render(<ArtifactRow artifact={sampleArtifact} onSelect={() => {}} />);
    expect(screen.getByText('test.md')).toBeInTheDocument();
    expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<ArtifactRow artifact={sampleArtifact} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith(sampleArtifact);
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
import type { Artifact } from '../../../features/artifacts/artifactApi';

interface ArtifactRowProps {
  artifact: Artifact;
  onSelect: (artifact: Artifact) => void;
}

const KIND_ICONS: Record<string, typeof File> = {
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
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactRow.tsx src/widgets/chat/__tests__/ArtifactRow.test.tsx
git commit -m "feat(frontend): add ArtifactRow component"
```

---

## Task 11: 前端 - ArtifactsSection 组件

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
    onSelect: (artifact: Artifact) => void;
    onReveal: (artifact: Artifact) => void;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactsSection.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtifactsSection } from '../artifacts/ArtifactsSection';
import type { Artifact } from '../../../features/artifacts/artifactApi';

const sampleArtifacts: Artifact[] = [
  { id: 'a1', session_id: 'sess_001', tool_call_id: null, path: '/tmp/a.md', name: 'a.md', kind: 'markdown', size: 100, created_at: 1 },
  { id: 'a2', session_id: 'sess_001', tool_call_id: null, path: '/tmp/b.py', name: 'b.py', kind: 'code', size: 200, created_at: 2 },
];

describe('ArtifactsSection', () => {
  it('shows empty state when no artifacts', () => {
    render(<ArtifactsSection artifacts={[]} loading={false} sessionId="sess_001" onRefresh={() => {}} onSelect={() => {}} onReveal={() => {}} />);
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  it('renders list of artifacts', () => {
    render(<ArtifactsSection artifacts={sampleArtifacts} loading={false} sessionId="sess_001" onRefresh={() => {}} onSelect={() => {}} onReveal={() => {}} />);
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.getByText('b.py')).toBeInTheDocument();
  });

  it('calls onRefresh when refresh button clicked', () => {
    const onRefresh = vi.fn();
    render(<ArtifactsSection artifacts={[]} loading={false} sessionId="sess_001" onRefresh={onRefresh} onSelect={() => {}} onReveal={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /刷新/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('shows "please select session" when sessionId is null', () => {
    render(<ArtifactsSection artifacts={[]} loading={false} sessionId={null} onRefresh={() => {}} onSelect={() => {}} onReveal={() => {}} />);
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
  artifacts,
  loading,
  sessionId,
  onRefresh,
  onSelect,
  onReveal,
}: ArtifactsSectionProps) {
  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Action bar */}
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
          onClick={onRefresh}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
      </div>

      {/* List */}
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
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactsSection.tsx src/widgets/chat/__tests__/ArtifactsSection.test.tsx
git commit -m "feat(frontend): add ArtifactsSection component"
```

---

## Task 12: 前端 - ArtifactViewer 组件

**Files:**
- Create: `src/widgets/chat/artifacts/ArtifactViewer.tsx`
- Test: `src/widgets/chat/__tests__/ArtifactViewer.test.tsx`

**Interfaces:**
- Props:
  ```typescript
  interface ArtifactViewerProps {
    artifact: Artifact;
    sessionId: string;
    onBack: () => void;
  }
  ```

- [ ] **Step 1: 写失败测试**

```tsx
// src/widgets/chat/__tests__/ArtifactViewer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../features/artifacts/useArtifactContent', () => ({
  useArtifactContent: vi.fn(),
}));

vi.mock('../../../features/artifacts/artifactApi', () => ({
  revealArtifact: vi.fn(),
}));

import { ArtifactViewer } from '../artifacts/ArtifactViewer';
import type { Artifact } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';

const sampleArtifact: Artifact = {
  id: 'a1',
  session_id: 'sess_001',
  tool_call_id: null,
  path: '/tmp/test.md',
  name: 'test.md',
  kind: 'markdown',
  size: 1024,
  created_at: 1722500000000,
};

describe('ArtifactViewer', () => {
  it('renders breadcrumb with filename', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Hello' },
      loading: false,
    });

    render(<ArtifactViewer artifact={sampleArtifact} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/产物/)).toBeInTheDocument();
    expect(screen.getByText('test.md')).toBeInTheDocument();
  });

  it('calls onBack when back button clicked', () => {
    vi.mocked(useArtifactContent).mockReturnValue({ content: null, loading: false });

    const onBack = vi.fn();
    render(<ArtifactViewer artifact={sampleArtifact} sessionId="sess_001" onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: /返回/ }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders markdown content', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Title' },
      loading: false,
    });

    render(<ArtifactViewer artifact={sampleArtifact} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/Title/)).toBeInTheDocument();
  });

  it('renders image with data_url', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'image', data_url: 'data:image/png;base64,xxx' },
      loading: false,
    });

    render(<ArtifactViewer artifact={{ ...sampleArtifact, kind: 'image' }} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,xxx');
  });

  it('shows error state', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: false, error: 'File not found' },
      loading: false,
    });

    render(<ArtifactViewer artifact={sampleArtifact} sessionId="sess_001" onBack={() => {}} />);
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
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import { revealArtifact } from '../../../features/artifacts/artifactApi';

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
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = []; cell = '';
    } else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c !== ''));
}

export function ArtifactViewer({ artifact, sessionId, onBack }: ArtifactViewerProps) {
  const { content, loading } = useArtifactContent(sessionId, artifact.id);

  const handleCopyPath = () => {
    navigator.clipboard?.writeText(artifact.path);
  };

  const handleReveal = () => {
    revealArtifact(sessionId, artifact.id);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          onClick={onBack}
          aria-label="返回"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 text-sm">
          <span className="text-muted">产物</span>
          <span className="mx-1 text-muted">/</span>
          <span className="text-text">{artifact.name}</span>
        </div>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          onClick={handleCopyPath}
          title="复制路径"
        >
          <Copy className="w-4 h-4" />
        </button>
        <button
          className="p-1.5 rounded hover:bg-bg-hover"
          onClick={handleReveal}
          title="在文件管理器中显示"
        >
          <FolderOpen className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {loading ? (
          <div className="text-sm text-muted">加载中...</div>
        ) : !content || !content.ok ? (
          <div className="text-sm text-error">{content?.error ?? '加载失败'}</div>
        ) : content.kind === 'image' ? (
          <img src={content.data_url} alt={artifact.name} className="max-w-full" />
        ) : content.kind === 'markdown' ? (
          <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>
        ) : content.kind === 'code' || content.kind === 'json' ? (
          <pre className="whitespace-pre-wrap text-xs font-mono bg-bg-hover p-2 rounded">
            {content.content}
          </pre>
        ) : content.kind === 'csv' ? (
          <CsvPreview text={content.content ?? ''} />
        ) : (
          <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>
        )}
      </div>
    </div>
  );
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ArtifactViewer.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/widgets/chat/artifacts/ArtifactViewer.tsx src/widgets/chat/__tests__/ArtifactViewer.test.tsx
git commit -m "feat(frontend): add ArtifactViewer with multi-format preview"
```

---

## Task 13: 前端 - RightPanel + RightPanelToggle 组件

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

describe('RightPanel', () => {
  const defaultProps = {
    open: true,
    onToggle: vi.fn(),
    iteration: 0,
    streamingState: null,
    toolCalls: [],
    isLoading: false,
    sessionId: 'sess_001',
  };

  it('renders Progress tab by default', () => {
    render(<RightPanel {...defaultProps} />);
    expect(screen.getByText('Progress')).toBeInTheDocument();
    expect(screen.getByText('Artifacts')).toBeInTheDocument();
  });

  it('switches to Artifacts tab on click', () => {
    render(<RightPanel {...defaultProps} />);
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
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { ProgressSection } from './progress/ProgressSection';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ArtifactViewer } from './artifacts/ArtifactViewer';
import type { Artifact } from '../../features/artifacts/artifactApi';

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
  open,
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  sessionId,
}: RightPanelProps) {
  const [tab, setTab] = useState<Tab>('progress');
  const [selected, setSelected] = useState<Artifact | null>(null);
  const { artifacts, loading, refresh } = useArtifacts(sessionId);

  return (
    <aside
      className={
        'fixed top-12 right-0 h-[calc(100vh-3rem)] w-80 bg-surface border-l border-border transform transition-transform duration-200 ease-in-out z-30 ' +
        (open ? 'translate-x-0' : 'translate-x-full')
      }
    >
      {/* Tab bar (hide when viewing artifact) */}
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

      {/* Content */}
      <div className="h-[calc(100%-3rem)]">
        {selected && sessionId ? (
          <ArtifactViewer
            artifact={selected}
            sessionId={sessionId}
            onBack={() => setSelected(null)}
          />
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
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/widgets/chat/RightPanel.tsx src/widgets/chat/RightPanelToggle.tsx src/widgets/chat/__tests__/RightPanel.test.tsx
git commit -m "feat(frontend): add RightPanel drawer container with tab switching"
```

---

## Task 14: 前端 - 确认 useChat 暴露 streamingToolCalls

**Files:**
- Modify: `src/features/send-message/useChat.ts` (确认即可)

**Interfaces:**
- 确认 useChat 返回值中包含 `streamingToolCalls: ToolCall[]`

- [ ] **Step 1: 检查 useChat 是否暴露 streamingToolCalls**

Run:
```bash
grep -n "streamingToolCalls" src/features/send-message/useChat.ts
```

如果存在 `return { ... streamingToolCalls }`,此任务无需改动。
如果不存在,在 return 语句中添加 `streamingToolCalls`。

- [ ] **Step 2: 运行现有 useChat 测试**

Run: `cd /home/fz/project/sage && npx vitest run src/features/send-message/`
Expected: 所有现有测试通过

- [ ] **Step 3: 提交(如有改动)**

```bash
git add src/features/send-message/useChat.ts
git commit -m "feat(frontend): expose streamingToolCalls from useChat hook"
```

(如果 useChat 已经返回 streamingToolCalls,此任务可以跳过。)

---

## Task 15: 前端 - 集成 RightPanel 到 Chat.tsx

**Files:**
- Modify: `src/pages/Chat.tsx`

- [ ] **Step 1: 添加状态和组件导入**

读取 `src/pages/Chat.tsx`,在顶部添加:
```typescript
import { useState } from 'react';
import { RightPanel } from '../widgets/chat/RightPanel';
import { RightPanelToggle } from '../widgets/chat/RightPanelToggle';
```

- [ ] **Step 2: 添加状态**

在 Chat 组件内部添加:
```typescript
const [rightPanelOpen, setRightPanelOpen] = useState(false);
```

- [ ] **Step 3: 从 useChat 解构 streamingToolCalls**

修改 destructure:
```typescript
const {
  messages,
  isLoading,
  error,
  clearError,
  sendMessage,
  interrupt,
  loadMessages,
  currentAgentId,
  streamingMessageId,
  iteration,
  streamingState,
  streamingToolCalls,  // 新增
} = useChat();
```

- [ ] **Step 4: 在 JSX 中插入 RightPanelToggle**

将外层 `<div className="flex-1 flex flex-col min-h-0">` 改为:
```tsx
<div className="flex-1 flex flex-col min-h-0 relative">
```

在页面头部工具栏(`<div className="h-12 ...">`) 内 `<h2>` 之后,添加:
```tsx
<RightPanelToggle
  open={rightPanelOpen}
  onClick={() => setRightPanelOpen(!rightPanelOpen)}
/>
```

- [ ] **Step 5: 在 Chat 组件末尾添加 RightPanel**

在 `<ChatInput />` 之后添加:
```tsx
<RightPanel
  open={rightPanelOpen}
  onToggle={() => setRightPanelOpen(!rightPanelOpen)}
  iteration={iteration}
  streamingState={streamingState}
  toolCalls={streamingToolCalls}
  isLoading={isLoading}
  sessionId={currentSessionId}
/>
```

- [ ] **Step 6: 运行全量前端测试**

Run: `cd /home/fz/project/sage && npx vitest run`
Expected: 所有测试通过

- [ ] **Step 7: 手动验证**

启动后端:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python /home/fz/project/sage/backend/main.py
```

启动前端:
```bash
cd /home/fz/project/sage && npm run dev
```

访问 http://localhost:1420/chat:
1. 验证右上角面板切换按钮可见
2. 点击切换按钮,RightPanel 从右侧滑入
3. Progress Tab 默认显示,显示流式状态
4. 切换到 Artifacts Tab,显示 "暂无产物"(新会话)

- [ ] **Step 8: 提交**

```bash
git add src/pages/Chat.tsx
git commit -m "feat(frontend): integrate RightPanel into Chat page"
```

---

## Task 16: 全量测试与文档归档

**Files:**
- Create: `docs/technical/31-artifacts-panel.md`

- [ ] **Step 1: 运行全量测试**

后端:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest -v
```

前端:
```bash
cd /home/fz/project/sage && npx vitest run
```

Expected: 全部通过

- [ ] **Step 2: 运行 typecheck**

```bash
cd /home/fz/project/sage && npm run typecheck 2>&1 | tail -20
```

Expected: 无 error

- [ ] **Step 3: 创建技术文档**

```markdown
# 31 - Artifacts Panel

> 日期: 2026-08-01
> 状态: 已实现

## 概述

Chat 页面右侧的抽屉式面板,包含 Progress(工具调用进度)和 Artifacts(AI 生成的文件)两个标签页。

## 架构

\`\`\`
Tool Executor → artifact_store.record() → SQLite artifacts 表
                                              ↓
                              GET /api/v1/sessions/{id}/artifacts
                                              ↓
                            Frontend RightPanel.ArtifactsSection
\`\`\`

## 后端

- **数据库表**:\`artifacts\` (\`backend/data/migrations/006_add_artifacts_table.py\`)
- **数据访问**:\`backend/data/artifact_store.py\` (record / list_for_session / find_by_id)
- **文件读取**:\`backend/data/artifact_reader.py\` (read_text / read_image / reveal_in_file_manager)
- **API 路由**:\`backend/api/artifact_routes.py\`
  - \`GET /api/v1/sessions/{session_id}/artifacts\`
  - \`GET /api/v1/sessions/{session_id}/artifacts/{artifact_id}/content\`
  - \`POST /api/v1/sessions/{session_id}/artifacts/{artifact_id}/reveal\`

## 前端

- **Hooks**:
  - \`useArtifacts(sessionId)\` - 产物列表
  - \`useArtifactContent(sessionId, artifactId)\` - 产物内容
- **组件**:
  - \`RightPanel\` - 抽屉容器(Progress + Artifacts Tab 切换)
  - \`RightPanelToggle\` - 右上角切换按钮
  - \`ProgressSection\` - 流式状态 + 工具调用列表
  - \`ArtifactsSection\` - 产物列表 + 空状态
  - \`ArtifactRow\` - 单个产物行(图标 + 文件名 + 大小)
  - \`ArtifactViewer\` - 多格式预览(markdown / code / csv / json / image)

## 限制

- 文本预览最大 500KB(超出截断)
- 图片预览最大 10MB(超出报错)
- 仅显示 kind = markdown/code/image/csv/json/text
- 二进制文件不支持预览,需用"在文件管理器中打开"

## 后续迭代

- PDF 预览(pdf.js)
- Excel 预览(SheetJS)
- 产物跳转到对应消息(通过 tool_call_id)
- 产物搜索/过滤
```

保存到 `docs/technical/31-artifacts-panel.md`。

- [ ] **Step 4: 更新技术手册 README**

读取 `docs/technical/README.md`,在章节目录中添加:
```
| 31 | [Artifacts Panel](31-artifacts-panel.md) | Chat 页面右侧的 Progress + Artifacts 抽屉面板 |
```

- [ ] **Step 5: 提交**

```bash
git add docs/technical/31-artifacts-panel.md docs/technical/README.md
git commit -m "docs: add artifacts panel technical documentation"
```

- [ ] **Step 6: 删除计划文档**

实现完成后,按规则删除 `docs/superpowers/plans/2026-08-01-artifacts-panel.md`。

```bash
git rm docs/superpowers/plans/2026-08-01-artifacts-panel.md
git commit -m "chore: archive completed artifacts panel implementation plan"
```