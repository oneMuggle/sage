"""Tests for design studio tools (Task 13)."""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.data.design_repo import DesignRepo
from backend.design import init_design_studio
from backend.design.async_bridge import run_sync
from backend.design.design_studio import DesignStudio
from backend.design.generator import DesignGenerator
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry
from backend.tools.design_export_tool import DesignExportTool
from backend.tools.design_generate_tool import DesignGenerateTool
from backend.tools.design_iterate_tool import DesignIterateTool
from backend.tools.design_list_systems_tool import DesignListSystemsTool
from backend.tools.design_list_templates_tool import DesignListTemplatesTool


@pytest.fixture()
def mock_design_studio(tmp_path):
    """Create a mock DesignStudio for testing."""
    # Create mock dependencies
    mock_repo = MagicMock(spec=DesignRepo)
    mock_generator = MagicMock(spec=DesignGenerator)
    mock_generator.generate = AsyncMock()

    # Create mock systems and templates registries
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    systems_dir = content_dir / "systems"
    systems_dir.mkdir()
    templates_dir = content_dir / "templates"
    templates_dir.mkdir()

    mock_systems = MagicMock(spec=DesignSystemRegistry)
    mock_templates = MagicMock(spec=DesignTemplateRegistry)

    # Create a mock design system
    from backend.design.models import DesignSystem
    mock_system = DesignSystem(
        id="test-system",
        name="Test System",
        description="A test design system",
        category="test",
        design_md="# Test System",
        tokens_css="/* test css */",
        design_tokens={},
        tags=[],
    )
    mock_systems.list_systems.return_value = [mock_system]
    mock_systems.get_system.return_value = mock_system

    # Create a mock design template
    from backend.design.models import DesignTemplate
    mock_template = DesignTemplate(
        id="test-template",
        name="Test Template",
        kind="prototype",
        description="A test template",
        skill_md="# Test Template",
        design_system_required=False,
        assets={},
    )
    mock_templates.list_templates.return_value = [mock_template]
    mock_templates.get_template.return_value = mock_template

    # Create a mock project
    from datetime import datetime, timezone

    from backend.design.models import DesignProject
    mock_project = DesignProject(
        id="test-project-id",
        name="Test Project",
        kind="prototype",
        system_id="test-system",
        template_id="test-template",
        brief="Test brief",
        status="draft",
        created_at=datetime.now(timezone.utc),  # noqa: UP017
        updated_at=datetime.now(timezone.utc),  # noqa: UP017
    )
    mock_repo.create_project.return_value = mock_project
    mock_repo.get_project.return_value = mock_project

    # Create a mock artifact
    from backend.design.models import DesignArtifact
    mock_artifact = DesignArtifact(
        id="test-artifact-id",
        project_id="test-project-id",
        version=1,
        html_content="<html><body>Test</body></html>",
        css_injected="",
        title="Test Artifact",
        file_path="/tmp/test.html",
        kind="html",
        export_formats=["html"],
        source_prompt="Test prompt",
        created_at=datetime.now(timezone.utc),  # noqa: UP017
    )
    mock_repo.get_latest_artifact.return_value = mock_artifact

    # Mock the generate result
    from backend.design.artifact_parser import ParsedArtifact
    from backend.design.generator import GenerationResult
    mock_result = GenerationResult(
        parsed=ParsedArtifact(
            identifier="test-artifact",
            type="html",
            title="Generated Artifact",
            html_content="<html><body>Generated</body></html>",
        ),
        bundled_html="<html><body>Generated</body></html>",
        source_prompt="Test prompt",
    )
    mock_generator.generate.return_value = mock_result

    # Create the studio
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    studio = DesignStudio(
        repo=mock_repo,
        generator=mock_generator,
        systems=mock_systems,
        templates=mock_templates,
        workspace_dir=workspace_dir,
    )

    # Initialize the global design studio
    init_design_studio(studio)

    yield studio

    # Clean up
    init_design_studio(None)


