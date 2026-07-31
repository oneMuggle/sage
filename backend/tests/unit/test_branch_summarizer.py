"""
分支摘要式上下文压缩测试 (A28, ported from pi coding-agent)

覆盖：
- 会话序列化（user / assistant / tool 三角色 + 工具调用 + 截断 +
  嵌套摘要渲染）
- 文件操作追踪（工具调用提取 / block 风格 / 嵌套摘要 details 折叠 /
  去重计算 / XML 格式化）
- token 预算选取（最新优先 / 全量文件扫描 / 摘要消息宽限 / 边界）
- 不可变性（prepare / summarize_branch 不修改输入）
- 摘要 prompt 构造（默认 / 追加 / 替换指令）
- BranchSummarizer（构造校验 / 成功 / 空分支 / 失败容错 / 前导开关）
- Layer 3 适配器（成功返回 / 失败抛异常 / 空分支占位放行 /
  忽略压缩器泛化 prompt）
- 上下文消息注入（details 元数据）
- 与 ContextCompactor (A12) 的集成（注入 / 降级 / 显式优先）
"""

import copy
import json
from typing import Any, Callable, Dict, List, Tuple

import pytest

from backend.application.services.branch_summarizer import (
    BRANCH_SUMMARY_PREAMBLE,
    BRANCH_SUMMARY_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT,
    BranchSummarizer,
    BranchSummaryResult,
    FileOperations,
    build_branch_prompt,
    compute_file_lists,
    extract_file_ops,
    format_file_operations,
    prepare_branch_messages,
    serialize_conversation,
)
from backend.application.services.context_compactor import (
    SUMMARY_PREFIX,
    ContextCompactor,
)

# ── 测试辅助 ────────────────────────────────────────────


def _msg(role: str, content: Any, **extra: Any) -> Dict[str, Any]:
    """构造 OpenAI 风格 dict 消息。"""
    message: Dict[str, Any] = {"role": role, "content": content}
    message.update(extra)
    return message


def _assistant_tool_call(name: str, args: Dict[str, Any], call_id: str = "c1") -> Dict[str, Any]:
    """构造带 OpenAI 风格 tool_calls 的 assistant 消息。"""
    return _msg(
        "assistant",
        "",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    )


def _fake_llm(response: str) -> Tuple[Callable[[str], Any], List[str]]:
    """构造记录 prompt 的假 LLM 补全函数。"""
    prompts: List[str] = []

    async def complete(prompt: str) -> str:
        prompts.append(prompt)
        return response

    return complete, prompts


def _failing_llm(error: Exception) -> Callable[[str], Any]:
    """构造总是抛异常的假 LLM 补全函数。"""

    async def complete(prompt: str) -> str:
        raise error

    return complete


# ── 会话序列化 ──────────────────────────────────────────


