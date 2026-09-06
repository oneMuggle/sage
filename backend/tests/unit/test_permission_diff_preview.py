"""U15 写类工具审批 diff 预览单元测试。

覆盖 build_diff_preview 三工具语义 + ApprovalRequest.create 集成:
- write_file: 现文件 diff / 新文件全加 diff / 参数缺失 → None
- edit_file: old→new 单次替换 / 目标不存在 → None
- apply_patch: 多文件拼接 / replace_all
- 截断: 超过 DIFF_PREVIEW_MAX_CHARS 尾部截断
- create(): diff_preview 进实例; to_dict 仅在非空时下发
"""

from __future__ import annotations

import json

import pytest

from backend.services.permission_gate import (
    DIFF_PREVIEW_MAX_CHARS,
    ApprovalRequest,
    build_diff_preview,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (ws / "b.txt").write_text("hello\n", encoding="utf-8")
    return ws


class TestWriteFile:
    def test_existing_file_diff(self, workspace):
        preview = build_diff_preview(
            "write_file",
            {"path": "a.py", "content": "line1\nCHANGED\nline3\n"},
            str(workspace),
        )
        assert preview is not None
        assert "-line2" in preview
        assert "+CHANGED" in preview
        assert preview.startswith("---")

    def test_new_file_all_additions(self, workspace):
        preview = build_diff_preview(
            "write_file",
            {"path": "new.py", "content": "x = 1\n"},
            str(workspace),
        )
        assert preview is not None
        assert "+x = 1" in preview

    def test_missing_content_returns_none(self, workspace):
        assert build_diff_preview("write_file", {"path": "a.py"}, str(workspace)) is None


class TestEditFile:
    def test_single_replace(self, workspace):
        preview = build_diff_preview(
            "edit_file",
            {"file_path": "a.py", "old_string": "line2", "new_string": "LINE2"},
            str(workspace),
        )
        assert preview is not None
        assert "-line2" in preview
        assert "+LINE2" in preview

    def test_missing_target_returns_none(self, workspace):
        preview = build_diff_preview(
            "edit_file",
            {"file_path": "ghost.py", "old_string": "a", "new_string": "b"},
            str(workspace),
        )
        assert preview is None

    def test_absolute_path_without_workspace(self, workspace):
        preview = build_diff_preview(
            "edit_file",
            {"file_path": str(workspace / "a.py"), "old_string": "line3", "new_string": "line3 # ok"},
        )
        assert preview is not None
        assert "+line3 # ok" in preview


class TestApplyPatch:
    def test_multi_file_joined(self, workspace):
        preview = build_diff_preview(
            "apply_patch",
            {
                "patches": [
                    {"file_path": "a.py", "old_string": "line1", "new_string": "LINE1"},
                    {"file_path": "b.txt", "old_string": "hello", "new_string": "world"},
                ]
            },
            str(workspace),
        )
        assert preview is not None
        assert "a/+" not in preview
        assert "-line1" in preview
        assert "+LINE1" in preview
        assert "-hello" in preview
        assert "+world" in preview

    def test_replace_all(self, workspace):
        (workspace / "c.md").write_text("dup\ndup\n", encoding="utf-8")
        preview = build_diff_preview(
            "apply_patch",
            {
                "patches": [
                    {"file_path": "c.md", "old_string": "dup", "new_string": "UNIQUE", "replace_all": True}
                ]
            },
            str(workspace),
        )
        assert preview is not None
        assert preview.count("+UNIQUE") == 2

    def test_no_patches_returns_none(self, workspace):
        assert build_diff_preview("apply_patch", {"patches": []}, str(workspace)) is None
        assert build_diff_preview("apply_patch", {}, str(workspace)) is None


class TestLimits:
    def test_truncation(self, workspace):
        big = "x" * (DIFF_PREVIEW_MAX_CHARS + 2000)
        preview = build_diff_preview(
            "write_file",
            {"path": "big.txt", "content": big + "\n"},
            str(workspace),
        )
        assert preview is not None
        assert len(preview) <= DIFF_PREVIEW_MAX_CHARS + 40
        assert "已截断" in preview

    def test_non_write_tool_returns_none(self, workspace):
        assert build_diff_preview("bash", {"command": "ls"}, str(workspace)) is None
        assert build_diff_preview("read_file", {"path": "a.py"}, str(workspace)) is None


class TestApprovalRequestIntegration:
    def test_create_includes_preview_and_dict(self, workspace):
        req = ApprovalRequest.create(
            tool_name="write_file",
            args={"path": "a.py", "content": "changed\n"},
            risk="safe",
            message="写文件",
            workspace_root=str(workspace),
        )
        assert req.diff_preview is not None
        payload = req.to_dict()
        assert "diff_preview" in payload
        assert "-line1" in payload["diff_preview"] or "+changed" in payload["diff_preview"]

    def test_to_dict_omits_empty_preview(self):
        req = ApprovalRequest.create(
            tool_name="bash",
            args={"command": "echo hi"},
            risk="safe",
            message="跑命令",
        )
        assert req.diff_preview is None
        assert "diff_preview" not in req.to_dict()

    def test_summary_still_scrubbed(self, workspace):
        req = ApprovalRequest.create(
            tool_name="edit_file",
            args={"file_path": "a.py", "old_string": "line2", "new_string": "X", "api_key": "sk-secret"},
            risk="safe",
            message="编辑",
            workspace_root=str(workspace),
        )
        # args_summary 照旧脱敏 api_key; diff 只含文件内容
        assert "sk-secret" not in req.args_summary
        assert json.loads(req.args_summary)["api_key"] == "***"
        assert req.diff_preview is not None
        assert "sk-secret" not in req.diff_preview
