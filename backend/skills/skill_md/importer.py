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
import stat
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import yaml

from ...utils.py_compat import to_thread
from ...wiki.files import secure_delete_path
from ..registry import SkillRegistry
from ..safe_writer import write_skill_file
from .exceptions import NoSkillsDirError, SkillDirectoryImportError
from .frontmatter import (
    SkillMdParseError,
    _is_valid_name,
    _split_frontmatter,
    _strip_bom,
    parse,
)
from .resources import ALLOWED_RESOURCE_DIRS
from .skills_dir_policy import read_skills_dir_preference

if TYPE_CHECKING:
    from .loader import SkillMdHotLoader
    from .script_runner import ScriptRunner

logger = logging.getLogger(__name__)

# Canonical name validation lives in frontmatter.py and is reused by import paths.

MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB per file
MAX_IMPORT_FILES = 100
MAX_IMPORT_TOTAL_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per batch
_UPLOAD_READ_CHUNK_BYTES = 64 * 1024

#: 目录导入：相对路径最大段数（防超深目录树打爆递归与路径长度）
MAX_DIRECTORY_DEPTH = 8

#: 目录导入：入口文件名（大小写不敏感匹配）
_ENTRY_FILENAME = "skill.md"

#: Windows reparse point 文件属性位（与 resources.py 口径一致）
_WINDOWS_REPARSE_POINT = 0x0400

#: Windows 保留设备名（大小写不敏感）。带扩展名同样保留：``NUL.txt`` 也会落到设备。
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

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


def _is_windows_reserved_device_name(segment: str) -> bool:
    """判断路径段是否是 Windows 保留设备名。

    ``CON`` / ``NUL`` / ``COM1`` 等名字在 Windows 上即使带扩展名也无法创建普通文件
    （``NUL.txt`` 实际落到 NUL 设备）。Win7 安装包是受支持平台 → 导入阶段直接拒绝，
    不让它们在写盘时才以 ``write_failed`` 的面目出现。
    """
    stem = segment.split(".")[0].strip().rstrip(" ")
    return stem.lower() in _WINDOWS_RESERVED_DEVICE_NAMES


def _safe_relative_path(raw: Any) -> Optional[Path]:
    """把 multipart 的 filename 解析成安全的相对路径。

    目录导入用 filename 携带相对路径（如 ``SKILL.md`` / ``scripts/scan.py``），
    这里做规范化与路径穿越防御：拒绝绝对路径、盘符前缀、反斜杠、
    ``.``/``..`` 段、空段、控制字符、Windows 保留设备名与超深路径。

    Returns:
        合法时返回相对 ``Path``（各段均非空且不含分隔符），否则 ``None``。
    """
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split("/")
    has_drive_prefix = len(parts[0]) == 2 and parts[0][1] == ":" and parts[0][0].isalpha()
    if (
        "\\" in raw
        or raw.startswith("/")
        or has_drive_prefix
        or any(part in ("", ".", "..") for part in parts)
        or len(parts) > MAX_DIRECTORY_DEPTH
        or any(_is_unsafe_upload_label_char(char) for char in raw)
        or any(_is_windows_reserved_device_name(part) for part in parts)
    ):
        return None
    return Path(*parts)


def _ensure_real_directory(path: Path) -> None:
    """确保路径是一个真实目录（不存在则创建；symlink/reparse point 一律拒绝）。"""
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        return
    if stat.S_ISLNK(st.st_mode):
        raise OSError(f"Refusing skill resource write through symlink: {path}")
    attributes = getattr(st, "st_file_attributes", 0)
    if attributes & _WINDOWS_REPARSE_POINT:
        raise OSError(f"Refusing skill resource write through reparse point: {path}")
    if not stat.S_ISDIR(st.st_mode):
        raise NotADirectoryError(str(path))