class TestSerializeConversation:
    """serialize_conversation：消息 → 纯文本转录"""

    def test_serializes_user_and_assistant_text(self):
        messages = [
            _msg("user", "Fix the login bug"),
            _msg("assistant", "I found the issue in auth.py"),
        ]

        text = serialize_conversation(messages)

        assert "[User]: Fix the login bug" in text
        assert "[Assistant]: I found the issue in auth.py" in text

    def test_skips_system_messages(self):
        messages = [
            _msg("system", "You are Sage."),
            _msg("user", "hello"),
        ]

        text = serialize_conversation(messages)

        assert "You are Sage." not in text
        assert "[User]: hello" in text

    def test_serializes_openai_style_tool_calls(self):
        messages = [
            _assistant_tool_call("read_file", {"path": "/repo/main.py"}),
        ]

        text = serialize_conversation(messages)

        assert "[Assistant tool calls]: " in text
        assert 'read_file(path="/repo/main.py")' in text

    def test_serializes_block_style_tool_calls(self):
        messages = [
            _msg(
                "assistant",
                [{"type": "tool_use", "name": "edit_file", "input": {"path": "/a.py"}}],
            ),
        ]

        text = serialize_conversation(messages)

        assert 'edit_file(path="/a.py")' in text

    def test_serializes_tool_result_role_with_truncation(self):
        messages = [_msg("tool", "y" * 3000, tool_call_id="c1")]

        text = serialize_conversation(messages)

        assert "[Tool result]: " in text
        assert "[... 1000 more characters truncated]" in text

    def test_serializes_user_embedded_tool_result_blocks(self):
        messages = [
            _msg(
                "user",
                [
                    {"type": "tool_result", "tool_call_id": "c1", "content": "file body here"},
                ],
            ),
        ]

        text = serialize_conversation(messages)

        assert "[Tool result]: file body here" in text

    def test_truncates_long_tool_call_argument_values(self):
        """write_file 的文件正文不应撑爆摘要 prompt"""
        messages = [
            _assistant_tool_call(
                "write_file", {"path": "/a.py", "content": "z" * 500}, call_id="c2"
            ),
        ]

        text = serialize_conversation(messages)

        assert 'path="/a.py"' in text
        assert "[200 more chars]" in text
        assert "z" * 500 not in text

    def test_renders_thinking_blocks_joined_by_newline(self):
        messages = [
            _msg(
                "assistant",
                [
                    {"type": "thinking", "thinking": "First thought"},
                    {"type": "thinking", "thinking": "Second thought"},
                ],
            ),
        ]

        text = serialize_conversation(messages)

        assert "[Assistant thinking]: First thought\nSecond thought" in text

    def test_renders_summary_system_messages_as_earlier_summary(self):
        """H1：嵌套摘要 system 消息必须进入转录，不能白耗预算宽限"""
        messages = [
            _msg(
                "system",
                f"{BRANCH_SUMMARY_PREAMBLE}Prior branch fixed the login bug",
                details={"branch_summary": True},
            ),
            _msg("user", "continue please"),
        ]

        text = serialize_conversation(messages)

        assert "[Earlier summary]: " in text
        assert "Prior branch fixed the login bug" in text

    def test_compaction_marker_system_messages_rendered_too(self):
        """A12 压缩摘要消息（内容前缀识别）同样进入转录"""
        messages = [
            _msg("system", f"{SUMMARY_PREFIX} (covers 5 earlier messages)\nold digest"),
            _msg("user", "hello"),
        ]

        text = serialize_conversation(messages)

        assert "[Earlier summary]: " in text
        assert "old digest" in text

    def test_empty_messages_serialize_to_empty_string(self):
        assert serialize_conversation([]) == ""

    def test_empty_content_messages_produce_no_parts(self):
        messages = [_msg("user", ""), _msg("assistant", "")]

        assert serialize_conversation(messages) == ""


# ── 文件操作追踪 ────────────────────────────────────────


