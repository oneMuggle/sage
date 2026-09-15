# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""内容嗅探 —— 按魔数 / Content-Type / 文件名判定响应体类型（Round 5 B1：DL3 / SN1）。

两个消费方：

- ``http_download``：落盘前读首块，若 URL / Content-Disposition 暗示的是
  PDF/ZIP/Office 等文件而首块实际是 HTML（登录页 / 验证码 / 反爬盾 / 404 壳），
  立即中止并返回 ``html_instead_of_file``——堵住"下载了一个 12 KB 的 paper.pdf
  其实是登录页"的高频故障；
- ``web_fetch``：非 HTML 且属二进制族的响应不再以乱码正文返回，改给结构化
  的 ``kind=binary`` 提示（含 content_length / suggested_filename），引导模型
  改用 ``http_download``。

纯函数、无 IO；py3.8 纪律：stdlib only。
"""

from __future__ import annotations

import re
from typing import Dict, NamedTuple, Optional, Tuple

#: 嗅探所需的首块字节数（覆盖所有魔数 + HTML 前导空白/BOM/注释）
SNIFF_BYTES = 512

#: 魔数 → 类型（前缀匹配，按顺序）
_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"%PDF-", "pdf"),
    (b"PK\x03\x04", "zip"),  # zip / docx / xlsx / pptx / epub / jar
    (b"PK\x05\x06", "zip"),  # 空 zip
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),  # doc / xls / ppt（OLE2）
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "riff"),  # webp / wav / avi
    (b"MZ", "exe"),
    (b"\x7fELF", "elf"),
    (b"SQLite format 3\x00", "sqlite"),
    (b"\x00\x00\x00\x14ftyp", "mp4"),
    (b"\x00\x00\x00\x18ftyp", "mp4"),
    (b"\x00\x00\x00\x1cftyp", "mp4"),
    (b"\x00\x00\x00 ftyp", "mp4"),
    (b"OggS", "ogg"),
    (b"fLaC", "flac"),
    (b"ID3", "mp3"),
)

#: 扩展名 → 期望类型（与 ``_MAGIC`` 的类型标签对齐）
_EXT_KIND: Dict[str, str] = {
    ".pdf": "pdf",
    ".zip": "zip",
    ".docx": "zip",
    ".xlsx": "zip",
    ".pptx": "zip",
    ".epub": "zip",
    ".jar": "zip",
    ".whl": "zip",
    ".apk": "zip",
    ".doc": "ole",
    ".xls": "ole",
    ".ppt": "ole",
    ".gz": "gzip",
    ".tgz": "gzip",
    ".bz2": "bzip2",
    ".xz": "xz",
    ".7z": "7z",
    ".rar": "rar",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".exe": "exe",
    ".msi": "ole",
    ".mp4": "mp4",
    ".mp3": "mp3",
    ".ogg": "ogg",
    ".flac": "flac",
    ".sqlite": "sqlite",
    ".db": "sqlite",
}

#: Content-Type → 期望类型（子串匹配，小写）
_CT_KIND: Tuple[Tuple[str, str], ...] = (
    ("application/pdf", "pdf"),
    ("application/x-pdf", "pdf"),
    ("application/zip", "zip"),
    ("application/x-zip", "zip"),
    ("application/epub+zip", "zip"),
    ("application/java-archive", "zip"),
    ("application/vnd.openxmlformats-officedocument", "zip"),
    ("application/msword", "ole"),
    ("application/vnd.ms-excel", "ole"),
    ("application/vnd.ms-powerpoint", "ole"),
    ("application/gzip", "gzip"),
    ("application/x-gzip", "gzip"),
    ("application/x-bzip2", "bzip2"),
    ("application/x-xz", "xz"),
    ("application/x-7z-compressed", "7z"),
    ("application/vnd.rar", "rar"),
    ("application/x-rar-compressed", "rar"),
    ("image/png", "png"),
    ("image/jpeg", "jpeg"),
    ("image/gif", "gif"),
    ("audio/mpeg", "mp3"),
    ("video/mp4", "mp4"),
)

#: web_fetch 视为"二进制族"的 Content-Type 前缀 / 子串——命中即不当文本返回
_BINARY_CT_MARKERS: Tuple[str, ...] = (
    "application/pdf",
    "application/x-pdf",
    "application/zip",
    "application/x-zip",
    "application/gzip",
    "application/x-gzip",
    "application/x-bzip2",
    "application/x-xz",
    "application/x-7z-compressed",
    "application/vnd.rar",
    "application/x-rar-compressed",
    "application/octet-stream",
    "application/msword",
    "application/vnd.ms-",
    "application/vnd.openxmlformats-officedocument",
    "application/epub+zip",
    "application/java-archive",
    "application/x-msdownload",
    "application/x-executable",
    "application/x-sqlite3",
    "application/wasm",
    "image/",
    "audio/",
    "video/",
    "font/",
)

#: Content-Type 明确是文本族——即使带 NUL 也不按二进制处理（如 UTF-16 页面）
_TEXTUAL_CT_MARKERS: Tuple[str, ...] = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/javascript",
    "application/x-javascript",
    "application/ld+json",
    "application/rss+xml",
    "application/atom+xml",
    "image/svg+xml",
)

_HTML_LEAD_RE = re.compile(
    rb"^\s*(?:\xef\xbb\xbf)?\s*(?:<!--.*?-->\s*)*<(?:!doctype\s+html|html|head|body|meta|title|script|link|div|p|h1|iframe|noscript)\b",
    re.IGNORECASE | re.DOTALL,
)

_TAG_RE = re.compile(rb"<[^>]{0,200}>")
_WS_RE = re.compile(r"\s+")


class SniffResult(NamedTuple):
    """嗅探结果。

    Attributes:
        detected: 首块判定的类型（``pdf``/``zip``/``html``/``text``/``binary``/
                  ``empty``/…）；
        expected: 由文件名 / Content-Type 推断的期望类型（``None`` = 无期望）；
        mismatch: 期望是文件类型而实际是 HTML —— 即"伪装文件"；
    """

    detected: str
    expected: Optional[str]
    mismatch: bool


def looks_like_html(head: bytes) -> bool:
    """首块是否是 HTML 文档（容忍 BOM / 前导空白 / 注释）。"""
    if not head:
        return False
    if _HTML_LEAD_RE.match(head[:SNIFF_BYTES]):
        return True
    lower = head[:SNIFF_BYTES].lower()
    return b"<html" in lower or b"<!doctype html" in lower


def detect_kind(head: bytes) -> str:
    """按魔数判定首块类型；无魔数时区分 html / text / binary。"""
    if not head:
        return "empty"
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if looks_like_html(head):
        return "html"
    sample = head[:SNIFF_BYTES]
    if b"\x00" in sample:
        return "binary"
    # 控制字符占比过高也视为二进制（排除 \t \n \r \f \x1b）
    control = sum(1 for b in sample if b < 0x20 and b not in (0x09, 0x0A, 0x0D, 0x0C, 0x1B))
    if len(sample) >= 32 and control / len(sample) > 0.1:
        return "binary"
    return "text"


def expected_kind_from_name(name: Optional[str]) -> Optional[str]:
    """从文件名扩展名推断期望类型；未知扩展名返回 ``None``。"""
    if not name:
        return None
    lowered = name.lower()
    # 复合扩展名优先（.tar.gz → gzip）
    for ext, kind in _EXT_KIND.items():
        if lowered.endswith(ext):
            return kind
    return None


def expected_kind_from_content_type(content_type: Optional[str]) -> Optional[str]:
    """从 Content-Type 推断期望类型；文本 / 未知 / octet-stream 返回 ``None``。"""
    if not content_type:
        return None
    lowered = content_type.lower()
    for marker, kind in _CT_KIND:
        if marker in lowered:
            return kind
    return None


def is_binary_content_type(content_type: Optional[str]) -> bool:
    """Content-Type 是否属二进制族（web_fetch 不应当文本返回）。"""
    if not content_type:
        return False
    lowered = content_type.lower()
    if any(marker in lowered for marker in _TEXTUAL_CT_MARKERS):
        return False
    return any(marker in lowered for marker in _BINARY_CT_MARKERS)


def is_textual_content_type(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(marker in lowered for marker in _TEXTUAL_CT_MARKERS)


def sniff(
    head: bytes,
    content_type: Optional[str] = None,
    filename_hint: Optional[str] = None,
) -> SniffResult:
    """综合判定：``detected`` 来自魔数；``expected`` 先看文件名再看 Content-Type。

    ``mismatch`` 仅在"期望是具体文件类型而首块是 HTML"时为 True——这是登录页 /
    反爬盾 / 404 壳伪装成附件的典型特征。期望类型与实际魔数不同但都是二进制
    （如 .zip 实为 gzip）不算 mismatch，交给用户自行判断。
    """
    detected = detect_kind(head)
    expected = expected_kind_from_name(filename_hint) or expected_kind_from_content_type(
        content_type
    )
    mismatch = bool(expected) and detected == "html"
    return SniffResult(detected=detected, expected=expected, mismatch=mismatch)


def is_binary_payload(head: bytes, content_type: Optional[str] = None) -> bool:
    """web_fetch 用：响应是否应按二进制处理（不走文本抽取）。

    Content-Type 明示文本 → False；明示二进制 → True；其余按魔数 / NUL 判定。
    """
    if is_textual_content_type(content_type):
        return False
    if is_binary_content_type(content_type):
        return True
    return detect_kind(head) not in ("text", "html", "empty")


def html_excerpt(head: bytes, limit: int = 300) -> str:
    """把 HTML 首块压成一行可读摘要（去标签 / 折叠空白），用于错误文案。"""
    if not head:
        return ""
    stripped = _TAG_RE.sub(b" ", head[: SNIFF_BYTES * 4])
    try:
        text = stripped.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001 — 摘要失败不影响主流程
        text = ""
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


__all__ = [
    "SNIFF_BYTES",
    "SniffResult",
    "detect_kind",
    "expected_kind_from_content_type",
    "expected_kind_from_name",
    "html_excerpt",
    "is_binary_content_type",
    "is_binary_payload",
    "is_textual_content_type",
    "looks_like_html",
    "sniff",
]
