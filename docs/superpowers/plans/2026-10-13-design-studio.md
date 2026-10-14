# Design Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a design studio module that generates HTML/CSS prototypes and presentations using LLM-driven generation, with design system management, iterative refinement, and export capabilities.

**Architecture:** New `backend/design/` module sits alongside `backend/office/`. The generator composes a system prompt from DESIGN.md + SKILL.md + brief, calls the existing LLM gateway, parses `<artifact>` HTML blocks from the response, and bundles a standalone HTML file. Frontend adds a full-page Design Studio with iframe preview and iteration chat.

**Tech Stack:** Python 3.10, FastAPI, Pydantic v2, SQLite, React 18, TypeScript, Vite

**Spec:** `docs/superpowers/specs/2026-10-13-opendesign-design-studio-integration.md`

## Global Constraints

- Python backend uses conda env `sage-backend` (Python 3.10.20, pydantic 2.x)
- All Pydantic models use `ConfigDict(extra="forbid")`
- Tools extend `BaseTool` from `backend.tools.base`, register in `register_all_tools()`
- Routers use `APIRouter`, mounted in `backend/main.py` under `/api/v1`
- Tests use pytest (classes `TestXxx`), no unittest
- Design system content is Apache-2.0 from OpenDesign
- LLM calls go through `LLMClient` in `backend.core.legacy.llm_client`

---

## File Structure

```
backend/design/
├── __init__.py              # Lazy exports (follows office/__init__.py pattern)
├── errors.py                # DesignError exception hierarchy
├── models.py                # Pydantic models
├── systems.py               # Design system registry (loads DESIGN.md + tokens)
├── templates.py             # Template registry (loads SKILL.md + assets)
├── prompt_composer.py       # System prompt assembly
├── artifact_parser.py       # <artifact> tag extraction from LLM output
├── standalone_bundler.py    # Inline CSS/JS/images → self-contained HTML
├── generator.py             # Core: prompt → LLM → parse → bundle → store
├── export.py                # HTML → PDF/PPTX/ZIP conversion
└── design_studio.py         # Top-level orchestrator

backend/data/
├── design_repo.py           # DesignProject + DesignArtifact CRUD
└── migrations/
    └── 0XX_add_design_tables.py  # Appended to existing MIGRATIONS list

backend/tools/
├── design_generate_tool.py
├── design_iterate_tool.py
├── design_export_tool.py
├── design_list_systems_tool.py
└── design_list_templates_tool.py

backend/api/v1/
└── design_routes.py         # REST API for design studio

backend/skills/skill_md/shipped/
├── design-prototype/SKILL.md
└── design-deck/SKILL.md

backend/design/content/
├── NOTICE.md                # Apache-2.0 attribution
├── systems/                 # Design systems (DESIGN.md + tokens.css + manifest.json)
│   └── minimal/...
└── templates/               # Generation templates
    └── prototype/landing-page/...

backend/tests/unit/
├── test_design_errors.py
├── test_design_models.py
├── test_design_repo.py
├── test_design_systems.py
├── test_design_templates.py
├── test_prompt_composer.py
├── test_artifact_parser.py
├── test_standalone_bundler.py
├── test_design_generator.py
├── test_design_studio.py
├── test_design_migration.py
└── test_design_tools.py

src/features/design/
├── DesignStudio.tsx
├── BriefComposer.tsx
├── DesignSystemPicker.tsx
├── TemplatePicker.tsx
├── ArtifactPreview.tsx
├── IterationChat.tsx
├── ArtifactHistory.tsx
├── ExportPanel.tsx
├── DesignProjectsList.tsx
├── useDesignProjects.ts
├── useDesignGeneration.ts
└── designApi.ts
```

---

## Milestone 1: Foundation + Core Generator

### Task 1: Error Definitions

**Files:**
- Create: `backend/design/__init__.py`
- Create: `backend/design/errors.py`
- Test: `backend/tests/unit/test_design_errors.py`

**Interfaces:**
- Consumes: Nothing
- Produces: `DesignError` base + 5 subclasses, importable from `backend.design.errors`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_errors.py
from __future__ import annotations
import pytest
from backend.design.errors import (
    DesignError,
    DesignSystemNotFoundError,
    DesignTemplateNotFoundError,
    DesignGenerationError,
    DesignExportError,
    DesignProjectNotFoundError,
)


class TestDesignErrors:
    def test_base_error_is_exception(self):
        err = DesignError("test message")
        assert str(err) == "test message"
        assert isinstance(err, Exception)

    def test_system_not_found(self):
        err = DesignSystemNotFoundError("minimal")
        assert isinstance(err, DesignError)
        assert "minimal" in str(err)

    def test_template_not_found(self):
        err = DesignTemplateNotFoundError("landing-page")
        assert isinstance(err, DesignError)

    def test_generation_error(self):
        err = DesignGenerationError("LLM timeout")
        assert isinstance(err, DesignError)

    def test_export_error(self):
        err = DesignExportError("PDF render failed")
        assert isinstance(err, DesignError)

    def test_project_not_found(self):
        err = DesignProjectNotFoundError("proj-123")
        assert isinstance(err, DesignError)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_errors.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.design'`

- [ ] **Step 3: Create package and implement errors**

```python
# backend/design/__init__.py
"""Design studio module — HTML/CSS prototype and presentation generation."""
```

```python
# backend/design/errors.py
"""Design studio exception hierarchy."""
from __future__ import annotations


class DesignError(Exception):
    """Base exception for all design studio errors."""


class DesignSystemNotFoundError(DesignError):
    """Raised when a design system ID is not found in the registry."""


class DesignTemplateNotFoundError(DesignError):
    """Raised when a template ID is not found in the registry."""


class DesignGenerationError(DesignError):
    """Raised when LLM generation fails or produces unparseable output."""


class DesignExportError(DesignError):
    """Raised when export to PDF/PPTX/ZIP fails."""


class DesignProjectNotFoundError(DesignError):
    """Raised when a design project ID is not found."""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_errors.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/__init__.py backend/design/errors.py backend/tests/unit/test_design_errors.py
git commit -m "feat(design): add error hierarchy for design studio module"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `backend/design/models.py`
- Test: `backend/tests/unit/test_design_models.py`

**Interfaces:**
- Consumes: Nothing
- Produces: `DesignSystem`, `DesignTemplate`, `DesignProject`, `DesignArtifact`, `DesignGenerateRequest`, `DesignIterateRequest`, `DesignExportRequest`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_models.py
from __future__ import annotations
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from backend.design.models import (
    DesignSystem,
    DesignTemplate,
    DesignProject,
    DesignArtifact,
    DesignGenerateRequest,
    DesignIterateRequest,
    DesignExportRequest,
)


class TestDesignSystem:
    def test_valid_system(self):
        system = DesignSystem(
            id="minimal",
            name="Minimal",
            category="general",
            description="A minimal design system",
            design_md="# Minimal\n\nColors: black, white",
            tokens_css=":root { --bg: #fff; --fg: #000; }",
            design_tokens={"bg": {"value": "#fff", "type": "color"}},
            tags=["minimal", "clean"],
        )
        assert system.id == "minimal"
        assert len(system.tags) == 2

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DesignSystem(
                id="x", name="x", category="x", description="x",
                design_md="x", tokens_css="x", design_tokens={},
                tags=[], unknown_field="bad",
            )


class TestDesignTemplate:
    def test_valid_prototype_template(self):
        t = DesignTemplate(
            id="landing-page",
            name="Landing Page",
            kind="prototype",
            description="Product landing page",
            skill_md="# Landing Page\nGenerate a hero section...",
            example_html="<html>...</html>",
            assets={"base.css": "body { margin: 0; }"},
            design_system_required=True,
        )
        assert t.kind == "prototype"
        assert "base.css" in t.assets

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            DesignTemplate(
                id="x", name="x", kind="invalid_kind",
                description="x", skill_md="x", assets={},
                design_system_required=False,
            )


class TestDesignProject:
    def test_valid_project(self):
        now = datetime.now(timezone.utc)
        p = DesignProject(
            id="proj-1",
            name="My Landing Page",
            kind="prototype",
            system_id="minimal",
            template_id="landing-page",
            brief="Create a SaaS landing page",
            status="draft",
            created_at=now,
            updated_at=now,
        )
        assert p.status == "draft"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            DesignProject(
                id="x", name="x", kind="prototype",
                system_id="x", template_id="x", brief="x",
                status="invalid_status",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )


class TestDesignArtifact:
    def test_valid_artifact(self):
        now = datetime.now(timezone.utc)
        a = DesignArtifact(
            id="art-1",
            project_id="proj-1",
            version=1,
            html_content="<!DOCTYPE html><html></html>",
            css_injected=":root { --bg: #fff; }",
            title="My Page",
            file_path="design/proj-1/v1.html",
            kind="html",
            export_formats=["html", "pdf"],
            source_prompt="Generate a landing page...",
            created_at=now,
        )
        assert a.version == 1


class TestRequests:
    def test_generate_request(self):
        r = DesignGenerateRequest(
            project_id="proj-1",
            brief="Create a landing page",
            system_id="minimal",
            template_id="landing-page",
        )
        assert r.model_id is None

    def test_iterate_request(self):
        r = DesignIterateRequest(
            project_id="proj-1",
            feedback="Change the button color to blue",
        )
        assert r.feedback.startswith("Change")

    def test_export_request(self):
        r = DesignExportRequest(artifact_id="art-1", format="pdf")
        assert r.format == "pdf"

    def test_export_invalid_format(self):
        with pytest.raises(ValidationError):
            DesignExportRequest(artifact_id="art-1", format="docx")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_models.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement models**

```python
# backend/design/models.py
"""Pydantic models for the design studio module."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DesignSystem(BaseModel):
    """A design system definition (DESIGN.md + tokens)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    description: str
    design_md: str
    tokens_css: str
    design_tokens: dict
    tags: list[str]


