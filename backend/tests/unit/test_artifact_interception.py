# backend/tests/unit/test_artifact_interception.py
from backend.data import artifact_repo
from backend.tools import file_tool
from backend.tools.context import ToolExecutionContext, reset_tool_context, set_tool_context


def test_detect_artifact_kind():
    assert file_tool.detect_artifact_kind("a.md") == "markdown"
    assert file_tool.detect_artifact_kind("a.py") == "code"
    assert file_tool.detect_artifact_kind("a.png") == "image"
    assert file_tool.detect_artifact_kind("a.csv") == "csv"
    assert file_tool.detect_artifact_kind("a.json") == "code"
    assert file_tool.detect_artifact_kind("a.unknown") == "text"


def test_write_file_records_artifact(tmp_path):
    from backend.tools.file_tool import WriteFileTool

    target = tmp_path / "out.md"
    tool = WriteFileTool()  # 无 policy => 跳过 workspace 边界检查

    ctx = ToolExecutionContext(
        session_id="sess_intercept",
        stream_id="stream_1",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )
    token = set_tool_context(ctx)
    try:
        result = tool.execute(path=str(target), content="# Hi")
    finally:
        reset_tool_context(token)

    assert result.success is True
    artifacts = artifact_repo.list_artifacts("sess_intercept")
    assert len(artifacts) == 1
    assert artifacts[0].name == "out.md"
    assert artifacts[0].kind == "markdown"


def test_write_file_without_context_does_not_record(tmp_path):
    from backend.tools.file_tool import WriteFileTool

    target = tmp_path / "no_ctx.md"
    tool = WriteFileTool()
    result = tool.execute(path=str(target), content="x")

    assert result.success is True
    # 无上下文时不记录(任何 session 都没有该产物)
    assert artifact_repo.list_artifacts("sess_none") == []
