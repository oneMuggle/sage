"""Persona 声明式 Markdown manifest 加载器（A5，来自 OpenWorker ``coworker/personas``）。

Persona = YAML frontmatter（身份 + 能力声明）+ Markdown body（system prompt）。
与 SKILL.md 同构（``persona ⊇ skill``），但字段更结构化：

.. code-block:: markdown

    ---
    id: ops
    name: Ops Coworker
    icon: wrench
    tools: [terminal, read_file, write_file]
    connectors: true
    recommended_models: [claude-sonnet-4-5, gpt-4-1]
    default_mode: prompt
    ---
    You are the Ops Coworker — ...

设计要点
--------

- **严格解析**：畸形 manifest 抛 ``PersonaManifestError`` 而非静默产出坏
  persona（第三方 persona 必须 fail loudly）。加载器层面单文件失败只
  skip + WARNING，不影响其他 persona。
- ``default_mode`` 校验对齐权限执行器（``backend.tools.permissions.
  PermissionMode``：read_only / workspace_write / prompt / full_access），
  manifest 声明的模式可直接喂给 ``PermissionEnforcer``。
- ``PersonaLoader`` 镜像 ``SkillMdHotLoader`` 的热重载模式（MD5 哈希缓存），
  并额外支持**整目录 rescan**：新增 / 变更 / 删除文件都在一次
  ``scan_and_load()`` 内收敛，无需重启后端。
- id 冲突（跨目录同名 persona）：**先出现的目录胜**（builtin 目录永远
  最先扫描），后者 skip + WARNING，与 skill builtin 优先策略一致。
- 线程安全：内部状态整体构建后在 ``RLock`` 内原子替换，读接口无阻塞竞争。
- 兼容 Python 3.8（release/win7 LTS 分支可能 cherry-pick）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from backend.skills.skill_md.validation import sanitize_for_logging
from backend.tools.permissions import PermissionMode

logger = logging.getLogger(__name__)

# persona id 会成为注册表键与（未来）安装目录名，限制为文件系统安全的
# slug：小写字母/数字起头，允许 '-' / '_'，禁止路径分隔符与 '..' 遍历。
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_VALID_MODES = frozenset(mode.value for mode in PermissionMode)
_FENCE = "---"
_BOM = "\ufeff"


class PersonaManifestError(ValueError):
    """Persona manifest 畸形或声明了非法字段值。"""


@dataclass(frozen=True)
class PersonaManifest:
    """解析后的 persona 声明（不可变值对象）。

    Attributes:
        id:                 persona 唯一标识（slug）。
        name:               展示名。
        system_prompt:      Markdown body —— 即 system prompt。
        icon:               图标标识（前端 gallery 用，缺省空串）。
        tagline:            一句话简介（缺省空串）。
        description:        详细描述（缺省空串）。
        tools:              声明的工具名列表（对应 ``backend.tools`` 注册名）。
        connectors:         是否请求 connector 接入能力。
        recommended_models: 推荐模型列表（仅建议，不校验 provider 目录）。
        default_mode:       默认权限模式（对齐 ``PermissionMode`` 值）。
        builtin:            是否来自内置 personas 目录。
        source:             来源文件路径（provenance，内存加载时为 None）。
    """

    id: str
    name: str
    system_prompt: str
    icon: str = ""
    tagline: str = ""
    description: str = ""
    tools: Tuple[str, ...] = ()
    connectors: bool = False
    recommended_models: Tuple[str, ...] = ()
    default_mode: str = PermissionMode.WORKSPACE_WRITE.value
    builtin: bool = False
    source: Optional[str] = None


# =====================================================================
# 解析
# =====================================================================


def _strip_bom(text: str) -> str:
    """剥除 UTF-8 BOM（若存在），兼容 Windows 工具保存的文件。"""
    if text.startswith(_BOM):
        return text[1:]
    return text


def _split_frontmatter(text: str) -> Tuple[str, str]:
    """切分 frontmatter 与 body。

    Returns:
        (frontmatter_yaml_text, body_text)。

    Raises:
        PersonaManifestError: 缺少 opening/closing fence。
    """
    if not text.startswith(_FENCE):
        raise PersonaManifestError(
            "persona manifest must start with a YAML frontmatter block (---)"
        )
    after_open = text[len(_FENCE):]
    if not after_open or after_open[0] not in ("\n", "\r"):
        raise PersonaManifestError(
            "persona manifest must start with a YAML frontmatter block (---)"
        )

    lines = after_open.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\r\n") == _FENCE:
            frontmatter_text = "".join(lines[:i])
            # closing fence 之后紧跟的空行仅作分隔，不属于 body
            body_text = "".join(lines[i + 1:]).lstrip("\r\n")
            return frontmatter_text, body_text

    raise PersonaManifestError("unterminated frontmatter block (missing closing ---)")


def _slugify(stem: str) -> str:
    """把文件名 stem 规范化到 id 字符集（仅用于从文件名派生 id）。"""
    slug = re.sub(r"[^a-z0-9_-]+", "-", stem.strip().lower()).strip("-_")[:64]
    return slug if _ID_RE.match(slug) else ""


def _strlist(meta: Dict[str, Any], key: str) -> Tuple[str, ...]:
    """取字符串列表字段：接受 YAML list 或逗号分隔字符串，其余类型报错。"""
    val = meta.get(key)
    if val is None:
        return ()
    if isinstance(val, str):
        return tuple(part.strip() for part in val.split(",") if part.strip())
    if isinstance(val, list):
        out: List[str] = []
        for item in val:
            if not isinstance(item, str):
                raise PersonaManifestError(
                    f"`{key}` list items must be strings, got {type(item).__name__}"
                )
            text = item.strip()
            if text:
                out.append(text)
        return tuple(out)
    raise PersonaManifestError(
        f"`{key}` must be a list or comma-separated string, got {type(val).__name__}"
    )


def parse_manifest(
    text: str,
    *,
    fallback_id: Optional[str] = None,
    builtin: bool = False,
    source: Optional[str] = None,
) -> PersonaManifest:
    """解析 persona manifest 文本。

    Args:
        text:        manifest 全文（frontmatter + body）。
        fallback_id: 缺省 ``id`` 字段时从文件名 stem 派生用。
        builtin:     是否内置 persona。
        source:      来源（路径/URL），写入 provenance。

    Raises:
        PersonaManifestError: manifest 畸形或字段值非法。
    """
    text = _strip_bom(text)
    fm_text, body = _split_frontmatter(text)

    try:
        meta = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        raise PersonaManifestError(f"invalid YAML frontmatter: {exc}") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise PersonaManifestError(
            f"frontmatter must be a mapping of key: value, got {type(meta).__name__}"
        )

    # -- id: 显式声明必须合法；缺省时从文件名派生 -----------------------
    explicit_id = str(meta.get("id") or "").strip()
    if explicit_id:
        persona_id = explicit_id
        if not _ID_RE.match(persona_id):
            raise PersonaManifestError(
                f"persona id {persona_id!r} is invalid: lowercase letters, digits, "
                "'-' or '_' only, starting with a letter/digit, max 64 chars"
            )
    else:
        persona_id = _slugify(str(fallback_id or ""))
        if not persona_id:
            raise PersonaManifestError(
                "manifest needs an `id` (or a filename to derive one from)"
            )

    # -- name / body 必填 ------------------------------------------------
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PersonaManifestError(f"persona {persona_id!r}: `name` must be a non-empty string")
    if not body.strip():
        raise PersonaManifestError(
            f"persona {persona_id!r} has no body (the system prompt)"
        )

    # -- default_mode 对齐权限执行器 PermissionMode ------------------------
    # 显式空值（`default_mode:` 后为空，YAML 解析为 None）视同未声明。
    raw_mode = meta.get("default_mode")
    if raw_mode is None:
        raw_mode = PermissionMode.WORKSPACE_WRITE.value
    mode = str(raw_mode).strip().lower()
    if mode not in _VALID_MODES:
        raise PersonaManifestError(
            f"persona {persona_id!r}: default_mode must be one of {sorted(_VALID_MODES)}, "
            f"got {mode!r}"
        )

    # -- connectors 必须是布尔 --------------------------------------------
    connectors = meta.get("connectors", False)
    if not isinstance(connectors, bool):
        raise PersonaManifestError(
            f"persona {persona_id!r}: `connectors` must be a boolean (true/false), "
            f"got {type(connectors).__name__}"
        )

    return PersonaManifest(
        id=persona_id,
        name=name.strip(),
        system_prompt=body.strip(),
        # `icon:` 后为空时 YAML 解析为 None，`or ""` 兜底避免字面量 "null"
        icon=str(meta.get("icon") or "").strip(),
        tagline=str(meta.get("tagline") or "").strip(),
        description=str(meta.get("description") or "").strip(),
        tools=_strlist(meta, "tools"),
        connectors=connectors,
        recommended_models=_strlist(meta, "recommended_models"),
        default_mode=mode,
        builtin=builtin,
        source=source,
    )


def load_manifest_file(path: Path, *, builtin: bool = False) -> PersonaManifest:
    """读盘并解析单个 persona manifest 文件。

    Raises:
        PersonaManifestError: 文件读失败或 manifest 畸形。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError 是 ValueError 子类：二进制 / UTF-16 存成 .md
        # 的文件必须归一为 PersonaManifestError，否则单文件会炸掉整轮扫描。
        raise PersonaManifestError(f"failed to read persona manifest {p}: {exc}") from exc
    return parse_manifest(text, fallback_id=p.stem, builtin=builtin, source=str(p))


