"""
三层上下文压缩测试 (A12 from LLM_Simple)

覆盖：
- token 估算与压缩阈值检测
- Layer 1 MicroCompact（read / error-aware / head-tail / generic 四策略）
- 错误感知截断 _truncate_error_aware（保留错误诊断上下文）
- 工具名解析三路径（显式字段 / tool_call_id 反查 / 内容标记）
- Layer 2 滑窗（system + 最近 N 条）
- Layer 3 LLM Summary（可选 + 失败回退）
- 不可变性（输入消息不被修改）
"""

from typing import Any, Dict, List

import pytest

from backend.application.services.context_compactor import (
    SUMMARY_PREFIX,
    ContextCompactor,
)


def _msg(role: str, content: Any, **extra: Any) -> Dict[str, Any]:
    """构造 OpenAI 风格 dict 消息。"""
    message: Dict[str, Any] = {"role": role, "content": content}
    message.update(extra)
    return message


def _lines(n: int) -> str:
    """生成 n 行文本。"""
    return "\n".join(f"line {i} content" for i in range(n))


# ── token 估算 ────────────────────────────────────────────


class TestTokenEstimation:
    """token 估算与阈值检测"""

    def test_estimate_tokens_empty(self):
        """空列表 → 0"""
        compactor = ContextCompactor()
        assert compactor.estimate_tokens([]) == 0

    def test_estimate_tokens_string_content(self):
        """字符串内容：len / 4"""
        compactor = ContextCompactor()
        messages = [_msg("user", "x" * 400)]
        assert compactor.estimate_tokens(messages) == 100

    def test_estimate_tokens_list_blocks(self):
        """list 形式 content 的 text 块"""
        compactor = ContextCompactor()
        messages = [_msg("user", [{"type": "text", "text": "y" * 40}])]
        assert compactor.estimate_tokens(messages) == 10

    def test_estimate_tokens_none_content(self):
        """content 为 None 不报错"""
        compactor = ContextCompactor()
        messages = [_msg("assistant", None)]
        assert compactor.estimate_tokens(messages) == 0

    def test_should_compact_below_threshold(self):
        """未超阈值 → False（400 chars = 100 tokens，阈值恰好 100）"""
        compactor = ContextCompactor(context_window=200, compact_threshold_ratio=0.5)
        messages = [_msg("user", "x" * 400)]
        assert compactor.should_compact(messages) is False

    def test_should_compact_above_threshold(self):
        """超阈值 → True"""
        compactor = ContextCompactor(context_window=200, compact_threshold_ratio=0.5)
        messages = [_msg("user", "x" * 404)]
        assert compactor.should_compact(messages) is True


class TestConstructorValidation:
    """构造参数校验"""

    def test_rejects_bad_ratio(self):
        """ratio 必须在 (0, 1)"""
        with pytest.raises(ValueError, match="compact_threshold_ratio"):
            ContextCompactor(compact_threshold_ratio=1.5)

    def test_rejects_non_positive_window(self):
        """context_window 必须为正"""
        with pytest.raises(ValueError, match="context_window"):
            ContextCompactor(context_window=0)

    def test_rejects_non_positive_window_size(self):
        """sliding_window_size 必须为正"""
        with pytest.raises(ValueError, match="sliding_window_size"):
            ContextCompactor(sliding_window_size=0)


# ── Layer 1: MicroCompact ────────────────────────────────


