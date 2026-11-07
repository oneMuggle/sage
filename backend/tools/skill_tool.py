"""skill 工具 —— in-loop 技能调用（M2 part B）。

让 agent 循环里的 LLM 按名称触发技能（SKILL.md 工作流 / builtin 技能），
与前端 slash menu 走**同一条执行路径**，不重新实现：

- 解析: 复用 ``backend.adapters.out.skill.inproc.get_singleton()`` 单例
  —— 与 ``/api/v1/skills*`` 端点共享同一 ``InprocSkillAdapter``（路由层
  的 ``_get_skill_adapter`` 委托此处），同一个 SkillRegistry、同一份
  enabled 状态。未知技能 → 错误 ToolResult 并列出所有可用技能名。
- 执行: 优先走 ``adapter.execute_command()`` —— 即 ``POST /skills/command``
  使用的同一函数（slash command → ``SkillMdSkill.execute_v2``）。技能不是
  user_invocable slash command 时（如 4 个 builtin），回退到
  ``adapter.execute()`` —— 即 ``POST /skills/{name}/execute`` 使用的函数。
- SKILL.md 脚本执行走既有 ``script_runner`` 沙箱（execute_v2 →
  ScriptRunner.run_script → SandboxPort），本工具不做任何旁路。

异步桥接: BaseTool.execute 是同步签名（agent.run_loop 同步调用），而技能
执行路径是 async。沿用 ``memory_tool`` 的先例：新建临时事件循环跑完即关。

能力分级: EXECUTE —— 技能可编排任意工具调用、SKILL.md 脚本更是直接跑子进程
（虽有沙箱，但语义上是"执行任意动作"），因此按最严格的 EXECUTE 对待，由
M1 审批闸口按模式矩阵拦截（workspace_write/prompt 下逐次确认）。
"""

from __future__ import annotations

import logging
import shlex
from typing import Any, Iterable, List, Optional, Set

from backend.application.services.harness_recorder import HarnessProbe
from backend.domain.skill_scope import resolve_skill_allowlist
from backend.domain.tool_policy import ToolPolicy

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 工具名常量（注册 / 测试共用）
SKILL_TOOL_NAME = "skill"

# 本轮技能作用域（M1，spec §5.1）原语在 domain 层定义，避免
# application → tools 的静态依赖触发六边形架构违规；这里重导出供调用方
# 与测试继续使用。
from backend.domain.skill_scope import (  # noqa: E402 — 分组导入保持文件头整洁
    peek_turn_skill_allowlist,
    reset_turn_skill_allowlist,
    set_turn_skill_allowlist,
)

# 供测试与调用方的模块级重导出（ContextVar 原语已下沉到 domain）。
__all__ = [
    "SkillTool",
    "SKILL_TOOL_NAME",
    "inject_skill_scope",
    "set_turn_skill_allowlist",
    "reset_turn_skill_allowlist",
]


def inject_skill_scope(
    registry: Any, patterns: Iterable[str], agent_id: Optional[str] = None
) -> int:
    """向注册表内所有 ``SkillTool`` 注入专家技能作用域（M1，spec §5.1/§5.2）。

    由 ``SageAgent.__init__`` 在 ``register_all_tools`` + ``inject_memory_manager``
    之后调用；非 SkillTool 条目直接跳过，返回注入次数（生产环境通常为 1）。

    ``agent_id`` 让工具在解析允许集时并入该专家自己的私有技能
    （``specialist__<agent_id>__*``）；``None`` 只解析公开技能。
    """
    count = 0
    list_names = getattr(registry, "list_names", None)
    get = getattr(registry, "get", None)
    if not callable(list_names) or not callable(get):
        return 0
    patterns_list = list(patterns)
    for name in list_names():
        tool = get(name)
        if isinstance(tool, SkillTool):
            tool.skill_patterns = patterns_list
            tool.agent_id = agent_id
            count += 1
    return count


