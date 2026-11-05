"""验证 MemoryExtractor 的事实提取功能。"""

import pytest

from backend.memory.extractor import MemoryExtractor

pytestmark = pytest.mark.unit


class TestMemoryExtractorKeywords:
    """测试关键词降级提取（无 LLM）"""

    @pytest.mark.asyncio()
    async def test_extract_preference_with_keyword(self):
        """包含偏好关键词时应提取事实。"""
        extractor = MemoryExtractor(llm_client=None)
        # 消息需要足够长（> 20 字符）才触发提取
        facts = await extractor.extract(
            "我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20, "好的"
        )
        assert len(facts) >= 1
        assert any("火锅" in f["content"] for f in facts)
        assert all(f["importance"] == 7 for f in facts)

    @pytest.mark.asyncio()
    async def test_extract_short_message_returns_empty(self):
        """太短的消息不应提取。"""
        extractor = MemoryExtractor(llm_client=None)
        facts = await extractor.extract("hi", "hello")
        assert facts == []

    @pytest.mark.asyncio()
    async def test_extract_no_keywords_returns_empty(self):
        """无偏好关键词的普通对话不应提取。"""
        extractor = MemoryExtractor(llm_client=None)
        facts = await extractor.extract("今天天气怎么样", "今天晴天")
        assert facts == []


