# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""chat_stream_support 纯函数直测（T1，DSH 对标 R33）。

R31 迁出的支撑函数此前只有经 producer 的间接覆盖；本文件补齐纯函数
直测（memory_used 事件构造 / NDJSON / orchestr run 终态闭环降级 /
dispatcher 构造的 run_id 文案改写）。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.api import chat_stream_support as sup

pytestmark = pytest.mark.unit


# ---- _memory_used_event_from_hits ---------------------------------------------


def test_memory_used_empty_hits_returns_none():
    assert sup._memory_used_event_from_hits([], "s1") is None
    assert sup._memory_used_event_from_hits(None, "s1") is None


def test_memory_used_skips_non_dict_and_blank_preview():
    hits: Any = [
        "not-a-dict",
        {"preview": "   "},
        {"id": "m1", "memory_type": "episodic", "preview": "有效内容"},
    ]
    event = sup._memory_used_event_from_hits(hits, "s1")
    assert event is not None
    assert len(event["memories"]) == 1
    assert event["memories"][0]["id"] == "m1"


def test_memory_used_defaults_and_cap_five():
    hits = [{"preview": f"p{i}"} for i in range(8)]
    event = sup._memory_used_event_from_hits(hits, "s1")
    assert len(event["memories"]) == 5  # 每类总体截断 5 条
    first = event["memories"][0]
    assert first["memory_type"] == "memory"  # 缺省类型
    assert first["id"] == "p0"  # id 缺省回退 preview


def test_memory_used_event_shape():
    event = sup._memory_used_event_from_hits([{"id": "a", "preview": "x"}], "sess-9")
    assert event == {
        "state": "memory_used",
        "session_id": "sess-9",
        "memories": [{"id": "a", "memory_type": "memory", "preview": "x"}],
    }


# ---- _ndjson ------------------------------------------------------------------


def test_ndjson_appends_newline_and_keeps_unicode():
    line = sup._ndjson({"state": "delta", "text": "中文"})
    assert line.endswith("\n")
    assert "中文" in line  # ensure_ascii=False
    import json

    assert json.loads(line)["text"] == "中文"


# ---- _finalize_orch_run -------------------------------------------------------


def test_finalize_orch_run_none_run_id_is_noop(monkeypatch):
    called = []

    class _Repo:
        def finalize(self, *a):
            called.append(a)

    import backend.data.orch_run_repo as repo_mod

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _Repo)
    sup._finalize_orch_run(None, "done", "summary")  # 不应抛、不应调用
    assert called == []


def test_finalize_orch_run_degrades_on_failure(monkeypatch):
    import backend.data.orch_run_repo as repo_mod

    class _Repo:
        def finalize(self, *a):
            raise RuntimeError("db down")

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _Repo)
    sup._finalize_orch_run("r1", "done", "s")  # 降级：只 warning 不抛


def test_finalize_orch_run_calls_repo(monkeypatch):
    calls = []

    class _Repo:
        def finalize(self, run_id, status, summary):
            calls.append((run_id, status, summary))

    import backend.data.orch_run_repo as repo_mod

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _Repo)
    sup._finalize_orch_run("r1", "failed", "boom")
    assert calls == [("r1", "failed", "boom")]


# ---- _build_orchestration_dispatcher ------------------------------------------


def test_build_dispatcher_rewrites_invalid_run_id_message(monkeypatch):
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    def _boom(**kwargs):
        raise ValueError("非法 run_id: 'evil/../x'")

    monkeypatch.setattr(ChatDispatcher, "__init__", lambda self, **kw: _boom(**kw))
    with pytest.raises(ValueError, match="编排启动失败") as exc_info:
        sup._build_orchestration_dispatcher(
            stream_id="s1",
            entry_queue=None,
            run_id="evil/../x",
            llm_config=None,
            total_tasks=None,
            workspace_root=None,
        )
    msg = str(exc_info.value)
    assert "编排启动失败" in msg
    assert "请刷新后重试" in msg
    assert "evil/../x" in msg  # 原始信息保留


def test_build_dispatcher_passes_through_valid_run_id(monkeypatch):
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    captured: Dict[str, Any] = {}

    def _fake_init(self, **kwargs):
        captured.update(kwargs)
        self._fake = True

    monkeypatch.setattr(ChatDispatcher, "__init__", _fake_init)
    sup._build_orchestration_dispatcher(
        stream_id="s1",
        entry_queue="queue",
        run_id="orch-1",
        llm_config={"k": "v"},
        total_tasks=3,
        workspace_root="/ws",
        session_id="sess-1",
    )
    assert captured["run_id"] == "orch-1"
    assert captured["session_id"] == "sess-1"
    assert captured["total_tasks"] == 3
