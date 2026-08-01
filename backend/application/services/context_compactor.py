"""
三层上下文压缩 + 错误感知截断 (A12 from LLM_Simple)

长会话 / 大体积工具输出会把 token 用量推到上下文窗口上限附近。
本模块按"三层渐进"策略压缩消息历史：

Layer 1 MicroCompact — 按工具类型策略截断（无 LLM 调用）：
    - read_file 类：按行保留头/尾，保留行号结构
    - run_shell / run_python / run_pytest 类：错误感知截断，
      保留错误诊断相关行（traceback / exception 上下文窗口）
    - list_directory / search_files 类：保留头/尾条目
    - 其他：通用头/尾字符截断
Layer 2 Sliding Window — 保留 system prompt + 最近 N 条消息
Layer 3 LLM Summary — 可选；把被滑窗淘汰的历史消息交给 LLM
    生成摘要，以一条摘要消息替代被淘汰前缀

设计要点
--------

- **不可变**：所有压缩操作返回新消息列表，绝不修改输入消息
  （压缩版本仅作 context，原始消息保留在存储层）。
- **工具名解析三路径**：消息显式字段（``tool_name`` / ``name``）→
  反查前序 assistant 的 ``tool_calls``（按 ``tool_call_id`` 匹配）→
  内容中的 ``<<<TOOL_RESULT>>>\\nTool: <name>`` 标记。
- **Layer 3 可选且容错**：摘要函数失败时自动回退到纯 Layer 2，
  不阻塞主流程。

Ported from LLM_Simple/agent/context_manager.py (ContextManager)。

使用示例：
    compactor = ContextCompactor(context_window=131072)

    # Layer 1 + 2（同步，无 LLM 调用）
    if compactor.should_compact(messages):
        messages = compactor.compact(messages)

    # Layer 1 + 2 + 3（需提供异步 LLM 摘要函数）
    async def summarize(old_messages, prompt): ...
    messages = await compactor.compact_with_summary(messages, summarize)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ── 各工具类型的 MicroCompact 策略 ────────────────────────
# 目录列表 / 搜索结果：保留头 + 尾条目
_HEAD_TAIL_TOOLS = {"list_directory", "check_directory", "search_files", "glob"}
_HEAD_TAIL_HEAD = 50
_HEAD_TAIL_TAIL = 20

# Shell / 脚本执行：错误感知截断（保留错误诊断上下文）
_ERROR_AWARE_TOOLS = {
    "run_shell",
    "run_python",
    "run_pytest",
    "execute_command",
    "shell",
    "bash",
    "terminal",
}
_ERROR_PATTERN = re.compile(
    r"(?i)(error|exception|traceback|fail|abort|denied|refused|"
    r"cannot|could not|unable|invalid|missing|not found|"
    r"syntaxerror|typeerror|valueerror|attributeerror|"
    r"importerror|modulenotfounderror|keyerror|indexerror|"
    r"runtimeerror|permissionerror|filenotfounderror|"
    r"segmentation fault|bus error|killed|out of memory)"
)

# 文件读取：按行头/尾截断
_READ_TOOLS = {"read_file", "view"}

# 单个工具结果触发 MicroCompact 的最大字符数
MAX_RESULT_CHARS = 2000

# 错误感知截断的头部区域字符上限
_ERROR_HEAD_CHARS = 1000

# 滑窗内单条消息内容的字符上限
_WINDOW_CONTENT_CHARS = 800

# 滑窗默认保留的非 system 消息条数
_DEFAULT_WINDOW_SIZE = 12

# 粗估 token 用的字符/token 比例（英文约 4 字符/token）
_DEFAULT_CHARS_PER_TOKEN = 4.0

# Layer 3 摘要消息前缀
SUMMARY_PREFIX = "[Earlier conversation summary]"

# 内容中的工具标记（LLM_Simple 兼容格式）
_TOOL_MARKER = re.compile(r"<<<TOOL_RESULT>>>\s*\nTool:\s*(\S+)")

# Layer 3 摘要函数签名：(被淘汰的消息列表, 摘要 prompt) -> 摘要文本
Summarizer = Callable[[List[Dict[str, Any]], str], Awaitable[str]]


def _rough_estimate(text: str, chars_per_token: float = _DEFAULT_CHARS_PER_TOKEN) -> int:
    """基于字符数的粗粒度 token 估算。"""
    if not text:
        return 0
    return max(1, round(len(text) / chars_per_token))


def _split_system(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把消息列表拆成 (system 消息, 其他消息)，保持各自相对顺序。"""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]
    return system_msgs, others


