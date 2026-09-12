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