class TestMicroCompact:
    """Layer 1 按工具类型策略截断"""

    def test_short_content_unchanged(self):
        """短内容不触发截断"""
        compactor = ContextCompactor()
        messages = [_msg("tool", "short output", tool_call_id="c1")]

        result = compactor.compact(messages)

        assert result[0]["content"] == "short output"

    def test_generic_truncation_for_unknown_tool(self):
        """未知工具 → 通用头/尾截断"""
        compactor = ContextCompactor()
        original = "HEAD" + "m" * 5000 + "TAIL"
        messages = [_msg("tool", original)]

        result = compactor.compact(messages)

        content = result[0]["content"]
        assert "characters truncated" in content
        assert content.startswith("HEAD")
        assert content.endswith("TAIL")
        assert len(content) < len(original)

    def test_read_file_truncation_via_tool_call_id(self):
        """read_file（经 tool_call_id 反查）→ 按行头/尾截断"""
        compactor = ContextCompactor()
        messages = [
            _msg(
                "assistant",
                "",
                tool_calls=[{"id": "c1", "function": {"name": "read_file"}}],
            ),
            _msg("tool", _lines(200), tool_call_id="c1"),
        ]

        result = compactor.compact(messages)

        content = result[1]["content"]
        assert "lines truncated by micro-compaction" in content
        assert "line 0 content" in content  # 头部保留
        assert "line 199 content" in content  # 尾部保留
        assert content.count("\n") < 199  # 确实被截断

    def test_read_file_truncation_via_explicit_field(self):
        """read_file（经显式 tool_name 字段）"""
        compactor = ContextCompactor()
        messages = [_msg("tool", _lines(200), tool_name="read_file")]

        result = compactor.compact(messages)

        assert "lines truncated by micro-compaction" in result[0]["content"]

    def test_tool_detection_via_content_marker(self):
        """内容中的 <<<TOOL_RESULT>>> 标记"""
        compactor = ContextCompactor()
        content = f"<<<TOOL_RESULT>>>\nTool: read_file\n{_lines(200)}"
        messages = [_msg("tool", content)]

        result = compactor.compact(messages)

        assert "lines truncated by micro-compaction" in result[0]["content"]

    def test_head_tail_truncation_for_list_directory(self):
        """list_directory → 头/尾条目截断"""
        compactor = ContextCompactor()
        entries = "\n".join(f"entry_{i}.txt" for i in range(300))
        messages = [_msg("tool", entries, tool_name="list_directory")]

        result = compactor.compact(messages)

        content = result[0]["content"]
        assert "entries truncated" in content
        assert "entry_0.txt" in content
        assert "entry_299.txt" in content

    def test_error_aware_truncation_for_run_shell(self):
        """run_shell → 错误感知截断，保留错误诊断行"""
        compactor = ContextCompactor()
        lines = [f"build log line {i}" for i in range(200)]
        lines[120] = "Traceback (most recent call last):"
        lines[121] = '  File "main.py", line 1, in <module>'
        lines[122] = "ModuleNotFoundError: No module named 'missing_dep'"
        messages = [_msg("tool", "\n".join(lines), tool_name="run_shell")]

        result = compactor.compact(messages)

        content = result[0]["content"]
        assert "ModuleNotFoundError: No module named 'missing_dep'" in content
        assert "showing error-relevant sections" in content
        # 无关中间行被丢弃
        assert "build log line 100" not in content
        assert len(content) < len("\n".join(lines))

    def test_does_not_mutate_input(self):
        """压缩不修改输入消息"""
        compactor = ContextCompactor()
        original_content = _lines(200)
        messages = [_msg("tool", original_content, tool_name="read_file")]

        compactor.compact(messages)

        assert messages[0]["content"] == original_content

    def test_list_content_tool_result_block(self):
        """list 形式 content 中的 tool_result 块被截断"""
        compactor = ContextCompactor()
        block = {"type": "tool_result", "tool_name": "read_file", "content": _lines(200)}
        messages = [_msg("user", [block])]

        result = compactor.compact(messages)

        new_block = result[0]["content"][0]
        assert "lines truncated by micro-compaction" in new_block["content"]
        # 原始块不被修改
        assert block["content"] == _lines(200)

    def test_list_content_large_text_block(self):
        """list 形式 content 中的大 text 块被通用截断（H1）"""
        compactor = ContextCompactor()
        block = {"type": "text", "text": "w" * 6000}
        messages = [_msg("user", [block])]

        result = compactor.compact(messages)

        new_block = result[0]["content"][0]
        assert "characters truncated" in new_block["text"]
        assert len(new_block["text"]) < 6000
        # 原始块不被修改
        assert block["text"] == "w" * 6000

    def test_single_line_huge_read_output_falls_back_to_generic(self):
        """单行巨型 read_file 输出（少行 guard）→ 通用字符截断（M1）"""
        compactor = ContextCompactor()
        messages = [_msg("tool", "z" * 8000, tool_name="read_file")]

        result = compactor.compact(messages)

        assert "characters truncated" in result[0]["content"]
        assert len(result[0]["content"]) < 8000

    def test_single_line_huge_shell_output_falls_back_to_generic(self):
        """单行巨型 run_shell 输出（少行 guard）→ 通用字符截断（M1）"""
        compactor = ContextCompactor()
        messages = [_msg("tool", "o" * 8000, tool_name="run_shell")]

        result = compactor.compact(messages)

        assert "characters truncated" in result[0]["content"]
        assert len(result[0]["content"]) < 8000


