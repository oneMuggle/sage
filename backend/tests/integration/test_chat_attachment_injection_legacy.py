"""/chat/stream 集成测试: Office 附件摘要注入 LLM system messages。

POST create 只返回 streamId, 因此测试 mock ``SageAgent.run_loop`` 并通过
GET attach 等待后台 producer 完成, 再断言 run_loop 实际收到的 messages。
"""

from __future__ import annotations

import threading
from typing import List
from unittest.mock import patch

import pytest

from backend.chat import attachment_resolver
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.office.errors import OfficePathError

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"
SESSION_ID = "attachment-injection-test"
ATTACHMENT_PROMPT_PREFIX = (
    "The user has referenced the following attached documents. "
    "Treat them as primary context for the user's request.\n\n"
)


@pytest.fixture()
def captured_run_loop_messages():
    """Capture the final messages passed from the route to SageAgent.run_loop."""
    calls: List[List[dict]] = []

    async def mock_run_loop(messages, **kwargs):
        calls.append([dict(message) for message in messages])
        yield AgentEvent(state=AgentState.THINKING, iteration=0)

    with patch("backend.api.legacy_routes.SageAgent") as mock_agent:
        mock_agent.return_value.run_loop = mock_run_loop
        yield calls


async def _run_chat_stream(client, captured_messages, message, workspace_path):
    create_response = await client.post(
        CHAT_STREAM_PATH,
        json={
            "session_id": SESSION_ID,
            "message": message,
            "workspace_path": workspace_path,
        },
    )
    assert create_response.status_code == 200, create_response.text

    stream_id = create_response.json()["streamId"]
    attach_response = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_response.status_code == 200, attach_response.text
    assert len(captured_messages) == 1
    return captured_messages[0]


def _attachment_messages(messages):
    return [
        message
        for message in messages
        if message.get("role") == "system" and "<attachments>" in (message.get("content") or "")
    ]


@pytest.mark.asyncio()
async def test_legacy_chat_stream_injects_pptx_digest(
    client, captured_run_loop_messages, monkeypatch, tmp_path
):
    """@foo.pptx reaches run_loop without blocking the event loop."""
    digest_calls = []
    digest_thread_ids = []
    route_thread_id = threading.get_ident()
    pptx_path = tmp_path / "x.pptx"
    pptx_path.touch()

    def fake_digest(path, workspace):
        digest_calls.append((path, workspace))
        digest_thread_ids.append(threading.get_ident())
        return "PPT_FAKE_DIGEST"

    monkeypatch.setattr(attachment_resolver, "_digest_ppt", fake_digest)

    messages = await _run_chat_stream(
        client,
        captured_run_loop_messages,
        f"看 @{pptx_path} 怎么样",
        str(tmp_path),
    )

    assert digest_calls == [(str(pptx_path.resolve()), str(tmp_path.resolve()))]
    assert digest_thread_ids
    assert all(thread_id != route_thread_id for thread_id in digest_thread_ids)
    assert _attachment_messages(messages) == [
        {
            "role": "system",
            "content": (
                f"{ATTACHMENT_PROMPT_PREFIX}<attachments>\n"
                "=== x.pptx ===\n"
                "PPT_FAKE_DIGEST\n"
                "</attachments>"
            ),
        }
    ]


@pytest.mark.asyncio()
async def test_legacy_chat_stream_no_mention_no_injection(
    client, captured_run_loop_messages, monkeypatch, tmp_path
):
    """A message without @ mentions calls process but adds no attachment prompt."""
    process_calls = []
    original_process = attachment_resolver.process

    def tracking_process(text, workspace):
        process_calls.append((text, workspace))
        return original_process(text, workspace)

    monkeypatch.setattr(attachment_resolver, "process", tracking_process)

    messages = await _run_chat_stream(
        client,
        captured_run_loop_messages,
        "hello world",
        str(tmp_path),
    )

    assert process_calls == [("hello world", str(tmp_path))]
    assert _attachment_messages(messages) == []


@pytest.mark.asyncio()
async def test_legacy_chat_stream_multi_doc_in_order(
    client, captured_run_loop_messages, monkeypatch, tmp_path
):
    """@a.pptx @b.docx produces one ordered attachment block."""
    pptx_path = tmp_path / "a.pptx"
    docx_path = tmp_path / "b.docx"
    pptx_path.touch()
    docx_path.touch()
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda path, workspace: "P")
    monkeypatch.setattr(attachment_resolver, "_digest_word", lambda path, workspace: "W")

    messages = await _run_chat_stream(
        client,
        captured_run_loop_messages,
        f"@{pptx_path} 然后 @{docx_path}",
        str(tmp_path),
    )

    attachment_messages = _attachment_messages(messages)
    assert len(attachment_messages) == 1
    content = attachment_messages[0]["content"]
    assert content.startswith(ATTACHMENT_PROMPT_PREFIX)
    assert content.index("=== a.pptx ===") < content.index("=== b.docx ===")
    assert "=== a.pptx ===\nP" in content
    assert "=== b.docx ===\nW" in content


@pytest.mark.asyncio()
async def test_legacy_chat_stream_silently_skips_failed_mention(
    client, captured_run_loop_messages, monkeypatch, tmp_path
):
    """Outside-workspace and failed mentions are skipped; a valid later one survives."""
    outside_path = tmp_path.parent / "outside.pptx"
    bad_path = tmp_path / "bad.pptx"
    good_path = tmp_path / "good.docx"
    outside_path.touch()
    bad_path.touch()
    good_path.touch()
    ppt_digest_calls = []

    def raise_path_error(path, workspace):
        ppt_digest_calls.append(path)
        raise OfficePathError("bad", file_path=None)

    monkeypatch.setattr(attachment_resolver, "_digest_ppt", raise_path_error)
    monkeypatch.setattr(attachment_resolver, "_digest_word", lambda path, workspace: "W")

    messages = await _run_chat_stream(
        client,
        captured_run_loop_messages,
        f"@{outside_path} 以及 @{bad_path} 但 @{good_path} 正常",
        str(tmp_path),
    )

    assert ppt_digest_calls == [str(bad_path.resolve())]
    attachment_messages = _attachment_messages(messages)
    assert len(attachment_messages) == 1
    content = attachment_messages[0]["content"]
    assert "outside.pptx" not in content
    assert "bad.pptx" not in content
    assert "=== good.docx ===\nW" in content
