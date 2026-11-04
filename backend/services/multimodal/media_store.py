"""MediaStore — 媒体文件生命周期管理"""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

MEDIA_ROOT = Path("data/media")

# P0 修复(2026-11-04): MediaStore.load() 在丢失 sidecar 的情况下回退到后缀推断;
# 回退表必须与 chat_attachment_routes 的 ALLOWED_TEXT_EXTENSIONS | ALLOWED_DOC_EXTENSIONS
# 同口径,否则上传时合法的文本文档在读取时被误判为 AUDIO 并被注入循环静默跳过。
# 历史回归来源: commit 0fb10c4bb (#2001) 只给 load() 加了 .xlsx,其余格式仍走 AUDIO 分支。
FALLBACK_DOCUMENT_SUFFIXES: FrozenSet[str] = frozenset(
    {
        # 基础文本
        ".txt", ".md", ".csv",
        # 编程语言
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
        ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".scala", ".r",
        # 前端
        ".html", ".css", ".scss", ".less", ".vue", ".svelte",
        # 数据/配置
        ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf",
        # 脚本/构建
        ".sh", ".bash", ".bat", ".ps1", ".sql", ".makefile", ".cmake",
        ".gradle",
        # 特殊命名(无扩展名场景由 chat_attachment_routes 兜底)
        ".dockerfile", ".gitignore", ".properties",
        # 日志
        ".log",
        ".pdf", ".docx", ".xlsx",
    }
)

FALLBACK_IMAGE_SUFFIXES: FrozenSet[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
)


class MediaKind(Enum):
    IMAGE = "image"
    AUDIO = "audio"
    # R37: 聊天文本文档附件（txt/md 直传，内容注入聊天上下文）
    DOCUMENT = "document"


@dataclass(frozen=True)
class MediaRef:
    """媒体文件的引用"""
    id: str
    kind: MediaKind
    mime_type: str
    file_path: str       # 相对路径 e.g. "2026/09/12/abc123.mp3"
    file_size: int
    created_at: str      # ISO 8601
    source: str          # "tts" | "asr" | "image_gen" | "chat_upload"
    metadata: dict = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"/api/v1/media/{self.id}"


def _kind_from_suffix(suffix: str) -> MediaKind:
    """无 sidecar 时的回退推断 —— 后缀表必须与上传端 allowlist 同口径。"""
    s = suffix.lower()
    if s in FALLBACK_IMAGE_SUFFIXES:
        return MediaKind.IMAGE
    if s in FALLBACK_DOCUMENT_SUFFIXES:
        return MediaKind.DOCUMENT
    return MediaKind.AUDIO


