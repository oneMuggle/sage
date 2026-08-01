"""
分支摘要式上下文压缩服务 (A28, ported from pi coding-agent)

当会话分支被切换、或上下文压缩（``ContextCompactor`` Layer 3）淘汰
历史前缀时，本服务用 LLM 为"被离开的那段对话"生成结构化摘要，并以
system 消息形式注入后续上下文，避免关键信息（目标、决策、文件变更）
因分支切换 / 历史淘汰而丢失。

参考实现：pi ``packages/coding-agent/src/core/compaction/branch-summarization.ts``
（``generateBranchSummary`` / ``prepareBranchEntries`` / 文件操作追踪）。

设计要点
--------

- **LLM 注入签名** ``Callable[[str], Awaitable[str]]``：与
  ``backend/chat/compaction.py`` 的 ``llm_chat_callable`` 及
  ``LLMClient.complete`` 一致；单测用假函数即可，不依赖具体客户端。
- **数据库纯净**：输入是 OpenAI 风格 dict 消息列表，输出是新对象
  （``BranchSummaryResult`` / 上下文消息 dict）；不修改输入、不触碰
  SQLite，落盘由调用方负责。
- **容错分层**：``summarize_branch`` 在 LLM 失败时**不抛异常**，以
  ``result.error`` 返回错误，由调用方决定降级策略；Layer 3 适配器
  ``as_layer3_summarizer`` 则刻意抛异常，以复用
  ``ContextCompactor.compact_with_summary`` 已有的"摘要失败 → 回退
  Layer 2 滑窗"契约。
- **结构化摘要格式**（沿用 pi）：Goal / Constraints & Preferences /
  Progress (Done / In Progress / Blocked) / Key Decisions / Next Steps；
  末尾自动附加从工具调用中提取的已读 / 已改文件列表。
- **token 预算**：按 ``context_window - reserve_tokens`` 计算预算，
  从**最新**消息向最旧方向选取，保证分支尾部（最近上下文）优先保留；
  摘要类消息（压缩摘要 / 分支摘要）享受 90% 预算宽限，避免嵌套摘要
  丢失导致的上下文断裂。
- Py3.8 兼容（release/win7 可 cherry-pick）：仅 ``typing.*`` 泛型。

使用示例::

    summarizer = BranchSummarizer(llm_complete=client.complete)

    # 场景 1：分支切换 —— 摘要旧分支并注入新上下文
    result = await summarizer.summarize_branch(old_branch_messages)
    if not result.error:
        messages.append(BranchSummarizer.to_context_message(result))

    # 场景 2：作为 ContextCompactor (A12) 的 Layer 3 默认摘要器
    compactor = ContextCompactor(branch_summarizer=summarizer)
    messages = await compactor.compact_with_summary(messages)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# LLM 单轮补全注入签名：async (prompt) -> 摘要文本
LLMComplete = Callable[[str], Awaitable[str]]

# Layer 3 摘要函数签名（与 context_compactor.Summarizer 同构；此处独立
# 定义以保持模块单向依赖：context_compactor 依赖本模块，反向不导入）
Layer3Summarizer = Callable[[List[Dict[str, Any]], str], Awaitable[str]]

# ── 默认配置 ────────────────────────────────────────────

#: 默认上下文窗口（与 ContextCompactor 默认值一致）
DEFAULT_CONTEXT_WINDOW = 131072

#: 预留给摘要 prompt + LLM 响应的 token 数（pi 默认 16384）
DEFAULT_RESERVE_TOKENS = 16384

#: 粗估 token 用的字符/token 比例（与 context_compactor 同口径）
DEFAULT_CHARS_PER_TOKEN = 4.0

#: 序列化时单个工具结果的字符上限（pi TOOL_RESULT_MAX_CHARS）
TOOL_RESULT_MAX_CHARS = 2000

#: 序列化时工具调用单个字符串参数的字符上限（防止 write_file 的
#: 大段文件内容撑爆摘要 prompt；路径等短参数不受影响）
ARG_VALUE_MAX_CHARS = 300

# ── 摘要 prompt（ported from pi branch-summarization.ts）─────────

#: 注入上下文时的前导说明，让后续对话理解摘要的来源与性质
BRANCH_SUMMARY_PREAMBLE = (
    "The user explored a different conversation branch before returning here.\n"
    "Summary of that exploration:\n\n"
)

#: 结构化分支摘要 prompt（严格按此格式输出，便于后续机器/人读）
BRANCH_SUMMARY_PROMPT = """Create a structured summary of this conversation branch for context when returning later.