class TestFileOperations:
    """extract_file_ops / compute_file_lists / format_file_operations"""

    def test_extracts_read_write_edit_from_tool_calls(self):
        messages = [
            _assistant_tool_call("read_file", {"path": "/a.py"}, call_id="c1"),
            _assistant_tool_call("write_file", {"path": "/b.py"}, call_id="c2"),
            _assistant_tool_call("edit_file", {"file_path": "/c.py"}, call_id="c3"),
            _assistant_tool_call("view", {"path": "/d.py"}, call_id="c4"),
        ]

        ops = extract_file_ops(messages)

        assert ops.read == {"/a.py", "/d.py"}
        assert ops.written == {"/b.py"}
        assert ops.edited == {"/c.py"}

    def test_ignores_unknown_tools_and_missing_paths(self):
        messages = [
            _assistant_tool_call("run_shell", {"command": "ls"}, call_id="c1"),
            _assistant_tool_call("read_file", {}, call_id="c2"),
            _msg("user", "no tool calls here"),
        ]

        ops = extract_file_ops(messages)

        assert ops.read == set()
        assert ops.written == set()
        assert ops.edited == set()

    def test_extracts_from_block_style_tool_calls(self):
        """T2：block 风格（tool_use + input）的工具调用同样被提取"""
        messages = [
            _msg(
                "assistant",
                [{"type": "tool_use", "name": "edit_file", "input": {"path": "/x.py"}}],
            ),
            _msg(
                "assistant",
                [{"type": "tool_call", "name": "read_file", "arguments": {"path": "/y.py"}}],
            ),
        ]

        ops = extract_file_ops(messages)

        assert ops.edited == {"/x.py"}
        assert ops.read == {"/y.py"}

    def test_folds_nested_summary_details_file_lists(self):
        """T4/M1：嵌套分支摘要 details 中的文件清单被折叠累计"""
        messages = [
            _msg(
                "system",
                "summary text",
                details={
                    "branch_summary": True,
                    "read_files": ["/old-read.py"],
                    "modified_files": ["/old-mod.py"],
                },
            ),
        ]

        ops = extract_file_ops(messages)

        assert ops.read == {"/old-read.py"}
        # modified 归入 edited，与 written 一起去重
        assert ops.edited == {"/old-mod.py"}

        read_files, modified_files = compute_file_lists(ops)
        assert read_files == ["/old-read.py"]
        assert modified_files == ["/old-mod.py"]

    def test_folds_details_ignores_non_string_entries(self):
        messages = [
            _msg(
                "system",
                "s",
                details={"branch_summary": True, "read_files": [None, 42, "/ok.py", ""]},
            ),
        ]

        ops = extract_file_ops(messages)

        assert ops.read == {"/ok.py"}

    def test_accumulates_into_existing_file_ops(self):
        ops = FileOperations(read={"/seed.py"})
        messages = [_assistant_tool_call("read_file", {"path": "/a.py"})]

        result = extract_file_ops(messages, ops)

        assert result is ops
        assert ops.read == {"/seed.py", "/a.py"}

    def test_compute_file_lists_dedupes_modified_from_read(self):
        """改过的文件不再出现在 read_files（modified = written ∪ edited）"""
        ops = FileOperations(
            read={"/a.py", "/b.py", "/c.py"},
            written={"/b.py"},
            edited={"/c.py"},
        )

        read_files, modified_files = compute_file_lists(ops)

        assert read_files == ["/a.py"]
        assert modified_files == ["/b.py", "/c.py"]

    def test_compute_file_lists_sorts_output(self):
        ops = FileOperations(read={"/z.py", "/a.py"})

        read_files, modified_files = compute_file_lists(ops)

        assert read_files == ["/a.py", "/z.py"]
        assert modified_files == []

    def test_format_file_operations_renders_xml_sections(self):
        text = format_file_operations(["/a.py"], ["/b.py", "/c.py"])

        assert "<read-files>\n/a.py\n</read-files>" in text
        assert "<modified-files>\n/b.py\n/c.py\n</modified-files>" in text
        assert text.startswith("\n\n")

    def test_format_file_operations_empty_when_no_files(self):
        assert format_file_operations([], []) == ""

    def test_format_file_operations_omits_empty_sections(self):
        text = format_file_operations([], ["/b.py"])

        assert "<read-files>" not in text
        assert "<modified-files>" in text


# ── token 预算选取 ──────────────────────────────────────


