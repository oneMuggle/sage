"""Profile 驱动的浏览器检索/下载执行器（不直接依赖 browser 工具）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Protocol

from .guidance import render_search_guidance
from .models import SiteProfile, render_search_url


class BrowserDriver(Protocol):
    def navigate(self, url: str, wait_for: str = "") -> str: ...
    def snapshot(self) -> str: ...
    def click(self, target: str) -> None: ...
    def click_text(self, text: str) -> None: ...
    def type_text(self, selector: str, text: str, clear: bool = True) -> bool: ...
    def press_key(self, key: str) -> None: ...
    def sleep(self, seconds: float) -> None: ...
    def current_url(self) -> str: ...
    def current_title(self) -> str: ...
    def wait_download(self, timeout_s: float = 60) -> Optional[str]: ...


def _fast_fetch_text(driver: Any, url: str) -> Optional[str]:
    """快路径：驱动支持 ``fetch_text``（web_fetch 通道）时优先用它取正文。

    驱动不支持、登录墙、反爬或工具异常一律返回 ``None``，由调用方回落到浏览器。
    """
    fetcher = getattr(driver, "fetch_text", None)
    if fetcher is None:
        return None
    try:
        text = fetcher(url)
    except Exception:  # noqa: BLE001 — 快路径失败不应中断检索
        return None
    text = str(text or "").strip()
    return text or None


@dataclass(frozen=True)
class SearchObservation:
    url: str
    page_url: str
    page_title: str
    guidance: str
    snapshot: str


def search_with_profile(
    profile: SiteProfile, query: str, driver: BrowserDriver, limit: int = 10
) -> SearchObservation:
    wait_for = ", ".join(profile.search.wait_for)
    if profile.search.mode == "interactive":
        entry = profile.search.entry_url or profile.search.url_template
        page_url = driver.navigate(entry, wait_for=wait_for)
        if profile.search.entry_click:
            driver.click_text(profile.search.entry_click)
            driver.sleep(1.0)
        typed = False
        for selector in profile.search.input_selectors:
            if driver.type_text(selector, query, clear=True):
                typed = True
                break
        if not typed:
            raise RuntimeError("未找到可用的搜索输入框（检查 search.input_selectors）")
        driver.press_key(profile.search.submit_key)
        if profile.search.wait_after_s:
            driver.sleep(profile.search.wait_after_s)
        snapshot = driver.snapshot()
        guidance = render_search_guidance(
            profile,
            query,
            limit=limit,
            page_url=driver.current_url() or page_url,
            page_title=driver.current_title(),
        )
        return SearchObservation(
            entry, page_url, driver.current_title(), guidance, snapshot
        )

    url = render_search_url(profile, query, limit=limit)
    fast_text = _fast_fetch_text(driver, url)
    if fast_text:
        page_url = driver.current_url() or url
        page_title = driver.current_title()
        guidance = render_search_guidance(
            profile,
            query,
            limit=limit,
            page_url=page_url,
            page_title=page_title,
        )
        return SearchObservation(url, page_url, page_title, guidance, fast_text)
    page_url = driver.navigate(url, wait_for=wait_for)
    snapshot = driver.snapshot()
    guidance = render_search_guidance(
        profile,
        query,
        limit=limit,
        page_url=driver.current_url() or page_url,
        page_title=driver.current_title(),
    )
    return SearchObservation(url, page_url, driver.current_title(), guidance, snapshot)


@dataclass
class DownloadResult:
    path: Optional[str]
    ok: bool
    errors: List[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def validate_pdf(path: Path, expected_title: str, magic: str = "%PDF-") -> List[str]:
    errors: List[str] = []
    if not path.is_file():
        return [f"下载文件不存在: {path}"]
    with path.open("rb") as handle:
        head = handle.read(len(magic))
    if head != magic.encode("ascii"):
        errors.append(f"文件头不是 {magic}")
    if expected_title:
        expected = _normalize(expected_title)
        actual = _normalize(path.stem)
        if expected and expected not in actual and actual not in expected:
            errors.append(f"文件名与题名不匹配: {path.name!r} vs {expected_title!r}")
    return errors


def download_pdf(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float = 60,
) -> DownloadResult:
    """点击真实下载链接元素（selector 优先）。

    xueshu789 等站点的 href 除 url 外还带站点需要的附加参数（如
    ``&ddata=文件名|库|题名|库|hash``）；必须点击 DOM 元素本身，
    不要用快照里可能截断的 URL 直连，否则服务端会报「参数错误」。
    """
    if profile.pdf is None:
        return DownloadResult(None, False, ["站点未配置 pdf 下载"])
    target = profile.pdf.entry_selector or profile.pdf.entry_text
    if not target:
        return DownloadResult(None, False, ["站点未配置 PDF 入口"])
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if profile.pdf.entry_selector:
        driver.click(profile.pdf.entry_selector)
    else:
        driver.click_text(profile.pdf.entry_text or "")
    if profile.pdf.post_click_wait_s:
        driver.sleep(profile.pdf.post_click_wait_s)
    downloaded = driver.wait_download(timeout_s=timeout_s)
    if not downloaded:
        return DownloadResult(None, False, ["等待下载超时"])
    path = Path(downloaded)
    errors = validate_pdf(path, expected_title, profile.pdf.magic)
    if profile.pdf.forbid:
        for word in profile.pdf.forbid:
            if word.lower() in path.suffix.lower():
                errors.append(f"禁止的下载格式: {word}")
    return DownloadResult(str(path), not errors, errors)
