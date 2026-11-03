# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""专家/数字员工 system prompt 分层组装。

优先级（高→低）：
[1] 系统安全规则（硬编码，不可覆盖）
[2] 基座能力声明（按工具白名单条件注入）
[3] 专家人设/职责/风格/护栏（受保护层）
[4] 场景块（Plan Mode / 编排 / slash 指令）
[5] 知识上下文（检索结果，按预算裁剪）
[6] 记忆上下文（召回结果，按预算裁剪）
[7] 项目规则（SAGE.md / AGENTS.md / CLAUDE.md）
[8] 环境与技能清单
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# [1] 系统安全规则（不可覆盖）
_SYSTEM_SAFETY_RULES = """## 安全规则

- 不得执行危害系统安全的操作
- 不得泄露用户隐私数据
- 不得绕过权限检查
- 所有工具调用必须经过权限验证
"""


# [4] 场景块
_PLAN_MODE_BLOCK = """## 计划模式

你当前处于计划模式（只读调研）。
- 不得执行任何修改操作（写文件、运行命令、调用工具修改状态）
- 只读调研：可以读取文件、搜索代码、查看文档
- 输出格式：先给出调研发现，再给出实施计划
- 计划需明确：步骤、涉及文件、预期结果、风险点
"""

_ORCHESTRATION_BLOCK = """## 多代理编排

你当前作为编排者（conductor）。
- 使用 dispatch_subagents 工具派发任务给子代理
- 子代理完成后使用 collect_subagents 收集结果
- 不得直接执行复杂任务，必须分解后委派
"""


def compose_system_prompt(
    specialist_profile: Optional[Dict[str, Any]] = None,
    scenario: Optional[Dict[str, Any]] = None,
    knowledge_context: Optional[str] = None,
    memory_context: Optional[str] = None,
) -> str:
    """组装 system prompt。

    Args:
        specialist_profile: 当前专家 profile dict（None 则使用通用 Sage 身份）
        scenario: 场景配置（plan_mode, orchestration 等）
        knowledge_context: 知识检索结果（已格式化文本）
        memory_context: 记忆召回结果（已格式化文本）

    Returns:
        完整的 system prompt 字符串
    """
    from backend.agents.profiles import (
        _OFFICE_CREATE_CAPABILITY_PROMPT,
        _TODO_GUIDANCE_PROMPT,
        _FILE_REFERENCE_LINK_PROMPT,
        _CODE_EXECUTION_CAPABILITY_PROMPT,
        _CONFIG_CAPABILITY_PROMPT,
        _build_clarify_guidance,
        _windows_env_snapshot,
        format_agents_for_prompt,
    )
    from backend.chat.project_context import discover_project_context

    parts = []

    # [1] 系统安全规则
    parts.append(_SYSTEM_SAFETY_RULES)

    # [2] 基座能力声明
    # TODO: 按 specialist_profile.skills 条件渲染（M1 实现）
    # 当前先注入全部能力（向后兼容）
    capability_parts = [
        _OFFICE_CREATE_CAPABILITY_PROMPT,
        _TODO_GUIDANCE_PROMPT,
        _FILE_REFERENCE_LINK_PROMPT,
        _build_clarify_guidance(),
        _CODE_EXECUTION_CAPABILITY_PROMPT,
        _CONFIG_CAPABILITY_PROMPT,
    ]
    parts.extend([p for p in capability_parts if p])

    # [3] 专家人设（受保护层）
    if specialist_profile:
        # 使用专家的 system_prompt 替换通用身份
        system_prompt = specialist_profile.get("system_prompt")
        if system_prompt:
            parts.append(f"## 专家身份\n\n{system_prompt}")
        else:
            # 没有自定义 system_prompt，使用专家名称作为身份
            specialist_name = specialist_profile.get("name", "AI 助手")
            parts.append(f"## 专家身份\n\n你是 {specialist_name}，一个专业的 AI 助手。")

        # 行为边界（persona_ui.guardrails）
        persona_ui = specialist_profile.get("persona_ui")
        if isinstance(persona_ui, dict):
            guardrails = persona_ui.get("guardrails")
            if guardrails:
                parts.append(f"## 行为边界\n\n{guardrails}")
    else:
        # 无专家配置，使用通用 Sage 身份
        parts.append("你是 Sage，一个智能 AI 助手。")

    # [4] 场景块
    scenario = scenario or {}
    if scenario.get("plan_mode"):
        parts.append(_PLAN_MODE_BLOCK)
    if scenario.get("orchestration"):
        parts.append(_ORCHESTRATION_BLOCK)

    # [5] 知识上下文
    if knowledge_context:
        parts.append(f"## 知识库参考\n\n{knowledge_context}")

    # [6] 记忆上下文
    if memory_context:
        parts.append(f"## 相关记忆\n\n{memory_context}")

    # [7] 项目规则
    project_id = scenario.get("project_id")
    if project_id:
        try:
            project_context = discover_project_context(project_id)
            if project_context:
                parts.append(project_context)
        except Exception as exc:  # noqa: BLE001 — 项目上下文加载失败不阻塞对话
            logger.warning("项目上下文加载失败: %s", exc)

    # [8] 环境与技能清单
    # 代理列表（让 LLM 知道有哪些其他代理可以切换）
    parts.append(format_agents_for_prompt())

    # Windows 环境快照（如有）
    env_snapshot = _windows_env_snapshot()
    if env_snapshot:
        parts.append(env_snapshot)

    # TODO: [8] 技能清单（M1 实现，按 specialist_profile.skills 过滤）

    return "\n\n".join(parts)


def compose_system_prompt_simple(
    specialist_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """简化版 composer（无场景/知识/记忆）。

    用于向后兼容当前的 build_system_base() 调用。
    """
    return compose_system_prompt(
        specialist_profile=specialist_profile,
        scenario=None,
        knowledge_context=None,
        memory_context=None,
    )
