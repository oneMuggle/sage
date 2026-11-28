"""文献 PDF 的 HTTP 下载快路径（spec §5.1 / §5.6）。

链路：``doDownload`` 入口 → 中间页 HTML → 解析 downurl → 按
``pdf.interstitial.host_fallbacks`` 换主机 → GET PDF → magic + 题名校验
→ 原子落盘。

**本模块不自己发 HTTP**：取数由外部注入的 ``Fetcher`` 完成。生产环境由
技能的 ``execute_code`` 代码用 ``sage.call("http_download", ...)`` 适配 ——
站点策略闸（Task 9）与限速（Task 8）因此自动生效，且本包保持不依赖
``backend.tools``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .interstitial import (
    parse_download_url,
    rewrite_host_candidates,
    select_first_valid,
)
from .models import SiteProfile
from .pdf_check import validate_pdf

logger = logging.getLogger(__name__)

#: 缺省的文件头魔数（profile 未声明 ``pdf.magic`` 时用这个）。
_DEFAULT_MAGIC = "%PDF-"


@dataclass(frozen=True)
class FetchResult:
    """一次 HTTP 取数的结果。"""

    status: int
    body: bytes


#: 取数函数签名：``(url, referer) -> FetchResult``。
Fetcher = Callable[[str, str], FetchResult]


@dataclass
class HttpDownloadOutcome:
    """HTTP 下载结果。"""

    path: Optional[str] = None
    ok: bool = False
    transport: str = "http"
    fallback_reason: str = ""
    errors: List[str] = field(default_factory=list)


def _host_fallbacks(profile: SiteProfile) -> List[str]:
    """取 profile 声明的主机回退列表。"""
    pdf = profile.pdf
    if pdf is None or pdf.interstitial is None:
        return []
    return list(pdf.interstitial.host_fallbacks or ())


def _magic_of(profile: SiteProfile) -> str:
    """取 profile 声明的文件头魔数。"""
    pdf = profile.pdf
    if pdf is None or not pdf.magic:
        return _DEFAULT_MAGIC
    return pdf.magic


def _fetch_entry_html(
    entry_url: str,
    referer: str,
    fetch: Fetcher,
) -> Tuple[str, str, str]:
    """取入口页 HTML；返回 ``(html, reason, message)``。

    失败时 ``reason`` 是可观测原因码（``no_entry_url`` /
    ``entry_fetch_failed`` / ``entry_status_<code>``），``message`` 是人读文案。
    """
    if not entry_url:
        return "", "no_entry_url", "缺少 doDownload 入口 URL"
    try:
        entry = fetch(entry_url, referer)
    except Exception as exc:  # noqa: BLE001 — 取数异常按失败上报，不伪造成功
        return "", "entry_fetch_failed", f"请求入口失败: {exc}"
    if entry.status != 200:
        return "", f"entry_status_{entry.status}", f"中间页 HTTP {entry.status}"
    return entry.body.decode("utf-8", errors="replace"), "", ""


def _candidate_urls(urls: List[str], profile: SiteProfile) -> List[str]:
    """把中间页解析出的 URL 展开成含主机回退的候选序列（保序去重）。"""
    fallbacks = _host_fallbacks(profile)
    candidates: List[str] = []
    for url in urls:
        for candidate in rewrite_host_candidates(url, fallbacks):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _safe_stem(title: str) -> str:
    """把题名转成安全的文件名主干（去非法字符、截断到 120 字符）。

    文件名用题名而不是固定 ``download`` —— 题名校验要比对文件名主干，
    且用户拿到磁盘上也有一个能认出来的名字。
    """
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(title or "").strip())
    text = text.strip(". ")
    return text[:120] or "download"


def _write_atomic(
    dest_dir: Path,
    stem: str,
    body: bytes,
) -> Tuple[Optional[Path], str]:
    """原子落盘；返回 ``(路径, 错误信息)``，成功时错误信息为空串。"""
    dest = Path(dest_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"创建目录失败: {exc}"
    part = dest / f"{stem}.pdf.part"
    final = dest / f"{stem}.pdf"
    try:
        part.write_bytes(body)
        part.replace(final)
    except OSError as exc:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
        return None, f"落盘失败: {exc}"
    return final, ""


def download_pdf_http(
    profile: SiteProfile,
    entry_url: str,
    expected_title: str,
    dest_dir: Path,
    fetch: Fetcher,
    *,
    referer: str = "",
) -> HttpDownloadOutcome:
    """走 HTTP 快路径下载一篇 PDF。

    Args:
        profile: 站点 profile（提供主机回退、magic 等）。
        entry_url: ``doDownload`` 入口 URL（由浏览器读元素 href 得到）。
        expected_title: 期望题名（用于落盘后校验）。
        dest_dir: 落盘目录。
        fetch: 注入的取数函数。
        referer: 检索页 Referer。

    Returns:
        ``HttpDownloadOutcome``；失败时 ``fallback_reason`` 给出可观测的原因码。
    """
    outcome = HttpDownloadOutcome()

    html, reason, message = _fetch_entry_html(entry_url, referer, fetch)
    if reason:
        outcome.fallback_reason = reason
        outcome.errors.append(message)
        return outcome

    urls = parse_download_url(html)
    if not urls:
        outcome.fallback_reason = "interstitial_parse_miss"
        outcome.errors.append("中间页未解析出下载地址")
        return outcome

    magic = _magic_of(profile)
    saw_non_pdf = False

    def _fetch_candidate(url: str) -> Optional[Tuple[str, bytes]]:
        nonlocal saw_non_pdf
        try:
            result = fetch(url, referer)
        except Exception:  # noqa: BLE001 — 单个候选失败继续试下一个
            return None
        if result.status != 200:
            return None
        if not result.body.startswith(magic.encode("utf-8")):
            # 取到了东西但不是 PDF（多半是登录墙 / 错误页）—— 与「取不到」区分开，
            # 否则两种失败会共用同一个原因码，事后无法定位。
            saw_non_pdf = True
            return None
        return url, result.body

    candidates = _candidate_urls(urls, profile)
    hit = select_first_valid(candidates, _fetch_candidate)
    if hit is None:
        outcome.fallback_reason = "magic_mismatch" if saw_non_pdf else "candidate_exhausted"
        outcome.errors.append(
            "候选地址返回的不是 PDF" if saw_non_pdf else "所有候选下载地址均未取得 PDF"
        )
        return outcome

    final, write_error = _write_atomic(dest_dir, _safe_stem(expected_title), hit[1])
    if final is None:
        outcome.fallback_reason = "write_failed"
        outcome.errors.append(write_error)
        return outcome

    errors = validate_pdf(final, expected_title, magic)
    if errors:
        final.unlink(missing_ok=True)
        body = hit[1]
        outcome.fallback_reason = (
            "magic_mismatch" if not body.startswith(magic.encode("utf-8")) else "title_mismatch"
        )
        outcome.errors.extend(errors)
        return outcome

    outcome.path = str(final)
    outcome.ok = True
    return outcome
