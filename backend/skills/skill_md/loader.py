"""SKILL.md 热加载器 + 目录发现。

- ``discover_skill_md_dirs()``: 按优先级返回 SKILL.md 搜索根
- ``SkillMdHotLoader``: 镜像 ``backend/tools/skill.py::SkillHotLoader`` 模式
  (深度 1 目录扫描 + MD5 哈希缓存 + 热重载)
- ``register_skill_md_skills()``: ``InprocSkillAdapter`` 启动时调用的便捷封装

设计要点
--------

- v1 只识别 ``<dir>/<skill_name>/SKILL.md`` (深度 1 目录, 包含 SKILL.md 文件)。
  不支持 ``<dir>/SKILL.md`` 单文件形态 (为 v2 留口子)。
- 隐藏目录(以 ``.`` 开头)跳过, 避免误加载 ``.git`` / ``.venv`` 内的 SKILL.md。
- builtin 名字冲突: builtin 永远胜, SKILL.md skip + WARNING 日志。优先级
  通过 ``registry.exists(name)`` 在加载前判定, 保证不可逆。
- 路径遍历防御由 ``validation.validate_base_dir`` 提供 (此处不调,
  在 chat 层的 ``{baseDir}`` 替换路径上拦截)。
- 日志中的不可信 body 走 ``validation.sanitize_for_logging`` 脱敏。
- v2: 支持条件加载门控 (requires/os/always), 通过 ``gating_ctx`` 参数启用。
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..registry import SkillRegistry
from .frontmatter import SkillMdParseError, parse_file
from .gating import GatingContext, evaluate_gating
from .skill import DispatchMode, RequiresSpec, SkillMdDocument, SkillMdSkill
from .validation import sanitize_for_logging

logger = logging.getLogger(__name__)


def _parse_allowed_tools(tools_str: Any) -> Tuple[str, ...]:
    """解析 allowed-tools 字段: 空格分隔字符串 → tuple (去空, 保序)。

    Args:
        tools_str: 来自 frontmatter 的 raw 值(可能为 None / str / 其他)。

    Returns:
        元组,如 ``("Bash", "Read", "Write")``。
        非字符串输入返回空元组(防御性 fallback)。
    """
    if not isinstance(tools_str, str):
        return ()
    return tuple(part for part in tools_str.split() if part)


def discover_skill_md_dirs() -> List[Path]:
    """按优先级返回 SKILL.md 搜索根列表。

    优先级:
      1. ``$SAGE_SKILLS_DIR`` 环境变量指向的目录 (若存在)
      2. ``$CWD/skills`` (若存在)
      3. ``~/.sage/skills`` (若存在)

    不存在的目录会被过滤掉 (而不是抛错), 调用方拿到的列表都是可直接扫描的。
    """
    roots: List[Path] = []

    env_dir = os.environ.get("SAGE_SKILLS_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        if p.is_dir():
            roots.append(p)

    cwd_skills = Path.cwd() / "skills"
    if cwd_skills.is_dir() and cwd_skills not in roots:
        roots.append(cwd_skills)

    user_skills = Path.home() / ".sage" / "skills"
    if user_skills.is_dir() and user_skills not in roots:
        roots.append(user_skills)

    return roots


class SkillMdHotLoader:
    """从目录加载 SKILL.md 到 SkillRegistry, 支持哈希热重载。

    与 ``backend/tools/skill.py::SkillHotLoader`` 的核心差异:
      - 加载的是 ``<dir>/<name>/SKILL.md`` 目录形态 (不是 ``*.py`` 文件)
      - 注册的是 ``SkillMdSkill(BaseSkill)`` (不是任意 ``BaseSkill`` 子类)
      - 冲突优先级: builtin 胜, SKILL.md skip
      - v2: 支持条件加载门控 (requires/os/always)
    """

    def __init__(
        self,
        registry: SkillRegistry,
        dirs: Optional[List[Path]] = None,
        gating_ctx: Optional[GatingContext] = None,
    ) -> None:
        self._registry = registry
        self._dirs: List[Path] = list(dirs or [])
        self._file_hashes: Dict[str, str] = {}
        self._loaded_paths: Dict[str, str] = {}  # skill_name -> file_path str
        self._gating_ctx = gating_ctx  # None = 不门控 (v1 行为)

    # ===== scan / load =====

    def scan_and_load(self) -> Tuple[int, int]:
        """扫描所有 dirs, 加载新 SKILL.md。返回 ``(loaded_count, skipped_count)``。

        支持两种文件形态 (agentskills.io spec):
          - 形态 A: 子目录形态 <dir>/<name>/SKILL.md (v1 已有)
          - 形态 B: 单文件形态 <dir>/SKILL.md (Task 5 新增)

        skipped_count 包括:
          - builtin 同名冲突
          - parse 失败
          - 验证失败 (缺 name/description, name 不是 slug)
          - 实例化失败 (极少见, 但防御性兜底)

        优先级: builtin 名称 > 子目录形态 > 单文件形态(同 name 时后者 skip)。
        """
        loaded = 0
        skipped = 0
        for d in self._dirs:
            if not d.is_dir():
                continue
            # 形态 A: 子目录形态 <dir>/<name>/SKILL.md
            for entry in sorted(d.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name.startswith("."):
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                try:
                    if self._load_from_path(skill_md):
                        loaded += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001 - 防御性兜底
                    logger.warning(
                        "SKILL.md load failed for %s: %s",
                        skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
            # 形态 B: 单文件形态 <dir>/SKILL.md (Task 5)
            root_skill_md = d / "SKILL.md"
            if root_skill_md.is_file():
                try:
                    if self._load_from_path(root_skill_md):
                        loaded += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SKILL.md single-file load failed for %s: %s",
                        root_skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
        if loaded:
            logger.info("SkillMd scan: %d loaded, %d skipped", loaded, skipped)
        return loaded, skipped

    def _load_from_path(self, path: Path) -> bool:
        """从单个 SKILL.md 路径加载, 返回 True 表示成功注册, False 表示跳过。"""
        try:
            meta, body = parse_file(path)
        except SkillMdParseError as exc:
            logger.warning(
                "SKILL.md parse error in %s: %s",
                path,
                sanitize_for_logging(str(exc), max_len=200),
            )
            return False

        name = meta["name"]
        if self._registry.exists(name):
            logger.warning(
                "SkillMd name collision: '%s' already in registry (builtin wins), skipping %s",
                name,
                path,
            )
            return False

        # 构造 SkillMdDocument (含 v2 字段)
        requires_data = meta.get("requires", {})
        if not isinstance(requires_data, dict):
            requires_data = {}

        requires_spec = RequiresSpec(
            bins=list(requires_data.get("bins", []))
            if isinstance(requires_data.get("bins"), list)
            else [],
            env=list(requires_data.get("env", []))
            if isinstance(requires_data.get("env"), list)
            else [],
            config=list(requires_data.get("config", []))
            if isinstance(requires_data.get("config"), list)
            else [],
        )

        # agentskills.io spec optional fields (Task 4)
        license_val = meta.get("license")
        compatibility_val = meta.get("compatibility")
        allowed_tools_tuple = _parse_allowed_tools(meta.get("allowed-tools"))

        doc = SkillMdDocument(
            name=name,
            description=meta.get("description", ""),
            triggers=list(meta.get("triggers", []))
            if isinstance(meta.get("triggers"), list)
            else [],
            body=body,
            base_dir=path.parent,
            version=str(meta["version"]) if "version" in meta else None,
            metadata=dict(meta.get("metadata", {}))
            if isinstance(meta.get("metadata"), dict)
            else {},
            raw_frontmatter=dict(meta),
            # v2 字段
            requires=requires_spec,
            os=list(meta.get("os", [])) if isinstance(meta.get("os"), list) else [],
            always=bool(meta.get("always", False)),
            dispatch=DispatchMode(
                disable_model_invocation=bool(meta.get("disable-model-invocation", False)),
                user_invocable=bool(meta.get("user-invocable", False)),
                user_invocable_name=str(meta["user-invocable-name"])
                if "user-invocable-name" in meta
                else None,
                command_dispatch=str(meta.get("command-dispatch", "auto")),
            ),
            resources=None,  # ResourceIndex 后续构建
            # agentskills.io spec optional fields (Task 4)
            license=license_val if isinstance(license_val, str) else None,
            compatibility=compatibility_val if isinstance(compatibility_val, str) else None,
            allowed_tools=allowed_tools_tuple,
        )

        # agentskills.io spec: name 应匹配父目录名 (Task 4)
        # 仅 warning,不阻断加载(避免破坏历史 SKILL.md 的命名习惯)
        parent_name = path.parent.name
        if name != parent_name:
            logger.warning(
                "SKILL.md at %s declares name='%s' but parent dir is '%s'; "
                "agentskills.io spec recommends name matches parent dir",
                path,
                name,
                parent_name,
            )

        # 评估门控条件 (v2 特性)
        if self._gating_ctx is not None:
            gating_result = evaluate_gating(doc, self._gating_ctx)
            if not gating_result.allowed:
                logger.info(
                    "SKILL.md gating failed for '%s' at %s: %s (always=%s, always_override=%s)",
                    name,
                    path,
                    "; ".join(gating_result.reasons),
                    doc.always,
                    gating_result.always_override,
                )
                return False

        try:
            skill = SkillMdSkill(doc, base_dir=path.parent)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "SkillMdSkill instantiation failed for %s: %s",
                name,
                sanitize_for_logging(str(exc), max_len=200),
            )
            return False

        self._registry.register(skill)
        self._loaded_paths[name] = str(path)
        self._file_hashes[str(path)] = self._compute_hash(path)
        logger.info(
            "SkillMd loaded: %s (version=%s) from %s",
            name,
            doc.version,
            path,
        )
        return True

    # ===== hot reload =====

    def check_for_updates(self) -> List[str]:
        """扫所有已加载文件, 返回内容变更的 skill 名称列表。"""
        updated: List[str] = []
        for path_str, old_hash in list(self._file_hashes.items()):
            path = Path(path_str)
            if not path.exists():
                continue
            new_hash = self._compute_hash(path)
            if new_hash != old_hash:
                for name, p in self._loaded_paths.items():
                    if p == path_str:
                        updated.append(name)
                        break
        return updated

    def hot_reload(self, skill_name: str) -> bool:
        """强制热重载指定 skill (即使哈希未变)。"""
        path_str = self._loaded_paths.get(skill_name)
        if not path_str:
            return False
        path = Path(path_str)
        if not path.exists():
            return False
        self._registry.unregister(skill_name)
        return self._load_from_path(path)

    def hot_reload_all(self) -> int:
        """批量热重载所有变更文件。返回成功数。"""
        reloaded = 0
        for name in self.check_for_updates():
            if self.hot_reload(name):
                reloaded += 1
        return reloaded

    def get_stats(self) -> Dict[str, Any]:
        return {
            "loaded_skills": len(self._loaded_paths),
            "watched_files": len(self._file_hashes),
            "skill_dirs": [str(d) for d in self._dirs],
        }

    @staticmethod
    def _compute_hash(path: Path) -> str:
        """MD5(UTF-8 字节), 内容变化即触发热重载。"""
        return hashlib.md5(path.read_bytes()).hexdigest()


def register_skill_md_skills(
    registry: SkillRegistry,
    dirs: Optional[List[str]] = None,
    gating_ctx: Optional[GatingContext] = None,
) -> int:
    """便捷封装: 从 ``dirs`` (或 ``discover_skill_md_dirs()``) 加载 SKILL.md。

    Args:
        registry: 技能注册表
        dirs: 搜索目录列表 (None = 使用默认发现逻辑)
        gating_ctx: 门控上下文 (None = 不门控, v1 行为)

    Returns:
        成功加载的 skill 数量 (跳过的不计)。

    Notes:
        调用方应负责异常隔离 (本函数不抛异常, 失败记 WARNING)。
        主要供 ``InprocSkillAdapter`` 在 ``__init__`` 末尾 guarded 调用。
    """
    skill_dirs = discover_skill_md_dirs() if dirs is None else [Path(d) for d in dirs]

    if not skill_dirs:
        return 0

    loader = SkillMdHotLoader(registry, skill_dirs, gating_ctx=gating_ctx)
    loaded, _ = loader.scan_and_load()
    return loaded
