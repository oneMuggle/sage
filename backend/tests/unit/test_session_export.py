"""
U18: HTML 会话导出测试

覆盖:
- 载荷构建纯函数 (_parse_tool_calls / _message_to_entry / _compute_stats)
- build_session_payload 结构
- render_export_html: 占位符清理 / Base64 载荷往返 / CSP 哈希一致性 /
  主题归一化 / 标题转义
- export_session_to_html: DB 全链路 + 404 语义
- 路由契约: JSON 信封 / Accept: text/html 直取文件 / 404 / extra=forbid
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid

import pytest

from backend.application.services.session_export import (
    DEFAULT_THEME,
    EXPORT_ASSETS_DIR,
    SessionNotFoundError,
    _build_filename,
    _compute_stats,
    _message_to_entry,
    _parse_tool_calls,
    build_session_payload,
    export_session_to_html,
    render_export_html,
)
from backend.data.session_repo import Message, MessageRepository, Session, SessionRepository

pytestmark = pytest.mark.unit

SESSION_DATA_RE = re.compile(
    r'<script id="session-data" type="application/json">([A-Za-z0-9+/=]+)</script>'
)

PLACEHOLDERS = (
    "{{THEME_MODE}}",
    "{{CSP_SCRIPT_HASHES}}",
    "{{TITLE}}",
    "{{CSS}}",
    "{{SESSION_DATA}}",
    "{{MARKED_JS}}",
    "{{HIGHLIGHT_JS}}",
    "{{JS}}",
)


# ==================== 测试工具 ====================


def _make_session(**overrides) -> Session:
    now = int(time.time() * 1000)
    base = {
        "id": "s-" + uuid.uuid4().hex[:8],
        "title": "测试会话",
        "created_at": now - 60_000,
        "updated_at": now,
    }
    base.update(overrides)
    return Session(**base)


def _make_message(session_id: str, role: str, content: str, **overrides) -> Message:
    base = {
        "id": "msg-" + uuid.uuid4().hex[:8],
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": int(time.time() * 1000),
    }
    base.update(overrides)
    return Message(**base)


def _extract_payload(html_text: str):
    """从导出 HTML 中取出 Base64 载荷并还原为 dict。"""
    match = SESSION_DATA_RE.search(html_text)
    assert match is not None, "导出 HTML 缺少 Base64 载荷 script 标签"
    raw = base64.b64decode(match.group(1)).decode("utf-8")
    return json.loads(raw)


def _expected_script_hashes():
    """按渲染顺序计算三个内联脚本的 CSP sha256 项。"""
    paths = [
        EXPORT_ASSETS_DIR / "vendor" / "marked.min.js",
        EXPORT_ASSETS_DIR / "vendor" / "highlight.min.js",
        EXPORT_ASSETS_DIR / "template.js",
    ]
    hashes = []
    for path in paths:
        digest = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return hashes


def _sample_payload() -> dict:
    session = _make_session(title="示例会话", total_tokens=1234)
    messages = [
        _make_message(session.id, "user", "你好"),
        _make_message(
            session.id,
            "assistant",
            "我可以帮你改文件",
            model="gpt-test",
            reasoning_content="用户想改文件,先读取",
            tool_calls=json.dumps(
                [{"name": "edit", "args": {"path": "a.py", "old_string": "x", "new_string": "y"}, "id": "t1"}]
            ),
        ),
        _make_message(session.id, "tool", "编辑成功", tool_call_id="t1"),
    ]
    return build_session_payload(session, messages)


# ==================== _parse_tool_calls ====================


class TestParseToolCalls:
    def test_parses_valid_json_list(self):
        raw = json.dumps([{"name": "bash", "args": {"command": "ls"}, "id": "t1"}])
        result = _parse_tool_calls(raw)
        assert result == [{"name": "bash", "args": {"command": "ls"}, "id": "t1"}]

    def test_invalid_json_degrades_to_empty(self):
        assert _parse_tool_calls("{not-json") == []

    def test_non_list_json_degrades_to_empty(self):
        assert _parse_tool_calls('{"name": "bash"}') == []

    def test_empty_and_none_degrade_to_empty(self):
        assert _parse_tool_calls(None) == []
        assert _parse_tool_calls("") == []

    def test_non_dict_items_filtered(self):
        raw = json.dumps([{"name": "x"}, "junk", 3, None])
        assert _parse_tool_calls(raw) == [{"name": "x"}]


# ==================== _message_to_entry ====================


class TestMessageToEntry:
    def test_maps_all_fields(self):
        msg = _make_message(
            "s-1",
            "assistant",
            "回答",
            model="m-1",
            provider="openai",
            tool_calls=json.dumps([{"name": "bash", "args": {}, "id": "t9"}]),
            tool_call_id=None,
            reasoning_content="想一想",
        )
        entry = _message_to_entry(msg)
        assert entry["id"] == msg.id
        assert entry["role"] == "assistant"
        assert entry["content"] == "回答"
        assert entry["model"] == "m-1"
        assert entry["provider"] == "openai"
        assert entry["tool_calls"] == [{"name": "bash", "args": {}, "id": "t9"}]
        assert entry["tool_call_id"] is None
        assert entry["reasoning_content"] == "想一想"

    def test_missing_optional_fields_normalized(self):
        msg = _make_message("s-1", "user", "hi")
        entry = _message_to_entry(msg)
        assert entry["tool_calls"] == []
        assert entry["reasoning_content"] == ""
        assert entry["model"] is None


# ==================== _compute_stats ====================


class TestComputeStats:
    def test_counts_roles_tools_thinking_models(self):
        payload = _sample_payload()
        stats = payload["stats"]
        assert stats["user_messages"] == 1
        assert stats["assistant_messages"] == 1
        assert stats["tool_results"] == 1
        assert stats["tool_calls"] == 1
        assert stats["thinking_blocks"] == 1
        assert stats["models"] == ["gpt-test"]

    def test_empty_entries(self):
        stats = _compute_stats([])
        assert stats["user_messages"] == 0
        assert stats["models"] == []


# ==================== build_session_payload ====================


class TestBuildSessionPayload:
    def test_structure(self):
        session = _make_session(title="结构测试", total_tokens=42)
        messages = [_make_message(session.id, "user", "第一条")]
        payload = build_session_payload(session, messages)

        assert payload["app"] == "sage"
        assert isinstance(payload["exported_at"], int)
        header = payload["header"]
        assert header["id"] == session.id
        assert header["title"] == "结构测试"
        assert header["total_tokens"] == 42
        assert len(payload["entries"]) == 1
        assert payload["entries"][0]["content"] == "第一条"
        assert "stats" in payload


# ==================== render_export_html ====================


class TestRenderExportHtml:
    def test_self_contained_structure(self):
        html_text = render_export_html(_sample_payload(), theme="dark")
        assert html_text.startswith("<!DOCTYPE html>")
        assert 'data-theme="dark"' in html_text
        assert "Content-Security-Policy" in html_text
        assert "marked" in html_text.lower()  # marked.js 已内联
        assert "hljs" in html_text  # highlight.js 已内联
        assert SESSION_DATA_RE.search(html_text) is not None

    def test_no_placeholders_left(self):
        html_text = render_export_html(_sample_payload())
        for token in PLACEHOLDERS:
            assert token not in html_text, f"残留占位符: {token}"
        # 资源文件受控,不含任何 {{ 序列
        assert "{{" not in html_text

    def test_payload_roundtrip(self):
        payload = _sample_payload()
        html_text = render_export_html(payload)
        restored = _extract_payload(html_text)
        assert restored == payload

    def test_theme_normalization(self):
        assert 'data-theme="auto"' in render_export_html(_sample_payload(), theme="sunny")
        assert 'data-theme="auto"' in render_export_html(_sample_payload(), theme=DEFAULT_THEME)
        assert 'data-theme="light"' in render_export_html(_sample_payload(), theme="light")

    def test_csp_hashes_match_inlined_scripts(self):
        html_text = render_export_html(_sample_payload())
        for item in _expected_script_hashes():
            assert item in html_text, f"CSP 缺少脚本哈希 {item[:32]}"

    def test_title_html_escaped(self):
        payload = _sample_payload()
        payload["header"]["title"] = '<script>alert("x")</script>'
        html_text = render_export_html(payload)
        assert "<script>alert" not in html_text
        assert "&lt;script&gt;alert" in html_text  # <title> 内已转义


# ==================== _build_filename ====================


class TestBuildFilename:
    def test_format(self):
        session = _make_session(id="abcdef12-3456-7890-abcd-ef1234567890")
        filename = _build_filename(session)
        assert filename.startswith("sage-session-abcdef12-")
        assert filename.endswith(".html")


# ==================== export_session_to_html(DB 全链路) ====================


class TestExportSessionToHtml:
    def test_happy_path(self):
        session = SessionRepository().create(title="导出全链路")
        msg_repo = MessageRepository()
        msg_repo.save(_make_message(session.id, "user", "问题?"))
        msg_repo.save(
            _make_message(
                session.id,
                "assistant",
                "回答。",
                model="gpt-test",
                reasoning_content="推理",
                tool_calls=json.dumps([{"name": "bash", "args": {"command": "ls"}, "id": "t1"}]),
            )
        )
        msg_repo.save(_make_message(session.id, "tool", "file.txt", tool_call_id="t1"))

        result = export_session_to_html(session.id)

        assert result.session_id == session.id
        assert result.message_count == 3
        assert result.theme == "auto"
        assert result.filename.endswith(".html")
        payload = _extract_payload(result.html)
        assert [e["role"] for e in payload["entries"]] == ["user", "assistant", "tool"]
        assert payload["stats"]["tool_calls"] == 1
        assert payload["stats"]["thinking_blocks"] == 1

    def test_theme_passthrough_and_normalization(self):
        session = SessionRepository().create(title="主题")
        assert export_session_to_html(session.id, theme="light").theme == "light"
        assert export_session_to_html(session.id, theme="bogus").theme == "auto"

    def test_missing_session_raises(self):
        with pytest.raises(SessionNotFoundError):
            export_session_to_html("no-such-session")


# ==================== 路由契约 ====================


class TestExportRoute:
    async def test_returns_json_envelope(self, client):
        session = SessionRepository().create(title="JSON 信封")
        resp = await client.post(f"/api/v1/sessions/{session.id}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"html", "filename", "session_id", "message_count", "theme"}
        assert data["html"].startswith("<!DOCTYPE html>")
        assert data["session_id"] == session.id
        assert data["message_count"] == 0
        assert data["theme"] == "auto"
        assert data["filename"].endswith(".html")

    async def test_theme_from_body(self, client):
        session = SessionRepository().create(title="主题请求")
        resp = await client.post(
            f"/api/v1/sessions/{session.id}/export", json={"theme": "dark"}
        )
        assert resp.status_code == 200
        assert resp.json()["theme"] == "dark"

    async def test_unknown_body_keys_rejected(self, client):
        session = SessionRepository().create(title="多余字段")
        resp = await client.post(
            f"/api/v1/sessions/{session.id}/export",
            json={"theme": "auto", "bogus": 1},
        )
        assert resp.status_code == 422

    async def test_accept_html_returns_file(self, client):
        session = SessionRepository().create(title="HTML 直取")
        resp = await client.post(
            f"/api/v1/sessions/{session.id}/export",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "attachment" in resp.headers["content-disposition"]
        assert ".html" in resp.headers["content-disposition"]
        assert resp.text.startswith("<!DOCTYPE html>")

    async def test_missing_session_404(self, client):
        resp = await client.post("/api/v1/sessions/does-not-exist/export")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "会话不存在"

    async def test_accept_both_prefers_json(self, client):
        """Accept 同时含 text/html 与 application/json → JSON 信封(优先级契约)。"""
        session = SessionRepository().create(title="双 Accept")
        resp = await client.post(
            f"/api/v1/sessions/{session.id}/export",
            headers={"Accept": "text/html, application/json"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "html" in resp.json()

    async def test_empty_body_defaults_theme(self, client):
        session = SessionRepository().create(title="空 body")
        resp = await client.post(f"/api/v1/sessions/{session.id}/export", json={})
        assert resp.status_code == 200
        assert resp.json()["theme"] == "auto"

    async def test_invalid_theme_normalized_at_route(self, client):
        session = SessionRepository().create(title="非法主题")
        resp = await client.post(
            f"/api/v1/sessions/{session.id}/export", json={"theme": "rainbow"}
        )
        assert resp.status_code == 200
        assert resp.json()["theme"] == "auto"

    async def test_content_disposition_carries_full_filename(self, client):
        session = SessionRepository().create(title="文件名")
        json_resp = await client.post(f"/api/v1/sessions/{session.id}/export")
        filename = json_resp.json()["filename"]

        html_resp = await client.post(
            f"/api/v1/sessions/{session.id}/export",
            headers={"Accept": "text/html"},
        )
        assert f'filename="{filename}"' in html_resp.headers["content-disposition"]

    async def test_html_body_equals_json_envelope_html(self, client):
        """HTML 直取体与 JSON 信封 html 同源(结构一致;exported_at 时戳允许不同)。"""
        session = SessionRepository().create(title="一致性")
        MessageRepository().save(_make_message(session.id, "user", "hello"))
        json_html = (await client.post(f"/api/v1/sessions/{session.id}/export")).json()["html"]
        html_body = (
            await client.post(
                f"/api/v1/sessions/{session.id}/export",
                headers={"Accept": "text/html"},
            )
        ).text

        json_payload = _extract_payload(json_html)
        body_payload = _extract_payload(html_body)
        # 剥掉时戳后,两者载荷逐字相同 → 同一渲染管线、同一模板
        json_payload.pop("exported_at", None)
        body_payload.pop("exported_at", None)
        assert body_payload == json_payload
        # 外壳(模板 + 内联资源)字节相同
        assert json_html[: json_html.index('type="application/json">')] == html_body[
            : html_body.index('type="application/json">')
        ]

    async def test_hostile_payload_roundtrips_via_base64_isolation(self, client):
        """核心承诺:恶意内容经 base64 隔离原样保留,且不污染外层 HTML 结构。"""
        hostile = '</script><img src=x onerror="alert(1)"><meta http-equiv="refresh" content="0;url=evil">'
        session = SessionRepository().create(title="注入隔离")
        MessageRepository().save(_make_message(session.id, "user", hostile))

        resp = await client.post(f"/api/v1/sessions/{session.id}/export")
        html_text = resp.json()["html"]

        # base64 字母表不含 <,故未编码的恶意结构在外层 0 命中;
        # 用 redirect 指令体(不含 <)精确证明 <meta refresh> 未泄漏进 <head>。
        assert html_text.count("<img src=x onerror") == 0
        assert html_text.count("</script><img") == 0
        assert html_text.count('content="0;url=evil"') == 0
        # 解码后载荷逐字还原(隔离不丢内容)  # noqa: ERA001 — 中文注释含括号，被 ruff 误判
        payload = _extract_payload(html_text)
        assert payload["entries"][0]["content"] == hostile
