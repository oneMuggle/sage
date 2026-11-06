# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M4-T4 — 黄金任务集评分器 + runner 抽象（spec §11）。

覆盖:

- ``load_golden_tasks()`` — 文件存在返回 10 条任务（5 模板 × 2）；
  文件缺失 / schema 非法抛 ValueError
- ``tasks_for_template()`` / ``all_template_ids()`` — 过滤与去重顺序保持
- ``template_id_from_agent_id()`` — 模板实例化 ``specialist-<tpl>-<6hex>``
  能提取；非模板专家（``user-*`` / ``custom-*``）返回 None
- ``_evaluate_check()`` — 6 种 kind 全部行为：
  - ``keywords_all``：全部命中通过；大小写不敏感
  - ``keywords_any``：任一命中通过
  - ``forbidden``：全部未命中通过（反向）
  - ``refusal``：无拒答模式通过；匹配中英文拒答失败
  - ``regex``：``re.search`` 匹配通过；非法 pattern 返回 False
  - ``max_chars``：长度 ≤ value 通过
  - 未知 kind → False
- ``evaluate_task()`` — 组合多检查；全过则 passed=True；任一失败则 False；
  tokens/tool_calls 缺省兜底；非 str output 强制转换
- ``aggregate_report()`` — 总/通过/失败/错误计数；按模板分桶；空输入 0.0 率
- ``run_golden_eval()`` — 注入假 runner 跑 10 个任务；task_ids 过滤；
  单任务异常不中断整体（记入 ``error``）；未知 task_id 被忽略
- ``new_run_id()`` — 32 hex uuid4 格式
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

import pytest

pytestmark = pytest.mark.unit


# =====================================================================
# 数据加载
# =====================================================================


class TestLoadGoldenTasks:
    def test_loads_ten_tasks_across_five_templates(self):
        from backend.services.specialist_golden_eval import (
            load_golden_tasks,
            tasks_for_template,
        )

        tasks = load_golden_tasks()
        assert len(tasks) == 10
        for tpl in ("writing", "research", "coding", "presentation", "office"):
            assert len(tasks_for_template(tpl, tasks)) == 2

    def test_each_task_has_required_fields(self):
        from backend.services.specialist_golden_eval import load_golden_tasks

        for task in load_golden_tasks():
            assert task["id"]
            assert task["template_id"]
            assert task["topic"]
            assert task["prompt"]
            assert isinstance(task["checks"], list)
            assert len(task["checks"]) >= 1
            for check in task["checks"]:
                assert check.get("kind") in {
                    "keywords_all",
                    "keywords_any",
                    "forbidden",
                    "refusal",
                    "regex",
                    "max_chars",
                }

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        from backend.services import specialist_golden_eval as mod

        monkeypatch.setattr(
            mod, "GOLDEN_TASKS_PATH", tmp_path / "missing.json"
        )
        with pytest.raises(ValueError, match="数据文件缺失"):
            mod.load_golden_tasks()

    def test_invalid_schema_raises(self, tmp_path, monkeypatch):
        from backend.services import specialist_golden_eval as mod

        bad = tmp_path / "bad.json"
        bad.write_text('{"no_tasks_key": true}', encoding="utf-8")
        monkeypatch.setattr(mod, "GOLDEN_TASKS_PATH", bad)
        with pytest.raises(ValueError, match="tasks 数组"):
            mod.load_golden_tasks()

    def test_corrupted_json_raises(self, tmp_path, monkeypatch):
        from backend.services import specialist_golden_eval as mod

        bad = tmp_path / "corrupt.json"
        bad.write_text('{"tasks": [', encoding="utf-8")
        monkeypatch.setattr(mod, "GOLDEN_TASKS_PATH", bad)
        with pytest.raises(ValueError, match="解析失败"):
            mod.load_golden_tasks()


class TestTasksForTemplate:
    def test_filters_by_template_id(self):
        from backend.services.specialist_golden_eval import tasks_for_template

        writing = tasks_for_template("writing")
        assert [t["id"] for t in writing] == [
            "writing-polish-ai-education",
            "writing-reply-customer-complaint",
        ]

    def test_unknown_template_returns_empty(self):
        from backend.services.specialist_golden_eval import tasks_for_template

        assert tasks_for_template("nonexistent") == []

    def test_all_template_ids_returns_unique_ordered(self):
        from backend.services.specialist_golden_eval import all_template_ids

        assert all_template_ids() == [
            "writing",
            "research",
            "coding",
            "presentation",
            "office",
        ]


