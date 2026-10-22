"""Integration tests for POST /skills/import-directory.

The endpoint accepts a whole skill directory as multipart, where each part's
``filename`` carries a relative path (``SKILL.md`` / ``scripts/scan.py``).
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
    """InprocSkillAdapter 是惰性单例，测试需要 reset 才能读到新 SAGE_SKILLS_DIR。"""
    import backend.adapters.out.skill.inproc as inproc_mod

    inproc_mod._skill_adapter_singleton = None


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    skills = tmp_path / "skills"
    skills.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(skills))
    # 隔离真实 DB 里的 skills_dir preference: 它优先级高于 env, 若用户在本机
    # 配过自定义目录, 导入会写进真实技能树、加载器也会扫到真实目录。
    # 置 None → 导入端回退到 SAGE_SKILLS_DIR, 加载端回退到同一目录。
    monkeypatch.setattr(
        "backend.skills.skill_md.importer.read_skills_dir_preference",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.skills.skill_md.loader.read_skills_dir_preference",
        lambda *args, **kwargs: None,
    )
    _reset_skill_adapter_singleton()
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


# ===== POST /skills/import-directory =====


def test_post_skills_import_directory_round_trip(
    client: TestClient, tmp_path: Path
) -> None:
    """目录导入 → 入口文件 + 附属资源落盘，且技能出现在 GET /skills。"""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("SKILL.md", _md("dir-skill"), "text/markdown")),
        ("files", ("scripts/scan.py", b"print('hi')\n", "text/x-python")),
        ("files", ("assets/tpl.html", b"<p>tpl</p>", "text/html")),
    ]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == [{"name": "dir-skill", "path": "."}]
    assert body["skipped"] == []

    skill_dir = tmp_path / "skills" / "dir-skill"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "scripts" / "scan.py").read_bytes() == b"print('hi')\n"
    assert (skill_dir / "assets" / "tpl.html").read_bytes() == b"<p>tpl</p>"

    names = [s["name"] for s in client.get("/api/v1/skills").json()]
    assert "dir-skill" in names


def test_post_skills_import_directory_no_files_returns_400(client: TestClient) -> None:
    """空 multipart → 400 invalid_request。"""
    _reset_skill_adapter_singleton()

    resp = client.post("/api/v1/skills/import-directory", files={})

    assert resp.status_code == 400
    assert resp.json()["detail"]["type"] == "invalid_request"


def test_post_skills_import_directory_missing_skill_md_returns_400(
    client: TestClient,
) -> None:
    """目录缺 SKILL.md → 400 missing_skill_md。"""
    _reset_skill_adapter_singleton()

    files = [("files", ("scripts/scan.py", b"print('hi')\n", "text/x-python"))]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["type"] == "missing_skill_md"


def test_post_skills_import_directory_invalid_entry_returns_400(
    client: TestClient,
) -> None:
    """SKILL.md 无法解析 → 400 parse_error。"""
    _reset_skill_adapter_singleton()

    files = [("files", ("SKILL.md", b"no frontmatter", "text/markdown"))]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["type"] == "parse_error"


def test_post_skills_import_directory_invalid_name_returns_400(
    client: TestClient,
) -> None:
    """SKILL.md 的 name 非法 → 400 invalid_name。"""
    _reset_skill_adapter_singleton()

    content = b"---\nname: Bad Name\ndescription: x\n---\nbody"
    files = [("files", ("SKILL.md", content, "text/markdown"))]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["type"] == "invalid_name"


def test_post_skills_import_directory_reports_skipped_resources(
    client: TestClient,
) -> None:
    """非白名单目录的资源在 skipped 中报告，导入仍成功。"""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("SKILL.md", _md("mixed-skill"), "text/markdown")),
        ("files", ("docs/readme.md", b"docs", "text/markdown")),
    ]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == [{"name": "mixed-skill", "path": "."}]
    assert {"name": "docs/readme.md", "reason": "resource_dir_not_allowed"} in body["skipped"]


def test_post_skills_import_directory_rejects_path_traversal(
    client: TestClient, tmp_path: Path
) -> None:
    """路径穿越文件名被跳过，不写到 skills_dir 之外。"""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("SKILL.md", _md("guard-skill"), "text/markdown")),
        ("files", ("../escape.py", b"payload", "text/x-python")),
    ]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == [{"name": "guard-skill", "path": "."}]
    assert any(item["reason"] == "invalid_path" for item in body["skipped"])
    assert not (tmp_path / "escape.py").exists()


def test_post_skills_import_directory_response_never_leaks_abs_path(
    client: TestClient, tmp_path: Path
) -> None:
    """响应体不含本机绝对路径。"""
    _reset_skill_adapter_singleton()

    files = [
        ("files", ("SKILL.md", _md("leak-check"), "text/markdown")),
        ("files", ("docs/readme.md", b"docs", "text/markdown")),
    ]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 200
    assert str(tmp_path / "skills") not in resp.text


def test_post_skills_import_directory_skips_existing_skill(
    client: TestClient, tmp_path: Path
) -> None:
    """同名技能已存在 → 跳过，不覆盖磁盘。

    adapter 初始化时会把 skills_dir 下的 SKILL.md 扫进 registry，import_directory
    先查 registry 再查磁盘，所以走 HTTP 路径命中的是 ``builtin_conflict``
    （纯磁盘重复、registry 未登记的 ``already_exists`` 由单测覆盖）。
    """
    skills = tmp_path / "skills"
    (skills / "dup-skill").mkdir()
    (skills / "dup-skill" / "SKILL.md").write_bytes(_md("dup-skill"))
    _reset_skill_adapter_singleton()

    files = [("files", ("SKILL.md", _md("dup-skill"), "text/markdown"))]
    resp = client.post("/api/v1/skills/import-directory", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == []
    assert body["skipped"] == [{"name": "dup-skill", "reason": "builtin_conflict"}]
    # 磁盘内容未被覆盖
    assert (skills / "dup-skill" / "SKILL.md").read_bytes() == _md("dup-skill")