class TestPrepareBranchMessages:
    """prepare_branch_messages：最新优先 + 文件全量扫描 + 摘要宽限"""

    def test_selects_newest_first_within_budget(self):
        # chars_per_token=1.0 → token 数 ≈ 字符数（role 4 + content 100 = 104/条）
        messages = [_msg("user", f"message {i} " + "x" * 90) for i in range(10)]

        selected, _ops, total = prepare_branch_messages(messages, token_budget=320, chars_per_token=1.0)

        assert [m["content"][:9] for m in selected] == [
            "message 7",
            "message 8",
            "message 9",
        ]
        assert total > 0

    def test_zero_budget_means_unlimited(self):
        messages = [_msg("user", "m" * 100) for _ in range(5)]

        selected, _ops, _total = prepare_branch_messages(messages, token_budget=0)

        assert len(selected) == 5

    def test_collects_file_ops_from_all_entries_regardless_of_budget(self):
        """早期消息被预算丢弃，其文件操作仍进入清单（累计追踪）"""
        early = _assistant_tool_call("write_file", {"path": "/early.py"}, call_id="c1")
        late = _msg("user", "recent question " + "x" * 400)

        # late ≈ 420 token（424 字符）；early ≈ 31 token（role + 工具参数）
        # 预算 430：装下 late 后装不下 early → early 被丢弃
        selected, ops, _total = prepare_branch_messages(
            [early, late], token_budget=430, chars_per_token=1.0
        )

        assert early not in selected
        assert ops.written == {"/early.py"}

    def test_summary_message_gets_budget_grace(self):
        """摘要类消息：已用 < 90% 预算时破例纳入"""
        summary = _msg(
            "system",
            "s" * 200,
            details={"branch_summary": True},
        )
        regular = [_msg("user", "u" * 50) for _ in range(4)]
        messages = [summary] + regular

        # 4 条 regular 各 54 token = 216；summary 206 → 共 422 > 400
        # 但 216 < 400 * 0.9 = 360 → 宽限纳入
        selected, _ops, _total = prepare_branch_messages(
            messages, token_budget=400, chars_per_token=1.0
        )

        assert summary in selected
        assert len(selected) == 5

    def test_summary_message_excluded_when_budget_mostly_used(self):
        """M2：宽限拒绝分支 —— regular 已占 ≥90% 预算时摘要不破例纳入"""
        summary = _msg(
            "system",
            "s" * 200,
            details={"branch_summary": True},
        )
        regular = [_msg("user", "u" * 90) for _ in range(4)]
        messages = [summary] + regular

        # 4 条 regular 各 94 token = 376；376 >= 400 * 0.9 = 360
        # summary 206 → 376 + 206 > 400 且已用 ≥90% → 不纳入
        selected, _ops, _total = prepare_branch_messages(
            messages, token_budget=400, chars_per_token=1.0
        )

        assert summary not in selected
        assert len(selected) == 4

    def test_block_style_tool_call_args_counted_once(self):
        """M1：block 风格工具调用参数只计一次，不因双重计数少选消息"""
        big_path = "x" * 400
        messages = [
            _msg(
                "assistant",
                [{"type": "tool_use", "name": "read_file", "input": {"path": big_path}}],
            ),
        ]

        # args json ≈ 412 字符 + role 9 ≈ 421 token；双重计数会 ≈ 833
        # 预算 500：单次计数装得下，双重计数装不下
        selected, _ops, total = prepare_branch_messages(
            messages, token_budget=500, chars_per_token=1.0
        )

        assert len(selected) == 1
        assert total < 500

    def test_non_summary_message_excluded_without_grace(self):
        """同样大小但非摘要消息：不享受宽限"""
        plain = _msg("system", "p" * 200)
        regular = [_msg("user", "u" * 50) for _ in range(4)]
        messages = [plain] + regular

        selected, _ops, _total = prepare_branch_messages(
            messages, token_budget=400, chars_per_token=1.0
        )

        assert plain not in selected
        assert len(selected) == 4

    def test_compaction_marker_content_detected_as_summary(self):
        summary = _msg("system", f"{SUMMARY_PREFIX} (covers 5 earlier messages)\nold digest")

        assert prepare_branch_messages([summary], 0)[0] == [summary]

    def test_single_newest_message_over_budget_selects_nothing(self):
        """T5：最新一条即超预算（非摘要）→ 选中为空"""
        messages = [_msg("user", "u" * 200)]

        selected, _ops, total = prepare_branch_messages(
            messages, token_budget=50, chars_per_token=1.0
        )

        assert selected == []
        assert total == 0

    def test_rejects_negative_budget(self):
        with pytest.raises(ValueError, match="token_budget"):
            prepare_branch_messages([], token_budget=-1)

    def test_rejects_non_positive_chars_per_token(self):
        with pytest.raises(ValueError, match="chars_per_token"):
            prepare_branch_messages([], chars_per_token=0)


# ── 摘要 prompt 构造 ────────────────────────────────────


class TestBuildBranchPrompt:
    """build_branch_prompt：默认 / 追加 / 替换指令"""

    def test_wraps_conversation_in_tags_with_default_instructions(self):
        prompt = build_branch_prompt("transcript text")

        assert "<conversation>\ntranscript text\n</conversation>" in prompt
        assert "## Goal" in prompt
        assert "## Next Steps" in prompt

    def test_appends_custom_instructions_as_additional_focus(self):
        prompt = build_branch_prompt("t", custom_instructions="focus on DB migrations")

        assert "Additional focus: focus on DB migrations" in prompt
        assert BRANCH_SUMMARY_PROMPT in prompt

    def test_replace_instructions_drops_default_prompt(self):
        prompt = build_branch_prompt(
            "t", custom_instructions="Just list files.", replace_instructions=True
        )

        assert prompt.endswith("Just list files.")
        assert "## Goal" not in prompt

    def test_replace_flag_without_custom_instructions_keeps_default(self):
        prompt = build_branch_prompt("t", replace_instructions=True)

        assert "## Goal" in prompt


