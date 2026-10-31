# 项目规程（Playbook）实施计划（P0 / P1）

> **For agentic workers:** REQUIRED SUB-SKILL: 按任务逐条执行，步骤使用 `- [ ]` 跟踪。每个任务先写失败测试，再实现，再跑测试，最后提交。

**Goal:** 为 Sage 项目新增"项目规程"子系统：按阶段定义目录/文档要求，离线核验完整性，识别阶段（需用户确认），并把规程导出/导入分享。

**Architecture:** 后端新增版本化 JSON 规程规格 + 项目级快照表 + 确定性审计器 + 动作执行器 + 导入导出；前端在项目概览 Tab 展示阶段条/清单，在设置区提供绑定、导出、导入；所有写操作先预览后执行，复用现有约束/里程碑/检查点能力。

**Tech Stack:** Python 3.10 + FastAPI + SQLite（无新依赖）、React 19 + TypeScript + Zustand、Electron IPC 桥、Vitest / Pytest。

**Spec:** `docs/plans/2026-10-31_project-playbook.md`

## Global Constraints

- 后端运行/测试使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。
- 不新增第三方依赖；glob 使用 `glob` / `fnmatch` 标准库。
- 路径必须 `resolve()` 后校验在项目根内；拒绝 `..` 与绝对路径导入。
- 所有 LLM 相关能力必须可确定性降级；本计划 P0/P1 不依赖 LLM。
- 不自动移动/重命名用户文件。
- 应用动作前创建项目检查点（复用 `create_project_checkpoint`）。
- 前端文案中文为主，导出/导入对话框明确"不包含项目实际内容"。
- 双分支注意：后端避免 Python 3.9+ 语法；Pydantic 字段保持可降级到 v1 的写法。

---

## 文件结构

**后端新增**
- `backend/services/playbook_spec.py` — 规格校验、规范化、hash、版本兼容。
- `backend/services/playbook_library.py` — 内置规程加载、导出信封、Markdown 手册、文档骨架模板。
- `backend/services/playbook_builtin/research_grant.json` — 科研课题内置规程。
- `backend/services/playbook_builtin/coding_project.json` — 代码工程内置规程。
- `backend/services/playbook_auditor.py` — 扫描、完整性、阶段识别。
- `backend/services/playbook_actions.py` — 动作执行（目录/骨架/规则/里程碑/阶段）。
- `backend/data/playbook_repo.py` — 快照 CRUD + 项目规程状态。
- `backend/api/playbook_routes.py` — HTTP 路由。
- `backend/tests/unit/test_playbook_spec.py`
- `backend/tests/unit/test_playbook_auditor.py`
- `backend/tests/unit/test_playbook_actions.py`
- `backend/tests/unit/test_playbook_repo.py`
- `backend/tests/integration/test_playbook_routes.py`

**后端修改**
- `backend/data/database.py` — `project_playbooks` 表 + `projects.playbook_state` 迁移。
- `backend/data/project_repo.py` — `Project.playbook_state` 字段与更新方法。
- `backend/main.py` — 挂载 `playbook_router`。
- `backend/api/project_schemas.py` — 导出 `ProjectModel` 增加 `playbook_state`（可选）。

**前端新增**
- `src/features/playbook/PlaybookCard.tsx`
- `src/features/playbook/PlaybookChecklist.tsx`
- `src/features/playbook/PlaybookImportDialog.tsx`
- `src/features/playbook/__tests__/PlaybookCard.test.tsx`
- `src/shared/api/playbookApi.ts`
- `src/shared/api/playbookTypes.ts`
- `electron/commandRoutes/playbooks.ts`

**前端修改**
- `src/pages/ProjectGovernance.tsx` — 概览 Tab 挂载规程卡；设置 Tab 增加规程区。
- `src/shared/api/index.ts` — 导出 `playbookApi` 与类型。
- `electron/commands.ts`（或现有路由注册表）— 注册 `playbookRoutes`。
- `src/shared/lib/i18n/locales/zh/playbook.ts`、`en/playbook.ts`（若接入 i18n；P0 可先硬编码中文，P1 补）。

