"""HTTP 出网前的站点策略闸门（spec §5.5）。

现状缺陷（C1）：``web_fetch`` / ``http_download`` 完全绕过
``browser_safety`` 的站点策略 —— 浏览器路径要用户确认，HTTP 路径却裸奔。
本模块把两条路径的约束对齐：同样的 ``check_site`` 判定、同样的
``ConfirmationRegistry`` 确认单、同样的 ``needs_confirmation: <id>`` 错误形态，
用户在**同一个**右栏面板裁决。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.services import browser_safety
<<<<<<< HEAD
=======
from backend.tools.context import current_tool_context
>>>>>>> origin/main

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteGateVerdict:
    """站点策略判定结果。"""

    allowed: bool
    reason: str
    confirmation_id: str = ""
    domain: str = ""


<<<<<<< HEAD
=======
def _current_conversation() -> str:
    """当前工具调用所属的聊天会话 id；无上下文返回空串。"""
    ctx = current_tool_context()
    return (ctx.session_id or "") if ctx is not None else ""


>>>>>>> origin/main
def gate_http_url(url: str, session_id: str = "") -> SiteGateVerdict:
    """判定一次 HTTP 出网是否被允许。

    Args:
        url: 目标 URL。
        session_id: 会话 id（决定会话级授权与确认单归属）。

    Returns:
        ``SiteGateVerdict``；``allowed=True`` 表示放行。
    """
    domain = browser_safety.domain_of(url)
    if not domain:
        return SiteGateVerdict(allowed=True, reason="allow", domain="")

    verdict = browser_safety.check_site(session_id, url)
    if verdict == "allow":
        return SiteGateVerdict(allowed=True, reason="allow", domain=domain)

    if verdict == "block":
        return SiteGateVerdict(
            allowed=False,
            reason="block",
            domain=domain,
        )

    registry = browser_safety.get_confirmation_registry()
    pending = registry.create(
        session_id,
        "site_access",
        code="site_access",
        domain=domain,
        description=f"访问站点 {domain}：{url}",
        options=list(browser_safety.SITE_ACCESS_OPTIONS),
        fingerprint=f"http:{domain}",
<<<<<<< HEAD
=======
        conversation_id=_current_conversation(),
>>>>>>> origin/main
    )
    logger.info("HTTP 出网待确认 domain=%s confirmation=%s", domain, pending.id)
    return SiteGateVerdict(
        allowed=False,
        reason="confirm",
        confirmation_id=pending.id,
        domain=domain,
    )


def gate_error_message(verdict: SiteGateVerdict) -> str:
    """把判定渲染成与浏览器路径同构的错误文案。"""
    if verdict.reason == "block":
        return f"site_blocked: 用户已禁止该站点 {verdict.domain}"
    return (
        f"needs_confirmation: {verdict.confirmation_id} "
        f"访问站点 {verdict.domain}（请在右栏浏览器面板确认）"
    )