# ── BranchSummarizer ────────────────────────────────────


class TestBranchSummarizerInit:
    """构造参数校验"""

    def test_rejects_non_callable_llm(self):
        with pytest.raises(ValueError, match="llm_complete"):
            BranchSummarizer(llm_complete="not callable")

    def test_rejects_non_positive_context_window(self):
        with pytest.raises(ValueError, match="context_window"):
            BranchSummarizer(llm_complete=_fake_llm("x")[0], context_window=0)

    def test_rejects_non_positive_reserve_tokens(self):
        with pytest.raises(ValueError, match="reserve_tokens"):
            BranchSummarizer(llm_complete=_fake_llm("x")[0], reserve_tokens=0)

    def test_rejects_reserve_not_smaller_than_window(self):
        with pytest.raises(ValueError, match="reserve_tokens"):
            BranchSummarizer(
                llm_complete=_fake_llm("x")[0], context_window=100, reserve_tokens=100
            )

    def test_rejects_non_positive_chars_per_token(self):
        with pytest.raises(ValueError, match="chars_per_token"):
            BranchSummarizer(llm_complete=_fake_llm("x")[0], chars_per_token=0)


class TestSummarizeBranch:
    """summarize_branch：成功 / 空分支 / 失败容错 / 预算"""

    async def test_happy_path_builds_structured_summary(self):
        llm, prompts = _fake_llm("## Goal\nFix login\n## Next Steps\n1. deploy")
        summarizer = BranchSummarizer(llm_complete=llm)
        messages = [
            _msg("user", "Please read the config"),
            _assistant_tool_call("read_file", {"path": "/repo/a.py"}),
            _msg("tool", "config body", tool_call_id="c1"),
        ]

        result = await summarizer.summarize_branch(messages)

        assert result.error is None
        assert result.summary is not None
        assert result.summary.startswith(BRANCH_SUMMARY_PREAMBLE)
        assert "## Goal" in result.summary
        assert "<read-files>\n/repo/a.py\n</read-files>" in result.summary
        assert result.read_files == ["/repo/a.py"]
        assert result.modified_files == []

        assert len(prompts) == 1
        assert SUMMARIZATION_SYSTEM_PROMPT in prompts[0]
        assert "<conversation>" in prompts[0]
        assert "[User]: Please read the config" in prompts[0]
        assert "## Goal" in prompts[0]

    async def test_empty_messages_returns_placeholder_without_llm_call(self):
        llm, prompts = _fake_llm("unused")
        summarizer = BranchSummarizer(llm_complete=llm)

        result = await summarizer.summarize_branch([])

        assert result.summary == "No content to summarize"
        assert result.error is None
        assert prompts == []

    async def test_system_only_messages_skip_llm_call(self):
        """system 消息不进转录 → 转录为空 → 不调 LLM"""
        llm, prompts = _fake_llm("unused")
        summarizer = BranchSummarizer(llm_complete=llm)

        result = await summarizer.summarize_branch([_msg("system", "You are Sage.")])

        assert result.summary == "No content to summarize"
        assert prompts == []

    async def test_llm_failure_returns_error_without_raising(self):
        summarizer = BranchSummarizer(llm_complete=_failing_llm(RuntimeError("LLM unavailable")))

        result = await summarizer.summarize_branch([_msg("user", "hello")])

        assert result.summary is None
        assert result.error == "LLM unavailable"

    async def test_empty_llm_response_returns_error(self):
        summarizer = BranchSummarizer(llm_complete=_fake_llm("   ")[0])

        result = await summarizer.summarize_branch([_msg("user", "hello")])

        assert result.summary is None
        assert result.error == "LLM returned empty summary"

    async def test_include_preamble_false_omits_preamble(self):
        summarizer = BranchSummarizer(llm_complete=_fake_llm("body text")[0])

        result = await summarizer.summarize_branch(
            [_msg("user", "hello")], include_preamble=False
        )

        assert result.summary == "body text"
        assert BRANCH_SUMMARY_PREAMBLE not in result.summary

    async def test_custom_instructions_reach_prompt(self):
        llm, prompts = _fake_llm("ok")
        summarizer = BranchSummarizer(llm_complete=llm)

        await summarizer.summarize_branch(
            [_msg("user", "hello")], custom_instructions="emphasize errors"
        )

        assert "Additional focus: emphasize errors" in prompts[0]

    async def test_token_budget_keeps_recent_drops_old(self):
        """预算不足时优先保留分支尾部（最新上下文）"""
        old_messages = [_msg("user", "OLD-UNIQUE " + "x" * 1000) for _ in range(5)]
        recent = [_msg("user", "NEW-UNIQUE question")]
        llm, prompts = _fake_llm("ok")
        # 预算 = 1000 - 800 = 200 token（默认 4 字符/token ≈ 800 字符）
        summarizer = BranchSummarizer(
            llm_complete=llm, context_window=1000, reserve_tokens=800
        )

        result = await summarizer.summarize_branch(old_messages + recent)

        assert result.error is None
        assert "NEW-UNIQUE" in prompts[0]
        assert "OLD-UNIQUE" not in prompts[0]

    async def test_nested_summary_reaches_llm_prompt(self):
        """T1/H1：含嵌套摘要的分支再摘要时，摘要内容必须对 LLM 可见"""
        llm, prompts = _fake_llm("ok")
        summarizer = BranchSummarizer(llm_complete=llm)
        messages = [
            BranchSummarizer.to_context_message(
                BranchSummaryResult(summary="Prior branch fixed the login bug"),
                from_id="branch-7",
            ),
            _msg("user", "now continue with the API work"),
        ]

        result = await summarizer.summarize_branch(messages)

        assert result.error is None
        assert "[Earlier summary]: " in prompts[0]
        assert "Prior branch fixed the login bug" in prompts[0]

    async def test_all_messages_over_budget_returns_placeholder(self):
        """T5 端到端：全部消息超预算 → 选中为空 → 不调 LLM"""
        llm, prompts = _fake_llm("unused")
        # 预算 = 200 - 100 = 100 token（≈400 字符），单条消息 ~2000 字符
        summarizer = BranchSummarizer(
            llm_complete=llm, context_window=200, reserve_tokens=100
        )

        result = await summarizer.summarize_branch([_msg("user", "u" * 2000)])

        assert result.summary == "No content to summarize"
        assert prompts == []


