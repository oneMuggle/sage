"""A4 acceptance checks — unit tests.

Coverage:
- detect_check_commands: pytest.ini / pyproject[tool.pytest] / package+tsconfig
- normalize_configured_checks: list/str/garbage/limit
- run_acceptance_checks: diff-stat on git repo, skip on non-git/missing,
  timeout熔断, missing tool skip, configured-overrides-detection
- record_acceptance_event: metadata shape, recorder failure -> None
- review.compute_verdict: empty/fact/negative-evidence threshold
- submit_with_report(verdict=...): event metadata carries verdict
- executor Step 6.5 hook: success path records acceptance event (real DB),
  reviewer lanes skipped, acceptance_enabled=False skips
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile

import pytest

from backend.data.database import Database
from backend.data.orchestration_repo import (
    LaneEventRepository,
    LaneRepository,
    TaskRepository,
)
from backend.orchestration import acceptance
from backend.orchestration.acceptance import (
    AcceptanceReport,
    CheckResult,
    detect_check_commands,
    normalize_configured_checks,
    record_acceptance_event,
    run_acceptance_checks,
)
from backend.orchestration.events import EventRecorder, LaneEvent
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane
from backend.orchestration.report_schema import Assertion, AssertionType
from backend.orchestration.review import compute_verdict
from backend.orchestration.task_registry import TaskRegistry


def _git(*args: str, cwd: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        timeout=60,
        check=True,
    )


@pytest.fixture
def git_repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    _git("init", cwd=str(d))
    (d / "a.txt").write_text("v1", encoding="utf-8")
    _git("add", "a.txt", cwd=str(d))
    _git(
        "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-m", "init", cwd=str(d),
    )
    (d / "a.txt").write_text("v2", encoding="utf-8")
    return d


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    db = Database(db_path=tmp_path)
    db.init_db()
    yield db, tmp_path
    with contextlib.suppress(PermissionError):
        os.unlink(tmp_path)


@pytest.fixture
def registries(temp_db):
    db, _ = temp_db
    lane_repo = LaneRepository()
    lane_repo.db = db
    task_repo = TaskRepository()
    task_repo.db = db
    event_repo = LaneEventRepository()
    event_repo.db = db
    return {
        "lane_registry": LaneRegistry(repo=lane_repo),
        "task_registry": TaskRegistry(repo=task_repo),
        "event_repo": event_repo,
        "event_recorder": EventRecorder(repo=event_repo),
    }


# ============================================================================
# 探测与归一化（纯函数）
# ============================================================================


class TestDetection:
    def test_empty_dir_detects_nothing(self, tmp_path):
        assert detect_check_commands(tmp_path) == []

    def test_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        assert ("pytest", ["pytest", "-q"]) in detect_check_commands(tmp_path)

    def test_pyproject_tool_pytest(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\nq = true\n", encoding="utf-8"
        )
        assert ("pytest", ["pytest", "-q"]) in detect_check_commands(tmp_path)

    def test_pyproject_without_pytest_section(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        assert detect_check_commands(tmp_path) == []

    def test_tsc_needs_package_and_tsconfig(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert detect_check_commands(tmp_path) == []
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        assert ("tsc", ["npx", "tsc", "--noEmit"]) in detect_check_commands(tmp_path)


class TestNormalizeConfigured:
    def test_list_form(self):
        assert normalize_configured_checks([["pytest", "-q"]]) == [["pytest", "-q"]]

    def test_string_form_split(self):
        assert normalize_configured_checks(["pytest -q"]) == [["pytest", "-q"]]

    def test_garbage_ignored(self):
        assert normalize_configured_checks([None, 42, [], ["ok"], "  "]) == [["ok"]]

    def test_non_list_is_empty(self):
        assert normalize_configured_checks("pytest -q") == []
        assert normalize_configured_checks(None) == []

    def test_capped_at_five(self):
        raw = [["echo", str(i)] for i in range(9)]
        assert len(normalize_configured_checks(raw)) == 5


# ============================================================================
# run_acceptance_checks
# ============================================================================


class TestRunChecks:
    def test_no_workdir_skipped(self):
        report = run_acceptance_checks(None)
        assert report.all_passed is True
        assert report.checks[0].skipped is True

    def test_missing_workdir_skipped(self, tmp_path):
        report = run_acceptance_checks(str(tmp_path / "nope"))
        assert report.all_passed is True
        assert report.checks[0].skipped is True

    def test_diff_stat_sees_modification(self, git_repo):
        report = run_acceptance_checks(str(git_repo))
        diff = next(c for c in report.checks if c.name == "diff")
        assert diff.passed is True
        assert "a.txt" in diff.summary

    def test_diff_stat_clean_repo(self, git_repo):
        _git("checkout", "--", "a.txt", cwd=str(git_repo))
        report = run_acceptance_checks(str(git_repo))
        diff = next(c for c in report.checks if c.name == "diff")
        assert diff.passed is True
        assert "无文件变更" in diff.summary

    def test_non_git_dir_diff_skipped(self, tmp_path):
        report = run_acceptance_checks(str(tmp_path))
        diff = next(c for c in report.checks if c.name == "diff")
        assert diff.skipped is True

    def test_configured_command_runs(self, tmp_path):
        report = run_acceptance_checks(
            str(tmp_path),
            configured=[[sys.executable, "-c", "print('ok')"]],
        )
        assert report.all_passed is True
        assert any(c.passed and not c.skipped for c in report.checks)

    def test_configured_beats_detection(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        report = run_acceptance_checks(
            str(tmp_path),
            configured=[[sys.executable, "-c", "print('ok')"]],
        )
        names = [c.name for c in report.checks]
        assert "pytest" not in names  # 显式配置优先，不跑探测

    def test_failing_command(self, tmp_path):
        report = run_acceptance_checks(
            str(tmp_path),
            configured=[[sys.executable, "-c", "raise SystemExit(3)"]],
        )
        assert report.all_passed is False

    def test_timeout_melts_down(self, tmp_path):
        report = run_acceptance_checks(
            str(tmp_path),
            configured=[[sys.executable, "-c", "import time; time.sleep(30)"]],
            check_timeout_s=1,
        )
        assert report.all_passed is False
        assert any("超时" in c.summary for c in report.checks)

    def test_missing_tool_skipped(self, tmp_path):
        report = run_acceptance_checks(
            str(tmp_path),
            configured=[["definitely-missing-tool-xyz-123", "--x"]],
        )
        missing = next(c for c in report.checks if "missing-tool" in c.name)
        assert missing.skipped is True
        assert report.all_passed is True  # 跳过不算失败

    def test_report_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            acceptance, "_run_diff_stat",
            lambda cwd: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        report = run_acceptance_checks(str(tmp_path))
        assert report.all_passed is False
        assert report.checks[-1].name == "acceptance-runner"


# ============================================================================
# record_acceptance_event
# ============================================================================


class FakeRecorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls = []
        self.fail = fail

    def record(self, event, **kwargs):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((event, kwargs))
        return "evt-1"


def _lane(**kw):
    base = {"lane_id": "lane-1", "task_id": "task-1", "agent_id": "coder"}
    base.update(kw)
    return Lane(**base)


class TestRecordEvent:
    def test_metadata_shape(self):
        rec = FakeRecorder()
        report = AcceptanceReport(
            checks=[CheckResult(name="diff", passed=True, summary="s")]
        )
        eid = record_acceptance_event(rec, _lane(), report)
        assert eid == "evt-1"
        event, kw = rec.calls[0]
        assert event == LaneEvent.ACCEPTANCE_COMPLETED
        assert kw["lane_id"] == "lane-1"
        assert kw["metadata"]["all_passed"] is True
        assert kw["metadata"]["checks"][0]["name"] == "diff"

    def test_recorder_failure_returns_none(self):
        rec = FakeRecorder(fail=True)
        assert record_acceptance_event(rec, _lane(), AcceptanceReport()) is None


# ============================================================================
# verdict plumbing
# ============================================================================


def _assertions(*specs):
    return [
        Assertion(type=t, statement=s, confidence=c) for t, s, c in specs
    ]


class TestComputeVerdict:
    def test_empty_is_fail(self):
        assert compute_verdict([]) == "fail"

    def test_facts_only_is_pass(self):
        a = _assertions((AssertionType.FACT, "x", 0.9))
        assert compute_verdict(a) == "pass"

    def test_strong_negative_evidence_is_fail(self):
        a = _assertions((AssertionType.NEGATIVE_EVIDENCE, "x", 0.7))
        assert compute_verdict(a) == "fail"

    def test_weak_negative_evidence_is_pass(self):
        a = _assertions((AssertionType.NEGATIVE_EVIDENCE, "x", 0.69))
        assert compute_verdict(a) == "pass"


class TestSubmitVerdict:
    def test_verdict_in_event_metadata(self):
        from unittest.mock import MagicMock

        from backend.orchestration.executor import LaneExecutor

        recorder = MagicMock()
        ex = LaneExecutor(
            lane_registry=MagicMock(), task_registry=MagicMock(),
            event_recorder=recorder,
        )
        ex.submit_with_report(
            lane_id="lane-1", task_id="task-1", assertions=[],
            reviewer_id="reviewer", verdict="fail",
        )
        meta = recorder.record.call_args.kwargs["metadata"]
        assert meta["verdict"] == "fail"
        assert meta["assertion_count"] == 0

    def test_verdict_defaults_none(self):
        from unittest.mock import MagicMock

        from backend.orchestration.executor import LaneExecutor

        recorder = MagicMock()
        ex = LaneExecutor(
            lane_registry=MagicMock(), task_registry=MagicMock(),
            event_recorder=recorder,
        )
        ex.submit_with_report(lane_id="lane-1", task_id="task-1", assertions=[])
        meta = recorder.record.call_args.kwargs["metadata"]
        assert meta["verdict"] is None


# ============================================================================
# executor Step 6.5 hook (real DB)
# ============================================================================


def _make_task_and_lane(registries, worktree=None, agent_id="coder"):
    task = registries["task_registry"].create_task(
        name="t1", description="d", task_type="general"
    )
    lane = registries["lane_registry"].create_lane(task_id=task.task_id)
    lane.agent_id = agent_id
    if worktree is not None:
        lane.worktree = str(worktree)
    registries["lane_registry"].update_lane(lane)
    return task, lane


class TestExecutorHook:
    def test_success_records_acceptance_event(self, registries, git_repo):
        async def runner(task, agent_id):
            return {"ok": True}

        _, lane = _make_task_and_lane(registries, worktree=git_repo)
        ex = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )
        result = asyncio.run(ex.execute_lane(lane))
        assert result["status"] == "succeeded"
        events = registries["event_repo"].list_by_lane(lane.lane_id)
        acc = [e for e in events if e["event_type"] == "lane.acceptance.completed"]
        assert len(acc) == 1
        assert acc[0]["metadata"]["all_passed"] is True
        assert any(
            c["name"] == "diff" for c in acc[0]["metadata"]["checks"]
        )

    def test_reviewer_lane_skipped(self, registries):
        async def runner(task, agent_id):
            return {"output": "x"}

        _, lane = _make_task_and_lane(registries, agent_id="reviewer")
        ex = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )
        result = asyncio.run(ex.execute_lane(lane))
        assert result["status"] == "succeeded"
        events = registries["event_repo"].list_by_lane(lane.lane_id)
        assert not [e for e in events if e["event_type"] == "lane.acceptance.completed"]

    def test_disabled_flag_skips(self, registries, git_repo):
        async def runner(task, agent_id):
            return {"ok": True}

        _, lane = _make_task_and_lane(registries, worktree=git_repo)
        ex = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
            acceptance_enabled=False,
        )
        result = asyncio.run(ex.execute_lane(lane))
        assert result["status"] == "succeeded"
        events = registries["event_repo"].list_by_lane(lane.lane_id)
        assert not [e for e in events if e["event_type"] == "lane.acceptance.completed"]

    def test_acceptance_failure_keeps_lane_green(self, registries, tmp_path):
        async def runner(task, agent_id):
            return {"ok": True}

        _, lane = _make_task_and_lane(registries, worktree=tmp_path)
        lane.metadata["acceptance_checks"] = [
            [sys.executable, "-c", "raise SystemExit(1)"]
        ]
        registries["lane_registry"].update_lane(lane)
        ex = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )
        result = asyncio.run(ex.execute_lane(lane))
        assert result["status"] == "succeeded"  # 验收失败不翻转 lane
        events = registries["event_repo"].list_by_lane(lane.lane_id)
        acc = [e for e in events if e["event_type"] == "lane.acceptance.completed"]
        assert acc[0]["metadata"]["all_passed"] is False
