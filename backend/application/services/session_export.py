"""
会话 HTML 导出服务 (U18)

设计与 pi (https://pi.dev, MIT) 的 coding-agent export-html 模块同源:

- 会话数据以 Base64 JSON 嵌入模板 ``<script type="application/json">``,
  从根上规避一切 HTML/JS 转义问题;
- marked.js + highlight.js 以静态资源内联进产物,导出的 HTML 完全离线
  自包含(无 CDN 依赖),适配内网/气隙环境(如 Win7 LTS 用户);
- 消息 / 工具调用 / edit diff / 思考过程由客户端 ``template.js`` 渲染;
- 深色 / 浅色 / 跟随系统三态主题,产物内可切换(localStorage 记忆);
- 产物带 CSP ``script-src`` sha256 白名单:仅允许内联的三个静态脚本,
  阻断一切注入脚本与内联事件处理器。

Py3.8 兼容(release/win7 LTS 分支共用本模块)。
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.session_repo import (
    Message,
    MessageRepository,
    Session,
    SessionRepository,
)

#: 模板与静态资源目录(与模块同级的 export_assets/)
EXPORT_ASSETS_DIR = Path(__file__).parent / "export_assets"

#: 支持的主题模式;auto = 跟随系统 prefers-color-scheme
VALID_THEMES = ("auto", "dark", "light")
DEFAULT_THEME = "auto"

#: 单次导出的消息数上限(与 fork_session 全量复制口径一致)
MAX_EXPORT_MESSAGES = 100000

APP_NAME = "sage"


class SessionNotFoundError(LookupError):
    """要导出的会话不存在。路由层据此映射 404。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"session not found: {session_id}")


@dataclass
class SessionExport:
    """一次导出的完整结果。"""

    session_id: str
    filename: str
    html: str
    message_count: int
    theme: str


# ==================== 载荷构建(纯函数) ====================


def _parse_tool_calls(raw: Optional[str]) -> List[Dict[str, Any]]:
    """``messages.tool_calls`` JSON 字符串 → dict 列表;非法数据降级为 []。

    持久化形态由 sqlite_adapter._serialize_tool_calls 约定:
    ``[{"name": ..., "args": {...}, "id": ...}, ...]``。
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _message_to_entry(message: Message) -> Dict[str, Any]:
    """持久化 Message → 导出载荷条目(字段重排,不做过滤)。"""
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content or "",
        "created_at": message.created_at,
        "model": message.model,
        "provider": message.provider,
        "tool_calls": _parse_tool_calls(message.tool_calls),
        "tool_call_id": message.tool_call_id,
        "reasoning_content": message.reasoning_content or "",
    }


def _compute_stats(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总头部统计信息(消息数 / 工具调用数 / 思考块 / 模型集)。"""
    user_count = 0
    assistant_count = 0
    tool_result_count = 0
    tool_call_count = 0
    thinking_count = 0
    models = set()
    for entry in entries:
        role = entry.get("role")
        if role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1
            tool_call_count += len(entry.get("tool_calls") or [])
            if entry.get("reasoning_content"):
                thinking_count += 1
            model = entry.get("model")
            if model:
                models.add(model)
        elif role == "tool":
            tool_result_count += 1
    return {
        "user_messages": user_count,
        "assistant_messages": assistant_count,
        "tool_results": tool_result_count,
        "tool_calls": tool_call_count,
        "thinking_blocks": thinking_count,
        "models": sorted(models),
    }


def build_session_payload(session: Session, messages: List[Message]) -> Dict[str, Any]:
    """组装导出 JSON 载荷(纯函数,可独立测试)。"""
    entries = [_message_to_entry(m) for m in messages]
    return {
        "app": APP_NAME,
        "exported_at": int(time.time() * 1000),
        "header": {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "total_tokens": session.total_tokens,
            "total_cost": session.total_cost,
        },
        "entries": entries,
        "stats": _compute_stats(entries),
    }


