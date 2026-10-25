"""
单元测试：LLMConfig.compute_dynamic_timeout() 动态超时计算

测试覆盖：
1. 短上下文（<100 tokens）→ 基础超时 ≈ 60s
2. 长上下文（10000 tokens）→ 超时翻倍 ≈ 120s
3. 慢模型（GPT-4/o1/DeepSeek R1）→ 超时 ×2
4. 超过 max_timeout → 截断到上限
5. token 估算失败 → 回退默认超时
6. 设置读取失败 → 使用默认上限 300s
"""

from unittest.mock import patch

import pytest

from backend.core.legacy.llm_client import LLMConfig


class TestComputeDynamicTimeout:
    """测试动态超时计算逻辑"""

    def test_short_context_gpt35(self):
        """短上下文（100 tokens）+ GPT-3.5 → 基础超时 ≈ 60s"""
        config = LLMConfig(model="gpt-3.5-turbo")
        messages = [{"role": "user", "content": "Hello"}]  # 约 5 tokens

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=100):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=0.1, model_factor=1.0
        # 60 * (1 + 0.1) * 1.0 = 66
        assert 60 <= timeout <= 70, f"短上下文 GPT-3.5 超时应在 60-70s，实际 {timeout}"

    def test_long_context_gpt35(self):
        """长上下文（10000 tokens）+ GPT-3.5 → 超时翻倍 ≈ 120s"""
        config = LLMConfig(model="gpt-3.5-turbo")
        messages = [{"role": "user", "content": "x" * 40000}]  # 约 10000 tokens

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=10000):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=10, model_factor=1.0
        # 60 * (1 + 10) * 1.0 = 660 → 截断到 max_timeout
        assert timeout == 300, f"长上下文应截断到 max_timeout 300s，实际 {timeout}"

    def test_slow_model_gpt4(self):
        """GPT-4 模型 → 超时 ×2"""
        config = LLMConfig(model="gpt-4")
        messages = [{"role": "user", "content": "Hello"}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=100):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=0.1, model_factor=2.0
        # 60 * (1 + 0.1) * 2.0 = 132
        assert 130 <= timeout <= 135, f"GPT-4 超时应在 130-135s，实际 {timeout}"

    def test_slow_model_o1(self):
        """OpenAI o1 模型 → 超时 ×2"""
        config = LLMConfig(model="o1-preview")
        messages = [{"role": "user", "content": "Hello"}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=100):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=0.1, model_factor=2.0
        assert 130 <= timeout <= 135, f"o1 超时应在 130-135s，实际 {timeout}"

    def test_slow_model_deepseek_r1(self):
        """DeepSeek R1 模型 → 超时 ×2"""
        config = LLMConfig(model="deepseek-r1")
        messages = [{"role": "user", "content": "Hello"}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=100):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=0.1, model_factor=2.0
        assert 130 <= timeout <= 135, f"DeepSeek R1 超时应在 130-135s，实际 {timeout}"

    def test_max_timeout_from_settings(self):
        """用户配置 max_timeout → 截断到配置值"""
        config = LLMConfig(model="gpt-3.5-turbo")
        messages = [{"role": "user", "content": "x" * 40000}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=10000), \
             patch("backend.data.settings_repo.SettingsRepository") as mock_repo:
            mock_repo.return_value.get_json.return_value = {"llmTotalTimeoutS": 120}
            timeout = config.compute_dynamic_timeout(messages)

        # 计算值 660s > max 120s → 截断
        assert timeout == 120, f"应截断到用户配置的 max_timeout 120s，实际 {timeout}"

    def test_import_error_fallback(self):
        """estimate_messages_tokens 导入失败 → 回退默认超时"""
        config = LLMConfig(model="gpt-3.5-turbo", timeout=60)
        messages = [{"role": "user", "content": "Hello"}]

        with patch(
            "backend.chat.compaction.estimate_messages_tokens",
            side_effect=ImportError("mock import失败"),
        ):
            timeout = config.compute_dynamic_timeout(messages)

        assert timeout == 60, f"导入失败应回退默认超时 60s，实际 {timeout}"

    def test_estimation_error_fallback(self):
        """token 估算抛异常 → 回退默认超时"""
        config = LLMConfig(model="gpt-3.5-turbo", timeout=60)
        messages = [{"role": "user", "content": "Hello"}]

        with patch(
            "backend.chat.compaction.estimate_messages_tokens",
            side_effect=ValueError("mock 估算失败"),
        ):
            timeout = config.compute_dynamic_timeout(messages)

        assert timeout == 60, f"估算失败应回退默认超时 60s，实际 {timeout}"

    def test_settings_read_error_fallback(self):
        """设置读取失败 → 使用默认上限 300s"""
        config = LLMConfig(model="gpt-3.5-turbo")
        messages = [{"role": "user", "content": "x" * 40000}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=10000), \
             patch("backend.data.settings_repo.SettingsRepository") as mock_repo:
            mock_repo.return_value.get_json.side_effect = Exception("mock DB 错误")
            timeout = config.compute_dynamic_timeout(messages)

        # 计算值 660s > 默认上限 300s → 截断
        assert timeout == 300, f"设置读取失败应使用默认上限 300s，实际 {timeout}"

    def test_medium_context_claude3(self):
        """中等上下文（5000 tokens）+ Claude 3 → 超时 ×2"""
        config = LLMConfig(model="claude-3-opus")
        messages = [{"role": "user", "content": "x" * 20000}]

        with patch("backend.chat.compaction.estimate_messages_tokens", return_value=5000):
            timeout = config.compute_dynamic_timeout(messages)

        # base=60, context_factor=5, model_factor=2.0
        # 60 * (1 + 5) * 2.0 = 720 → 截断到 300s
        assert timeout == 300, f"Claude 3 中等上下文应截断到 300s，实际 {timeout}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