def _write_resource_file(skill_dir: Path, rel_path: Path, content: bytes) -> None:
    """在技能目录下安全写入一个附属资源文件。

    逐段校验中间目录不是 symlink/reparse point；最终文件以
    ``O_EXCL|O_NOFOLLOW`` 创建（已存在 → ``FileExistsError``），不覆盖既有内容。

    额外做一次 resolve-and-contain 复核：``_ensure_real_directory`` 是
    lstat 逐段检查，与后续 open 之间存在 TOCTOU 窗口；解析后的父目录必须
    仍在 ``skill_dir`` 之内，否则拒绝写入。
    """
    _ensure_real_directory(skill_dir)
    current = skill_dir
    for part in rel_path.parent.parts:
        current = current / part
        _ensure_real_directory(current)

    target = current / rel_path.name
    base = skill_dir.resolve()
    resolved_parent = target.parent.resolve()
    if resolved_parent != base and base not in resolved_parent.parents:
        raise OSError(f"Refusing skill resource write outside skills dir: {rel_path}")

    if os.name == "nt":
        from backend.tools.win_reparse_io import write_file_reparse_safe

        write_file_reparse_safe(str(target), content, overwrite=False)
        return

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(target), flags, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(f"Short write for skill resource: {rel_path}")
            view = view[written:]
    finally:
        os.close(fd)


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

    async def import_directory(
        self, files: List[UploadedFile]
    ) -> Dict[str, List[Dict[str, str]]]:
        """按相对路径导入整个技能目录（SKILL.md + scripts/ + references/ + assets/ + templates/）。

        与 ``import_files`` 的区别：multipart 的 filename 携带相对路径，
        根目录的 ``SKILL.md`` 决定技能名，附属资源按相对路径落盘到技能目录下。

        与 ``import_files`` 一致的部分：单文件 1MB / 总 10MB / 最多 100 个文件；
        builtin 冲突与写失败都记入 ``skipped``（HTTP 仍 200，部分成功）。

        Raises:
            SkillDirectoryImportError: 目录里没有 ``SKILL.md``，或入口文件不合法。
        """
        if not files:
            raise SkillDirectoryImportError("no_files", "no files provided")
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

        skipped: List[Dict[str, str]] = []
        entries: List[Tuple[Path, bytes]] = []
        total_size = 0

        for f in files:
            raw_name = getattr(f, "filename", None)
            rel = _safe_relative_path(raw_name)
            if rel is None:
                skipped.append(
                    {"name": _safe_upload_basename(raw_name), "reason": "invalid_path"}
                )
                continue
            try:
                content, content_size = await _read_upload_with_limit(f)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read upload %s: %s", rel.as_posix(), exc)
                skipped.append({"name": rel.as_posix(), "reason": "read_failed"})
                continue
            if content is None:
                skipped.append(
                    {
                        "name": rel.as_posix(),
                        "reason": f"file_too_large: {content_size} > {MAX_FILE_SIZE_BYTES}",
                    }
                )
                continue
            if total_size + content_size > MAX_IMPORT_TOTAL_SIZE_BYTES:
                skipped.append(
                    {
                        "name": rel.as_posix(),
                        "reason": (
                            f"batch_too_large: {total_size + content_size} > "
                            f"{MAX_IMPORT_TOTAL_SIZE_BYTES}"
                        ),
                    }
                )
                continue
            total_size += content_size
            entries.append((rel, content))

        entry_rel, entry_content = self._extract_directory_entry(entries)
        if entry_rel is None:
            raise SkillDirectoryImportError(
                "missing_skill_md", "技能目录中缺少 SKILL.md"
            )

        try:
            meta, _body = parse_file_from_bytes(entry_content, fallback_name="SKILL.md")
        except Exception as exc:  # noqa: BLE001
            # 与单文件导入共用同一分类口径：显式非法的 name → invalid_name，
            # 其余解析失败 → parse_error。
            raise SkillDirectoryImportError(
                _classify_parse_error(exc, entry_content),
                f"SKILL.md 解析失败: {type(exc).__name__}",
            ) from exc

        name = meta.get("name", "")
        if not _is_valid_name(name):
            raise SkillDirectoryImportError("invalid_name", "SKILL.md 的 name 字段非法")

        if self._registry.exists(name):
            return {
                "imported": [],
                "skipped": skipped + [{"name": name, "reason": "builtin_conflict"}],
            }

        skills_dir = self._resolve_skills_dir()
        skill_dir = skills_dir / name

        # 写盘是纯同步 I/O（最多 100 个文件 / 10 MB），放线程里跑，
        # 避免阻塞事件循环（与 legacy_routes 的 to_thread 约定一致）。
        status, resource_skipped = await to_thread(
            self._write_directory_files,
            skills_dir,
            name,
            entry_content,
            entries,
            entry_rel,
        )
        if status == "already_exists":
            return {
                "imported": [],
                "skipped": skipped + [{"name": name, "reason": "already_exists"}],
            }
        if status == "write_failed":
            return {
                "imported": [],
                "skipped": skipped + [{"name": name, "reason": "write_failed"}],
            }
        skipped.extend(resource_skipped)

        try:
            self._hot_reload_from_path(skill_dir / "SKILL.md")
        except Exception as exc:  # noqa: BLE001
            # 磁盘与注册表必须保持一致：回滚整个技能目录（含附属资源）。
            logger.error("Hot reload failed for %s: %s; rolling back", name, exc)
            with suppress(OSError):
                secure_delete_path(skills_dir, skill_dir)
            return {
                "imported": [],
                "skipped": skipped + [{"name": name, "reason": "hot_reload_failed"}],
            }

        return {"imported": [{"name": name, "path": "."}], "skipped": skipped}

    def _write_directory_files(
        self,
        skills_dir: Path,
        name: str,
        entry_content: bytes,
        entries: List[Tuple[Path, bytes]],
        entry_rel: Path,
    ) -> Tuple[str, List[Dict[str, str]]]:
        """把入口文件与附属资源写到磁盘（纯同步 I/O，由调用方放到线程里执行）。

        Returns:
            ``(status, skipped)``。status 取值：

            - ``"ok"``：入口文件与资源都已处理，skipped 是附属资源的跳过原因
            - ``"already_exists"`` / ``"write_failed"``：入口文件没落盘，
              此时**不写任何附属资源**，skipped 为空
        """
        skill_dir = skills_dir / name
        try:
            write_skill_file(skills_dir, name, entry_content, overwrite=False)
        except FileExistsError:
            return "already_exists", []
        except OSError as exc:
            logger.warning("Write failed for %s: %s", skill_dir, exc)
            return "write_failed", []

        skipped: List[Dict[str, str]] = []
        for rel, content in entries:
            if rel == entry_rel:
                continue
            top = rel.parts[0]
            if top not in ALLOWED_RESOURCE_DIRS:
                skipped.append(
                    {"name": rel.as_posix(), "reason": "resource_dir_not_allowed"}
                )
                continue
            if len(rel.parts) < 2:
                # 单段文件名（形如 ``scripts``）与同名资源目录冲突 —— 明确拒绝，
                # 不让它以 write_failed 的面目混进 skipped。
                skipped.append(
                    {"name": rel.as_posix(), "reason": "resource_path_too_shallow"}
                )
                continue
            if any(part.startswith(".") for part in rel.parts):
                skipped.append({"name": rel.as_posix(), "reason": "hidden_path_rejected"})
                continue
            try:
                _write_resource_file(skill_dir, rel, content)
            except FileExistsError:
                skipped.append({"name": rel.as_posix(), "reason": "already_exists"})
            except OSError as exc:
                logger.warning("Resource write failed for %s: %s", rel.as_posix(), exc)
                skipped.append({"name": rel.as_posix(), "reason": "write_failed"})
        return "ok", skipped

    @staticmethod
    def _extract_directory_entry(
        entries: List[Tuple[Path, bytes]]
    ) -> Tuple[Optional[Path], bytes]:
        """挑出根目录的入口 ``SKILL.md``（大小写不敏感）。

        Returns:
            ``(rel_path, content)``；找不到入口时 ``rel_path`` 为 ``None``、
            ``content`` 为空字节。
        """
        for rel, content in entries:
            if rel.as_posix().lower() == _ENTRY_FILENAME:
                return rel, content
        return None, b""

    def _resolve_skills_dir(self) -> Path:
        """解析 skills_dir: 显式参数 > SAGE_SKILLS_DIR > preference > ~/.sage/skills (auto-mkdir)。

        env var 优先于 DB preference —— 与代码库其它设置一致
        (``SAGE_COMPACT_THRESHOLD`` 等): 运维/开发覆盖 > 用户配置,
        避免 DB 损坏或误配阻止开发环境启动。

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

        preferred = read_skills_dir_preference()
        if preferred is not None:
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                return preferred
            except OSError as exc:
                logger.warning(
                    "skills_dir preference 目录不可创建 %s，回退下一级: %s", preferred, exc
                )

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
