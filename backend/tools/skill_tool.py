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
from typing import Any, List, Optional

from backend.domain.tool_policy import ToolPolicy

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 工具名常量（注册 / 测试共用）
SKILL_TOOL_NAME = "skill"


class SkillTool(BaseTool):
    """按名称调用已注册技能的工具。"""

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        adapter: Optional[Any] = None,
    ) -> None:
        """Args:
        policy:  M2 工具策略（缺省 ToolPolicy()）。
        adapter: 可选 InprocSkillAdapter 注入（测试用）；None 时惰性复用
            REST 路由层的模块级单例——与 /api/v1/skills* 端点同一注册表。
        """
        super().__init__(policy)
        self._adapter = adapter

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
                },
                "required": ["skill"],
            },
        )

    def execute(self, skill: str = "", args: Optional[str] = None, **kwargs) -> ToolResult:
        """解析并执行技能。

        Args:
            skill: 技能名（必填）
            args:  可选参数字符串
        """
        del kwargs
        if not isinstance(skill, str) or not skill.strip():
            return ToolResult(success=False, error="skill 参数必须是非空字符串")
        skill = skill.strip()

        adapter = self._resolve_adapter()
        if not adapter.has_skill(skill):
            available = sorted(spec.name for spec in adapter.list_skills())
            listing = ", ".join(available) if available else "(无可用技能)"
            return ToolResult(
                success=False,
                error=f"unknown skill: '{skill}'. available skills: {listing}",
            )

        args_raw = args if isinstance(args, str) else ""
        try:
            args_list: List[str] = shlex.split(args_raw) if args_raw.strip() else []
        except ValueError as exc:  # shlex 引号不配对等
            return ToolResult(success=False, error=f"args 解析失败: {exc}")

        # 异步桥接（memory_tool 先例）：agent.run_loop 同步调用本方法，
        # 而技能执行路径是 async —— 临时事件循环跑完即关。
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self._invoke(adapter, skill, args_raw, args_list)
            )
        except Exception as exc:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("skill 执行失败: skill=%s error=%s", skill, exc)
            return ToolResult(success=False, error=f"skill 执行失败: {exc}")
        finally:
            loop.close()

        if not result.success:
            return ToolResult(success=False, error=result.error or "skill 执行失败")
        return ToolResult(success=True, content=result.content)

    @staticmethod
    async def _invoke(
        adapter: Any,
        skill: str,
        args_raw: str,
        args_list: List[str],
    ) -> Any:
        """走既有执行路径：slash command 优先，builtin 回退。

        - ``adapter.execute_command`` —— POST /skills/command 的同一函数
          （user_invocable 的 SKILL.md 技能；未注册命令抛 LookupError）。
        - ``adapter.execute`` —— POST /skills/{name}/execute 的同一函数
          （builtin 等非 slash 技能）。
        """
        try:
            return await adapter.execute_command(skill, args_list)
        except LookupError:
            return await adapter.execute(skill, "", {"args": args_raw})
