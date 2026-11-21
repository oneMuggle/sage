# Design Workbench Streamline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/design` 设计工作台从「4 步向导 + 裸文本框迭代」压缩为「单屏开局 + 可回滚的版本闭环」,首次产出的必填字段从 5 个降到 1 个,并补齐版本历史、迭代记录持久化与导出直达。

**Architecture:** 后端在现有 `DesignStudio` / `DesignRepo` 基础上增加服务端默认值解析（system_id / template_id / name 可选）、产物历史读取与恢复端点、文件式迭代消息存储（沿用 `source.json` 的 per-project JSON 模式，不新增数据库表）、导出内联 base64 响应；前端把 `DesignCreateWizard` 替换为单屏 `DesignCreateComposer`，详情页右栏改为「迭代 / 版本」双 Tab，导出改为浏览器 Blob 下载。

**Tech Stack:** FastAPI (pydantic v1/v2 shim)、SQLite、React + Zustand + Tailwind、Vitest + Testing Library、Electron IPC relay。

**Spec:** 本计划基于 2026-11-19 会话中与 `/home/fz/project/open-design` 的对比分析；参考实现位于 `/home/fz/project/open-design/apps/web/src/components/HomeHero.tsx`（Chip Rail）与 `apps/web/src/edit-mode/`（版本/编辑闭环）。

## Global Constraints

- 分支基于 `release/win7`：后端测试必须使用 `/home/fz/anaconda3/envs/sage-backend-py38/bin/python`,Py3.8 兼容（`typing.List/Optional`,禁用 PEP 604 `X | Y`）。
- 请求模型保持 `extra="forbid"`；新字段一律带默认值,保证旧调用方（聊天 6 个 `design_*` 工具）不变。
- 不新增数据库迁移：迭代消息存 `<workspace>/design/<project_id>/messages.json`。
- 前端所有后端调用经 `backendRequest`（Electron IPC relay）,不得裸 `fetch`。
- 文案同时改 `src/shared/lib/i18n/locales/zh/design.ts` 与 `en/design.ts`。
- 每任务完成即 commit（conventional commits）。

---

### Task 1: 后端可选参数 + 服务端默认值

**Files:**
- Modify: `backend/api/v1/design_routes.py:51-59`（`CreateProjectRequest`）、`:209-235`（`create_project` 路由）
- Modify: `backend/design/design_studio.py:74-96`（`create_project`）+ 文件顶部常量与辅助函数
- Test: `backend/tests/unit/test_design_studio.py`、`backend/tests/unit/test_design_routes.py`

**Interfaces:**
- Produces:
  - `CreateProjectRequest(name: Optional[str] = None, kind: str = "deck", system_id: Optional[str] = None, template_id: Optional[str] = None, brief: str)`
  - `DesignStudio.create_project(name: Optional[str] = None, kind: str = "deck", system_id: Optional[str] = None, template_id: Optional[str] = None, brief: str = "") -> DesignProject`
  - `DesignStudio._default_system_id() -> str`、`_default_template_id(kind: str) -> str`、模块级 `_derive_project_name(brief: str) -> str`

- [x] **Step 1: 写失败测试（studio 默认值）**

在 `backend/tests/unit/test_design_studio.py` 追加（fixture 已含 `test-sys` 系统与 `test-page` 原型模板）：

```python
def test_create_project_defaults_system_template_and_name(studio):
    project = studio.create_project(brief="Q4 路线图演示稿")
    assert project.system_id == "test-sys"
    assert project.template_id == "test-page"
    assert project.kind == "prototype"
    assert project.name == "Q4 路线图演示稿"


def test_create_project_defaults_pick_kind_matching_template(studio):
    project = studio.create_project(kind="prototype", brief="landing")
    template = studio.list_templates(kind="prototype")[0]
    assert project.template_id == template.id
```

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_studio.py -k defaults -v`
Expected: FAIL（`create_project` 仍要求全部位置参数）

- [x] **Step 3: 实现 studio 默认值**

`backend/design/design_studio.py` 顶部：

```python
_DEFAULT_SYSTEM_IDS = ("minimal", "corporate")
_DEFAULT_TEMPLATE_IDS = {
    "deck": ("pitch-deck", "weekly-report"),
    "prototype": ("landing-page", "dashboard", "pricing", "docs-page"),
}


def _derive_project_name(brief: str) -> str:
    """From the brief's first non-empty line, capped at 24 chars."""
    for line in (brief or "").splitlines():
        cleaned = line.strip().lstrip("#-*> ").strip()
        if cleaned:
            return cleaned[:24]
    return "Untitled design"
```

`DesignStudio` 内新增：

```python
def _default_system_id(self) -> str:
    available = {s.id for s in self._systems.list_systems()}
    if not available:
        raise DesignSystemNotFoundError("No design systems are available")
    for candidate in _DEFAULT_SYSTEM_IDS:
        if candidate in available:
            return candidate
    return sorted(available)[0]

def _default_template_id(self, kind: str) -> str:
    available = [t.id for t in self._templates.list_templates_by_kind(kind)]
    if not available:
        raise DesignTemplateNotFoundError(
            f"No templates are available for kind '{kind}'"
        )
    for candidate in _DEFAULT_TEMPLATE_IDS.get(kind, ()):
        if candidate in available:
            return candidate
    return available[0]
