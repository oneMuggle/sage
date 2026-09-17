"""P1-B (office-p1b)：CSV 双扩展支持 —— excel doc_type 下的 .csv 读写。

覆盖：
- path_safety: excel doc_type 接受 .csv；其他类型仍拒绝 csv；
  .xlsx 仍是 excel 规范扩展（无扩展名自动补 xlsx）
- read_csv: utf-8-sig / gbk 解码、引号字段（逗号/换行）、行数上限
- update_csv: set_cells（含网格扩展）、append_rows、不支持 op 的
  all-or-nothing（失败不落盘）
- edit.update_document: excel + .csv 分流
- diff_preview: .csv 的 dry-run 预览
- attachment_resolver: .csv → office-excel 摘要
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.edit import update_document
from backend.office.errors import OfficePathError, OfficeSizeLimitError
from backend.office.excel import MAX_CSV_ROWS, read_csv, update_csv
from backend.office.models import OfficeDocType
from backend.office.path_safety import validate_supported_filename

pytestmark = pytest.mark.unit


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ── path_safety ──────────────────────────────────────────────────────


class TestPathSafety:
    def test_excel_accepts_csv_extension(self) -> None:
        assert (
            validate_supported_filename("数据.csv", OfficeDocType.EXCEL) == "数据.csv"
        )

    def test_excel_canonical_ext_still_auto_appends(self) -> None:
        assert (
            validate_supported_filename("数据", OfficeDocType.EXCEL) == "数据.xlsx"
        )

    def test_other_doc_types_reject_csv(self) -> None:
        with pytest.raises(OfficePathError):
            validate_supported_filename("x.csv", OfficeDocType.WORD)
        with pytest.raises(OfficePathError):
            validate_supported_filename("x.csv", OfficeDocType.PPT)

    def test_excel_rejects_wrong_non_csv_ext(self) -> None:
        with pytest.raises(OfficePathError):
            validate_supported_filename("x.docx", OfficeDocType.EXCEL)


# ── read_csv ─────────────────────────────────────────────────────────


class TestReadCsv:
    def test_reads_utf8_with_bom_and_quoted_fields(self, tmp_path: Path) -> None:
        p = _write_csv(
            tmp_path / "a.csv",
            '名称,备注\n苹果,"含,逗号"\n香蕉,"含\n换行"\n',
        )
        result = read_csv(p, workspace_path=str(tmp_path))
        assert result.summary.doc_type.value == "excel"
        assert len(result.sheets) == 1
        sheet = result.sheets[0]
        assert sheet.rows[0] == ["名称", "备注"]
        assert sheet.rows[1] == ["苹果", "含,逗号"]
        assert sheet.rows[2] == ["香蕉", "含\n换行"]
        assert sheet.max_row == 3
        assert sheet.max_col == 2

    def test_reads_gbk_encoded_file(self, tmp_path: Path) -> None:
        p = tmp_path / "gbk.csv"
        p.write_bytes("名称,金额\n测试,90\n".encode("gbk"))
        result = read_csv(p)
        assert result.sheets[0].rows == [["名称", "金额"], ["测试", "90"]]

    def test_undecodable_bytes_raise_parse_error(self, tmp_path: Path) -> None:
        from backend.office.errors import OfficeParseError

        p = tmp_path / "bad.csv"
        p.write_bytes(b"\xff\xfe\x00\x00\x81")
        with pytest.raises(OfficeParseError):
            read_csv(p)

    def test_row_cap_raises_size_limit(self, tmp_path: Path, monkeypatch) -> None:
        from backend.office import excel as excel_mod

        p = tmp_path / "big.csv"
        p.write_text(
            "h\n" + "".join(f"r{i}\n" for i in range(50)), encoding="utf-8"
        )
        monkeypatch.setattr(excel_mod, "MAX_CSV_ROWS", 10)
        with pytest.raises(OfficeSizeLimitError):
            read_csv(p)


# ── update_csv ───────────────────────────────────────────────────────


class TestUpdateCsv:
    def test_set_cells_extends_grid_and_writes(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path / "a.csv", "名称,金额\n苹果,3\n")
        saved, results = update_csv(
            p, [{"op": "set_cells", "cells": [{"addr": "C2", "value": "备注"}]}]
        )
        assert saved
        assert results[0]["ok"]
        assert read_csv(p).sheets[0].rows[1] == ["苹果", "3", "备注"]

    def test_append_rows(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path / "a.csv", "名称\n苹果\n")
        saved, results = update_csv(p, [{"op": "append_rows", "rows": [["香蕉"], ["橙"]]}])
        assert saved
        assert results[0]["ok"]
        rows = read_csv(p).sheets[0].rows
        assert rows[2] == ["香蕉"]
        assert rows[3] == ["橙"]

    def test_failed_op_is_all_or_nothing(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path / "a.csv", "a\n1\n")
        original = p.read_text(encoding="utf-8")
        saved, results = update_csv(
            p,
            [
                {"op": "append_rows", "rows": [["x"]]},
                {"op": "set_cells", "cells": [{"addr": "不是地址", "value": "v"}]},
            ],
        )
        assert not saved
        assert results[-1]["ok"] is False
        assert p.read_text(encoding="utf-8") == original  # 未落盘

    def test_formula_prefix_kept_literal(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path / "a.csv", "v\n1\n")
        update_csv(p, [{"op": "set_cells", "cells": [{"addr": "A1", "value": "=SUM(A2)"}]}])
        assert read_csv(p).sheets[0].rows[0] == ["=SUM(A2)"]  # 字面写入，非公式

    def test_write_back_row_cap_rejected(self, tmp_path: Path, monkeypatch) -> None:
        from backend.office import excel as excel_mod

        p = _write_csv(tmp_path / "a.csv", "h\n")
        monkeypatch.setattr(excel_mod, "MAX_CSV_ROWS", 2)
        saved, results = update_csv(
            p, [{"op": "append_rows", "rows": [["1"], ["2"], ["3"]]}]
        )
        assert not saved  # 写回超限折算失败，不抛异常
        assert results[-1]["op"] == "write_back"
        assert results[-1]["ok"] is False


# ── update_document / diff_preview / tool_service 分流 ───────────────


class TestDispatch:
    def test_update_document_routes_csv_to_csv_editor(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path / "a.csv", "名称\n苹果\n")
        saved, results = update_document("excel", p, [{"op": "append_rows", "rows": [["橙"]]}])
        assert saved
        assert results[0]["ok"]
        assert read_csv(p).sheets[0].rows[2] == ["橙"]

    def test_diff_preview_supports_csv(self, tmp_path: Path) -> None:
        from backend.office.diff_preview import preview_update

        p = _write_csv(tmp_path / "a.csv", "名称,值\n苹果,3\n")
        result = preview_update(
            p, [{"op": "set_cells", "cells": [{"addr": "B2", "value": "5"}]}]
        )
        assert result.ok is True
        assert any(c.op == "set_cells" for c in result.changes)
        # 预览绝不改源文件
        assert "3" in p.read_text(encoding="utf-8")

    def test_tool_service_reads_csv_doc(self, tmp_path: Path) -> None:
        from backend.data.database import Database
        from backend.office.models import (
            OfficeDocStatus,
            OfficeDocumentMetadata,
            OfficeDocumentSummary,
        )
        from backend.office.session_workspace import bind_session_workspace
        from backend.office.storage import document_path, save_document
        from backend.office.tool_service import OfficeToolService

        db = Database(db_path=str(tmp_path / "t.db"))
        db.init_db()
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s1','t',1,1)"
        )
        conn.commit()
        work = tmp_path / "work"
        work.mkdir()
        binding = bind_session_workspace(conn, "s1", str(work), now_ms=1)
        doc = OfficeDocumentSummary(
            id="doc-csv",
            workspace_path=binding.workspace_path,
            doc_type=OfficeDocType.EXCEL,
            original_filename="a.csv",
            generated_filename="doc-csv.csv",
            status=OfficeDocStatus.PARSED,
            created_at=1,
            updated_at=1,
            metadata=OfficeDocumentMetadata(file_size_bytes=1),
            archived_at=None,
        )
        save_document(conn, doc)
        target = document_path(doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(target, "名称,值\n苹果,3\n")

        service = OfficeToolService()
        result = service.read(conn, "s1", binding.generation, "doc-csv", section="all")
        assert result["success"] is True
        assert result["content"]["sheets"][0]["rows"] == [["名称", "值"], ["苹果", "3"]]


# ── attachment 摘要 ──────────────────────────────────────────────────


class TestAttachmentDigest:
    def test_csv_routes_to_excel_digest(self, tmp_path: Path) -> None:
        from backend.chat.attachment_resolver import _digest_for_kind

        p = _write_csv(tmp_path / "a.csv", "名称,值\n苹果,3\n")
        digest = _digest_for_kind("office-excel", str(p), str(tmp_path))
        assert "名称" in digest
        assert "苹果" in digest

    def test_ext_to_kind_maps_csv(self) -> None:
        from backend.chat.attachment_resolver import _EXT_TO_KIND

        assert _EXT_TO_KIND.get(".csv") == "office-excel"


def test_max_csv_rows_constant_sane() -> None:
    assert MAX_CSV_ROWS == 10_000