# ── 错误感知截断（直接测试） ─────────────────────────────


class TestTruncateErrorAware:
    """_truncate_error_aware 错误感知截断"""

    def test_short_output_unchanged(self):
        """≤30 行原样返回"""
        text = _lines(30)
        assert ContextCompactor._truncate_error_aware(text) == text

    def test_preserves_error_context_window(self):
        """保留错误行附近的诊断窗口"""
        lines = [f"output line {i}" for i in range(120)]
        lines[80] = "Traceback (most recent call last):"
        lines[81] = '  File "app.py", line 42, in handler'
        lines[82] = "ValueError: invalid literal for int()"
        lines[83] = "    return int(raw)"

        result = ContextCompactor._truncate_error_aware("\n".join(lines))

        assert "ValueError: invalid literal for int()" in result
        assert 'File "app.py", line 42, in handler' in result
        assert "showing error-relevant sections" in result
        # 无关中间行被丢弃（头部区域约前 67 行、尾部 5 行、错误窗口之外）
        assert "output line 100" not in result
        assert len(result) < len("\n".join(lines))

    def test_no_error_lines_keeps_head_and_tail(self):
        """无错误行 → 头部 + 末尾 10 行"""
        text = _lines(100)

        result = ContextCompactor._truncate_error_aware(text)

        assert "lines truncated" in result
        assert "line 0 content" in result  # 头部
        assert "line 99 content" in result  # 末尾
        assert "line 80 content" not in result  # 中间被丢（头/尾之外）

    def test_no_false_marker_when_remaining_within_tail(self):
        """remaining ≤ 10 行时全部保留，不产生虚假截断标记（M3）"""
        # 31 行 × 48 chars/行：头部吃 21 行（≥1000 chars），remaining 恰 10 行
        lines = ["y" * 47 for _ in range(31)]
        original = "\n".join(lines)

        result = ContextCompactor._truncate_error_aware(original)

        assert "lines truncated" not in result
        assert result == original

    def test_no_duplicate_tail_when_error_near_end(self):
        """错误靠近末尾时，尾部 5 行与错误窗口去重（M3）"""
        lines = [f"out {i} " + "q" * 40 for i in range(100)]
        lines[95] = "Error: boom"

        result = ContextCompactor._truncate_error_aware("\n".join(lines))

        assert result.count("Error: boom") == 1  # 窗口内一次，尾部不重复
        assert result.count("out 97 ") == 1  # 窗口与尾部重叠行去重
        assert "out 99 " in result  # 窗口外的末尾行仍保留

    def test_keeps_final_lines_after_error_section(self):
        """错误段后附加末尾 5 行"""
        lines = [f"step {i} " + "z" * 40 for i in range(100)]
        lines[70] = "Error: compilation failed"

        result = ContextCompactor._truncate_error_aware("\n".join(lines))

        assert "Error: compilation failed" in result
        assert "step 99 " in result  # 末尾 5 行
        assert result.count("\n") < 99  # 确实被截断


# ── Layer 2: Sliding Window ──────────────────────────────


