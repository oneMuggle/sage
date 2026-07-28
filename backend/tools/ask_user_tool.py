"""ask_user_question 工具 —— agent 向用户提问（M2 part B）。

设计（与 claw-code AskUserQuestion 对齐）:

- **本模块是纯渲染器**: ``execute()`` 只把（由 agent 循环注入的）用户应答
  渲染成 ToolResult，不与闸口交互。闸口交互（发事件、await 应答、超时
  兜底）全部由 ``backend.core.legacy.agent.run_loop`` 负责——和 M1 审批流
  "循环拥有 gate" 的职责划分一致。
- run_loop 在分发前特判工具名 ``ask_user_question``：先
  ``validate_ask_user_args()`` 校验参数（question 非空、options 2-4 项且
  每项有 label），再发 ASK_USER_QUESTION 事件、await UserQuestionGate，
  最后以 ``answers`` / ``custom`` 注入的方式调用本工具。
- 超时未应答 → 循环注入空应答，本工具渲染"用户未回答"软结果；agent
  带着该结果继续跑（永不挂起）。

能力分级见 ``backend.tools.permissions.TOOL_CAPABILITIES``：READ（零副作用）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 工具名常量（run_loop 特判 / 测试共用）
ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"

#: Claude AskUserQuestion 约束: 2-4 个选项
MIN_OPTIONS = 2
MAX_OPTIONS = 4

#: 未应答时的软结果文案（agent 据此自行选择合理默认值）
UNANSWERED_RESULT_TEXT = "用户未回答，请自行决定合理默认值"


def _validate_options(options: Any) -> Optional[str]:
    """校验 options 列表（2-4 项，每项含非空 label）；合法返回 None。"""
    if not isinstance(options, list):
        return "options 必须是列表"
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        return f"options 数量必须在 {MIN_OPTIONS}-{MAX_OPTIONS} 之间，实际 {len(options)}"
    for idx, opt in enumerate(options):
        if not isinstance(opt, dict):
            return f"options[{idx}] 必须是对象"
        label = opt.get("label")
        if not isinstance(label, str) or not label.strip():
            return f"options[{idx}].label 必须是非空字符串"
    return None


def validate_ask_user_args(args: Dict[str, Any]) -> Optional[str]:
    """校验 LLM 传入的 ask_user_question 参数；合法返回 None，否则返回错误描述。

    约束（镜像 Claude AskUserQuestion）:
    - ``question``: 非空字符串
    - ``header``:   可选字符串
    - ``options``:  2-4 项的列表，每项是含非空 ``label`` 的对象，
                    可选 ``description``
    - ``multi_select``: 可选布尔
    """
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return "question 必须是非空字符串"

    header = args.get("header")
    if header is not None and not isinstance(header, str):
        return "header 必须是字符串（可选）"

    options_error = _validate_options(args.get("options"))
    if options_error is not None:
        return options_error

    multi_select = args.get("multi_select")
    if multi_select is not None and not isinstance(multi_select, bool):
        return "multi_select 必须是布尔值（可选）"

    return None


def render_answer_result(
    answers: Sequence[str],
    custom: Optional[str],
) -> ToolResult:
    """把用户应答渲染为 ToolResult（纯函数，供 execute 复用）。

    - 有选项 / 有自由文本 → 成功结果，content 为渲染后的应答文本。
    - 两者皆空（超时 / 用户 Escape 空提交）→ 成功结果 +
      ``UNANSWERED_RESULT_TEXT`` 软提示（工具本身未失败，is_error=False）。
    """
    selected = [str(a) for a in answers if str(a).strip()]
    custom_text = custom.strip() if isinstance(custom, str) else ""

    if not selected and not custom_text:
        return ToolResult(success=True, content=UNANSWERED_RESULT_TEXT)

    lines: List[str] = ["用户已回答:"]
    lines.extend(f"- {item}" for item in selected)
    if custom_text:
        lines.append(f"补充说明: {custom_text}")
    return ToolResult(success=True, content="\n".join(lines))


class AskUserQuestionTool(BaseTool):
    """ask_user_question —— 把用户应答渲染为工具结果（纯渲染器）。"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=ASK_USER_QUESTION_TOOL_NAME,
            description=(
                "向用户提一个结构化问题并等待回答。当你需要用户在几个明确选项间做决定时使用"
                "（如输出格式、实现方案、是/否确认）。提供 2-4 个选项，每个选项带 label"
                "和可选 description；multi_select=true 时允许多选。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "展示给用户的完整问题文本",
                    },
                    "header": {
                        "type": "string",
                        "description": '可选的短标签（UI 角标，如"输出格式"）',
                    },
                    "options": {
                        "type": "array",
                        "description": f"{MIN_OPTIONS}-{MAX_OPTIONS} 个选项",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "选项文本（回传给 agent 的值）",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "选项的补充说明（可选）",
                                },
                            },
                            "required": ["label"],
                        },
                        "minItems": MIN_OPTIONS,
                        "maxItems": MAX_OPTIONS,
                    },
                    "multi_select": {
                        "type": "boolean",
                        "description": "是否允许多选（默认 false）",
                    },
                },
                "required": ["question", "options"],
            },
        )

    def execute(
        self,
        question: str = "",
        header: Optional[str] = None,
        options: Optional[List[Dict[str, Any]]] = None,
        multi_select: bool = False,
        answers: Optional[Sequence[str]] = None,
        custom: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """渲染用户应答为 ToolResult。

        ``answers`` / ``custom`` 由 agent 循环在闸口应答后注入；直接调用
        （无注入）等价于空应答，渲染"用户未回答"软结果。
        ``question`` / ``header`` / ``options`` / ``multi_select`` 是 LLM
        原始参数，渲染阶段仅用于日志（校验已在 run_loop 前置完成）。
        """
        del header, options, multi_select, kwargs  # 渲染阶段不消费
        logger.debug("ask_user_question 渲染应答: question=%r answers=%r", question, answers)
        return render_answer_result(answers or (), custom)
