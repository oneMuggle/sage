"""Rescue support bundle — 生成 / 脱敏 / 内容完整性."""
from __future__ import annotations

import json
import zipfile

from backend.services.rescue import support_bundle as sb


def test_collect_bundle_manifest_and_redaction(tmp_path, monkeypatch):
    # 构造最小 userData 环境
    ud = tmp_path / "userData"
    ud.mkdir()
    diag = ud / "diagnostics"
    diag.mkdir()
    (diag / "crash-journal.jsonl").write_text(
        '{"ts":"2026-11-08T10:00:00Z","event":"test"}\n', encoding="utf-8"
    )
    (diag / "compat.json").write_text('{"schema":1,"level":0}', encoding="utf-8")
    (diag / "doctor-last.json").write_text('{"status":"ok"}', encoding="utf-8")
    logs = ud / "logs"
    logs.mkdir()
    (logs / "sage-2026-11-08.ndjson").write_text(
        '{"ts":"...","level":"info","msg":"hello"}\n', encoding="utf-8"
    )
    # 带 apiKey 的 sage.db
    import sqlite3

    db = ud / "sage.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT, value_type TEXT, category TEXT, created_at INTEGER, updated_at INTEGER)"
    )
    settings = {
        "version": 1,
        "endpoints": [
            {"id": "e1", "baseUrl": "http://x/v1", "apiKey": "sk-very-secret"}
        ],
        "modelSelections": {},
    }
    conn.execute(
        "INSERT INTO preferences(key,value,value_type,category,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("app_settings", json.dumps(settings), "json", "general", 0, 0),
    )
    conn.commit()
    conn.close()

    out = sb.collect_support_bundle(
        user_data_dir=ud,
        output_dir=tmp_path / "out",
        log_days=7,
    )
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "config-summary.json" in names
        assert "README.txt" in names
        assert "diagnostics/crash-journal.jsonl" in names
        assert "diagnostics/doctor-last.json" in names
        assert "logs/sage-2026-11-08.ndjson" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schema"] == 1
        assert manifest["system"]["hostname"] == "<redacted>"

        summary = json.loads(zf.read("config-summary.json"))
        ep = summary["endpoints"][0]
        assert "sk-very-secret" not in ep["apiKey"]


def test_collect_bundle_include_hostname(tmp_path):
    ud = tmp_path / "userData"
    ud.mkdir()
    out = sb.collect_support_bundle(
        user_data_dir=ud,
        output_dir=tmp_path / "out",
        include_hostname=True,
    )
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["system"]["hostname"] != "<redacted>"


def test_edr_snapshot_non_windows_is_empty(monkeypatch):
    monkeypatch.setattr(sb.platform, "system", lambda: "Linux")
    snap = sb._edr_snapshot()
    assert snap == {"av_products": [], "services": [], "errors": []}


def test_collect_bundle_doctor_report_included(tmp_path):
    ud = tmp_path / "userData"
    ud.mkdir()
    out = sb.collect_support_bundle(
        user_data_dir=ud,
        output_dir=tmp_path / "out",
        doctor_report={"status": "ok", "summary": {"critical": 0}},
    )
    with zipfile.ZipFile(out) as zf:
        assert "doctor.json" in zf.namelist()
        data = json.loads(zf.read("doctor.json"))
        assert data["status"] == "ok"
