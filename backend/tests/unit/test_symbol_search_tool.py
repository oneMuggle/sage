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


def test_js_ts_symbols_discovered_and_ranked(tmp_path):
    """F-3 (round5 批次 F): JS/TS 定义走行级提取, 与 Python 符号合并且命中。"""
    (tmp_path / "service.ts").write_text(
        "export function createCheckpointService() {\n"
        "  return {}\n"
        "}\n"
        "export interface CheckpointOptions {\n"
        "  keepCount: number\n"
        "}\n"
        "export const reloadCheckpoints = async () => {\n"
        "  return true\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "plain.py").write_text("def unrelated_helper():\n    pass\n", encoding="utf-8")

    tool = SymbolSearchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    result = tool.execute(query="checkpoint")
    assert result.success is True
    names = [m["name"] for m in result.content["matches"]]
    assert "createCheckpointService" in names
    assert "CheckpointOptions" in names
    assert "reloadCheckpoints" in names
    assert all("service.ts" in m["path"] for m in result.content["matches"])
    assert "unrelated_helper" not in names


# ==================== H-1/H-2 (round5 批次 H): 持久化缓存 + 语言扩展 ====================


def test_h1_incremental_second_query_uses_cache(tmp_path):
    """H-1: 首扫建缓存；二次查询走缓存（reindexed=0）且结果一致。"""
    (tmp_path / "svc.py").write_text("def make_tea():\n    pass\n", encoding="utf-8")
    tool = SymbolSearchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))

    first = tool.execute(query="make_tea")
    assert first.success is True
    assert first.content["cached"] is True
    assert first.content["scanned_files"] >= 1  # 首扫有重析

    second = tool.execute(query="make_tea")
    assert second.content["cached"] is True
    assert second.content["scanned_files"] == 0  # 未变文件零重析
    assert [m["name"] for m in second.content["matches"]] == ["make_tea"]


def test_h1_reindexes_changed_file_and_cleans_gone(tmp_path):
    (tmp_path / "svc.py").write_text("def make_tea():\n    pass\n", encoding="utf-8")
    (tmp_path / "old.py").write_text("def make_coffee():\n    pass\n", encoding="utf-8")
    tool = SymbolSearchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    tool.execute(query="make")

    # 改 svc.py、删 old.py
    (tmp_path / "svc.py").write_text("def make_latte():\n    pass\n", encoding="utf-8")
    (tmp_path / "old.py").unlink()

    second = tool.execute(query="make")
    names = [m["name"] for m in second.content["matches"]]
    assert "make_latte" in names
    assert "make_coffee" not in names
    assert second.content["scanned_files"] == 1  # 只重析了 svc.py


def test_h2_go_rust_java_symbols_discovered(tmp_path):
    (tmp_path / "server.go").write_text(
        "package main\n"
        "\n"
        "func StartServer(port int) {\n"
        "}\n"
        "\n"
        "type ServerConfig struct {\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "cache.rs").write_text(
        "pub struct CacheStore;\n"
        "\n"
        "impl CacheStore {\n"
        "}\n"
        "\n"
        "pub fn clear_cache() {\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "Repo.java").write_text(
        "public class UserRepository {\n"
        "    public User findById(long id) {\n"
        "        return null;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    tool = SymbolSearchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))

    go = tool.execute(query="startserver")
    assert [m["name"] for m in go.content["matches"]] == ["StartServer"]
    rs = tool.execute(query="clear_cache")
    # 精确命中排第一（CacheStore 因分词部分命中 cache 也会出现）
    assert rs.content["matches"][0]["name"] == "clear_cache"
    java = tool.execute(query="findbyid")
    assert [m["name"] for m in java.content["matches"]] == ["findById"]
