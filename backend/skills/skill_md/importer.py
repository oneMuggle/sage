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
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import yaml

from ...wiki.files import secure_delete_path
from ..registry import SkillRegistry
from ..safe_writer import write_skill_file
from .exceptions import NoSkillsDirError
from .frontmatter import (
    SkillMdParseError,
    _is_valid_name,
    _split_frontmatter,
    _strip_bom,
    parse,
)

if TYPE_CHECKING:
    from .loader import SkillMdHotLoader
    from .script_runner import ScriptRunner

logger = logging.getLogger(__name__)

# Canonical name validation lives in frontmatter.py and is reused by import paths.

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB per file
MAX_IMPORT_FILES = 100
MAX_IMPORT_TOTAL_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per batch
_UPLOAD_READ_CHUNK_BYTES = 64 * 1024

# Type alias for the input UploadFile-like object
UploadedFile = Any  # fastapi.UploadFile 等;运行时 duck-typed


async def _read_upload_with_limit(upload: UploadedFile) -> Tuple[Optional[bytes], int]:
    """分块读取上传文件；超限时立即停止且不保留超限内容。"""
    chunks: List[bytes] = []
    total = 0

    while total < MAX_FILE_SIZE_BYTES:
        requested = min(_UPLOAD_READ_CHUNK_BYTES, MAX_FILE_SIZE_BYTES - total)
        chunk = await upload.read(requested)
        if not chunk:
            return b"".join(chunks), total
        if not isinstance(chunk, bytes):  # noqa: UP038 - Python 3.8 compatibility
            chunk = bytes(chunk)
        chunk_size = len(chunk)
        if chunk_size > requested:
            # AsyncMock and other UploadFile-like test doubles may ignore size.
            return None, total + chunk_size
        chunks.append(chunk)
        total += chunk_size

    extra = await upload.read(1)
    if extra:
        extra_size = len(extra) if isinstance(extra, bytes) else len(bytes(extra))  # noqa: UP038 - Python 3.8 compatibility
        return None, total + extra_size
    return b"".join(chunks), total


def _target_exists_without_following_links(target: Path) -> bool:
    """Return whether the target existed before this import, without following it."""
    try:
        os.lstat(str(target))
    except FileNotFoundError:
        return False
    except OSError:
        # An inaccessible path is conservatively treated as pre-existing.
        return True
    return True


def _cleanup_partial_write(skills_dir: Path, target: Path, target_existed: bool) -> None:
    """Best-effort, boundary-safe cleanup of a file created by a failed write."""
    if target_existed:
        return
    with suppress(OSError):
        secure_delete_path(skills_dir, target)


_BIDI_CONTROL_CODEPOINTS = frozenset(
    {
        0x061C,  # Arabic Letter Mark
        0x200E,  # Left-to-right mark
        0x200F,  # Right-to-left mark
        *range(0x202A, 0x202F),  # embeddings, overrides, and isolates
        *range(0x2066, 0x206A),  # directional isolates
    }
)


def _is_unsafe_upload_label_char(char: str) -> bool:
    """Return whether ``char`` could alter a response or log rendering."""
    codepoint = ord(char)
    # Replace C0/C1 controls (including NUL, newline, tab, and ESC/ANSI).
    return codepoint < 0x20 or 0x7F <= codepoint <= 0x9F or codepoint in _BIDI_CONTROL_CODEPOINTS


def _safe_upload_basename(filename: Any) -> str:
    """Return a basename label safe for client responses and logging.

    Untrusted path components are removed and rendering controls are replaced
    rather than echoed, so labels cannot inject newlines, ANSI sequences, or
    bidirectional text controls into API responses or logs.
    """
    if not filename:
        return "<unknown>"
    basename = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    safe = "".join("_" if _is_unsafe_upload_label_char(char) else char for char in basename)
    return safe or "<unknown>"


def _name_field_is_invalid(content: bytes) -> bool:
    """Classify only an explicitly supplied, invalid YAML ``name`` field.

    This is deliberately a best-effort second parse used only for classification;
    ``frontmatter.parse`` remains the sole schema authority.  It never includes
    parsed values in a public error and treats undecodable/malformed YAML as
    ordinary ``parse_error``.
    """
    try:
        text = _strip_bom(content.decode("utf-8"))
        if not text.startswith("---"):
            return False
        metadata_text, _ = _split_frontmatter(text)
        if not metadata_text:
            return False
        metadata = yaml.safe_load(metadata_text)
    except (UnicodeDecodeError, SkillMdParseError, yaml.YAMLError):
        return False
    if not isinstance(metadata, dict) or "name" not in metadata:
        return False
    value = metadata["name"]
    return not _is_valid_name(value)


def _classify_parse_error(exc: BaseException, content: bytes) -> str:
    """Map parser failures to the stable, non-sensitive public taxonomy."""
    if isinstance(exc, SkillMdParseError) and _name_field_is_invalid(content):
        return "invalid_name"
    return "parse_error"


