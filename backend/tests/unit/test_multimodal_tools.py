"""多模态工具单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


# ── TextToSpeechTool ────────────────────────────────────────────

def test_tts_tool_schema():
    from backend.tools.tts_tool import TextToSpeechTool
    tool = TextToSpeechTool()
    assert tool.schema.name == "text_to_speech"
    assert "text" in tool.schema.parameters["required"]


def test_tts_tool_risk():
    from backend.tools.tts_tool import TextToSpeechTool
    from backend.domain.risk import RiskClass
    tool = TextToSpeechTool()
    # Note: brief originally said RiskClass.WRITE (which doesn't exist);
    # WRITE_LOCAL is the correct semantic (writes audio to local media store)
    assert tool.risk == RiskClass.WRITE_LOCAL


# ── SpeechToTextTool ────────────────────────────────────────────

def test_asr_tool_schema():
    from backend.tools.asr_tool import SpeechToTextTool
    tool = SpeechToTextTool()
    assert tool.schema.name == "speech_to_text"
    assert "file_path" in tool.schema.parameters["required"]


def test_asr_tool_risk():
    from backend.tools.asr_tool import SpeechToTextTool
    from backend.domain.risk import RiskClass
    tool = SpeechToTextTool()
    assert tool.risk == RiskClass.READ


# ── ImageGenerationTool ─────────────────────────────────────────

def test_image_gen_tool_schema():
    from backend.tools.image_gen_tool import ImageGenerationTool
    tool = ImageGenerationTool()
    assert tool.schema.name == "generate_image"
    assert "prompt" in tool.schema.parameters["required"]


def test_image_gen_tool_risk():
    from backend.tools.image_gen_tool import ImageGenerationTool
    from backend.domain.risk import RiskClass
    tool = ImageGenerationTool()
    # WRITE does not exist; generated media is persisted locally.
    assert tool.risk == RiskClass.WRITE_LOCAL