class SkillTool(BaseTool):
    """按名称调用已注册技能的工具。"""

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        adapter: Optional[Any] = None,
        skill_patterns: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """Args:
            policy:  M2 工具策略（缺省 ToolPolicy()）。
            adapter: 可选 InprocSkillAdapter 注入（测试用）；None 时惰性复用
                REST 路由层的模块级单例——与 /api/v1/skills* 端点同一注册表。
            skill_patterns: 专家技能允许集（M1）；None / 空 = 公开技能不受限。
                由 ``inject_skill_scope`` 在 agent 构造时注入，或测试时
                直接传入（避免必须经过 ``inject_skill_scope``）。
            agent_id: 专家 id；提供时允许集并入本人私有技能（M1，spec §5.2）。
        """
        super().__init__(policy)
        self._adapter = adapter
        # 专家技能作用域（M1，spec §5.1）：延迟到执行时解析 ——
        # adapter 是惰性拿到的，避免在 SageAgent 构造期触发一次 fs 扫描。
        self.skill_patterns: Optional[List[str]] = (
            list(skill_patterns) if skill_patterns else None
        )
        self.agent_id: Optional[str] = agent_id

    def _resolve_allowed(self) -> Optional[Set[str]]:
        """惰性解析技能允许集；``None`` = 公开技能不受限（私有技能仍遮罩）。

        优先级: 本轮执行器设置的作用域（ContextVar，hex 共享工具注册表）＞
        构造期注入的专家作用域（legacy SageAgent）＞ 无限制。
        """
        adapter = self._resolve_adapter()
        allowlist_set, turn_allowed = peek_turn_skill_allowlist()
        if allowlist_set:
            return None if turn_allowed is None else set(turn_allowed)
        if self.agent_id:
            resolve_agent = getattr(adapter, "resolve_agent_allowlist", None)
            if callable(resolve_agent):
                return resolve_agent(self.skill_patterns or [], self.agent_id)
        if not self.skill_patterns:
            return None
        names = [spec.name for spec in adapter.list_skills()]
        return resolve_skill_allowlist(self.skill_patterns, names)

    def _resolve_adapter(self) -> Any:
        """取技能适配器：注入优先，否则惰性复用 inproc 单例。

        惰性 import 避免 tools → api 的模块加载期耦合（legacy_routes
        导入面较广）；运行期 backend.main 早已 import 过 inproc，
        无额外开销。

        ``inproc.get_singleton()`` 与
        ``backend.api.legacy_routes._get_skill_adapter()`` 共享同一
        单例缓存（M2b 重构：单例缓存搬到 inproc.py），保证 REST 路由
        与工具共享同一注册表状态。
        """
        if self._adapter is not None:
            return self._adapter
        from backend.adapters.out.skill.inproc import get_singleton

        return get_singleton()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=SKILL_TOOL_NAME,
            description=(
                "按名称调用一个已注册技能（SKILL.md 工作流或内置技能）。"
                "技能是比工具粒度更粗的工作流；未知技能名会返回可用技能清单。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "技能名（如 slash command 名或 builtin 技能名）",
                    },
                    "args": {
                        "type": "string",
                        "description": "传给技能的参数字符串（按 shell 词法切分为参数列表）",
                    },
                    "script": {
                        "type": "string",
                        "description": (
                            "相对技能目录的脚本路径（如 'scripts/scan.py'）。"
                            "提供时走权限闸口（_enforce_permission），执行技能绑定的外部脚本。"
                        ),
                    },
                },
                "required": ["skill"],
            },
        )

    def execute(
        self,
        skill: str = "",
        args: Optional[str] = None,
        script: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """解析并执行技能。

        Args:
            skill: 技能名（必填）
            args:  可选参数字符串
            script: 相对技能目录的脚本路径（提供时走权限闸口执行外部脚本）
        """
        del kwargs
        skill_ok = isinstance(skill, str) and bool(skill.strip())
        # script 路径合法性由 adapter.execute → script_runner 链校验，
        # 这里仅做基本类型检查
        script_ok = script is None or isinstance(script, str)
        if not skill_ok or not script_ok:
            message = (
                "skill 参数必须是非空字符串"
                if not skill_ok
                else "script 参数必须是字符串"
            )
            return ToolResult(success=False, error=message)
        skill = skill.strip()

        adapter = self._resolve_adapter()
        # 专家技能作用域（M1，spec §5.1）：先解析 allowlist，fail-closed。
        # 允许集外的技能按"不存在"处理（不泄漏技能存在性）。
        allowed = self._resolve_allowed()
        denial = self._denial_for(adapter, skill, allowed)
        if denial is not None:
            return ToolResult(success=False, error=denial)

        args_raw = args if isinstance(args, str) else ""
        try:
            args_list: List[str] = shlex.split(args_raw) if args_raw.strip() else []
        except ValueError as exc:  # shlex 引号不配对等
            return ToolResult(success=False, error=f"args 解析失败: {exc}")

        # 异步桥接（memory_tool 先例）：agent.run_loop 同步调用本方法，
        # 而技能执行路径是 async —— 临时事件循环跑完即关。
        import asyncio

        probe = HarnessProbe("skill", skill)
        loop = asyncio.new_event_loop()
        try:
            with probe:
                try:
                    result = loop.run_until_complete(
                        self._invoke(
                            adapter,
                            skill,
                            args_raw,
                            args_list,
                            script=script,
                            allowed=allowed,
                        )
                    )
                    probe.result = result  # SkillResult.success 供 probe 读取
                except Exception as exc:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
                    logger.error("skill 执行失败: skill=%s error=%s", skill, exc)
                    return ToolResult(success=False, error=f"skill 执行失败: {exc}")
        finally:
            # __exit__ 已计算 metrics；loop 仍 open —— 在此 await 埋点，
            # 保证写事务在函数返回前完成（杜绝后台线程 use-after-free）。
            try:
                loop.run_until_complete(probe.aemit())
            finally:
                loop.close()

        if not result.success:
            return ToolResult(success=False, error=result.error or "skill 执行失败")
        return ToolResult(success=True, content=result.content)

    @staticmethod
    def _denial_for(
        adapter: Any, skill: str, allowed: Optional[Set[str]]
    ) -> Optional[str]:
        """拒绝原因；``None`` 表示该技能可执行。

        允许集外技能按"未知技能"报错，可用清单只列允许集内技能 ——
        与真正不存在的技能同构，不泄漏越权技能的存在性。专家私有技能
        （``specialist__`` 前缀）在无显式允许集时同样按未知处理（M1，spec §5.2）。
        """
        from backend.skills.specialist_skills import agent_id_from_private_skill

        if allowed is not None and skill not in allowed:
            available = sorted(allowed)
        elif agent_id_from_private_skill(skill) is not None and allowed is None:
            # 私有技能默认遮罩：清单只列公开技能
            available = [spec.name for spec in adapter.list_skills()]
        elif not adapter.has_skill(skill):
            list_kwargs = {"allowed": allowed} if allowed is not None else {}
            available = [spec.name for spec in adapter.list_skills(**list_kwargs)]
        else:
            return None
        listing = ", ".join(sorted(available)) if available else "(无可用技能)"
        return f"unknown skill: '{skill}'. available skills: {listing}"

    @staticmethod
    async def _invoke(
        adapter: Any,
        skill: str,
        args_raw: str,
        args_list: List[str],
        *,
        script: Optional[str] = None,
        allowed: Optional[Set[str]] = None,
    ) -> Any:
        """走既有执行路径：script 优先 → slash command → builtin 回退。

        - 提供 ``script`` 时直接走 ``adapter.execute`` —— 即
          ``POST /skills/{name}/execute`` 的同一函数，自动触发
          ``_is_script_dispatch`` + ``_enforce_permission`` 权限闸口。
        - ``adapter.execute_command`` —— POST /skills/command 的同一函数
          （user_invocable 的 SKILL.md 技能；未注册命令抛 LookupError）。
        - ``adapter.execute`` —— POST /skills/{name}/execute 的同一函数
          （builtin 等非 slash 技能）。

        ``allowed`` 透传给 adapter（M1，spec §5.1）；adapter 内做 fail-closed。
        仅在 ``allowed`` 非 None 时传递 —— 不受限路径与旧 adapter 实现
        （不含 ``allowed`` 参数）保持完全兼容。
        """
        extra = {"allowed": allowed} if allowed is not None else {}
        if script is not None:
            # script 分发走权限闸口（_enforce_permission 在 adapter.execute 内部）
            return await adapter.execute(
                skill, "", {"script": script, "args": args_list}, **extra
            )
        try:
            return await adapter.execute_command(skill, args_list, **extra)
        except LookupError:
            return await adapter.execute(
                skill, "", {"args": args_raw}, **extra
            )
