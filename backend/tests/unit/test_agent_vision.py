"""Vision model fallback unit tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestVisionFallback:
    """Test intelligent vision fallback strategy."""

    @pytest.mark.asyncio
    async def test_chat_model_supports_vision(self):
        """chatModel 支持 vision 时，直接注入图片，不调用 visionModel。"""
        from backend.core.legacy.agent import SageAgent

        # Arrange
        agent = MagicMock(spec=SageAgent)
        agent._get_model_capabilities = AsyncMock(return_value=['chat', 'vision'])
        agent._inject_images_as_content = MagicMock(return_value=[
            {"role": "user", "content": [
                {"type": "text", "text": "描述这张图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
            ]}
        ])

        messages = [{"role": "user", "content": "描述这张图片"}]
        images = ["data:image/png;base64,..."]

        # Act
        result = await SageAgent._prepare_messages_with_images(
            agent, messages, images
        )

        # Assert
        assert len(result) == 1
        assert result[0]["content"][1]["type"] == "image_url"
        agent._inject_images_as_content.assert_called_once_with(messages, images)
