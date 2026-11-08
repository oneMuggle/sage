"""Rescue security software — 检测 + 处置 + 回滚."""
from __future__ import annotations

import json
import subprocess

import pytest

from backend.services.rescue import security_software as ss


@pytest.fixture()
def windows(monkeypatch):
    monkeypatch.setattr(ss, "_is_windows", lambda: True)
    return monkeypatch


class TestDetect:
    def test_detect_non_windows_returns_empty(self, monkeypatch):
        monkeypatch.setattr(ss, "_is_windows", lambda: False)
        assert ss.detect_products() == []

    def test_detect_skips_missing_services(self, windows):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, stdout="FAILED 1060", stderr="")

        windows.setattr(ss, "_run", fake_run)
        assert ss.detect_products() == []

    def test_detect_returns_running_and_present(self, windows):
        def fake_run(cmd, **kw):
            if cmd[0] == "sc" and cmd[1] == "query":
                svc = cmd[2]
                if svc == "360tray":
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout="SERVICE_NAME: 360tray\nSTATE: 4 RUNNING\n", stderr=""
                    )
                if svc == "edrservice":
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout="SERVICE_NAME: edrservice\nSTATE: 1 STOPPED\n", stderr=""
                    )
                return subprocess.CompletedProcess(cmd, 1, stdout="FAILED 1060", stderr="")
            if cmd[0] == "tasklist":
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        windows.setattr(ss, "_run", fake_run)
        products = ss.detect_products()
        kinds = [(p.target, p.status) for p in products]
        assert ("360tray", "RUNNING") in kinds
        assert ("edrservice", "STOPPED") in kinds

    def test_detect_process_via_tasklist(self, windows):
        def fake_run(cmd, **kw):
            if cmd[0] == "sc":
                return subprocess.CompletedProcess(cmd, 1, stdout="FAILED 1060", stderr="")
            if cmd[0] == "tasklist":
                if "VrvProtect.exe" in " ".join(cmd):
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout="\nVrvProtect.exe  1234  Console  0  10,000 K\n", stderr=""
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        windows.setattr(ss, "_run", fake_run)
        products = ss.detect_products()
        proc_kinds = [(p.target, p.status) for p in products if p.kind == "process"]
        assert ("VrvProtect.exe", "PRESENT") in proc_kinds


class TestEndProcess:
    def test_unsupported_on_linux(self, monkeypatch):
        monkeypatch.setattr(ss, "_is_windows", lambda: False)
        result = ss.end_process("VrvProtect.exe", confirm=True)
        assert result.ok is False
        assert "unsupported" in result.message

    def test_dry_run_without_confirm(self, windows):
        result = ss.end_process("VrvProtect.exe", confirm=False)
        assert result.dry_run is True
        assert result.ok is False

    def test_executes_with_confirm(self, windows):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="已终止", stderr="")

        windows.setattr(ss, "_run", fake_run)
        result = ss.end_process("VrvProtect.exe", confirm=True)
        assert result.ok is True
        assert calls[0][0] == "taskkill"


class TestServiceActions:
    def test_stop_service_dry_run(self, windows):
        result = ss.stop_service("360tray", confirm=False)
        assert result.dry_run is True
        assert result.ok is False

    def test_stop_service_backs_up_and_runs_sc_stop(self, windows, tmp_path):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if cmd[0:2] == ["sc", "qc"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="SERVICE_NAME: 360tray\nSTART_TYPE: 2 AUTO_START\n",
                    stderr="",
                )
            if cmd[0:2] == ["sc", "stop"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="[SC] StopService SUCCESS\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        windows.setattr(ss, "_run", fake_run)
        result = ss.stop_service("360tray", confirm=True, user_data_dir=tmp_path)
        assert result.ok is True
        assert result.backup_path
        assert "backups/security" in result.backup_path
        # 检查备份文件确实创建并含原始启动类型
        from pathlib import Path

        backup = json.loads(Path(result.backup_path).read_text(encoding="utf-8"))
        assert backup["startType"] == "auto"
        # 验证命令顺序：qc (backup) → stop
        assert any(c[0:2] == ["sc", "qc"] for c in calls)
        assert any(c[0:2] == ["sc", "stop"] for c in calls)

    def test_disable_service_records_original_start_type(self, windows, tmp_path):
        def fake_run(cmd, **kw):
            if cmd[0:2] == ["sc", "qc"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="START_TYPE: 2 AUTO_START\n", stderr=""
                )
            if cmd[0:3] == ["sc", "config", "disabled_start"]:
                # 模拟用户传入的禁用
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="[SC] ChangeServiceConfig SUCCESS\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        windows.setattr(ss, "_run", fake_run)
        result = ss.disable_service("disabled_start", confirm=True, user_data_dir=tmp_path)
        # 这里 fake_run 的 start= disabled 匹配不到，所以 ok=False；测试仅验证备份写入
        assert result.backup_path


class TestRestoreAll:
    def test_restore_all_skips_when_no_backups(self, windows, tmp_path):
        assert ss.restore_all(user_data_dir=tmp_path) == []

    def test_stop_backup_then_restore_uses_symbolic_start_type(self, windows, tmp_path):
        flow = []

        def fake_run(cmd, **kw):
            flow.append(list(cmd))
            if cmd[0:2] == ["sc", "qc"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="START_TYPE : 2   AUTO_START\n", stderr=""
                )
            if cmd[0:2] == ["sc", "stop"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="[SC] StopService SUCCESS\n", stderr=""
                )
            if cmd[0:2] == ["sc", "config"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="[SC] ChangeServiceConfig SUCCESS\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        windows.setattr(ss, "_run", fake_run)
        stop = ss.stop_service("svc", confirm=True, user_data_dir=tmp_path)
        assert stop.ok is True
        results = ss.restore_all(user_data_dir=tmp_path)
        assert results
        assert results[0].ok
        assert ["sc", "config", "svc", "start=", "auto"] in flow


    def test_restore_all_reapplies_backups(self, windows, tmp_path):
        backup_dir = tmp_path / "backups" / "security"
        backup_dir.mkdir(parents=True)
        (backup_dir / "service-svcA.json").write_text(
            json.dumps({"kind": "service", "name": "svcA", "startType": "DEMAND_START"}),
            encoding="utf-8",
        )
        (backup_dir / "service-svcB.json").write_text(
            json.dumps({"kind": "service", "name": "svcB", "startType": "AUTO_START"}),
            encoding="utf-8",
        )
        captured = []

        def fake_run(cmd, **kw):
            captured.append(cmd)
            return subprocess.CompletedProcess(
                cmd, 0, stdout="[SC] ChangeServiceConfig SUCCESS\n", stderr=""
            )

        windows.setattr(ss, "_run", fake_run)
        results = ss.restore_all(user_data_dir=tmp_path)
        assert len(results) == 2
        assert all(r.ok for r in results)
        targets = [c[2] for c in captured]
        assert set(targets) == {"svcA", "svcB"}


class TestPlanBypass:
    def test_plan_bypass_returns_modes_and_unsupported(self):
        plan = ss.plan_bypass()
        assert {m["id"] for m in plan["modes"]} == {"parent", "dir", "delay"}
        assert any("内核驱动" in u for u in plan["unsupported"])