# =====================================================================
# template_id_from_agent_id
# =====================================================================


class TestTemplateIdFromAgentId:
    def test_extracts_writing(self):
        from backend.services.specialist_golden_eval import template_id_from_agent_id

        assert template_id_from_agent_id("specialist-writing-abc123") == "writing"

    def test_extracts_research(self):
        from backend.services.specialist_golden_eval import template_id_from_agent_id

        assert (
            template_id_from_agent_id("specialist-research-deadbe") == "research"
        )

    def test_non_template_returns_none(self):
        from backend.services.specialist_golden_eval import template_id_from_agent_id

        assert template_id_from_agent_id("user-writer-abcdef") is None
        assert template_id_from_agent_id("custom-agent-xyz-abcdef") is None
        assert template_id_from_agent_id("") is None
        assert template_id_from_agent_id("specialist-writing") is None  # 缺 6hex
        # 7 hex 段（多 1 字符）不匹配 6hex 锚定
        assert template_id_from_agent_id("specialist-writing-abcdef1") is None
        # 大写 template 不匹配 [a-z]
        assert template_id_from_agent_id("specialist-WRITING-abcdef") is None
        assert template_id_from_agent_id(None) is None  # type: ignore[arg-type]


# =====================================================================
# _evaluate_check — 6 种 kind
# =====================================================================


