"""设计产物桥接到 artifacts 表的测试"""
from unittest.mock import MagicMock, patch


def test_design_generate_records_artifact():
    """design_generate 工具应在生成后桥接到 artifacts 表"""
    from backend.tools.design_generate_tool import DesignGenerateTool

    mock_artifact = MagicMock()
    mock_artifact.id = "design_art_123"
    mock_artifact.version = 1
    mock_artifact.title = "Test Design"
    mock_artifact.file_path = "/workspace/design/proj/v1.html"
    mock_artifact.html_content = "<html>test</html>"

    mock_project = MagicMock()
    mock_project.id = "proj_123"
    mock_project.name = "Test Project"

    mock_studio = MagicMock()
    mock_studio.create_project.return_value = mock_project

    # Async mock for generate
    async def mock_generate(project_id):
        return mock_artifact
    mock_studio.generate.side_effect = mock_generate

    tool = DesignGenerateTool()

    with patch("backend.tools.design_generate_tool.get_design_studio", return_value=mock_studio), \
         patch("backend.tools.design_generate_tool._record_artifact_safely") as mock_record, \
         patch("backend.tools.design_generate_tool.current_tool_context") as mock_ctx:

        mock_ctx_instance = MagicMock()
        mock_ctx_instance.session_id = "sess_123"
        mock_ctx.return_value = mock_ctx_instance

        result = tool.execute(
            name="Test",
            kind="web",
            system_id="sys_1",
            template_id="tpl_1",
            brief="Test brief",
        )

    assert result.success is True
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["resolved_path"] == "/workspace/design/proj/v1.html"
    assert call_kwargs["size"] == len(b"<html>test</html>")