class DesignTemplate(BaseModel):
    """A generation template (SKILL.md + assets)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["prototype", "deck"]
    description: str
    skill_md: str
    example_html: str | None = None
    assets: dict[str, str]
    design_system_required: bool


class DesignProject(BaseModel):
    """A design project (user session)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: Literal["prototype", "deck"]
    system_id: str
    template_id: str
    brief: str
    status: Literal["draft", "generating", "complete", "error"]
    created_at: datetime
    updated_at: datetime


class DesignArtifact(BaseModel):
    """A generated design artifact (one version of a project's output)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    version: int
    html_content: str
    css_injected: str
    title: str
    file_path: str
    kind: Literal["html", "deck", "standalone"]
    export_formats: list[str]
    source_prompt: str
    created_at: datetime


class DesignGenerateRequest(BaseModel):
    """Request to generate a new design artifact."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    brief: str
    system_id: str
    template_id: str
    model_id: str | None = None


class DesignIterateRequest(BaseModel):
    """Request to iterate on an existing design artifact."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    feedback: str
    model_id: str | None = None


class DesignExportRequest(BaseModel):
    """Request to export a design artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    format: Literal["html", "pdf", "pptx", "zip"]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_models.py -v
```
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/models.py backend/tests/unit/test_design_models.py
git commit -m "feat(design): add Pydantic models for design studio"
```

---

### Task 3: Database Migration

**Files:**
- Modify: `backend/data/migrations/runner.py` (append migration entry)
- Test: `backend/tests/unit/test_design_migration.py`

**Interfaces:**
- Consumes: Migration runner pattern from `backend.data.migrations.runner`
- Produces: `design_projects` and `design_artifacts` tables in `sage.db`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_migration.py
from __future__ import annotations
import sqlite3
import pytest


