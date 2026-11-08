"""
Recap 单元测试 — backend/chat/recap.py

覆盖:
- _parse_recap_output: JSON（camelCase / snake_case）与 Markdown 降级解析
- RecapResult.to_dict 的 camelCase 输出契约
- build_recap_prompt 的对话转写
- generate_recap 的地板（RecapTooShortError）、LLM 失败/空输出/无进度
"""

import json

import pytest

from backend.chat.recap import (
    DEFAULT_RECAP_MESSAGE_LIMIT,
    MIN_RECAP_MESSAGE_COUNT,
    RecapError,
    RecapTooShortError,
    _parse_recap_output,
    build_recap_prompt,
    generate_recap,
)

pytestmark = pytest.mark.unit


def _dict_messages(n: int):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"消息 #{i}"}
        for i in range(n)
    ]


def _fetcher(messages):
    async def _fetch(session_id: str, limit: int):
        return messages

    return _fetch


# ---- _parse_recap_output ----------------------------------------------------


def test_parse_json_camel_case():
    raw = json.dumps(
        {
            "progress": "完成认证模块",
            "decisions": ["用 JWT 而非 Session"],
            "nextSteps": ["编写单元测试"],
            "openQuestions": ["是否需要 OAuth?"],
        }
    )
    result = _parse_recap_output(raw)

    assert result.progress == "完成认证模块"
    assert result.decisions == ["用 JWT 而非 Session"]
    assert result.next_steps == ["编写单元测试"]
    assert result.open_questions == ["是否需要 OAuth?"]


def test_parse_json_accepts_snake_case_keys():
    raw = json.dumps(
        {
            "progress": "完成认证模块",
            "decisions": ["用 JWT"],
            "next_steps": ["写测试"],
            "open_questions": ["要 OAuth 吗"],
        }
    )
    result = _parse_recap_output(raw)

    assert result.next_steps == ["写测试"]
    assert result.open_questions == ["要 OAuth 吗"]


def test_parse_json_missing_optional_fields_defaults_to_empty():
    result = _parse_recap_output(json.dumps({"progress": "完成认证模块"}))

    assert result.progress == "完成认证模块"
    assert result.decisions == []
    assert result.next_steps == []
    assert result.open_questions == []


def test_parse_markdown_fallback_by_sections():
    raw = """
## 进度
完成了用户认证模块

## 决策
- 使用 JWT 而非 Session
- 使用 Redis 做缓存

## 下一步
1. 编写单元测试
2. 部署到测试环境

## 问题
- 是否需要支持 OAuth?
"""
    result = _parse_recap_output(raw)

    assert result.progress == "完成了用户认证模块"
    assert result.decisions == ["使用 JWT 而非 Session", "使用 Redis 做缓存"]
    assert result.next_steps == ["编写单元测试", "部署到测试环境"]
    assert result.open_questions == ["是否需要支持 OAuth?"]


def test_parse_markdown_falls_back_to_first_line():
    result = _parse_recap_output("当前正在做登录页\n更多细节")

    assert result.progress == "当前正在做登录页"
    assert result.decisions == []


def test_parse_markdown_ignores_leading_heading_for_progress():
    result = _parse_recap_output("# 总结\n## 决策\n- 用 JWT")

    assert result.progress == ""
    assert result.decisions == ["用 JWT"]


def test_parse_invalid_json_falls_back_to_markdown():
    """以 { 开头但 JSON 非法 → 降级 markdown，不抛异常。"""
    raw = "{这不是合法 JSON\n## 决策\n- 用 JWT"

    result = _parse_recap_output(raw)

    assert result.decisions == ["用 JWT"]


# ---- RecapResult.to_dict ----------------------------------------------------


def test_to_dict_uses_camel_case_contract():
    from backend.chat.recap import RecapResult

    result = RecapResult(
        progress="完成认证模块",
        decisions=["用 JWT"],
        next_steps=["写测试"],
        open_questions=["要 OAuth 吗"],
    )

    assert result.to_dict() == {
        "progress": "完成认证模块",
        "decisions": ["用 JWT"],
        "nextSteps": ["写测试"],
        "openQuestions": ["要 OAuth 吗"],
    }


# ---- build_recap_prompt -----------------------------------------------------


def test_build_recap_prompt_transcribes_roles_and_content():
    prompt = build_recap_prompt(_dict_messages(MIN_RECAP_MESSAGE_COUNT))

    assert "[user]: 消息 #0" in prompt
    assert "[assistant]: 消息 #1" in prompt
    assert "nextSteps" in prompt
    assert "对话历史：" in prompt


# ---- generate_recap ---------------------------------------------------------


@pytest.mark.asyncio()
async def test_generate_recap_too_short_raises_specific_error():
    async def _never_called(prompt: str) -> str:
        raise AssertionError("消息不足时不应调用 LLM")

    with pytest.raises(RecapTooShortError):
        await generate_recap(
            "s-1",
            _never_called,
            message_fetcher=_fetcher(_dict_messages(MIN_RECAP_MESSAGE_COUNT - 1)),
        )


@pytest.mark.asyncio()
async def test_generate_recap_success_uses_default_limit_and_parses():
    captured = {}

    async def _fetch(session_id: str, limit: int):
        captured["session_id"] = session_id
        captured["limit"] = limit
        return _dict_messages(MIN_RECAP_MESSAGE_COUNT)

    async def _llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {
                "progress": "完成认证模块",
                "decisions": ["用 JWT"],
                "nextSteps": ["写测试"],
                "openQuestions": [],
            }
        )

    result = await generate_recap("s-1", _llm, message_fetcher=_fetch)

    assert captured["session_id"] == "s-1"
    assert captured["limit"] == DEFAULT_RECAP_MESSAGE_LIMIT
    assert "消息 #0" in captured["prompt"]
    assert result.progress == "完成认证模块"
    assert result.next_steps == ["写测试"]


@pytest.mark.asyncio()
async def test_generate_recap_wraps_llm_exception():
    async def _broken(prompt: str) -> str:
        raise RuntimeError("upstream exploded")

    with pytest.raises(RecapError) as exc_info:
        await generate_recap(
            "s-1", _broken, message_fetcher=_fetcher(_dict_messages(3))
        )

    assert not isinstance(exc_info.value, RecapTooShortError)
    assert "LLM 调用失败" in str(exc_info.value)
    assert "upstream exploded" in str(exc_info.value)


@pytest.mark.asyncio()
async def test_generate_recap_rejects_empty_output():
    async def _empty(prompt: str) -> str:
        return "   "

    with pytest.raises(RecapError, match="LLM 返回空结果"):
        await generate_recap("s-1", _empty, message_fetcher=_fetcher(_dict_messages(3)))


@pytest.mark.asyncio()
async def test_generate_recap_rejects_output_without_progress():
    async def _no_progress(prompt: str) -> str:
        return json.dumps({"decisions": ["用 JWT"]})

    with pytest.raises(RecapError, match="未生成有效的进度总结"):
        await generate_recap(
            "s-1", _no_progress, message_fetcher=_fetcher(_dict_messages(3))
        )