def test_design_list_systems_schema():
    """Test DesignListSystemsTool schema."""
    tool = DesignListSystemsTool()
    schema = tool.schema
    assert schema.name == "design_list_systems"
    assert "design systems" in schema.description.lower()
    assert tool.risk.value == "read"


def test_design_list_systems_execute(mock_design_studio):
    """Test DesignListSystemsTool execute."""
    tool = DesignListSystemsTool()
    result = tool.execute()

    assert result.success is True
    assert "systems" in result.content
    assert len(result.content["systems"]) == 1
    assert result.content["systems"][0]["id"] == "test-system"
    assert result.content["systems"][0]["name"] == "Test System"


def test_design_list_templates_schema():
    """Test DesignListTemplatesTool schema."""
    tool = DesignListTemplatesTool()
    schema = tool.schema
    assert schema.name == "design_list_templates"
    assert "design templates" in schema.description.lower()
    assert tool.risk.value == "read"


def test_design_list_templates_execute(mock_design_studio):
    """Test DesignListTemplatesTool execute."""
    tool = DesignListTemplatesTool()
    result = tool.execute()

    assert result.success is True
    assert "templates" in result.content
    assert len(result.content["templates"]) == 1
    assert result.content["templates"][0]["id"] == "test-template"
    assert result.content["templates"][0]["name"] == "Test Template"


def test_design_generate_schema():
    """Test DesignGenerateTool schema."""
    tool = DesignGenerateTool()
    schema = tool.schema
    assert schema.name == "design_generate"
    assert "generate" in schema.description.lower()
    assert tool.risk.value == "write_local"
    assert "name" in schema.parameters["properties"]
    assert "kind" in schema.parameters["properties"]
    assert "system_id" in schema.parameters["properties"]
    assert "template_id" in schema.parameters["properties"]
    assert "brief" in schema.parameters["properties"]


def test_design_generate_execute(mock_design_studio):
    """Test DesignGenerateTool execute."""
    tool = DesignGenerateTool()
    result = tool.execute(
        name="Test Project",
        kind="prototype",
        system_id="test-system",
        template_id="test-template",
        brief="Test brief",
    )

    assert result.success is True
    assert "project_id" in result.content
    assert "artifact_id" in result.content
    assert result.content["project_name"] == "Test Project"


def test_design_generate_missing_params(mock_design_studio):
    """Test DesignGenerateTool with missing parameters."""
    tool = DesignGenerateTool()
    result = tool.execute(name="Test")

    assert result.success is False
    assert "missing_required_parameters" in result.error


def test_design_iterate_schema():
    """Test DesignIterateTool schema."""
    tool = DesignIterateTool()
    schema = tool.schema
    assert schema.name == "design_iterate"
    assert "iterate" in schema.description.lower()
    assert tool.risk.value == "write_local"
    assert "project_id" in schema.parameters["properties"]
    assert "feedback" in schema.parameters["properties"]


def test_design_iterate_execute(mock_design_studio):
    """Test DesignIterateTool execute."""
    tool = DesignIterateTool()
    result = tool.execute(
        project_id="test-project-id",
        feedback="Make it better",
    )

    assert result.success is True
    assert "project_id" in result.content
    assert "artifact_id" in result.content


def test_design_iterate_missing_params(mock_design_studio):
    """Test DesignIterateTool with missing parameters."""
    tool = DesignIterateTool()
    result = tool.execute(project_id="test-project-id")

    assert result.success is False
    assert "missing_required_parameters" in result.error


def test_design_export_schema():
    """Test DesignExportTool schema."""
    tool = DesignExportTool()
    schema = tool.schema
    assert schema.name == "design_export"
    assert "export" in schema.description.lower()
    assert tool.risk.value == "write_local"
    assert "project_id" in schema.parameters["properties"]


