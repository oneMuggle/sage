"""R155 — office_restore 还原工具单元测试。

覆盖：schema 契约、doc_id 校验、ToolExecutionContext 缺失、DB 失败、
service 异常与业务失败码透出、成功路径 self_check 合并与 N4 历史落库、
自检回读降级。全部协作者 monkeypatch，不触真实 DB/工作区。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.domain.risk import RiskClass
from backend.tools import office_restore_tool as ort
from backend.tools.office_restore_tool import OfficeRestoreTool

pytestmark = pytest.mark.unit


def _ctx(session_id="s1", gen=2):
    return SimpleNamespace(session_id=session_id, binding_generation=gen)


@pytest.fixture()
def patched(monkeypatch):
    state = {
        "service_result": {"success": True, "content": {"restored": "d1"}},
        "self_check": {"ok": True, "summary": "live=3"},
        "service_exc": None,
        "db_exc": None,
        "service_calls": [],
        "record_calls": [],
    }

    class _FakeConn:
        pass

    class _FakeService:
        def __init__(self, policy):
            state["service_policy"] = policy

        def restore(self, conn, session_id, gen, doc_id):
            if state["service_exc"]:
                raise state["service_exc"]
            state["service_calls"].append((conn, session_id, gen, doc_id))
            return state["service_result"]

    conn = _FakeConn()
    monkeypatch.setattr(ort, "get_database", lambda: SimpleNamespace(get_connection=lambda: conn))
    monkeypatch.setattr(
        ort, "current_tool_context", lambda: _ctx(session_id="s1", gen=2)
    )
    monkeypatch.setattr(ort, "OfficeToolService", _FakeService)
    monkeypatch.setattr(
        ort,
        "workspace_count_self_check",
        lambda conn, ctx, doc_id, kind: state["self_check"],
    )
    monkeypatch.setattr(
        ort,
        "record",
        lambda doc_id, op, ok, summary, conn=None: state["record_calls"].append(
            (doc_id, op, ok)
        ),
    )
    state["conn"] = conn
    state["ctx"] = _ctx()
    return state


def test_schema_contract():
    schema = OfficeRestoreTool().schema
    assert schema.name == "office_restore"
    assert schema.parameters["required"] == ["doc_id"]
    assert OfficeRestoreTool.risk == RiskClass.WRITE_LOCAL
    assert OfficeRestoreTool.requires_tool_context is True


@pytest.mark.parametrize("bad", [None, "", "   ", 123])
def test_doc_id_missing_or_blank_rejected(bad):
    out = OfficeRestoreTool().execute(doc_id=bad)
    assert out.success is False
    assert out.error == "doc_id_required"


def test_missing_tool_context_rejected(patched, monkeypatch):
    monkeypatch.setattr(ort, "current_tool_context", lambda: None)
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is False
    assert out.error == "missing_tool_context"


def test_context_without_session_id_rejected(patched, monkeypatch):
    monkeypatch.setattr(
        ort, "current_tool_context", lambda: SimpleNamespace(session_id="")
    )
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is False
    assert out.error == "missing_tool_context"


def test_db_failure_maps_to_document_not_found(patched, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ort, "get_database", boom)
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is False
    assert out.error == "document_not_found"


def test_service_exception_maps_to_restore_failed(patched):
    patched["service_exc"] = RuntimeError("boom")
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is False
    assert out.error == "restore_failed"


def test_service_business_failure_code_passthrough(patched):
    patched["service_result"] = {"success": False, "error": {"code": "already_live"}}
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is False
    assert out.error == "already_live"


def test_success_merges_self_check_and_records_history(patched):
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is True
    assert out.content["restored"] == "d1"  # service content 透传
    assert out.content["self_check"] == {"ok": True, "summary": "live=3"}
    assert patched["record_calls"] == [("d1", "restore", True)]
    conn, session_id, gen, doc_id = patched["service_calls"][0]
    assert (session_id, gen, doc_id) == ("s1", 2, "d1")


def test_self_check_failure_degrades_but_stays_success(patched, monkeypatch):
    # R7 回读 best-effort：回读失败时 helper 自吞并返回 {ok: False, error}，
    # 主结果保持 success 且不缺 self_check 键
    def broken_self_check(conn, ctx, doc_id, kind):
        return {"ok": False, "error": "readback failed"}

    monkeypatch.setattr(ort, "workspace_count_self_check", broken_self_check)
    out = OfficeRestoreTool().execute(doc_id="d1")
    assert out.success is True
    assert out.content["self_check"] == {"ok": False, "error": "readback failed"}
