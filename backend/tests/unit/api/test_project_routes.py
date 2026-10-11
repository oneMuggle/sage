"""R183 — projects 注册表路由单元测试（`backend/api/project_routes.py`）。

DB 由 tests/conftest.py 的 autouse `setup_test_db` 提供（模板库复制的
独立临时库），全部 25 条路由走真实 SQL。与
`tests/integration/test_project_routes.py` 互补：那边只覆盖登记/open/
sessions 生命周期，本文件覆盖 patch 语义、allowed-paths、资料与
answer 保存、类型检测、约束、里程碑、类型配置、git-status。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import project_routes as pr

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router)
    return TestClient(app)


@pytest.fixture()
def ws_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workspace-a"
    d.mkdir()
    return d


def _register(client: TestClient, path: Path, **extra) -> dict:
    resp = client.post("/projects", json={"path": str(path), **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# 登记 / 清单
# ---------------------------------------------------------------------------


def test_register_project(client, ws_dir: Path) -> None:
    body = _register(client, ws_dir)
    assert body["path"] == str(ws_dir.resolve())
    assert body["name"] == "workspace-a"
    assert body["session_count"] == 0
    assert body["last_session_id"] is None
    assert body["vcs_mode"] == "builtin"


def test_register_project_idempotent_by_path(client, ws_dir: Path) -> None:
    first = _register(client, ws_dir)
    second = _register(client, ws_dir, project_type="coding")
    assert second["id"] == first["id"]  # ON CONFLICT(path) 更新而非新行
    rows = client.get("/projects").json()["projects"]
    assert len(rows) == 1
    assert rows[0]["project_type"] == "coding"


def test_register_project_missing_dir(client, tmp_path: Path) -> None:
    resp = client.post("/projects", json={"path": str(tmp_path / "ghost")})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_workspace_path"


def test_register_project_rejects_dotdot(client, tmp_path: Path) -> None:
    sneaky = str(tmp_path / "sub" / ".." / "escape")
    resp = client.post("/projects", json={"path": sneaky})
    assert resp.status_code == 400


def test_list_projects_orders_and_fields(client, ws_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "workspace-b"
    other.mkdir()
    _register(client, ws_dir)
    _register(client, other)
    rows = client.get("/projects").json()["projects"]
    assert {r["name"] for r in rows} == {"workspace-a", "workspace-b"}
    assert all("allowed_paths" in r and "project_type" in r for r in rows)


# ---------------------------------------------------------------------------
# 更新 / 删除
# ---------------------------------------------------------------------------


def test_patch_project_fields_set_semantics(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    body = client.patch(f"/projects/{pid}", json={"description": "d1"}).json()
    assert body["description"] == "d1"
    assert body["instructions"] is None
    body = client.patch(f"/projects/{pid}", json={"instructions": "i1"}).json()
    assert body["description"] == "d1"  # 未出现的字段保持不变
    assert body["instructions"] == "i1"


def test_patch_project_type_and_stage(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    body = client.patch(
        f"/projects/{pid}", json={"project_type": "research", "project_stage": "探索"}
    ).json()
    assert body["project_type"] == "research"
    assert body["project_stage"] == "探索"


def test_patch_project_invalid_type(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    resp = client.patch(f"/projects/{pid}", json={"project_type": "hacker"})
    assert resp.status_code == 422


def test_patch_and_delete_unknown_project(client) -> None:
    assert client.patch("/projects/nope", json={"description": "x"}).status_code == 404
    assert client.delete("/projects/nope").status_code == 404


def test_delete_project(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    assert client.delete(f"/projects/{pid}").json() == {"removed": True}
    rows = client.get("/projects").json()["projects"]
    assert rows == []


def test_update_allowed_paths(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    resp = client.put(f"/projects/{pid}/allowed-paths", json={"allowed_paths": ["D:/extra"]})
    assert resp.status_code == 200
    assert resp.json() == {"id": pid, "allowed_paths": ["D:/extra"]}
    rows = client.get("/projects").json()["projects"]
    assert rows[0]["allowed_paths"] == ["D:/extra"]


# ---------------------------------------------------------------------------
# open / sessions
# ---------------------------------------------------------------------------


def test_open_project_creates_bound_session(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    first = client.post(f"/projects/{pid}/open").json()
    assert first["created"] is True
    assert first["session"]["title"] == "workspace-a"
    second = client.post(f"/projects/{pid}/open").json()
    assert second["created"] is False  # 复用最近会话
    assert second["session"]["id"] == first["session"]["id"]


def test_open_project_unknown(client) -> None:
    assert client.post("/projects/nope/open").status_code == 404


def test_open_project_path_missing(client, ws_dir: Path) -> None:
    import shutil

    pid = _register(client, ws_dir)["id"]
    shutil.rmtree(ws_dir)
    resp = client.post(f"/projects/{pid}/open")
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "project_path_missing"


def test_list_project_sessions(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    opened = client.post(f"/projects/{pid}/open").json()
    rows = client.get(f"/projects/{pid}/sessions").json()["sessions"]
    assert [s["id"] for s in rows] == [opened["session"]["id"]]
    assert client.get("/projects/nope/sessions").status_code == 404


# ---------------------------------------------------------------------------
# 项目资料 / answer 保存
# ---------------------------------------------------------------------------


def test_material_crud(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    assert client.get(f"/projects/{pid}/materials").json()["materials"] == []
    created = client.post(f"/projects/{pid}/materials", json={"content": "关键结论 A"})
    assert created.status_code == 201
    material = created.json()
    assert material["content"] == "关键结论 A"
    assert material["project_id"] == pid

    rows = client.get(f"/projects/{pid}/materials").json()["materials"]
    assert [m["id"] for m in rows] == [material["id"]]

    assert client.delete(f"/projects/{pid}/materials/{material['id']}").json() == {"removed": True}
    assert client.delete(f"/projects/{pid}/materials/{material['id']}").status_code == 404


def test_material_unknown_project(client) -> None:
    assert client.get("/projects/nope/materials").status_code == 404
    resp = client.post("/projects/nope/materials", json={"content": "x"})
    assert resp.status_code == 404


def test_material_oversize_rejected(client, ws_dir: Path) -> None:
    from backend.data.project_material_repo import MAX_MATERIAL_CONTENT_CHARS

    pid = _register(client, ws_dir)["id"]
    resp = client.post(
        f"/projects/{pid}/materials", json={"content": "x" * (MAX_MATERIAL_CONTENT_CHARS + 1)}
    )
    assert resp.status_code == 422


def test_save_answer_assistant_message(client, ws_dir: Path) -> None:
    from backend.data.session_repo import Message, MessageRepository

    pid = _register(client, ws_dir)["id"]
    session_id = client.post(f"/projects/{pid}/open").json()["session"]["id"]
    msg = Message(
        id="msg-a1",
        session_id=session_id,
        role="assistant",
        content="回答内容",
        created_at=int(time.time() * 1000),
    )
    MessageRepository().save(msg)

    resp = client.post(f"/projects/{pid}/materials/save-answer", json={"message_id": "msg-a1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["content"] == "回答内容"
    assert body["source_message_id"] == "msg-a1"


def test_save_answer_rejects_user_role(client, ws_dir: Path) -> None:
    from backend.data.session_repo import Message, MessageRepository

    pid = _register(client, ws_dir)["id"]
    session_id = client.post(f"/projects/{pid}/open").json()["session"]["id"]
    MessageRepository().save(
        Message(
            id="msg-u1",
            session_id=session_id,
            role="user",
            content="用户消息",
            created_at=int(time.time() * 1000),
        )
    )
    resp = client.post(f"/projects/{pid}/materials/save-answer", json={"message_id": "msg-u1"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "message_role_not_savable"


def test_save_answer_message_of_other_project(client, ws_dir: Path, tmp_path: Path) -> None:
    from backend.data.session_repo import Message, MessageRepository

    other = tmp_path / "workspace-b"
    other.mkdir()
    pid_a = _register(client, ws_dir)["id"]
    pid_b = _register(client, other)["id"]
    session_b = client.post(f"/projects/{pid_b}/open").json()["session"]["id"]
    MessageRepository().save(
        Message(
            id="msg-b1",
            session_id=session_b,
            role="assistant",
            content="B 的回答",
            created_at=int(time.time() * 1000),
        )
    )
    resp = client.post(f"/projects/{pid_a}/materials/save-answer", json={"message_id": "msg-b1"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "message_project_mismatch"


def test_save_answer_unknown_message(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    client.post(f"/projects/{pid}/open")
    resp = client.post(f"/projects/{pid}/materials/save-answer", json={"message_id": "ghost"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 类型检测 / 配置
# ---------------------------------------------------------------------------


def test_detect_type_on_empty_dir(client, tmp_path: Path) -> None:
    d = tmp_path / "empty-proj"
    d.mkdir()
    body = client.post("/projects/detect-type", json={"path": str(d)}).json()
    assert set(body) == {"project_type", "confidence", "signals"}
    assert isinstance(body["confidence"], float)


def test_detect_type_missing_dir(client, tmp_path: Path) -> None:
    resp = client.post("/projects/detect-type", json={"path": str(tmp_path / "ghost")})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "path_not_directory"


def test_project_type_config(client) -> None:
    body = client.get("/projects/config/types").json()
    assert body["milestone_status"] == ["pending", "in_progress", "completed", "blocked"]
    assert body["constraint_templates"]
    assert body["stage_enum"]


# ---------------------------------------------------------------------------
# 约束
# ---------------------------------------------------------------------------


def test_constraint_crud(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    created = client.post(
        f"/projects/{pid}/constraints",
        json={"category": "风格", "content": "使用四空格缩进", "priority": 7},
    )
    assert created.status_code == 201
    constraint = created.json()
    assert constraint["enabled"] is True
    assert constraint["priority"] == 7

    updated = client.patch(
        f"/projects/{pid}/constraints/{constraint['id']}",
        json={"enabled": False, "priority": 3},
    ).json()
    assert updated["enabled"] is False
    assert updated["priority"] == 3

    rows = client.get(f"/projects/{pid}/constraints").json()["constraints"]
    assert [c["id"] for c in rows] == [constraint["id"]]

    assert client.delete(f"/projects/{pid}/constraints/{constraint['id']}").json() == {
        "removed": True
    }


def test_constraint_cross_project_id_404(client, ws_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "workspace-c"
    other.mkdir()
    pid_a = _register(client, ws_dir)["id"]
    pid_b = _register(client, other)["id"]
    cid = client.post(
        f"/projects/{pid_a}/constraints", json={"category": "c", "content": "x"}
    ).json()["id"]
    resp = client.patch(f"/projects/{pid_b}/constraints/{cid}", json={"enabled": False})
    assert resp.status_code == 404


def test_constraint_import_template(client, ws_dir: Path) -> None:
    from backend.data.project_constraint_repo import CONSTRAINT_TEMPLATES

    pid = _register(client, ws_dir)["id"]
    template_name = sorted(CONSTRAINT_TEMPLATES)[0]
    resp = client.post(
        f"/projects/{pid}/constraints/import-template", json={"template": template_name}
    )
    assert resp.status_code == 201
    created = resp.json()["constraints"]
    assert created
    assert all(c["project_id"] == pid for c in created)

    bad = client.post(f"/projects/{pid}/constraints/import-template", json={"template": "nope"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "unknown_template"

    templates = client.get("/projects/templates/constraints").json()["templates"]
    assert set(templates) == set(CONSTRAINT_TEMPLATES)


def test_constraint_unknown_project(client) -> None:
    resp = client.post("/projects/nope/constraints", json={"category": "c", "content": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 里程碑
# ---------------------------------------------------------------------------


def test_milestone_lifecycle(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    created = client.post(
        f"/projects/{pid}/milestones",
        json={"title": "M1", "due_date": "2026-10-01", "sort_order": 2},
    )
    assert created.status_code == 201
    milestone = created.json()
    assert milestone["status"] == "pending"
    assert milestone["completed_at"] is None

    listed = client.get(f"/projects/{pid}/milestones").json()["milestones"]
    assert [m["id"] for m in listed] == [milestone["id"]]
    filtered = client.get(f"/projects/{pid}/milestones", params={"status": "completed"}).json()[
        "milestones"
    ]
    assert filtered == []

    completed = client.post(f"/projects/{pid}/milestones/{milestone['id']}/complete").json()
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None
    filtered = client.get(f"/projects/{pid}/milestones", params={"status": "completed"}).json()[
        "milestones"
    ]
    assert [m["id"] for m in filtered] == [milestone["id"]]

    assert client.delete(f"/projects/{pid}/milestones/{milestone['id']}").json() == {
        "removed": True
    }


def test_milestone_patch_fields(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    mid = client.post(f"/projects/{pid}/milestones", json={"title": "T"}).json()["id"]
    body = client.patch(
        f"/projects/{pid}/milestones/{mid}",
        json={"title": "T2", "stage": "构建", "sort_order": 5},
    ).json()
    assert body["title"] == "T2"
    assert body["stage"] == "构建"
    assert body["sort_order"] == 5
    assert client.patch(f"/projects/{pid}/milestones/ghost", json={"title": "x"}).status_code == 404


def test_milestone_bad_due_date_pattern(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    resp = client.post(f"/projects/{pid}/milestones", json={"title": "T", "due_date": "2026/10/01"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# git-status
# ---------------------------------------------------------------------------


def test_git_status_non_repo(client, ws_dir: Path) -> None:
    pid = _register(client, ws_dir)["id"]
    body = client.get(f"/projects/{pid}/git-status").json()
    assert body["is_repo"] is False
    assert body["current_branch"] is None


def test_git_status_repo(client, tmp_path: Path) -> None:
    repo = tmp_path / "git-proj"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_bytes(b"hello")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "b.txt").write_bytes(b"dirty")

    pid = _register(client, repo)["id"]
    body = client.get(f"/projects/{pid}/git-status").json()
    assert body["is_repo"] is True
    assert body["current_branch"] == "main"
    assert "b.txt" in body["untracked_files"]
    assert body["recent_commits"][0]["message"] == "init"



def test_scaffold_business_archive_project(client, tmp_path: Path) -> None:
    dossier_dir = tmp_path / "dossier-2026"
    dossier_dir.mkdir()
    pid = _register(client, dossier_dir)["id"]

    resp = client.post(
        f"/projects/{pid}/scaffold",
        json={"project_type": "business"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["project_type"] == "business"
    assert body["project"]["project_stage"] == "initiation"
    assert set(body["created_directories"]) == {
        "00_立项与背景材料",
        "01_原始依据与佐证",
        "02_编制中工作稿",
        "03_定稿与签发归档",
    }
    assert body["created_files"] == ["SAGE.md"]
    assert (dossier_dir / "01_原始依据与佐证").is_dir()
    assert (dossier_dir / "SAGE.md").is_file()
    assert body["imported_constraints_count"] >= 3
    assert body["seeded_milestones_count"] >= 3

    # 幂等再调一次：不重复创建已存在的目录/SAGE.md、不重复导入约束和里程碑
    resp_again = client.post(f"/projects/{pid}/scaffold", json={"project_type": "business"})
    assert resp_again.status_code == 200
    again_body = resp_again.json()
    assert again_body["created_directories"] == []
    assert again_body["created_files"] == []
    assert again_body["imported_constraints_count"] == 0
    assert again_body["seeded_milestones_count"] == 0


def test_scaffold_research_project(client, tmp_path: Path) -> None:
    lab_dir = tmp_path / "llm-paper"
    lab_dir.mkdir()
    pid = _register(client, lab_dir)["id"]

    resp = client.post(
        f"/projects/{pid}/scaffold",
        json={"project_type": "research"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["project_type"] == "research"
    assert body["project"]["project_stage"] == "proposal"
    assert set(body["created_directories"]) == {
        "01_literature",
        "02_experiments_and_data",
        "03_manuscript",
        "04_submission_and_rebuttal",
    }
    assert "零幻觉引用铁律" in (lab_dir / "SAGE.md").read_text(encoding="utf-8")


def test_material_toggle_context_budget_and_workspace_overview(
    client, tmp_path: Path
) -> None:
    ws_dir = tmp_path / "polymorphic-ws"
    ws_dir.mkdir()
    (ws_dir / "SAGE.md").write_text("# 项目宪法\n遵守规范", encoding="utf-8")
    (ws_dir / "01_literature").mkdir()
    (ws_dir / "01_literature" / "refs.bib").write_text("@article{k2026}", encoding="utf-8")
    (ws_dir / "03_定稿与签批归档").mkdir()
    (ws_dir / "03_定稿与签批归档" / "report.docx").write_bytes(b"PK\x03\x04dummy")

    pid = _register(client, ws_dir)["id"]
    mat = client.post(
        f"/projects/{pid}/materials",
        json={"content": "核心文献摘要：Transformer 架构与注意力机制"},
    ).json()
    assert mat["enabled"] is True

    budget1 = client.get(f"/projects/{pid}/context-budget").json()
    assert budget1["active_materials_count"] == 1
    assert budget1["total_materials_count"] == 1
    assert budget1["l1_conventions_chars"] > 0
    assert budget1["l4_materials_chars"] > 0

    patched = client.patch(
        f"/projects/{pid}/materials/{mat['id']}",
        json={"enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    budget2 = client.get(f"/projects/{pid}/context-budget").json()
    assert budget2["active_materials_count"] == 0
    assert budget2["total_materials_count"] == 1
    assert budget2["l4_materials_chars"] == 0

    overview = client.get(f"/projects/{pid}/workspace-overview").json()
    assert overview["has_sage_md"] is True
    assert any(item["name"] == "report.docx" for item in overview["office_deliverables"])
    assert any(item["name"] == "refs.bib" for item in overview["research_artifacts"])


def test_add_material_from_workspace_file(client, ws_dir: Path):
    """POST /projects/{id}/materials/from-file 支持将工作区文献/案卷文件一键纳入受控资料池并拦截越界路径。"""
    pid = _register(client, ws_dir)["id"]

    lit_dir = ws_dir / "01_literature"
    lit_dir.mkdir(exist_ok=True)
    bib_file = lit_dir / "references.bib"
    bib_file.write_text("@article{vaswani2017attention, title={Attention is All You Need}}", encoding="utf-8")

    pin_res = client.post(
        f"/projects/{pid}/materials/from-file",
        json={"relative_path": "01_literature/references.bib"},
    )
    assert pin_res.status_code == 201
    mat = pin_res.json()
    assert mat["status"] == "ready"
    assert mat["enabled"] is True
    assert "[来源文件: 01_literature/references.bib]" in mat["content"]
    assert "vaswani2017attention" in mat["content"]

    # Path traversal is rejected with 400
    bad_res = client.post(
        f"/projects/{pid}/materials/from-file",
        json={"relative_path": "../outside.txt"},
    )
    assert bad_res.status_code == 400


def test_project_diagnose_endpoint(client, ws_dir: Path):
    """GET /projects/{id}/diagnose 返回代码项目的语言栈、测试命令入口与 hooks.json 状态。"""
    (ws_dir / "package.json").write_text(
        '{"name": "demo", "scripts": {"test": "vitest", "lint": "eslint ."}}',
        encoding="utf-8",
    )
    (ws_dir / "tsconfig.json").write_text("{}", encoding="utf-8")
    hooks_dir = ws_dir / ".sage"
    hooks_dir.mkdir(exist_ok=True)
    (hooks_dir / "hooks.json").write_text('{"hooks": [{"event": "post-edit"}]}', encoding="utf-8")

    pid = _register(client, ws_dir)["id"]
    resp = client.get(f"/projects/{pid}/diagnose")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert "TypeScript/Node.js" in body["detected_languages"]
    assert "npm run test" in body["test_commands"]
    assert "npm run lint" in body["test_commands"]
    assert body["hooks_config_exists"] is True
    assert body["hooks_count"] == 1