Use this EXACT format:

## Goal
[What was the user trying to accomplish in this branch?]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Work that was started but not finished]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [What should happen next to continue this work]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

#: 摘要专用 system prompt：禁止模型"接着聊"，只输出摘要
SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. Your task is to read a "
    "conversation between a user and an AI assistant, then produce a "
    "structured summary following the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in "
    "the conversation. ONLY output the structured summary."
)

#: 与 context_compactor.SUMMARY_PREFIX 保持一致的压缩摘要标记
#: （独立复制而非导入，维持模块单向依赖）
_COMPACTION_SUMMARY_MARKER = "[Earlier conversation summary]"

# ── 文件操作追踪（ported from pi compaction/utils.ts）────────────

#: 按 sage 实际工具名分类（read_file/view 读；write_file 写；edit_file 改）
_READ_FILE_TOOLS = {"read_file", "view"}
_WRITE_FILE_TOOLS = {"write_file", "create_file"}
_EDIT_FILE_TOOLS = {"edit_file", "apply_patch", "apply_diff"}

#: 工具参数中承载文件路径的候选 key
_PATH_ARG_KEYS = ("path", "file_path")

#: block 风格工具调用的 type 取值（_iter_tool_calls 与 token 估算共用，
#: 单一来源避免漂移）
_TOOL_CALL_BLOCK_TYPES = ("toolCall", "tool_call", "tool_use")


@dataclass
class FileOperations:
    """从工具调用中累计的文件操作集合（读 / 新建 / 编辑）。"""

    read: Set[str] = field(default_factory=set)
    written: Set[str] = field(default_factory=set)
    edited: Set[str] = field(default_factory=set)


@dataclass
class BranchSummaryResult:
    """分支摘要生成结果。

    ``summary`` 为 None 且 ``error`` 非空表示生成失败；调用方据此降级。
    ``read_files`` / ``modified_files`` 为从工具调用中提取的文件清单
    （已附加进 ``summary`` 文本末尾，单独返回便于持久化/展示）。
    """

    summary: Optional[str] = None
    read_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ── token 估算 ──────────────────────────────────────────


