"""Slash command registry - 索引 user_invocable=true 的 SKILL.md 技能 (M10)。

设计要点
--------

- 单一职责: 只负责 command_name → SkillMdSkill 映射;不直接执行副作用
- ``execute_command()`` 委托给 ``SkillMdSkill.execute_v2`` (M8) 的 v1 body fallback 路径,
  返回 body 作为 system prompt 模板。脚本执行仍走 POST ``/skills/{name}/execute``
  with 显式 ``script`` 参数 — slash command 不直接 dispatch 脚本
- 不可变索引: ``from_registry()`` 时一次性构建,后续修改 registry 不会反映
  (调用方若 reload, 需重新构建 SlashCommandRegistry)
- 命令名规范化: 接受带或不带前导斜杠, 内部统一存为 ``/name`` 形式
"""

from __future__ import annotations

from ..registry import SkillRegistry
from .skill import SkillMdSkill


class SlashCommandRegistry:
    """Slash command → SkillMdSkill 索引。"""

    def __init__(self, mapping: dict[str, SkillMdSkill] | None = None) -> None:
        self._commands: dict[str, SkillMdSkill] = mapping or {}

    @classmethod
    def from_registry(cls, registry: SkillRegistry) -> SlashCommandRegistry:
        """从 SkillRegistry 构建 slash command 索引。

        索引规则:
          - 遍历 registry.list() 所有 skill
          - 仅 ``SkillMdSkill`` 实例且 ``doc.dispatch.user_invocable == True`` 才索引
          - builtin (非 ``SkillMdSkill``) 永不索引
          - key 优先用 ``dispatch.user_invocable_name``,fallback 到 ``/{doc.name}``
        """
        mapping: dict[str, SkillMdSkill] = {}
        for schema in registry.list():
            skill = registry.get(schema.name)
            if skill is None or not isinstance(skill, SkillMdSkill):
                continue
            doc = skill._doc  # type: ignore[attr-defined]
            if not doc.dispatch.user_invocable:
                continue
            cmd_name = doc.dispatch.user_invocable_name or f"/{doc.name}"
            normalized = cls._normalize(cmd_name)
            mapping[normalized] = skill
        return cls(mapping)

    def resolve(self, command_name: str) -> SkillMdSkill | None:
        """解析命令名为 skill,未找到返回 None。

        接受 ``"/foo"`` / ``"foo"`` / ``"//foo"`` 等变体,内部规范化。
        """
        normalized = self._normalize(command_name)
        return self._commands.get(normalized)

    def list_commands(self) -> list[str]:
        """返回所有已注册命令名 (规范化后, 带前导斜杠)。"""
        return list(self._commands.keys())

    async def execute_command(
        self,
        command_name: str,
        args: tuple[str, ...] = (),
    ):
        """执行 slash command: 委托 ``SkillMdSkill.execute_v2`` 走 v1 body fallback。

        Args:
            command_name: 命令名 (带或不带 ``/``)
            args: 命令参数 (元组, 列表化后透传 execute_v2 params)

        Returns:
            SkillResult: ``content`` 为 SKILL.md body, 供聊天层注入 system prompt

        Raises:
            LookupError: 命令未注册 (路由层转 404)
        """
        skill = self.resolve(command_name)
        if skill is None:
            raise LookupError(f"slash command not registered: {command_name!r}")
        return await skill.execute_v2(
            params={"args": list(args)},
            context={},
        )

    @staticmethod
    def _normalize(command_name: str) -> str:
        """规范化命令名: ``/foo`` / ``foo`` / ``//foo`` 全部 → ``/foo``。

        空字符串 / 纯斜杠 → 空字符串 (resolve 时映射 miss, 返回 None)。
        """
        if not command_name:
            return ""
        stripped = command_name.lstrip("/")
        return f"/{stripped}" if stripped else ""
