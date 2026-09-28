"""R180 — 聊天流支撑函数（chat_stream_support）单元测试。

覆盖：_finalize_orch_run（降级闭环）、_build_orchestration_dispatcher
（ValueError 重抛为中文）、_validate_chat_images（数量/格式/大小/解码
全路径）、_memory_used_event_from_hits（截断/空值过滤）、
_clear_working_segment（None agent 跳过）、_ndjson 序列化。
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from backend.api.chat_stream_support import (
    _build_orchestration_dispatcher,
    _clear_working_segment,
    _finalize_orch_run,
    _memory_used_event_from_hits,
    _ndjson,
    _validate_chat_images,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _finalize_orch_run
# ---------------------------------------------------------------------------


def test_finalize_orch_run_none_skips(monkeypatch):
    called = []
    import backend.data.orch_run_repo as repo_mod

    class _FakeRepo:
        def finalize(self, run_id, status, summary):
            called.append((run_id, status, summary))

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _FakeRepo)
    _finalize_orch_run(None, "completed", "done")
    assert called == []  # run_id=None 直接跳过


def test_finalize_orch_run_calls_repo(monkeypatch):
    called = []
    import backend.data.orch_run_repo as repo_mod

    class _FakeRepo:
        def finalize(self, run_id, status, summary):
            called.append((run_id, status, summary))

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _FakeRepo)
    _finalize_orch_run("run-1", "completed", "done")
    assert called == [("run-1", "completed", "done")]


def test_finalize_orch_run_swallows_exceptions(monkeypatch):
    import backend.data.orch_run_repo as repo_mod

    class _Boom:
        def finalize(self, *a):
            raise RuntimeError("db down")

    monkeypatch.setattr(repo_mod, "OrchRunRepository", _Boom)
    _finalize_orch_run("run-1", "failed", "err")  # 不抛错即通过


# ---------------------------------------------------------------------------
# _build_orchestration_dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_invalid_run_id_raises_readable():
    with pytest.raises(ValueError, match="run_id 格式非法"):
        _build_orchestration_dispatcher(
            stream_id="s1",
            entry_queue=None,
            run_id="../path/traversal",
            llm_config=None,
            total_tasks=None,
            workspace_root=None,
        )


def test_dispatcher_valid_run_id_succeeds(monkeypatch):
    from unittest.mock import patch

    fake_dispatcher = SimpleNamespace(name="fake")
    with patch(
        "backend.api.chat_stream_support.ChatDispatcher",
        return_value=fake_dispatcher,
    ):
        out = _build_orchestration_dispatcher(
            stream_id="s1",
            entry_queue=None,
            run_id="orch-abc123",
            llm_config=None,
            total_tasks=3,
            workspace_root=None,
        )
    assert out is fake_dispatcher


# ---------------------------------------------------------------------------
# _validate_chat_images
# ---------------------------------------------------------------------------


def _img(mime="image/png", data="aGVsbG8="):
    return f"data:{mime};base64,{data}"


def test_validate_empty_images_ok():
    assert _validate_chat_images([]) is None


def test_validate_single_valid_png():
    assert _validate_chat_images([_img("image/png")]) is None


def test_validate_valid_jpeg_webp_gif():
    for mime in ("image/jpeg", "image/webp", "image/gif"):
        assert _validate_chat_images([_img(mime)]) is None


def test_validate_over_count_limit():
    images = [_img() for _ in range(5)]
    error = _validate_chat_images(images)
    assert error is not None
    assert "超过上限 4" in error


def test_validate_exactly_four_ok():
    images = [_img() for _ in range(4)]
    assert _validate_chat_images(images) is None


def test_validate_non_string_rejected():
    error = _validate_chat_images([123])
    assert "不是合法的图片 data URL" in error


def test_validate_bad_prefix_rejected():
    error = _validate_chat_images(["data:text/html;base64,abc"])
    assert "不是合法的图片 data URL" in error


def test_validate_missing_base64_payload_rejected():
    error = _validate_chat_images(["data:image/png;base64,"])
    assert "缺少 base64 数据段" in error


def test_validate_invalid_base64_rejected():
    error = _validate_chat_images(["data:image/png;base64,!!!not-base64!!!"])
    assert "base64 解码失败" in error


def test_validate_oversized_image_rejected():
    # 6 MiB payload > 5 MiB limit
    big_data = base64.b64encode(b"\x00" * (6 * 1024 * 1024)).decode()
    error = _validate_chat_images([_img("image/png", data=big_data)])
    assert "超过单张上限" in error


def test_validate_valid_size_at_boundary():
    # 恰好 5 MiB 不超限
    data = base64.b64encode(b"\x00" * (5 * 1024 * 1024)).decode()
    assert _validate_chat_images([_img("image/png", data=data)]) is None


# ---------------------------------------------------------------------------
# _memory_used_event_from_hits
# ---------------------------------------------------------------------------


def test_memory_used_empty_hits_returns_none():
    assert _memory_used_event_from_hits([], "s1") is None
    assert _memory_used_event_from_hits(None, "s1") is None


def test_memory_used_normal_hit():
    hits = [{"id": "m1", "memory_type": "semantic", "preview": "用户喜欢火锅"}]
    out = _memory_used_event_from_hits(hits, "s1")
    assert out["state"] == "memory_used"
    assert out["session_id"] == "s1"
    assert out["memories"] == [
        {"id": "m1", "memory_type": "semantic", "preview": "用户喜欢火锅"}
    ]


def test_memory_used_truncates_at_five():
    hits = [{"id": f"m{i}", "memory_type": "episodic", "preview": f"p{i}"} for i in range(8)]
    out = _memory_used_event_from_hits(hits, "s1")
    assert len(out["memories"]) == 5


def test_memory_used_non_dict_skipped():
    out = _memory_used_event_from_hits(["not-dict", 42], "s1")
    assert out is None


def test_memory_used_empty_preview_skipped():
    hits = [{"id": "m1", "preview": ""}, {"id": "m2", "preview": "  "}]
    out = _memory_used_event_from_hits(hits, "s1")
    assert out is None


def test_memory_used_missing_id_falls_back_to_preview():
    hits = [{"preview": "some text"}]
    out = _memory_used_event_from_hits(hits, "s1")
    assert out["memories"][0]["id"] == "some text"


# ---------------------------------------------------------------------------
# _clear_working_segment
# ---------------------------------------------------------------------------


def test_clear_working_segment_delegates():
    cleared = []
    mm = SimpleNamespace(
        working=SimpleNamespace(
            clear_segment=lambda sid, seg: cleared.append((sid, seg))
        )
    )
    agent = SimpleNamespace(memory_manager=mm)
    _clear_working_segment(agent, "s1", 2)
    assert cleared == [("s1", 2)]


def test_clear_working_segment_none_agent_skips():
    agent = SimpleNamespace(memory_manager=None)
    _clear_working_segment(agent, "s1", 0)  # 不抛错


# ---------------------------------------------------------------------------
# _ndjson
# ---------------------------------------------------------------------------


def test_ndjson_appends_newline():
    out = _ndjson({"key": "value"})
    assert out.endswith("\n")
    assert json.loads(out) == {"key": "value"}


def test_ndjson_unicode_not_escaped():
    out = _ndjson({"msg": "中文"})
    assert "中文" in out  # ensure_ascii=False
