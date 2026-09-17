"""会话消息副标题预览截断单测 (P0-4 UI 优化)。

验证 backend 批量返回 last_message_preview 时字符截断为 40 字符，
且正确过滤 system/tool 角色。
"""

import pytest
from sage_core import Message, Role

from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter


@pytest.mark.asyncio()
async def test_memory_adapter_preview_truncates_at_40_chars():
    adapter = MemoryStorageAdapter()
    sid = await adapter.create_session("测试会话")

    # 追加长消息 (>40 字符)
    long_text = "这是非常长的测试消息，用来验证后端副标题预览是否会被严格截断在四十个字符以内，防止侧边栏溢出变形。"
    assert len(long_text) > 40
    await adapter.append_message(sid, Message(role=Role.USER, content=long_text))

    sessions = await adapter.list_sessions()
    target = next((s for s in sessions if s["id"] == sid), None)
    assert target is not None
    preview = target.get("last_message_preview")
    assert preview is not None
    assert len(preview) == 40
    assert preview == long_text[:40]


@pytest.mark.asyncio()
async def test_memory_adapter_preview_ignores_system_and_tool_messages():
    adapter = MemoryStorageAdapter()
    sid = await adapter.create_session("测试角色过滤")

    await adapter.append_message(sid, Message(role=Role.USER, content="用户输入内容"))
    await adapter.append_message(sid, Message(role=Role.ASSISTANT, content="助手回复"))
    # 系统与工具消息不应覆盖 preview
    await adapter.append_message(sid, Message(role=Role.SYSTEM, content="系统消息忽略"))

    sessions = await adapter.list_sessions()
    target = next((s for s in sessions if s["id"] == sid), None)
    assert target is not None
    assert target.get("last_message_preview") == "助手回复"
