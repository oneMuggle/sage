from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.office.models import PdfGenerateResult

_AUTH_HEADERS = {"Authorization": "Bearer test-local-auth-token"}


def _client() -> TestClient:
    from backend.main import app

    return TestClient(app, headers=_AUTH_HEADERS)


def _make_output(workspace: Path, kind: str, doc_id: str, name: str, data: bytes) -> Path:
    out = workspace / "office" / kind / doc_id / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def test_generate_nl_word_happy_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake = _make_output(workspace, "word", "abc123", "Test.docx", b"fake docx")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "Test", "paragraphs": [{"text": "Hello"}]}'

    with (
        patch(
            "backend.api.office_generate_routes.build_llm_client_from_settings",
            return_value=llm,
        ),
        patch("backend.api.office_generate_routes.generate_docx", return_value=fake) as mock_gen,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "写一份测试文档",
                "doc_type": "word",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "Test.docx"
    assert data["output_path"] == str(fake)
    assert data["file_size_bytes"] == len(b"fake docx")
    assert data["summary"]["id"] == "abc123"
    assert data["summary"]["doc_type"] == "word"
    assert data["summary"]["generated_filename"] == "Test.docx"
    assert data["summary"]["workspace_path"] == str(workspace.resolve())

    request = mock_gen.call_args.args[0]
    assert request.workspace_path == str(workspace.resolve())
    assert request.filename == "Test.docx"
    assert request.title == "Test"


def test_generate_nl_pdf_uses_result_output_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake = _make_output(workspace, "pdf", "pdf123", "generated.pdf", b"%PDF-1.4")

    llm = AsyncMock()
    llm.complete.return_value = '{"pages": [{"title": "P1", "paragraphs": ["hi"]}]}'
    pdf_result = PdfGenerateResult(
        output_path=str(fake),
        filename="generated.pdf",
        file_size_bytes=8,
        page_count=1,
    )

    with (
        patch(
            "backend.api.office_generate_routes.build_llm_client_from_settings",
            return_value=llm,
        ),
        patch("backend.api.office_generate_routes.generate_pdf", return_value=pdf_result),
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "生成一页 PDF",
                "doc_type": "pdf",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "generated.pdf"
    assert data["summary"]["doc_type"] == "pdf"
    assert data["summary"]["id"] == "pdf123"


def test_generate_nl_sanitizes_unsafe_title(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake = _make_output(workspace, "word", "abc123", "etc_passwd.docx", b"x")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "../../etc/passwd", "paragraphs": [{"text": "b"}]}'

    with (
        patch(
            "backend.api.office_generate_routes.build_llm_client_from_settings",
            return_value=llm,
        ),
        patch("backend.api.office_generate_routes.generate_docx", return_value=fake) as mock_gen,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "x",
                "doc_type": "word",
            },
        )

    assert resp.status_code == 200, resp.text
    filename = mock_gen.call_args.args[0].filename
    assert filename == "etc_passwd.docx"
    assert "/" not in filename
    assert "\\" not in filename
    assert ".." not in filename


def test_generate_nl_embeds_reference_text(tmp_path: Path) -> None:
    from docx import Document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    ref = workspace / "ref.docx"
    doc = Document()
    doc.add_paragraph("上周完成了功能A")
    doc.save(str(ref))
    fake = _make_output(workspace, "word", "abc123", "Test.docx", b"x")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "Test", "paragraphs": [{"text": "Hello"}]}'

    with (
        patch(
            "backend.api.office_generate_routes.build_llm_client_from_settings",
            return_value=llm,
        ),
        patch("backend.api.office_generate_routes.generate_docx", return_value=fake),
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "根据参考资料写周报",
                "doc_type": "word",
                "reference_paths": [str(ref)],
            },
        )

    assert resp.status_code == 200, resp.text
    prompt = llm.complete.call_args.args[0]
    assert "上周完成了功能A" in prompt
    assert "参考资料" in prompt


def test_generate_nl_rejects_reference_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"x")

    llm = AsyncMock()
    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "x",
                "doc_type": "word",
                "reference_paths": [str(outside)],
            },
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"
    llm.complete.assert_not_called()


def test_generate_nl_rejects_non_docx_reference(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    notes = workspace / "notes.txt"
    notes.write_text("not a docx", encoding="utf-8")

    resp = _client().post(
        "/api/v1/office/generate/nl",
        json={
            "workspace_path": str(workspace),
            "instruction": "x",
            "doc_type": "word",
            "reference_paths": [str(notes)],
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"


def test_generate_nl_rejects_invalid_doc_type(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    resp = _client().post(
        "/api/v1/office/generate/nl",
        json={
            "workspace_path": str(workspace),
            "instruction": "x",
            "doc_type": "markdown",
        },
    )

    assert resp.status_code == 422, resp.text


def test_generate_nl_without_llm_returns_503(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=None,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "x",
                "doc_type": "word",
            },
        )

    assert resp.status_code == 503, resp.text


def test_generate_nl_unparseable_llm_output_returns_422(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    llm = AsyncMock()
    llm.complete.return_value = "not json"

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "x",
                "doc_type": "word",
            },
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error_type"] == "OfficeParseError"
