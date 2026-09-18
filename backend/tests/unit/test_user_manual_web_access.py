"""R19：用户手册「网页访问与登录态」章节守卫测试。

防止手册章节被误删/链接断裂，并锁定核心关键词（凭据 / 浏览器健康 /
SAGE_BROWSER_PATH / 出网指标）。文件名在 main（18-web-access.md）与
win7（19-web-access.md）上可能不同，故按 glob 匹配。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANUAL_DIR = _REPO_ROOT / "docs" / "user-manual"

_REQUIRED_KEYWORDS = ("凭据", "browser", "SAGE_BROWSER_PATH", "指标")


def test_web_access_chapter_exists_and_covers_key_topics():
    matches = sorted(_MANUAL_DIR.glob("*web-access.md"))
    assert matches, "用户手册缺少网页访问章节（*web-access.md）"
    text = matches[0].read_text(encoding="utf-8")
    for keyword in _REQUIRED_KEYWORDS:
        assert keyword in text, f"章节缺少关键词: {keyword}"


def test_manual_readme_links_the_chapter():
    readme = (_MANUAL_DIR / "README.md").read_text(encoding="utf-8")
    linked = [line for line in readme.splitlines() if "web-access.md" in line]
    assert linked, "手册 README 未链接网页访问章节"
