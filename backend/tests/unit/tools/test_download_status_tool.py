"""R129 — 后台下载任务查询/取消工具单元测试。

覆盖：download_status 单查（strip）/全查/空表 note/job_not_found；
download_cancel 成功与失败透出、job_id 空白容错；schema 契约。
manager 为 fake 单例（patch get_download_job_manager）。
"""

from __future__ import annotations

import pytest

from backend.tools import download_status_tool as dst
from backend.tools.download_status_tool import DownloadCancelTool, DownloadStatusTool

pytestmark = pytest.mark.unit


class _FakeManager:
    def __init__(self, status=None, jobs=None, cancel=None):
        self._status = status
        self.jobs = jobs or {}
        self.cancel_result = cancel

    def status(self, job_id):
        return self._status

    def all_jobs(self):
        return self.jobs

    def cancel(self, job_id):
        self.cancelled = job_id
        return self.cancel_result


@pytest.fixture()
def install(monkeypatch):
    def _install(manager):
        monkeypatch.setattr(dst, "get_download_job_manager", lambda: manager)
        return manager

    return _install


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_status_schema_contract():
    schema = DownloadStatusTool().schema
    assert schema.name == "download_status"
    assert schema.parameters["required"] == []


def test_cancel_schema_contract():
    schema = DownloadCancelTool().schema
    assert schema.name == "download_cancel"
    assert schema.parameters["required"] == ["job_id"]


# ---------------------------------------------------------------------------
# download_status
# ---------------------------------------------------------------------------


def test_status_single_job_found(install):
    job = {"id": "j1", "state": "done", "path": "x.zip"}
    install(_FakeManager(status=job))
    out = DownloadStatusTool().execute(job_id="j1")
    assert out.success is True
    assert out.content == job


def test_status_single_job_strips_whitespace(install):
    seen = {}

    class _RecordingManager(_FakeManager):
        def status(self, job_id):
            seen["arg"] = job_id
            return {"id": job_id}

    install(_RecordingManager(status={"id": "j9"}))
    DownloadStatusTool().execute(job_id="  j9  ")
    assert seen["arg"] == "j9"  # 实参 strip 后才传给 manager


def test_status_single_job_not_found(install):
    install(_FakeManager(status=None))
    out = DownloadStatusTool().execute(job_id="ghost")
    assert out.success is False
    assert "job_not_found" in out.error


def test_status_all_jobs(install):
    install(_FakeManager(jobs={"a": {"id": "a"}, "b": {"id": "b"}}))
    out = DownloadStatusTool().execute()
    assert out.success is True
    assert out.content == {"jobs": [{"id": "a"}, {"id": "b"}]}


def test_status_all_jobs_empty_note(install):
    install(_FakeManager(jobs={}))
    out = DownloadStatusTool().execute()
    assert out.success is True
    assert out.content["jobs"] == []
    assert "无后台下载任务" in out.content["note"]


# ---------------------------------------------------------------------------
# download_cancel
# ---------------------------------------------------------------------------


def test_cancel_success(install):
    manager = install(_FakeManager(cancel={"ok": True, "id": "j1"}))
    out = DownloadCancelTool().execute(job_id="j1")
    assert out.success is True
    assert out.content == {"ok": True, "id": "j1"}
    assert manager.cancelled == "j1"


def test_cancel_failure_maps_to_error(install):
    install(_FakeManager(cancel={"ok": False, "error": "not_pending"}))
    out = DownloadCancelTool().execute(job_id="running-job")
    assert out.success is False
    assert out.error == "not_pending"


def test_cancel_blank_job_id_still_routes(install):
    manager = install(_FakeManager(cancel={"ok": False, "error": "missing_id"}))
    out = DownloadCancelTool().execute(job_id="   ")
    assert manager.cancelled == ""  # strip 后为空串仍交给 manager 裁决
    assert out.success is False