class TestSlidingWindow:
    """Layer 2 滑窗兜底"""

    def _over_budget_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        """构造超阈值的消息列表（system + count 条 user）"""
        messages = [_msg("system", "You are Sage.")]
        for i in range(count):
            messages.append(_msg("user", f"message {i} " + "x" * 100))
        return messages

    def test_keeps_system_and_recent_window(self):
        """保留 system + 最近 N 条"""
        # 阈值 200 tokens = 800 chars；10 条 × ~110 chars ≈ 275 tokens > 阈值
        compactor = ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )
        messages = self._over_budget_messages(10)

        result = compactor.compact(messages)

        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are Sage."
        # system + 最近 4 条
        assert len(result) == 5
        assert "message 9" in result[-1]["content"]
        assert "message 6" in result[1]["content"]
        # 旧消息被淘汰
        assert all("message 0 " not in m.get("content", "") for m in result)

    def test_truncates_large_content_in_window(self):
        """窗口内的超长内容被激进截断"""
        compactor = ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )
        messages = self._over_budget_messages(10)
        messages[-1] = _msg("user", "BIG" * 1000)  # 3000 chars

        result = compactor.compact(messages)

        assert result[-1]["content"].endswith("... (truncated for context)")
        assert len(result[-1]["content"]) < 900

    def test_does_not_mutate_window_messages(self):
        """滑窗截断不修改输入"""
        compactor = ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )
        messages = self._over_budget_messages(10)
        messages[-1] = _msg("user", "BIG" * 1000)
        original_content = messages[-1]["content"]

        compactor.compact(messages)

        assert messages[-1]["content"] == original_content

    def test_truncates_list_content_blocks_in_window(self):
        """窗口内 list 形式 content 的块也被截断（H1）"""
        compactor = ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )
        messages = [_msg("system", "sys")]
        messages += [_msg("user", f"message {i} " + "x" * 100) for i in range(6)]
        block = {"type": "text", "text": "b" * 900}
        messages.append(_msg("user", [block]))

        result = compactor.compact(messages)

        last_block = result[-1]["content"][0]
        assert last_block["text"].endswith("... (truncated for context)")
        assert len(last_block["text"]) < 850
        # 原始块不被修改
        assert block["text"] == "b" * 900


# ── compact() 编排 ───────────────────────────────────────


class TestCompactOrchestration:
    """compact() 三层编排（Layer 1 + 2）"""

    def test_below_threshold_returns_micro_result(self):
        """未超阈值：MicroCompact 后直接返回"""
        compactor = ContextCompactor()
        messages = [
            _msg("system", "system prompt"),
            _msg("user", "hello"),
            _msg("assistant", "world"),
        ]

        result = compactor.compact(messages)

        assert result == messages

    def test_over_threshold_reduces_tokens(self):
        """超阈值：压缩后 token 数显著下降"""
        compactor = ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )
        messages = [_msg("system", "sys")]
        for i in range(20):
            messages.append(_msg("user", f"msg {i} " + "y" * 200))

        result = compactor.compact(messages)

        assert compactor.estimate_tokens(result) < compactor.estimate_tokens(messages)

    def test_micro_compact_alone_may_satisfy_budget(self):
        """超长工具结果：MicroCompact 后即低于预算，不触发滑窗"""
        # 阈值 1000 tokens = 4000 chars；原始 ~6000 chars 超阈值，
        # read_file 按行截断后 ~3000 chars 回到阈值内
        compactor = ContextCompactor(context_window=2000, compact_threshold_ratio=0.5)
        tool_content = _lines(400)
        messages = [
            _msg("system", "sys"),
            _msg("user", "question"),
            _msg("tool", tool_content, tool_name="read_file"),
        ]

        result = compactor.compact(messages)

        # 三条消息全保留（未触发滑窗），工具结果已被 MicroCompact
        assert len(result) == 3
        assert "lines truncated by micro-compaction" in result[2]["content"]
        assert len(result[2]["content"]) < len(tool_content)
        assert compactor.estimate_tokens(result) <= compactor.compact_threshold


# ── Layer 3: LLM Summary ─────────────────────────────────


