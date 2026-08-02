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

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

from sage_core import SkillResult, SkillSpec
from sage_core.repositories import SkillPort  # noqa: F401  (structural typing target)

from backend.skills.registry import SkillRegistry as _SkillRegistry

if TYPE_CHECKING:
    from backend.skills.skill_md.auto_activation import AutoActivationResult


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
        # PR-C: store SkillMdHotLoader dirs + SkillMdImporter for rescan_skill_mds / import_skill_mds
        try:
            from backend.skills.skill_md.importer import SkillMdImporter
            from backend.skills.skill_md.loader import discover_skill_md_dirs

            self._skill_dirs = discover_skill_md_dirs()
            self._skill_importer = SkillMdImporter(self._registry)
        except Exception as exc:  # noqa: BLE001 - adapter init must be tolerant
            import logging

            logging.getLogger(__name__).warning("SkillMd rescan/import wiring skipped: %s", exc)
            self._skill_dirs = []
            self._skill_importer = None
        # enabled 状态: 未登记视为 enabled
        self._enabled: Dict[str, bool] = {}
        # usage_count: 进程内累计, 启动时从 skill_usage 表回填持久化计数
        # （"重启不归零"）; 运行期 bump 同时写内存 + DB。
        self._usage_count: Dict[str, int] = {}
        self._hydrate_usage_from_db()
        # 归档策展状态（spec 2026-08-02-skill-curator-lifecycle）：DB 为持久真相，
        # 内存 Set 为热缓存（auto_activate / slash / list 读它，零 DB）；
        # 启动从 skill_lifecycle 表回填（重启不丢）。
        self._archived: Set[str] = set()
        self._hydrate_archived_from_db()
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
        - **成功路径自动记使用**（bump_usage + DB 持久化）——
          覆盖 REST / SkillTool / 任何走本方法的调用方。
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
        if raw.success:
            self.bump_usage(name)
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
        """execute 成功时调用,累计 usage_count。

        内存态累计（供列表即时读取）+ best-effort 持久化到 ``skill_usage``
        表（重启不归零）。DB 写入失败只 warning, 不影响热路径。
        """
        if not self._registry.exists(name):
            return
        self._usage_count[name] = self._usage_count.get(name, 0) + 1
        try:
            from backend.skills.usage import get_usage_store

            get_usage_store().bump(name, success=True)
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            import logging

            logging.getLogger(__name__).warning(
                f"Skill usage persist failed for {name!r}: {exc}"
            )

    def _hydrate_usage_from_db(self) -> None:
        """从 ``skill_usage`` 表回填持久化使用计数（best-effort）。

        使 ``usage_count()`` 在进程重启后仍返回历史累计值（review HIGH）。
        仅回填 registry 中真实存在的技能; DB 不可用 / 表不存在时跳过。
        """
        try:
            from backend.skills.usage import get_usage_store

            for stat in get_usage_store().get_all():
                name = stat.get("name")
                if name and self._registry.exists(name):
                    self._usage_count[name] = int(stat.get("use_count", 0))
        except Exception as exc:  # pragma: no cover - 防御性兜底
            import logging

            logging.getLogger(__name__).debug(f"技能使用计数回填跳过: {exc}")

    # ========== Skill 生命周期 (curator): active/stale/archived ==========

    def _hydrate_archived_from_db(self) -> None:
        """从 ``skill_lifecycle`` 表回填归档集合（best-effort，重启不丢）。

        仅收 registry 中真实存在的技能（仿 ``_hydrate_usage_from_db``）。
        """
        try:
            from backend.skills.lifecycle import get_lifecycle_store

            for name in get_lifecycle_store().get_archived_names():
                if name and self._registry.exists(name):
                    self._archived.add(name)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            import logging

            logging.getLogger(__name__).debug(f"技能归档状态回填跳过: {exc}")

    def is_archived(self, name: str) -> bool:
        """技能是否已归档（内存热缓存，O(1)）。"""
        return name in self._archived

    def set_archived(self, name: str, archived: bool) -> bool:
        """设置归档状态。返回 False 表示技能名不存在（路由层 → 404）。

        DB 持久真相 + 内存热缓存双写（仿 ``set_enabled``，但持久化到
        ``skill_lifecycle`` 表，重启不丢）。DB 写失败只 warning（best-effort），
        内存态仍更新以保证本次会话一致。
        """
        if not self._registry.exists(name):
            return False
        try:
            from backend.skills.lifecycle import get_lifecycle_store

            get_lifecycle_store().set_archived(name, archived)
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            import logging

            logging.getLogger(__name__).warning(
                f"Skill lifecycle persist failed for {name!r}: {exc}"
            )
        if archived:
            self._archived.add(name)
        else:
            self._archived.discard(name)
        return True

    def lifecycle_map(self) -> Dict[str, str]:
        """批量计算全量 name → lifecycle（active/stale/archived）。

        active/stale 读取时即时算（对 ``now`` 比较 ``skill_usage.last_used_at``），
        archived 取内存缓存。供 ``list_skills_extended`` 一次性调用（非热路径）。
        """
        from backend.skills.lifecycle import classify_lifecycle
        from backend.skills.usage import get_usage_store

        usage = {row["name"]: row for row in get_usage_store().get_all()}
        now_ms = int(time.time() * 1000)
        result: Dict[str, str] = {}
        for name in self._registry.list_names():
            last = (usage.get(name) or {}).get("last_used_at")
            result[name] = classify_lifecycle(last, name in self._archived, now_ms)
        return result

    # ========== A16: Skill Auto-Activation ==========

    def auto_activate(self, message: str) -> AutoActivationResult:
        """按用户消息自动匹配 SKILL.md 的 ``when_to_use``, 返回注入上下文块。

        聊天层 (``ChatService._run_turn_inner`` 步骤 2.6) 在组装本轮
        system prompt 前结构性探测并调用本方法, 把命中技能的 body
        作为动态段追加 —— 不进 frozen snapshot, 不写 storage。

        参与自动匹配的候选过滤 (全部满足):
          - SKILL.md 技能 (builtin 无 ``when_to_use`` 字段, 天然排除)
          - enabled (``set_enabled(False)`` 的技能不参与)
          - ``dispatch.disable_model_invocation`` 为 False (v2 元数据:
            作者显式声明"禁止模型自动触发"时尊重该意图)

        Returns:
            ``AutoActivationResult`` (``names`` + ``context_block``)。

        Note:
            永不外抛 —— 聊天层按 best-effort 语义依赖本契约,
            任何内部故障降级为空结果 (只 debug 日志)。
        """
        # 延迟导入避免循环 (与本模块其他 skill_md 引用同策略)
        from backend.skills.skill_md.auto_activation import (
            AutoActivationResult as _Result,
            auto_activate,
        )
        from backend.skills.skill_md.skill import SkillMdSkill

        if not message:
            return _Result()
        try:
            docs = []
            for schema in self._registry.list():
                skill = self._registry.get(schema.name)
                if not isinstance(skill, SkillMdSkill):
                    continue
                if not self.is_enabled(schema.name):
                    continue
                # 归档技能不参与自动激活（spec：可用性 = enabled ∧ ¬archived）
                if self.is_archived(schema.name):
                    continue
                doc = skill._doc
                if doc.dispatch.disable_model_invocation:
                    continue
                docs.append(doc)
            result = auto_activate(message, docs)
            # 命中技能记使用（bump_usage + DB 持久化）——自动激活也是"使用"
            for matched in result.names:
                self.bump_usage(matched)
            return result
        except Exception as exc:  # noqa: BLE001 — best-effort 契约
            import logging

            logging.getLogger(__name__).debug("A16 auto_activate failed: %s", exc)
            return _Result()

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
        # 归档技能的 slash command 不可用（路由层转 404 command_not_found）
        if self._command_archived(command):
            raise LookupError(f"slash command archived: {command!r}")
        result = await self._slash_registry.execute_command(
            command_name=command,
            args=tuple(args),
        )
        # 成功路径自动记使用（bump_usage + DB 持久化）
        if result.success:
            resolved = self._slash_registry.resolve(command)
            if resolved is not None:
                self.bump_usage(resolved.name)
        # SkillMdSkill.execute_v2 返回 backend.skills.base.SkillResult (含 metadata dict)
        # 路由层需要的是 backend.domain.skill.SkillResult,字段同构,直接构造
        return SkillResult(
            success=result.success,
            content=result.content,
            metadata=dict(result.metadata),
            error=result.error,
        )

    def list_slash_commands(self) -> List[str]:
        """列出所有已注册的 slash command (M10)，排除已归档技能。

        用于前端自动补全 / chat 输入提示。
        """
        return [
            cmd
            for cmd in self._slash_registry.list_commands()
            if not self._command_archived(cmd)
        ]

    def _command_archived(self, command: str) -> bool:
        """slash command 对应的技能是否已归档。"""
        resolved = self._slash_registry.resolve(command)
        return resolved is not None and self.is_archived(resolved.name)

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

    # ========== PR-C: Skills load-new (rescan + import) ==========

    def rescan_skill_mds(self) -> Dict[str, Any]:
        """重扫 SAGE_SKILLS_DIR / ~/.sage/skills / ./skills, 增量加载新 SKILL.md。

        Returns:
            {
                "loaded": [{"name", "source", "path"}],
                "skipped": [{"name", "reason"}],  # currently always [] — plan-mandated limitation
                "total_loaded": int,
            }

        Note on `skipped`: SkillMdHotLoader.scan_and_load() returns (loaded_count, skipped_count)
        as integers only, not detailed [{name, reason}]. Detailed skipped reporting requires
        loader API extension (future work). See plan §4.1 and §10 risk notes.
        """
        if self._skill_importer is None:  # init-time import failed
            return {"loaded": [], "skipped": [], "total_loaded": 0}
        from backend.skills.skill_md.loader import SkillMdHotLoader

        loader = SkillMdHotLoader(self._registry, dirs=list(self._skill_dirs), gating_ctx=None)
        loaded_count, _ = loader.scan_and_load()
        # Fresh loader per call: _loaded_paths only contains THIS call's loads.
        return {
            "loaded": [
                {"name": name, "source": "skillmd", "path": loader._loaded_paths.get(name) or ""}
                for name in loader._loaded_paths
            ],
            "skipped": [],  # plan-mandated limitation; see docstring
            "total_loaded": loaded_count,
        }

    async def import_skill_mds(self, files: List[Any]) -> Dict[str, List[Dict[str, str]]]:
        """异步包装 SkillMdImporter.import_files()。"""
        if self._skill_importer is None:
            return {
                "imported": [],
                "skipped": [{"name": "<unknown>", "reason": "adapter_init_failed"}],
            }
        return await self._skill_importer.import_files(files)

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

        # 生命周期态一次性批量计算（active/stale 读时算，archived 取内存缓存）
        lifecycles = self.lifecycle_map()
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
                # A16: 自动激活触发场景原文，空串表示不参与自动激活
                item["when_to_use"] = doc.when_to_use
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
            # 生命周期态（active/stale/archived）— builtin 与 skillmd 一律计算
            item["lifecycle"] = lifecycles.get(schema.name, "stale")
            result.append(item)
        return result


#: 进程内单例缓存 (M2b 审查加固: 把单例从 backend.api.legacy_routes 搬
#: 到此, 避免 tools -> api 的 import-linter 循环链). 旧 _get_skill_adapter
#: 仍 export 同一单例 (委托此处), 保证 REST 路由与工具共享同一注册表状态.
#:
#: 注: 故意放在 ``InprocSkillAdapter`` class 之后, 让类型注解可以直接引用
#: class 本身, 满足 ruff UP037 (在 ``from __future__ import annotations``
#: 下禁止带引号的 type annotation).
_skill_adapter_singleton: Optional[InprocSkillAdapter] = None


def get_singleton() -> InprocSkillAdapter:
    """惰性构造 + 缓存 InprocSkillAdapter 单例."""
    global _skill_adapter_singleton
    if _skill_adapter_singleton is None:
        _skill_adapter_singleton = InprocSkillAdapter()
    return _skill_adapter_singleton
