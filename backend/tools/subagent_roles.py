"""M3.1: 子代理角色注册表 —— ``agent`` 工具 ``subagent_type`` 解析。

内置角色（始终可用，不依赖 DB）：

- ``explore``（默认，历史行为）：只读工具；定位信息、给出答案。
- ``plan``：只读工具 + 规划指令；产出可执行计划，不修改任何东西。
- ``general-purpose``：读写文件 / 编辑 / 打补丁 / 执行命令 / 网络检索；
  全部工具仍受 ToolPolicy、工作区隔离与审批门禁约束。

DB 启用中的 agent profile（``agents`` 表 / ``.sage/agents/*.md`` 导入）
同样可作 ``subagent_type``：工具集按 profile ``tools`` 白名单从子代理
可用全集中过滤；system prompt 由 ``compose_system_prompt`` 组合；迭代
上限取 profile.max_iterations。

未知的显式 ``subagent_type`` 由调用方返回错误（不静默降级），空值
回落 ``explore``（与历史行为一致）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: 仅探索（默认角色）—— 历史 SUBAGENT_SYSTEM_PROMPT 文本。
EXPLORE_SYSTEM_PROMPT = (
    "You are a focused Sage sub-agent performing a delegated task. "
    "You have READ-ONLY tools: file reading, directory listing, web search/fetch, "
    "memory search — plus a controlled browser channel "
    "(browser_launch/navigate/snapshot/interact/cookies/close) for pages that "
    "need JavaScript rendering or a login state. You cannot modify files or run "
    "commands. File tools can only read the delegated scratch/workspace content; "
    "web fetch and browser navigation reject private or local destinations and "
    "are subject to network mode and approval gates. Complete the task concisely "
    "and return your final answer as plain text."
)

PLAN_SYSTEM_PROMPT = (
    "You are a planning sub-agent for Sage. You have READ-ONLY tools. "
    "Investigate the codebase/content with those tools, then produce a concise, "
    "executable plan: ordered steps, files likely involved, dependencies, risks, "
    "and how to validate. Do NOT modify files or run commands. "
    "Return the plan as plain text."
)

GENERAL_PURPOSE_SYSTEM_PROMPT = (
    "You are a general-purpose Sage sub-agent performing a delegated task. "
    "Unlike explore sub-agents you may read and modify files and run commands, "
    "but every action stays inside the delegated workspace and is subject to "
    "the tool policy, permission gates and approval prompts — destructive or "
    "out-of-scope operations may be denied or require user approval. Prefer "
    "minimal, reversible changes. Complete the task and return a concise final "
    "answer as plain text."
)

#: schema 中最多列出的 DB profile 角色数（防描述超长）。
MAX_PROFILE_ROLES_IN_SCHEMA = 12


@dataclass(frozen=True)
class SubagentRole:
    """一个可派发的子代理角色。"""

    role_id: str
    label: str
    description: str
    #: "explore" | "plan" | "general" | "profile"
    kind: str
    profile: Optional[Dict[str, Any]] = None


BUILTIN_ROLES: Dict[str, SubagentRole] = {
    "explore": SubagentRole(
        role_id="explore",
        label="Explore",
        description="只读探索：读文件/目录、检索网页、记忆检索；适合调研与定位信息",
        kind="explore",
    ),
    "plan": SubagentRole(
        role_id="plan",
        label="Plan",
        description="规划：只读工具 + 输出可执行计划（不修改文件、不执行命令）",
        kind="plan",
    ),
    "general-purpose": SubagentRole(
        role_id="general-purpose",
        label="General",
        description="通用：可读写文件、打补丁、执行命令（受策略与审批约束）",
        kind="general",
    ),
}


def _profile_role(profile: Dict[str, Any]) -> SubagentRole:
    rid = str(profile.get("id") or "").strip() or "unknown"
    label = str(profile.get("name") or rid)
    desc = str(profile.get("description") or profile.get("role") or "").strip()
    return SubagentRole(
        role_id=rid,
        label=label,
        description=desc[:120] or f"角色 {label}",
        kind="profile",
        profile=profile,
    )


def list_subagent_roles(
    max_profiles: int = MAX_PROFILE_ROLES_IN_SCHEMA,
) -> List[SubagentRole]:
    """内置三角色 + 启用中的 DB profile 角色（DB 不可用时仅内置）。"""
    roles: List[SubagentRole] = list(BUILTIN_ROLES.values())
    try:
        from backend.data.agent_repo import AgentRepository

        profiles = AgentRepository().list_all()
    except Exception:  # noqa: BLE001 — DB 不可用时降级为内置角色
        return roles
    for profile in profiles:
        rid = str(profile.get("id") or "").strip()
        if not rid or rid in BUILTIN_ROLES or not profile.get("enabled", True):
            continue
        roles.append(_profile_role(profile))
        if len(roles) >= len(BUILTIN_ROLES) + max_profiles:
            break
    return roles


def resolve_subagent_role(
    subagent_type: Optional[str],
) -> Tuple[SubagentRole, bool]:
    """解析 ``subagent_type``。

    Returns:
        ``(role, known)``。空值 → explore、known=True（默认行为不变）；
        显式未知类型 → explore、known=False（调用方应返回错误）。
    """
    raw = (subagent_type or "").strip()
    if not raw:
        return BUILTIN_ROLES["explore"], True
    key = raw.lower()
    if key in BUILTIN_ROLES:
        return BUILTIN_ROLES[key], True
    try:
        from backend.agents.profiles import get_enabled_agent

        profile = get_enabled_agent(raw)
    except Exception:  # noqa: BLE001 — DB 不可用按未知处理
        profile = None
    if profile:
        return _profile_role(profile), True
    return BUILTIN_ROLES["explore"], False


def role_system_prompt(role: SubagentRole) -> str:
    """角色对应的 system prompt。"""
    if role.kind == "plan":
        return PLAN_SYSTEM_PROMPT
    if role.kind == "general":
        return GENERAL_PURPOSE_SYSTEM_PROMPT
    if role.kind == "profile" and role.profile:
        try:
            from backend.chat.specialist_prompt_composer import compose_system_prompt

            return compose_system_prompt(specialist_profile=role.profile)
        except Exception:  # noqa: BLE001 — 组合失败回落只读探索提示词
            return EXPLORE_SYSTEM_PROMPT
    return EXPLORE_SYSTEM_PROMPT


def role_max_iterations(role: SubagentRole) -> Optional[int]:
    """profile 显式声明的迭代上限（非法值忽略）。"""
    if not role.profile:
        return None
    value = role.profile.get("max_iterations")
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 100:
        return value
    return None


def schema_role_options() -> Tuple[List[str], str]:
    """schema 用：角色 id 列表 + 每行一句描述的 enum 说明。"""
    roles = list_subagent_roles()
    ids = [r.role_id for r in roles]
    lines = [f"- {r.role_id}: {r.description}" for r in roles]
    header = "可选子代理角色（缺省 explore）："
    return ids, header + "\n" + "\n".join(lines)