# =====================================================================
# 目录发现
# =====================================================================


def builtin_personas_dir() -> Path:
    """内置 personas 目录（随仓库分发，只读语义）。"""
    return Path(__file__).parent / "personas"


def discover_persona_dirs() -> List[Path]:
    """按优先级返回用户级 persona 搜索目录（不含 builtin）。

    优先级:
      1. ``$SAGE_PERSONAS_DIR`` 环境变量指向的目录（若存在）
      2. ``~/.sage/personas``（若存在）

    不存在的目录会被过滤掉，调用方拿到的列表都可直接扫描。
    """
    roots: List[Path] = []

    env_dir = os.environ.get("SAGE_PERSONAS_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        if p.is_dir():
            roots.append(p)

    user_personas = Path.home() / ".sage" / "personas"
    if user_personas.is_dir() and user_personas not in roots:
        roots.append(user_personas)

    return roots


# =====================================================================
# 热加载器
# =====================================================================


@dataclass(frozen=True)
class SyncResult:
    """一次 rescan 的收敛结果。"""

    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0


class PersonaLoader:
    """从目录扫描加载 persona manifest，支持无重启热加载。

    - 内置 personas（``builtin_personas_dir()``）永远最先扫描，id 冲突时
      builtin 胜（与 skill builtin 优先策略一致）。
    - ``scan_and_load()`` 是一次完整 rescan：新增文件加载、变更文件重载、
      删除文件卸载，全部在一次调用内收敛 —— 供启动时与运行期（如
      Settings → Personas 的 Refresh / 定时轮询）复用同一入口。
    - 单文件解析失败只 skip + WARNING，不阻断其他 persona。
    """

    def __init__(
        self,
        dirs: Optional[List[Path]] = None,
        *,
        include_builtin: bool = True,
    ) -> None:
        builtin_dir = builtin_personas_dir() if include_builtin else None
        self._builtin_dir = builtin_dir
        user_dirs = discover_persona_dirs() if dirs is None else [Path(d) for d in dirs]
        self._dirs: List[Path] = (
            [builtin_dir] + user_dirs if builtin_dir is not None else user_dirs
        )
        self._manifests: Dict[str, PersonaManifest] = {}
        self._file_hashes: Dict[str, str] = {}  # path str -> md5
        self._paths_by_id: Dict[str, str] = {}  # persona id -> path str
        self._lock = threading.RLock()

    # ===== scan / load =====

    def scan_and_load(self) -> SyncResult:
        """全量 rescan 所有目录，收敛新增 / 变更 / 删除。

        Returns:
            ``SyncResult`` —— 各事件计数（解析/读盘失败计入 ``skipped``）。
        """
        new_manifests: Dict[str, PersonaManifest] = {}
        new_hashes: Dict[str, str] = {}
        new_paths: Dict[str, str] = {}
        seen_paths: set = set()
        skipped = 0

        for d in self._dirs:
            if not d.is_dir():
                continue
            is_builtin = self._builtin_dir is not None and d == self._builtin_dir
            for md in sorted(d.glob("*.md")):
                if md.name.startswith("."):
                    continue  # 隐藏文件（.git / 编辑器临时文件等）
                path_str = str(md)
                if path_str in seen_paths:
                    continue
                seen_paths.add(path_str)

                try:
                    manifest = load_manifest_file(md, builtin=is_builtin)
                    # 哈希与解析在同一 try 内：parse 之后文件被删/锁掉
                    # （TOCTOU）时只 skip 这一份，不炸掉整轮 rescan。
                    file_hash = self._compute_hash(md)
                except PersonaManifestError as exc:
                    logger.warning(
                        "persona manifest invalid at %s: %s",
                        md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
                    continue
                except OSError as exc:
                    logger.warning(
                        "persona manifest unreadable at %s: %s",
                        md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
                    continue

                if manifest.id in new_manifests:
                    logger.warning(
                        "persona id collision: '%s' already loaded from %s, skipping %s "
                        "(first directory wins)",
                        manifest.id,
                        new_paths[manifest.id],
                        md,
                    )
                    skipped += 1
                    continue

                new_manifests[manifest.id] = manifest
                new_paths[manifest.id] = path_str
                new_hashes[path_str] = file_hash

        with self._lock:
            old_manifests = self._manifests
            old_hashes = self._file_hashes
            old_paths = self._paths_by_id

            added = [pid for pid in new_manifests if pid not in old_manifests]
            removed = [pid for pid in old_manifests if pid not in new_manifests]
            updated = [
                pid
                for pid in new_manifests
                if pid in old_manifests
                and new_hashes[new_paths[pid]] != old_hashes.get(old_paths[pid])
            ]

            self._manifests = new_manifests
            self._file_hashes = new_hashes
            self._paths_by_id = new_paths

        if added or updated or removed or skipped:
            logger.info(
                "persona scan: %d added, %d updated, %d removed, %d skipped "
                "(total %d loaded)",
                len(added),
                len(updated),
                len(removed),
                skipped,
                len(new_manifests),
            )
        return SyncResult(
            added=len(added),
            updated=len(updated),
            removed=len(removed),
            skipped=skipped,
        )

    # ===== hot reload =====

    def check_for_updates(self) -> List[str]:
        """返回内容已变更（或文件已删除）的 persona id 列表，不修改状态。"""
        with self._lock:
            snapshot = list(self._paths_by_id.items())
            old_hashes = dict(self._file_hashes)
        stale: List[str] = []
        for persona_id, path_str in snapshot:
            path = Path(path_str)
            if not path.is_file():
                stale.append(persona_id)
                continue
            try:
                changed = self._compute_hash(path) != old_hashes.get(path_str)
            except OSError:
                # 读不动（权限/IO 抖动）视同变更：下次 rescan 会 skip + WARNING
                changed = True
            if changed:
                stale.append(persona_id)
        return stale

    def hot_reload(self) -> SyncResult:
        """热重载入口 —— 等价于一次 ``scan_and_load()`` rescan。"""
        return self.scan_and_load()

    # ===== queries =====

    def get(self, persona_id: str) -> Optional[PersonaManifest]:
        """按 id 取 persona，未知 id 返回 None。"""
        with self._lock:
            return self._manifests.get(persona_id)

    def ids(self) -> List[str]:
        """已加载的 persona id 列表。"""
        with self._lock:
            return list(self._manifests)

    def list_all(self) -> List[PersonaManifest]:
        """已加载的全部 persona manifest。"""
        with self._lock:
            return list(self._manifests.values())

    def get_stats(self) -> Dict[str, Any]:
        """加载器状态快照（诊断 / API 用）。"""
        with self._lock:
            return {
                "loaded_personas": len(self._manifests),
                "watched_files": len(self._file_hashes),
                "persona_dirs": [str(d) for d in self._dirs],
                "ids": list(self._manifests),
            }

    # ===== internals =====

    @staticmethod
    def _compute_hash(path: Path) -> str:
        """MD5(文件字节) —— 仅作变更检测缓存键，非安全用途。"""
        return hashlib.md5(path.read_bytes()).hexdigest()