def _estimate_tokens(text: str, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    """基于字符数的粗粒度 token 估算（与 context_compactor 同算法）。"""
    if not text:
        return 0
    return max(1, round(len(text) / chars_per_token))


# ── 消息内容读取辅助 ────────────────────────────────────


def _content_text(content: Any) -> str:
    """统一提取 str / block-list 形式 content 中的纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: List[str] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", None):
                text = block.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        return "\n".join(texts)
    if content is None:
        return ""
    return str(content)


def _iter_content_blocks(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """取出 list 形式 content 中的所有 dict 块。"""
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _parse_arguments(args: Any) -> Dict[str, Any]:
    """把工具调用参数统一解析为 dict（支持 dict / JSON 字符串）。"""
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _iter_tool_calls(message: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """枚举消息中的工具调用，统一为 ``(工具名, 参数 dict)`` 列表。

    覆盖两种消息形态：
    - OpenAI 风格：顶层 ``tool_calls`` 列表（``function.name`` /
      ``function.arguments``，arguments 可为 JSON 字符串）
    - block 风格：content 中 ``type`` 为 ``toolCall`` / ``tool_call`` /
      ``tool_use`` 的块（``name`` + ``arguments`` / ``input``）
    """
    calls: List[Tuple[str, Dict[str, Any]]] = []

    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name") or call.get("name")
        if not isinstance(name, str) or not name:
            continue
        args = _parse_arguments(
            function.get("arguments") if "arguments" in function else call.get("arguments")
        )
        calls.append((name, args))

    for block in _iter_content_blocks(message):
        if block.get("type") not in _TOOL_CALL_BLOCK_TYPES:
            continue
        name = block.get("name")
        if not isinstance(name, str) or not name:
            continue
        args = _parse_arguments(
            block.get("arguments") if "arguments" in block else block.get("input")
        )
        calls.append((name, args))

    return calls


def _shorten_arg_values(args: Dict[str, Any]) -> Dict[str, Any]:
    """截断超长字符串参数（如 write_file 的文件正文），路径等短值不变。"""
    shortened: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > ARG_VALUE_MAX_CHARS:
            skipped = len(value) - ARG_VALUE_MAX_CHARS
            shortened[key] = f"{value[:ARG_VALUE_MAX_CHARS]}... [{skipped} more chars]"
        else:
            shortened[key] = value
    return shortened


# ── 文件操作提取 ────────────────────────────────────────


def extract_file_ops(
    messages: List[Dict[str, Any]], file_ops: Optional[FileOperations] = None
) -> FileOperations:
    """从消息序列累计文件操作（工具调用 + 嵌套摘要清单）。

    两个来源：

    1. 工具调用：只识别参数中带 ``path`` / ``file_path`` 的已知文件
       工具，其他工具忽略；
    2. 嵌套分支摘要（``details.branch_summary`` 消息）：其
       ``details.read_files`` / ``details.modified_files`` 折叠进
       累计集合——即使原始工具调用消息因预算被丢弃，文件清单也
       不丢失（对齐 pi ``prepareBranchEntries`` 的第一遍扫描；
       modified 归入 edited，与 written 一起去重）。

    结果按 读 / 写 / 改 三类去重累计。
    """
    if file_ops is None:
        file_ops = FileOperations()

    for message in messages:
        details = message.get("details")
        if isinstance(details, dict) and details.get("branch_summary"):
            for path in details.get("read_files") or []:
                if isinstance(path, str) and path:
                    file_ops.read.add(path)
            for path in details.get("modified_files") or []:
                if isinstance(path, str) and path:
                    file_ops.edited.add(path)

        for name, args in _iter_tool_calls(message):
            path = ""
            for key in _PATH_ARG_KEYS:
                value = args.get(key)
                if isinstance(value, str) and value:
                    path = value
                    break
            if not path:
                continue
            if name in _READ_FILE_TOOLS:
                file_ops.read.add(path)
            elif name in _WRITE_FILE_TOOLS:
                file_ops.written.add(path)
            elif name in _EDIT_FILE_TOOLS:
                file_ops.edited.add(path)

    return file_ops


def compute_file_lists(file_ops: FileOperations) -> Tuple[List[str], List[str]]:
    """由累计的文件操作计算最终清单。

    返回 ``(read_files, modified_files)``：modified = written ∪ edited；
    read_files 剔除已被修改的文件（改过的文件不必再强调"读过"）。
    两个列表均排序，保证输出稳定。
    """
    modified = set(file_ops.written) | set(file_ops.edited)
    read_only = sorted(f for f in file_ops.read if f not in modified)
    return read_only, sorted(modified)


def format_file_operations(read_files: List[str], modified_files: List[str]) -> str:
    """把文件清单格式化为 XML 段落，附加在摘要文本末尾。

    无文件操作时返回空串（不产生多余空行）。
    """
    sections: List[str] = []
    if read_files:
        sections.append("<read-files>\n" + "\n".join(read_files) + "\n</read-files>")
    if modified_files:
        sections.append("<modified-files>\n" + "\n".join(modified_files) + "\n</modified-files>")
    if not sections:
        return ""
    return "\n\n" + "\n\n".join(sections)


# ── 会话序列化 ──────────────────────────────────────────


def _truncate_for_summary(text: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    """截断超长工具结果，保留头部并追加截断标记。"""
    if len(text) <= max_chars:
        return text
    truncated_chars = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... {truncated_chars} more characters truncated]"


def _format_tool_calls(message: Dict[str, Any]) -> List[str]:
    """把消息中的工具调用序列化为 ``name(arg=value, ...)`` 字符串列表。"""
    formatted: List[str] = []
    for name, args in _iter_tool_calls(message):
        shortened = _shorten_arg_values(args)
        if not shortened:
            formatted.append(f"{name}()")
            continue
        args_str = ", ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in shortened.items()
        )
        formatted.append(f"{name}({args_str})")
    return formatted


def serialize_conversation(messages: List[Dict[str, Any]]) -> str:
    """把消息序列序列化为纯文本转录，供摘要 prompt 使用。

    序列化为文本（而非原样传入消息数组）是为了防止模型把转录当作
    "需要继续的对话"。各角色渲染规则（ported from pi serializeConversation）：

    - ``user``    → ``[User]: <文本>``；user 消息内嵌的 ``tool_result``
      块渲染为 ``[Tool result]:``（Anthropic 风格）
    - ``assistant`` → ``[Assistant]:`` 文本 + ``[Assistant tool calls]:``
      调用列表；``thinking`` 块渲染为 ``[Assistant thinking]:``
    - ``tool``    → ``[Tool result]:``（OpenAI 风格工具结果），
      超长内容按 ``TOOL_RESULT_MAX_CHARS`` 截断
    - ``system``  → 默认跳过（system prompt 由装配上游控制，不进
      转录）；但摘要类 system 消息（压缩摘要 / 分支摘要）渲染为
      ``[Earlier summary]:``——pi 中这类消息映射为 user role 进入
      转录，跳过会让嵌套摘要白白消耗预算宽限却对 LLM 不可见
    """
    parts: List[str] = []

    for message in messages:
        role = message.get("role")

        if role == "system":
            if _is_summary_message(message):
                text = _content_text(message.get("content"))
                if text:
                    parts.append(f"[Earlier summary]: {text}")
            continue

        if role == "user":
            text = _content_text(message.get("content"))
            if text:
                parts.append(f"[User]: {text}")
            for block in _iter_content_blocks(message):
                if block.get("type") != "tool_result":
                    continue
                result_text = _content_text(block.get("content"))
                if result_text:
                    parts.append(f"[Tool result]: {_truncate_for_summary(result_text)}")
            continue

        if role == "assistant":
            thinking_parts: List[str] = []
            for block in _iter_content_blocks(message):
                if block.get("type") != "thinking":
                    continue
                thinking = block.get("thinking") or block.get("text")
                if isinstance(thinking, str) and thinking:
                    thinking_parts.append(thinking)
            if thinking_parts:
                parts.append("[Assistant thinking]: " + "\n".join(thinking_parts))

            text = _content_text(message.get("content"))
            if text:
                parts.append(f"[Assistant]: {text}")

            tool_calls = _format_tool_calls(message)
            if tool_calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(tool_calls)}")
            continue

        if role == "tool":
            text = _content_text(message.get("content"))
            if text:
                parts.append(f"[Tool result]: {_truncate_for_summary(text)}")

    return "\n\n".join(parts)


# ── 分支消息选取（token 预算）────────────────────────────


def _is_summary_message(message: Dict[str, Any]) -> bool:
    """判断消息是否为"摘要类"消息（压缩摘要 / 分支摘要）。

    摘要类消息在预算紧张时享受宽限（见 ``prepare_branch_messages``），
    因为丢掉嵌套摘要会造成上下文断裂。识别依据：

    - 显式标记：``branch_summary`` 字段或 ``details.branch_summary``
    - 内容前缀：``context_compactor.SUMMARY_PREFIX`` / 分支摘要前导
    """
    if message.get("branch_summary"):
        return True
    details = message.get("details")
    if isinstance(details, dict) and details.get("branch_summary"):
        return True
    content = message.get("content")
    if isinstance(content, str):
        return content.startswith(_COMPACTION_SUMMARY_MARKER) or content.startswith(
            BRANCH_SUMMARY_PREAMBLE
        )
    return False


def _estimate_message_tokens(message: Dict[str, Any], chars_per_token: float) -> int:
    """估算单条消息的 token 占用（content + 工具调用参数）。

    block 风格工具调用（``tool_use`` 等）的参数只由下方
    ``_iter_tool_calls`` 循环计一次；content 循环显式跳过这些块，
    否则参数会被双重计数，在工具密集分支上系统性少选消息。
    """
    total = _estimate_tokens(str(message.get("role") or ""), chars_per_token)

    content = message.get("content")
    if isinstance(content, str):
        total += _estimate_tokens(content, chars_per_token)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in _TOOL_CALL_BLOCK_TYPES:
                    continue
                text = block.get("text") or block.get("content")
                total += _estimate_tokens(
                    text if isinstance(text, str) else json.dumps(block, ensure_ascii=False),
                    chars_per_token,
                )
            else:
                total += _estimate_tokens(str(block), chars_per_token)
    elif content is not None:
        total += _estimate_tokens(str(content), chars_per_token)

    for _name, args in _iter_tool_calls(message):
        total += _estimate_tokens(json.dumps(args, ensure_ascii=False), chars_per_token)

    return total


def prepare_branch_messages(
    messages: List[Dict[str, Any]],
    token_budget: int = 0,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> Tuple[List[Dict[str, Any]], FileOperations, int]:
    """按 token 预算从分支消息中选取待摘要内容。

    从**最新**消息向最旧方向遍历选取，超预算即停止 —— 保证分支尾部
    （最近的上下文）优先保留。返回 ``(选中消息, 文件操作, 估算 token 数)``，
    选中消息保持时间升序。

    文件操作单独做全量扫描（不受预算约束）：即使早期消息因预算被
    丢弃，其中读/改过的文件仍应进入摘要的文件清单（累计追踪）。

    摘要类消息（压缩摘要 / 分支摘要）享受宽限：超预算时，若已用预算
    不足 90%，仍破例纳入，避免嵌套摘要丢失。

    Args:
        messages: 分支消息列表（时间升序）
        token_budget: token 预算上限；``0`` 表示不限制
        chars_per_token: 字符/token 换算比例

    Raises:
        ValueError: ``token_budget`` 为负或 ``chars_per_token`` 非正
    """
    if token_budget < 0:
        raise ValueError(f"token_budget must be >= 0, got {token_budget}")
    if chars_per_token <= 0:
        raise ValueError(f"chars_per_token must be positive, got {chars_per_token}")

    file_ops = extract_file_ops(messages)

    selected: List[Dict[str, Any]] = []
    total_tokens = 0

    for message in reversed(messages):
        tokens = _estimate_message_tokens(message, chars_per_token)

        if token_budget > 0 and total_tokens + tokens > token_budget:
            # 摘要类消息宽限：已用 < 90% 预算时仍纳入
            if _is_summary_message(message) and total_tokens < token_budget * 0.9:
                selected.insert(0, message)
                total_tokens += tokens
            break

        selected.insert(0, message)
        total_tokens += tokens

    return selected, file_ops, total_tokens


# ── 摘要 prompt 构造 ────────────────────────────────────


def build_branch_prompt(
    conversation_text: str,
    custom_instructions: Optional[str] = None,
    replace_instructions: bool = False,
) -> str:
    """构造分支摘要的用户侧 prompt。

    转录用 ``<conversation>`` 标签包裹，后接结构化摘要指令。
    ``custom_instructions`` 缺省时用默认 ``BRANCH_SUMMARY_PROMPT``；
    提供时默认作为"附加关注点"追加，``replace_instructions=True``
    时整体替换默认指令。
    """
    if replace_instructions and custom_instructions:
        instructions = custom_instructions
    elif custom_instructions:
        instructions = f"{BRANCH_SUMMARY_PROMPT}\n\nAdditional focus: {custom_instructions}"
    else:
        instructions = BRANCH_SUMMARY_PROMPT
    return f"<conversation>\n{conversation_text}\n</conversation>\n\n{instructions}"


# ── 摘要器 ──────────────────────────────────────────────


class BranchSummarizer:
    """分支摘要生成器。

    通过注入的 ``llm_complete``（``async (prompt) -> str``，通常是
    ``LLMClient.complete`` 或测试替身）调用 LLM，为一段消息序列生成
    结构化分支摘要。

    所有方法都不修改输入消息。LLM 失败不抛异常，错误经
    ``BranchSummaryResult.error`` 返回；Layer 3 适配器
    ``as_layer3_summarizer`` 例外（见其 docstring）。

    与 ``ContextCompactor`` 配合使用时，两者的 ``context_window``
    应配置为相同的实际模型窗口：摘要预算 = ``context_window -
    reserve_tokens``，若远大于压缩器窗口，摘要 prompt 可能超出
    实际模型容量（失败时压缩器静默回退 Layer 2，Layer 3 事实上
    永不生效且难以察觉）。
    """

    def __init__(
        self,
        llm_complete: LLMComplete,
        *,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        reserve_tokens: int = DEFAULT_RESERVE_TOKENS,
        chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
    ) -> None:
        if not callable(llm_complete):
            raise ValueError("llm_complete must be callable")
        if context_window <= 0:
            raise ValueError("context_window must be positive")
        if reserve_tokens <= 0:
            raise ValueError("reserve_tokens must be positive")
        if reserve_tokens >= context_window:
            raise ValueError("reserve_tokens must be smaller than context_window")
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")

        self._llm_complete = llm_complete
        self._context_window = context_window
        self._reserve_tokens = reserve_tokens
        self._chars_per_token = chars_per_token

    async def summarize_branch(
        self,
        messages: List[Dict[str, Any]],
        *,
        custom_instructions: Optional[str] = None,
        replace_instructions: bool = False,
        include_preamble: bool = True,
    ) -> BranchSummaryResult:
        """为一段消息序列生成结构化分支摘要。

        流程（ported from pi generateBranchSummary）：

        1. 按 ``context_window - reserve_tokens`` 预算选取消息（最新优先）
        2. 序列化为文本转录，构造 ``<conversation>`` prompt
        3. 调用 LLM；失败 → ``result.error``（不抛异常）
        4. 摘要文本前置来源说明（``include_preamble``）、追加文件清单

        Args:
            messages: 待摘要消息列表（时间升序）
            custom_instructions: 自定义摘要关注点（追加或替换默认指令）
            replace_instructions: True 时以 custom_instructions 整体替换
                默认结构化指令
            include_preamble: 是否前置"分支探索"来源说明。作为 Layer 3
                线性压缩使用时建议 False（压缩器自带摘要前缀）

        Returns:
            ``BranchSummaryResult``；``error`` 非空表示失败，
            ``summary`` 仍可能是 "No content to summarize"（空分支，
            非错误）。
        """
        token_budget = self._context_window - self._reserve_tokens
        selected, file_ops, _total = prepare_branch_messages(
            messages, token_budget, self._chars_per_token
        )
        conversation_text = serialize_conversation(selected)

        if not conversation_text.strip():
            return BranchSummaryResult(summary="No content to summarize")

        prompt = (
            f"{SUMMARIZATION_SYSTEM_PROMPT}\n\n"
            f"{build_branch_prompt(conversation_text, custom_instructions, replace_instructions)}"
        )

        try:
            raw = await self._llm_complete(prompt)
        except Exception as exc:
            logger.warning("分支摘要 LLM 调用失败: %s", exc, exc_info=True)
            return BranchSummaryResult(error=str(exc) or type(exc).__name__)

        text = str(raw or "").strip()
        if not text:
            return BranchSummaryResult(error="LLM returned empty summary")

        read_files, modified_files = compute_file_lists(file_ops)
        summary = (BRANCH_SUMMARY_PREAMBLE if include_preamble else "") + text
        summary += format_file_operations(read_files, modified_files)

        return BranchSummaryResult(
            summary=summary,
            read_files=read_files,
            modified_files=modified_files,
        )

    def as_layer3_summarizer(self) -> Layer3Summarizer:
        """返回与 ``context_compactor.Summarizer`` 同构的适配器。

        适配器使用 ``BRANCH_SUMMARY_PROMPT`` 结构化指令，不带分支
        前导（压缩器自带 ``SUMMARY_PREFIX``）。``ContextCompactor``
        按协议传入的 prompt 参数被忽略——那是面向普通会话摘要的
        泛化指令，追加进结构化 prompt 只会产生重复噪声。

        与 ``summarize_branch`` 的容错策略不同：适配器在失败时
        **抛 RuntimeError**，这是刻意的 —— ``compact_with_summary``
        捕获摘要异常后回退纯 Layer 2 滑窗，该契约要求摘要器以异常
        信号失败。
        """

        async def _summarize(evicted_messages: List[Dict[str, Any]], compactor_prompt: str) -> str:
            # compactor_prompt 按 Summarizer 协议传入但刻意不用（见 docstring）
            del compactor_prompt
            result = await self.summarize_branch(evicted_messages, include_preamble=False)
            if result.error or not result.summary:
                raise RuntimeError(result.error or "branch summarization produced no summary")
            return result.summary

        return _summarize

    @staticmethod
    def to_context_message(
        result: BranchSummaryResult,
        *,
        from_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """把摘要结果包装为可注入上下文的 system 消息。

        元数据（来源分支 id、文件清单）放 ``details`` 子字典，避免
        污染传给 LLM 的 role / content 字段；``details.branch_summary``
        标记供 ``prepare_branch_messages`` 识别嵌套摘要。

        Raises:
            ValueError: ``result`` 无摘要文本（失败结果不可注入）
        """
        if not result.summary:
            raise ValueError("cannot build context message from a failed summary result")
        return {
            "role": "system",
            "content": result.summary,
            "details": {
                "branch_summary": True,
                "from_id": from_id,
                "read_files": list(result.read_files),
                "modified_files": list(result.modified_files),
            },
        }
