# ruff: noqa: UP006, UP007, UP035, UP038, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""网页内候选文件链接嗅探（Round 5 §2.2 SN2，``web_fetch mode=files``）。

从 HTML（静态或渲染后）里抽取"可能是文件"的链接并打分，输出可直接喂
``http_download`` 的候选表。纯 stdlib ``HTMLParser``，不出网 —— 轻量探测
（首块 content-type / 魔数）由调用方按需做。

候选来源与基础分：

- ``<meta name="citation_pdf_url">`` / ``<link rel="alternate" type="application/pdf">``
  （学术站标准位）—— 最高；
- ``<a href>`` 后缀属文件族（pdf/zip/docx/…）、带 ``download`` 属性、
  ``type="application/pdf"``；
- ``<iframe|embed|object src/data>`` 指向文件；``<meta http-equiv=refresh>`` 跳转到文件；
- 锚文本 / title / aria-label 含 ``download|PDF|全文|下载|附件|Full text`` 等提示词
  （无文件后缀时也收，但分低）。

同一 URL 多处出现只保留最高分一条，附 ``sources`` 汇总。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

#: 文件族后缀 → 类型标签
FILE_EXTENSIONS: Dict[str, str] = {
    ".pdf": "pdf",
    ".zip": "archive",
    ".rar": "archive",
    ".7z": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".tgz": "archive",
    ".bz2": "archive",
    ".xz": "archive",
    ".doc": "office",
    ".docx": "office",
    ".xls": "office",
    ".xlsx": "office",
    ".ppt": "office",
    ".pptx": "office",
    ".odt": "office",
    ".ods": "office",
    ".odp": "office",
    ".rtf": "office",
    ".epub": "ebook",
    ".mobi": "ebook",
    ".csv": "data",
    ".tsv": "data",
    ".json": "data",
    ".xml": "data",
    ".bib": "data",
    ".ris": "data",
    ".txt": "text",
    ".md": "text",
    ".apk": "binary",
    ".exe": "binary",
    ".msi": "binary",
    ".dmg": "binary",
    ".deb": "binary",
    ".rpm": "binary",
    ".iso": "binary",
    ".jar": "binary",
    ".whl": "binary",
    ".mp4": "media",
    ".mp3": "media",
    ".wav": "media",
    ".flac": "media",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".webp": "image",
    ".tif": "image",
    ".tiff": "image",
}

#: 文件族 MIME → 类型标签（``type=`` 属性 / link alternate）
_MIME_KINDS: Tuple[Tuple[str, str], ...] = (
    ("application/pdf", "pdf"),
    ("application/zip", "archive"),
    ("application/x-zip", "archive"),
    ("application/x-rar", "archive"),
    ("application/x-7z", "archive"),
    ("application/gzip", "archive"),
    ("application/x-tar", "archive"),
    ("application/msword", "office"),
    ("application/vnd.openxmlformats", "office"),
    ("application/vnd.ms-", "office"),
    ("application/vnd.oasis", "office"),
    ("application/epub", "ebook"),
    ("text/csv", "data"),
    ("application/octet-stream", "binary"),
)

_HINT_RE = re.compile(
    r"(download|\bpdf\b|full[\s-]?text|fulltext|attachment|supplement|dataset|"
    r"下载|全文|附件|文件|原文|补充材料|数据集|导出)",
    re.I,
)
#: 明显不是文件的 URL 片段（分享 / 登录 / 列表页）
_NEGATIVE_RE = re.compile(r"(login|signin|share|twitter|facebook|weibo|mailto:|javascript:)", re.I)
#: 学术站 / 通用下载端点关键词（无后缀 URL 的加分项）
_ENDPOINT_RE = re.compile(
    r"(/pdf/|/download|/fulltext|/full-text|/attachment|/file/|/files/|/export|"
    r"[?&](download|attachment|file|pdf)=|\.pdf[?#]|/epdf/|/doi/pdf/|/content/pdf/)",
    re.I,
)
_META_REFRESH_RE = re.compile(r"url\s*=\s*['\"]?([^'\";\s]+)", re.I)

#: 最终返回的候选上限
MAX_FILE_CANDIDATES = 50


def classify_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """→ (扩展名, 类型标签)；无文件后缀返回 (None, None)。"""
    try:
        path = urlparse(url).path or ""
    except ValueError:
        return None, None
    lowered = path.lower()
    for ext, kind in FILE_EXTENSIONS.items():
        if lowered.endswith(ext):
            return ext.lstrip("."), kind
    return None, None


def classify_mime(mime: str) -> Optional[str]:
    lowered = (mime or "").lower().strip()
    if not lowered or lowered.startswith(("text/html", "application/xhtml")):
        return None
    for prefix, kind in _MIME_KINDS:
        if lowered.startswith(prefix):
            return kind
    return None


