"""进程内 skill registry adapter (PR-7)。

包装 ``backend.skills.registry.SkillRegistry``,实现
``backend.ports.skill.SkillPort`` 协议。

设计要点
--------

- 接受外部注入的 ``SkillRegistry``(便于测试用 mock 替换);缺省情况下
  使用新建的 ``SkillRegistry`` 并自动 ``register_all_skills()`` 装载
  4 个 builtin skills (search / writer / coder / travel)。
- ``list_skills`` 把 ``SkillSchema``(带 parameters / examples JSON)
  转成端口侧的纯 ``SkillSpec``。
- ``execute`` 内部直接调用 ``skill.execute(params, context)`` (同步),
  然后 ``SkillResult`` 已经是 ``skills.base.SkillResult`` 的实例,
  字段与 ``domain.skill.SkillResult`` 一致,直接构造 domain 版本返回。
- ``is_enabled`` / ``set_enabled`` / ``usage_count`` / ``bump_usage``
  是端口协议外的扩展方法(给路由层用),enabled 状态默认全开、
  usage_count 内存累计,路由层负责序列化。
- 技能未注册 / 已禁用时 ``execute`` 返回 ``success=False, error=...``,
  **不抛异常**,与端口契约"失败时 success=False 并携带 error"一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from sage_core import SkillResult, SkillSpec
from sage_core.repositories import SkillPort  # noqa: F401  (structural typing target)

from backend.skills.registry import SkillRegistry as _SkillRegistry


class InprocSkillAdapter:
    """``SkillPort`` 的 in-process 实现 (PR-7)。

    SKILL.md 适配层 (v1)
    ---------------------

    PR-7 之后扩展: 在 ``__init__`` 末尾尝试调用 ``register_skill_md_skills``
    从 ``discover_skill_md_dirs()`` 发现的目录加载 AgentSkills 规范的
    SKILL.md 技能。SKILL.md 技能与 4 个 builtin 共享同一个 ``SkillRegistry``,
    builtin 名字永远胜 (冲突时 SKILL.md 被 skip + WARNING 日志)。

    路由层调用 ``list_skills_extended()`` (而非 ``list_skills()``) 拿到
    包含 ``source / body / base_dir / version`` 等扩展字段的 dict 列表,
    用于前端折叠展示 SKILL.md 的 body。
    """

    def __init__(self, registry: Optional[_SkillRegistry] = None) -> None:
        # 接受外部注入(用于测试)或使用新建 registry 并装载 builtin
        if registry is not None:
            self._registry = registry
        else:
            from backend.skills import register_all_skills

            self._registry = _SkillRegistry()
            register_all_skills(self._registry)
        # v1: SKILL.md 适配层 (guarded 调用, 失败不破坏 adapter 构造)
        try:
            from backend.skills import register_skill_md_skills

            register_skill_md_skills(self._registry)
        except Exception as exc:  # noqa: BLE001 — adapter 构造必须容错
            import logging

            logging.getLogger(__name__).warning("SkillMd loader skipped in adapter init: %s", exc)
        # enabled 状态: 未登记视为 enabled
        self._enabled: Dict[str, bool] = {}
        # usage_count: 进程内累计,重启归零
        self._usage_count: Dict[str, int] = {}
        # M10: slash command 索引 (从 registry 一次性构建)
        from backend.skills.skill_md.slash_registry import SlashCommandRegistry

        self._slash_registry: SlashCommandRegistry = SlashCommandRegistry.from_registry(
            self._registry,
        )

    # ========== SkillPort 协议方法 ==========

    def list_skills(self) -> List[SkillSpec]:
        """返回所有已注册技能的 spec(按注册顺序)。"""
        specs: List[SkillSpec] = []
        for schema in self._registry.list():
            specs.append(
                SkillSpec(
                    name=schema.name,
                    description=schema.description,
                    triggers=list(schema.triggers),
                    parameters=dict(schema.parameters),
                    examples=list(schema.examples),
                )
            )
        return specs

    async def execute(
        self,
        name: str,
        action: str,
        args: Dict[str, Any],
    ) -> SkillResult:
        """执行技能。

        - 技能不存在 → success=False
        - 技能 disabled → success=False
        - 工具未注入(context={}) 大多数 builtin 会返回 success=False
          ("搜索工具不可用" 等),这是 builtin 的设计行为,不在本层包装。
        """
        if not self._registry.exists(name):
            return SkillResult(
                success=False,
                error=f"skill '{name}' not found",
            )
        if not self.is_enabled(name):
            return SkillResult(
                success=False,
                error=f"skill '{name}' is disabled",
            )
        # BaseSkill.execute 接收 (params, context); action 当前未用
        # (BaseSkill 是单动作技能, action 留给未来的 multi-action skill)
        skill = self._registry.get(name)
        assert skill is not None  # exists() 已 guard
        try:
            raw = skill.execute(args, context={})
        except Exception as exc:  # pragma: no cover - 防御性兜底
            return SkillResult(
                success=False,
                error=f"skill execution failed: {exc}",
            )
        # skills.base.SkillResult 字段与 domain.skill.SkillResult 一致
        # (success / content / metadata / error),直接构造 domain 版本
        return SkillResult(
            success=raw.success,
            content=raw.content,
            metadata=dict(raw.metadata),
            error=raw.error,
        )

    # ========== 路由层辅助方法 (端口协议外) ==========

    def has_skill(self, name: str) -> bool:
        """技能是否已注册(路由层用来在 execute 前判 404)。"""
        return self._registry.exists(name)

    def is_enabled(self, name: str) -> bool:
        """技能是否启用(默认 True)。"""
        return self._enabled.get(name, True)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """设置技能 enabled 状态。返回 False 表示技能名不存在。"""
        if not self._registry.exists(name):
            return False
        self._enabled[name] = bool(enabled)
        return True

    def usage_count(self, name: str) -> int:
        """技能累计使用次数。"""
        return self._usage_count.get(name, 0)

    def bump_usage(self, name: str) -> None:
        """execute 成功时调用,累计 usage_count。"""
        if not self._registry.exists(name):
            return
        self._usage_count[name] = self._usage_count.get(name, 0) + 1

    # ========== M10: slash command 暴露 ==========

    async def execute_command(
        self,
        command: str,
        args: Union[List[str], Tuple[str, ...]] = (),
    ) -> SkillResult:
        """通过 slash command 触发 SKILL.md 技能 (M10)。

        委托 ``SlashCommandRegistry.execute_command`` (走 ``SkillMdSkill.execute_v2``
        v1 body fallback 路径)。返回的 ``content`` 是 SKILL.md body,
        供聊天层注入 system prompt 模板。

        Args:
            command: slash command 名 (带或不带 ``/``)
            args: 命令参数列表 (透传给 execute_v2 params)

        Returns:
            SkillResult: 成功时 ``content`` 是 SKILL.md body

        Raises:
            LookupError: 命令未注册 (路由层转 404)
        """
        result = await self._slash_registry.execute_command(
            command_name=command,
            args=tuple(args),
        )
        # SkillMdSkill.execute_v2 返回 backend.skills.base.SkillResult (含 metadata dict)
        # 路由层需要的是 backend.domain.skill.SkillResult,字段同构,直接构造
        return SkillResult(
            success=result.success,
            content=result.content,
            metadata=dict(result.metadata),
            error=result.error,
        )

    def list_slash_commands(self) -> List[str]:
        """列出所有已注册的 slash command (M10)。

        用于前端自动补全 / chat 输入提示。
        """
        return self._slash_registry.list_commands()

    # ========== Skills management: SKILL.md 删除 (PR-A) ==========

    def delete_skill_md(self, name: str) -> Dict[str, Any]:
        """Public API: 物理删除一个 SKILL.md 技能 (委托给 SkillMdDeleter)。

        仅可删 SKILL.md 技能 (source='skillmd')。builtin 拒绝 — 由
        ``SkillMdDeleter`` 抛 ``BuiltinSkillError``。

        Args:
            name: 技能名 (匹配 ``^[a-z0-9-]{1,64}$``)。

        Returns:
            dict: ``{"deleted": True, "name": str, "base_dir": str}``

        Raises:
            BuiltinSkillError: name 是 builtin (路由层 → 400)
            SkillMdNotFoundError: name 在 registry 不存在或 base_dir 无目录
                (路由层 → 404)
            ValueError: name 非法 或 base_dir 跑出 SAGE_SKILLS_DIR (路由层 → 400)
            FileNotFoundError: SAGE_SKILLS_DIR 未配置 (路由层 → 500)
        """
        # 延迟导入避免循环 (delete.py 依赖 SkillRegistry, 已 import; 这里
        # 引入 SkillMdDeleter 仅供管理 API 使用,不影响路由热路径)
        from backend.skills.skill_md.delete import SkillMdDeleter

        deleter = SkillMdDeleter(self._registry)
        result = deleter.delete(name)
        return dict(result)

    # ========== 扩展序列化 (PR-8 SKILL.md 适配层) ==========

    def list_skills_extended(self) -> List[Dict[str, Any]]:
        """列出所有技能 + 扩展字段 (供路由层序列化到前端)。

        返回的 dict 包含 SkillSpec 全字段 + 扩展字段:
          - ``source`` (str): ``"builtin"`` 或 ``"skillmd"``
          - ``body`` (str | None): 仅 SKILL.md 有值, 是 markdown body
          - ``base_dir`` (str | None): 仅 SKILL.md 有值, 是 SKILL.md 所在目录绝对路径
          - ``version`` (str | None): 仅 SKILL.md 有值, 是 frontmatter ``version`` 字段
          - ``license`` (str | None): agentskills.io spec 字段 (PR-84 后)
          - ``compatibility`` (str | None): agentskills.io spec 字段 (PR-84 后)
          - ``allowed_tools`` (list[str]): agentskills.io spec 字段 (PR-84 后)

        builtin 技能只输出 SkillSpec 字段, **不** 输出扩展字段 (空 key 省略,
        避免 TS strict optional 报警)。
        """
        # 延迟导入避免循环 (skill_md 依赖 base, base 在更早的初始化阶段)
        from backend.skills.skill_md.skill import SkillMdSkill

        result: List[Dict[str, Any]] = []
        for schema in self._registry.list():
            skill = self._registry.get(schema.name)
            assert skill is not None  # list() 与 get() 同源, exists 已 guard
            is_skillmd = isinstance(skill, SkillMdSkill)
            item: Dict[str, Any] = {
                "name": schema.name,
                "description": schema.description,
                "triggers": list(schema.triggers),
                "parameters": dict(schema.parameters),
                "examples": list(schema.examples),
                "source": "skillmd" if is_skillmd else "builtin",
            }
            if is_skillmd:
                # 仅在 SKILL.md 时输出扩展字段
                doc = skill._doc  # type: ignore[attr-defined]
                item["body"] = doc.body
                item["base_dir"] = str(doc.base_dir) if doc.base_dir is not None else None
                item["version"] = doc.version
                # agentskills.io spec optional fields (PR-84): 让 API consumer
                # 能看到 SKILL.md frontmatter 的 license / compatibility /
                # allowed_tools 字段。allowed_tools 是 tuple, 序列化为 list。
                item["license"] = doc.license
                item["compatibility"] = doc.compatibility
                item["allowed_tools"] = list(doc.allowed_tools)
                # v2 DispatchMode 元数据 (M9): 前端根据 user_invocable / command_dispatch
                # 决定如何暴露 (slash command / tool mode),disable_model_invocation
                # 由 chat 层消费 (阻止自动触发),嵌套 dict 形式便于前端 TS 类型推导。
                dp = doc.dispatch
                item["dispatch"] = {
                    "disable_model_invocation": dp.disable_model_invocation,
                    "user_invocable": dp.user_invocable,
                    "user_invocable_name": dp.user_invocable_name,
                    "command_dispatch": dp.command_dispatch,
                }
            result.append(item)
        return result
