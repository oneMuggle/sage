"""A16: Skill Auto-Activation — 按 SKILL.md ``when_to_use`` 自动匹配用户消息。

移植自 LLM_Simple (``main.py::_auto_activate_skills`` +
``_extract_triggers``), 适配 sage 的 ``SkillMdDocument`` 数据结构。

工作流
------

1. SKILL.md frontmatter 声明 ``when_to_use`` (触发场景描述, 可含引号短语
   与逗号分隔的裸短语, 支持中英文)。
2. 用户消息到达聊天层时, ``auto_activate()`` 提取各技能 ``when_to_use``
   中的触发短语, 对消息文本做大小写不敏感的子串匹配。
3. 命中的技能按 LLM_Simple 同款 ``<system-reminder>`` 块格式组装成
   ``context_block``, 由聊天层追加到本轮 system prompt (动态段,
   不进 frozen snapshot, 不写 storage)。

设计要点
--------

- 纯函数模块: 不依赖 registry / adapter / LLM。输入是消息文本 +
  ``SkillMdDocument`` 序列; 输出 ``AutoActivationResult``。
  enabled / ``disable_model_invocation`` 过滤由调用方 (adapter 层)
  在构造 docs 序列前完成, 本模块假设传入的都是"可参与自动匹配"的文档。
- 触发短语提取支持三种写法 (与 LLM_Simple 对齐):
  引号短语 (``"code review"`` / ``"审查代码"`` / 弯引号)、逗号分隔裸短语
  (``code review, 审查代码``, 兼容中文全角逗号)、以及两者混合。
- 长度 < 2 的触发词被过滤 (误报率高); 逗号分隔段中以 ``use when``
  开头的元描述短语同样被过滤 (与参考实现一致; 注意引号提取路径
  不做 use-when 过滤, 这是参考实现的原始行为)。
- 单条消息最多激活 ``MAX_AUTO_ACTIVATED_SKILLS`` 个技能, 且总块
  尺寸不超过 ``MAX_CONTEXT_BLOCK_CHARS`` 字符, 防止 prompt 膨胀;
  超限技能按 registry 顺序跳过 (LLM_Simple 无双重上限, 此处为
  防御性收紧)。被跳过的技能仍可通过显式 slash command 调用。
- 注入内容是裸 SKILL.md body (与 sage 显式调用路径
  ``slash_registry`` / ``execute_v2`` v1 fallback 一致), **不**加
  LLM_Simple ``invoke_prompt`` 的 ``Base directory for this skill:``
  头 —— 保持同一 body 在不同触发路径下的注入格式自洽。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Iterable, List, Sequence, Tuple

from .resources import render_body_with_resources
from .skill import SkillMdDocument
from .validation import SkillMdSecurityError

logger = logging.getLogger(__name__)

#: 单条消息最多自动激活的技能数 (防 prompt 膨胀)。
MAX_AUTO_ACTIVATED_SKILLS = 5

#: 注入块总尺寸上限 (字符)。超限技能整块跳过 (不截断 body,
#: 避免半截指令误导模型); 显式 slash 调用不受此限。
MAX_CONTEXT_BLOCK_CHARS = 32_000

#: 每个技能块的 framing 开销估算 (system-reminder 头 + 分隔符,
#: 用于尺寸闸门投影, 取保守上整)。
_PER_SKILL_OVERHEAD_CHARS = 256

#: 触发词最小长度 — 单字符短语误报率过高, 与 LLM_Simple 一致跳过。
_MIN_TRIGGER_LEN = 2

#: 引号短语提取: ASCII 双引号 + 中文弯引号 (U+201C / U+201D)。
_QUOTED_TRIGGER_RE = re.compile(r'["“”]([^"“”]+)["“”]')

#: 逗号分隔切分: 兼容 ASCII 逗号与中文全角逗号 (LLM_Simple 仅 ASCII,
#: 此处收紧对中文 frontmatter 的支持)。
_COMMA_SPLIT_RE = re.compile(r"[,，]")


def extract_triggers(when_to_use: str) -> List[str]:
    """从 ``when_to_use`` 原文提取触发短语列表 (小写, 去重, 保序)。

    提取规则 (移植 LLM_Simple::MainWindow._extract_triggers):

    1. 引号短语: ``"keyword"`` / ``“中文关键词”`` — 整条短语作为一个触发词。
    2. 逗号分隔裸短语: ``code review, 审查代码`` — 每段 strip 引号
       (含弯引号) 与空白后作为一个触发词。
    3. 过滤: 长度 < 2 的短语; 逗号段中 ``use when`` 开头的元描述短语
       (如 ``Use when the user asks to review code``)。注意: 引号提取
       路径不做 use-when 过滤 (参考实现原始行为, 长句作子串几乎不
       命中, 实际危害近零)。

    Args:
        when_to_use: frontmatter 字段原文。

    Returns:
        小写触发短语列表 (去重保序); 无有效短语时为空列表。
    """
    triggers: List[str] = []

    # 1) 引号短语 (中英文)
    for quoted in _QUOTED_TRIGGER_RE.findall(when_to_use):
        token = quoted.strip().lower()
        if token and len(token) >= _MIN_TRIGGER_LEN:
            triggers.append(token)

    # 2) 逗号分隔裸短语 (fallback: 引号外的部分也按逗号切)
    #    strip 含弯引号 (U+201C/U+201D/U+2018/U+2019), 避免产出永不命中的死触发词
    for part in _COMMA_SPLIT_RE.split(when_to_use):
        token = part.strip().strip('"“”‘’\'').strip().lower()
        if (
            token
            and len(token) >= _MIN_TRIGGER_LEN
            and not token.startswith("use when")
        ):
            triggers.append(token)

    # 去重保序
    seen = set()
    unique: List[str] = []
    for token in triggers:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _matches(message_lower: str, when_to_use: str) -> bool:
    """消息 (已小写) 是否命中 ``when_to_use`` 的任一触发短语。"""
    return any(trigger in message_lower for trigger in extract_triggers(when_to_use))


def build_context_block(activated: Sequence[SkillMdDocument]) -> str:
    """把命中的技能文档组装成可注入 system prompt 的上下文块。

    单个技能块格式与 LLM_Simple 对齐::

        <system-reminder>
        Skill '<name>' auto-activated: <description>
        Follow the instructions below.
        </system-reminder>

        <SKILL.md body>

    多个技能块之间用 ``\\n\\n---\\n\\n`` 分隔, 整体前置一行中文说明,
    便于模型理解这段注入的来源。空序列返回空字符串。

    与 LLM_Simple 的差异: 直接注入裸 ``doc.body``, 不加
    ``Base directory for this skill:`` 头 —— 与 sage 显式调用路径
    (slash_registry / execute_v2 v1 fallback) 的注入格式保持自洽。
    """
    if not activated:
        return ""

    parts: List[str] = []
    for doc in activated:
        try:
            body = doc.body
            if doc.base_dir is not None and doc.resources is not None:
                body = render_body_with_resources(
                    body, base_dir=doc.base_dir, index=doc.resources
                )
        except SkillMdSecurityError:
            logger.warning(
                "Skipping auto-activated skill '%s' due to resource security validation",
                doc.name,
            )
            continue
        parts.append(
            "<system-reminder>\n"
            f"Skill '{doc.name}' auto-activated: {doc.description}\n"
            "Follow the instructions below.\n"
            "</system-reminder>\n\n"
            f"{body}"
        )

    header = "以下是根据用户本次消息自动激活的技能指令 (A16 Skill Auto-Activation):"
    return header + "\n\n" + "\n\n---\n\n".join(parts)


@dataclass(frozen=True)
class AutoActivationResult:
    """一次自动激活匹配的结果。

    Attributes:
        names: 命中的技能名 (按匹配顺序, 截断到上限后)。
        context_block: 可直接追加到 system prompt 的文本; 无命中为空串。
    """

    names: Tuple[str, ...] = ()
    context_block: str = ""

    @property
    def activated(self) -> bool:
        """是否有技能被激活。"""
        return bool(self.names)


def auto_activate(
    message: str,
    docs: Iterable[SkillMdDocument],
) -> AutoActivationResult:
    """扫描消息文本, 返回命中 ``when_to_use`` 的技能及注入块。

    Args:
        message: 用户消息原文 (匹配大小写不敏感)。
        docs: 候选技能文档序列 (调用方已过滤 enabled /
            ``disable_model_invocation``)。

    Returns:
        ``AutoActivationResult``; 空消息或无命中时 ``names`` 为空元组、
        ``context_block`` 为空串。
    """
    if not message:
        return AutoActivationResult()

    message_lower = message.lower()
    activated: List[SkillMdDocument] = []
    projected_chars = 0
    for doc in docs:
        if not doc.when_to_use:
            continue
        if not _matches(message_lower, doc.when_to_use):
            continue
        rendered_doc = doc
        if doc.base_dir is not None and doc.resources is not None:
            try:
                rendered_body = render_body_with_resources(
                    doc.body, base_dir=doc.base_dir, index=doc.resources
                )
            except SkillMdSecurityError:
                logger.warning(
                    "Skipping auto-activated skill '%s' due to resource security validation",
                    doc.name,
                )
                continue
            # Cache the rendered prompt and clear render metadata so the
            # build step cannot render it a second time.
            rendered_doc = replace(doc, body=rendered_body, base_dir=None, resources=None)
        if len(activated) >= MAX_AUTO_ACTIVATED_SKILLS:
            logger.debug(
                "A16 auto-activation count cap reached (%d); remaining skills ignored",
                MAX_AUTO_ACTIVATED_SKILLS,
            )
            break
        # 尺寸闸门: 投影超限的整块跳过 (不截断 body), 后续较小的
        # 命中技能仍可参与 (first-fit); 超限技能显式 slash 调用不受影响
        next_chars = projected_chars + len(rendered_doc.body) + _PER_SKILL_OVERHEAD_CHARS
        if next_chars > MAX_CONTEXT_BLOCK_CHARS:
            logger.debug(
                "A16 auto-activation skipping '%s': block would exceed %d chars",
                doc.name,
                MAX_CONTEXT_BLOCK_CHARS,
            )
            continue
        activated.append(rendered_doc)
        projected_chars = next_chars

    if not activated:
        return AutoActivationResult()

    names = tuple(doc.name for doc in activated)
    logger.info("A16 skill auto-activation matched: %s", ", ".join(names))
    return AutoActivationResult(
        names=names,
        context_block=build_context_block(activated),
    )