class TestLayer3Summary:
    """compact_with_summary 三层压缩（含可选 LLM 摘要）"""

    def _compactor(self) -> ContextCompactor:
        return ContextCompactor(
            context_window=400, compact_threshold_ratio=0.5, sliding_window_size=4
        )

    def _over_budget_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        messages = [_msg("system", "You are Sage.")]
        for i in range(count):
            messages.append(_msg("user", f"message {i} " + "x" * 100))
        return messages

    @pytest.mark.asyncio()
    async def test_summary_replaces_evicted_prefix(self):
        """摘要消息插在 system 之后、最近窗口之前"""
        compactor = self._compactor()
        messages = self._over_budget_messages(10)
        calls: List[List[Dict[str, Any]]] = []

        async def summarize(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            calls.append(old_messages)
            assert "Summarize the conversation" in prompt
            return "User did A, then B."

        result = await compactor.compact_with_summary(messages, summarize)

        assert len(calls) == 1
        # 淘汰了 10 - 4 = 6 条
        assert len(calls[0]) == 6
        assert "message 0" in calls[0][0]["content"]

        assert result[0]["content"] == "You are Sage."
        assert result[1]["content"].startswith(SUMMARY_PREFIX)
        assert "User did A, then B." in result[1]["content"]
        assert "(covers 6 earlier messages)" in result[1]["content"]
        # system + summary + 最近 4 条
        assert len(result) == 6
        assert "message 9" in result[-1]["content"]

    @pytest.mark.asyncio()
    async def test_summary_skipped_when_under_budget(self):
        """未超阈值时不调用摘要函数"""
        compactor = self._compactor()
        messages = [_msg("user", "hello")]
        called = False

        async def summarize(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            nonlocal called
            called = True
            return "unused"

        result = await compactor.compact_with_summary(messages, summarize)

        assert called is False
        assert result == messages

    @pytest.mark.asyncio()
    async def test_no_eviction_skips_summary(self):
        """消息数 ≤ 窗口大小：无需淘汰，不调用摘要"""
        compactor = self._compactor()
        # 4 条超长消息超阈值，但不超过窗口大小 4
        messages = [_msg("user", f"msg {i} " + "x" * 300) for i in range(4)]
        called = False

        async def summarize(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            nonlocal called
            called = True
            return "unused"

        result = await compactor.compact_with_summary(messages, summarize)

        assert called is False
        assert len(result) == 4

    @pytest.mark.asyncio()
    async def test_oversized_summary_text_capped(self):
        """LLM 返回超长摘要 → 兜底截断（M2）"""
        compactor = self._compactor()
        messages = self._over_budget_messages(10)

        async def summarize(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            return "s" * 5000

        result = await compactor.compact_with_summary(messages, summarize)

        summary_content = result[1]["content"]
        assert summary_content.startswith(SUMMARY_PREFIX)
        assert "characters truncated" in summary_content
        assert len(summary_content) < 2200

    @pytest.mark.asyncio()
    async def test_summary_failure_falls_back_to_window(self):
        """摘要失败 → 回退纯 Layer 2 滑窗"""
        compactor = self._compactor()
        messages = self._over_budget_messages(10)

        async def summarize(old_messages: List[Dict[str, Any]], prompt: str) -> str:
            raise RuntimeError("LLM unavailable")

        result = await compactor.compact_with_summary(messages, summarize)

        # 与纯 compact() 结果一致（system + 最近 4 条，无摘要消息）
        assert result == compactor.compact(messages)
        assert all(
            not str(m.get("content", "")).startswith(SUMMARY_PREFIX) for m in result
        )


# ── 摘要 prompt ──────────────────────────────────────────


class TestSummaryPrompt:
    """build_summary_prompt"""

    def test_prompt_contains_structure(self):
        """prompt 包含结构化摘要要求"""
        prompt = ContextCompactor.build_summary_prompt([])

        assert "Summarize the conversation" in prompt
        assert "accomplished" in prompt
        assert "next steps" in prompt
        assert "300 words" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
