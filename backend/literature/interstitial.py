"""中间页解析与主机回退候选生成（spec §5.3）。

纯函数模块，无 IO —— 便于离线单测。生产路径由 ``http_download`` 注入
真实的取数函数。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

#: 提取顺序：var downurl > window.location > successBtn href。
_DOWNURL_PATTERN = re.compile(r"var\s+downurl\s*=\s*['\"]([^'\"]+)['\"]")
_LOCATION_PATTERN = re.compile(r"window\.location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]")
_ANCHOR_PATTERN = re.compile(
    r"<a\b[^>]*\bid\s*=\s*['\"]successBtn['\"][^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_ANCHOR_HREF_FIRST_PATTERN = re.compile(
    r"<a\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*\bid\s*=\s*['\"]successBtn['\"]",
    re.IGNORECASE,
)


def parse_download_url(html: str) -> List[str]:
    """从中间页 HTML 提取候选下载地址，按出现顺序去重。

    三种形态按上表顺序匹配；命中多个时全部保留（按形态优先级）。
    """
    text = html or ""
    found: List[str] = []
    for pattern in (_DOWNURL_PATTERN, _LOCATION_PATTERN):
        for match in pattern.finditer(text):
            found.append(match.group(1).strip())
    for pattern in (_ANCHOR_PATTERN, _ANCHOR_HREF_FIRST_PATTERN):
        for match in pattern.finditer(text):
            found.append(match.group(1).strip())

    seen = set()
    ordered: List[str] = []
    for url in found:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def rewrite_host_candidates(url: str, fallbacks: Sequence[str]) -> List[str]:
    """按 ``fallbacks`` 依次替换主机生成候选 URL；原域最后兜底。

    路径与查询串保持不变。仅返回 ``http(s)`` URL。
    """
    text = str(url or "").strip()
    if not text:
        return []
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return [text]

    candidates: List[str] = []
    seen = set()
    for raw_host in list(fallbacks or ()):
        host = str(raw_host or "").strip()
        if not host:
            continue
        candidate = urlunsplit(
            (parts.scheme, host, parts.path, parts.query, parts.fragment)
        )
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    if text not in seen:
        candidates.append(text)
    return candidates


def select_first_valid(
    candidates: Sequence[str],
    fetch: Callable[[str], Optional[Tuple[str, bytes]]],
    validate: Optional[Callable[[bytes], bool]] = None,
) -> Optional[Tuple[str, bytes]]:
    """按候选顺序取第一个通过校验的响应。

    Args:
        candidates: 候选 URL 序列（``rewrite_host_candidates`` 的输出）。
        fetch: 注入的取数函数；返回 ``None`` 或 ``(url, body)``。
        validate: 可选的响应体校验（如 magic 前缀检查）；不通过则试下一个。

    Returns:
        命中的 ``(url, body)``；全部失败返回 ``None``。
    """
    for candidate in candidates:
        try:
            fetched = fetch(candidate)
        except Exception:  # noqa: BLE001 — 单个候选失败不中断候选序列
            continue
        if not fetched:
            continue
        url, body = fetched
        if validate is not None and not validate(body):
            continue
        return url, body
    return None
