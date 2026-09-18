"""上下文分类明细估算 + provider 实报校准单元测试 (backend/chat/context_breakdown.py)。"""

from __future__ import annotations

from backend.chat.context_breakdown import (
    CATEGORY_ORDER,
    build_breakdown_snapshot,
    calibrate_breakdown,
    compute_context_breakdown,
)

_SKILLS_BLOCK = "<available-skills>\n- /demo：示例技能\n</available-skills>"


def _messages():
    return [
        {"role": "system", "content": "你是 Sage。" + _SKILLS_BLOCK},
        {"role": "user", "content": "第一问 " + "hello " * 40},
        {"role": "assistant", "content": "第一答", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "total 42 " * 20},
        {"role": "system", "content": "<environment>\n- 平台: Windows\n</environment>"},
        {"role": "user", "content": "本轮输入"},
    ]


_TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "执行命令",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}
]


class TestCompute:
    def test_buckets_cover_all_categories(self):
        breakdown = compute_context_breakdown(_messages(), _TOOLS)
        assert set(breakdown) == set(CATEGORY_ORDER)

    def test_skills_split_from_system_base(self):
        breakdown = compute_context_breakdown(_messages(), _TOOLS)
        assert breakdown["skills"] > 0
        assert breakdown["system"] > 0

    def test_tools_and_dynamic_and_current_input_counted(self):
        breakdown = compute_context_breakdown(_messages(), _TOOLS)
        assert breakdown["tools"] > 0
        assert breakdown["dynamic_context"] > 0  # 尾部 environment system 消息
        assert breakdown["current_input"] > 0

    def test_history_roles_split_and_tool_calls_included(self):
        """assistant 的 tool_calls 参数与 tool 结果都计入（旧口径漏算项）。"""
        with_calls = compute_context_breakdown(_messages(), _TOOLS)
        stripped = [dict(m) for m in _messages()]
        stripped[2].pop("tool_calls")
        without_calls = compute_context_breakdown(stripped, _TOOLS)
        assert with_calls["history_assistant"] > without_calls["history_assistant"]
        assert with_calls["history_tool"] > 0
        # 历史 user 与"最后一条 user"分开归桶
        assert with_calls["history_user"] > 0

    def test_multimodal_parts(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": [
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
            ]},
        ]
        breakdown = compute_context_breakdown(msgs, None)
        assert breakdown["current_input"] > 0  # 含图片固定常数 + 文本

    def test_no_user_message_keeps_current_input_zero(self):
        breakdown = compute_context_breakdown(
            [{"role": "system", "content": "s"}], None
        )
        assert breakdown["current_input"] == 0


class TestCalibrate:
    def test_sums_exactly_to_actual(self):
        est = {"tools": 100, "system": 50, "history_user": 33, "current_input": 17}
        out = calibrate_breakdown(est, 1000)
        assert sum(out.values()) == 1000
        # 等比放大且保持相对次序
        assert out["tools"] > out["system"] > out["history_user"] >= out["current_input"]

    def test_scale_down_also_exact(self):
        est = {"a": 500, "b": 500}
        out = calibrate_breakdown(est, 801)
        assert sum(out.values()) == 801
        assert sorted(out.values()) == [400, 401]

    def test_zero_estimates_passthrough(self):
        est = {"a": 0, "b": 0}
        assert calibrate_breakdown(est, 100) == {"a": 0, "b": 0}

    def test_non_positive_actual_passthrough(self):
        est = {"a": 10}
        assert calibrate_breakdown(est, 0) == est


class TestSnapshot:
    def test_calibrated_snapshot(self):
        snap = build_breakdown_snapshot(_messages(), _TOOLS, 4321)
        assert snap["calibrated"] is True
        assert snap["prompt_tokens"] == 4321
        assert sum(snap["categories"].values()) == 4321
        assert snap["estimated_total"] > 0

    def test_uncalibrated_snapshot_without_usage(self):
        snap = build_breakdown_snapshot(_messages(), _TOOLS, None)
        assert snap["calibrated"] is False
        assert snap["prompt_tokens"] is None
        assert sum(snap["categories"].values()) == snap["estimated_total"]


class TestMeasureReserve:
    def test_reserve_scales_with_content_and_output(self):
        from backend.chat.context_breakdown import (
            DEFAULT_OUTPUT_RESERVE_TOKENS,
            measure_request_reserve,
        )

        small = measure_request_reserve("短 system", user_content="短输入")
        big = measure_request_reserve(
            "长 system " + "x" * 4000,
            attachment_block="附件内容 " + "y" * 4000,
            trailing_system="<environment>平台</environment>",
            user_content="长输入 " + "z" * 2000,
            tools=_TOOLS,
        )
        assert big > small
        # 默认输出预留被计入
        bare = measure_request_reserve("s", output_reserve=0)
        assert bare < measure_request_reserve("s")
        assert DEFAULT_OUTPUT_RESERVE_TOKENS == 4096

    def test_images_counted_in_reserve(self):
        from backend.chat.context_breakdown import measure_request_reserve

        text_only = measure_request_reserve("s", user_content="看图")
        with_image = measure_request_reserve(
            "s",
            user_content=[
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
            ],
        )
        assert with_image > text_only


class TestTrackerPersistence:
    """record → usage_events 落库 → session_summary 透出的闭环。"""

    def _patch_db(self, monkeypatch):
        from backend.data import database as database_module

        test_db = database_module.Database(":memory:")
        test_db.init_db()
        monkeypatch.setattr(database_module, "_db", test_db)

    def test_breakdown_roundtrip_and_task_filter(self, monkeypatch):
        import time

        from backend.services.usage_tracker import UsageTracker, current_task_id

        self._patch_db(monkeypatch)
        tracker = UsageTracker()
        snap = build_breakdown_snapshot(_messages(), _TOOLS, 4321)

        tracker.record("gpt-4o", 4321, 10, session_id="s-bd", context_breakdown=snap)
        time.sleep(0.003)
        # 更晚的子任务行（task_id 归因）不得污染 last_request
        token = current_task_id.set("task-9")
        try:
            tracker.record("gpt-4o", 99999, 10, session_id="s-bd")
        finally:
            current_task_id.reset(token)

        last = tracker.last_request("s-bd")
        assert last["prompt_tokens"] == 4321  # 跳过 task_id 行
        assert last["context_breakdown"]["categories"]["tools"] > 0

        summary = tracker.session_summary("s-bd")
        assert summary["last_context_breakdown"]["calibrated"] is True
        assert summary["requests"] == 2  # 聚合仍含子任务行

    def test_breakdown_none_for_legacy_rows(self, monkeypatch):
        from backend.services.usage_tracker import UsageTracker

        self._patch_db(monkeypatch)
        tracker = UsageTracker()
        tracker.record("gpt-4o", 100, 5, session_id="s-old")
        assert tracker.last_request("s-old")["context_breakdown"] is None
