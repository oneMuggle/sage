"""Profile 驱动的浏览器检索/下载执行器（不直接依赖 browser 工具）。"""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Protocol

from .guidance import render_search_guidance
from .interstitial import rewrite_host_candidates
from .models import SiteProfile, render_search_url


class BrowserDriver(Protocol):
    """浏览器驱动协议。

    可选能力（站点 profile 声明 ``pdf.interstitial`` 时需要）：
    ``element_attr(selector, name)``、``tabs()``、``open_tab(url)``、
    ``focus_tab(tab_id)``、``close_tab(tab_id)``。缺失时下载自动回退到
    原「点击入口」路径。
    """

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


def _candidate_download_urls(url: str, hosts: List[str]) -> List[str]:
    """生成候选下载地址（主机回退优先，原域最后）。

    委托 ``interstitial.rewrite_host_candidates``，避免两处逻辑漂移。
    """
    return rewrite_host_candidates(url, hosts)


def _find_interstitial_tab(
    driver: BrowserDriver, inter: Any, timeout_s: float
) -> Optional[dict]:
    """轮询标签页，返回 URL 命中 ``url_contains`` 的中间页/跳转页。"""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        try:
            tabs = driver.tabs()
        except Exception:  # noqa: BLE001 — 驱动缺能力/失败按未发现处理
            return None
        for tab in tabs:
            url = str(tab.get("url") or "")
            if url and any(token in url for token in inter.url_contains):
                return tab
        if time.monotonic() >= deadline:
            return None
        driver.sleep(0.5)


def _close_tab_quietly(driver: BrowserDriver, tab_id: str) -> None:
    closer = getattr(driver, "close_tab", None)
    if closer is None or not tab_id:
        return
    with contextlib.suppress(Exception):
        closer(tab_id)


def _download_via_interstitial(  # noqa: PLR0911 — 能力缺失/失败路径各自独立早退
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float,
    *,
    entry_url: str,
    entry_selector: str,
) -> Optional[DownloadResult]:
    """中间页下载；返回 None 表示应回退到原「点击入口」路径。"""
    pdf = profile.pdf
    inter = pdf.interstitial if pdf is not None else None
    if inter is None:
        return None
    if not entry_url:
        selector = entry_selector or pdf.entry_selector or ""
        reader = getattr(driver, "element_attr", None)
        if not selector or reader is None:
            return None
        try:
            entry_url = reader(selector, "href")
        except Exception:  # noqa: BLE001 — 读取失败按回退处理
            return None
    opener = getattr(driver, "open_tab", None)
    if not entry_url or opener is None:
        return None
    tab_id = opener(entry_url)
    if inter.sleep_after_open_s:
        driver.sleep(inter.sleep_after_open_s)
    tab = _find_interstitial_tab(driver, inter, inter.tab_timeout_s)
    if tab is None:
        _close_tab_quietly(driver, tab_id)
        return DownloadResult(
            None,
            False,
            ["未发现下载中间页标签（检查 pdf.interstitial.url_contains）"],
        )
    target_tab = str(tab.get("tab_id") or tab_id or "")
    candidates = _candidate_download_urls(
        str(tab.get("url") or ""), list(inter.host_fallbacks)
    )
    errors: List[str] = []
    for index, candidate in enumerate(candidates):
        if target_tab:
            driver.focus_tab(target_tab)
        # 附件下载会中断导航（ERR_ABORTED），异常不阻断后续等下载
        with contextlib.suppress(Exception):
            driver.navigate(candidate)
        last = index == len(candidates) - 1
        wait_s = timeout_s if last else min(timeout_s, inter.attempt_timeout_s)
        downloaded = driver.wait_download(timeout_s=wait_s)
        if not downloaded:
            errors.append(f"{candidate}: 等待下载超时")
            continue
        path = Path(downloaded)
        problems = validate_pdf(path, expected_title, pdf.magic)
        if pdf.forbid:
            for word in pdf.forbid:
                if word.lower() in path.suffix.lower():
                    problems.append(f"禁止的下载格式: {word}")
        if not problems:
            _close_tab_quietly(driver, target_tab)
            return DownloadResult(str(path), True)
        errors.extend(f"{candidate}: {problem}" for problem in problems)
    _close_tab_quietly(driver, target_tab)
    return DownloadResult(None, False, errors or ["下载失败"])


def download_pdf(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: float = 60,
    *,
    entry_url: str = "",
    entry_selector: str = "",
) -> DownloadResult:
    """下载并校验 PDF。

    站点声明了 ``pdf.interstitial`` 时走「中间页 + 主机回退」路径：
    读取入口 href → 新标签打开 → 等中间页跳转 → 按回退主机重写 URL 导航 →
    等下载完成；拿不到入口 URL 或驱动缺能力时回退到原「点击入口」路径。

    原路径必须点击 DOM 元素本身：部分站点的 href 除 url 外还带站点需要的
    附加参数（如 ``&ddata=...``），用快照里可能截断的 URL 直连会报
    「参数错误」。
    """
    if profile.pdf is None:
        return DownloadResult(None, False, ["站点未配置 pdf 下载"])
    if profile.pdf.interstitial is not None:
        result = _download_via_interstitial(
            profile,
            driver,
            expected_title,
            dest_dir,
            timeout_s,
            entry_url=entry_url,
            entry_selector=entry_selector,
        )
        if result is not None:
            return result
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
