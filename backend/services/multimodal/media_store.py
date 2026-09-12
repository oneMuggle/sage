"""MediaStore — 媒体文件生命周期管理"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MEDIA_ROOT = Path("data/media")


class MediaKind(Enum):
    IMAGE = "image"
    AUDIO = "audio"


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


class MediaStore:
    """媒体文件生命周期管理"""

    def __init__(self, root: Path = MEDIA_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        content: bytes,
        kind: MediaKind,
        source: str,
        metadata: Optional[dict] = None,
        ext: Optional[str] = None,
    ) -> MediaRef:
        """存储媒体文件，返回 MediaRef"""
        media_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        date_dir = f"{now:%Y}/{now:%m}/{now:%d}"
        (self.root / date_dir).mkdir(parents=True, exist_ok=True)

        if not ext:
            mime = self._guess_mime(content, kind)
            ext = mimetypes.guess_extension(mime) or self._default_ext(kind)
        else:
            mime = mimetypes.guess_type(f"x.{ext}")[0] or self._default_mime(kind)

        filename = f"{media_id}.{ext.lstrip('.')}"
        rel_path = f"{date_dir}/{filename}"
        abs_path = self.root / rel_path
        abs_path.write_bytes(content)

        return MediaRef(
            id=media_id,
            kind=kind,
            mime_type=mime,
            file_path=rel_path,
            file_size=len(content),
            created_at=now.isoformat(),
            source=source,
            metadata=metadata or {},
        )

    def load(self, media_id: str) -> Optional[Tuple[MediaRef, bytes]]:
        """根据 ID 加载媒体文件"""
        for f in self.root.rglob(f"{media_id}.*"):
            content = f.read_bytes()
            rel = str(f.relative_to(self.root))
            kind = (
                MediaKind.IMAGE
                if f.suffix in (".png", ".jpg", ".jpeg", ".webp")
                else MediaKind.AUDIO
            )
            return MediaRef(
                id=media_id,
                kind=kind,
                mime_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream",
                file_path=rel,
                file_size=len(content),
                created_at=datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                source="unknown",
            ), content
        return None

    def delete(self, media_id: str) -> bool:
        """删除媒体文件"""
        for f in self.root.rglob(f"{media_id}.*"):
            f.unlink()
            return True
        return False

    @staticmethod
    def _guess_mime(content: bytes, kind: MediaKind) -> str:
        """通过 magic bytes 推断 MIME 类型"""
        if len(content) >= 8 and content[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if len(content) >= 2 and content[:2] == b'\xff\xd8':
            return "image/jpeg"
        if len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WAVE':
            return "audio/wav"
        if len(content) >= 3 and (content[:3] == b'ID3' or content[:2] == b'\xff\xfb'):
            return "audio/mpeg"
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"

    @staticmethod
    def _default_ext(kind: MediaKind) -> str:
        return "png" if kind == MediaKind.IMAGE else "mp3"

    @staticmethod
    def _default_mime(kind: MediaKind) -> str:
        return "image/png" if kind == MediaKind.IMAGE else "audio/mpeg"
