"""SKILL.md 技能导入器。

- 接收 multipart UploadFile 列表
- 每个文件: parse frontmatter → 校验 name → 检查 builtin 冲突 → 写盘 → hot_reload
- 落地目录: SAGE_SKILLS_DIR -> ~/.sage/skills (auto-mkdir)
- 防御: 1MB size cap + slug 校验 + path traversal 防御 + yaml.safe_load
- 部分失败不影响其他文件 (collected into 'skipped')

设计要点(镜像 SkillMdDeleter):
- builtin name 永远胜, SKILL.md skip + warning
- 文件已存在 skip + warning (本期不支持覆盖)
- 单文件解析失败 skip + warning, 不抛
- 写失败 skip + warning, 不抛
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..registry import SkillRegistry
from .exceptions import NoSkillsDirError

if TYPE_CHECKING:
    from .loader import SkillMdHotLoader

logger = logging.getLogger(__name__)

# 复用 delete.py 的 slug 规则 (防御: 路径遍历 + 非法字符)
try:
    from .delete import _SKILL_NAME_RE
except ImportError:  # pragma: no cover - 防御性兜底
    _SKILL_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB

# Type alias for the input UploadFile-like object
UploadedFile = Any  # fastapi.UploadFile 等;运行时 duck-typed


class SkillMdImporter:
    """从内存中的 .md 文件批量导入到 skills_dir。"""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        skills_dir: Path | None = None,
    ) -> None:
        self._registry = registry
        self._explicit_skills_dir = skills_dir
        self._batch_loader: SkillMdHotLoader | None = None  # lazy-init for batch reuse

    async def import_files(self, files: list[UploadedFile]) -> dict[str, list[dict[str, str]]]:
        """逐文件解析 + 写盘 + hot_reload, 聚合结果。

        Returns:
            {
                "imported": [{"name": str, "path": str}],
                "skipped": [{"name": str, "reason": str}],
            }
        """
        if not files:
            return {"imported": [], "skipped": []}

        skills_dir = self._resolve_skills_dir()
        imported: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []

        for f in files:
            try:
                content = await f.read()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read upload %s: %s", f.filename, exc)
                skipped.append({"name": f.filename or "<unknown>", "reason": f"read_failed: {exc}"})
                continue

            # size cap
            if len(content) > MAX_FILE_SIZE_BYTES:
                skipped.append(
                    {
                        "name": f.filename or "<unknown>",
                        "reason": f"file_too_large: {len(content)} > {MAX_FILE_SIZE_BYTES}",
                    }
                )
                continue

            # parse frontmatter
            raw_name = f.filename or "<unknown>"
            try:
                meta, body = parse_file_from_bytes(content, fallback_name=f.filename)
            except Exception as exc:  # noqa: BLE001
                # 解析失败时使用 fallback_name (无扩展名) 作为识别名
                fallback = _strip_md_extension(raw_name) if raw_name != "<unknown>" else raw_name
                skipped.append({"name": fallback, "reason": f"parse_error: {exc}"})
                continue

            name = meta.get("name", "")
            if not isinstance(name, str) or not _SKILL_NAME_RE.match(name):
                fallback = _strip_md_extension(raw_name) if raw_name != "<unknown>" else raw_name
                skipped.append({"name": name or fallback, "reason": "invalid_name"})
                continue

            # builtin 冲突: builtin 胜
            if self._registry.exists(name):
                skipped.append({"name": name, "reason": "builtin_conflict"})
                continue

            # 磁盘已有同名 SKILL.md: skip (本期不覆盖)
            target = skills_dir / name / "SKILL.md"
            if target.exists():
                skipped.append({"name": name, "reason": "already_exists"})
                continue

            # 写盘
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            except OSError as exc:
                logger.warning("Write failed for %s: %s", target, exc)
                skipped.append({"name": name, "reason": f"write_failed: {exc}"})
                continue

            # hot reload (注册到 registry)
            try:
                self._hot_reload_from_path(target)
                imported.append({"name": name, "path": str(target)})
                logger.info("SkillMd imported: %s from %s", name, target)
            except Exception as exc:  # noqa: BLE001
                # Roll back the just-written file so disk and registry stay in sync.
                logger.error("Hot reload failed for %s: %s; rolling back file", name, exc)
                try:
                    target.unlink()
                    target.parent.rmdir()  # 只在空时删
                except OSError:
                    pass
                skipped.append({"name": name, "reason": f"hot_reload_failed: {exc}"})

        return {"imported": imported, "skipped": skipped}

    def _resolve_skills_dir(self) -> Path:
        """解析 skills_dir: 显式参数 > SAGE_SKILLS_DIR > ~/.sage/skills (auto-mkdir)。

        与 SkillMdDeleter._resolve_skills_dir 行为对齐, 但增加了 auto-mkdir。
        """
        if self._explicit_skills_dir is not None:
            d = self._explicit_skills_dir.expanduser()
            try:
                d.mkdir(parents=True, exist_ok=True)
                return d
            except OSError as exc:
                raise NoSkillsDirError(f"Cannot create {d}: {exc}") from exc

        env = os.environ.get("SAGE_SKILLS_DIR", "").strip()
        if env:
            d = Path(env).expanduser()
            try:
                d.mkdir(parents=True, exist_ok=True)
                return d
            except OSError as exc:
                raise NoSkillsDirError(f"Cannot create SAGE_SKILLS_DIR={d}: {exc}") from exc

        user = Path.home() / ".sage" / "skills"
        try:
            user.mkdir(parents=True, exist_ok=True)
            return user
        except OSError as exc:
            raise NoSkillsDirError(f"Cannot create {user}: {exc}") from exc

    def _hot_reload_from_path(self, path: Path) -> None:
        """从单文件路径解析 + 注册到 registry。失败抛异常让调用方处理。

        复用同一 batch 内已构造的 SkillMdHotLoader（首次按需 lazy-init），避免每文件
        重新构建 loader + 重复 walk dirs。

        直接复用 SkillMdHotLoader._load_from_path(),因为:
          - 文件刚写到磁盘, 还没在 _loaded_paths 里
          - hot_reload(name) 内部先 unregister 再 _load_from_path, 这里不需要 unregister
          - _load_from_path 会做完整的 parse + validate + 冲突检查 + register + 记 _loaded_paths + 算 hash
        """
        if self._batch_loader is None:
            from .loader import SkillMdHotLoader

            self._batch_loader = SkillMdHotLoader(
                self._registry,
                dirs=[path.parent.parent],
                gating_ctx=None,
            )
        loaded = self._batch_loader._load_from_path(path)
        if not loaded:
            # _load_from_path 内部已经 log warning, 这里转 raise 让 caller 走 rollback
            raise RuntimeError(
                f"failed to register {path} (parse/validation/conflict — see warning)"
            )


def _strip_md_extension(filename: str) -> str:
    """从文件名剥除 .md 扩展名,用于 parse_error / invalid_name 的 fallback name。"""
    if filename.lower().endswith(".md"):
        return filename[:-3]
    return filename


def parse_file_from_bytes(
    content: bytes, *, fallback_name: str | None = None
) -> tuple[dict[str, Any], str]:
    """从字节内容解析 frontmatter, 返回 (meta, body)。

    与 parse_file(path) 对齐, 但不依赖文件系统。

    用 re.split 切分首尾的 `---` 边界:
      - 容忍 closing delimiter 缺尾随换行 (真实 SKILL.md 常见)
      - 容忍 closing delimiter 周围有空白
      - maxsplit=2 保证 body 部分不丢失其中嵌的 '---' 文本
    """
    import yaml

    text = content.decode("utf-8")
    parts = re.split(r"^---\s*\n", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3 or parts[0] != "":
        raise ValueError("missing closing frontmatter delimiter '---'")

    fm_text, body = parts[1], parts[2]

    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error: {exc}") from exc

    if not isinstance(meta, dict):
        raise ValueError(f"frontmatter must be a YAML mapping, got {type(meta).__name__}")

    if "name" not in meta:
        raise ValueError("frontmatter missing required field 'name'")

    return meta, body
