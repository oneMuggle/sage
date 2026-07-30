"""A17 — Code Diff Visualization 单元测试。

覆盖:
- ``backend.application.services.code_diff`` 纯函数(unified diff 生成 /
  变更统计 / metadata 构建 / 三级大小护栏)
- ``WriteFileTool`` / ``EditTool`` 写前写后捕获并挂 ``metadata['code_diff']``
- ``tool_result_display_content`` OBSERVING 展示层注入(LLM 上下文隔离)
- ``InprocToolAdapter`` metadata 透传到域 ``ToolResult``
"""

from __future__ import annotations

import json

import pytest

from backend.application.services import code_diff as cd
from backend.application.services.code_diff import (
    MAX_CAPTURE_BYTES,
    MAX_DIFF_CONTENT_BYTES,
    MAX_UNIFIED_DIFF_BYTES,
    build_code_diff_metadata,
    count_changes,
    generate_unified_diff,
    should_skip_capture,
)
from backend.core.legacy.agent import tool_result_display_content
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import WriteFileTool

pytestmark = pytest.mark.unit


# ============================================================================
# 1) code_diff 纯函数
# ============================================================================


class TestGenerateUnifiedDiff:
    def test_git_style_headers_and_hunk(self):
        """unified diff 采用 a/ b/ 头 + @@ hunk,与 git diff 同构。"""
        diff = generate_unified_diff("src/a.py", "x = 1\n", "x = 2\n")
        assert "--- a/src/a.py" in diff
        assert "+++ b/src/a.py" in diff
        assert "@@" in diff
        assert "-x = 1" in diff
        assert "+x = 2" in diff

    def test_new_file_produces_additions_only(self):
        diff = generate_unified_diff("new.txt", "", "hello\n")
        assert "+hello" in diff
        # 无删除行(排除 --- 文件头;@@ -0,0 +1 @@ hunk 头不算)
        removed = [
            line
            for line in diff.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        assert removed == []


class TestCountChanges:
    def test_counts_plus_minus_and_skips_file_headers(self):
        diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,1 @@\n-a\n-b\n+c\n"
        additions, deletions = count_changes(diff)
        assert additions == 1
        assert deletions == 2


class TestShouldSkipCapture:
    def test_boundary(self):
        assert should_skip_capture(MAX_CAPTURE_BYTES) is False
        assert should_skip_capture(MAX_CAPTURE_BYTES + 1) is True


class TestBuildCodeDiffMetadata:
    def test_no_change_returns_none(self):
        assert build_code_diff_metadata("f.py", "same\n", "same\n") is None

    def test_edit_metadata_shape(self):
        meta = build_code_diff_metadata("/w/f.py", "a = 1\n", "a = 2\n")
        assert meta is not None
        assert meta["path"] == "/w/f.py"
        assert meta["is_new_file"] is False
        assert meta["additions"] == 1
        assert meta["deletions"] == 1
        assert "-a = 1" in meta["unified_diff"]
        assert "+a = 2" in meta["unified_diff"]
        # 双侧均小于 64 KB → 全文随 metadata 下发(前端高亮渲染用)
        assert meta["old_content"] == "a = 1\n"
        assert meta["new_content"] == "a = 2\n"

    def test_new_file_flag(self):
        meta = build_code_diff_metadata("/w/f.py", "", "print('hi')\n", is_new_file=True)
        assert meta is not None
        assert meta["is_new_file"] is True

    def test_content_omitted_when_one_side_oversized(self):
        """old/new 任一侧超 MAX_DIFF_CONTENT_BYTES → 省略全文,降级数据仍在。"""
        big = "x" * (MAX_DIFF_CONTENT_BYTES + 1)
        meta = build_code_diff_metadata("/w/big.txt", big, big + "tail")
        assert meta is not None
        assert "old_content" not in meta
        assert "new_content" not in meta
        assert meta["unified_diff"]
        assert meta["additions"] >= 1

    def test_huge_diff_is_truncated_and_flagged(self):
        old = "\n".join(f"line{i}" for i in range(5000))
        new = "\n".join(f"row{i}" for i in range(5000))
        meta = build_code_diff_metadata("/w/big.txt", old, new)
        assert meta is not None
        assert meta["diff_truncated"] is True
        assert len(meta["unified_diff"].encode("utf-8")) <= MAX_UNIFIED_DIFF_BYTES


# ============================================================================
# 2) WriteFileTool — code_diff metadata 捕获
# ============================================================================


class TestWriteFileToolCodeDiff:
    def test_new_file_attaches_diff(self, tmp_path):
        target = tmp_path / "hello.py"
        result = WriteFileTool().execute(path=str(target), content="print('hi')\n")

        assert result.success is True
        assert result.metadata is not None
        diff = result.metadata["code_diff"]
        assert diff["is_new_file"] is True
        assert diff["additions"] == 1
        assert diff["deletions"] == 0
        assert "+print('hi')" in diff["unified_diff"]
        assert diff["old_content"] == ""
        assert diff["new_content"] == "print('hi')\n"

    def test_overwrite_attaches_diff(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("alpha\nbeta\n", encoding="utf-8")

        result = WriteFileTool().execute(path=str(target), content="alpha\ngamma\n")

        diff = result.metadata["code_diff"]
        assert diff["is_new_file"] is False
        assert diff["additions"] == 1
        assert diff["deletions"] == 1
        assert "-beta" in diff["unified_diff"]
        assert "+gamma" in diff["unified_diff"]

    def test_identical_content_no_metadata(self, tmp_path):
        """内容未变 → 不挂 metadata(前端不渲染空 diff)。"""
        target = tmp_path / "same.txt"
        target.write_text("unchanged\n", encoding="utf-8")

        result = WriteFileTool().execute(path=str(target), content="unchanged\n")

        assert result.success is True
        assert result.metadata is None

    def test_append_diff_shows_only_appended_lines(self, tmp_path):
        target = tmp_path / "log.txt"
        target.write_text("line1\n", encoding="utf-8")

        result = WriteFileTool().execute(
            path=str(target), content="line2\n", append=True
        )

        diff = result.metadata["code_diff"]
        assert diff["additions"] == 1
        assert diff["deletions"] == 0
        assert "+line2" in diff["unified_diff"]
        assert target.read_text(encoding="utf-8") == "line1\nline2\n"

    def test_binary_file_skips_diff_but_write_succeeds(self, tmp_path):
        """二进制旧文件 → 跳过 diff 捕获,写入本身不受影响。"""
        target = tmp_path / "blob.bin"
        target.write_bytes(b"\x00\x01\x02binary")

        result = WriteFileTool().execute(path=str(target), content="text now\n")

        assert result.success is True
        assert result.metadata is None
        assert target.read_text(encoding="utf-8") == "text now\n"

    def test_oversized_old_file_skips_capture(self, tmp_path, monkeypatch):
        """旧文件超 MAX_CAPTURE_BYTES → 跳过捕获,写入成功。"""
        monkeypatch.setattr(cd, "MAX_CAPTURE_BYTES", 10)
        target = tmp_path / "big.txt"
        target.write_text("x" * 100, encoding="utf-8")

        result = WriteFileTool().execute(path=str(target), content="small\n")

        assert result.success is True
        assert result.metadata is None


# ============================================================================
# 3) EditTool — code_diff metadata 捕获
# ============================================================================


class TestEditToolCodeDiff:
    def test_edit_attaches_diff(self, tmp_path):
        target = tmp_path / "code.py"
        target.write_text("def f():\n    return 1\n", encoding="utf-8")

        result = EditTool().execute(
            file_path=str(target), old_string="return 1", new_string="return 2"
        )

        assert result.success is True
        assert result.metadata is not None
        diff = result.metadata["code_diff"]
        assert diff["is_new_file"] is False
        assert diff["additions"] == 1
        assert diff["deletions"] == 1
        assert "-    return 1" in diff["unified_diff"]
        assert "+    return 2" in diff["unified_diff"]
        assert diff["old_content"] == "def f():\n    return 1\n"
        assert diff["new_content"] == "def f():\n    return 2\n"

    def test_edit_failure_has_no_metadata(self, tmp_path):
        target = tmp_path / "code.py"
        target.write_text("alpha\n", encoding="utf-8")

        result = EditTool().execute(
            file_path=str(target), old_string="NOT FOUND", new_string="x"
        )

        assert result.success is False
        assert result.metadata is None


# ============================================================================
# 4) tool_result_display_content — OBSERVING 展示层注入
# ============================================================================


class TestToolResultDisplayContent:
    def test_empty_metadata_passthrough(self):
        assert tool_result_display_content('{"a": 1}', None) == '{"a": 1}'
        assert tool_result_display_content("plain text", {}) == "plain text"

    def test_dict_content_gets_metadata_injected(self):
        out = tool_result_display_content(
            json.dumps({"path": "/f"}), {"code_diff": {"additions": 1}}
        )
        parsed = json.loads(out)
        assert parsed["path"] == "/f"
        assert parsed["metadata"]["code_diff"]["additions"] == 1

    def test_existing_metadata_is_shallow_merged(self):
        """工具 content 自带 metadata(如 MCP imageData)→ 浅合并而非覆盖。"""
        out = tool_result_display_content(
            json.dumps({"text": "ok", "metadata": {"imageData": "data:x"}}),
            {"code_diff": {"path": "/f"}},
        )
        parsed = json.loads(out)
        assert parsed["metadata"]["imageData"] == "data:x"
        assert parsed["metadata"]["code_diff"]["path"] == "/f"

    def test_non_json_string_is_wrapped(self):
        out = tool_result_display_content("权限拒绝: denied", {"code_diff": {}})
        parsed = json.loads(out)
        assert parsed["text"] == "权限拒绝: denied"
        assert parsed["metadata"] == {"code_diff": {}}

    def test_json_array_is_wrapped(self):
        out = tool_result_display_content("[1, 2]", {"m": 1})
        parsed = json.loads(out)
        assert parsed["text"] == "[1, 2]"
        assert parsed["metadata"] == {"m": 1}


# ============================================================================
# 5) InprocToolAdapter — metadata 透传到域 ToolResult
# ============================================================================


class _AllowAllEnforcer:
    """全放行 enforcer 桩:隔离权限逻辑,只测 metadata 透传。"""

    def check(self, tool_name, args=None):
        from backend.tools.permissions import PermissionDecision

        return PermissionDecision(allowed=True, needs_approval=False, reason="test")


class TestInprocAdapterMetadataPropagation:
    async def test_code_diff_reaches_domain_result(self, tmp_path):
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
        from backend.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(WriteFileTool())
        adapter = InprocToolAdapter(
            registry=registry, enforcer_factory=_AllowAllEnforcer
        )

        target = tmp_path / "out.py"
        result = await adapter.execute(
            "write_file", {"path": str(target), "content": "x = 1\n"}
        )

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata["code_diff"]["is_new_file"] is True
        assert result.metadata["code_diff"]["additions"] == 1

    async def test_truncation_meta_merges_with_tool_meta(self, tmp_path):
        """output 截断标记与工具 metadata 合并(截断标记优先)。"""
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
        from backend.domain.tool_policy import ToolPolicy
        from backend.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(WriteFileTool())
        adapter = InprocToolAdapter(
            registry=registry,
            policy=ToolPolicy(max_output_bytes=10),
            enforcer_factory=_AllowAllEnforcer,
        )

        target = tmp_path / "out.txt"
        result = await adapter.execute(
            "write_file", {"path": str(target), "content": "payload\n"}
        )

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata["truncated"] is True
        assert result.metadata["code_diff"]["additions"] == 1
