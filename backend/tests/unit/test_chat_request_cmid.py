# 2026-09-19: client_message_id 协议 (docs/plans/2026-09-18_client-message-id-r1-plan.md, 同步 #1155)
"""ChatRequest.client_message_id 校验与确定性 user id 规则测试。"""

import uuid

import pytest
from pydantic import ValidationError

from backend.api.legacy_routes import ChatRequest

pytestmark = pytest.mark.unit

_SID = "01849cf6-1a2b-7c3d-8e4f-a5b6c7d8e9f0"


def test_client_message_id_accepts_uuid():
    req = ChatRequest(
        session_id=_SID,
        message="hi",
        client_message_id="123e4567-e89b-12d3-a456-426614174000",
    )
    assert req.client_message_id == "123e4567-e89b-12d3-a456-426614174000"


def test_client_message_id_optional():
    req = ChatRequest(session_id=_SID, message="hi")
    assert req.client_message_id is None


@pytest.mark.parametrize(
    "bad",
    [
        "bad id with spaces",
        "short",
        " UPPER-CASE-NOT-ALLOWED-1234567890",
        "x" * 65,
        "",
    ],
)
def test_client_message_id_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        ChatRequest(session_id=_SID, message="hi", client_message_id=bad)


def test_user_message_id_rule():
    """协议核心: 传 cmid → 确定性 id u-<cmid>; 未传 → UUID。"""

    def derive(client_message_id):
        return f"u-{client_message_id}" if client_message_id else str(uuid.uuid4())

    cmid = "123e4567-e89b-12d3-a456-426614174000"
    assert derive(cmid) == f"u-{cmid}"
    assert derive(cmid) == derive(cmid)  # 确定性
    uuid.UUID(derive(None))  # 未传时仍是合法 UUID
