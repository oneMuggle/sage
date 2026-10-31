"""ocr_image 工具单元测试（fake OCR 服务，无真实引擎）。"""

from __future__ import annotations

import pytest

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.services.ocr import (
    OcrConfig,
    OcrLine,
    OcrResult,
    OcrService,
    init_ocr_service,
    reset_ocr_service,
)
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.ocr_image_tool import OcrImageTool

pytestmark = pytest.mark.unit


class FakeEngine:
    name = "fake-ocr"

    def available(self):
        return True, ""

    def recognize(self, image_bytes, opts):
        return OcrResult(
            text="截图里的文字",
            lines=(OcrLine(text="截图里的文字", confidence=0.91),),
            engine=self.name,
            lang=opts.lang,
        )


@pytest.fixture(autouse=True)
def _isolate_service():
    init_ocr_service(
        OcrService(
            engines=[FakeEngine()],
            config_provider=lambda: OcrConfig(enabled=True, engine="auto"),
        )
    )
    yield
    reset_ocr_service()


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="s1",
        stream_id="st1",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )


def test_schema_and_risk() -> None:
    tool = OcrImageTool()

    assert tool.schema.name == "ocr_image"
    assert tool.risk == RiskClass.READ
    assert tool.requires_tool_context is True


def test_execute_requires_path_or_media_id() -> None:
    tool = OcrImageTool()

    result = tool.execute()

    assert result.success is False
    assert result.error == "path_or_media_id_required"


def test_execute_rejects_path_outside_workspace(tmp_path) -> None:
    tool = OcrImageTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    token = set_tool_context(_ctx())
    try:
        result = tool.execute(path="../outside.png")
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "path_outside_workspace"


def test_execute_reads_workspace_image(tmp_path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")
    tool = OcrImageTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    token = set_tool_context(_ctx())
    try:
        result = tool.execute(path="shot.png", lang="ch")
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["text"] == "截图里的文字"
    assert result.content["engine"] == "fake-ocr"


def test_execute_media_id(monkeypatch) -> None:
    class FakeMediaStore:
        def load(self, media_id):
            assert media_id == "media-1"
            return object(), b"fake-png"

    monkeypatch.setattr(
        "backend.services.multimodal.media_store.MediaStore", FakeMediaStore
    )
    tool = OcrImageTool()
    token = set_tool_context(_ctx())
    try:
        result = tool.execute(media_id="media-1")
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["text"] == "截图里的文字"
