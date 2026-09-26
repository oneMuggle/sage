"""R137 — Agent 事件信封 + RunEventScope 单元测试。

覆盖：envelope 五键版本化形状与常量、payload 原样携带、RunEventScope
稳定 run_id、emit 自增 seq、payload 恒注入 run_id+seq、sink 记录完整
事件序列。
"""

from __future__ import annotations

import pytest

from backend.domain.agent_event import (
    AGENT_EVENT_FORMAT_VERSION,
    AGENT_EVENT_SCHEMA,
    RunEventScope,
    envelope,
)

pytestmark = pytest.mark.unit


class _RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


def test_envelope_shape_and_constants():
    out = envelope("tool_invoked", {"tool": "t"}, ts="2026-09-26T00:00:00Z")
    assert out == {
        "schema": AGENT_EVENT_SCHEMA,
        "format_version": AGENT_EVENT_FORMAT_VERSION,
        "ts": "2026-09-26T00:00:00Z",
        "type": "tool_invoked",
        "payload": {"tool": "t"},
    }
    assert AGENT_EVENT_SCHEMA == "sage.agent.event"
    assert AGENT_EVENT_FORMAT_VERSION == 1


def test_envelope_carries_payload_by_reference():
    payload = {"k": "v"}
    out = envelope("e", payload, ts="t")
    assert out["payload"] is payload  # 同一 dict，无隐藏拷贝


def test_envelope_requires_ts_keyword():
    with pytest.raises(TypeError):
        envelope("e", {}, "2026-09-26T00:00:00Z")  # ts 仅限关键字


# ---------------------------------------------------------------------------
# RunEventScope
# ---------------------------------------------------------------------------


def test_scope_run_id_stable():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "run-42")
    assert scope.run_id == "run-42"


def test_emit_returns_monotonic_seq():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "run-1")
    assert scope.emit("run_start") == 0
    assert scope.emit("llm_call") == 1
    assert scope.emit("run_end") == 2


def test_emit_payload_contains_run_id_and_seq():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "run-9")
    scope.emit("llm_call", model="gpt-x")
    etype, payload = sink.events[0]
    assert etype == "llm_call"
    assert payload == {"run_id": "run-9", "seq": 0, "model": "gpt-x"}


def test_emit_caller_data_shadows_reserved_keys():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "run-3")
    scope.emit("tool_result", run_id="spoof", seq=99)
    _, payload = sink.events[0]
    # 现实现 **data 展开在 run_id/seq 之后：调用方同名键会覆盖保留键。
    # 钉死该行为——若后续改为保留键不可覆盖，本测试当场报警。
    assert payload["run_id"] == "spoof"
    assert payload["seq"] == 99


def test_emit_without_extra_data_payload_minimal():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "r")
    scope.emit("turn_start")
    _, payload = sink.events[0]
    assert payload == {"run_id": "r", "seq": 0}


def test_sink_records_full_sequence():
    sink = _RecordingSink()
    scope = RunEventScope(sink, "run-7")
    scope.emit("run_start", status="begin")
    scope.emit("run_end", status="ok")
    assert [t for t, _ in sink.events] == ["run_start", "run_end"]
    assert [p["seq"] for _, p in sink.events] == [0, 1]
    assert sink.events[1][1]["status"] == "ok"
