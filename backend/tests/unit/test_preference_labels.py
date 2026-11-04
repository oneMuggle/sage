"""偏好中文标签映射测试。

背景：进化任务原先把机器键（``response_length``）和英文枚举值
（``detailed``）直接拼进 user_profile / memories_semantic，
用户在记忆库里看到的是 "用户偏好 response_length: detailed"，
被前端截断后变成 "response_length:detai" 这类奇怪内容。
"""

from backend.memory.preference_labels import (
    PREFERENCE_DIMENSION_LABELS,
    PREFERENCE_VALUE_LABELS,
    format_preference,
)


class TestFormatPreference:
    def test_translates_known_dimension_and_value(self):
        assert format_preference("response_length", "detailed") == "用户偏好回复长度: 详细"
        assert format_preference("tone", "friendly") == "用户偏好交互风格: 友好"
        assert format_preference("detail_level", "comprehensive") == "用户偏好详细程度: 全面"

    def test_never_leaks_english_machine_key(self):
        """回归: 渲染文本里不能再出现 response_length 这类机器键。"""
        rendered = format_preference("response_length", "detailed")
        assert "response_length" not in rendered
        assert "detailed" not in rendered

    def test_unknown_dimension_falls_back_to_raw_key(self):
        assert format_preference("unknown_dim", "foo") == "用户偏好unknown_dim: foo"

    def test_unknown_value_falls_back_to_raw_value(self):
        assert format_preference("tone", "casual") == "用户偏好交互风格: casual"

    def test_empty_value_does_not_crash(self):
        assert format_preference("response_length", "") == "用户偏好回复长度: "


class TestLabelTables:
    def test_dimension_labels_cover_all_preference_dimensions(self):
        """三个已知维度都必须有中文标签，否则会退回英文键。"""
        for key in ("response_length", "tone", "detail_level"):
            assert key in PREFERENCE_DIMENSION_LABELS
            assert PREFERENCE_DIMENSION_LABELS[key] != key

    def test_value_labels_cover_all_known_values(self):
        """维度下的每个合法取值都要有中文标签。"""
        expected = {
            "response_length": {"short", "medium", "long", "detailed"},
            "tone": {"friendly", "professional", "humorous", "formal"},
            "detail_level": {"brief", "medium", "comprehensive"},
        }
        for dimension, values in expected.items():
            assert dimension in PREFERENCE_VALUE_LABELS
            for value in values:
                assert value in PREFERENCE_VALUE_LABELS[dimension]
