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

from typing import Any

from backend.domain.skill import SkillResult, SkillSpec
from backend.ports.skill import SkillPort  # noqa: F401  (structural typing target)
from backend.skills import register_all_skills
from backend.skills.registry import SkillRegistry as _SkillRegistry


class InprocSkillAdapter:
    """``SkillPort`` 的 in-process 实现 (PR-7)。"""

    def __init__(self, registry: _SkillRegistry | None = None) -> None:
        # 接受外部注入(用于测试)或使用新建 registry 并装载 builtin
        if registry is not None:
            self._registry = registry
        else:
            self._registry = _SkillRegistry()
            register_all_skills(self._registry)
        # enabled 状态: 未登记视为 enabled
        self._enabled: dict[str, bool] = {}
        # usage_count: 进程内累计,重启归零
        self._usage_count: dict[str, int] = {}

    # ========== SkillPort 协议方法 ==========

    def list_skills(self) -> list[SkillSpec]:
        """返回所有已注册技能的 spec(按注册顺序)。"""
        specs: list[SkillSpec] = []
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
        args: dict[str, Any],
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
