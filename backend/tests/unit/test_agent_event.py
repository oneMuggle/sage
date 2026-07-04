"""M1 结构化可观测性 — 事件信封域类型单测。

覆盖：
- ``envelope()`` 给任意事件加 ``schema`` + ``format_version`` 信封，保留 type/payload/ts。
- ``RunEventScope`` 分配稳定 run_id 且 seq 单调递增。
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


class _RecordingEvents:
    """最小 EventPort 假实现（记录 emit 调用），避免用 MagicMock。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


def test_envelope_adds_schema_and_format_version():
    out = envelope("tool_invoked", {"tool": "echo"}, ts="2026-07-04T00:00:00")
    assert out["schema"] == AGENT_EVENT_SCHEMA == "sage.agent.event"
    assert out["format_version"] == AGENT_EVENT_FORMAT_VERSION == 1
    assert out["type"] == "tool_invoked"
    assert out["payload"] == {"tool": "echo"}
    assert out["ts"] == "2026-07-04T00:00:00"


def test_envelope_preserves_provided_ts():
    # 领域层不读时钟；ts 由适配器边界传入并原样保留
    out = envelope("run_start", {}, ts="2026-07-04T12:34:56")
    assert out["ts"] == "2026-07-04T12:34:56"


def test_run_event_scope_seq_is_monotonic_and_run_id_stable():
    events = _RecordingEvents()
    scope = RunEventScope(events, run_id="run-xyz")

    s0 = scope.emit("run_start", model="gpt-x")
    s1 = scope.emit("turn_start")
    s2 = scope.emit("run_end", status="ok")

    assert (s0, s1, s2) == (0, 1, 2)
    assert scope.run_id == "run-xyz"
    # 每次 emit 都带 run_id + 单调 seq
    assert [p["seq"] for _, p in events.calls] == [0, 1, 2]
    assert {p["run_id"] for _, p in events.calls} == {"run-xyz"}
    assert events.calls[0] == ("run_start", {"run_id": "run-xyz", "seq": 0, "model": "gpt-x"})
