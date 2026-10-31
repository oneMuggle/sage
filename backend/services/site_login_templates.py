# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""常见学术站点登录模板。

模板只提供「默认登录入口 + 展示名 + 登录方式提示」，不包含任何凭据。
用户可在设置页一键选择，实际登录始终在浏览器里由用户完成。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: 模板按用户熟悉度排序；域名用于匹配凭据档案的 cookie domain。
SITE_LOGIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "cnki",
        "display_name": "知网 CNKI",
        "domains": ["cnki.net", "cnki.com.cn"],
        "login_url": "https://kns.cnki.net/",
        "login_hint": "支持个人账号、机构账号（CARSI）或校园网 IP 直接访问",
    },
    {
        "id": "wanfang",
        "display_name": "万方数据",
        "domains": ["wanfangdata.com.cn"],
        "login_url": "https://www.wanfangdata.com.cn/",
        "login_hint": "支持个人账号或机构账号",
    },
    {
        "id": "cqvip",
        "display_name": "维普期刊",
        "domains": ["cqvip.com"],
        "login_url": "https://www.cqvip.com/",
        "login_hint": "支持个人账号或机构账号",
    },
    {
        "id": "ieee",
        "display_name": "IEEE Xplore",
        "domains": ["ieeexplore.ieee.org"],
        "login_url": "https://ieeexplore.ieee.org/",
        "login_hint": "机构订阅用户通过校园网或机构登录访问",
    },
    {
        "id": "springer",
        "display_name": "SpringerLink",
        "domains": ["link.springer.com", "springer.com"],
        "login_url": "https://link.springer.com/",
        "login_hint": "机构订阅用户通过校园网或机构登录访问",
    },
]


def match_site_template(hostname: str) -> Optional[Dict[str, Any]]:
    """按 hostname 后缀匹配模板；未知站点返回 ``None``。"""
    host = (hostname or "").strip().lower().lstrip(".")
    if not host:
        return None
    for template in SITE_LOGIN_TEMPLATES:
        for domain in template["domains"]:
            if host == domain or host.endswith("." + domain):
                return template
    return None


def login_url_for_host(hostname: str) -> str:
    """凭据档案的默认登录入口：模板优先，否则站点首页。"""
    template = match_site_template(hostname)
    if template:
        return str(template["login_url"])
    host = (hostname or "").strip().lower().lstrip(".")
    return f"https://{host}/" if host else ""


def display_name_for_host(hostname: str) -> str:
    template = match_site_template(hostname)
    if template:
        return str(template["display_name"])
    return (hostname or "").strip().lower().lstrip(".")


__all__ = [
    "SITE_LOGIN_TEMPLATES",
    "display_name_for_host",
    "login_url_for_host",
    "match_site_template",
]