class SkillMdImporter:
    """从内存中的 .md 文件批量导入到 skills_dir。"""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        skills_dir: Optional[Path] = None,
        script_runner: Optional[ScriptRunner] = None,
    ) -> None:
        self._registry = registry
        self._explicit_skills_dir = skills_dir
        self._script_runner = script_runner
        self._batch_loader: Optional[SkillMdHotLoader] = None  # lazy-init for batch reuse

    async def import_files(self, files: List[UploadedFile]) -> Dict[str, List[Dict[str, str]]]:
        """逐文件解析 + 写盘 + hot_reload, 聚合结果。

        Returns:
            {
                "imported": [{"name": str, "path": "."}],
                "skipped": [{"name": str, "reason": str}],
            }
        """
        if not files:
            return {"imported": [], "skipped": []}
        if len(files) > MAX_IMPORT_FILES:
            return {
                "imported": [],
                "skipped": [
                    {
                        "name": "<batch>",
                        "reason": f"batch_too_many_files: {len(files)} > {MAX_IMPORT_FILES}",
                    }
                ],
            }

        skills_dir = self._resolve_skills_dir()
        imported: List[Dict[str, str]] = []
        skipped: List[Dict[str, str]] = []
        total_size = 0

        for f in files:
            safe_filename = _safe_upload_basename(getattr(f, "filename", None))
            try:
                content, content_size = await _read_upload_with_limit(f)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read upload %s: %s", safe_filename, exc)
                skipped.append({"name": safe_filename, "reason": "read_failed"})
                continue

            # size cap: stop reading as soon as one byte beyond the limit is seen.
            if content is None:
                skipped.append(
                    {
                        "name": safe_filename,
                        "reason": f"file_too_large: {content_size} > {MAX_FILE_SIZE_BYTES}",
                    }
                )
                continue

            if total_size + content_size > MAX_IMPORT_TOTAL_SIZE_BYTES:
                skipped.append(
                    {
                        "name": safe_filename,
                        "reason": (
                            f"batch_too_large: {total_size + content_size} > "
                            f"{MAX_IMPORT_TOTAL_SIZE_BYTES}"
                        ),
                    }
                )
                continue
            total_size += content_size

            # parse frontmatter.  Multipart filenames are untrusted client input;
            # retain only a basename for stable diagnostics so a submitted absolute
            # path can never reach the response.
            raw_name = getattr(f, "filename", None)
            safe_filename = _safe_upload_basename(raw_name)
            try:
                meta, body = parse_file_from_bytes(content, fallback_name=safe_filename)
            except Exception as exc:  # noqa: BLE001
                # 解析失败时使用 basename fallback；只返回稳定分类，绝不把 YAML、路径
                # 或上传原文透传给 API 调用方。
                fallback = (
                    _strip_md_extension(safe_filename)
                    if safe_filename != "<unknown>"
                    else safe_filename
                )
                reason = _classify_parse_error(exc, content)
                skipped.append({"name": fallback, "reason": reason})
                continue

            name = meta.get("name", "")
            if not _is_valid_name(name):
                fallback = (
                    _strip_md_extension(safe_filename)
                    if safe_filename != "<unknown>"
                    else safe_filename
                )
                # Invalid frontmatter names are untrusted too; return only the
                # sanitized filename fallback rather than echoing arbitrary YAML.
                skipped.append({"name": fallback, "reason": "invalid_name"})
                continue

            # builtin 冲突: builtin 胜
            if self._registry.exists(name):
                skipped.append({"name": name, "reason": "builtin_conflict"})
                continue

            # 磁盘已有同名 SKILL.md: skip (本期不覆盖)
            target = skills_dir / name / "SKILL.md"
            target_existed = _target_exists_without_following_links(target)

            # 写盘；辅助同时检查 root、技能目录和目标文件的 symlink。
            try:
                write_skill_file(skills_dir, name, content, overwrite=False)
            except FileExistsError:
                skipped.append({"name": name, "reason": "already_exists"})
                continue
            except OSError as exc:
                _cleanup_partial_write(skills_dir, target, target_existed)
                logger.warning("Write failed for %s: %s", target, exc)
                skipped.append({"name": name, "reason": "write_failed"})
                continue

            # hot reload (注册到 registry)
            try:
                self._hot_reload_from_path(target)
                imported.append({"name": name, "path": "."})
                logger.info("SkillMd imported: %s", name)
            except Exception as exc:  # noqa: BLE001
                # Roll back the just-written file so disk and registry stay in sync.
                logger.error("Hot reload failed for %s: %s; rolling back file", name, exc)
                with suppress(OSError):
                    secure_delete_path(skills_dir, target)
                skipped.append({"name": name, "reason": "hot_reload_failed"})

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
            from .loader import SkillMdHotLoader, build_gating_context_for_dirs

            self._batch_loader = SkillMdHotLoader(
                self._registry,
                dirs=[path.parent.parent],
                gating_ctx=build_gating_context_for_dirs([path.parent.parent]),
                script_runner=self._script_runner,
            )
        else:
            from .loader import build_gating_context_for_dirs

            # 前序上传可能新增了声明不同 bin 的 SKILL.md；每次加载前刷新快照，
            # 避免批量导入结果依赖文件顺序。
            self._batch_loader._gating_ctx = build_gating_context_for_dirs(
                [path.parent.parent]
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
    content: bytes, *, fallback_name: Optional[str] = None
) -> Tuple[Dict[str, Any], str]:
    """从字节内容解析并校验 frontmatter，返回 ``(meta, body)``。

    ``frontmatter.parse`` 是唯一 schema 校验入口；此适配器只负责 UTF-8
    解码，并保留导入器要求的 frontmatter 必须存在的契约。
    ``fallback_name`` 为历史兼容参数，解析成功时不参与字段填充。
    """
    del fallback_name  # 保留参数兼容性，但不能绕过统一 schema
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid UTF-8 skill file") from exc

    meta, body = parse(text)
    if not meta:
        raise ValueError("missing frontmatter")
    return meta, body