# ── 不可变性 ────────────────────────────────────────────


class TestImmutability:
    """T3：所有操作不修改输入消息"""

    def test_prepare_does_not_mutate_input(self):
        messages = [
            _assistant_tool_call("read_file", {"path": "/a.py"}),
            _msg("user", "question"),
        ]
        snapshot = copy.deepcopy(messages)

        prepare_branch_messages(messages, token_budget=0)

        assert messages == snapshot

    async def test_summarize_branch_does_not_mutate_input(self):
        summarizer = BranchSummarizer(llm_complete=_fake_llm("ok")[0])
        messages = [
            _assistant_tool_call("write_file", {"path": "/b.py"}),
            _msg("user", "do the thing"),
        ]
        snapshot = copy.deepcopy(messages)

        await summarizer.summarize_branch(messages)

        assert messages == snapshot


# ── Layer 3 适配器 ──────────────────────────────────────


class TestLayer3Adapter:
    """as_layer3_summarizer：与 ContextCompactor.Summarizer 同构"""

    async def test_returns_summary_without_preamble(self):
        llm, prompts = _fake_llm("Structured output")
        summarizer = BranchSummarizer(llm_complete=llm)
        adapter = summarizer.as_layer3_summarizer()

        text = await adapter([_msg("user", "hello")], "compactor prompt")

        assert text == "Structured output"
        # 压缩器 prompt 按协议传入但刻意不用（避免指令重复噪声）
        assert "Additional focus" not in prompts[0]
        assert BRANCH_SUMMARY_PROMPT in prompts[0]

    async def test_empty_branch_passes_through_placeholder(self):
        """空分支 → 占位文本是 truthy，适配器放行（固化契约）"""
        summarizer = BranchSummarizer(llm_complete=_fake_llm("unused")[0])
        adapter = summarizer.as_layer3_summarizer()

        text = await adapter([], "compactor prompt")

        assert text == "No content to summarize"

    async def test_raises_runtime_error_on_llm_failure(self):
        """刻意抛异常：触发 compact_with_summary 的 Layer 2 回退"""
        summarizer = BranchSummarizer(llm_complete=_failing_llm(RuntimeError("LLM unavailable")))
        adapter = summarizer.as_layer3_summarizer()

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            await adapter([_msg("user", "hello")], "prompt")

    async def test_raises_on_empty_summary(self):
        summarizer = BranchSummarizer(llm_complete=_fake_llm("  ")[0])
        adapter = summarizer.as_layer3_summarizer()

        with pytest.raises(RuntimeError, match="empty summary"):
            await adapter([_msg("user", "hello")], "prompt")