class _FileLinkCollector(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self.candidates: List[Dict[str, Any]] = []
        self._anchor: Optional[Dict[str, Any]] = None
        self._anchor_text: List[str] = []
        self._in_head = False

    # -- helpers ---------------------------------------------------------

    def _add(
        self, href: str, source: str, base_score: int, text: str = "", mime: str = "", **extra: Any
    ) -> None:
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return
        url = urljoin(self._base_url, href)
        if not url.lower().startswith(("http://", "https://")):
            return
        ext, kind = classify_url(url)
        mime_kind = classify_mime(mime)
        if kind is None and mime_kind:
            kind = mime_kind
        score = base_score
        if ext:
            score += 40 if kind == "pdf" else 30
        if mime_kind:
            score += 15
        if _ENDPOINT_RE.search(url):
            score += 15
        if text and _HINT_RE.search(text):
            score += 10
        if _NEGATIVE_RE.search(url):
            score -= 30
        if kind is None and score < 25:
            return
        self.candidates.append(
            {
                "url": url,
                "text": " ".join((text or "").split())[:200],
                "source": source,
                "ext": ext,
                "kind": kind,
                "mime": (mime or "").lower() or None,
                "score": score,
                **extra,
            }
        )

    # -- parser hooks ----------------------------------------------------

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs if k}
        if tag == "head":
            self._in_head = True
        elif tag == "meta":
            name = attr.get("name", "").lower()
            prop = attr.get("property", "").lower()
            content = attr.get("content", "")
            if name in ("citation_pdf_url", "citation_fulltext_html_url_pdf") and content:
                self._add(content, "meta:citation_pdf_url", 80, mime="application/pdf")
            elif (
                name in ("citation_abstract_pdf_url", "eprints.document_url", "dc.identifier")
                and content
            ):
                self._add(content, f"meta:{name}", 50)
            elif prop in ("og:file", "og:pdf") and content:
                self._add(content, f"meta:{prop}", 50)
            elif attr.get("http-equiv", "").lower() == "refresh" and content:
                match = _META_REFRESH_RE.search(content)
                if match:
                    self._add(match.group(1), "meta:refresh", 45)
        elif tag == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            mime = attr.get("type", "")
            if href and ("alternate" in rel or "enclosure" in rel) and classify_mime(mime):
                self._add(href, f"link:{rel.split()[0]}", 70, text=attr.get("title", ""), mime=mime)
            elif (
                href
                and classify_url(href)[0]
                and rel not in ("stylesheet", "icon", "shortcut icon", "preload", "modulepreload")
            ):
                self._add(href, f"link:{rel or 'href'}", 30, text=attr.get("title", ""), mime=mime)
        elif tag == "a":
            if self._anchor is not None:
                self.handle_endtag("a")  # 未闭合的上一个 <a>：先收口
            href = attr.get("href", "")
            if not href:
                return
            self._anchor = {
                "href": href,
                "download": "download" in attr,
                "mime": attr.get("type", ""),
                "label": " ".join(
                    p for p in (attr.get("title", ""), attr.get("aria-label", "")) if p
                ),
                "download_name": attr.get("download", ""),
            }
            self._anchor_text = []
        elif tag in ("iframe", "embed", "object"):
            src = attr.get("src") or attr.get("data") or ""
            mime = attr.get("type", "")
            if src and (classify_url(src)[0] or classify_mime(mime) or _ENDPOINT_RE.search(src)):
                self._add(src, tag, 40, text=attr.get("title", ""), mime=mime)
        elif tag == "img" and self._anchor is not None:
            alt = attr.get("alt", "")
            if alt:
                self._anchor_text.append(alt)

    def handle_startendtag(self, tag: str, attrs: List[Any]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag == "a" and self._anchor is not None:
            anchor = self._anchor
            self._anchor = None
            text = " ".join("".join(self._anchor_text).split())
            label = " ".join(p for p in (text, anchor["label"]) if p)
            base = 20
            source = "anchor"
            if anchor["download"]:
                base += 25
                source = "anchor:download"
            extra: Dict[str, Any] = {}
            if anchor["download_name"]:
                extra["download_name"] = anchor["download_name"]
            self._add(anchor["href"], source, base, text=label, mime=anchor["mime"], **extra)

    def close(self) -> None:
        super().close()
        if self._anchor is not None:
            self.handle_endtag("a")


def extract_file_links(
    html: str, base_url: str, limit: int = MAX_FILE_CANDIDATES
) -> List[Dict[str, Any]]:
    """从 HTML 抽取候选文件链接（按分数降序、URL 去重）。"""
    collector = _FileLinkCollector(base_url)
    try:
        collector.feed(html or "")
        collector.close()
    except Exception:  # noqa: BLE001 — 残缺 HTML 不阻断：返回已收集部分
        pass
    merged: Dict[str, Dict[str, Any]] = {}
    for item in collector.candidates:
        key = item["url"].split("#", 1)[0]
        existing = merged.get(key)
        if existing is None:
            fresh = dict(item)
            fresh["url"] = key
            fresh["sources"] = [fresh.pop("source")]
            merged[key] = fresh
            continue
        existing["sources"].append(item["source"])
        if item["score"] > existing["score"]:
            for field in ("score", "ext", "kind", "mime", "text"):
                if item.get(field):
                    existing[field] = item[field]
        elif not existing.get("text") and item.get("text"):
            existing["text"] = item["text"]
    ranked = sorted(merged.values(), key=lambda c: (-c["score"], c["url"]))
    for item in ranked:
        item["sources"] = sorted(set(item["sources"]))
    return ranked[: max(0, limit)]


def merge_file_links(
    primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]], limit: int = MAX_FILE_CANDIDATES
) -> List[Dict[str, Any]]:
    """合并两组候选（如渲染后 + 静态），同 URL 取高分并合并 sources。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for item in list(primary) + list(secondary):
        url = str(item.get("url", ""))
        if not url:
            continue
        existing = merged.get(url)
        if existing is None:
            copy = dict(item)
            copy["sources"] = list(item.get("sources") or [])
            merged[url] = copy
            continue
        existing["sources"] = sorted(set(existing["sources"]) | set(item.get("sources") or []))
        if int(item.get("score", 0)) > int(existing.get("score", 0)):
            for field in ("score", "ext", "kind", "mime", "text"):
                if item.get(field):
                    existing[field] = item[field]
    ranked = sorted(merged.values(), key=lambda c: (-int(c.get("score", 0)), str(c.get("url"))))
    return ranked[: max(0, limit)]


__all__ = [
    "FILE_EXTENSIONS",
    "MAX_FILE_CANDIDATES",
    "classify_mime",
    "classify_url",
    "extract_file_links",
    "merge_file_links",
]
