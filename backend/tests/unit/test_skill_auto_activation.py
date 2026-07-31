# mypy: disable-error-code="no-untyped-def,attr-defined"
"""A16: Skill Auto-Activation 单元测试。

覆盖四层:

1. ``auto_activation.extract_triggers`` — 触发短语提取
   (引号短语 / 逗号分隔 / 中文 / 去重 / 过滤规则)
2. ``auto_activation.auto_activate`` + ``build_context_block`` —
   匹配与注入块组装 (大小写不敏感 / 多技能 / 上限截断 / 块格式)
3. frontmatter / loader — ``when_to_use`` 字段解析
   (下划线主键 / 连字符别名 / 类型校验 / 缺失默认空串)
4. 集成 — ``InprocSkillAdapter.auto_activate`` 过滤语义
   (enabled / disable_model_invocation / builtin 排除) 与
   ``ChatService`` system prompt 注入 (best-effort 降级)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sage_core import Message, Role

from backend.application.services.chat_service import ChatService, _skill_activation_block
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.auto_activation import (
    MAX_AUTO_ACTIVATED_SKILLS,
    AutoActivationResult,
    auto_activate,
    build_context_block,
    extract_triggers,
)
from backend.skills.skill_md.frontmatter import SkillMdParseError, parse
from backend.skills.skill_md.loader import SkillMdHotLoader
from backend.skills.skill_md.skill import DispatchMode, SkillMdDocument

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _doc(
    name: str,
    when_to_use: str = "",
    description: str = "test skill",
    body: str = "skill body",
    disable_model_invocation: bool = False,
) -> SkillMdDocument:
    """构造测试用 SkillMdDocument。"""
    return SkillMdDocument(
        name=name,
        description=description,
        when_to_use=when_to_use,
        body=body,
        dispatch=DispatchMode(disable_model_invocation=disable_model_invocation),
    )


def _write_skill_md(
    parent: Path,
    name: str,
    frontmatter_extra: str = "",
    body: str = "Body content\n",
) -> Path:
    """在 parent/<name>/SKILL.md 写一个合法 SKILL.md, 返回路径。"""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: test {name}\n"
        f"{frontmatter_extra}"
        f"---\n"
        f"{body}",
        encoding="utf-8",
    )
    return path


# =====================================================================
# 1. extract_triggers
# =====================================================================


class TestExtractTriggers:
    def test_quoted_phrases(self):
        """引号短语整条作为触发词。"""
        triggers = extract_triggers('"code review", "check my code"')
        assert "code review" in triggers
        assert "check my code" in triggers

    def test_chinese_quoted_phrases(self):
        """中文引号短语 (ASCII 引号包裹中文)。"""
        triggers = extract_triggers('"审查代码", "代码审查"')
        assert "审查代码" in triggers
        assert "代码审查" in triggers

    def test_curly_quotes(self):
        """中文弯引号 (U+201C / U+201D) 同样识别。"""
        triggers = extract_triggers("“写周报”")
        assert "写周报" in triggers

    def test_bare_comma_separated(self):
        """无引号逗号分隔短语。"""
        triggers = extract_triggers("code review, 审查代码")
        assert "code review" in triggers
        assert "审查代码" in triggers

    def test_fullwidth_comma(self):
        """中文全角逗号分隔 (对 LLM_Simple 的兼容扩展)。"""
        triggers = extract_triggers("写周报，写总结")
        assert "写周报" in triggers
        assert "写总结" in triggers

    def test_mixed_quoted_and_bare(self):
        """混合格式: 引号 + 裸短语。"""
        triggers = extract_triggers('"review this", code review')
        assert "review this" in triggers
        assert "code review" in triggers

    def test_lowercase_normalization(self):
        """触发词统一小写。"""
        triggers = extract_triggers('"Code Review"')
        assert "code review" in triggers
        assert "Code Review" not in triggers

    def test_dedup_keeps_order(self):
        """去重且保序 (引号与裸短语重复只留一次)。"""
        triggers = extract_triggers('"code review", code review, "code review"')
        assert triggers.count("code review") == 1

    def test_skips_short_tokens(self):
        """单字符触发词被过滤 (误报率高)。"""
        triggers = extract_triggers('"a", b, ok')
        assert "a" not in triggers
        assert "b" not in triggers
        assert "ok" in triggers

    def test_skips_use_when_meta_phrases(self):
        """``use when`` 开头的元描述短语被过滤。"""
        triggers = extract_triggers("Use when the user asks for review, code review")
        assert "code review" in triggers
        assert not any(t.startswith("use when") for t in triggers)

    def test_empty_input(self):
        """空串返回空列表。"""
        assert extract_triggers("") == []


# =====================================================================
# 2. auto_activate + build_context_block
# =====================================================================


class TestAutoActivate:
    def test_single_match(self):
        """单技能命中: names + context_block 均填充。"""
        docs = [_doc("code-review", when_to_use='"code review"')]
        result = auto_activate("please code review my PR", docs)
        assert result.activated is True
        assert result.names == ("code-review",)
        assert "code-review" in result.context_block
        assert "skill body" in result.context_block

    def test_no_match_returns_empty(self):
        """无命中: 空结果, block 为空串。"""
        docs = [_doc("code-review", when_to_use='"code review"')]
        result = auto_activate("what is the weather today", docs)
        assert result.activated is False
        assert result.names == ()
        assert result.context_block == ""

    def test_case_insensitive_match(self):
        """匹配大小写不敏感。"""
        docs = [_doc("reviewer", when_to_use='"CODE REVIEW"')]
        assert auto_activate("Please Code Review", docs).activated is True

    def test_chinese_trigger_match(self):
        """中文触发短语匹配中文消息。"""
        docs = [_doc("weekly-report", when_to_use='"写周报", weekly report')]
        result = auto_activate("帮我写周报", docs)
        assert result.names == ("weekly-report",)

    def test_multiple_matches_preserve_order(self):
        """多技能命中按 docs 顺序排列。"""
        docs = [
            _doc("a-skill", when_to_use='"deploy"'),
            _doc("b-skill", when_to_use='"deploy"'),
        ]
        result = auto_activate("deploy the app", docs)
        assert result.names == ("a-skill", "b-skill")

    def test_skips_docs_without_when_to_use(self):
        """when_to_use 为空的 doc 不参与匹配 (builtin 语义)。"""
        docs = [_doc("builtin-like", when_to_use="")]
        result = auto_activate("anything matches?", docs)
        assert result.activated is False

    def test_empty_message_returns_empty(self):
        """空消息直接返回空结果。"""
        docs = [_doc("s", when_to_use='"hello"')]
        assert auto_activate("", docs).activated is False

    def test_activation_cap(self):
        """单消息最多激活 MAX_AUTO_ACTIVATED_SKILLS 个技能。"""
        docs = [
            _doc(f"skill-{i}", when_to_use='"shared trigger"') for i in range(8)
        ]
        result = auto_activate("shared trigger here", docs)
        assert len(result.names) == MAX_AUTO_ACTIVATED_SKILLS
        # 按顺序截断前 N 个
        assert result.names == tuple(f"skill-{i}" for i in range(MAX_AUTO_ACTIVATED_SKILLS))

    def test_block_format_system_reminder(self):
        """注入块含 <system-reminder> 头 + name + description + body。"""
        docs = [
            _doc(
                "reviewer",
                when_to_use='"review"',
                description="Reviews code",
                body="# Review checklist",
            )
        ]
        block = auto_activate("review this", docs).context_block
        assert "<system-reminder>" in block
        assert "Skill 'reviewer' auto-activated: Reviews code" in block
        assert "Follow the instructions below." in block
        assert "# Review checklist" in block

    def test_multiple_blocks_separated(self):
        """多技能块之间用 --- 分隔。"""
        docs = [
            _doc("s1", when_to_use='"x1"', body="body-1"),
            _doc("s2", when_to_use='"x2"', body="body-2"),
        ]
        block = auto_activate("x1 and x2", docs).context_block
        assert "body-1" in block
        assert "body-2" in block
        assert "\n\n---\n\n" in block


class TestBuildContextBlock:
    def test_empty_sequence_returns_empty(self):
        """空序列返回空串。"""
        assert build_context_block([]) == ""

    def test_result_dataclass_defaults(self):
        """AutoActivationResult 默认值: 未激活 + 空块。"""
        result = AutoActivationResult()
        assert result.activated is False
        assert result.names == ()
        assert result.context_block == ""


# =====================================================================
# 3. frontmatter / loader — when_to_use 解析
# =====================================================================


class TestFrontmatterWhenToUse:
    def test_parse_accepts_string(self):
        """when_to_use 为字符串时解析通过 (YAML 单引号包裹保留内部双引号)。"""
        meta, _ = parse(
            "---\nname: demo\ndescription: demo skill\n"
            "when_to_use: '\"code review\", 审查代码'\n---\nbody\n"
        )
        assert meta["when_to_use"] == '"code review", 审查代码'

    def test_parse_rejects_non_string(self):
        """when_to_use 非字符串 → SkillMdParseError。"""
        with pytest.raises(SkillMdParseError, match="when_to_use"):
            parse("---\nname: demo\ndescription: demo skill\nwhen_to_use: 42\n---\nbody\n")

    def test_parse_rejects_too_long(self):
        """when_to_use 超过 1024 字符 → SkillMdParseError。"""
        long_val = "x" * 1025
        with pytest.raises(SkillMdParseError, match="when_to_use"):
            parse(
                f"---\nname: demo\ndescription: demo skill\nwhen_to_use: {long_val}\n---\nbody\n"
            )

    def test_parse_dash_alias(self):
        """连字符别名 when-to-use 同样校验。"""
        with pytest.raises(SkillMdParseError, match="when_to_use"):
            parse("---\nname: demo\ndescription: demo skill\nwhen-to-use: 42\n---\nbody\n")


class TestLoaderWhenToUse:
    def test_loader_populates_when_to_use(self, tmp_path):
        """loader 把 frontmatter when_to_use 填入 SkillMdDocument。"""
        _write_skill_md(
            tmp_path,
            "review-tool",
            frontmatter_extra="when_to_use: '\"review my code\", 审查代码'\n",
            body="# Review\n",
        )
        registry = SkillRegistry()
        loader = SkillMdHotLoader(registry, [tmp_path])
        loaded, _ = loader.scan_and_load()
        assert loaded == 1

        skill = registry.get("review-tool")
        assert skill is not None
        doc = skill._doc
        assert doc.when_to_use == '"review my code", 审查代码'

    def test_loader_dash_alias(self, tmp_path):
        """连字符别名 when-to-use 同样被 loader 识别。"""
        _write_skill_md(
            tmp_path,
            "dash-skill",
            frontmatter_extra="when-to-use: '\"do the dash\"'\n",
        )
        registry = SkillRegistry()
        SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
        doc = registry.get("dash-skill")._doc
        assert doc.when_to_use == '"do the dash"'

    def test_loader_missing_field_defaults_empty(self, tmp_path):
        """未声明 when_to_use → 空串 (不参与自动激活)。"""
        _write_skill_md(tmp_path, "plain-skill")
        registry = SkillRegistry()
        SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
        doc = registry.get("plain-skill")._doc
        assert doc.when_to_use == ""


# =====================================================================
# 4. 集成 — InprocSkillAdapter.auto_activate
# =====================================================================


def _make_adapter_with_skillmd(tmp_path, frontmatter_extra: str = ""):
    """构造装载了一个 SKILL.md 技能的 InprocSkillAdapter (空 registry, 不装 builtin)。"""
    from backend.adapters.out.skill.inproc import InprocSkillAdapter

    _write_skill_md(
        tmp_path,
        "review-auto",
        frontmatter_extra=frontmatter_extra or 'when_to_use: "review my code"\n',
        body="# Auto review body\n",
    )
    registry = SkillRegistry()
    SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
    return InprocSkillAdapter(registry=registry)


class TestInprocAutoActivate:
    def test_match_returns_body_block(self, tmp_path):
        """命中消息 → names + body 注入块。"""
        adapter = _make_adapter_with_skillmd(tmp_path)
        result = adapter.auto_activate("please review my code now")
        assert result.activated is True
        assert result.names == ("review-auto",)
        assert "# Auto review body" in result.context_block

    def test_no_match_empty(self, tmp_path):
        """不命中 → 空结果。"""
        adapter = _make_adapter_with_skillmd(tmp_path)
        result = adapter.auto_activate("unrelated message")
        assert result.activated is False
        assert result.context_block == ""

    def test_disabled_skill_excluded(self, tmp_path):
        """set_enabled(False) 的技能不参与自动激活。"""
        adapter = _make_adapter_with_skillmd(tmp_path)
        adapter.set_enabled("review-auto", False)
        result = adapter.auto_activate("please review my code")
        assert result.activated is False

    def test_disable_model_invocation_excluded(self, tmp_path):
        """frontmatter disable-model-invocation: true → 尊重作者意图不自动激活。"""
        adapter = _make_adapter_with_skillmd(
            tmp_path,
            frontmatter_extra=(
                'when_to_use: "review my code"\ndisable-model-invocation: true\n'
            ),
        )
        result = adapter.auto_activate("please review my code")
        assert result.activated is False

    def test_builtin_skills_never_auto_activate(self):
        """builtin 技能 (无 when_to_use) 永不自动激活。"""
        from backend.adapters.out.skill.inproc import InprocSkillAdapter
        from backend.skills import register_all_skills

        registry = SkillRegistry()
        register_all_skills(registry)
        adapter = InprocSkillAdapter(registry=registry)
        # "search" 是 SearchSkill 的触发词, 但 builtin 无 when_to_use
        result = adapter.auto_activate("search for documents about AI")
        assert result.activated is False

    def test_empty_message_safe(self, tmp_path):
        """空消息 → 空结果, 不抛异常。"""
        adapter = _make_adapter_with_skillmd(tmp_path)
        assert adapter.auto_activate("").activated is False

    def test_list_skills_extended_exposes_when_to_use(self, tmp_path):
        """list_skills_extended 输出包含 when_to_use 字段 (YAML 引号已被解析消费)。"""
        adapter = _make_adapter_with_skillmd(tmp_path)
        ext = next(e for e in adapter.list_skills_extended() if e["name"] == "review-auto")
        assert ext["when_to_use"] == "review my code"


# =====================================================================
# 5. 集成 — ChatService system prompt 注入
# =====================================================================


class _FakeActivationResult:
    """模拟 AutoActivationResult 的鸭子类型。"""

    def __init__(self, block: str) -> None:
        self.names = ("fake-skill",) if block else ()
        self.context_block = block


class _FakeSkillPort:
    """带 auto_activate 扩展的假 skills port。"""

    def __init__(self, block: str = "", raise_exc: Exception | None = None) -> None:
        self._block = block
        self._raise = raise_exc
        self.calls: list[str] = []

    def list_skills(self):
        return []

    async def execute(self, name, action, args):  # pragma: no cover - 本测试不用
        raise NotImplementedError

    def auto_activate(self, message: str):
        self.calls.append(message)
        if self._raise is not None:
            raise self._raise
        return _FakeActivationResult(self._block)


class _PlainSkillPort:
    """无 auto_activate 属性的纯 SkillPort 实现。"""

    def list_skills(self):
        return []

    async def execute(self, name, action, args):  # pragma: no cover
        raise NotImplementedError


def _make_chat_service(skills_port):
    """构造带指定 skills port 的 ChatService (其余 mock)。"""
    from unittest.mock import MagicMock

    from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
    from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
    from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
    from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter

    mock_tool_registry = MagicMock()
    mock_tool_registry.list.return_value = []

    return ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="ok")]),
        tools=InprocToolAdapter(registry=mock_tool_registry),
        skills=skills_port,
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )


def _system_prompt_of(service) -> str:
    """取最近一次 LLM 调用的 system message 内容。"""
    messages = service.llm.calls[-1]["messages"]
    system_msgs = [m for m in messages if m.role == Role.SYSTEM]
    assert system_msgs, "LLM 调用应包含 system message"
    return system_msgs[0].content


class TestChatServiceInjection:
    async def test_activation_block_injected_into_system_prompt(self):
        """命中时 context_block 出现在本轮 system prompt。"""
        block = "FAKE-ACTIVATION-BLOCK: skill body here"
        service = _make_chat_service(_FakeSkillPort(block=block))
        sid = await service.storage.create_session()

        await service.run_turn(sid, Message(role=Role.USER, content="trigger message"))

        assert block in _system_prompt_of(service)

    async def test_user_message_stored_unmodified(self):
        """A16 只改 system prompt, 不改持久化的用户消息原文。"""
        service = _make_chat_service(_FakeSkillPort(block="INJECTED"))
        sid = await service.storage.create_session()

        await service.run_turn(sid, Message(role=Role.USER, content="raw user text"))

        stored = await service.storage.get_messages(sid)
        user_msgs = [m for m in stored if m.role == Role.USER]
        assert user_msgs[0].content == "raw user text"

    async def test_no_auto_activate_attr_no_injection(self):
        """skills port 无 auto_activate → 零注入, 轮次正常。"""
        service = _make_chat_service(_PlainSkillPort())
        sid = await service.storage.create_session()

        await service.run_turn(sid, Message(role=Role.USER, content="hello"))

        assert "system-reminder" not in _system_prompt_of(service)

    async def test_auto_activate_raises_degrades_silently(self):
        """auto_activate 抛错 → 静默降级, 轮次不中断。"""
        service = _make_chat_service(_FakeSkillPort(raise_exc=RuntimeError("boom")))
        sid = await service.storage.create_session()

        result = await service.run_turn(sid, Message(role=Role.USER, content="hello"))

        assert result[1].content == "ok"

    async def test_magicmock_skills_port_safe(self):
        """MagicMock skills (自动属性) 不产生脏注入 — 回归保护。"""
        from unittest.mock import MagicMock

        service = _make_chat_service(MagicMock())
        sid = await service.storage.create_session()

        await service.run_turn(sid, Message(role=Role.USER, content="hello"))

        # MagicMock().auto_activate() 返回 MagicMock, 非 str → 视为无激活
        assert "MagicMock" not in _system_prompt_of(service)


class TestSkillActivationBlockHelper:
    def test_empty_message_returns_empty(self):
        """空消息 → 空串。"""
        assert _skill_activation_block("", _FakeSkillPort(block="x")) == ""

    def test_none_skills_returns_empty(self):
        """skills=None → 空串。"""
        assert _skill_activation_block("hello", None) == ""

    def test_block_prefixed_with_newlines(self):
        """非空块前置双换行 (便于直接 += 拼接)。"""
        result = _skill_activation_block("hello", _FakeSkillPort(block="BLOCK"))
        assert result == "\n\nBLOCK"


# =====================================================================
# 6. 审查回归 (M2 尺寸闸门 / L1-L4 边界)
# =====================================================================


class TestSizeCap:
    def test_oversized_skill_skipped_smaller_included(self):
        """超限技能整块跳过 (first-fit), 后续较小的命中技能仍激活。"""
        from backend.skills.skill_md.auto_activation import (
            MAX_CONTEXT_BLOCK_CHARS,
        )

        docs = [
            _doc("huge", when_to_use='"trigger"', body="x" * (MAX_CONTEXT_BLOCK_CHARS + 1)),
            _doc("small", when_to_use='"trigger"', body="small body"),
        ]
        result = auto_activate("trigger", docs)
        assert result.names == ("small",)
        assert "small body" in result.context_block

    def test_single_oversized_match_yields_empty(self):
        """唯一命中技能即超限 → 无激活 (显式 slash 调用不受此限)。"""
        from backend.skills.skill_md.auto_activation import (
            MAX_CONTEXT_BLOCK_CHARS,
        )

        docs = [
            _doc("huge", when_to_use='"trigger"', body="x" * (MAX_CONTEXT_BLOCK_CHARS * 2))
        ]
        result = auto_activate("trigger", docs)
        assert result.activated is False

    def test_bodies_within_cap_all_included(self):
        """总尺寸未超限的多个技能全部激活。"""
        docs = [_doc(f"s{i}", when_to_use='"trigger"', body="y" * 1000) for i in range(3)]
        result = auto_activate("trigger", docs)
        assert len(result.names) == 3


class TestTriggerExtractionEdgeCases:
    def test_quoted_use_when_phrase_kept(self):
        """引号提取路径不过滤 use-when 元描述 (参考实现原始行为, 回归保护)。"""
        triggers = extract_triggers('"Use when reviewing code"')
        assert "use when reviewing code" in triggers

    def test_curly_quotes_stripped_in_comma_segments(self):
        """逗号段两端的弯引号被剥离, 不产出死触发词。"""
        triggers = extract_triggers("“写周报”,总结")
        assert "写周报" in triggers
        assert "总结" in triggers
        assert not any("“" in t or "”" in t for t in triggers)

    def test_all_single_char_triggers_yield_empty(self):
        """when_to_use 全是单字符 → 无有效触发词 → 不激活。"""
        triggers = extract_triggers('"a", "b", c')
        assert triggers == []
        docs = [_doc("s", when_to_use='"a", "b", c')]
        assert auto_activate("a b c anything", docs).activated is False


class TestLoaderKeyPrecedence:
    def test_underscore_wins_over_dash_alias(self, tmp_path):
        """双键共存时 underscore 主键胜出 (loader 与 frontmatter 一致)。"""
        _write_skill_md(
            tmp_path,
            "dual-key",
            frontmatter_extra=(
                "when_to_use: '\"underscore wins\"'\n"
                "when-to-use: '\"dash alias\"'\n"
            ),
        )
        registry = SkillRegistry()
        SkillMdHotLoader(registry, [tmp_path]).scan_and_load()
        doc = registry.get("dual-key")._doc
        assert doc.when_to_use == '"underscore wins"'

    def test_explicit_null_falls_back_to_alias_validation(self):
        """主键显式 null 时回落校验别名 (L3: 与 loader 取值优先级一致)。"""
        with pytest.raises(SkillMdParseError, match="when_to_use"):
            parse(
                "---\nname: demo\ndescription: demo skill\n"
                "when_to_use: null\nwhen-to-use: 42\n---\nbody\n"
            )


class TestAdapterDegradationAndReload:
    def test_adapter_internal_error_degrades_to_empty(self, tmp_path, monkeypatch):
        """auto_activate 内部故障 → 空结果, 绝不外抛 (best-effort 契约)。"""
        import backend.skills.skill_md.auto_activation as aa

        adapter = _make_adapter_with_skillmd(tmp_path)

        def _boom(message, docs):
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr(aa, "auto_activate", _boom)
        result = adapter.auto_activate("please review my code")
        assert result.activated is False
        assert result.context_block == ""

    def test_hot_reload_updates_when_to_use(self, tmp_path):
        """热重载后 when_to_use 与自动激活跟随新内容。"""
        path = _write_skill_md(
            tmp_path, "evolving", frontmatter_extra='when_to_use: "old trigger"\n'
        )
        registry = SkillRegistry()
        loader = SkillMdHotLoader(registry, [tmp_path])
        loader.scan_and_load()
        # YAML 消费外层引号, 字段值为裸短语
        assert registry.get("evolving")._doc.when_to_use == "old trigger"

        _write_skill_md(
            tmp_path, "evolving", frontmatter_extra='when_to_use: "new trigger"\n'
        )
        assert loader.check_for_updates() == ["evolving"]
        assert loader.hot_reload("evolving") is True

        doc = registry.get("evolving")._doc
        assert doc.when_to_use == "new trigger"
        assert auto_activate("hit new trigger", [doc]).activated is True
        assert auto_activate("hit old trigger", [doc]).activated is False
        assert path.is_file()  # 原文件被 helper 原地覆写
