"""Tests for exporter — manifest / system / config / README / trace.jsonl."""
from __future__ import annotations

import base64
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
    # app_version 必须用实际传入值,不能是 "unknown"
    assert sys_info["app_version"] == "0.4.9-alpha.28-win7"
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
    # README 应说明 trace.jsonl 是倒序
    assert "倒序" in readme or "最新" in readme
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


def test_trace_jsonl_reverse_chronological_order() -> None:
    """trace.jsonl 必须按时间倒序(最新在前),与 README 一致。"""
    records = [
        TraceRecord(
            trace_id="t-oldest",
            ts=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc),  # noqa: UP017
            endpoint="/api/v1/chat/completions",
            upstream_url="https://x/v1/chat/completions",
            upstream_method="POST",
            request_headers={},
            request_body=b"{}",
            response_status=200,
            response_headers={},
            response_body=b"{}",
            response_streamed=False,
            duration_ms=10,
        ),
        TraceRecord(
            trace_id="t-middle",
            ts=datetime(2026, 9, 11, 11, 0, 0, tzinfo=timezone.utc),  # noqa: UP017
            endpoint="/api/v1/chat/completions",
            upstream_url="https://x/v1/chat/completions",
            upstream_method="POST",
            request_headers={},
            request_body=b"{}",
            response_status=200,
            response_headers={},
            response_body=b"{}",
            response_streamed=False,
            duration_ms=10,
        ),
        TraceRecord(
            trace_id="t-newest",
            ts=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),  # noqa: UP017
            endpoint="/api/v1/chat/completions",
            upstream_url="https://x/v1/chat/completions",
            upstream_method="POST",
            request_headers={},
            request_body=b"{}",
            response_status=200,
            response_headers={},
            response_body=b"{}",
            response_streamed=False,
            duration_ms=10,
        ),
    ]
    out = export_to_zip_bytes(
        records=records,
        include_prompts=False,
        include_hostname=False,
        app_version="0.4.9-alpha.28-win7",
        config_snapshot="",
    )
    zf = _read_zip(out)
    lines = zf.read("trace.jsonl").decode("utf-8").strip().split("\n")
    ids = [json.loads(line)["trace_id"] for line in lines]
    # 最新在前
    assert ids == ["t-newest", "t-middle", "t-oldest"]


def test_serialize_json_response_body_in_body_text() -> None:
    """JSON 响应体应序列化回字符串出现在 body_text,不应是 null。"""
    rec = TraceRecord(
        trace_id="t-json-resp",
        ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://x/v1/chat/completions",
        upstream_method="POST",
        request_headers={},
        request_body=b'{"model":"gpt-4","messages":[]}',
        response_status=200,
        response_headers={},
        response_body=b'{"choices":[{"message":{"content":"hi"}}]}',
        response_streamed=False,
        duration_ms=10,
    )
    out = export_to_zip_bytes(
        records=[rec],
        include_prompts=False,
        include_hostname=False,
        app_version="x",
        config_snapshot="",
    )
    zf = _read_zip(out)
    line = zf.read("trace.jsonl").decode("utf-8").strip()
    obj = json.loads(line)
    # body_text 必须有内容(JSON 字符串),不能是 null
    assert obj["response"]["body_text"] is not None
    parsed = json.loads(obj["response"]["body_text"])
    assert "choices" in parsed
    assert obj["response"]["body_encoding"] == "utf-8"
    # request body 也是 JSON,同样应出现在 body_json
    assert obj["request"]["body_json"] is not None


def test_serialize_binary_response_body_as_base64() -> None:
    """非 UTF-8 响应体应 base64 编码,body_encoding=base64。"""
    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00"
    rec = TraceRecord(
        trace_id="t-binary-resp",
        ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://x/v1/chat/completions",
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=200,
        response_headers={},
        response_body=binary_data,
        response_streamed=False,
        duration_ms=10,
    )
    out = export_to_zip_bytes(
        records=[rec],
        include_prompts=False,
        include_hostname=False,
        app_version="x",
        config_snapshot="",
    )
    zf = _read_zip(out)
    line = zf.read("trace.jsonl").decode("utf-8").strip()
    obj = json.loads(line)
    assert obj["response"]["body_encoding"] == "base64"
    assert obj["response"]["body_b64"] is not None
    # base64 可还原为原 bytes
    decoded = base64.b64decode(obj["response"]["body_b64"])
    assert decoded == binary_data


def test_extract_error_message_from_json_error_field() -> None:
    """上游 4xx 响应含 {"error":{"message":"..."}} 时,response.error 应提取该消息。"""
    rec = TraceRecord(
        trace_id="t-err",
        ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://x/v1/chat/completions",
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=401,
        response_headers={},
        response_body=b'{"error":{"message":"Invalid API key provided"}}',
        response_streamed=False,
        duration_ms=10,
    )
    out = export_to_zip_bytes(
        records=[rec],
        include_prompts=False,
        include_hostname=False,
        app_version="x",
        config_snapshot="",
    )
    zf = _read_zip(out)
    line = zf.read("trace.jsonl").decode("utf-8").strip()
    obj = json.loads(line)
    assert obj["response"]["error"] == "Invalid API key provided"


def test_extract_error_message_redacts_non_string_message() -> None:
    """当 error.message 是嵌套 dict(非 str),应 JSON 序列化后脱敏,不泄露结构化数据。"""
    # error.message 是个 dict 而不是 str → 必须 JSON 序列化 + redact_text
    # 内含 OpenAI 格式 key,redact_text 会脱敏
    body = json.dumps({
        "error": {"message": {"detail": "key=sk-abc123def456ghi789jkl012"}},
    }).encode("utf-8")
    rec = TraceRecord(
        trace_id="t-nested-err",
        ts=datetime.now(timezone.utc),  # noqa: UP017
        endpoint="/api/v1/chat/completions",
        upstream_url="https://x/v1/chat/completions",
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=500,
        response_headers={},
        response_body=body,
        response_streamed=False,
        duration_ms=10,
    )
    out = export_to_zip_bytes(
        records=[rec],
        include_prompts=False,
        include_hostname=False,
        app_version="x",
        config_snapshot="",
    )
    zf = _read_zip(out)
    line = zf.read("trace.jsonl").decode("utf-8").strip()
    obj = json.loads(line)
    err_msg = obj["response"]["error"]
    # error 字段是 str(不是 dict),且不含原始 key
    assert isinstance(err_msg, str)
    assert "sk-abc123def456ghi789jkl012" not in err_msg
    assert "***REDACTED:openai_key***" in err_msg