# ==================== HTML 渲染(纯函数) ====================


def _script_hash(script_text: str) -> str:
    """计算 CSP script-src 用的 ``'sha256-<b64>'`` 项。

    浏览器按脚本元素内 UTF-8 文本字节计算哈希,故这里对 encode 后的
    字节取 sha256 —— 必须与最终写进 HTML 的脚本内容逐字节一致。
    """
    digest = hashlib.sha256(script_text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _build_filename(session: Session) -> str:
    """``sage-session-<8位id>-<会话创建时间>.html``

    ``max(0, ...)`` 兜底:Windows 的 ``time.localtime`` 对负 epoch 抛 OSError,
    而 created_at 恒为正毫秒值,这里仅做防御性夹取。
    """
    short_id = session.id.replace("-", "")[:8] or "session"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(max(0, session.created_at) / 1000))
    return f"{APP_NAME}-session-{short_id}-{stamp}.html"


def render_export_html(payload: Dict[str, Any], theme: str = DEFAULT_THEME) -> str:
    """把载荷 + 主题渲染为自包含导出 HTML。

    非法 theme 归一化为 DEFAULT_THEME,与路由层双重兜底。
    """
    normalized_theme = theme if theme in VALID_THEMES else DEFAULT_THEME

    template = (EXPORT_ASSETS_DIR / "template.html").read_text(encoding="utf-8")
    css = (EXPORT_ASSETS_DIR / "template.css").read_text(encoding="utf-8")
    js = (EXPORT_ASSETS_DIR / "template.js").read_text(encoding="utf-8")
    marked_js = (EXPORT_ASSETS_DIR / "vendor" / "marked.min.js").read_text(encoding="utf-8")
    highlight_js = (EXPORT_ASSETS_DIR / "vendor" / "highlight.min.js").read_text(
        encoding="utf-8"
    )

    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    csp_hashes = " ".join(_script_hash(s) for s in (marked_js, highlight_js, js))
    header = payload.get("header") or {}
    title = html_escape(str(header.get("title") or APP_NAME), quote=True)

    # 占位符内容本身不含其它 {{TOKEN}}(资源文件受控),逐个替换安全。
    return (
        template.replace("{{THEME_MODE}}", normalized_theme)
        .replace("{{CSP_SCRIPT_HASHES}}", csp_hashes)
        .replace("{{TITLE}}", title)
        .replace("{{CSS}}", css)
        .replace("{{SESSION_DATA}}", payload_b64)
        .replace("{{MARKED_JS}}", marked_js)
        .replace("{{HIGHLIGHT_JS}}", highlight_js)
        .replace("{{JS}}", js)
    )


# ==================== 对外入口 ====================


def export_session_to_html(
    session_id: str,
    theme: str = DEFAULT_THEME,
    session_repo: Optional[SessionRepository] = None,
    message_repo: Optional[MessageRepository] = None,
) -> SessionExport:
    """导出完整会话为自包含 HTML。

    Args:
        session_id: 目标会话 id
        theme: ``auto`` / ``dark`` / ``light``,非法值归一化为 auto
        session_repo: 可选注入(测试 seam);缺省取全局 DB
        message_repo: 可选注入(测试 seam);缺省取全局 DB

    Raises:
        SessionNotFoundError: 会话不存在
    """
    sess_repo = session_repo or SessionRepository()
    msg_repo = message_repo or MessageRepository()

    session = sess_repo.get(session_id)
    if session is None:
        raise SessionNotFoundError(session_id)

    messages = msg_repo.get_by_session(session_id, limit=MAX_EXPORT_MESSAGES)
    payload = build_session_payload(session, messages)
    normalized_theme = theme if theme in VALID_THEMES else DEFAULT_THEME
    html_text = render_export_html(payload, normalized_theme)

    return SessionExport(
        session_id=session_id,
        filename=_build_filename(session),
        html=html_text,
        message_count=len(messages),
        theme=normalized_theme,
    )
