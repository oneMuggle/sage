"""子代理档案文件化（CA1-CA3, round9）— backend/agents/agents_files.py 单测。

覆盖:
- parse_agent_file：完整 frontmatter / 无 frontmatter / 未闭合 / 空正文 /
  id 清洗 / 非法字段
- import_agents_from_files：新导入 / 差异才 upsert / enabled 保留 DB 现值 /
  坏文件计 errors 不中断 / 目录不存在全空
- export_agent_to_file：roundtrip（导出 → 再解析等值）/ 404
"""

from __future__ import annotations

import pytest

from backend.agents.agents_files import (
    AgentsFileError,
    agents_dir,
    export_agent_to_file,
    import_agents_from_files,
    parse_agent_file,
    sanitize_agent_id,
)

pytestmark = pytest.mark.unit


_SAMPLE = """---
name: 审查员
role: researcher
description: 代码审查专家
tools: read_file, grep_file, list_dir
memory_access: working, semantic
max_iterations: 8
enabled: true
model: gpt-4o
temperature: 0.4
max_tokens: 8192
---

你是代码审查专家，逐行审查提交。
"""


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "agents-files.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


# ---- parse --------------------------------------------------------------------


def test_parse_full_frontmatter(tmp_path):
    path = tmp_path / "reviewer.md"
    path.write_text(_SAMPLE, encoding="utf-8")
    profile = parse_agent_file(path)
    assert profile["id"] == "reviewer"
    assert profile["name"] == "审查员"
    assert profile["tools"] == ["read_file", "grep_file", "list_dir"]
    assert profile["memory_access"] == ["working", "semantic"]
    assert profile["max_iterations"] == 8
    assert profile["enabled"] is True
    assert profile["model_config"]["model"] == "gpt-4o"
    assert profile["model_config"]["temperature"] == 0.4
    assert "逐行审查提交" in profile["system_prompt"]


def test_parse_without_frontmatter_body_is_prompt(tmp_path):
    path = tmp_path / "helper.md"
    path.write_text("你是一个辅助 agent。", encoding="utf-8")
    profile = parse_agent_file(path)
    assert profile["id"] == "helper"
    assert profile["system_prompt"] == "你是一个辅助 agent。"
    assert profile["enabled"] is True


def test_parse_unclosed_frontmatter_raises(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("---\nname: x\n正文", encoding="utf-8")
    with pytest.raises(AgentsFileError):
        parse_agent_file(path)


def test_parse_empty_body_raises(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("---\nname: x\n---\n\n", encoding="utf-8")
    with pytest.raises(AgentsFileError):
        parse_agent_file(path)


def test_parse_invalid_field_raises(tmp_path):
    path = tmp_path / "badint.md"
    path.write_text("---\nmax_iterations: abc\n---\n正文", encoding="utf-8")
    with pytest.raises(AgentsFileError):
        parse_agent_file(path)


def test_sanitize_agent_id():
    assert sanitize_agent_id("My Agent!") == "my-agent"
    assert sanitize_agent_id("///") == "agent"
    assert sanitize_agent_id("Reviewer-2") == "reviewer-2"


def test_agents_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "custom"))
    assert agents_dir() == tmp_path / "custom"
    monkeypatch.delenv("SAGE_AGENTS_DIR")
    assert agents_dir().name == "agents"


# ---- import -------------------------------------------------------------------


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_import_new_and_modified_preserves_enabled(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "agents"))
    agents_md = tmp_path / "agents" / "reviewer.md"
    _write(agents_md, _SAMPLE)

    first = import_agents_from_files()
    assert first["imported"] == ["reviewer"]
    assert first["errors"] == []

    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    repo.set_enabled("reviewer", False)  # 用户关掉开关

    # 内容不变 → unchanged；改 system_prompt → 重导入但 enabled 仍保留 False
    again = import_agents_from_files()
    assert again["imported"] == []
    assert again["unchanged"] == ["reviewer"]

    _write(agents_md, _SAMPLE.replace("逐行审查提交", "逐函数审查提交"))
    third = import_agents_from_files()
    assert third["imported"] == ["reviewer"]
    assert AgentRepository().get("reviewer")["enabled"] is False


def test_import_bad_file_counts_error_without_blocking(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "agents"))
    _write(tmp_path / "agents" / "bad.md", "---\nname: x\n未闭合")
    _write(tmp_path / "agents" / "good.md", _SAMPLE)

    result = import_agents_from_files()
    assert result["imported"] == ["good"]
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("bad.md:")


def test_import_missing_dir_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "nope"))
    result = import_agents_from_files()
    assert result == {"imported": [], "unchanged": [], "errors": []}


# ---- export -------------------------------------------------------------------


def test_export_roundtrip(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "agents"))
    _write(tmp_path / "agents" / "reviewer.md", _SAMPLE)
    import_agents_from_files()

    out = export_agent_to_file("reviewer", directory=tmp_path / "export")
    assert out.exists()
    reparsed = parse_agent_file(out)
    assert reparsed["name"] == "审查员"
    assert reparsed["tools"] == ["read_file", "grep_file", "list_dir"]
    assert reparsed["max_iterations"] == 8
    assert "逐行审查提交" in reparsed["system_prompt"]


def test_export_unknown_agent_raises_lookup(tmp_path):
    with pytest.raises(LookupError):
        export_agent_to_file("nope", directory=tmp_path / "out")


# ---- 端点（RV 与 CA2 的 REST 面） ----------------------------------------------


@pytest.mark.asyncio()
async def test_endpoints_import_and_export(tmp_path, monkeypatch):
    """POST /agents/import-files 重扫导入；POST /agents/{id}/export 写文件。"""
    import httpx
    from httpx import ASGITransport

    from backend.main import app

    _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "agents"))
    _write(tmp_path / "agents" / "reviewer.md", _SAMPLE)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        imp = await client.post("/api/v1/agents/import-files")
        assert imp.status_code == 200
        assert imp.json()["imported"] == ["reviewer"]

        exp = await client.post("/api/v1/agents/reviewer/export")
        assert exp.status_code == 200
        assert exp.json()["ok"] is True

        missing = await client.post("/api/v1/agents/nope/export")
        assert missing.status_code == 404

    # 导出文件可再解析（roundtrip 闭环）
    reparsed = parse_agent_file(tmp_path / "agents" / "reviewer.md")
    assert reparsed["id"] == "reviewer"


# ---- doctor check（CA3） -------------------------------------------------------


def test_doctor_agents_files_check(tmp_path, monkeypatch):
    from backend.cli.checks.agents_files import AgentsFilesCheck
    from backend.cli.doctor import Severity

    monkeypatch.setenv("SAGE_AGENTS_DIR", str(tmp_path / "agents"))
    check = AgentsFilesCheck()

    # 目录不存在 → INFO
    result = check.run()
    assert result.severity is Severity.INFO

    # 结构正常 → INFO（parsed 计数）
    _write(tmp_path / "agents" / "ok.md", _SAMPLE)
    result = check.run()
    assert result.severity is Severity.INFO
    assert "1 个档案文件结构正常" in result.message

    # 坏文件 → WARN（前 3 条进消息）
    _write(tmp_path / "agents" / "bad.md", "---\nname: x\n未闭合")
    result = check.run()
    assert result.severity is Severity.WARN
    assert "bad.md" in result.message
