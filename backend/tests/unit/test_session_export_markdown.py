"""R18-C: 会话 Markdown 导出单元测试

覆盖 backend/application/services/session_export.py:
- render_export_markdown: 结构（标题/元信息/角色小节）、tool 折叠、
  空消息跳过、工具调用清单
- export_session_to_markdown: 落库读取（内存仓库 seam）、404 语义
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from backend.application.services.session_export import (
    SessionNotFoundError,
    build_session_payload,
    export_session_to_markdown,
    render_export_markdown,
)
from backend.data.session_repo import Message as MessageModel, Session as SessionModel

pytestmark = pytest.mark.unit


class _Repo:
    """最小内存仓库 seam（session_export 的可选注入参数）。"""

    def __init__(self, session: Optional[SessionModel], messages: List[MessageModel]):
        self._session = session
        self._messages = messages

    def get(self, session_id: str) -> Optional[SessionModel]:
        return self._session

    def get_by_session(self, session_id: str, limit: int = 10) -> List[MessageModel]:
        return self._messages


def _mk_session() -> SessionModel:
    return SessionModel(
        id="11111111-2222-3333-4444-555555555555",
        title="测试会话",
        created_at=1757600000000,
        updated_at=1757600000000,
        total_tokens=42,
        total_cost=0.01,
    )


def _mk_msg(role: str, content: str, **extra: Any) -> MessageModel:
    return MessageModel(
        id=f"m-{role}-{abs(hash(content)) % 10000}",
        session_id="11111111-2222-3333-4444-555555555555",
        role=role,
        content=content,
        created_at=1757600000001,
        **extra,
    )


def test_render_markdown_basic_structure():
    session = _mk_session()
    messages = [
        _mk_msg("user", "你好"),
        _mk_msg("assistant", "你好！有什么可以帮你？"),
    ]
    payload = build_session_payload(session, messages)
    md = render_export_markdown(payload)
    assert md.startswith("# 测试会话")
    assert "### 用户" in md
    assert "### Sage" in md
    assert "你好！有什么可以帮你？" in md


def test_render_markdown_folds_tool_messages_and_lists_calls():
    session = _mk_session()
    messages = [
        _mk_msg("user", "列出文件"),
        _mk_msg(
            "assistant",
            "",
            tool_calls='[{"name": "list_files", "args": {}}]',
        ),
        _mk_msg("tool", "a.txt\nb.txt"),
        _mk_msg("assistant", "共有两个文件。"),
    ]
    payload = build_session_payload(session, messages)
    md = render_export_markdown(payload)
    assert "↳ 工具结果" in md
    assert "调用工具 `list_files`" in md
    # 空内容的 assistant 消息若有工具调用则保留小节
    assert md.count("### ") >= 3


def test_render_markdown_skips_blank_non_tool_messages():
    session = _mk_session()
    messages = [_mk_msg("assistant", "   ")]
    payload = build_session_payload(session, messages)
    md = render_export_markdown(payload)
    assert "### Sage" not in md


def test_export_session_to_markdown_uses_repo_seam():
    session = _mk_session()
    messages = [_mk_msg("user", "ping"), _mk_msg("assistant", "pong")]
    result = export_session_to_markdown(
        session.id,
        session_repo=_Repo(session, messages),
        message_repo=_Repo(session, messages),
    )
    assert result.filename.endswith(".md")
    assert "# 测试会话" in result.html  # SessionExport.html 字段承载 md 文本
    assert result.message_count == 2


def test_export_session_to_markdown_raises_for_missing_session():
    with pytest.raises(SessionNotFoundError):
        export_session_to_markdown(
            "nope",
            session_repo=_Repo(None, []),
            message_repo=_Repo(None, []),
        )