class ContextCompactor:
    """三层上下文压缩器。

    Layer 1 MicroCompact：按工具类型策略截断（无 LLM 调用）
    Layer 2 Sliding Window：system prompt + 最近 N 条消息
    Layer 3 LLM Summary：可选，LLM 摘要替代被淘汰前缀

    所有方法都不修改输入消息，返回全新列表。

    已知局限：system 消息在任何层都不截断（巨型 system prompt
    需要在装配上游控制）。
    """

    def __init__(
        self,
        context_window: int = 131072,
        compact_threshold_ratio: float = 0.75,
        sliding_window_size: int = _DEFAULT_WINDOW_SIZE,
    ) -> None:
        if context_window <= 0:
            raise ValueError("context_window must be positive")
        if not 0 < compact_threshold_ratio < 1:
            raise ValueError("compact_threshold_ratio must be in (0, 1)")
        if sliding_window_size <= 0:
            raise ValueError("sliding_window_size must be positive")

        self.context_window = context_window
        self.compact_threshold = int(context_window * compact_threshold_ratio)
        self.sliding_window_size = sliding_window_size

    # ── Token 估算 ─────────────────────────────────────

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """对消息列表做粗粒度 token 估算。"""
        total = 0
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                total += _rough_estimate(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text")
                        total += _rough_estimate(text if isinstance(text, str) else str(block))
                    else:
                        total += _rough_estimate(str(block))
            elif content is not None:
                total += _rough_estimate(str(content))
        return total

    def should_compact(self, messages: List[Dict[str, Any]]) -> bool:
        """检查上下文是否超过压缩阈值。"""
        return self.estimate_tokens(messages) > self.compact_threshold

    # ── 压缩入口 ───────────────────────────────────────

    def compact(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Layer 1 + Layer 2 压缩（同步，无 LLM 调用）。

        先做 MicroCompact；若仍超阈值，再用滑窗兜底。
        """
        compacted = self._micro_compact(messages)
        if self.estimate_tokens(compacted) <= self.compact_threshold:
            return compacted
        return self._sliding_window_compact(compacted)

    async def compact_with_summary(
        self,
        messages: List[Dict[str, Any]],
        summarize: Summarizer,
    ) -> List[Dict[str, Any]]:
        """三层压缩（含可选的 Layer 3 LLM 摘要）。

        流程：
        1. MicroCompact 后若低于阈值，直接返回
        2. 按滑窗拆分：最近 N 条保留，其余为"被淘汰前缀"
        3. 用 ``summarize(被淘汰消息, prompt)`` 生成摘要消息，
           插在 system 消息之后、最近窗口之前（摘要文本过长时
           兜底截断到 ``MAX_RESULT_CHARS``）
        4. 摘要失败时回退到纯 Layer 2 滑窗结果
        """
        compacted = self._micro_compact(messages)
        if self.estimate_tokens(compacted) <= self.compact_threshold:
            return compacted

        windowed = self._sliding_window_compact(compacted)
        _, others = _split_system(compacted)
        if len(others) <= self.sliding_window_size:
            # 没有可淘汰的前缀，Layer 2 即可
            return windowed

        evicted = others[: -self.sliding_window_size]
        recent = others[-self.sliding_window_size :]
        prompt = self.build_summary_prompt(recent)
        try:
            summary_text = await summarize(evicted, prompt)
        except Exception:
            logger.warning(
                "Layer 3 LLM 摘要失败，回退到 Layer 2 滑窗（%d 条消息被淘汰且无摘要）",
                len(evicted),
                exc_info=True,
            )
            return windowed

        # 兜底：LLM 返回超长摘要时截断，防止摘要消息本身撑爆上下文
        if len(summary_text) > MAX_RESULT_CHARS:
            summary_text = self._truncate_generic(summary_text)

        system_msgs, _ = _split_system(compacted)
        summary_msg = {
            "role": "system",
            "content": (
                f"{SUMMARY_PREFIX} (covers {len(evicted)} earlier messages)\n"
                f"{summary_text}"
            ),
        }
        return system_msgs + [summary_msg] + windowed[len(system_msgs):]

    # ── Layer 1: MicroCompact ──────────────────────────

    def _micro_compact(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按工具类型对超长工具结果做策略截断（不修改输入）。"""
        compacted: List[Dict[str, Any]] = []
        for index, msg in enumerate(messages):
            content = msg.get("content")
            if isinstance(content, str) and len(content) > MAX_RESULT_CHARS:
                tool_name = self._resolve_tool_name(messages, index)
                new_msg = dict(msg)
                new_msg["content"] = self._micro_compact_text(content, tool_name)
                compacted.append(new_msg)
            elif isinstance(content, list):
                new_blocks, changed = self._micro_compact_blocks(content, messages, index)
                if changed:
                    new_msg = dict(msg)
                    new_msg["content"] = new_blocks
                    compacted.append(new_msg)
                else:
                    compacted.append(msg)
            else:
                compacted.append(msg)
        return compacted

    def _micro_compact_blocks(
        self,
        blocks: List[Any],
        messages: List[Dict[str, Any]],
        index: int,
    ) -> Tuple[List[Any], bool]:
        """对 list 形式 content 中的超长块做截断。

        - ``tool_result`` 块：按工具类型策略截断 ``content``
        - 其他带 ``text`` 字段的块（如 text 块）：通用字符截断
        """
        new_blocks: List[Any] = []
        changed = False
        for block in blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            if block.get("type") == "tool_result":
                new_block = self._compact_tool_result_block(block, messages, index)
            else:
                new_block = self._compact_text_block(block)
            new_blocks.append(new_block)
            if new_block is not block:
                changed = True
        return new_blocks, changed

    def _compact_tool_result_block(
        self,
        block: Dict[str, Any],
        messages: List[Dict[str, Any]],
        index: int,
    ) -> Dict[str, Any]:
        """截断单个 tool_result 块；无需截断时原样返回。"""
        text = block.get("content")
        if not (isinstance(text, str) and len(text) > MAX_RESULT_CHARS):
            return block
        tool_name = (
            block.get("tool_name")
            or block.get("name")
            or self._resolve_tool_name(messages, index)
        )
        new_block = dict(block)
        new_block["content"] = self._micro_compact_text(text, tool_name)
        return new_block

    @staticmethod
    def _compact_text_block(block: Dict[str, Any]) -> Dict[str, Any]:
        """截断单个 text 块；无需截断时原样返回。"""
        text = block.get("text")
        if not (isinstance(text, str) and len(text) > MAX_RESULT_CHARS):
            return block
        new_block = dict(block)
        new_block["text"] = ContextCompactor._truncate_generic(text)
        return new_block

    @staticmethod
    def _resolve_tool_name(messages: List[Dict[str, Any]], index: int) -> str:
        """解析第 ``index`` 条消息对应的工具名。

        三条路径（按优先级）：
        1. 消息自身的 ``tool_name`` / ``name`` 字段
        2. 按 ``tool_call_id`` 反查前序 assistant 消息的 ``tool_calls``
        3. 内容中的 ``<<<TOOL_RESULT>>>\\nTool: <name>`` 标记
        """
        msg = messages[index]

        for key in ("tool_name", "name"):
            value = msg.get(key)
            if isinstance(value, str) and value:
                return value

        tool_call_id = msg.get("tool_call_id")
        if tool_call_id:
            for prev in reversed(messages[:index]):
                for call in prev.get("tool_calls") or []:
                    if not isinstance(call, dict) or call.get("id") != tool_call_id:
                        continue
                    function = call.get("function") or {}
                    name = function.get("name") or call.get("name")
                    if isinstance(name, str) and name:
                        return name

        content = msg.get("content")
        if isinstance(content, str):
            match = _TOOL_MARKER.search(content)
            if match:
                return match.group(1)

        return ""

    def _micro_compact_text(self, text: str, tool_name: str) -> str:
        """按工具类型分发到具体截断策略。"""
        if len(text) <= MAX_RESULT_CHARS:
            return text
        if tool_name in _READ_TOOLS:
            return self._truncate_read_output(text)
        if tool_name in _ERROR_AWARE_TOOLS:
            return self._truncate_error_aware(text)
        if tool_name in _HEAD_TAIL_TOOLS:
            return self._truncate_head_tail(text)
        return self._truncate_generic(text)

    @staticmethod
    def _truncate_read_output(text: str) -> str:
        """截断 read_file 输出，按行保留头/尾。"""
        lines = text.splitlines()
        if len(lines) <= 60:
            # 行数少（如单行 minified 文件）→ 退回通用字符截断
            return ContextCompactor._truncate_generic(text)

        head_lines = max(20, len(lines) // 3)
        tail_lines = max(10, len(lines) // 6)
        skipped = len(lines) - head_lines - tail_lines
        kept = lines[:head_lines]
        kept.append(f"... ({skipped} lines truncated by micro-compaction) ...")
        kept.extend(lines[-tail_lines:])
        return "\n".join(kept)

    @staticmethod
    def _truncate_error_aware(text: str) -> str:
        """错误感知截断：保留头部 + 错误上下文窗口 + 尾部。

        用于 shell / python / pytest 输出。扫描错误特征行
        （traceback / exception / fail 等），保留其特征行附近
        前 2 行 + 后 3 行的诊断窗口，丢弃无关的中间输出。
        """
        lines = text.splitlines()
        if len(lines) <= 30:
            # 行数少（如单行大 JSON）→ 退回通用字符截断
            return ContextCompactor._truncate_generic(text)

        # 头部区域：前 ~1000 字符
        head_lines: List[str] = []
        head_len = 0
        for line in lines:
            head_lines.append(line)
            head_len += len(line) + 1
            if head_len >= _ERROR_HEAD_CHARS:
                break

        remaining = lines[len(head_lines):]

        # 扫描错误上下文窗口（错误行前 2 行 + 后 3 行）
        error_windows: set = set()
        for i, line in enumerate(remaining):
            if _ERROR_PATTERN.search(line):
                for j in range(max(0, i - 2), min(len(remaining), i + 4)):
                    error_windows.add(j)

        if not error_windows:
            # 没找到错误行：头部 + 截断标记 + 末尾 10 行
            tail = remaining[-10:]
            skipped = len(remaining) - len(tail)
            kept = list(head_lines)
            if skipped > 0:
                kept.append(f"... ({skipped} lines truncated) ...")
            kept.extend(tail)
            return "\n".join(kept)

        # 头部 + 所有错误上下文行
        result = list(head_lines)
        for i, line in enumerate(remaining):
            if i in error_windows:
                result.append(line)

        if len(result) < len(lines):
            result.append(
                f"... (total {len(lines)} lines, showing error-relevant sections) ..."
            )
            # 末尾 5 行（错误靠近末尾时与窗口重叠的行去重）
            kept_indices = set(range(len(head_lines)))
            kept_indices.update(len(head_lines) + i for i in error_windows)
            for idx in range(max(0, len(lines) - 5), len(lines)):
                if idx not in kept_indices:
                    result.append(lines[idx])

        return "\n".join(result)

    @staticmethod
    def _truncate_head_tail(text: str) -> str:
        """截断目录列表 / 搜索结果，保留头/尾条目。"""
        lines = text.splitlines()
        if len(lines) <= _HEAD_TAIL_HEAD + _HEAD_TAIL_TAIL + 5:
            # 条目少（如单行超长路径）→ 退回通用字符截断
            return ContextCompactor._truncate_generic(text)

        skipped = len(lines) - _HEAD_TAIL_HEAD - _HEAD_TAIL_TAIL
        kept = lines[:_HEAD_TAIL_HEAD]
        kept.append(f"... ({skipped} entries truncated) ...")
        kept.extend(lines[-_HEAD_TAIL_TAIL:])
        return "\n".join(kept)

    @staticmethod
    def _truncate_generic(text: str) -> str:
        """通用截断：保留头/尾各 MAX_RESULT_CHARS/2 字符。"""
        if len(text) <= MAX_RESULT_CHARS:
            return text

        half = MAX_RESULT_CHARS // 2
        skipped = len(text) - MAX_RESULT_CHARS
        return (
            text[:half]
            + f"\n\n... ({skipped} characters truncated) ...\n\n"
            + text[-half:]
        )

    # ── Layer 2: Sliding Window ────────────────────────

    def _sliding_window_compact(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """滑窗兜底：保留 system prompt + 最近 N 条消息。

        保留窗口内的超长内容会被激进截断到 ``_WINDOW_CONTENT_CHARS``。
        """
        system_msgs, others = _split_system(messages)
        recent = others[-self.sliding_window_size :]

        truncated: List[Dict[str, Any]] = []
        for msg in recent:
            content = msg.get("content")
            if isinstance(content, str) and len(content) > _WINDOW_CONTENT_CHARS:
                new_msg = dict(msg)
                new_msg["content"] = (
                    content[:_WINDOW_CONTENT_CHARS] + "\n... (truncated for context)"
                )
                truncated.append(new_msg)
                continue
            if isinstance(content, list):
                new_blocks, changed = self._shrink_window_blocks(content)
                if changed:
                    new_msg = dict(msg)
                    new_msg["content"] = new_blocks
                    truncated.append(new_msg)
                    continue
            truncated.append(msg)

        return system_msgs + truncated

    @staticmethod
    def _shrink_window_blocks(blocks: List[Any]) -> Tuple[List[Any], bool]:
        """对窗口内 list 形式 content 逐块截断。"""
        new_blocks: List[Any] = []
        changed = False
        for block in blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            new_block = ContextCompactor._shrink_window_block(block)
            new_blocks.append(new_block)
            if new_block is not block:
                changed = True
        return new_blocks, changed

    @staticmethod
    def _shrink_window_block(block: Dict[str, Any]) -> Dict[str, Any]:
        """截断单个块的 text / content 字段；无需截断时原样返回。"""
        for key in ("text", "content"):
            value = block.get(key)
            if isinstance(value, str) and len(value) > _WINDOW_CONTENT_CHARS:
                new_block = dict(block)
                new_block[key] = (
                    value[:_WINDOW_CONTENT_CHARS] + "\n... (truncated for context)"
                )
                return new_block
        return block

    # ── Layer 3: LLM Summary prompt ────────────────────

    @staticmethod
    def build_summary_prompt(
        recent_messages: List[Dict[str, Any]],  # noqa: ARG004 — kept for API symmetry
    ) -> str:
        """构造 LLM 会话摘要 prompt（Layer 3）。

        当 MicroCompact + 滑窗仍不够时，用此 prompt 让 LLM 把
        被淘汰的历史消息压缩成结构化摘要。
        """
        return (
            "Summarize the conversation above in a structured way:\n"
            "1. What has been accomplished so far?\n"
            "2. What is the current task being worked on?\n"
            "3. What are the pending next steps?\n"
            "4. What key files have been modified?\n\n"
            "Keep the summary concise (under 300 words). "
            "Focus on information that would be essential for continuing the work."
        )
