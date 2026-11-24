from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from backend.adapters.out.document_parse.mineru_errors import MineruRemoteError
from backend.adapters.out.document_parse.mineru_models import (
    build_create_body,
    parse_task_snapshot,
    unpack_result_payload,
)
from backend.domain.document_parse import MineruSettings, ParseRequest, ParseResult


def test_parse_request_extension_and_hash() -> None:
    req = ParseRequest(filename="论文.PDF", content_bytes=b"abc")
    assert req.extension == "pdf"
    assert req.content_hash() == hashlib.sha256(b"abc").hexdigest()


def test_with_warning_is_immutable() -> None:
    base = ParseResult(text="t", engine_used="local")
    bumped = base.with_warning("mineru_failed:timeout")
    assert base.warnings == []
    assert bumped.warnings == ["mineru_failed:timeout"]


def test_mineru_settings_configured_flag() -> None:
    assert MineruSettings().configured is False
    assert MineruSettings(base_url="http://10.0.0.8:8000").configured is True


def test_build_create_body_shape() -> None:
    body = build_create_body(
        filename="a.pdf",
        content=b"xyz",
        page_range="1-3",
        output_formats=["default"],
        tier="standard",
        ocr_mode=None,
    )
    assert body["files"][0]["file_name"] == "a.pdf"
    assert body["files"][0]["bytes"] == 3
    assert body["files"][0]["sha256sum"] == hashlib.sha256(b"xyz").hexdigest()
    assert body["files"][0]["page_range"] == "1-3"
    assert body["output_formats"] == ["default"]
    assert body["tier"] == "standard"
    assert "ocr_mode" not in body


def test_parse_task_snapshot_requires_identity() -> None:
    with pytest.raises(MineruRemoteError) as exc:
        parse_task_snapshot({"task_id": "", "status": "pending", "files": []})
    assert exc.value.code == "invalid_response"


def test_unpack_default_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("markdown.md", "# hi")
        zf.writestr("middle_json.json", json.dumps({"pages": []}))
        zf.writestr("images/a.png", b"png")
    out = unpack_result_payload(buf.getvalue(), ["default"], "completed")
    assert out.markdown == "# hi"
    assert out.structured == {"pages": []}
    assert out.images == {"images/a.png": b"png"}
    assert out.file_bytes is None


def test_unpack_bare_docx() -> None:
    out = unpack_result_payload(b"PKdocx", ["docx"], "completed")
    assert out.file_bytes == b"PKdocx"
    assert out.file_ext == "docx"
