"""单站点多检索后端的枚举与探测（spec §6.2 / §6.3 / §6.4）。

库清单**只能在登录态下枚举**（未登录访问库清单页只会拿到「您还未登陆」），
因此枚举是**显式动作**（用户触发 / 首次使用该库时提示），不是全量自动 ——
全量自动会连续触发 WAF。
"""

from __future__ import annotations

import re
from typing import Callable, List, Tuple
from urllib.parse import urljoin

from .models import SiteBackend

#: 库入口路径形如 ``/dbItem/3``。
_DB_ITEM_PATTERN = re.compile(r"[\"'(]?/dbItem/(\d+)")

#: 从 ``<a href=".../dbItem/N">库名</a>`` 里同时取编号与库名。
_ENTRY_LINK_PATTERN = re.compile(
    r"href=[\"'][^\"']*/dbItem/(\d+)[^\"']*[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)

#: 命中即判定为 blocked（站点侧要求人工交互）。
_BLOCKED_TOKENS = ("滑块", "验证码", "人机验证", "拖动", "安全验证")

#: 命中即判定为 unavailable（站点侧直接报错）。
_UNAVAILABLE_TOKENS = (
    "代理报错",
    "代理访问失败",
    "资源已下线",
    "无法访问",
    "服务不可用",
    "不存在",
)

#: 命中即判定为 ready（检索表单已渲染）。
_READY_TOKENS = ("检索", "关键词", "请输入")


def _clean_label(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    return cleaned.strip()


def parse_backend_entries(snapshot: str, base_url: str) -> List[SiteBackend]:
    """从库清单页快照解析出各库入口。

    Args:
        snapshot: 页面快照文本。
        base_url: 库清单页 URL（用于把相对路径拼成绝对 URL）。

    Returns:
        ``SiteBackend`` 列表；状态一律为 ``unknown``（未探测）。
    """
    text = snapshot or ""
    labels = {
        match.group(1): _clean_label(match.group(2))
        for match in _ENTRY_LINK_PATTERN.finditer(text)
    }

    entries: List[SiteBackend] = []
    seen: set = set()
    for match in _DB_ITEM_PATTERN.finditer(text):
        number = match.group(1)
        backend_id = f"db{number}"
        if backend_id in seen:
            continue
        seen.add(backend_id)
        entry_url = urljoin(base_url, f"/dbItem/{number}")
        label = labels.get(number, "") or f"库 {number}"
        entries.append(
            SiteBackend(
                id=backend_id,
                label=label,
                entry_url=entry_url,
                status="unknown",
            )
        )
    return entries


def classify_probe(text: str) -> Tuple[str, str]:
    """把探测到的页面文本分类为 ``(status, reason)``。

    判定顺序：blocked → unavailable → ready → unknown。
    """
    content = text or ""
    for token in _BLOCKED_TOKENS:
        if token in content:
            return "blocked", f"触发{token}验证"
    for token in _UNAVAILABLE_TOKENS:
        if token in content:
            return "unavailable", f"站点侧报错：{token}"
    for token in _READY_TOKENS:
        if token in content:
            return "ready", ""
    return "unknown", "未探测"


def probe_backend(
    entry_url: str,
    fetch_title: Callable[[str], str],
    fetch_text: Callable[[str], str],
) -> Tuple[str, str]:
    """探测单个后端；返回 ``(status, reason)``。

    Args:
        entry_url: 后端入口 URL。
        fetch_title: 取页面标题的回调。
        fetch_text: 取页面正文的回调。
    """
    try:
        title = fetch_title(entry_url) or ""
        body = fetch_text(entry_url) or ""
    except Exception:  # noqa: BLE001 — 探测失败按 unknown 处理，不中断枚举
        return "unknown", "探测失败"
    return classify_probe(f"{title}\n{body}")
