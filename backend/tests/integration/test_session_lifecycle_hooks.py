"""Phase 2 会话生命周期钩子集成测试。

真实 HTTP 端点 (POST/DELETE /sessions) + 真实 shell 钩子:
1. POST /sessions → session_start 钩子收到 payload 并落盘
2. DELETE /sessions/{id} → session_stop 钩子触发
3. 未配置钩子 → 端点行为不变 (零开销旁路)
4. 钩子故障 → 端点仍成功 (fail-open)
"""

from __future__ import annotations

import json
import sys

import pytest

from backend.data.settings_repo import SettingsRepository

pytestmark = pytest.mark.integration

PY = sys.executable


def _install_hooks(hooks: list) -> None:
    SettingsRepository().set_json("hooks", hooks)


def _capture_hook_command(tmp_path, marker_name: str) -> str:
    """写一个把 payload 落盘到 marker 的钩子脚本, 返回 shell 命令。"""
    script = tmp_path / f"capture_{marker_name}.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "with open(sys.argv[1], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(payload) + '\\n')\n"
        "print(json.dumps({'decision': 'allow'}))\n",
        encoding="utf-8",
    )
    marker = tmp_path / marker_name
    return f"{PY} {script} {marker}"


def _read_marker(marker) -> list:
    if not marker.exists():
        return []
    return [json.loads(line) for line in marker.read_text(encoding="utf-8").strip().splitlines()]


@pytest.mark.asyncio()
async def test_create_session_fires_session_start_hook(client, tmp_path):
    cmd = _capture_hook_command(tmp_path, "start.jsonl")
    _install_hooks([{"event": "session_start", "matcher": "*", "command": cmd}])

    resp = await client.post("/api/v1/sessions", json={"title": "钩子测试会话"})
    assert resp.status_code == 200
    session_id = resp.json()["id"]

    recorded = _read_marker(tmp_path / "start.jsonl")
    assert recorded, "session_start hook should have fired"
    assert recorded[-1]["hook_event_name"] == "session_start"
    assert recorded[-1]["session_id"] == session_id


@pytest.mark.asyncio()
async def test_delete_session_fires_session_stop_hook(client, tmp_path):
    cmd = _capture_hook_command(tmp_path, "stop.jsonl")
    _install_hooks([{"event": "session_stop", "matcher": "*", "command": cmd}])

    created = await client.post("/api/v1/sessions", json={"title": "待删除"})
    session_id = created.json()["id"]

    resp = await client.delete(f"/api/v1/sessions/{session_id}")
    assert resp.status_code == 200

    recorded = _read_marker(tmp_path / "stop.jsonl")
    assert recorded, "session_stop hook should have fired"
    assert recorded[-1]["hook_event_name"] == "session_stop"
    assert recorded[-1]["session_id"] == session_id


@pytest.mark.asyncio()
async def test_session_crud_unaffected_without_hooks(client, tmp_path):
    """未配置钩子 → 会话 CRUD 完全不受影响。"""
    _install_hooks([])

    created = await client.post("/api/v1/sessions", json={"title": "无钩子"})
    assert created.status_code == 200
    session_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/sessions/{session_id}")
    assert deleted.status_code == 200


@pytest.mark.asyncio()
async def test_session_creation_fail_open_on_broken_hook(client, tmp_path):
    """钩子命令故障 → 会话创建仍然成功 (fail-open)。"""
    _install_hooks([{"event": "session_start", "matcher": "*", "command": "exit 9"}])

    resp = await client.post("/api/v1/sessions", json={"title": "钩子故障"})
    assert resp.status_code == 200
    assert resp.json()["id"]


@pytest.mark.asyncio()
async def test_delete_missing_session_still_404s_with_hook_configured(client, tmp_path):
    """钩子存在不影响删除不存在会话的 404 语义。"""
    _install_hooks([{"event": "session_stop", "matcher": "*", "command": "true"}])
    resp = await client.delete("/api/v1/sessions/does-not-exist")
    assert resp.status_code == 404
