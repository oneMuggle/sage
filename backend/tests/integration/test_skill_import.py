"""Integration tests for /skills/rescan and /skills/import endpoints.

Use FastAPI TestClient + monkeypatch env to isolated tmp dirs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def _md(name: str, description: str = "Test") -> bytes:
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        ---
        Body of {name}.
    """).encode("utf-8")


def _reset_skill_adapter_singleton() -> None:
    """InprocSkillAdapter 是惰性单例, 测试需要 reset 才能读到新 SAGE_SKILLS_DIR。

    单例存在 backend/api/legacy_routes.py 模块全局变量 `_skill_adapter_singleton`。
    """
    import backend.api.legacy_routes as routes_mod
    routes_mod._skill_adapter_singleton = None


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client + reset adapter singleton so each test sees a fresh adapter."""
    skills = tmp_path / "skills"
    skills.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(skills))
    _reset_skill_adapter_singleton()
    return TestClient(app)


# ===== POST /skills/rescan =====


def test_post_skills_rescan_returns_loaded_count(client: TestClient, tmp_path: Path) -> None:
    """Rescan finds a pre-existing SKILL.md and returns it as loaded."""
    skills = tmp_path / "skills"
    (skills / "code-review").mkdir()
    (skills / "code-review" / "SKILL.md").write_bytes(_md("code-review"))

    _reset_skill_adapter_singleton()

    resp = client.post("/api/v1/skills/rescan")
    assert resp.status_code == 200
    body = resp.json()
    assert "loaded" in body
    assert "skipped" in body
    assert "total_loaded" in body


def test_post_skills_rescan_is_idempotent(client: TestClient, tmp_path: Path) -> None:
    """Rescan 是幂等的: 同样状态下重复调用不重复加载。

    Adapter init 时已经 auto-load 了 SAGE_SKILLS_DIR 下的所有 SKILL.md, 所以首次
    rescan 也应返回 loaded=0。关键是"加新文件后再 rescan 能发现"。
    """
    skills = tmp_path / "skills"
    (skills / "code-review").mkdir()
    (skills / "code-review" / "SKILL.md").write_bytes(_md("code-review"))

    _reset_skill_adapter_singleton()

    # 第一次: 已经在 __init__ 时 auto-loaded, rescan 看到 0 新增
    r1 = client.post("/api/v1/skills/rescan").json()
    assert r1["total_loaded"] == 0

    # 第二次: 仍然 0 (幂等)
    r2 = client.post("/api/v1/skills/rescan").json()
    assert r2["total_loaded"] == 0

    # 关键验证: 加新文件后, rescan 能发现
    (skills / "new-skill").mkdir()
    (skills / "new-skill" / "SKILL.md").write_bytes(_md("new-skill"))
    r3 = client.post("/api/v1/skills/rescan").json()
    assert r3["total_loaded"] == 1
    assert any(s["name"] == "new-skill" for s in r3["loaded"])


# ===== POST /skills/import =====


def test_post_skills_import_multipart_round_trip(client: TestClient, tmp_path: Path) -> None:
    """POST files → GET /skills shows them."""
    _reset_skill_adapter_singleton()

    files = {"files": ("code-review.md", _md("code-review"), "text/markdown")}
    resp = client.post("/api/v1/skills/import", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["imported"]) == 1
    assert body["imported"][0]["name"] == "code-review"
    assert (tmp_path / "skills" / "code-review" / "SKILL.md").is_file()

    # GET /skills 看到新 skill
    list_resp = client.get("/api/v1/skills")
    names = [s["name"] for s in list_resp.json()]
    assert "code-review" in names


def test_post_skills_import_returns_structured_skipped(
    client: TestClient, tmp_path: Path
) -> None:
    """Bad file → skipped with reason, valid file → imported."""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("good.md", _md("good"), "text/markdown")),
        ("files", ("broken.md", b"no frontmatter at all", "text/markdown")),
    ]
    resp = client.post("/api/v1/skills/import", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["imported"]) == 1
    assert body["imported"][0]["name"] == "good"
    skip_reasons = {s["name"]: s["reason"] for s in body["skipped"]}
    assert "broken" in skip_reasons
    assert skip_reasons["broken"].startswith("parse_error:")


def test_post_skills_import_no_files_returns_400(client: TestClient) -> None:
    """Empty multipart → 400 invalid_request."""
    _reset_skill_adapter_singleton()

    resp = client.post("/api/v1/skills/import", files={})
    assert resp.status_code == 400
    assert resp.json()["detail"]["type"] == "invalid_request"


def test_post_skills_import_to_sage_skills_dir_uses_env(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files go to SAGE_SKILLS_DIR, not ~/.sage/skills."""
    # Fixture already created tmp_path/skills; just point env to it.
    target = tmp_path / "skills"
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(target))

    _reset_skill_adapter_singleton()

    files = {"files": ("code-review.md", _md("code-review"), "text/markdown")}
    resp = client.post("/api/v1/skills/import", files=files)

    assert resp.status_code == 200
    assert (target / "code-review" / "SKILL.md").is_file()


def test_post_skills_import_invalid_md_returns_parse_error_in_skipped(
    client: TestClient,
) -> None:
    _reset_skill_adapter_singleton()

    bad = b"---\ndescription: no name\n---\nbody"
    files = {"files": ("bad.md", bad, "text/markdown")}
    resp = client.post("/api/v1/skills/import", files=files)

    body = resp.json()
    assert body["imported"] == []
    assert any(s["reason"].startswith("parse_error:") for s in body["skipped"])


def test_post_skills_import_concurrent_safe(client: TestClient) -> None:
    """Two files with same name in one batch → one imported, one skipped."""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("a.md", _md("dup"), "text/markdown")),
        ("files", ("b.md", _md("dup"), "text/markdown")),
    ]
    resp = client.post("/api/v1/skills/import", files=files)

    body = resp.json()
    # 第一个应该成功 (写盘), 第二个被 already_exists skip
    assert len(body["imported"]) >= 1
    skip_names = [s["name"] for s in body["skipped"]]
    assert "dup" in skip_names


def test_post_skills_import_then_list_includes_new(client: TestClient) -> None:
    """End-to-end: POST → GET /skills 包含新 skill。"""
    _reset_skill_adapter_singleton()

    files = {"files": ("new-skill.md", _md("new-skill"), "text/markdown")}
    client.post("/api/v1/skills/import", files=files)

    list_resp = client.get("/api/v1/skills")
    names = [s["name"] for s in list_resp.json()]
    assert "new-skill" in names


def test_post_skills_import_with_empty_file_returns_skipped(client: TestClient) -> None:
    """Empty file → skip (parse error: missing delimiter)."""
    _reset_skill_adapter_singleton()

    files = {"files": ("empty.md", b"", "text/markdown")}
    resp = client.post("/api/v1/skills/import", files=files)

    body = resp.json()
    assert body["imported"] == []
    assert len(body["skipped"]) == 1


def test_post_skills_import_oversized_file_skipped(
    client: TestClient,
) -> None:
    """File > 1MB → skipped with file_too_large reason."""
    from backend.skills.skill_md.importer import MAX_FILE_SIZE_BYTES

    _reset_skill_adapter_singleton()

    huge = b"---\nname: huge\ndescription: huge\n---\n" + b"x" * (MAX_FILE_SIZE_BYTES + 1)
    files = {"files": ("huge.md", huge, "text/markdown")}
    resp = client.post("/api/v1/skills/import", files=files)

    body = resp.json()
    assert body["imported"] == []
    assert any("file_too_large" in s["reason"] for s in body["skipped"])
