"""SiteLoginJobs 单元测试：任务生命周期、并发去重、失败回传。"""

from __future__ import annotations

import threading
import time

import pytest

from backend.services.site_login_jobs import (
    FAILED,
    RUNNING,
    SUCCESS,
    SiteLoginJobs,
)

pytestmark = pytest.mark.unit


def _wait_terminal(jobs: SiteLoginJobs, job_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job and job["status"] in (SUCCESS, FAILED):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_job_success_and_result():
    jobs = SiteLoginJobs(runner=lambda url: {"ok": True, "saved_domains": [".cnki.net"]})
    job_id = jobs.start("https://kns.cnki.net/")
    job = _wait_terminal(jobs, job_id)
    assert job["status"] == SUCCESS
    assert job["result"]["saved_domains"] == [".cnki.net"]
    assert job["error"] is None


def test_job_failure_captures_error():
    jobs = SiteLoginJobs(runner=lambda url: {"ok": False, "error": "user cancelled"})
    job = _wait_terminal(jobs, jobs.start("https://example.com/"))
    assert job["status"] == FAILED
    assert job["error"] == "user cancelled"
    assert job["result"] is None


def test_runner_exception_becomes_failed_job():
    def boom(url):
        raise RuntimeError("browser missing")

    jobs = SiteLoginJobs(runner=boom)
    job = _wait_terminal(jobs, jobs.start("https://example.com/"))
    assert job["status"] == FAILED
    assert "browser missing" in job["error"]


def test_duplicate_start_reuses_active_job():
    gate = threading.Event()

    def slow(url):
        gate.wait(timeout=2.0)
        return {"ok": True, "saved_domains": []}

    jobs = SiteLoginJobs(runner=slow)
    first = jobs.start("https://a.example/")
    second = jobs.start("https://a.example/")
    assert first == second
    gate.set()
    assert _wait_terminal(jobs, first)["status"] == SUCCESS


def test_different_url_while_active_is_rejected():
    gate = threading.Event()

    def slow(url):
        gate.wait(timeout=2.0)
        return {"ok": True}

    jobs = SiteLoginJobs(runner=slow)
    jobs.start("https://a.example/")
    with pytest.raises(ValueError, match="login_in_progress"):
        jobs.start("https://b.example/")
    gate.set()


def test_start_rejects_blank_url():
    jobs = SiteLoginJobs(runner=lambda url: {"ok": True})
    with pytest.raises(ValueError, match="url"):
        jobs.start("  ")


def test_get_unknown_job_returns_none():
    jobs = SiteLoginJobs(runner=lambda url: {"ok": True})
    assert jobs.get("nope") is None


def test_status_is_running_while_runner_blocks():
    gate = threading.Event()

    def slow(url):
        gate.wait(timeout=2.0)
        return {"ok": True}

    jobs = SiteLoginJobs(runner=slow)
    job_id = jobs.start("https://a.example/")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job and job["status"] == RUNNING:
            break
        time.sleep(0.01)
    assert job["status"] == RUNNING
    gate.set()
    _wait_terminal(jobs, job_id)
