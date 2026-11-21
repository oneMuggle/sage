"""Profile 驱动的浏览器检索/下载执行器（不直接依赖 browser 工具）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Protocol

from .guidance import render_search_guidance
from .models import SiteProfile, render_search_url


class BrowserDriver(Protocol):
    def navigate(self, url: str, wait_for: str = "") -> str: ...
    def snapshot(self) -> str: ...
    def click(self, target: str) -> None: ...
    def current_url(self) -> str: ...
    def current_title(self) -> str: ...
    def wait_download(self, timeout_s: float = 60) -> Optional[str]: ...


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
    url = render_search_url(profile, query, limit=limit)
    wait_for = ", ".join(profile.search.wait_for)
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
    if profile.pdf is None:
        return DownloadResult(None, False, ["站点未配置 pdf 下载"])
    target = profile.pdf.entry_selector or profile.pdf.entry_text
    if not target:
        return DownloadResult(None, False, ["站点未配置 PDF 入口"])
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    driver.click(target)
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