```

`create_project` 改为：

```python
def create_project(
    self,
    name: Optional[str] = None,
    kind: str = "deck",
    system_id: Optional[str] = None,
    template_id: Optional[str] = None,
    brief: str = "",
) -> DesignProject:
    resolved_system = system_id or self._default_system_id()
    resolved_template = template_id or self._default_template_id(kind)
    resolved_name = (name or "").strip() or _derive_project_name(brief)
    self._systems.get_system(resolved_system)
    self._resolve_template_for_kind(resolved_template, kind)
    now = datetime.now(timezone.utc)  # noqa: UP017
    return self._repo.create_project(
        id=str(uuid.uuid4()), name=resolved_name, kind=kind,
        system_id=resolved_system, template_id=resolved_template,
        brief=brief, created_at=now, updated_at=now,
    )
```

需补 import：`DesignSystemNotFoundError`、`DesignTemplateNotFoundError`。

- [x] **Step 4: 路由模型与调用改为可选**

`design_routes.py`：

```python
class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    kind: str = "deck"
    system_id: Optional[str] = None
    template_id: Optional[str] = None
    brief: str
```

`create_project` 路由的 `studio.create_project(...)` 调用改为透传 `name=req.name, kind=req.kind, system_id=req.system_id, template_id=req.template_id, brief=req.brief`（原本已是关键字参数，无需改）。

- [x] **Step 5: 补路由测试**

`test_design_routes.py` 追加：

```python
async def test_create_project_with_only_brief(self, studio):
    client, *_ = studio
    resp = await client.post("/api/v1/design/projects", json={"brief": "only brief"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["system_id"] == "test-sys"
    assert body["template_id"] == "test-page"
    assert body["name"] == "only brief"
```

（若该文件 fixture 返回形态不同,按文件内 `test_create_project` 的取用方式对齐。）

- [x] **Step 6: 运行全部设计后端测试**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py backend/tests/unit/test_design_tools.py -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add backend/design/design_studio.py backend/api/v1/design_routes.py backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py
git commit -m "feat(design): default missing system/template/name on project create"
```

---

### Task 2: 产物历史读取 + 版本恢复端点

**Files:**
- Modify: `backend/design/design_studio.py`（`list_artifacts` / `get_artifact` / `restore_artifact`）
- Modify: `backend/api/v1/design_routes.py`（3 个新端点）
- Test: `backend/tests/unit/test_design_studio.py`、`backend/tests/unit/test_design_routes.py`

**Interfaces:**
- Produces:
  - `DesignStudio.list_artifacts(project_id: str) -> List[DesignArtifact]`
  - `DesignStudio.get_artifact(artifact_id: str) -> DesignArtifact`
  - `DesignStudio.restore_artifact(project_id: str, artifact_id: str) -> DesignArtifact`（把旧 HTML 作为新版本追加,不调 LLM）
  - `GET /api/v1/design/projects/{id}/artifacts` → `[{id, project_id, version, title, kind, created_at}]`（不含 html_content）
  - `GET /api/v1/design/projects/{id}/artifacts/{artifact_id}` → 完整 artifact
  - `POST /api/v1/design/projects/{id}/artifacts/{artifact_id}/restore` → 新 artifact

- [x] **Step 1: 写失败测试（studio）**

```python
def test_restore_artifact_appends_new_version(studio):
    project = studio.create_project(brief="restore me")
    first = studio.add_artifact(project.id, "<html>v1</html>", title="One")
    second = studio.add_artifact(project.id, "<html>v2</html>", title="Two")
    restored = studio.restore_artifact(project.id, first.id)
    assert restored.version == second.version + 1
    assert restored.html_content == "<html>v1</html>"
    versions = [a.version for a in studio.list_artifacts(project.id)]
    assert versions == [1, 2, 3]


def test_restore_artifact_rejects_foreign_project(studio):
    p1 = studio.create_project(brief="a")
    p2 = studio.create_project(brief="b")
    artifact = studio.add_artifact(p1.id, "<html/>", title="x")
    with pytest.raises(DesignProjectNotFoundError):
        studio.restore_artifact(p2.id, artifact.id)
```

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_studio.py -k restore -v`
Expected: FAIL（`list_artifacts` 不存在）

- [x] **Step 3: 实现 studio 方法**

```python
def list_artifacts(self, project_id: str) -> List[DesignArtifact]:
    """List all artifact versions of a project, oldest first."""
    self._repo.get_project(project_id)
    return self._repo.list_artifacts(project_id)

def get_artifact(self, artifact_id: str) -> DesignArtifact:
    """Fetch one artifact (including HTML content) by ID."""
    return self._repo.get_artifact(artifact_id)

def restore_artifact(
    self, project_id: str, artifact_id: str,
) -> DesignArtifact:
    """Append a copy of an old artifact as a new version (no LLM call)."""
    self._repo.get_project(project_id)
    source = self._repo.get_artifact(artifact_id)
    if source.project_id != project_id:
        raise DesignProjectNotFoundError(
            f"Artifact {artifact_id} does not belong to project {project_id}"
        )
    return self.add_artifact(
        project_id, source.html_content, title=source.title, kind=source.kind,
    )
```

- [x] **Step 4: 加路由**

```python
@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(project_id: str):
    """Return artifact version summaries (no HTML payload)."""
    studio = _require_studio()
    try:
        artifacts = studio.list_artifacts(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return [
        {
            "id": a.id, "project_id": a.project_id, "version": a.version,
            "title": a.title, "kind": a.kind,
            "created_at": a.created_at.isoformat(),
        }
        for a in artifacts
    ]


@router.get("/projects/{project_id}/artifacts/{artifact_id}")
async def get_artifact(project_id: str, artifact_id: str):
    """Return one artifact with its full HTML content."""
    studio = _require_studio()
    try:
        studio.get_project(project_id)
        artifact = studio.get_artifact(artifact_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    if artifact.project_id != project_id:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Artifact {artifact_id} not in project {project_id}"},
        )
    return artifact.model_dump()


@router.post("/projects/{project_id}/artifacts/{artifact_id}/restore")
async def restore_artifact(project_id: str, artifact_id: str):
    """Restore an old artifact by appending it as a new version."""
    studio = _require_studio()
    try:
        artifact = studio.restore_artifact(project_id, artifact_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return artifact.model_dump()
```

- [x] **Step 5: 路由测试**

```python
async def test_artifact_history_and_restore(self, studio):
    client, studio_obj = studio
    project = studio_obj.create_project(brief="history")
    first = studio_obj.add_artifact(project.id, "<html>1</html>", title="One")
    studio_obj.add_artifact(project.id, "<html>2</html>", title="Two")

    listing = await client.get(f"/api/v1/design/projects/{project.id}/artifacts")
    assert listing.status_code == 200
    assert [a["version"] for a in listing.json()] == [1, 2]
    assert "html_content" not in listing.json()[0]

    restored = await client.post(
        f"/api/v1/design/projects/{project.id}/artifacts/{first.id}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["html_content"] == "<html>1</html>"
```

（`studio` fixture 的实际解包方式按文件内既有测试对齐。）

- [x] **Step 6: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add backend/design/design_studio.py backend/api/v1/design_routes.py backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py
git commit -m "feat(design): expose artifact history and restore endpoints"
```

---

### Task 3: 迭代消息持久化（文件式）

**Files:**
- Create: `backend/design/messages_store.py`
- Modify: `backend/design/design_studio.py`（`__init__` 实例化 + `iterate` 记录 + `list_messages`）
- Modify: `backend/api/v1/design_routes.py`（`GET /design/projects/{id}/messages`）
- Test: `backend/tests/unit/test_design_messages.py`（新建）、`test_design_routes.py`、`test_design_studio.py`

**Interfaces:**
- Produces:
  - `IterationMessage`（pydantic: `id/role/content/artifact_id?/artifact_version?/created_at`）
  - `MessageStore(base_dir: Path).list(project_id) -> List[IterationMessage]`
  - `MessageStore(base_dir).append(project_id, role, content, *, artifact_id=None, artifact_version=None) -> IterationMessage`
  - `DesignStudio.list_messages(project_id) -> List[IterationMessage]`

- [x] **Step 1: 写失败测试（store）**

新建 `backend/tests/unit/test_design_messages.py`：

```python
"""Unit tests for the file-backed iteration message store."""
from __future__ import annotations

from backend.design.messages_store import MessageStore


def test_append_and_list_round_trip(tmp_path):
    store = MessageStore(tmp_path)
    first = store.append("p1", "user", "make it calmer")
    second = store.append(
        "p1", "assistant", "applied", artifact_version=2, artifact_id="a2",
    )
    messages = store.list("p1")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].id == first.id
    assert messages[1].artifact_version == 2
    assert messages[1].artifact_id == "a2"
    assert second.created_at


def test_list_unknown_project_is_empty(tmp_path):
    assert MessageStore(tmp_path).list("missing") == []


def test_list_corrupt_file_returns_empty(tmp_path):
    project_dir = tmp_path / "p1"
    project_dir.mkdir()
    (project_dir / "messages.json").write_text("{not json", encoding="utf-8")
    assert MessageStore(tmp_path).list("p1") == []


def test_projects_are_isolated(tmp_path):
    store = MessageStore(tmp_path)
    store.append("p1", "user", "one")
    store.append("p2", "user", "two")
    assert [m.content for m in store.list("p1")] == ["one"]
    assert [m.content for m in store.list("p2")] == ["two"]
```

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_messages.py -q`
Expected: FAIL（找不到模块）

- [x] **Step 3: 实现 `messages_store.py`**

```python
"""File-backed iteration message store (per project)."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel

from backend.compat.win7.pydantic_compat import ConfigDict

logger = logging.getLogger(__name__)

__all__ = ["IterationMessage", "MessageStore"]


class IterationMessage(BaseModel):
    """One design iteration chat message."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: Literal["user", "assistant"]
    content: str
    artifact_id: Optional[str] = None
    artifact_version: Optional[int] = None
    created_at: str


class MessageStore:
    """Persist iteration messages under ``<base_dir>/<project_id>/messages.json``."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()

    def _path(self, project_id: str) -> Path:
        return self._base_dir / Path(project_id).name / "messages.json"

    def list(self, project_id: str) -> List[IterationMessage]:
        """Read all messages; missing or corrupt files yield an empty list."""
        path = self._path(project_id)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable design messages file: %s", path)
            return []
        if not isinstance(raw, list):
            return []
        messages: List[IterationMessage] = []
        for item in raw:
            try:
                messages.append(IterationMessage(**item))
            except (TypeError, ValueError):
                continue
        return messages

    def append(
        self,
        project_id: str,
        role: str,
        content: str,
        *,
        artifact_id: Optional[str] = None,
        artifact_version: Optional[int] = None,
    ) -> IterationMessage:
        """Append one message and atomically rewrite the file."""
        message = IterationMessage(
            id=str(uuid.uuid4()),
            role=role,  # type: ignore[arg-type]
            content=content,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            created_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )
        with self._lock:
            messages = self.list(project_id)
            messages.append(message)
            path = self._path(project_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    [m.model_dump() for m in messages],
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        return message
```

- [x] **Step 4: 接入 studio**

`DesignStudio.__init__` 追加 `self._messages = MessageStore(workspace_dir / "design")`。

`iterate()` 在 `self._repo.update_project_status(project_id, "generating")` 之前：

```python
self._messages.append(project_id, "user", feedback)
```

在创建 artifact、`update_project_status(... "complete")` 之后：

```python
self._messages.append(
    project_id, "assistant", artifact.title,
    artifact_id=artifact.id, artifact_version=artifact.version,
)
```

新增方法：

```python
def list_messages(self, project_id: str) -> List[IterationMessage]:
    """List persisted iteration messages for a project."""
    self._repo.get_project(project_id)
    return self._messages.list(project_id)
```

- [x] **Step 5: 路由**

```python
@router.get("/projects/{project_id}/messages")
async def list_messages(project_id: str):
    """Return persisted iteration messages (oldest first)."""
    studio = _require_studio()
    try:
        messages = studio.list_messages(project_id)
    except DesignProjectNotFoundError as exc:
        return _map_design_error(exc)
    return [m.model_dump() for m in messages]
```

- [x] **Step 6: 测试 iterate 记录**

在 `test_design_studio.py` 追加（使用 mock LLM fixture）：

```python
@pytest.mark.asyncio
async def test_iterate_records_messages(studio):
    project = studio.create_project(brief="iterate me")
    first = studio.add_artifact(project.id, "<html/>", title="Base")
    await studio.iterate(project.id, "darker palette")
    messages = studio.list_messages(project.id)
    assert messages[0].role == "user"
    assert messages[0].content == "darker palette"
    assert messages[-1].role == "assistant"
    assert messages[-1].artifact_version > first.version
```

在 `test_design_routes.py` 追加 GET messages 的 200/404 用例。

- [x] **Step 7: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_messages.py backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py -q`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add backend/design/messages_store.py backend/design/design_studio.py backend/api/v1/design_routes.py backend/tests/unit/test_design_messages.py backend/tests/unit/test_design_studio.py backend/tests/unit/test_design_routes.py
git commit -m "feat(design): persist iteration messages per project"
```

---

### Task 4: 导出内联下载（base64）

**Files:**
- Modify: `backend/api/v1/design_routes.py:79-84`（`ExportRequest`）、`:436-456`（导出响应）
- Test: `backend/tests/unit/test_design_routes.py`

**Interfaces:**
- Produces: `ExportRequest.inline: bool = False`；`inline=True` 且 `format != html` 时响应 `{ok, format, filename, content_base64}`。

- [x] **Step 1: 写失败测试**

```python
async def test_export_zip_inline_returns_base64(self, studio):
    client, studio_obj = studio
    project = studio_obj.create_project(brief="zip me")
    studio_obj.add_artifact(project.id, "<html><body>x</body></html>", title="Z")
    resp = await client.post(
        f"/api/v1/design/projects/{project.id}/export",
        json={"format": "zip", "inline": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["filename"].endswith(".zip")
    assert base64.b64decode(body["content_base64"])[:2] == b"PK"
```

文件顶部补 `import base64`。

- [x] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_routes.py -k inline -v`
Expected: FAIL（unknown field `inline`）

- [x] **Step 3: 实现**

```python
class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = "html"
    inline: bool = False
```

导出路由 `return result.model_dump()` 之前：

```python
if req.inline and req.format != "html" and result.file_path:
    import base64
    from pathlib import Path as _Path

    path = _Path(result.file_path)
    return {
        "ok": True,
        "format": result.format,
        "filename": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }

return result.model_dump()
```

- [x] **Step 4: 运行测试**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_routes.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add backend/api/v1/design_routes.py backend/tests/unit/test_design_routes.py
git commit -m "feat(design): support inline base64 export downloads"
```

---

### Task 5: 前端数据层（types / api / store）

**Files:**
- Modify: `src/entities/design/types.ts`
- Modify: `src/entities/design/designApi.ts`
- Modify: `src/entities/design/designStore.ts`
- Test: `src/entities/design/__tests__/designStore.test.ts`（新建）

**Interfaces:**
- Produces（types）：
  - `CreateProjectInput { name?: string; kind: ProjectKind; system_id?: string; template_id?: string; brief: string }`
  - `DesignArtifactSummary { id; project_id; version; title; kind; created_at }`
  - `IterationMessage { id; role: 'user' | 'assistant'; content; artifact_id?: string | null; artifact_version?: number | null; created_at }`
  - `ExportResult.content_base64?: string; filename?: string`
- Produces（api）：`listArtifacts` / `getArtifact` / `restoreArtifact` / `listMessages`；`exportArtifact(projectId, format, inline?)`
- Produces（store）：`messages`、`artifacts`、`previewArtifact` 状态；`loadArtifacts`、`previewVersion`、`restoreVersion`、`clearPreview`；`loadProject` 并行拉取 detail + messages + artifacts。

- [x] **Step 1: 写失败测试（store）**

`src/entities/design/__tests__/designStore.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../designApi';
import { useDesignStore } from '../designStore';

vi.mock('../designApi');

const baseProject = {
  id: 'p1', name: 'Demo', kind: 'deck' as const, system_id: 's',
  template_id: 't', brief: 'b', status: 'complete' as const,
  created_at: '2026-11-19T00:00:00Z', updated_at: '2026-11-19T00:00:00Z',
};

describe('designStore version + message state', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useDesignStore.setState({
      currentProject: null, currentArtifact: null, previewArtifact: null,
      artifacts: [], messages: [], loadingProject: false, errorProject: null,
    });
  });

  it('loadProject loads detail, messages and artifacts together', async () => {
    vi.mocked(api.getProject).mockResolvedValue({ ...baseProject, latest_artifact: null });
    vi.mocked(api.listMessages).mockResolvedValue([
      { id: 'm1', role: 'user', content: 'hi', created_at: '2026-11-19T00:00:00Z' },
    ]);
    vi.mocked(api.listArtifacts).mockResolvedValue([
      { id: 'a1', project_id: 'p1', version: 1, title: 'v1', kind: 'html', created_at: '2026-11-19T00:00:00Z' },
    ]);

    await useDesignStore.getState().loadProject('p1');

    expect(useDesignStore.getState().messages).toHaveLength(1);
    expect(useDesignStore.getState().artifacts[0].version).toBe(1);
  });

  it('previewVersion fetches the full artifact into previewArtifact', async () => {
    vi.mocked(api.getArtifact).mockResolvedValue({
      id: 'a1', project_id: 'p1', version: 1, html_content: '<html/>',
      title: 'v1', kind: 'html', export_formats: ['html'],
      source_prompt: '', created_at: '2026-11-19T00:00:00Z', css_injected: '',
    });

    await useDesignStore.getState().previewVersion('p1', 'a1');

    expect(useDesignStore.getState().previewArtifact?.version).toBe(1);
  });

  it('restoreVersion calls the API and clears the preview', async () => {
    vi.mocked(api.restoreArtifact).mockResolvedValue({
      id: 'a2', project_id: 'p1', version: 2, html_content: '<html/>',
      title: 'v1', kind: 'html', export_formats: ['html'],
      source_prompt: '', created_at: '2026-11-19T00:00:00Z', css_injected: '',
    });
    vi.mocked(api.getProject).mockResolvedValue({ ...baseProject, latest_artifact: null });
    vi.mocked(api.listMessages).mockResolvedValue([]);
    vi.mocked(api.listArtifacts).mockResolvedValue([]);

    await useDesignStore.getState().restoreVersion('p1', 'a1');

    expect(api.restoreArtifact).toHaveBeenCalledWith('p1', 'a1');
    expect(useDesignStore.getState().previewArtifact).toBeNull();
  });
});
```

- [x] **Step 2: 运行确认失败**

Run: `npm run test -- src/entities/design/__tests__/designStore.test.ts`
Expected: FAIL（`listMessages` 未定义）

- [x] **Step 3: 实现 types / api / store**

`types.ts` 追加：

```ts
export interface CreateProjectInput {
  name?: string;
  kind: ProjectKind;
  system_id?: string;
  template_id?: string;
  brief: string;
}

export interface DesignArtifactSummary {
  id: string;
  project_id: string;
  version: number;
  title: string;
  kind: string;
  created_at: string;
}

export interface IterationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  artifact_id?: string | null;
  artifact_version?: number | null;
  created_at: string;
}
```

`ExportResult` 增加 `filename?: string; content_base64?: string;`。

`designApi.ts`：

```ts
export async function createProject(input: CreateProjectInput): Promise<DesignProject> { ... body: input ... }

export async function listArtifacts(projectId: string): Promise<DesignArtifactSummary[]> {
  return backendRequest<DesignArtifactSummary[]>({
    method: 'GET', path: `${BASE}/projects/${projectId}/artifacts`,
  });
}

export async function getArtifact(projectId: string, artifactId: string): Promise<DesignArtifact> {
  return backendRequest<DesignArtifact>({
    method: 'GET', path: `${BASE}/projects/${projectId}/artifacts/${artifactId}`,
  });
}

export async function restoreArtifact(projectId: string, artifactId: string): Promise<DesignArtifact> {
  return backendRequest<DesignArtifact>({
    method: 'POST', path: `${BASE}/projects/${projectId}/artifacts/${artifactId}/restore`,
  });
}

export async function listMessages(projectId: string): Promise<IterationMessage[]> {
  return backendRequest<IterationMessage[]>({
    method: 'GET', path: `${BASE}/projects/${projectId}/messages`,
  });
}

export async function exportArtifact(
  projectId: string, format: ExportFormat, inline = false,
): Promise<ExportResult> {
  const request: ExportRequest = inline ? { format, inline: true } : { format };
  ...
}
```

`ExportRequest` 增加 `inline?: boolean`。

`designStore.ts` 新增状态/动作：

```ts
messages: IterationMessage[];
artifacts: DesignArtifactSummary[];
previewArtifact: DesignArtifact | null;

async loadProject(projectId) {
  set({ loadingProject: true, errorProject: null });
  try {
    const [detail, messages, artifacts] = await Promise.all([
      api.getProject(projectId),
      api.listMessages(projectId),
      api.listArtifacts(projectId),
    ]);
    set({
      currentProject: detail,
      currentArtifact: detail.latest_artifact,
      messages, artifacts, previewArtifact: null, loadingProject: false,
    });
  } catch (error) { ... }
},

async previewVersion(projectId, artifactId) {
  const artifact = await api.getArtifact(projectId, artifactId);
  set({ previewArtifact: artifact });
},

async restoreVersion(projectId, artifactId) {
  await api.restoreArtifact(projectId, artifactId);
  set({ previewArtifact: null });
  await useDesignStore.getState().loadProject(projectId);
},

clearPreview() { set({ previewArtifact: null }); },
```

`generate` / `iterate` 成功后改为 `await useDesignStore.getState().loadProject(projectId)` 统一刷新（替换现有 getProject 调用），保证 versions + messages 同步。

- [x] **Step 4: 运行测试**

Run: `npm run test -- src/entities/design/__tests__/designStore.test.ts`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/entities/design/types.ts src/entities/design/designApi.ts src/entities/design/designStore.ts src/entities/design/__tests__/designStore.test.ts
git commit -m "feat(design-ui): add history, messages and inline export data layer"
```

---

### Task 6: 单屏创作器替换 4 步向导

**Files:**
- Create: `src/features/design/DesignCreateComposer.tsx`
- Delete: `src/features/design/DesignCreateWizard.tsx`
- Modify: `src/pages/DesignStudio.tsx:11,69-73`
- Modify: `src/shared/lib/i18n/locales/zh/design.ts`、`.../en/design.ts`
- Test: `src/features/design/__tests__/DesignCreateComposer.test.tsx`（新建）

**Interfaces:**
- Produces: `<DesignCreateComposer onCancel={} onCreated={(id) => void} />`；提交时调用 `createProject({ name?, kind, system_id?, template_id?, brief })`，成功后 `generate(project.id, brief)`。

- [x] **Step 1: 写失败测试**

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDesignStore } from '../../../entities/design/designStore';
import { DesignCreateComposer } from '../DesignCreateComposer';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe('DesignCreateComposer', () => {
  beforeEach(() => {
    useDesignStore.setState({
      systems: [{ id: 'minimal', name: 'Minimal', description: '', category: 'general', tokens_css: '', design_md: '' }],
      templates: [
        { id: 'pitch-deck', name: 'Pitch', description: '', kind: 'deck', skill_md: '', assets: {} },
        { id: 'landing-page', name: 'Landing', description: '', kind: 'prototype', skill_md: '', assets: {} },
      ],
      createProject: vi.fn().mockResolvedValue({ id: 'p1' }),
      generate: vi.fn().mockResolvedValue(undefined),
    } as never);
  });

  it('creates and generates with a single brief (defaults omitted)', async () => {
    const onCreated = vi.fn();
    render(<DesignCreateComposer onCancel={() => {}} onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText('design.composer.brief'), {
      target: { value: '8 页投资人演示稿' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'design.composer.create' }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('p1'));
    expect(useDesignStore.getState().createProject).toHaveBeenCalledWith({
      name: undefined, kind: 'deck', system_id: undefined, template_id: undefined,
      brief: '8 页投资人演示稿',
    });
  });

  it('prefills kind and template when a preset chip is chosen', async () => {
    render(<DesignCreateComposer onCancel={() => {}} onCreated={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'design.preset.landing' }));
    fireEvent.change(screen.getByLabelText('design.composer.brief'), {
      target: { value: 'landing page for our SaaS' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'design.composer.create' }));

    await waitFor(() =>
      expect(useDesignStore.getState().createProject).toHaveBeenCalledWith(
        expect.objectContaining({ kind: 'prototype', template_id: 'landing-page' }),
      ),
    );
  });
});
```

注意：store 的 action 在 zustand 中不能直接 `setState` 成 mock 后仍读到原闭包——测试里 mock 通过 `setState({ createProject: vi.fn() })` 覆盖即可；若 store 类型不允许，改为 `vi.spyOn(useDesignStore.getState(), 'createProject')`。

- [x] **Step 2: 运行确认失败**

Run: `npm run test -- src/features/design/__tests__/DesignCreateComposer.test.tsx`
Expected: FAIL（组件不存在）

- [x] **Step 3: 实现组件**

结构（Tailwind,复用现有页面样式）：

```tsx
const PRESETS = [
  { key: 'design.preset.pitch', kind: 'deck', templateId: 'pitch-deck' },
  { key: 'design.preset.weekly', kind: 'deck', templateId: 'weekly-report' },
  { key: 'design.preset.landing', kind: 'prototype', templateId: 'landing-page' },
  { key: 'design.preset.dashboard', kind: 'prototype', templateId: 'dashboard' },
  { key: 'design.preset.pricing', kind: 'prototype', templateId: 'pricing' },
] as const;

export function DesignCreateComposer({ onCancel, onCreated }: Props) {
  const systems = useDesignStore((s) => s.systems);
  const templates = useDesignStore((s) => s.templates);
  const createProject = useDesignStore((s) => s.createProject);
  const generate = useDesignStore((s) => s.generate);

  const [kind, setKind] = useState<ProjectKind>('deck');
  const [templateId, setTemplateId] = useState<string | undefined>();
  const [systemId, setSystemId] = useState<string | undefined>();
  const [name, setName] = useState('');
  const [brief, setBrief] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const availablePresets = useMemo(
    () => PRESETS.filter((p) => templates.some((tpl) => tpl.id === p.templateId && tpl.kind === p.kind)),
    [templates],
  );
  const kindTemplates = useMemo(() => templates.filter((tpl) => tpl.kind === kind), [templates, kind]);

  const handleSubmit = async () => {
    const trimmed = brief.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true); setError(null);
    try {
      const project = await createProject({
        name: name.trim() || undefined,
        kind,
        system_id: systemId,
        template_id: templateId,
        brief: trimmed,
      });
      onCreated(project.id);
      void generate(project.id, trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };
  // JSX: 大 textarea + chips + 折叠高级选项 + 提交按钮
}
```

要点：
- textarea 必须有 `id="design-brief"` + `<label htmlFor="design-brief">`，文案 key `design.composer.brief`。
- kind 切换时若当前 templateId 与新 kind 不匹配则清空。
- 提交按钮文案 `design.composer.create`，loading 用 `design.composer.creating`。
- 「高级选项」披露按钮文案 `design.composer.advanced`。

- [x] **Step 4: 替换页面引用并删除向导**

`DesignStudio.tsx`：import 与渲染改为 `DesignCreateComposer`；`git rm src/features/design/DesignCreateWizard.tsx`。

- [x] **Step 5: i18n 新增 key（zh/en 同步）**

```
design.composer.brief / briefPlaceholder
design.composer.presetsHint / advanced / name
design.composer.create / creating
design.preset.pitch / weekly / landing / dashboard / pricing
design.empty.hint 改为「描述你想做什么，其余交给默认设计系统与模板。」
```

- [x] **Step 6: 运行测试 + 类型检查**

Run: `npm run test -- src/features/design/__tests__/DesignCreateComposer.test.tsx`
Run: `npx tsc --noEmit`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/features/design/DesignCreateComposer.tsx src/features/design/__tests__/DesignCreateComposer.test.tsx src/pages/DesignStudio.tsx src/shared/lib/i18n/locales/zh/design.ts src/shared/lib/i18n/locales/en/design.ts
git rm src/features/design/DesignCreateWizard.tsx
git commit -m "feat(design-ui): replace 4-step wizard with single-screen composer"
```

---

### Task 7: 版本历史 + 迭代记录 UI

**Files:**
- Create: `src/features/design/DesignVersionPanel.tsx`
- Modify: `src/features/design/DesignGenerationView.tsx`
- Modify: `src/features/design/DesignIterationChat.tsx`
- Modify: i18n zh/en
- Test: `src/features/design/__tests__/DesignGenerationDetail.test.tsx`（新建,覆盖版本列表渲染与预览切换）

**Interfaces:**
- Consumes: store `messages / artifacts / previewArtifact`、`previewVersion / restoreVersion / clearPreview`
- Produces: 右栏 Tab（`design.detail.tabIterate` / `design.detail.tabHistory`）；预览区顶部只读横幅（`design.detail.previewing`）。

- [x] **Step 1: 写失败测试**

```tsx
it('shows version list and loads preview on click', async () => {
  useDesignStore.setState({
    artifacts: [
      { id: 'a2', project_id: 'p1', version: 2, title: 'v2', kind: 'html', created_at: '2026-11-19T00:00:00Z' },
      { id: 'a1', project_id: 'p1', version: 1, title: 'v1', kind: 'html', created_at: '2026-11-19T00:00:00Z' },
    ],
    previewVersion: vi.fn(),
  } as never);
  render(<DesignVersionPanel projectId="p1" />);
  expect(screen.getByText('v2')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'design.version.preview' }));
  expect(useDesignStore.getState().previewVersion).toHaveBeenCalled();
});
```

- [x] **Step 2: 实现 `DesignVersionPanel`**

- 列表按 version 降序；每行：`v{n}`、title、时间（`new Date(created_at).toLocaleString()`）。
- 两个按钮：`design.version.preview`（调 `previewVersion(projectId, id)`）、`design.version.restore`（调 `restoreVersion`,成功后 toast）。
- 空态：`design.version.empty`。

- [x] **Step 3: 改造 `DesignGenerationView`**

- `const [panel, setPanel] = useState<'iterate' | 'history'>('iterate')`。
- 右栏头部两枚 Tab 按钮；`panel === 'iterate' ? <DesignIterationChat/> : <DesignVersionPanel/>`。
- 预览源：`const shown = previewArtifact ?? artifact`。
- 当 `previewArtifact` 存在时,预览区顶部渲染横幅：

```tsx
<div className="mb-2 flex items-center justify-between rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-ui-xs">
  <span>{t('design.detail.previewing').replace('{version}', String(previewArtifact.version))}</span>
  <div className="flex gap-2">
    <button onClick={clearPreview}>{t('design.detail.backToLatest')}</button>
    <button onClick={() => void restoreVersion(projectId, previewArtifact.id)}>
      {t('design.version.restore')}
    </button>
  </div>
</div>
```

- 版本徽章继续显示当前最新版本；预览时额外显示 `v{preview.version}`。

- [x] **Step 4: 改造 `DesignIterationChat`**

- 删除本地 `history` state,改读 `useDesignStore((s) => s.messages)`。
- user 消息右对齐（accent/10），assistant 消息左对齐（surface-hover），assistant 显示 `v{artifact_version}`。
- 发送后 store.iterate 已负责重新拉取 messages；失败时保留错误条。

- [x] **Step 5: i18n**

```
design.detail.tabIterate / tabHistory
design.detail.previewing («正在预览 v{version}（只读）»)
design.detail.backToLatest
design.version.preview / restore / empty / restored
```

- [x] **Step 6: 运行测试 + tsc**

Run: `npm run test -- src/features/design src/entities/design`
Run: `npx tsc --noEmit`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add src/features/design/DesignVersionPanel.tsx src/features/design/DesignGenerationView.tsx src/features/design/DesignIterationChat.tsx src/features/design/__tests__/DesignGenerationDetail.test.tsx src/shared/lib/i18n/locales/zh/design.ts src/shared/lib/i18n/locales/en/design.ts
git commit -m "feat(design-ui): version timeline, preview banner and persisted iteration history"
```

---

### Task 8: 导出直达下载

**Files:**
- Modify: `src/features/design/DesignExportPanel.tsx`
- Modify: i18n zh/en（`design.export.success` 文案改为「已下载 {name}」）

**Interfaces:**
- Consumes: `exportArtifact(projectId, format, inline=true)` → `{filename, content_base64}`。

- [x] **Step 1: 实现下载**

```ts
const MIME: Record<ExportFormat, string> = {
  pdf: 'application/pdf',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  zip: 'application/zip',
  html: 'text/html;charset=utf-8',
};

function downloadBase64(base64: string, filename: string, mime: string): void {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
```

`handleExport`：

```ts
const result = await exportArtifact(projectId, format, true);
if (!result.ok) throw new Error(result.error ?? result.format);
if (format === 'html' && result.html_content) {
  downloadHtml(result.html_content, `${designName}.html`);
} else if (result.content_base64 && result.filename) {
  downloadBase64(result.content_base64, result.filename, MIME[format]);
}
toast.success(t('design.export.success').replace('{name}', result.filename ?? format.toUpperCase()));
```

- [ ] **Step 2: 手测（Electron）——未执行**:需在桌面端真机验证 PDF/PPTX/ZIP 下载（自动化侧已由 `test_export_zip_inline_returns_base64` 覆盖）。

启动 worktree 前端 (`npm run dev` + electron),生成一个 deck → 依次导出 PDF/PPTX/ZIP,确认浏览器下载目录出现文件。若 LibreOffice 不可用,验证 PDF 降级 reportlab 仍可下载。

- [x] **Step 3: Commit**

```bash
git add src/features/design/DesignExportPanel.tsx src/shared/lib/i18n/locales/zh/design.ts src/shared/lib/i18n/locales/en/design.ts
git commit -m "feat(design-ui): download exported files directly instead of showing paths"
```

---

### Task 9: 文档更新与全量验证

**Files:**
- Modify: `docs/technical/151-design-studio-content-craft.md` §11（前端工作台）、§6（内容数量改为 17 系统 / 13 deck / 4 原型 / 5 craft）
- Modify: `docs/technical/README.md:131`（章节简介同步）
- Modify: 本计划文件（勾选完成项并补实施记录）

- [x] **Step 1: 更新技术文档 §11/§6**

§11 描述改为：单屏创作器（意图 presets + 可选高级项）、详情页「迭代 / 版本」双 Tab、版本预览/恢复、消息持久化路径 `<workspace>/design/<id>/messages.json`、导出内联下载。

- [x] **Step 2: 全量后端测试（py38）**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_design_*.py backend/tests/unit/test_craft_loader.py backend/tests/unit/test_prompt_composer.py -q`
Expected: PASS

- [x] **Step 3: 前端测试 + 构建**

Run: `npm run test -- src/entities/design src/features/design`
Run: `npx tsc --noEmit`
Run: `npm run build`（或项目约定的 CI 等价命令）
Expected: PASS

- [x] **Step 4: 架构棘轮检查**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/architecture -q`
（若基线因新增文件行数变化,按棘轮脚本 `--tighten` 流程按分支实测后更新基线,勿跨分支复制数值。）

- [x] **Step 5: Commit**

```bash
git add docs/technical/151-design-studio-content-craft.md docs/technical/README.md docs/plans/2026-11-19_design-workbench-streamline.md
git commit -m "docs(design): document streamlined workbench flow and refresh content counts"
```

---

## 实施记录（2026-11-19）

- 全部 9 个任务完成,按任务分别提交（Task 1–8 各一个 commit,Task 9 合并为文档/基线 commit）。
- 验证结果:
  - 后端设计测试 `test_design_*.py`:208 passed（含新增 messages / history / inline export 用例）。
  - 前端 `vitest`:design store 5 + composer 3 + version panel 3 = 11 passed;`tsc --noEmit` 通过;`npm run build` 通过。
  - 架构棘轮 `node scripts/architecture-check.mjs` 通过（`test_design_routes.py` 基线 1171 → 1288,仅改该条目）。
- 与计划的偏差:
  - 本分支技术文档编号为 §155（非 main 的 §151）。
  - 迭代消息持久化改为 best-effort:`DesignStudio._record_message` 失败仅告警,避免 mock/磁盘异常拖垮生成主流程（工具测试回归发现）。
  - 测试 fixture 与实际结构对齐（系统 id `test` / `test-sys`、路由测试内自建 AsyncClient）。
- 待办:Electron 真机手测导出下载;cherry-pick 到 main 并分别开 PR。

## 后续里程碑（本计划范围外,列出以防遗漏）

- [x] M5: Tweaks 微调面板 — 已实施(2026-11-20)。后端 `tweaks_store.py` + GET/PUT `/tweaks` 端点;前端 `DesignTweaksPanel` + `designTweaks.ts`(`applyTweaks` / `extractTweakDefaults`)+ 第三 Tab + i18n;测试 83 全绿。
- M6: 生成阶段流式进度 — 已实施(2026-11-21)。后端 `generate/iterate` 推送 starting→composing→generating→linting→saving→complete 进度(可选 `progress_queue` + 内存 `_progress`),新增 `GET /projects/{id}/progress`;SSE 路由改为 queue 驱动并抽离到 `design_streaming.py`;前端 800ms 轮询 + `DesignProgressStrip` 阶段条;220 后端 / 86 前端测试全绿。
- M7: Word 大纲导入 / 数据源绑定 / 图表嵌入的前端入口（后端端点均已存在）。
- M8: 首轮结构化简报、三方向选择、区块级局部重生成、可选评审。

## Self-Review

- 覆盖对照：P0 减步骤 → Task 1/6；迭代闭环 → Task 2/3/5/7；导出直达 → Task 4/8；文档 → Task 9。P1.5/P2 明确列入后续里程碑,不在本次范围。
- 无占位符：所有任务均给出具体文件、接口与可运行测试。
- 类型一致性：`CreateProjectInput` 可选字段、`IterationMessage.artifact_version`、`ExportResult.content_base64/filename` 在前后端任务中命名一致。