def test_design_export_execute(mock_design_studio):
    """Test DesignExportTool execute."""
    tool = DesignExportTool()
    result = tool.execute(project_id="test-project-id")

    assert result.success is True
    assert "project_id" in result.content
    assert "html_content" in result.content
    assert result.content["artifact_title"] == "Test Artifact"


def test_design_export_missing_params(mock_design_studio):
    """Test DesignExportTool with missing parameters."""
    tool = DesignExportTool()
    result = tool.execute()

    assert result.success is False
    assert "missing_required_parameters" in result.error


def test_tools_not_initialized():
    """Test tools handle uninitialized design studio gracefully."""
    # Reset the global studio
    init_design_studio(None)

    tool = DesignListSystemsTool()
    result = tool.execute()
    assert result.success is False
    assert "design_studio_not_initialized" in result.error

    tool = DesignListTemplatesTool()
    result = tool.execute()
    assert result.success is False
    assert "design_studio_not_initialized" in result.error


# ---------------------------------------------------------------------------
# Dispatch-contract regression (Task 13 self-review)
#
# Both dispatch paths call ``tool.execute(**args)`` synchronously and read
# ``.content`` off the return value. An ``async def execute`` returns a
# coroutine instead of ``ToolResult`` and blows up at the dispatch point.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_cls",
    [DesignGenerateTool, DesignIterateTool, DesignExportTool,
     DesignListSystemsTool, DesignListTemplatesTool],
)
def test_execute_is_synchronous(tool_cls):
    """All five design tools must expose a sync ``execute`` (never a coroutine fn)."""
    assert not inspect.iscoroutinefunction(tool_cls().execute)


def test_generate_repeated_invocations_reuse_one_loop(mock_design_studio):
    """Two consecutive generates must both succeed.

    Regression guard: a per-call ``asyncio.run`` would tear the loop down after
    the first call, and the generator's cached ``httpx.AsyncClient`` would then
    fail on the second call with ``RuntimeError: Event loop is closed``.
    The shared bridge loop keeps both calls on one loop.
    """
    tool = DesignGenerateTool()
    for _ in range(2):
        result = tool.execute(
            name="Repeat Project",
            kind="prototype",
            system_id="test-system",
            template_id="test-template",
            brief="Test brief",
        )
        assert result.success is True, result.error


def test_iterate_repeated_invocations_reuse_one_loop(mock_design_studio):
    """Two consecutive iterates must both succeed (same loop-reuse guard)."""
    tool = DesignIterateTool()
    for _ in range(2):
        result = tool.execute(
            project_id="test-project-id",
            feedback="Make it better",
        )
        assert result.success is True, result.error


def test_run_sync_reuses_a_single_loop_across_calls():
    """``run_sync`` must pin every call to ONE long-lived loop.

    This is the invariant that keeps the generator's cached ``httpx.AsyncClient``
    usable: the client is bound to the loop that first opened its connections,
    so a per-call ``asyncio.run`` would leave the second call holding pooled
    connections from an already-closed loop (``RuntimeError: Event loop is
    closed``). The mocked tool tests above can't reproduce that (no real
    sockets), so assert the invariant directly.
    """

    async def _current_loop():
        # Return the loop *object*, not id(): a per-call asyncio.run closes and
        # drops the old loop, and CPython happily hands a freed id to the new
        # one — id() comparison would pass even when the invariant is broken.
        return asyncio.get_running_loop()

    first = run_sync(_current_loop())
    second = run_sync(_current_loop())
    assert first is second, "run_sync created more than one event loop"


def test_async_bridge_works_from_inside_running_loop():
    """``run_sync`` must work even when the caller already has a running loop.

    Dispatch sometimes lands on a thread that owns a live loop; a naive
    ``asyncio.run`` there raises ``the current event loop is already running``.
    """

    async def _call() -> str:
        async def _inner() -> str:
            return "ok"

        return run_sync(_inner())

    assert asyncio.run(_call()) == "ok"