class MediaStore:
    """媒体文件生命周期管理"""

    def __init__(self, root: Path = MEDIA_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ── sidecar 元数据读写 ──────────────────────────────────────────────
    #
    # save() 在写媒体字节的同时写一份 <id>.meta.json，持久化 kind / mime /
    # original_filename / source / metadata / created_at。load() 优先读 sidecar，
    # 缺失时回退到后缀推断（表与上传 allowlist 同口径），保证历史数据零迁移。
    #
    # Sidecar 字段 —— id: str / kind: document|image|audio / mime_type: str /
    # original_filename: str / source: chat_upload / metadata: dict /
    # created_at: ISO-8601（如 2026-11-04T12:34:56.789012+00:00）。

    def _read_sidecar(self, media_file: Path) -> Optional[dict]:
        """读 sidecar;失败/不存在返回 None。"""
        meta_path = media_file.with_name(media_file.stem + ".meta.json")
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("MediaStore sidecar read failed for %s: %s", media_file, exc)
            return None

    def _write_sidecar(
        self,
        media_id: str,
        date_dir: str,
        *,
        kind: MediaKind,
        mime_type: str,
        original_filename: str,
        source: str,
        metadata: dict,
        created_at: str,
    ) -> None:
        """写 sidecar;失败仅 log,不阻断主流程。"""
        payload = {
            "id": media_id,
            "kind": kind.value,
            "mime_type": mime_type,
            "original_filename": original_filename,
            "source": source,
            "metadata": metadata,
            "created_at": created_at,
        }
        try:
            path = self.root / date_dir / f"{media_id}.meta.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — 元数据落盘失败不影响主流程
            logger.warning("MediaStore sidecar write failed for %s: %s", media_id, exc)

    # ── 主接口 ──────────────────────────────────────────────────────────

    def save(
        self,
        content: bytes,
        kind: MediaKind,
        source: str,
        metadata: Optional[dict] = None,
        ext: Optional[str] = None,
    ) -> MediaRef:
        """存储媒体文件,返回 MediaRef;同时写 sidecar 元数据。"""
        media_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)  # noqa: UP017 — py3.10 compat (UTC is 3.11+)
        date_dir = f"{now:%Y}/{now:%m}/{now:%d}"
        (self.root / date_dir).mkdir(parents=True, exist_ok=True)

        if not ext:
            mime = self._guess_mime(content, kind)
            ext = mimetypes.guess_extension(mime) or self._default_ext(kind)
        else:
            mime = mimetypes.guess_type(f"x.{ext}")[0] or self._default_mime(kind)

        ext = ext.lstrip(".")
        filename = f"{media_id}.{ext}"
        rel_path = f"{date_dir}/{filename}"
        abs_path = self.root / rel_path
        abs_path.write_bytes(content)

        original_filename = (metadata or {}).get("original_filename") or filename
        created_at_iso = now.isoformat()
        meta = dict(metadata or {})
        # 规范化 metadata.original_filename —— 下游(如 RAG 引用溯源)直接取。
        meta.setdefault("original_filename", original_filename)

        self._write_sidecar(
            media_id,
            date_dir,
            kind=kind,
            mime_type=mime,
            original_filename=original_filename,
            source=source,
            metadata=meta,
            created_at=created_at_iso,
        )

        return MediaRef(
            id=media_id,
            kind=kind,
            mime_type=mime,
            file_path=rel_path,
            file_size=len(content),
            created_at=created_at_iso,
            source=source,
            metadata=meta,
        )

    def load(self, media_id: str) -> Optional[Tuple[MediaRef, bytes]]:
        """根据 ID 加载媒体文件。

        优先读 sidecar(<id>.meta.json)恢复完整 MediaRef;
        sidecar 缺失(历史数据)时回退到后缀推断,后缀表与上传端 allowlist 同口径。
        """
        for f in self.root.rglob(f"{media_id}.*"):
            # 跳过 sidecar 自身,不要把 <id>.meta.json 当作媒体文件
            if f.name.endswith(".meta.json"):
                continue
            try:
                content = f.read_bytes()
            except OSError as exc:
                logger.warning("MediaStore load read failed for %s: %s", f, exc)
                return None
            rel = str(f.relative_to(self.root))
            sidecar = self._read_sidecar(f)
            if sidecar:
                try:
                    kind = MediaKind(sidecar.get("kind", ""))
                except ValueError:
                    kind = _kind_from_suffix(f.suffix)
                return MediaRef(
                    id=media_id,
                    kind=kind,
                    mime_type=sidecar.get("mime_type")
                    or (mimetypes.guess_type(str(f))[0] or "application/octet-stream"),
                    file_path=sidecar.get("file_path") or rel,
                    file_size=sidecar.get("file_size") or len(content),
                    created_at=sidecar.get("created_at")
                    or datetime.fromtimestamp(
                        f.stat().st_mtime, tz=timezone.utc  # noqa: UP017
                    ).isoformat(),
                    source=sidecar.get("source") or "unknown",
                    metadata=sidecar.get("metadata") or {},
                ), content
            # 回退:无 sidecar 的历史数据 → 用完整后缀表推断
            return MediaRef(
                id=media_id,
                kind=_kind_from_suffix(f.suffix),
                mime_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream",
                file_path=rel,
                file_size=len(content),
                created_at=datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc  # noqa: UP017
                ).isoformat(),
                source="unknown",
            ), content
        return None

    def delete(self, media_id: str) -> bool:
        """删除媒体文件及其 sidecar。"""
        deleted_any = False
        # 同时清理 <id>.<ext> 与 <id>.meta.json —— rglob 返回的迭代顺序不确定,
        # 旧实现 `return True` 会在第一遍后退出,可能漏删另一个。
        for f in list(self.root.rglob(f"{media_id}.*")):
            try:
                f.unlink()
                deleted_any = True
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("MediaStore delete unlink failed for %s: %s", f, exc)
        return deleted_any

    @staticmethod
    def _guess_mime(content: bytes, kind: MediaKind) -> str:
        """通过 magic bytes 推断 MIME 类型"""
        if len(content) >= 8 and content[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if len(content) >= 2 and content[:2] == b"\xff\xd8":
            return "image/jpeg"
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            return "audio/wav"
        if len(content) >= 3 and (content[:3] == b"ID3" or content[:2] == b"\xff\xfb"):
            return "audio/mpeg"
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"

    @staticmethod
    def _default_ext(kind: MediaKind) -> str:
        if kind == MediaKind.IMAGE:
            return "png"
        if kind == MediaKind.DOCUMENT:
            return "txt"
        return "mp3"

    @staticmethod
    def _default_mime(kind: MediaKind) -> str:
        if kind == MediaKind.IMAGE:
            return "image/png"
        if kind == MediaKind.DOCUMENT:
            return "text/plain"
        return "audio/mpeg"