# ── 上下文注入 ──────────────────────────────────────────


class TestToContextMessage:
    """to_context_message：摘要 → 可注入的 system 消息"""

    def test_builds_system_message_with_details_metadata(self):
        result = BranchSummaryResult(
            summary="the summary", read_files=["/a.py"], modified_files=["/b.py"]
        )

        message = BranchSummarizer.to_context_message(result, from_id="branch-42")

        assert message["role"] == "system"
        assert message["content"] == "the summary"
        assert message["details"]["branch_summary"] is True
        assert message["details"]["from_id"] == "branch-42"
        assert message["details"]["read_files"] == ["/a.py"]
        assert message["details"]["modified_files"] == ["/b.py"]

    def test_rejects_failed_result(self):
        result = BranchSummaryResult(error="LLM unavailable")

        with pytest.raises(ValueError, match="failed summary"):
            BranchSummarizer.to_context_message(result)


# ── 与 ContextCompactor (A12) 集成 ─────────────────────


class TestCompactorIntegration:
    """ContextCompactor(branch_summarizer=...) 的 Layer 3 行为"""

    def _compactor(self, summarizer: Any = None) -> ContextCompactor:
        return ContextCompactor(
            context_window=400,
            compact_threshold_ratio=0.5,
            sliding_window_size=4,
            branch_summarizer=summarizer,
        )

    def _over_budget_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        messages = [_msg("system", "You are Sage.")]
        for i in range(count):
            messages.append(_msg("user", f"message {i} " + "x" * 100))
        return messages

    async def test_injected_branch_summarizer_used_for_layer3(self):
        summarizer = BranchSummarizer(llm_complete=_fake_llm("## Goal\nTest goal")[0])
        compactor = self._compactor(summarizer)

        result = await compactor.compact_with_summary(self._over_budget_messages())

        # system + 摘要 + 最近 4 条
        assert len(result) == 6
        assert result[1]["content"].startswith(SUMMARY_PREFIX)
        assert "## Goal" in result[1]["content"]
        assert "(covers 6 earlier messages)" in result[1]["content"]
        # 适配器不带分支前导（压缩器自带 SUMMARY_PREFIX）
        assert BRANCH_SUMMARY_PREAMBLE not in result[1]["content"]

    async def test_layer3_failure_falls_back_to_layer2(self):
        summarizer = BranchSummarizer(
            llm_complete=_failing_llm(RuntimeError("LLM unavailable"))
        )
        compactor = self._compactor(summarizer)
        messages = self._over_budget_messages()

        result = await compactor.compact_with_summary(messages)

        assert result == compactor.compact(messages)
        assert all(not str(m.get("content", "")).startswith(SUMMARY_PREFIX) for m in result)

    async def test_explicit_summarize_takes_precedence(self):
        llm, prompts = _fake_llm("branch summary")
        summarizer = BranchSummarizer(llm_complete=llm)
        compactor = self._compactor(summarizer)

        async def explicit(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            return "explicit summary"

        result = await compactor.compact_with_summary(self._over_budget_messages(), explicit)

        assert "explicit summary" in result[1]["content"]
        assert prompts == []

    def test_constructor_rejects_invalid_branch_summarizer(self):
        with pytest.raises(ValueError, match="as_layer3_summarizer"):
            ContextCompactor(branch_summarizer=object())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
