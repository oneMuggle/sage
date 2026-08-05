"""Important-2 (final review) — the memory_retrieval preference must be
independent of auto_memory.

The Settings UI's "记忆检索注入" toggle now drives GET/PUT
``/api/v1/preferences/memory_retrieval`` (a new whitelisted key) instead of
sharing the ``auto_memory`` key with "自动记忆沉淀". This test proves over
the real HTTP route that toggling one preference leaves the other untouched.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PREF_AUTO = "/api/v1/preferences/auto_memory"
PREF_RETR = "/api/v1/preferences/memory_retrieval"


@pytest.mark.asyncio()
async def test_set_memory_retrieval_does_not_touch_auto_memory(client):
    """PUT memory_retrieval=false must NOT change the auto_memory value."""
    put_auto = await client.put(PREF_AUTO, json={"value": "true"})
    assert put_auto.status_code == 200, put_auto.text

    put_retr = await client.put(PREF_RETR, json={"value": "false"})
    assert put_retr.status_code == 200, put_retr.text

    get_auto = await client.get(PREF_AUTO)
    assert get_auto.status_code == 200, get_auto.text
    assert get_auto.json()["value"] == "true", (
        "auto_memory must be unchanged by memory_retrieval toggle"
    )

    get_retr = await client.get(PREF_RETR)
    assert get_retr.status_code == 200, get_retr.text
    assert get_retr.json()["value"] == "false"


@pytest.mark.asyncio()
async def test_set_auto_memory_does_not_touch_memory_retrieval(client):
    """PUT auto_memory=false must NOT change the memory_retrieval value."""
    put_retr = await client.put(PREF_RETR, json={"value": "true"})
    assert put_retr.status_code == 200, put_retr.text

    put_auto = await client.put(PREF_AUTO, json={"value": "false"})
    assert put_auto.status_code == 200, put_auto.text

    get_retr = await client.get(PREF_RETR)
    assert get_retr.status_code == 200, get_retr.text
    assert get_retr.json()["value"] == "true", (
        "memory_retrieval must be unchanged by auto_memory toggle"
    )

    get_auto = await client.get(PREF_AUTO)
    assert get_auto.status_code == 200, get_auto.text
    assert get_auto.json()["value"] == "false"


@pytest.mark.asyncio()
async def test_memory_retrieval_pref_defaults_null(client):
    """Unset memory_retrieval reads back null (renderer defaults to True)."""
    resp = await client.get(PREF_RETR)
    assert resp.status_code == 200, resp.text
    assert resp.json()["value"] is None
