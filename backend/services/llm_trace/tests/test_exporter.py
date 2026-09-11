"""Tests for exporter — manifest / system / config / README / trace.jsonl."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from backend.services.llm_trace.exporter import export_to_zip_bytes
from backend.services.llm_trace.recorder import TraceRecord


def _empty_record() -> TraceRecord:
    return TraceRecord(
        trace_id="t-empty",
        ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://internal-llm.example/v1/chat/completions",
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=200,
        response_headers={},
        response_body=b"{}",
        response_streamed=False,
        duration_ms=10,
    )


def _read_zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(data), "r")


def test_export_with_no_records_still_produces_zip() -> None:
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="llm:\n  base_url: x\n",
    )
    assert isinstance(out, bytes)
    assert len(out) > 0
    zf = _read_zip(out)
    names = set(zf.namelist())
    assert "manifest.json" in names
    assert "system.json" in names
    assert "config.yaml" in names
    assert "trace.jsonl" in names
    assert "README.txt" in names


def test_manifest_has_required_fields() -> None:
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["schema_version"] == "1"
    assert manifest["app_version"] == "0.4.9-alpha.28-win7"
    assert manifest["redactor_version"] == "1"
    assert manifest["trace_count"] == 0
    assert "generated_at" in manifest
    # 校验 ISO 8601
    datetime.fromisoformat(manifest["generated_at"].replace("Z", "+00:00"))


def test_system_json_includes_versions_excludes_hostname_by_default() -> None:
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    sys_info = json.loads(zf.read("system.json").decode("utf-8"))
    assert "os" in sys_info
    assert "python_version" in sys_info
    assert "app_version" in sys_info
    assert "hostname" not in sys_info  # 默认不含


def test_system_json_includes_hostname_when_opted_in() -> None:
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=True,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    sys_info = json.loads(zf.read("system.json").decode("utf-8"))
    assert "hostname" in sys_info
    assert isinstance(sys_info["hostname"], str)
    assert len(sys_info["hostname"]) > 0


def test_config_yaml_snapshot_present() -> None:
    cfg = "llm:\n  base_url: https://internal-llm.example/v1\n  api_key: sk-abc123def456ghi789jkl012\n"
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot=cfg,
    )
    zf = _read_zip(out)
    saved = zf.read("config.yaml").decode("utf-8")
    # config snapshot 走 redact_text 扫 secrets(匹配 openai_key pattern)
    assert "sk-abc123def456ghi789jkl012" not in saved
    assert "***REDACTED:openai_key***" in saved
    assert "llm:" in saved
    assert "base_url: https://internal-llm.example/v1" in saved


def test_readme_contains_human_readable_field_explanation() -> None:
    out = export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    readme = zf.read("README.txt").decode("utf-8")
    assert "manifest.json" in readme
    assert "trace.jsonl" in readme
    assert "system.json" in readme
    assert "config.yaml" in readme
    # 至少一段告诉支持人员怎么用
    assert len(readme) > 200


def test_trace_jsonl_is_valid_jsonl_with_one_line_per_record() -> None:
    records = [_empty_record(), _empty_record(), _empty_record()]
    out = export_to_zip_bytes(
        records=records,
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    lines = zf.read("trace.jsonl").decode("utf-8").strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert obj["trace_id"] == "t-empty"