**文档**
- `docs/technical/114-project-playbook.md`（编号以实际最新为准）
- `docs/user-manual/26-project-playbook.md`（编号以实际最新为准）
- 更新 `docs/technical/README.md`、`docs/user-manual/README.md`

---

## Task 1: 规程规格与内置规程库

**Files:**
- Create: `backend/services/playbook_spec.py`
- Create: `backend/services/playbook_library.py`
- Create: `backend/services/playbook_builtin/research_grant.json`
- Create: `backend/services/playbook_builtin/coding_project.json`
- Test: `backend/tests/unit/test_playbook_spec.py`

**Interfaces:**
- Produces: `PLAYBOOK_SCHEMA_VERSION: str`, `PlaybookValidationError`, `normalize_playbook(raw: dict) -> dict`, `spec_hash(spec: dict) -> str`, `is_compatible(version: str) -> bool`
- Produces: `list_builtin() -> list[dict]`, `get_builtin(playbook_id: str) -> dict | None`, `render_markdown_handbook(spec: dict) -> str`, `build_export_envelope(spec: dict, *, include_scaffold: bool, app_version: str) -> dict`, `validate_import_envelope(payload: dict) -> dict`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_playbook_spec.py
import pytest
from backend.services.playbook_spec import (
    PlaybookValidationError, normalize_playbook, spec_hash, is_compatible,
)
from backend.services.playbook_library import (
    list_builtin, get_builtin, render_markdown_handbook, build_export_envelope,
    validate_import_envelope,
)

def minimal_playbook(**overrides):
    spec = {
        "schema_version": "1.0",
        "id": "demo",
        "name": "示例规程",
        "applies_to": {"project_types": ["research"], "sub_types": []},
        "directory_layout": [{"path": "01_开题", "required": True, "purpose": "开题材料"}],
        "stages": [{
            "id": "proposal", "label": "开题", "order": 1,
            "artifacts": [{
                "id": "proposal_report", "label": "开题报告", "required": True,
                "match": {"globs": ["**/开题报告*.md"]},
            }],
            "exit_criteria": [], "rules": [], "recommended_milestones": [],
        }],
        "global_rules": [], "todos": [], "ai_guidance": {},
        "meta": {"author": "t", "license": "CC-BY-4.0", "created_at": "2026-10-31"},
    }
    spec.update(overrides)
    return spec


def test_normalize_fills_defaults_and_rejects_unknown_version():
    spec = normalize_playbook(minimal_playbook())
    assert spec["stages"][0]["artifacts"][0]["match"]["min_count"] == 1
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(minimal_playbook(schema_version="9.0"))


def test_normalize_rejects_path_traversal_and_absolute_paths():
    bad = minimal_playbook(directory_layout=[{"path": "../escape", "required": True}])
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(bad)
    bad = minimal_playbook(directory_layout=[{"path": "/abs/path", "required": True}])
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(bad)


def test_spec_hash_is_stable_and_order_independent():
    a = normalize_playbook(minimal_playbook())
    b = dict(reversed(list(a.items())))
    assert spec_hash(a) == spec_hash(normalize_playbook(b))


def test_builtin_library_has_research_and_coding():
    ids = {item["id"] for item in list_builtin()}
    assert {"cn-research-grant", "coding-project"} <= ids
    assert get_builtin("cn-research-grant")["stages"][0]["id"] == "proposal"


def test_markdown_and_export_envelope_round_trip():
    spec = get_builtin("cn-research-grant")
    md = render_markdown_handbook(spec)
    assert "开题" in md and "实施" in md
    envelope = build_export_envelope(spec, include_scaffold=True, app_version="0.6.0")
    parsed = validate_import_envelope(envelope)
    assert parsed["playbook"]["id"] == spec["id"]
    assert parsed["scaffold"]["directories"]
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/pytest.sh backend/tests/unit/test_playbook_spec.py -q`
Expected: `ModuleNotFoundError: backend.services.playbook_spec`

- [ ] **Step 3: 实现最小代码**

`playbook_spec.py` 核心逻辑：

```python
PLAYBOOK_SCHEMA_VERSION = "1.0"
MAX_STAGES = 20
MAX_ARTIFACTS_PER_STAGE = 50

