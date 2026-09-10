# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Integration tests for the journal template subsystem HTTP routes (Task 6).

覆盖 5 个 endpoints：
- POST /office/journal/parse-template
- GET  /office/journal/specs
- GET  /office/journal/specs/{spec_id}
- POST /office/journal/validate
- POST /office/journal/fill-from-content

直接调用 route 函数（与 test_office_template_routes.py 同模式）。不依赖 FastAPI
TestClient，启动开销最小。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.api.office_routes import (
    OfficeJournalFillRequest,
    OfficeJournalParseRequest,
    OfficeJournalValidateRequest,
    fill_journal_from_content_endpoint,
    get_journal_spec_endpoint,
    list_journal_specs_endpoint,
    parse_journal_template_endpoint,
    validate_journal_endpoint,
)
from backend.office.errors import OfficeFileNotFoundError, OfficePathError
from backend.office.journal.errors import JournalContentShapeError

pytestmark = pytest.mark.integration

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "journal"
TEMPLATE_PATH = FIXTURE_ROOT / "simple_chinese_template.docx"
GOOD_FILLED = FIXTURE_ROOT / "good_filled_paper.docx"
BAD_FILLED = FIXTURE_ROOT / "bad_filled_paper.docx"


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _copy_template(workspace: Path) -> Path:
    target = workspace / "tmpl.docx"
    shutil.copy2(TEMPLATE_PATH, target)
    return target


def _copy_filled(workspace: Path, src: Path = GOOD_FILLED) -> Path:
    target = workspace / "filled.docx"
    shutil.copy2(src, target)
    return target


# ——— (section divider) ———
# POST /office/journal/parse-template
# ——— (section divider) ———


def test_parse_template_endpoint_returns_spec(workspace: Path):
    target = _copy_template(workspace)
    req = OfficeJournalParseRequest(
        workspace_path=str(workspace), file_path=str(target)
    )
    resp = parse_journal_template_endpoint(req)
    assert resp.spec.spec_id
    assert resp.spec.template_sha256
    assert resp.spec.template_filename == "tmpl.docx"
    assert abs(resp.spec.body_pt - 12.0) < 0.01


def test_parse_template_persists_spec_for_later(workspace: Path):
    target = _copy_template(workspace)
    req = OfficeJournalParseRequest(
        workspace_path=str(workspace), file_path=str(target)
    )
    resp = parse_journal_template_endpoint(req)
    list_resp = list_journal_specs_endpoint(workspace_path=str(workspace))
    ids = [s.spec_id for s in list_resp.specs]
    assert resp.spec.spec_id in ids