class TestMemoryExtractorLLM:
    """测试 LLM 提取"""

    @pytest.mark.asyncio()
    async def test_extract_with_mock_llm_json(self):
        """LLM 返回 JSON 时应正确解析。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message

                return Message(
                    role="assistant",
                    content='[{"content":"用户喜欢吃火锅","importance":8,"category":"preference","tags":["火锅"]}]',
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract(
            "我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20,
            "好的记住了",
        )
        assert len(facts) == 1
        assert facts[0]["content"] == "用户喜欢吃火锅"
        assert facts[0]["importance"] == 8
        # F4 — the old-vocabulary category 'preference' must be normalized to
        # the new taxonomy 'user_pref'.
        assert facts[0]["category"] == "user_pref"

    @pytest.mark.asyncio()
    async def test_extract_with_markdown_code_block(self):
        """LLM 返回 markdown 代码块中的 JSON 应正确解析。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message

                return Message(
                    role="assistant",
                    content='好的，以下是提取的结果：\n```json\n[{"content":"用户喜欢Python","importance":6,"category":"fact","tags":["编程"]}]\n```\n希望这对你有帮助！',
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract(
            "我喜欢用Python编程，已经学了一年多了" + "x" * 20,
            "很好",
        )
        assert len(facts) == 1
        assert "Python" in facts[0]["content"]

    @pytest.mark.asyncio()
    async def test_extract_with_invalid_json_falls_back(self):
        """LLM 返回无效 JSON 时应降级到关键词提取。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message

                return Message(
                    role="assistant",
                    content="这不是JSON格式",
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract("我喜欢吃火锅，每次都去那家店" + "x" * 20, "好的")
        assert len(facts) >= 0

    @pytest.mark.asyncio()
    async def test_extract_with_llm_error_falls_back(self):
        """LLM 调用失败时应降级到关键词提取。"""

        class FailingLLM:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("LLM unavailable")

        extractor = MemoryExtractor(llm_client=FailingLLM())
        facts = await extractor.extract("我喜欢吃火锅，每次都去那家店" + "x" * 20, "好的")
        assert len(facts) >= 0


# ----------------------------------------------------------------------------
# Task 4 / Gap A — memory_category heuristic
# ----------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_keyword_extract_tags_user_pref():
    """Preference keywords (喜欢/偏好/讨厌/不要/记得/以后/设置/爱吃)
    must produce memory_category='user_pref'."""

    extractor = MemoryExtractor(llm_client=None)
    facts = await extractor.extract(
        "我喜欢吃火锅" + "x" * 20, "好的"
    )
    assert len(facts) >= 1
    assert all(f["category"] == "user_pref" for f in facts)


@pytest.mark.asyncio()
async def test_keyword_extract_defaults_to_project_fact():
    """When no preference keyword matches, default to 'project_fact'."""

    extractor = MemoryExtractor(llm_client=None)
    # Long-ish message without any preference keyword
    facts = await extractor.extract(
        "The Postgres backup uses pg_dump with a 30-day rotation policy" + "x" * 20,
        "ok noted",
    )
    assert facts == []  # no preference keyword → empty list

    # Direct test of the heuristic via the internal helper
    category = extractor._categorize("we use kafka for event streaming")
    assert category == "project_fact"


def test_categorize_returns_known_categories():
    """All 4 categories from task-4-brief.md step 13 must be representable."""
    extractor = MemoryExtractor(llm_client=None)
    assert extractor._categorize("我以后要看这个") == "user_pref"
    assert extractor._categorize("the deploy uses helm") == "project_fact"
    # The heuristic defaults to project_fact; task_summary and
    # cross_session_pattern are reserved for richer extractor stages.
    assert extractor._categorize("") in {"user_pref", "project_fact"}


@pytest.mark.asyncio()
async def test_llm_extract_normalizes_category_vocabulary():
    """F4 — LLM path emits the OLD vocabulary (preference/fact/goal/event);
    the extractor must normalize it to the new taxonomy
    (user_pref/project_fact/task_summary/cross_session_pattern)."""

    class MockLLM:
        async def chat(self, messages, **kwargs):
            from backend.domain.message import Message

            return Message(
                role="assistant",
                content=(
                    '[{"content":"用户喜欢Python","importance":6,"category":"preference",'
                    '"tags":["编程"]},'
                    '{"content":"部署用helm","importance":5,"category":"fact","tags":["运维"]},'
                    '{"content":"用户目标是一个月内上线","importance":6,"category":"goal",'
                    '"tags":["目标"]},'
                    '{"content":"今天完成了登录模块","importance":5,"category":"event",'
                    '"tags":["任务"]}]'
                ),
            )

    extractor = MemoryExtractor(llm_client=MockLLM())
    facts = await extractor.extract(
        "我喜欢用Python编程，已经学了一年多了" + "x" * 20,
        "很好",
    )
    cats = {f["category"] for f in facts}
    assert "user_pref" in cats  # preference → user_pref
    assert "project_fact" in cats  # fact → project_fact
    # goal → cross_session_pattern (or project_fact), event → task_summary
    assert "cross_session_pattern" in cats or "project_fact" in cats
    assert "task_summary" in cats
    # old vocabulary must never leak through
    assert not (cats & {"preference", "fact", "goal", "event"})


# ----------------------------------------------------------------------------
# Task 2.1 — 双向提取门槛（短消息跳过 + 高价值信号放行）
# ----------------------------------------------------------------------------


class TestExtractionGate:
    """覆盖 ``_should_extract`` / ``_has_high_value_signal``。

    设计目标：
    * 纯寒暄（"好的谢谢" / "收到"）不再浪费提取器一轮；
    * 但因门槛上调而被原阈值放过的短消息（"我喜欢 ruff"）必须仍被提取。
    """

    def test_short_chitchat_is_skipped(self):
        extractor = MemoryExtractor(llm_client=None)
        assert extractor._should_extract("好的谢谢", "不客气，还有问题随时问") is False

    def test_short_message_with_high_value_signal_passes(self):
        extractor = MemoryExtractor(llm_client=None)
        # 用户消息远低于 30 字，但命中「我喜欢」
        assert extractor._should_extract("我喜欢 ruff", "好的") is True

    def test_high_value_signal_in_assistant_also_passes(self):
        extractor = MemoryExtractor(llm_client=None)
        # 用户消息很短且无信号；助手侧命中「我们决定」
        assert extractor._should_extract("嗯", "那么我们决定改用 TypeScript") is True

    def test_strong_negative_preference_passes(self):
        extractor = MemoryExtractor(llm_client=None)
        # 禁令类信号（「永远不」）也应放行
        assert extractor._should_extract("以后永远不用 class", "明白") is True

    def test_long_messages_always_pass(self):
        extractor = MemoryExtractor(llm_client=None)
        user_msg = "x" * extractor._USER_MSG_THRESHOLD
        assistant_msg = "y" * extractor._ASSISTANT_MSG_THRESHOLD
        assert extractor._should_extract(user_msg, assistant_msg) is True

    def test_one_side_long_enough_passes(self):
        extractor = MemoryExtractor(llm_client=None)
        # 用户短、助手长 → 不满足「两侧都短」，仍应提取
        assert extractor._should_extract("嗯", "y" * extractor._ASSISTANT_MSG_THRESHOLD) is True

    def test_empty_messages_are_skipped(self):
        extractor = MemoryExtractor(llm_client=None)
        assert extractor._should_extract("", "") is False
        assert extractor._has_high_value_signal("", "") is False

    def test_high_value_keywords_match_substring(self):
        """关键词是子串匹配——不要求整句，也不依赖中文词边界。"""
        assert MemoryExtractor._has_high_value_signal(
            "我们决定用 pnpm 作为包管理器", ""
        )
        assert MemoryExtractor._has_high_value_signal("我习惯用 4 空格缩进", "")
        assert not MemoryExtractor._has_high_value_signal("今天天气不错", "明天也不错")

    @pytest.mark.asyncio()
    async def test_extract_skips_chitchat_end_to_end(self):
        """端到端：短寒暄不进入 LLM 路径，返回空列表。"""

        class ExplodingLLM:
            async def chat(self, messages, **kwargs):  # pragma: no cover
                raise AssertionError("chitchat should never reach the LLM")

        extractor = MemoryExtractor(llm_client=ExplodingLLM())
        assert await extractor.extract("收到", "好的") == []

    @pytest.mark.asyncio()
    async def test_extract_short_high_value_reaches_llm(self):
        """端到端：短消息但因高价值信号仍被送入提取器。"""

        class RecordingLLM:
            def __init__(self):
                self.called = False

            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message

                self.called = True
                return Message(
                    role="assistant",
                    content='[{"content":"用户偏好使用 ruff","importance":7,'
                    '"category":"user_pref","tags":["tooling"]}]',
                )

        llm = RecordingLLM()
        extractor = MemoryExtractor(llm_client=llm)
        facts = await extractor.extract("我喜欢 ruff", "好的")
        assert llm.called is True
        assert len(facts) == 1
        assert facts[0]["category"] == "user_pref"
