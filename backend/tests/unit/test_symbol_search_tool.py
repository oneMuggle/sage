"""symbol_search 工具单元测试（G4 符号索引务实版）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.symbol_search_tool import SymbolSearchTool, _tokenize

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def codebase(tmp_path: Path) -> Path:
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "auth.py").write_text(
        "class LoginManager:\n"
        "    def validate_password(self, pwd: str) -> bool:\n"
        "        return bool(pwd)\n"
        "\n"
        "def create_user_session(user_id: int) -> str:\n"
        "    return f'sess-{user_id}'\n",
        encoding="utf-8",
    )
    (ws / "storage.py").write_text(
        "def save_checkpoint(state: dict) -> None:\n"
        "    pass\n"
        "\n"
        "def killProcessTree(pid: int) -> None:  # camelCase\n"
        "    pass\n",
        encoding="utf-8",
    )
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "junk.py").write_text("def noisy_symbol(): pass\n", encoding="utf-8")
    (ws / "broken.py").write_text("def broken(:\n", encoding="utf-8")  # 语法坏 → 跳过
    return ws


def _tool(ws: Path) -> SymbolSearchTool:
    return SymbolSearchTool(policy=ToolPolicy(workspace_root=str(ws)))


def test_exact_name_match(codebase):
    result = _tool(codebase).execute(query="save_checkpoint")
    assert result.success is True
    assert result.content["matches"][0]["path"] == "storage.py"
    assert result.content["matches"][0]["line"] == 1
    assert result.content["matches"][0]["kind"] == "function"


def test_concept_tokens_match_camel_and_snake(codebase):
    """分词 AND 匹配：'kill process' 命中 camelCase 的 killProcessTree。"""
    result = _tool(codebase).execute(query="kill process")
    names = [m["name"] for m in result.content["matches"]]
    assert "killProcessTree" in names


def test_prefix_and_substring_ranking(codebase):
    result = _tool(codebase).execute(query="login")
    assert result.content["matches"][0]["name"] == "LoginManager"

    result = _tool(codebase).execute(query="session")
    names = [m["name"] for m in result.content["matches"]]
    assert "create_user_session" in names


def test_methods_extracted_with_owner_prefix(codebase):
    result = _tool(codebase).execute(query="validate_password")
    match = result.content["matches"][0]
    assert match["name"] == "LoginManager.validate_password"
    assert match["kind"] == "method"


def test_excludes_vendor_and_broken_files(codebase):
    result = _tool(codebase).execute(query="noisy")
    assert result.content["matches"] == []  # node_modules 被排除

    result = _tool(codebase).execute(query="broken")
    assert result.content["matches"] == []  # 语法坏文件跳过不炸


def test_no_match_and_validation(codebase):
    result = _tool(codebase).execute(query="zzz_nonexistent")
    assert result.success is True
    assert result.content["matches"] == []
    assert result.content["total"] == 0

    tool = _tool(codebase)
    assert tool.execute(query="").success is False
    assert tool.execute().success is False
    assert tool.execute(query="x", bogus=1).success is False


def test_tokenizer_splits_camel_and_snake():
    assert _tokenize("killProcessTree") == ["kill", "process", "tree"]
    assert "checkpoint" in _tokenize("save_checkpoint")
