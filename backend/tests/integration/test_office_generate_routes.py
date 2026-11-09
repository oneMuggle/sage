from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.office.models import PdfGenerateResult, WordTemplateFillResult

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

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch(
            "backend.api.office_generate_routes.generate_docx", return_value=fake
        ) as mock_gen:
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

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch("backend.api.office_generate_routes.generate_pdf", return_value=pdf_result):
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

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch(
            "backend.api.office_generate_routes.generate_docx", return_value=fake
        ) as mock_gen:
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

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch("backend.api.office_generate_routes.generate_docx", return_value=fake):
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


def test_generate_nl_unreadable_reference_returns_422(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    broken = workspace / "reference.docx"
    broken.write_bytes(b"not a docx")

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
                "reference_paths": [str(broken)],
            },
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error_type"] == "OfficeParseError"
    llm.complete.assert_not_called()


def _fake_fill(workspace: Path, doc_id: str, name: str) -> WordTemplateFillResult:
    fake = _make_output(workspace, "word", doc_id, name, b"filled")
    return WordTemplateFillResult(
        output_path=str(fake),
        filename=name,
        file_size_bytes=len(b"filled"),
        filled_count=2,
        unfilled_placeholders=[],
    )


def test_template_chat_happy_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fill = _fake_fill(workspace, "abc123", "周报.docx")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "第 45 周周报", "highlights": "完成 P3 生成工作台"}'

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch(
            "backend.api.office_generate_routes.instantiate_template",
            return_value=fill,
        ) as mock_instantiate:
            resp = _client().post(
                "/api/v1/office/generate/template-chat",
                json={
                    "workspace_path": str(workspace),
                    "template_id": "weekly_report",
                    "messages": [
                        {"role": "user", "content": "帮我写第 45 周周报"},
                        {"role": "assistant", "content": "本周有哪些亮点？"},
                        {"role": "user", "content": "完成了 P3 生成工作台"},
                    ],
                },
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "周报.docx"
    assert data["summary"]["id"] == "abc123"
    assert data["summary"]["doc_type"] == "word"

    kwargs = mock_instantiate.call_args.kwargs
    assert kwargs["template_id"] == "weekly_report"
    assert kwargs["workspace_template"] is None
    assert kwargs["filename"] == "周报.docx"
    assert kwargs["data"] == {
        "title": "第 45 周周报",
        "highlights": "完成 P3 生成工作台",
    }

    prompt = llm.complete.call_args.args[0]
    assert "周报" in prompt
    assert "highlights" in prompt
    assert "完成了 P3 生成工作台" in prompt


def test_template_chat_unknown_template_returns_404(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    llm = AsyncMock()
    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/template-chat",
            json={
                "workspace_path": str(workspace),
                "template_id": "no_such_template",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["error_type"] == "OfficeFileNotFoundError"
    llm.complete.assert_not_called()


def test_template_chat_rejects_two_template_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    resp = _client().post(
        "/api/v1/office/generate/template-chat",
        json={
            "workspace_path": str(workspace),
            "template_id": "weekly_report",
            "workspace_template": "my.docx",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"


def test_template_chat_invalid_llm_json_returns_422(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    llm = AsyncMock()
    llm.complete.return_value = "not json"

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/template-chat",
            json={
                "workspace_path": str(workspace),
                "template_id": "weekly_report",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error_type"] == "OfficeParseError"


def test_template_chat_without_llm_returns_503(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=None,
    ):
        resp = _client().post(
            "/api/v1/office/generate/template-chat",
            json={
                "workspace_path": str(workspace),
                "template_id": "weekly_report",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 503, resp.text


def _write_source_docx(workspace: Path, name: str, text: str) -> Path:
    from docx import Document

    path = workspace / name
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))
    return path


def test_iterate_word_happy_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = _write_source_docx(workspace, "report.docx", "原始内容：第一版周报")
    fake = _make_output(workspace, "word", "iter1", "report_v2.docx", b"v2")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "周报第二版", "paragraphs": [{"text": "修订后的内容"}]}'

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch(
            "backend.api.office_generate_routes.generate_docx", return_value=fake
        ) as mock_gen:
            resp = _client().post(
                "/api/v1/office/generate/iterate",
                json={
                    "workspace_path": str(workspace),
                    "source_path": str(source),
                    "instruction": "把语气改得更正式",
                },
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["filename"] == "report_v2.docx"
    assert data["summary"]["id"] == "iter1"
    assert data["summary"]["doc_type"] == "word"

    request = mock_gen.call_args.args[0]
    assert request.filename == "report_v2.docx"
    assert request.workspace_path == str(workspace.resolve())
    assert request.title == "周报第二版"

    prompt = llm.complete.call_args.args[0]
    assert "原始内容：第一版周报" in prompt
    assert "把语气改得更正式" in prompt


def test_iterate_increments_existing_version_suffix(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = _write_source_docx(workspace, "report_v2.docx", "第二版")
    fake = _make_output(workspace, "word", "iter2", "report_v3.docx", b"v3")

    llm = AsyncMock()
    llm.complete.return_value = '{"title": "T", "paragraphs": [{"text": "b"}]}'

    with patch(  # noqa: SIM117 — py38 不支持括号多上下文 with
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        with patch(
            "backend.api.office_generate_routes.generate_docx", return_value=fake
        ) as mock_gen:
            resp = _client().post(
                "/api/v1/office/generate/iterate",
                json={
                    "workspace_path": str(workspace),
                    "source_path": str(source),
                    "instruction": "继续修改",
                },
            )

    assert resp.status_code == 200, resp.text
    assert mock_gen.call_args.args[0].filename == "report_v3.docx"


def test_iterate_rejects_source_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _write_source_docx(tmp_path, "outside.docx", "secret")

    llm = AsyncMock()
    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/iterate",
            json={
                "workspace_path": str(workspace),
                "source_path": str(outside),
                "instruction": "x",
            },
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"
    llm.complete.assert_not_called()


def test_iterate_rejects_non_docx_source(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    notes = workspace / "notes.txt"
    notes.write_text("not a docx", encoding="utf-8")

    resp = _client().post(
        "/api/v1/office/generate/iterate",
        json={
            "workspace_path": str(workspace),
            "source_path": str(notes),
            "instruction": "x",
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"


def test_iterate_missing_source_returns_400(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    resp = _client().post(
        "/api/v1/office/generate/iterate",
        json={
            "workspace_path": str(workspace),
            "source_path": str(workspace / "nope.docx"),
            "instruction": "x",
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error_type"] == "OfficePathError"


def test_iterate_invalid_llm_json_returns_422(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = _write_source_docx(workspace, "report.docx", "正文")

    llm = AsyncMock()
    llm.complete.return_value = "not json"

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/iterate",
            json={
                "workspace_path": str(workspace),
                "source_path": str(source),
                "instruction": "x",
            },
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["error_type"] == "OfficeParseError"


def test_iterate_without_llm_returns_503(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    source = _write_source_docx(workspace, "report.docx", "正文")

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=None,
    ):
        resp = _client().post(
            "/api/v1/office/generate/iterate",
            json={
                "workspace_path": str(workspace),
                "source_path": str(source),
                "instruction": "x",
            },
        )

    assert resp.status_code == 503, resp.text


# ──────────────────────────────────────────────────────────────────────
# Final fix round — provider failures, constrained list, corrupt source
# ──────────────────────────────────────────────────────────────────────


def test_generate_nl_provider_failure_returns_502_json(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    llm = AsyncMock()
    llm.complete.side_effect = RuntimeError("provider down")

    with patch(
        "backend.api.office_generate_routes.build_llm_client_from_settings",
        return_value=llm,
    ):
        resp = _client().post(
            "/api/v1/office/generate/nl",
            json={
                "workspace_path": str(workspace),
                "instruction": "写一份测试文档",
                "doc_type": "word",
            },
        )

    assert resp.status_code == 502, resp.text
    body = resp.json()
    assert body["error_type"] == "OfficeLLMError"
    assert body["message"] == "LLM 调用失败，请稍后重试"


def test_template_chat_request_rejects_empty_messages() -> None:
    from backend.api.office_generate_routes import TemplateChatRequest

    with pytest.raises(ValidationError):
        TemplateChatRequest(workspace_path="/ws", messages=[])


def test_template_chat_messages_use_a_constrained_list() -> None:
<<<<<<< HEAD
    import pydantic

    from backend.api.office_generate_routes import TemplateChatRequest

    if int(pydantic.VERSION.split(".")[0]) >= 2:
        field = TemplateChatRequest.model_fields["messages"]
        assert any(getattr(meta, "min_length", None) == 1 for meta in field.metadata)
    else:
        # pydantic v1: conlist(min_items=1) is baked into the field type;
        # behavioral parity already covered by rejects_empty_messages; here
        # just confirm the field rejects [] via ValidationError on v1 too.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TemplateChatRequest(workspace_path="/ws", messages=[])
=======
    from backend.api.office_generate_routes import TemplateChatRequest

    field = TemplateChatRequest.model_fields["messages"]
    assert any(getattr(meta, "min_length", None) == 1 for meta in field.metadata)
>>>>>>> origin/main


def test_iterate_corrupt_docx_returns_422(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    broken = workspace / "broken.docx"
    broken.write_bytes(b"not a real docx")

    resp = _client().post(
        "/api/v1/office/generate/iterate",
        json={
            "workspace_path": str(workspace),
            "source_path": str(broken),
            "instruction": "整理语气",
        },
    )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error_type"] == "OfficeParseError"
    assert "broken.docx" in body["message"]