class TestDesignMigration:
    @pytest.fixture()
    def conn(self, tmp_path):
        """Create a fresh database for each test."""
        db_path = tmp_path / "test.db"
        c = sqlite3.connect(str(db_path))
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        yield c
        c.close()

    def test_migration_creates_design_projects(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for version, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        assert design_migration is not None, "Design migration not found in MIGRATIONS list"
        design_migration(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='design_projects'"
        )
        assert cursor.fetchone() is not None

    def test_migration_creates_design_artifacts(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for version, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='design_artifacts'"
        )
        assert cursor.fetchone() is not None

    def test_design_projects_columns(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for version, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute("PRAGMA table_info(design_projects)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "id", "name", "kind", "system_id", "template_id",
            "brief", "status", "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_design_artifacts_columns(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for version, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        cursor = conn.execute("PRAGMA table_info(design_artifacts)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "id", "project_id", "version", "file_path", "kind",
            "title", "export_formats", "source_prompt", "created_at",
        }
        assert expected.issubset(columns)

    def test_insert_and_query_project(self, conn):
        from backend.data.migrations.runner import MIGRATIONS

        design_migration = None
        for version, name, fn in MIGRATIONS:
            if "design" in name.lower():
                design_migration = fn
                break

        design_migration(conn)

        conn.execute(
            """INSERT INTO design_projects
               (id, name, kind, system_id, template_id, brief,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("p1", "Test", "prototype", "minimal", "landing-page",
             "brief", "draft", "2026-10-13", "2026-10-13"),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT name, kind FROM design_projects WHERE id = ?", ("p1",)
        )
        row = cursor.fetchone()
        assert row == ("Test", "prototype")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_migration.py -v
```
Expected: FAIL — "Design migration not found in MIGRATIONS list"

- [ ] **Step 3: Add migration to runner.py**

Read the last few lines of `backend/data/migrations/runner.py` to find the current highest version number, then append:

```python
def _add_design_tables(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS design_projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('prototype', 'deck')),
            system_id TEXT NOT NULL,
            template_id TEXT NOT NULL,
            brief TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft', 'generating', 'complete', 'error')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS design_artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL
                REFERENCES design_projects(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            kind TEXT NOT NULL
                CHECK(kind IN ('html', 'deck', 'standalone')),
            title TEXT NOT NULL,
            export_formats TEXT NOT NULL DEFAULT '[]',
            source_prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, version)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_artifacts_project "
        "ON design_artifacts(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_projects_status "
        "ON design_projects(status)"
    )

register_migration(VERSION, "add_design_tables", _add_design_tables)
```

Replace `VERSION` with the next integer after the current highest version in the file.

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_migration.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/data/migrations/runner.py backend/tests/unit/test_design_migration.py
git commit -m "feat(design): add migration for design_projects and design_artifacts tables"
```

---

### Task 4: Design Repo

**Files:**
- Create: `backend/data/design_repo.py`
- Test: `backend/tests/unit/test_design_repo.py`

**Interfaces:**
- Consumes: `DesignProject`, `DesignArtifact` from `backend.design.models`; SQLite `conn`
- Produces: `DesignRepo` class with CRUD methods

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_repo.py
from __future__ import annotations
import sqlite3
import pytest
from datetime import datetime, timezone

from backend.data.design_repo import DesignRepo
from backend.design.errors import DesignProjectNotFoundError


class TestDesignRepo:
    @pytest.fixture()
    def repo(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE design_projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                kind TEXT NOT NULL, system_id TEXT NOT NULL,
                template_id TEXT NOT NULL, brief TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE design_artifacts (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                version INTEGER NOT NULL, file_path TEXT NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL,
                export_formats TEXT NOT NULL DEFAULT '[]',
                source_prompt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(project_id, version)
            )
        """)
        conn.commit()
        return DesignRepo(conn)

    @pytest.fixture()
    def now(self):
        return datetime.now(timezone.utc)

    def test_create_and_get_project(self, repo, now):
        repo.create_project(
            id="p1", name="Test Page", kind="prototype",
            system_id="minimal", template_id="landing-page",
            brief="Create a landing page",
            created_at=now, updated_at=now,
        )
        project = repo.get_project("p1")
        assert project.id == "p1"
        assert project.name == "Test Page"
        assert project.status == "draft"

    def test_get_project_not_found(self, repo):
        with pytest.raises(DesignProjectNotFoundError):
            repo.get_project("nonexistent")

    def test_list_projects(self, repo, now):
        repo.create_project(
            "p1", "Page 1", "prototype", "minimal", "landing-page",
            "brief1", now, now,
        )
        repo.create_project(
            "p2", "Page 2", "deck", "corporate", "html-ppt",
            "brief2", now, now,
        )
        projects = repo.list_projects()
        assert len(projects) == 2

    def test_update_project_status(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.update_project_status("p1", "generating")
        project = repo.get_project("p1")
        assert project.status == "generating"

    def test_delete_project(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.delete_project("p1")
        with pytest.raises(DesignProjectNotFoundError):
            repo.get_project("p1")

    def test_create_and_get_artifact(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            id="a1", project_id="p1", version=1,
            html_content="<html></html>", title="v1",
            file_path=str(tmp_path / "v1.html"),
            kind="html", export_formats=["html", "pdf"],
            source_prompt="Generate...", created_at=now,
        )
        artifact = repo.get_artifact("a1")
        assert artifact.project_id == "p1"
        assert artifact.version == 1

    def test_list_artifacts_for_project(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            "a1", "p1", 1, "<html>v1</html>", "v1",
            str(tmp_path / "v1.html"), "html", ["html"], "", now,
        )
        repo.create_artifact(
            "a2", "p1", 2, "<html>v2</html>", "v2",
            str(tmp_path / "v2.html"), "html", ["html"], "", now,
        )
        artifacts = repo.list_artifacts("p1")
        assert len(artifacts) == 2

    def test_get_latest_artifact(self, repo, now):
        repo.create_project(
            "p1", "Test", "prototype", "minimal", "landing-page",
            "brief", now, now,
        )
        repo.create_artifact(
            "a1", "p1", 1, "<html>v1</html>", "v1",
            str(tmp_path / "v1.html"), "html", ["html"], "", now,
        )
        repo.create_artifact(
            "a2", "p1", 2, "<html>v2</html>", "v2",
            str(tmp_path / "v2.html"), "html", ["html"], "", now,
        )
        latest = repo.get_latest_artifact("p1")
        assert latest.version == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_repo.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DesignRepo**

```python
# backend/data/design_repo.py
"""SQLite repository for design projects and artifacts."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.design.errors import DesignProjectNotFoundError
from backend.design.models import DesignArtifact, DesignProject


class DesignRepo:
    """CRUD operations for design_projects and design_artifacts tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_project(
        self,
        id: str,
        name: str,
        kind: str,
        system_id: str,
        template_id: str,
        brief: str,
        created_at: datetime,
        updated_at: datetime,
        status: str = "draft",
    ) -> DesignProject:
        self._conn.execute(
            """INSERT INTO design_projects
               (id, name, kind, system_id, template_id, brief,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, name, kind, system_id, template_id, brief, status,
             created_at.isoformat(), updated_at.isoformat()),
        )
        self._conn.commit()
        return DesignProject(
            id=id, name=name, kind=kind, system_id=system_id,
            template_id=template_id, brief=brief, status=status,
            created_at=created_at, updated_at=updated_at,
        )

    def get_project(self, project_id: str) -> DesignProject:
        cursor = self._conn.execute(
            """SELECT id, name, kind, system_id, template_id, brief,
                      status, created_at, updated_at
               FROM design_projects WHERE id = ?""",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise DesignProjectNotFoundError(project_id)
        return DesignProject(
            id=row[0], name=row[1], kind=row[2], system_id=row[3],
            template_id=row[4], brief=row[5], status=row[6],
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
        )

    def list_projects(
        self, kind: Optional[str] = None, limit: int = 50,
    ) -> list[DesignProject]:
        if kind:
            cursor = self._conn.execute(
                """SELECT id, name, kind, system_id, template_id, brief,
                          status, created_at, updated_at
                   FROM design_projects
                   WHERE kind = ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (kind, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT id, name, kind, system_id, template_id, brief,
                          status, created_at, updated_at
                   FROM design_projects
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            )
        return [
            DesignProject(
                id=r[0], name=r[1], kind=r[2], system_id=r[3],
                template_id=r[4], brief=r[5], status=r[6],
                created_at=datetime.fromisoformat(r[7]),
                updated_at=datetime.fromisoformat(r[8]),
            )
            for r in cursor.fetchall()
        ]

    def update_project_status(self, project_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """UPDATE design_projects
               SET status = ?, updated_at = ?
               WHERE id = ?""",
            (status, now, project_id),
        )
        self._conn.commit()

    def delete_project(self, project_id: str) -> None:
        self._conn.execute(
            "DELETE FROM design_projects WHERE id = ?", (project_id,)
        )
        self._conn.commit()

    def create_artifact(
        self,
        id: str,
        project_id: str,
        version: int,
        html_content: str,
        title: str,
        file_path: str,
        kind: str,
        export_formats: list[str],
        source_prompt: str,
        created_at: datetime,
    ) -> DesignArtifact:
        self._conn.execute(
            """INSERT INTO design_artifacts
               (id, project_id, version, file_path, kind, title,
                export_formats, source_prompt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, project_id, version, file_path, kind, title,
             json.dumps(export_formats), source_prompt,
             created_at.isoformat()),
        )
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html_content, encoding="utf-8")
        self._conn.commit()
        return DesignArtifact(
            id=id, project_id=project_id, version=version,
            html_content=html_content, css_injected="", title=title,
            file_path=file_path, kind=kind,
            export_formats=export_formats,
            source_prompt=source_prompt, created_at=created_at,
        )

    def _load_artifact_row(self, row: tuple) -> DesignArtifact:
        html_content = ""
        try:
            html_content = Path(row[3]).read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
        return DesignArtifact(
            id=row[0], project_id=row[1], version=row[2],
            html_content=html_content, css_injected="", title=row[5],
            file_path=row[3], kind=row[4],
            export_formats=json.loads(row[6]),
            source_prompt=row[7],
            created_at=datetime.fromisoformat(row[8]),
        )

    def get_artifact(self, artifact_id: str) -> DesignArtifact:
        cursor = self._conn.execute(
            """SELECT id, project_id, version, file_path, kind, title,
                      export_formats, source_prompt, created_at
               FROM design_artifacts WHERE id = ?""",
            (artifact_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise DesignProjectNotFoundError(f"Artifact {artifact_id}")
        return self._load_artifact_row(row)

    def list_artifacts(self, project_id: str) -> list[DesignArtifact]:
        cursor = self._conn.execute(
            """SELECT id, project_id, version, file_path, kind, title,
                      export_formats, source_prompt, created_at
               FROM design_artifacts
               WHERE project_id = ?
               ORDER BY version ASC""",
            (project_id,),
        )
        return [self._load_artifact_row(r) for r in cursor.fetchall()]

    def get_latest_artifact(
        self, project_id: str,
    ) -> Optional[DesignArtifact]:
        cursor = self._conn.execute(
            """SELECT id, project_id, version, file_path, kind, title,
                      export_formats, source_prompt, created_at
               FROM design_artifacts
               WHERE project_id = ?
               ORDER BY version DESC LIMIT 1""",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._load_artifact_row(row)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_repo.py -v
```
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/data/design_repo.py backend/tests/unit/test_design_repo.py
git commit -m "feat(design): add DesignRepo for project and artifact CRUD"
```

---

### Task 5: Artifact Parser

**Files:**
- Create: `backend/design/artifact_parser.py`
- Test: `backend/tests/unit/test_artifact_parser.py`

**Interfaces:**
- Consumes: Raw LLM output string
- Produces: `ParsedArtifact(identifier, type, title, html_content)` or raises `DesignGenerationError`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_artifact_parser.py
from __future__ import annotations
import pytest
from backend.design.artifact_parser import ArtifactParser, ParsedArtifact
from backend.design.errors import DesignGenerationError


class TestArtifactParser:
    def test_parse_simple_artifact(self):
        llm_output = '''Some preamble text.
<artifact identifier="my-page" type="text/html" title="My Page">
<!DOCTYPE html>
<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>
</artifact>
Some postamble.'''
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "my-page"
        assert result.type == "text/html"
        assert result.title == "My Page"
        assert "<!DOCTYPE html>" in result.html_content
        assert "<h1>Hello</h1>" in result.html_content

    def test_parse_artifact_with_attributes(self):
        llm_output = (
            '<artifact identifier="dashboard" type="text/html"'
            ' title="Dashboard View">\n<html></html>\n</artifact>'
        )
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "dashboard"
        assert result.title == "Dashboard View"

    def test_no_artifact_tag_raises(self):
        with pytest.raises(DesignGenerationError, match="No <artifact>"):
            ArtifactParser.parse(
                "Just plain text, no artifact tags here."
            )

    def test_unclosed_artifact_tag_raises(self):
        with pytest.raises(DesignGenerationError, match="Unclosed"):
            ArtifactParser.parse(
                '<artifact identifier="x" type="text/html" title="X">'
                "\n<html></html>"
            )

    def test_multiple_artifacts_returns_first(self):
        llm_output = '''
<artifact identifier="first" type="text/html" title="First">
<html>first</html>
</artifact>
<artifact identifier="second" type="text/html" title="Second">
<html>second</html>
</artifact>
'''
        result = ArtifactParser.parse(llm_output)
        assert result.identifier == "first"

    def test_parse_strips_leading_trailing_whitespace(self):
        llm_output = (
            '<artifact identifier="x" type="text/html" title="X">'
            "\n   <html>  </html>   \n</artifact>"
        )
        result = ArtifactParser.parse(llm_output)
        assert result.html_content.strip() == "<html>  </html>"

    def test_parse_realistic_html_content(self):
        llm_output = '''<artifact identifier="landing" type="text/html" title="SaaS Landing">
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SaaS Landing Page</title>
  <style>
    :root { --primary: #6366f1; }
    body { font-family: system-ui; margin: 0; }
    .hero { padding: 4rem 2rem; text-align: center; }
  </style>
</head>
<body>
  <section class="hero">
    <h1>Build faster with our platform</h1>
    <p>The all-in-one solution for modern teams.</p>
    <button>Get Started</button>
  </section>
</body>
</html>
</artifact>'''
        result = ArtifactParser.parse(llm_output)
        assert "<!DOCTYPE html>" in result.html_content
        assert "--primary: #6366f1" in result.html_content
        assert "Get Started" in result.html_content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_parser.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement ArtifactParser**

```python
# backend/design/artifact_parser.py
"""Parse <artifact> blocks from LLM output."""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.design.errors import DesignGenerationError


@dataclass(frozen=True)
class ParsedArtifact:
    """A parsed artifact block from LLM output."""

    identifier: str
    type: str
    title: str
    html_content: str


_ARTIFACT_RE = re.compile(
    r'<artifact\s+identifier="([^"]+)"\s+type="([^"]+)"'
    r'\s+title="([^"]+)">\s*(.*?)\s*</artifact>',
    re.DOTALL,
)


class ArtifactParser:
    """Extract <artifact> blocks from LLM output text."""

    @staticmethod
    def parse(text: str) -> ParsedArtifact:
        """Parse the first <artifact> block from text.

        Raises DesignGenerationError if no artifact block is found
        or if it's unclosed.
        """
        match = _ARTIFACT_RE.search(text)
        if match is None:
            if "<artifact" in text and "</artifact>" not in text:
                raise DesignGenerationError(
                    "Unclosed <artifact> tag in LLM output"
                )
            raise DesignGenerationError(
                "No <artifact> block found in LLM output"
            )

        return ParsedArtifact(
            identifier=match.group(1),
            type=match.group(2),
            title=match.group(3),
            html_content=match.group(4),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_artifact_parser.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/artifact_parser.py backend/tests/unit/test_artifact_parser.py
git commit -m "feat(design): add ArtifactParser for extracting HTML from LLM output"
```

---

### Task 6: Prompt Composer

**Files:**
- Create: `backend/design/prompt_composer.py`
- Test: `backend/tests/unit/test_prompt_composer.py`

**Interfaces:**
- Consumes: `DesignSystem`, `DesignTemplate`, brief string, optional iteration context
- Produces: Complete system prompt string

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_prompt_composer.py
from __future__ import annotations
import pytest
from backend.design.prompt_composer import PromptComposer
from backend.design.models import DesignSystem, DesignTemplate


@pytest.fixture()
def system():
    return DesignSystem(
        id="minimal",
        name="Minimal",
        category="general",
        description="A minimal design system",
        design_md="# Minimal Design System\n\nUse black and white only.",
        tokens_css=":root { --bg: #fff; --fg: #000; }",
        design_tokens={},
        tags=["minimal"],
    )


@pytest.fixture()
def template():
    return DesignTemplate(
        id="landing-page",
        name="Landing Page",
        kind="prototype",
        description="Product landing page",
        skill_md="# Landing Page\nCreate a hero section with CTA button.",
        example_html=None,
        assets={},
        design_system_required=True,
    )


class TestPromptComposer:
    def test_compose_includes_all_sections(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Create a SaaS landing page for a developer tool",
        )
        assert "Minimal Design System" in prompt
        assert "Landing Page" in prompt
        assert "SaaS landing page" in prompt
        assert "<artifact" in prompt

    def test_compose_with_iteration_context(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Original brief",
            iteration_context={
                "current_html": "<html><body>Old version</body></html>",
                "user_feedback": "Change the button to blue",
            },
        )
        assert "Old version" in prompt
        assert "Change the button to blue" in prompt

    def test_compose_without_iteration_has_no_iteration_section(
        self, system, template,
    ):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="Create a page",
            iteration_context=None,
        )
        assert "当前版本" not in prompt

    def test_compose_identifier_from_template(self, system, template):
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief="test",
        )
        assert "landing-page" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_prompt_composer.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement PromptComposer**

```python
# backend/design/prompt_composer.py
"""Compose system prompts for design generation."""
from __future__ import annotations

from typing import Optional

from backend.design.models import DesignSystem, DesignTemplate


_BASE_INSTRUCTIONS = """\
你是一个专业的 HTML/CSS 设计专家。根据用户的设计需求和品牌规范，\
生成高质量的 HTML 页面。

## 输出格式要求
将生成的完整 HTML 包裹在 <artifact> 标签中：
<artifact identifier="{identifier}" type="text/html" title="{title}">
<!DOCTYPE html>
<html>
...完整 HTML 文档...
</html>
</artifact>

## 通用设计原则
- 使用语义化 HTML5 标签
- CSS 使用 Flexbox/Grid 布局
- 响应式设计（mobile-first）
- 无障碍基础（aria 属性、语义化标签）
- 所有颜色/间距/字体使用 design system 的 CSS 变量
"""

_ITERATION_ADDENDUM = """\

## 当前版本 HTML
```html
{current_html}
```

## 用户修改要求
{user_feedback}

请基于当前 HTML 进行修改，保持整体结构不变，仅修改用户要求的部分。
输出修改后的完整 HTML（同样使用 <artifact> 标签包裹）。
"""


class PromptComposer:
    """Assemble system prompts from design system + template + brief."""

    @staticmethod
    def compose(
        design_system: DesignSystem,
        template: DesignTemplate,
        brief: str,
        iteration_context: Optional[dict] = None,
    ) -> str:
        """Compose a complete system prompt for design generation."""
        identifier = template.id
        title = template.name

        parts = [
            _BASE_INSTRUCTIONS.format(
                identifier=identifier, title=title,
            ),
            "",
            "## 品牌设计规范",
            design_system.design_md,
            "",
            "## CSS 变量定义",
            "```css",
            design_system.tokens_css,
            "```",
            "",
            "## 模板生成指令",
            template.skill_md,
            "",
            "## 用户需求",
            brief,
        ]

        if iteration_context:
            parts.append(
                _ITERATION_ADDENDUM.format(
                    current_html=iteration_context.get("current_html", ""),
                    user_feedback=iteration_context.get("user_feedback", ""),
                )
            )

        return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_prompt_composer.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/prompt_composer.py backend/tests/unit/test_prompt_composer.py
git commit -m "feat(design): add PromptComposer for assembling generation prompts"
```

---

### Task 7: Standalone Bundler

**Files:**
- Create: `backend/design/standalone_bundler.py`
- Test: `backend/tests/unit/test_standalone_bundler.py`

**Interfaces:**
- Consumes: HTML string, CSS string, optional assets dict
- Produces: Self-contained HTML string with inlined CSS

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_standalone_bundler.py
from __future__ import annotations
import pytest
from backend.design.standalone_bundler import StandaloneBundler


class TestStandaloneBundler:
    def test_bundle_injects_css_into_head(self):
        html = (
            "<!DOCTYPE html><html><head><title>Test</title>"
            "</head><body>Hello</body></html>"
        )
        css = ":root { --bg: #fff; } body { background: var(--bg); }"
        result = StandaloneBundler.bundle(html, css)
        assert ":root { --bg: #fff; }" in result
        assert "<style>" in result
        assert "</style>" in result

    def test_bundle_preserves_existing_content(self):
        html = (
            "<!DOCTYPE html><html><head><title>My Page</title>"
            "</head><body><h1>Hello</h1></body></html>"
        )
        result = StandaloneBundler.bundle(html, "")
        assert "<title>My Page</title>" in result
        assert "<h1>Hello</h1>" in result

    def test_bundle_handles_html_without_head(self):
        html = "<html><body>Simple</body></html>"
        css = "body { color: red; }"
        result = StandaloneBundler.bundle(html, css)
        assert "body { color: red; }" in result

    def test_bundle_with_empty_css(self):
        html = "<html><head></head><body>Test</body></html>"
        result = StandaloneBundler.bundle(html, "")
        assert "Test" in result

    def test_bundle_with_template_assets(self):
        html = "<html><head></head><body>Content</body></html>"
        css = ":root { --primary: blue; }"
        assets = {
            "animations.css": (
                "@keyframes fade { from { opacity: 0; } "
                "to { opacity: 1; } }"
            ),
        }
        result = StandaloneBundler.bundle(html, css, assets)
        assert "@keyframes fade" in result
        assert ":root { --primary: blue; }" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_standalone_bundler.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement StandaloneBundler**

```python
# backend/design/standalone_bundler.py
"""Bundle HTML + CSS + assets into a self-contained HTML file."""
from __future__ import annotations

import re
from typing import Optional


class StandaloneBundler:
    """Inline CSS and assets into a self-contained HTML document."""

    @staticmethod
    def bundle(
        html: str,
        css: str,
        assets: Optional[dict[str, str]] = None,
    ) -> str:
        """Bundle HTML with design system CSS and optional template assets.

        Returns self-contained HTML string with all CSS inlined.
        """
        all_css_parts: list[str] = []
        if css:
            all_css_parts.append(css)
        if assets:
            for filename, content in assets.items():
                if filename.endswith(".css"):
                    all_css_parts.append(content)

        combined_css = "\n\n".join(all_css_parts)

        if not combined_css:
            return html

        style_block = f"<style>\n{combined_css}\n</style>"

        # Inject before </head>
        if "</head>" in html:
            return html.replace("</head>", f"{style_block}\n</head>")

        # Inject after <head...>
        head_match = re.search(r"<head[^>]*>", html)
        if head_match:
            insert_pos = head_match.end()
            return html[:insert_pos] + f"\n{style_block}" + html[insert_pos:]

        # Fallback: inject at the beginning
        return f"{style_block}\n{html}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_standalone_bundler.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/standalone_bundler.py backend/tests/unit/test_standalone_bundler.py
git commit -m "feat(design): add StandaloneBundler for self-contained HTML output"
```

---

### Task 8: Design System Registry

**Files:**
- Create: `backend/design/systems.py`
- Create: `backend/design/content/NOTICE.md`
- Create: `backend/design/content/systems/minimal/DESIGN.md`
- Create: `backend/design/content/systems/minimal/tokens.css`
- Create: `backend/design/content/systems/minimal/manifest.json`
- Create: `backend/design/content/systems/corporate/DESIGN.md`
- Create: `backend/design/content/systems/corporate/tokens.css`
- Create: `backend/design/content/systems/corporate/manifest.json`
- Test: `backend/tests/unit/test_design_systems.py`

**Interfaces:**
- Consumes: Content directory path
- Produces: `DesignSystemRegistry` with `list_systems()`, `get_system(id)`, `search_systems(query)`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_systems.py
from __future__ import annotations
import json
import pytest
from pathlib import Path

from backend.design.systems import DesignSystemRegistry
from backend.design.errors import DesignSystemNotFoundError


class TestDesignSystemRegistry:
    @pytest.fixture()
    def content_dir(self, tmp_path):
        """Create a minimal content directory with one design system."""
        systems_dir = tmp_path / "systems" / "test-system"
        systems_dir.mkdir(parents=True)

        (systems_dir / "DESIGN.md").write_text(
            "# Test System\n\nA test design system."
        )
        (systems_dir / "tokens.css").write_text(
            ":root { --bg: #fff; --fg: #000; }"
        )
        (systems_dir / "manifest.json").write_text(json.dumps({
            "id": "test-system",
            "name": "Test System",
            "category": "general",
            "description": "A test design system for unit tests",
            "tags": ["test", "minimal"],
        }))

        return tmp_path

    def test_list_systems(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        systems = registry.list_systems()
        assert len(systems) == 1
        assert systems[0].id == "test-system"
        assert systems[0].name == "Test System"

    def test_get_system(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        system = registry.get_system("test-system")
        assert system.id == "test-system"
        assert "Test System" in system.design_md
        assert "--bg: #fff" in system.tokens_css

    def test_get_system_not_found(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        with pytest.raises(DesignSystemNotFoundError):
            registry.get_system("nonexistent")

    def test_search_systems(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        results = registry.search_systems("test")
        assert len(results) == 1

    def test_search_systems_no_match(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        results = registry.search_systems("quantum")
        assert len(results) == 0

    def test_get_system_includes_tags(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        system = registry.get_system("test-system")
        assert "test" in system.tags
        assert "minimal" in system.tags
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_systems.py -v
```
Expected: FAIL

- [ ] **Step 3: Create content files**

Create the NOTICE.md (Apache-2.0 attribution from OpenDesign) and two design systems under `backend/design/content/systems/`:

Each system needs:
- `DESIGN.md` — Brand guidelines (50-100 lines): Visual Theme, Color Palette, Typography, Component Stylings, Layout, Do's/Don'ts
- `tokens.css` — CSS custom properties
- `manifest.json` — `{"id": "...", "name": "...", "category": "...", "description": "...", "tags": [...]}`

For `minimal`: black/white, system-ui font, 4px spacing grid, no shadows.
For `corporate`: blue/gray palette, Inter font, 8px spacing grid, subtle shadows.

- [ ] **Step 4: Implement DesignSystemRegistry**

```python
# backend/design/systems.py
"""Design system registry — loads and manages DESIGN.md packages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from backend.design.errors import DesignSystemNotFoundError
from backend.design.models import DesignSystem


class DesignSystemRegistry:
    """Load and query design systems from a content directory."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._systems_dir = content_dir / "systems"
        self._cache: dict[str, DesignSystem] = {}

    def list_systems(self) -> list[DesignSystem]:
        """List all available design systems."""
        if not self._systems_dir.exists():
            return []
        systems: list[DesignSystem] = []
        for system_dir in sorted(self._systems_dir.iterdir()):
            if system_dir.is_dir() and (system_dir / "manifest.json").exists():
                systems.append(self._load_system(system_dir))
        return systems

    def get_system(self, system_id: str) -> DesignSystem:
        """Get a design system by ID."""
        if system_id in self._cache:
            return self._cache[system_id]

        system_dir = self._systems_dir / system_id
        if not system_dir.exists() or not (system_dir / "manifest.json").exists():
            raise DesignSystemNotFoundError(
                f"Design system '{system_id}' not found"
            )

        system = self._load_system(system_dir)
        self._cache[system_id] = system
        return system

    def search_systems(self, query: str) -> list[DesignSystem]:
        """Search design systems by name, description, or tags."""
        query_lower = query.lower()
        results: list[DesignSystem] = []
        for system in self.list_systems():
            if (
                query_lower in system.name.lower()
                or query_lower in system.description.lower()
                or query_lower in system.category.lower()
                or any(query_lower in tag.lower() for tag in system.tags)
            ):
                results.append(system)
        return results

    def _load_system(self, system_dir: Path) -> DesignSystem:
        """Load a design system from a directory."""
        manifest_path = system_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        design_md_path = system_dir / "DESIGN.md"
        design_md = (
            design_md_path.read_text(encoding="utf-8")
            if design_md_path.exists() else ""
        )

        tokens_css_path = system_dir / "tokens.css"
        tokens_css = (
            tokens_css_path.read_text(encoding="utf-8")
            if tokens_css_path.exists() else ""
        )

        tokens_json_path = system_dir / "design-tokens.json"
        design_tokens: dict = {}
        if tokens_json_path.exists():
            design_tokens = json.loads(
                tokens_json_path.read_text(encoding="utf-8")
            )

        return DesignSystem(
            id=manifest["id"],
            name=manifest["name"],
            category=manifest.get("category", "general"),
            description=manifest.get("description", ""),
            design_md=design_md,
            tokens_css=tokens_css,
            design_tokens=design_tokens,
            tags=manifest.get("tags", []),
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_systems.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/design/systems.py backend/design/content/ backend/tests/unit/test_design_systems.py
git commit -m "feat(design): add DesignSystemRegistry with minimal and corporate systems"
```

---

### Task 9: Template Registry

**Files:**
- Create: `backend/design/templates.py`
- Create: `backend/design/content/templates/prototype/landing-page/SKILL.md`
- Create: `backend/design/content/templates/prototype/landing-page/example.html`
- Test: `backend/tests/unit/test_design_templates.py`

**Interfaces:**
- Consumes: Content directory path
- Produces: `DesignTemplateRegistry` with `list_templates()`, `get_template(id)`, `list_templates_by_kind(kind)`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_templates.py
from __future__ import annotations
import pytest
from pathlib import Path

from backend.design.templates import DesignTemplateRegistry
from backend.design.errors import DesignTemplateNotFoundError


class TestDesignTemplateRegistry:
    @pytest.fixture()
    def content_dir(self, tmp_path):
        """Create a minimal content directory with one template."""
        template_dir = tmp_path / "templates" / "prototype" / "test-page"
        template_dir.mkdir(parents=True)

        (template_dir / "SKILL.md").write_text(
            "---\nname: test-page\nkind: prototype\n"
            "description: A test page\n"
            "design_system_required: true\n---\n"
            "# Test Page\nCreate a simple test page."
        )
        (template_dir / "example.html").write_text(
            "<html><body>Example</body></html>"
        )

        return tmp_path

    def test_list_templates(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        templates = registry.list_templates()
        assert len(templates) == 1
        assert templates[0].id == "test-page"
        assert templates[0].kind == "prototype"

    def test_get_template(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("test-page")
        assert template.id == "test-page"
        assert "Test Page" in template.skill_md

    def test_get_template_not_found(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        with pytest.raises(DesignTemplateNotFoundError):
            registry.get_template("nonexistent")

    def test_list_templates_by_kind(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        prototypes = registry.list_templates_by_kind("prototype")
        assert len(prototypes) == 1
        decks = registry.list_templates_by_kind("deck")
        assert len(decks) == 0

    def test_template_has_example_html(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("test-page")
        assert template.example_html is not None
        assert "Example" in template.example_html
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_templates.py -v
```
Expected: FAIL

- [ ] **Step 3: Create landing page template content**

Create `backend/design/content/templates/prototype/landing-page/SKILL.md` with:
- YAML frontmatter: `name: landing-page`, `kind: prototype`, `description`, `design_system_required: true`
- Markdown body: generation instructions for a landing page (hero section, features, CTA, footer)

Create `backend/design/content/templates/prototype/landing-page/example.html` with a reference landing page.

- [ ] **Step 4: Implement DesignTemplateRegistry**

```python
# backend/design/templates.py
"""Template registry — loads SKILL.md templates for design generation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from backend.design.errors import DesignTemplateNotFoundError
from backend.design.models import DesignTemplate


def _parse_skill_md(content: str) -> dict:
    """Parse YAML frontmatter from SKILL.md."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {
            "skill_md": content, "name": "", "kind": "prototype",
            "description": "", "design_system_required": False,
        }

    frontmatter_str = match.group(1)
    body = match.group(2)

    fm: dict = {}
    for line in frontmatter_str.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.lower() == "true":
                fm[key] = True
            elif value.lower() == "false":
                fm[key] = False
            else:
                fm[key] = value

    fm["skill_md"] = f"---\n{frontmatter_str}\n---\n{body}"
    return fm


class DesignTemplateRegistry:
    """Load and query design templates from a content directory."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._templates_dir = content_dir / "templates"
        self._cache: dict[str, DesignTemplate] = {}

    def list_templates(self) -> list[DesignTemplate]:
        """List all available templates."""
        if not self._templates_dir.exists():
            return []
        templates: list[DesignTemplate] = []
        for kind_dir in sorted(self._templates_dir.iterdir()):
            if not kind_dir.is_dir():
                continue
            for template_dir in sorted(kind_dir.iterdir()):
                if (
                    template_dir.is_dir()
                    and (template_dir / "SKILL.md").exists()
                ):
                    templates.append(
                        self._load_template(template_dir, kind_dir.name)
                    )
        return templates

    def list_templates_by_kind(self, kind: str) -> list[DesignTemplate]:
        """List templates filtered by kind (prototype or deck)."""
        return [t for t in self.list_templates() if t.kind == kind]

    def get_template(self, template_id: str) -> DesignTemplate:
        """Get a template by ID."""
        if template_id in self._cache:
            return self._cache[template_id]

        for kind_dir in self._templates_dir.iterdir():
            if not kind_dir.is_dir():
                continue
            template_dir = kind_dir / template_id
            if (
                template_dir.is_dir()
                and (template_dir / "SKILL.md").exists()
            ):
                template = self._load_template(template_dir, kind_dir.name)
                self._cache[template_id] = template
                return template

        raise DesignTemplateNotFoundError(
            f"Template '{template_id}' not found"
        )

    def _load_template(
        self, template_dir: Path, kind: str,
    ) -> DesignTemplate:
        """Load a template from a directory."""
        skill_content = (template_dir / "SKILL.md").read_text(
            encoding="utf-8"
        )
        parsed = _parse_skill_md(skill_content)

        example_path = template_dir / "example.html"
        example_html = (
            example_path.read_text(encoding="utf-8")
            if example_path.exists() else None
        )

        assets: dict[str, str] = {}
        assets_dir = template_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if (
                    asset_file.is_file()
                    and asset_file.suffix in (".css", ".js")
                ):
                    rel_path = str(asset_file.relative_to(template_dir))
                    assets[rel_path] = asset_file.read_text(
                        encoding="utf-8"
                    )

        template_id = parsed.get("name", template_dir.name)

        return DesignTemplate(
            id=template_id,
            name=(
                parsed.get("name", template_dir.name)
                .replace("-", " ")
                .title()
            ),
            kind=parsed.get("kind", kind),
            description=parsed.get("description", ""),
            skill_md=parsed["skill_md"],
            example_html=example_html,
            assets=assets,
            design_system_required=parsed.get(
                "design_system_required", False,
            ),
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_templates.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/design/templates.py backend/design/content/templates/ backend/tests/unit/test_design_templates.py
git commit -m "feat(design): add DesignTemplateRegistry with landing-page template"
```

---

### Task 10: Generator

**Files:**
- Create: `backend/design/generator.py`
- Test: `backend/tests/unit/test_design_generator.py`

**Interfaces:**
- Consumes: `PromptComposer`, `ArtifactParser`, `StandaloneBundler`, `LLMClient`
- Produces: `DesignGenerator` with `generate()` method returning `GenerationResult`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_generator.py
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.design.generator import DesignGenerator
from backend.design.models import DesignSystem, DesignTemplate
from backend.design.errors import DesignGenerationError


@pytest.fixture()
def system():
    return DesignSystem(
        id="minimal", name="Minimal", category="general",
        description="Minimal", design_md="# Minimal",
        tokens_css=":root { --bg: #fff; }",
        design_tokens={}, tags=[],
    )


@pytest.fixture()
def template():
    return DesignTemplate(
        id="landing-page", name="Landing Page", kind="prototype",
        description="Landing page", skill_md="# Landing Page",
        example_html=None, assets={}, design_system_required=True,
    )


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


class TestDesignGenerator:
    @pytest.mark.asyncio
    async def test_generate_success(self, system, template, mock_llm):
        mock_llm.chat.return_value = MagicMock(
            content=(
                '<artifact identifier="landing-page" type="text/html"'
                ' title="Landing Page">\n'
                '<!DOCTYPE html><html><body><h1>Test</h1></body></html>'
                '\n</artifact>'
            )
        )

        generator = DesignGenerator(llm_client=mock_llm)
        result = await generator.generate(
            system, template, "Create a landing page",
        )

        assert "Test" in result.bundled_html
        assert ":root { --bg: #fff; }" in result.bundled_html
        assert result.parsed.identifier == "landing-page"

    @pytest.mark.asyncio
    async def test_generate_no_artifact_raises(
        self, system, template, mock_llm,
    ):
        mock_llm.chat.return_value = MagicMock(
            content="Just text, no artifact."
        )

        generator = DesignGenerator(llm_client=mock_llm)
        with pytest.raises(DesignGenerationError):
            await generator.generate(system, template, "test")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_generator.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement DesignGenerator**

```python
# backend/design/generator.py
"""Core design generation — compose prompt, call LLM, parse, bundle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.design.artifact_parser import ArtifactParser, ParsedArtifact
from backend.design.errors import DesignGenerationError
from backend.design.models import DesignSystem, DesignTemplate
from backend.design.prompt_composer import PromptComposer
from backend.design.standalone_bundler import StandaloneBundler


@dataclass
class GenerationResult:
    """Result of a design generation."""

    parsed: ParsedArtifact
    bundled_html: str
    source_prompt: str


class DesignGenerator:
    """Generate HTML designs by composing prompts and calling LLM."""

    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    async def generate(
        self,
        system: DesignSystem,
        template: DesignTemplate,
        brief: str,
        iteration_context: Optional[dict] = None,
    ) -> GenerationResult:
        """Generate a design artifact.

        Raises DesignGenerationError if LLM output can't be parsed.
        """
        prompt = PromptComposer.compose(
            design_system=system,
            template=template,
            brief=brief,
            iteration_context=iteration_context,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self._llm.chat(messages)
        raw_output = response.content

        if not raw_output:
            raise DesignGenerationError("LLM returned empty response")

        parsed = ArtifactParser.parse(raw_output)

        bundled = StandaloneBundler.bundle(
            html=parsed.html_content,
            css=system.tokens_css,
            assets=template.assets,
        )

        return GenerationResult(
            parsed=parsed,
            bundled_html=bundled,
            source_prompt=prompt,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_generator.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/generator.py backend/tests/unit/test_design_generator.py
git commit -m "feat(design): add DesignGenerator for LLM-driven HTML generation"
```

---

### Task 11: Design Studio Orchestrator

**Files:**
- Create: `backend/design/design_studio.py`
- Test: `backend/tests/unit/test_design_studio.py`

**Interfaces:**
- Consumes: `DesignGenerator`, `DesignSystemRegistry`, `DesignTemplateRegistry`, `DesignRepo`
- Produces: `DesignStudio` with `create_project()`, `generate()`, `iterate()`, `list_projects()`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_design_studio.py
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
import json
import sqlite3
import pytest

from backend.design.design_studio import DesignStudio
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry
from backend.data.design_repo import DesignRepo


class TestDesignStudio:
    @pytest.fixture()
    def studio(self, tmp_path):
        db = sqlite3.connect(str(tmp_path / "test.db"))
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("""CREATE TABLE design_projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            system_id TEXT NOT NULL, template_id TEXT NOT NULL,
            brief TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE design_artifacts (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            version INTEGER NOT NULL, file_path TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL,
            export_formats TEXT NOT NULL DEFAULT '[]',
            source_prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, version))""")
        db.commit()
        repo = DesignRepo(db)

        content_dir = tmp_path / "content"

        systems_dir = content_dir / "systems" / "test"
        systems_dir.mkdir(parents=True)
        (systems_dir / "DESIGN.md").write_text("# Test")
        (systems_dir / "tokens.css").write_text(":root { --bg: #fff; }")
        (systems_dir / "manifest.json").write_text(json.dumps({
            "id": "test", "name": "Test", "category": "general",
            "description": "test", "tags": [],
        }))

        template_dir = content_dir / "templates" / "prototype" / "test-page"
        template_dir.mkdir(parents=True)
        (template_dir / "SKILL.md").write_text(
            "---\nname: test-page\nkind: prototype\n"
            "description: test\ndesign_system_required: true\n---\n"
            "# Test"
        )

        systems_reg = DesignSystemRegistry(content_dir)
        templates_reg = DesignTemplateRegistry(content_dir)

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()
        mock_llm.chat.return_value = MagicMock(
            content=(
                '<artifact identifier="test-page" type="text/html"'
                ' title="Test">\n'
                '<html><body>Generated</body></html>'
                '\n</artifact>'
            )
        )

        from backend.design.generator import DesignGenerator
        generator = DesignGenerator(llm_client=mock_llm)

        return DesignStudio(
            repo=repo,
            generator=generator,
            systems=systems_reg,
            templates=templates_reg,
            workspace_dir=tmp_path / "workspace",
        )

    def test_create_project(self, studio):
        project = studio.create_project(
            name="Test Project",
            kind="prototype",
            system_id="test",
            template_id="test-page",
            brief="Create a test page",
        )
        assert project.name == "Test Project"
        assert project.status == "draft"

    def test_list_projects(self, studio):
        studio.create_project(
            "P1", "prototype", "test", "test-page", "brief1",
        )
        studio.create_project(
            "P2", "prototype", "test", "test-page", "brief2",
        )
        projects = studio.list_projects()
        assert len(projects) == 2

    @pytest.mark.asyncio
    async def test_generate_creates_artifact(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        artifact = await studio.generate(
            project.id, "Generate a test page",
        )
        assert artifact.version == 1
        assert "Generated" in artifact.html_content

    @pytest.mark.asyncio
    async def test_iterate_increments_version(self, studio):
        project = studio.create_project(
            "Test", "prototype", "test", "test-page", "Create a page",
        )
        await studio.generate(project.id, "v1 brief")
        artifact = await studio.iterate(project.id, "Make it better")
        assert artifact.version == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_studio.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement DesignStudio**

```python
# backend/design/design_studio.py
"""Top-level design studio orchestrator."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.data.design_repo import DesignRepo
from backend.design.errors import DesignProjectNotFoundError
from backend.design.generator import DesignGenerator
from backend.design.models import DesignArtifact, DesignProject
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry


class DesignStudio:
    """Orchestrate design project lifecycle."""

    def __init__(
        self,
        repo: DesignRepo,
        generator: DesignGenerator,
        systems: DesignSystemRegistry,
        templates: DesignTemplateRegistry,
        workspace_dir: Path,
    ) -> None:
        self._repo = repo
        self._generator = generator
        self._systems = systems
        self._templates = templates
        self._workspace = workspace_dir

    def create_project(
        self,
        name: str,
        kind: str,
        system_id: str,
        template_id: str,
        brief: str,
    ) -> DesignProject:
        """Create a new design project."""
        self._systems.get_system(system_id)
        self._templates.get_template(template_id)

        now = datetime.now(timezone.utc)
        return self._repo.create_project(
            id=str(uuid.uuid4()),
            name=name,
            kind=kind,
            system_id=system_id,
            template_id=template_id,
            brief=brief,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> DesignProject:
        return self._repo.get_project(project_id)

    def list_projects(
        self, kind: Optional[str] = None,
    ) -> list[DesignProject]:
        return self._repo.list_projects(kind=kind)

    def delete_project(self, project_id: str) -> None:
        self._repo.delete_project(project_id)

    async def generate(
        self, project_id: str, brief: Optional[str] = None,
    ) -> DesignArtifact:
        """Generate the first artifact for a project."""
        project = self._repo.get_project(project_id)
        system = self._systems.get_system(project.system_id)
        template = self._templates.get_template(project.template_id)

        self._repo.update_project_status(project_id, "generating")

        try:
            use_brief = brief or project.brief
            result = await self._generator.generate(
                system, template, use_brief,
            )

            artifact_id = str(uuid.uuid4())
            file_path = str(
                self._workspace / "design" / project_id / "v1.html"
            )
            now = datetime.now(timezone.utc)

            artifact = self._repo.create_artifact(
                id=artifact_id,
                project_id=project_id,
                version=1,
                html_content=result.bundled_html,
                title=result.parsed.title,
                file_path=file_path,
                kind="html",
                export_formats=["html"],
                source_prompt=result.source_prompt,
                created_at=now,
            )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise

    async def iterate(
        self, project_id: str, feedback: str,
    ) -> DesignArtifact:
        """Iterate on the latest artifact with user feedback."""
        project = self._repo.get_project(project_id)
        latest = self._repo.get_latest_artifact(project_id)
        if latest is None:
            raise DesignProjectNotFoundError(
                f"No artifacts for project {project_id}"
            )

        system = self._systems.get_system(project.system_id)
        template = self._templates.get_template(project.template_id)

        self._repo.update_project_status(project_id, "generating")

        try:
            result = await self._generator.generate(
                system, template, project.brief,
                iteration_context={
                    "current_html": latest.html_content,
                    "user_feedback": feedback,
                },
            )

            new_version = latest.version + 1
            artifact_id = str(uuid.uuid4())
            file_path = str(
                self._workspace / "design" / project_id
                / f"v{new_version}.html"
            )
            now = datetime.now(timezone.utc)

            artifact = self._repo.create_artifact(
                id=artifact_id,
                project_id=project_id,
                version=new_version,
                html_content=result.bundled_html,
                title=result.parsed.title,
                file_path=file_path,
                kind="html",
                export_formats=["html"],
                source_prompt=result.source_prompt,
                created_at=now,
            )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_studio.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/design/design_studio.py backend/tests/unit/test_design_studio.py
git commit -m "feat(design): add DesignStudio orchestrator for project lifecycle"
```

---

### Task 12: Wire Backend into Application

**Files:**
- Modify: `backend/design/__init__.py` (add lazy exports)
- Modify: `backend/main.py` (add DesignStudio initialization)

- [ ] **Step 1: Update `backend/design/__init__.py`**

```python
"""Design studio module — HTML/CSS prototype and presentation generation."""

_PHASE_2_EXPORTS = {
    "DesignStudio": (".design_studio", "DesignStudio"),
    "DesignGenerator": (".generator", "DesignGenerator"),
    "DesignSystemRegistry": (".systems", "DesignSystemRegistry"),
    "DesignTemplateRegistry": (".templates", "DesignTemplateRegistry"),
}


def __getattr__(name: str):
    if name in _PHASE_2_EXPORTS:
        import importlib
        module_name, attr_name = _PHASE_2_EXPORTS[name]
        module = importlib.import_module(module_name, __package__)
        return getattr(module, attr_name)
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
```

- [ ] **Step 2: Add DesignStudio initialization to `backend/main.py`**

Add near the top of `main.py` (after imports):
```python
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry
from backend.design.generator import DesignGenerator
from backend.design.design_studio import DesignStudio
from backend.data.design_repo import DesignRepo
```

Add inside the app startup (after database init):
```python
_content_dir = Path(__file__).parent / "design" / "content"
_systems_registry = DesignSystemRegistry(_content_dir)
_templates_registry = DesignTemplateRegistry(_content_dir)
_design_repo = DesignRepo(conn)  # reuse existing database connection
_generator = DesignGenerator(llm_client=llm_client)
_workspace_dir = Path(workspace_root)
design_studio = DesignStudio(
    repo=_design_repo,
    generator=_generator,
    systems=_systems_registry,
    templates=_templates_registry,
    workspace_dir=_workspace_dir,
)
```

- [ ] **Step 3: Verify all tests still pass**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_design_*.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/design/__init__.py backend/main.py
git commit -m "feat(design): wire DesignStudio into application startup"
```

---

## Milestone 2: Tools + API

### Task 13: Five Design Tools

**Files:**
- Create: `backend/tools/design_generate_tool.py`
- Create: `backend/tools/design_iterate_tool.py`
- Create: `backend/tools/design_export_tool.py`
- Create: `backend/tools/design_list_systems_tool.py`
- Create: `backend/tools/design_list_templates_tool.py`
- Modify: `backend/tools/__init__.py` (register 5 new tools)
- Test: `backend/tests/unit/test_design_tools.py`

Each tool follows the `BaseTool` pattern:
```python
class DesignGenerateTool(BaseTool):
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="design_generate",
            description="Generate an HTML design artifact",
            parameters={...},
        )

    async def execute(self, args: dict, context: Any = None) -> ToolResult:
        ...
```

Risk levels: `design_list_systems` and `design_list_templates` are READ. `design_generate`, `design_iterate`, `design_export` are WRITE_LOCAL.

- [ ] **Step 1: Implement all 5 tools**
- [ ] **Step 2: Register in `__init__.py`**
- [ ] **Step 3: Write tests verifying schema + basic execute**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 14: Design API Routes

**Files:**
- Create: `backend/api/v1/design_routes.py`
- Modify: `backend/main.py` (mount new router)
- Test: `backend/tests/unit/test_design_routes.py`

Follow existing `office_routes.py` pattern:
- `APIRouter(prefix="/design", tags=["design"])`
- Error mapping: `DesignError` subclasses → HTTP status codes
- SSE streaming for generate/iterate endpoints

Mount in `main.py`:
```python
from backend.api.v1.design_routes import router as design_router
app.include_router(design_router, prefix="/api/v1")
```

- [ ] **Step 1: Implement routes**
- [ ] **Step 2: Mount in main.py**
- [ ] **Step 3: Write integration tests**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 15: Design Skills (SKILL.md)

**Files:**
- Create: `backend/skills/skill_md/shipped/design-prototype/SKILL.md`
- Create: `backend/skills/skill_md/shipped/design-deck/SKILL.md`

- [ ] **Step 1: Create design-prototype SKILL.md**
- [ ] **Step 2: Create design-deck SKILL.md**
- [ ] **Step 3: Verify skills are discovered**
- [ ] **Step 4: Commit**

---

## Milestone 3: Frontend Workbench

### Task 16: Design API Client + Types

**Files:**
- Create: `src/shared/api/designApi.ts`
- Create: `src/shared/api/designApiTypes.ts`

Follow existing `officeApi.ts` pattern.

- [ ] **Step 1: Create types**
- [ ] **Step 2: Create API client**
- [ ] **Step 3: Commit**

---

### Task 17-20: Frontend Components

- Task 17: DesignStudio layout + page wrapper
- Task 18: BriefComposer + DesignSystemPicker + TemplatePicker
- Task 19: ArtifactPreview (sandboxed iframe) + useDesignGeneration (SSE)
- Task 20: IterationChat + ArtifactHistory + ExportPanel + DesignProjectsList

- [ ] **Step 1-5 per task: implement, wire, commit**

---

## Milestone 4: Presentations

### Task 21: HTML-PPT Template

Port core of OpenDesign's html-ppt template: base CSS, 6 themes, keyboard navigation runtime.

- [ ] **Step 1-6: Create SKILL.md + base.css + themes + runtime.js + example**

---

## Milestone 5: Export + Polish

### Task 22: Export Service

**Files:**
- Create: `backend/design/export.py`
- Test: `backend/tests/unit/test_design_export.py`

- [ ] **Step 1-5: Implement HTML/PDF/ZIP export + tests**

### Task 23: Content Expansion

Add 3-5 more design systems and 2-3 more templates.

- [ ] **Step 1-6: Create additional systems and templates**

---

## Execution Order Summary

```
M1 (Week 1):  Tasks 1-12  — Foundation + Core Generator (all backend)
M2 (Week 2):  Tasks 13-15 — Tools + API + Skills
M3 (Week 3):  Tasks 16-20 — Frontend Workbench
M4 (Week 4):  Task 21     — Presentations (html-ppt template)
M5 (Week 5):  Tasks 22-23 — Export + Content Expansion
```