class TestEvaluateCheck:
    def test_keywords_all_pass(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check(
            {"kind": "keywords_all", "value": ["教育", "AI"]},
            "教育是 AI 的核心方向",
        )

    def test_keywords_all_case_insensitive(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check(
            {"kind": "keywords_all", "value": ["React", "vue"]},
            "react vs Vue"
        )

    def test_keywords_all_fail_when_missing(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "keywords_all", "value": ["教育", "AI", "缺失"]},
            "教育是 AI 的方向",
        )

    def test_keywords_any_pass(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check(
            {"kind": "keywords_any", "value": ["抱歉", "理解", "歉意"]},
            "我们非常抱歉",
        )

    def test_keywords_any_fail_when_none(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "keywords_any", "value": ["抱歉", "歉意"]},
            "这是你的问题",
        )

    def test_forbidden_pass_when_absent(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check(
            {"kind": "forbidden", "value": ["不知道", "无法回答"]},
            "这里提供完整解答",
        )

    def test_forbidden_fail_when_present(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "forbidden", "value": ["不知道", "无法回答"]},
            "抱歉，我无法回答",
        )

    def test_refusal_pass_when_clean(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check({"kind": "refusal"}, "这里是详细解答")

    def test_refusal_fail_on_chinese_pattern(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "refusal"}, "抱歉，我无法回答这个问题"
        )

    def test_refusal_fail_on_english_pattern(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "refusal"},
            "Sorry, I cannot assist with that request",
        )

    def test_refusal_fail_on_as_ai_pattern(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "refusal"},
            "As an AI, I can't help with that",
        )

    def test_regex_pass(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check(
            {"kind": "regex", "pattern": r"class \w+LRU|class LRU"},
            "class LRUCache:",
        )

    def test_regex_fail(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "regex", "pattern": r"def get"}, "no match here"
        )

    def test_regex_invalid_pattern_returns_false(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check({"kind": "regex", "pattern": r"[unclosed"}, "x")

    def test_max_chars_pass(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert _evaluate_check({"kind": "max_chars", "value": 100}, "short")

    def test_max_chars_fail_when_too_long(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check(
            {"kind": "max_chars", "value": 3}, "toolong"
        )

    def test_unknown_kind_returns_false(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check({"kind": "bogus"}, "anything")

    def test_missing_kind_returns_false(self):
        from backend.services.specialist_golden_eval import _evaluate_check

        assert not _evaluate_check({"value": ["x"]}, "anything")


# =====================================================================
# evaluate_task
# =====================================================================


class TestEvaluateTask:
    def test_all_pass(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {
                "id": "t1",
                "template_id": "writing",
                "topic": "T",
                "checks": [
                    {"kind": "keywords_all", "value": ["教育", "AI"]},
                    {"kind": "forbidden", "value": ["无法"]},
                    {"kind": "refusal"},
                    {"kind": "max_chars", "value": 1000},
                ],
            },
            {"output": "教育是 AI 方向", "tokens": 42, "tool_calls": []},
        )
        assert res["passed"] is True
        assert res["task_id"] == "t1"
        assert res["template_id"] == "writing"
        assert res["tokens"] == 42
        assert res["output_length"] == len("教育是 AI 方向")
        assert all(c["passed"] for c in res["checks"])

    def test_any_fail_marks_task_failed(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {
                "id": "t2",
                "template_id": "writing",
                "topic": "T",
                "checks": [
                    {"kind": "forbidden", "value": ["无法回答"]},
                    {"kind": "refusal"},
                ],
            },
            {"output": "抱歉，我无法回答"},
        )
        assert res["passed"] is False
        failed_checks = [c for c in res["checks"] if not c["passed"]]
        assert len(failed_checks) >= 1

    def test_non_str_output_coerced(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {"id": "t", "template_id": "w", "topic": "T", "checks": [{"kind": "max_chars", "value": 100}]},
            {"output": 12345},
        )
        assert res["passed"] is True
        assert res["output_length"] == 5  # "12345"

    def test_missing_output_treated_as_empty(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {
                "id": "t",
                "template_id": "w",
                "topic": "T",
                "checks": [{"kind": "refusal"}],
            },
            {},
        )
        assert res["passed"] is True
        assert res["output_length"] == 0

    def test_missing_tokens_defaults_zero(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {"id": "t", "template_id": "w", "topic": "T", "checks": [{"kind": "refusal"}]},
            {"output": "hello"},
        )
        assert res["tokens"] == 0
        assert res["tool_calls"] == []

    def test_empty_checks_marks_task_not_passed(self):
        from backend.services.specialist_golden_eval import evaluate_task

        res = evaluate_task(
            {"id": "t", "template_id": "w", "topic": "T", "checks": []},
            {"output": "anything"},
        )
        assert res["passed"] is False


# =====================================================================
# aggregate_report
# =====================================================================


class TestAggregateReport:
    def test_counts_and_pass_rate(self):
        from backend.services.specialist_golden_eval import aggregate_report

        results = [
            {"passed": True, "tokens": 10, "template_id": "writing"},
            {"passed": True, "tokens": 20, "template_id": "writing"},
            {"passed": False, "tokens": 5, "template_id": "research"},
            {"passed": True, "tokens": 15, "template_id": "research"},
        ]
        agg = aggregate_report(results)
        assert agg["total_tasks"] == 4
        assert agg["passed"] == 3
        assert agg["failed"] == 1
        assert agg["errored"] == 0
        assert agg["pass_rate"] == 0.75
        assert agg["total_tokens"] == 50
        assert agg["by_template"]["writing"] == {
            "total": 2,
            "passed": 2,
            "tokens": 30,
            "pass_rate": 1.0,
        }
        assert agg["by_template"]["research"] == {
            "total": 2,
            "passed": 1,
            "tokens": 20,
            "pass_rate": 0.5,
        }

    def test_empty_input(self):
        from backend.services.specialist_golden_eval import aggregate_report

        agg = aggregate_report([])
        assert agg["total_tasks"] == 0
        assert agg["pass_rate"] == 0.0
        assert agg["by_template"] == {}

    def test_errored_counted_separately(self):
        from backend.services.specialist_golden_eval import aggregate_report

        results = [
            {"passed": True, "tokens": 0, "template_id": "w"},
            {"passed": False, "tokens": 0, "template_id": "w", "error": "boom"},
        ]
        agg = aggregate_report(results)
        assert agg["errored"] == 1
        assert agg["passed"] == 1
        assert agg["failed"] == 1


# =====================================================================
# run_golden_eval（注入假 runner）
# =====================================================================


class TestRunGoldenEval:
    @staticmethod
    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _fake_runner(self, output: str = "教育是 AI 应用，教学场景广泛。", tokens: int = 10):
        async def runner(profile: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
            return {"output": output, "tokens": tokens, "tool_calls": []}

        return runner

    def test_runs_all_ten_tasks_with_passing_fake_runner(self):
        from backend.services.specialist_golden_eval import run_golden_eval

        # fake runner 输出覆盖全部 10 个任务的 keywords_all/any/regex 且不含
        # 任何 forbidden 词、无拒答短语、长度远低于各任务 max_chars 上限。
        async def runner(profile, task):
            return {
                "output": (
                    "教育 AI 教学 React Vue Svelte 响应式 运行时\n"
                    "量子计算 密码 后量子 Shor\n"
                    "def get def put class LRUCache O(1) 时间复杂度\n"
                    "SELECT orders ROW_NUMBER\n"
                    "融资 产品 市场 增长 团队\n"
                    "大模型 代码审查 今天 议程 分享\n"
                    "远程 生产力 建议 数据\n"
                    "季度 销售 Excel 地区 销售人员 列 字段\n"
                    "理解 感谢 歉意"
                ),
                "tokens": 5,
                "tool_calls": [],
            }

        report = self._run(run_golden_eval({"id": "specialist-writing-abc123"}, runner=runner))
        assert report["total_tasks"] == 10
        assert report["passed"] == 10, [
            r for r in report["task_results"] if not r["passed"]
        ]
        assert report["pass_rate"] == 1.0
        assert report["total_tokens"] == 50
        assert "started_at" in report
        assert "finished_at" in report
        assert report["finished_at"] >= report["started_at"]

    def test_task_ids_filters_selection(self):
        from backend.services.specialist_golden_eval import run_golden_eval

        report = self._run(
            run_golden_eval(
                {"id": "x"},
                task_ids=["writing-polish-ai-education"],
                runner=self._fake_runner("教育是 AI 的重要应用"),
            )
        )
        assert report["total_tasks"] == 1
        assert report["task_results"][0]["task_id"] == "writing-polish-ai-education"

    def test_unknown_task_ids_ignored(self):
        from backend.services.specialist_golden_eval import run_golden_eval

        report = self._run(
            run_golden_eval(
                {"id": "x"},
                task_ids=["nonexistent-task"],
                runner=self._fake_runner(),
            )
        )
        assert report["total_tasks"] == 0

    def test_runner_exception_isolated_per_task(self):
        from backend.services.specialist_golden_eval import run_golden_eval

        call_count = {"n": 0}

        async def flaky_runner(profile, task):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient failure")
            # 满足 writing-reply-customer-complaint 的全部检查（含「理解」任意词命中）
            return {
                "output": "理解您的困扰，感谢您的耐心等待，我们会尽快处理。",
                "tokens": 1,
                "tool_calls": [],
            }

        report = self._run(
            run_golden_eval(
                {"id": "x"},
                task_ids=[
                    "writing-polish-ai-education",
                    "writing-reply-customer-complaint",
                ],
                runner=flaky_runner,
            )
        )
        assert report["total_tasks"] == 2
        assert report["errored"] == 1
        assert report["passed"] == 1  # 第二个通过
        errored = [r for r in report["task_results"] if r.get("error")]
        assert len(errored) == 1
        assert "transient failure" in errored[0]["error"]

    def test_no_selected_tasks_returns_empty_report_with_timestamps(self):
        from backend.services.specialist_golden_eval import run_golden_eval

        report = self._run(
            run_golden_eval(
                {"id": "x"},
                task_ids=["nonexistent"],
                runner=self._fake_runner(),
            )
        )
        assert report["total_tasks"] == 0
        assert "started_at" in report
        assert "finished_at" in report


# =====================================================================
# new_run_id
# =====================================================================


class TestNewRunId:
    def test_uuid4_hex_format(self):
        from backend.services.specialist_golden_eval import new_run_id

        rid = new_run_id()
        assert isinstance(rid, str)
        assert len(rid) == 32
        assert re.fullmatch(r"[0-9a-f]{32}", rid)

    def test_unique(self):
        from backend.services.specialist_golden_eval import new_run_id

        ids = {new_run_id() for _ in range(100)}
        assert len(ids) == 100