def test_parse_template_outside_workspace_rejected(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    other = tmp_path / "other.docx"
    shutil.copy2(TEMPLATE_PATH, other)
    req = OfficeJournalParseRequest(
        workspace_path=str(workspace), file_path=str(other)
    )
    with pytest.raises(OfficePathError):
        parse_journal_template_endpoint(req)


def test_parse_template_corrupt_docx_raises_journal_parse_error_mapped_to_422(
    workspace: Path,
):
    """Regression for C1 (Task 6 fix round 1).

    When parse_journal_spec raises JournalParseError, the endpoint MUST let it
    propagate as-is (not wrap as plain OfficeError) so the registered FastAPI
    exception handler maps OfficeParseError → HTTP 422. If it gets wrapped as
    OfficeError, office_error_to_http_status falls through to the 500 base case.
    """
    from backend.office.errors import OfficeParseError, office_error_to_http_status
    from backend.office.journal.errors import JournalParseError

    target = workspace / "corrupt.docx"
    shutil.copy2(FIXTURE_ROOT / "bad_template_corrupt.docx", target)
    req = OfficeJournalParseRequest(
        workspace_path=str(workspace), file_path=str(target)
    )

    # Endpoints must propagate JournalParseError as-is (not wrap as OfficeError).
    with pytest.raises(JournalParseError) as excinfo:
        parse_journal_template_endpoint(req)

    # The raised exception must also be an OfficeParseError subclass so that
    # office_error_to_http_status returns 422 (not the 500 base case).
    assert isinstance(excinfo.value, OfficeParseError)
    assert office_error_to_http_status(excinfo.value) == 422


# ——— (section divider) ———
# GET /office/journal/specs
# ——— (section divider) ———


def test_list_journal_specs_empty(workspace: Path):
    resp = list_journal_specs_endpoint(workspace_path=str(workspace))
    assert resp.total == 0
    assert resp.specs == []


# ——— GET /office/journal/specs/{spec_id} ———


def test_get_journal_spec_endpoint_returns_full_spec(workspace: Path):
    target = _copy_template(workspace)
    parsed = parse_journal_template_endpoint(
        OfficeJournalParseRequest(
            workspace_path=str(workspace), file_path=str(target)
        )
    )
    spec_id = parsed.spec.spec_id
    resp = get_journal_spec_endpoint(spec_id, workspace_path=str(workspace))
    assert resp.spec.spec_id == spec_id


def test_get_journal_spec_missing_returns_404(workspace: Path):
    with pytest.raises(OfficeFileNotFoundError):
        get_journal_spec_endpoint("spec_does_not_exist", workspace_path=str(workspace))


# ——— (section divider) ———
# POST /office/journal/fill-from-content
# ——— (section divider) ———


def test_fill_from_content_endpoint_happy_path(workspace: Path):
    target = _copy_template(workspace)
    parsed = parse_journal_template_endpoint(
        OfficeJournalParseRequest(
            workspace_path=str(workspace), file_path=str(target)
        )
    )
    content = {
        "title": "集成测试论文",
        "abstract": "本测试覆盖 fill-from-content 端到端路径。",
        "sections": {"关键词": "集成测试, 端到端"},
        "references": [],
        "citations": [],
    }
    req = OfficeJournalFillRequest(
        workspace_path=str(workspace),
        spec_id=parsed.spec.spec_id,
        content=content,
        output_filename="paper.docx",
    )
    resp = fill_journal_from_content_endpoint(req)
    assert resp.spec_id == parsed.spec.spec_id
    assert resp.output_path.endswith("paper.docx")
    assert Path(resp.output_path).is_file()
    assert resp.bytes_written > 0


def test_fill_from_content_missing_spec_id_and_file_path(workspace: Path):
    """既无 spec_id 也无 file_path → OfficePathError（前端必须传其一）。"""
    req = OfficeJournalFillRequest(
        workspace_path=str(workspace),
        content={
            "title": "x",
            "abstract": "y",
            "sections": {"关键词": "k"},
            "references": [],
            "citations": [],
        },
    )
    with pytest.raises(OfficePathError):
        fill_journal_from_content_endpoint(req)


def test_fill_from_content_invalid_content_shape(workspace: Path):
    target = _copy_template(workspace)
    parsed = parse_journal_template_endpoint(
        OfficeJournalParseRequest(
            workspace_path=str(workspace), file_path=str(target)
        )
    )
    # title 期望 str，传 int → Pydantic ValidationError → JournalContentShapeError
    req = OfficeJournalFillRequest(
        workspace_path=str(workspace),
        spec_id=parsed.spec.spec_id,
        content={
            "title": 12345,
            "abstract": "x",
            "sections": {"关键词": "k"},
        },
    )
    with pytest.raises(JournalContentShapeError):
        fill_journal_from_content_endpoint(req)


# ——— (section divider) ———
# POST /office/journal/validate
# ——— (section divider) ———


def test_validate_endpoint_returns_violations_list(workspace: Path):
    target = _copy_template(workspace)
    parsed = parse_journal_template_endpoint(
        OfficeJournalParseRequest(
            workspace_path=str(workspace), file_path=str(target)
        )
    )
    filled = _copy_filled(workspace, BAD_FILLED)  # bad fixture：至少 1 violation
    req = OfficeJournalValidateRequest(
        workspace_path=str(workspace),
        spec_id=parsed.spec.spec_id,
        file_path=str(filled),
    )
    resp = validate_journal_endpoint(req)
    assert resp.spec_id == parsed.spec.spec_id
    assert resp.file_path == str(filled)
    assert isinstance(resp.violations, list)
    assert resp.error_count >= 0
    assert resp.warning_count >= 0


def test_validate_endpoint_clean_doc(workspace: Path):
    """good_filled_paper.docx 应满足 simple_chinese_template 规约（error_count == 0）。"""
    target = _copy_template(workspace)
    parsed = parse_journal_template_endpoint(
        OfficeJournalParseRequest(
            workspace_path=str(workspace), file_path=str(target)
        )
    )
    filled = _copy_filled(workspace, GOOD_FILLED)
    req = OfficeJournalValidateRequest(
        workspace_path=str(workspace),
        spec_id=parsed.spec.spec_id,
        file_path=str(filled),
    )
    resp = validate_journal_endpoint(req)
    assert resp.error_count == 0, [v.message for v in resp.violations]


def test_validate_endpoint_missing_file_in_workspace(workspace: Path):
    """file_path 在 workspace 内但文件不存在 → OfficeFileNotFoundError。"""
    req = OfficeJournalValidateRequest(
        workspace_path=str(workspace),
        spec_id="spec_anything",
        file_path=str(workspace / "non_existent.docx"),
    )
    with pytest.raises(OfficeFileNotFoundError):
        validate_journal_endpoint(req)


def test_validate_endpoint_file_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    shutil.copy2(GOOD_FILLED, outside)
    req = OfficeJournalValidateRequest(
        workspace_path=str(workspace),
        spec_id="spec_anything",
        file_path=str(outside),
    )
    with pytest.raises(OfficePathError):
        validate_journal_endpoint(req)