class PlaybookValidationError(ValueError):
    pass

def _check_rel_path(path: str) -> str:
    path = (path or "").strip().replace("\\", "/")
    if not path or path.startswith("/") or path.startswith("~") or ".." in path.split("/"):
        raise PlaybookValidationError(f"非法相对路径: {path!r}")
    return path

def normalize_playbook(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise PlaybookValidationError("规程必须是 JSON 对象")
    version = str(raw.get("schema_version") or "")
    if not is_compatible(version):
        raise PlaybookValidationError(f"不兼容的 schema_version: {version}")
    for key in ("id", "name", "stages"):
        if not raw.get(key):
            raise PlaybookValidationError(f"缺少字段: {key}")
    if len(raw["stages"]) > MAX_STAGES:
        raise PlaybookValidationError("阶段数量超限")
    spec = {
        "schema_version": PLAYBOOK_SCHEMA_VERSION,
        "id": str(raw["id"]).strip(),
        "name": str(raw["name"]).strip(),
        "description": str(raw.get("description") or ""),
        "applies_to": {
            "project_types": list((raw.get("applies_to") or {}).get("project_types") or []),
            "sub_types": list((raw.get("applies_to") or {}).get("sub_types") or []),
        },
        "directory_layout": [],
        "stages": [], "global_rules": [], "todos": [], "ai_guidance": {},
        "meta": dict(raw.get("meta") or {}),
    }
    for item in raw.get("directory_layout") or []:
        spec["directory_layout"].append({
            "path": _check_rel_path(str(item.get("path") or "")),
            "required": bool(item.get("required", True)),
            "purpose": str(item.get("purpose") or ""),
        })
    for order, stage in enumerate(raw.get("stages") or [], start=1):
        sid = str(stage.get("id") or "").strip()
        if not sid:
            raise PlaybookValidationError("阶段缺少 id")
        artifacts = []
        for art in (stage.get("artifacts") or [])[:MAX_ARTIFACTS_PER_STAGE]:
            match = dict(art.get("match") or {})
            globs = [str(g).replace("\\", "/") for g in (match.get("globs") or [])]
            if not globs:
                raise PlaybookValidationError(f"产物 {art.get('id')} 缺少 match.globs")
            artifacts.append({
                "id": str(art.get("id") or "").strip(),
                "label": str(art.get("label") or "").strip(),
                "required": bool(art.get("required", True)),
                "required_when": art.get("required_when"),
                "match": {
                    "globs": globs,
                    "min_bytes": int(match.get("min_bytes") or 0),
                    "min_count": int(match.get("min_count") or 1),
                    "max_age_days": match.get("max_age_days"),
                },
                "content_checks": list(art.get("content_checks") or []),
                "missing_action": art.get("missing_action"),
            })
        spec["stages"].append({
            "id": sid,
            "label": str(stage.get("label") or sid),
            "order": int(stage.get("order") or order),
            "objective": str(stage.get("objective") or ""),
            "artifacts": artifacts,
            "exit_criteria": list(stage.get("exit_criteria") or []),
            "rules": list(stage.get("rules") or []),
            "recommended_milestones": list(stage.get("recommended_milestones") or []),
        })
    spec["global_rules"] = list(raw.get("global_rules") or [])
    spec["todos"] = list(raw.get("todos") or [])
    spec["ai_guidance"] = dict(raw.get("ai_guidance") or {})
    return spec

def is_compatible(version: str) -> bool:
    major = (version or "").split(".")[0]
    return major == PLAYBOOK_SCHEMA_VERSION.split(".")[0]

def spec_hash(spec: dict) -> str:
    import hashlib, json
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`playbook_library.py`（要点）：

```python
from pathlib import Path
import json
from backend.services.playbook_spec import normalize_playbook, spec_hash

_BUILTIN_DIR = Path(__file__).parent / "playbook_builtin"
_CACHE = None

def _load_builtin() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    items = {}
    for path in sorted(_BUILTIN_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            spec = normalize_playbook(json.load(fh))
        items[spec["id"]] = spec
    _CACHE = items
    return items

def list_builtin() -> list:
    return [
        {"id": s["id"], "name": s["name"], "description": s["description"],
         "project_types": s["applies_to"]["project_types"],
         "stage_count": len(s["stages"])}
        for s in _load_builtin().values()
    ]

def get_builtin(playbook_id: str):
    return _load_builtin().get(playbook_id)

def render_markdown_handbook(spec: dict) -> str:
    lines = [f"# {spec['name']}", "", spec.get("description", ""), "", "## 阶段与交付物", ""]
    for stage in sorted(spec["stages"], key=lambda s: s["order"]):
        lines.append(f"### {stage['order']}. {stage['label']}")
        if stage.get("objective"):
            lines.append(stage["objective"])
        for art in stage["artifacts"]:
            mark = "必需" if art.get("required", True) else "可选"
            globs = ", ".join(art["match"]["globs"])
            lines.append(f"- [ ] {art['label']}（{mark}）：`{globs}`")
    return "\n".join(lines) + "\n"

def build_export_envelope(spec: dict, *, include_scaffold: bool, app_version: str) -> dict:
    spec = normalize_playbook(spec)
    scaffold = {"include": include_scaffold, "directories": [], "documents": []}
    if include_scaffold:
        scaffold["directories"] = [d["path"] for d in spec["directory_layout"] if d["required"]]
        for stage in spec["stages"]:
            for art in stage["artifacts"]:
                action = art.get("missing_action") or {}
                if action.get("type") == "create_doc_stub":
                    scaffold["documents"].append(action.get("payload") or {})
    return {
        "format": "sage.playbook",
        "schema_version": spec["schema_version"],
        "exported_at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exporter": {"app": "Sage", "version": app_version},
        "playbook": spec,
        "scaffold": scaffold,
        "integrity": {"sha256": spec_hash(spec)},
    }

def validate_import_envelope(payload: dict) -> dict:
    from backend.services.playbook_spec import PlaybookValidationError
    if not isinstance(payload, dict) or payload.get("format") != "sage.playbook":
        raise PlaybookValidationError("不是 Sage 规程文件")
    spec = normalize_playbook(payload.get("playbook") or {})
    return {"playbook": spec, "scaffold": payload.get("scaffold") or {"include": False}}
```

内置规程 JSON 从设计文档 §5.2 复制，`coding-project` 使用现有 coding 蓝图阶段与 `src/**`、`tests/**`、`docs/**` 要求。

- [ ] **Step 4: 运行测试通过**

Run: `scripts/pytest.sh backend/tests/unit/test_playbook_spec.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/services/playbook_spec.py backend/services/playbook_library.py \
  backend/services/playbook_builtin backend/tests/unit/test_playbook_spec.py
git commit -m "feat(playbook): 规程规格与内置规程库"
```

---

## Task 2: 项目规程快照表与仓储

**Files:**
- Modify: `backend/data/database.py`（projects 迁移 + 新表）
- Modify: `backend/data/project_repo.py`
- Create: `backend/data/playbook_repo.py`
- Test: `backend/tests/unit/test_playbook_repo.py`

**Interfaces:**
- Consumes: `normalize_playbook`, `spec_hash`
- Produces: `PlaybookSnapshot`, `PlaybookRepository.get_active(project_id) -> PlaybookSnapshot | None`, `create_snapshot(project_id, spec, source, parent_id=None) -> PlaybookSnapshot`, `list_versions(project_id, limit=20) -> list[PlaybookSnapshot]`, `get_state(project_id) -> dict`, `update_state(project_id, state: dict) -> bool`
- Produces: `Project.playbook_state: Optional[str]` + `to_dict()` key、`ProjectRepository.update_playbook_state(project_id, state_json) -> bool`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_playbook_repo.py
import json
import pytest
from pathlib import Path
from backend.data import database as database_module
from backend.data.database import Database
from backend.data.project_repo import ProjectRepository
from backend.data.playbook_repo import PlaybookRepository
from backend.services.playbook_library import get_builtin

@pytest.fixture()
def db(monkeypatch):
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db

@pytest.fixture()
def project(db, tmp_path: Path):
    root = tmp_path / "demo"; root.mkdir()
    return ProjectRepository().register(str(root), project_type="research")

def test_bind_and_read_snapshot(project):
    repo = PlaybookRepository()
    snap = repo.create_snapshot(project.id, get_builtin("cn-research-grant"), source="builtin:cn-research-grant@1")
    assert snap.version == 1
    active = repo.get_active(project.id)
    assert active.spec["id"] == "cn-research-grant"
    assert active.spec_hash

def test_versions_keep_history_and_activate_latest(project):
    repo = PlaybookRepository()
    repo.create_snapshot(project.id, get_builtin("cn-research-grant"), source="custom")
    repo.create_snapshot(project.id, get_builtin("coding-project"), source="custom")
    versions = repo.list_versions(project.id)
    assert [v.version for v in versions] == [2, 1]
    assert repo.get_active(project.id).spec["id"] == "coding-project"

def test_state_round_trip(project):
    repo = PlaybookRepository()
    state = {"current_stage": "proposal", "stage_history": []}
    assert repo.update_state(project.id, state) is True
    assert repo.get_state(project.id)["current_stage"] == "proposal"
```

- [ ] **Step 2: 运行确认失败**

Run: `scripts/pytest.sh backend/tests/unit/test_playbook_repo.py -q`
Expected: `ModuleNotFoundError: backend.data.playbook_repo`

- [ ] **Step 3: 实现**

`database.py` 在 projects 迁移块后追加：

```python
if "playbook_state" not in _projects_columns:
    cursor.execute("ALTER TABLE projects ADD COLUMN playbook_state TEXT")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_playbooks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        source TEXT NOT NULL,
        parent_id TEXT,
        spec_json TEXT NOT NULL,
        spec_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
""")
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_project_playbooks_project "
    "ON project_playbooks(project_id, active, version DESC)"
)
conn.commit()
```

`project_repo.py`：`Project.playbook_state` 字段、`to_dict()`、`_row_to_project`、`update_playbook_state()`。

`playbook_repo.py`：标准仓储，`create_snapshot` 先 `UPDATE project_playbooks SET active=0` 再插入新版本；`get_state` 解析 `Project.playbook_state` JSON；`update_state` 调 `ProjectRepository().update_playbook_state(...)`。

- [ ] **Step 4: 测试通过**

Run: `scripts/pytest.sh backend/tests/unit/test_playbook_repo.py backend/tests/unit/test_project_profile_p2.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/data/database.py backend/data/project_repo.py backend/data/playbook_repo.py backend/tests/unit/test_playbook_repo.py
git commit -m "feat(playbook): 项目规程快照与状态存储"
```

---

## Task 3: 确定性审计器

**Files:**
- Create: `backend/services/playbook_auditor.py`
- Test: `backend/tests/unit/test_playbook_auditor.py`

**Interfaces:**
- Produces: `audit_playbook(project, spec: dict, *, state: dict | None = None) -> dict`
  - 返回 `{playbook:{id,name}, current_stage, detected_stage, stages:[...], overall:{required_total,required_done,progress}, scanned_at}`
- Produces: `match_glob(root: Path, pattern: str) -> list[Path]`（供测试与动作复用）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_playbook_auditor.py
from pathlib import Path
from backend.services.playbook_auditor import audit_playbook
from backend.services.playbook_library import get_builtin

def make_project(tmp_path: Path):
    root = tmp_path / "proj"; root.mkdir()
    (root / "01_开题").mkdir()
    (root / "01_开题" / "开题报告.md").write_text("研究问题\n假设\n技术路线", encoding="utf-8")
    return root

def test_missing_required_artifact_is_reported(tmp_path):
    root = make_project(tmp_path)
    spec = get_builtin("cn-research-grant")
    result = audit_playbook({"path": str(root), "id": "p1", "name": "demo"}, spec)
    proposal = next(s for s in result["stages"] if s["id"] == "proposal")
    report = next(a for a in proposal["artifacts"] if a["id"] == "proposal_report")
    assert report["status"] == "present"
    ethics = next(a for a in proposal["artifacts"] if a["id"] == "ethics_approval")
    assert ethics["status"] in {"missing", "optional"}

def test_completion_and_detected_stage(tmp_path):
    root = make_project(tmp_path)
    spec = get_builtin("cn-research-grant")
    result = audit_playbook({"path": str(root), "id": "p1", "name": "demo"}, spec)
    assert 0 <= result["overall"]["progress"] <= 100
    assert result["detected_stage"]["id"] in {"proposal", "execution", "closure"}

def test_path_outside_root_is_ignored(tmp_path):
    root = make_project(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "开题报告.md").write_text("x", encoding="utf-8")
    spec = get_builtin("cn-research-grant")
    result = audit_playbook({"path": str(root), "id": "p1", "name": "demo"}, spec)
    proposal = next(s for s in result["stages"] if s["id"] == "proposal")
    report = next(a for a in proposal["artifacts"] if a["id"] == "proposal_report")
    assert report["evidence"]["matches"][0].startswith("01_开题/")
```

- [ ] **Step 2: 运行失败** → 实现。

- [ ] **Step 3: 实现要点**

```python
import fnmatch, time
from pathlib import Path
from typing import Any, Dict, List, Optional

EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".sage"}
SENSITIVE_NAMES = {".env", "credentials.json"}

def match_glob(root: Path, pattern: str) -> List[Path]:
    pattern = pattern.replace("\\", "/")
    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.name in SENSITIVE_NAMES or path.name.startswith(".env"):
            continue
        rel_str = rel.as_posix()
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_str, pattern.lstrip("./")):
            matches.append(path)
    return matches
```

`audit_playbook` 逐阶段逐产物计算：
- `matches = union(match_glob(root, g))`
- `status`: `missing`（必需且无匹配）/ `optional`（非必需且无匹配）/ `present` / `stale`（有匹配但 `max_age_days` 全超）
- `evidence.matches` 为相对路径（最多 5 个）、`latest_mtime`。
- 阶段进度：`required_total`、`required_done`（present/stale 计 1；waived 从 state 中读取并计 1）、`progress = round(100*done/total)`。
- 检测阶段：按 order 找第一个 `progress < 70` 的阶段；若全部 ≥70 取最后阶段；同时要求下一阶段存在活动（任一产物 present），否则优先当前进度最高阶段。返回 `{id, confidence, evidence}`。
- `current_stage` 取 state 的 `current_stage` 或 spec 第一阶段。

- [ ] **Step 4: 测试通过**（同上命令）
- [ ] **Step 5: 提交** `feat(playbook): 确定性与阶段识别审计器`

---

## Task 4: 动作执行与导出

**Files:**
- Create: `backend/services/playbook_actions.py`
- Test: `backend/tests/unit/test_playbook_actions.py`
- Test: `backend/tests/unit/test_playbook_spec.py`（导出测试已在 Task 1）

**Interfaces:**
- Produces: `apply_playbook_actions(project, actions: list[dict]) -> dict`
  - 支持 `create_folder`、`create_doc_stub`、`apply_rules`、`seed_milestones`、`set_stage`
  - 返回 `{applied: [...], skipped: [...], errors: [{item,message}], checkpoint_created: bool}`
- Consumes: `ProjectConstraintRepository`, `ProjectMilestoneRepository`, `create_project_checkpoint`

- [ ] **Step 1: 写失败测试**

```python
def test_create_folder_and_doc_stub_idempotent(project, tmp_path):
    from backend.services.playbook_actions import apply_playbook_actions
    result = apply_playbook_actions(project, [
        {"type": "create_folder", "payload": {"path": "01_开题"}},
        {"type": "create_doc_stub", "payload": {"path": "01_开题/开题报告.md", "template": "research_proposal"}},
    ])
    assert "create_folder" in result["applied"]
    assert (tmp_path / "demo" / "01_开题" / "开题报告.md").is_file()
    again = apply_playbook_actions(project, [{"type": "create_folder", "payload": {"path": "01_开题"}}])
    assert again["skipped"]

def test_apply_rules_and_milestones_dedup(project):
    from backend.services.playbook_actions import apply_playbook_actions
    actions = [
        {"type": "apply_rules", "payload": {"rules": [{"content": "Use ruff", "category": "coding_style", "priority": 7}]}},
        {"type": "seed_milestones", "payload": {"milestones": [{"title": "开题报告", "stage": "proposal"}]}},
    ]
    first = apply_playbook_actions(project, actions)
    second = apply_playbook_actions(project, actions)
    assert "apply_rules" in first["applied"]
    assert "apply_rules" in second["skipped"]
    assert "seed_milestones" in second["skipped"]

def test_rejects_path_escape(project):
    from backend.services.playbook_actions import apply_playbook_actions
    result = apply_playbook_actions(project, [{"type": "create_folder", "payload": {"path": "../escape"}}])
    assert result["errors"]
    assert not (Path(project.path).parent / "escape").exists()
```

- [ ] **Step 2–4: 实现并跑通**

要点：
- 所有 `path` 经 `Path(root, rel).resolve()` 后必须 `is_relative_to(root.resolve())`（py3.8 用 `str.startswith` 兜底）。
- `create_doc_stub` 不覆盖已有文件；模板内容来自 `playbook_library.DOC_STUB_TEMPLATES`（新增常量）。
- 批量动作前调用 `create_project_checkpoint(project, "应用项目规程")`，失败不阻塞但记录 `checkpoint_created=False`。
- `set_stage` 更新 `projects.project_stage` 并写入 `playbook_state.stage_history`。
- `apply_rules` 按 normalized content 去重，与 `project_bootstrap._normalize` 行为一致。

- [ ] **Step 5: 提交** `feat(playbook): 规程动作执行与幂等`

---

## Task 5: HTTP API

**Files:**
- Create: `backend/api/playbook_routes.py`
- Create: `backend/api/playbook_schemas.py`（推荐独立文件）
- Modify: `backend/main.py`
- Test: `backend/tests/integration/test_playbook_routes.py`

**Interfaces:** 端点见设计文档 §7.2；本计划实现：
- `GET /api/v1/playbooks/builtin`
- `GET /api/v1/playbooks/builtin/{id}`
- `GET /api/v1/projects/{id}/playbook`
- `PUT /api/v1/projects/{id}/playbook`（body `{playbook_id?, spec?, source?}`）
- `GET /api/v1/projects/{id}/playbook/audit`
- `POST /api/v1/projects/{id}/playbook/stage/confirm`（body `{stage_id}`）
- `POST /api/v1/projects/{id}/playbook/actions/apply`（body `{actions}`）
- `GET /api/v1/projects/{id}/playbook/export?format=json|md`
- `POST /api/v1/playbooks/import/preview` + `POST /api/v1/playbooks/import`

- [ ] **Step 1: 写失败集成测试**（使用 `TestClient`，参考 `backend/tests/integration/test_project_routes.py` 的 app/db fixture；注册临时项目后逐个断言 200/结构）
- [ ] **Step 2: 实现路由与 Pydantic schema**
- [ ] **Step 3: 挂载**

```python
# backend/main.py
from backend.api.playbook_routes import playbook_router
app.include_router(playbook_router, prefix="/api/v1")
```

- [ ] **Step 4: 跑集成测试**
- [ ] **Step 5: 提交** `feat(playbook): HTTP API 与导入导出`

---

## Task 6: 前端 API 与 IPC 桥

**Files:**
- Create: `src/shared/api/playbookTypes.ts`
- Create: `src/shared/api/playbookApi.ts`
- Create: `electron/commandRoutes/playbooks.ts`
- Modify: `src/shared/api/index.ts`
- Modify: `electron/commands.ts`（注册路由）

**Interfaces:**
- `playbookApi.getCurrent(projectId)`, `bind(projectId, payload)`, `audit(projectId)`, `confirmStage(projectId, stageId)`, `applyActions(projectId, actions)`, `exportPlaybook(projectId, format)`, `importPreview(payload)`, `importPlaybook(payload)`
- IPC command names: `playbooks_builtin_list`, `playbooks_builtin_get`, `playbook_get_current`, `playbook_bind`, `playbook_audit`, `playbook_stage_confirm`, `playbook_actions_apply`, `playbook_export`, `playbook_import_preview`, `playbook_import`.

- [ ] **Step 1–4: 按现有 `projects_bootstrap_*` 的写法实现；vite 单测用 mock invoke 验证参数映射**
- [ ] **Step 5: 提交** `feat(playbook): 前端 API 与 Electron IPC`

---

## Task 7: 项目主页规程卡与设置区

**Files:**
- Create: `src/features/playbook/PlaybookCard.tsx`
- Create: `src/features/playbook/PlaybookChecklist.tsx`
- Create: `src/features/playbook/PlaybookImportDialog.tsx`
- Modify: `src/pages/ProjectGovernance.tsx`
- Test: `src/features/playbook/__tests__/PlaybookCard.test.tsx`

**UI 要求：**
- 概览 Tab 在 `ProjectBootstrapPanel` 之后挂载 `<PlaybookCard project={project} />`。
- 未绑定规程时显示"为这个项目选择管理规程"按钮；已绑定显示阶段条、完成度、缺失项清单、`检查完整性`、`导出`。
- 缺失项有 `创建目录` / `生成骨架` 按钮，点击后调用 `applyActions` 并刷新 audit。
- 阶段检测结果以"检测到可能已进入『实施』阶段 [确认推进] [保持当前]"呈现；确认调用 `confirmStage`。
- 设置 Tab 增加规程信息区（名称/来源/版本/解绑/导入）。
- 导入对话框：文件选择 → `File.text()` → `importPreview` → 展示 diff/摘要 → `import`；明确提示"导入仅包含规程与空骨架，不含对方项目文件内容"。

- [ ] **Step 1: 写组件测试**（mock `playbookApi`，断言未绑定态、绑定态、缺失项按钮、确认推进）
- [ ] **Step 2–4: 实现与跑测试** `npx vitest run src/features/playbook/__tests__/PlaybookCard.test.tsx`
- [ ] **Step 5: 提交** `feat(playbook): 项目主页规程卡与导入导出`

---

## Task 8: 文档、质量门与收尾

- [ ] 新增技术文档章节（架构、规格、审计、API、双分支注意）
- [ ] 新增用户手册章节（如何绑定/定制/检查/导出/导入）
- [ ] 更新两个 README 索引
- [ ] 运行后端全量项目相关测试 + 前端测试
- [ ] 运行 `npm run build`（类型检查）与 `npm run lint`
- [ ] 更新 `docs/plans/2026-10-31_project-playbook.md` 的 P0/P1 勾选状态
- [ ] 提交 `docs(playbook): 技术文档与用户手册`

---

## 验收标准

1. 科研项目绑定内置规程后，概览页显示阶段条、完成度、缺失项清单。
2. 点击"检查完整性"返回与文件系统一致的证据（路径、时间、缺失原因）。
3. 缺失项动作可创建目录与文档骨架，重复执行幂等，执行前有检查点。
4. 阶段识别给出证据，确认后才写入 `project_stage` 与 `stage_history`。
5. 导出的 `.sageplaybook.json` 可在另一项目导入并绑定，审计结果一致。
6. 导入包含 `../` 或绝对路径时被拒绝，且不产生任何文件。
7. 后端项目相关测试全绿；前端新增组件测试全绿；`npm run build` 通过。

## 不在本计划范围

- LLM 定制规程、LLM 内容级检查、阶段 LLM 裁决（P2）。
- AGENTS.md/CLAUDE.md 导出（P2）。
- 文件归类与移动（P3）。
- 云端规程市场（不做）。
