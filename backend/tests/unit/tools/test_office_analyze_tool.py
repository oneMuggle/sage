# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_analyze_tool`.

覆盖（Office Parity Batch-2 item 2.2，对标 ChatGPT 数据分析）：

- 形状声明：读类工具 ``requires_tool_context = True`` + READ；schema
  不暴露 workspace_path。
- 四类操作：describe（含 mean/std）、value_counts（计数正确）、
  aggregate（group_by sum 数值正确）、corr（矩阵存在）。
- 多操作按序执行；参数错误 fail-fast（缺 operations / 超 5 个 / 非法
  kind / aggregate 缺列 / 列不存在 / sheet 不存在 / 空 sheet）。
- write_report：报告 xlsx 落在源文件同目录（``<stem>-analysis.xlsx``），
  含 summary sheet + aggregate sheet + 原生图表 xml；重复覆盖 OK；
  源文件不动；write_report=false 不产生报告。
- doc_id 模式经 binding 解析受管文档，报告落受管目录。
- pandas 缺失 → 干净工具错误（非崩溃）；输出按 max_output_bytes 截断。
"""

from __future__ import annotations

import builtins
import zipfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from backend.data.database import Database
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.tools.context import ToolExecutionContext, reset_tool_context, set_tool_context
from backend.tools.office_analyze_tool import OfficeAnalyzeTool

pytestmark = pytest.mark.unit

pandas = pytest.importorskip("pandas")


# ── Helpers ───────────────────────────────────────────────────────────


def _tool(cls=OfficeAnalyzeTool, **policy_kwargs):
    return cls(policy=ToolPolicy(**policy_kwargs))


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.EXCEL,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        # 真实导入路径里 generated_filename = 原文件名（带真实扩展名，
        # 见 office_routes 导入网关），excel → ".xlsx"。
        original_filename=f"上传-{doc_id}.xlsx",
        generated_filename=f"{doc_id}.xlsx",
        status=OfficeDocStatus.PARSED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(session_id: str, binding_generation: int = 1) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


def _make_xlsx(path: Path, rows: int = 30) -> Path:
    """30 行测试数据：category（3 类字符串）+ value（float）+ quantity（int）。

    value = i (1..30)，quantity = 2i；category = cat<i%3>。
    group_by=category 后 value 求和：cat0=165, cat1=145, cat2=155。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(["category", "value", "quantity"])
    for i in range(1, rows + 1):
        ws.append([f"cat{i % 3}", float(i), i * 2])
    wb.save(str(path))
    return path


class _BoundWorkspace:
    """一台测试机：in-memory DB + 绑定工作区 + patch 过的 get_database。"""

    def __init__(self, tmp_path: Path, workspace_root: Optional[str] = None):
        self.db = Database(db_path=str(tmp_path / "t.db"))
        self.db.init_db()
        self.conn = self.db.get_connection()
        _seed_session(self.conn, "sess-1")
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.binding = bind_session_workspace(self.conn, "sess-1", str(self.work), now_ms=1)
        self.policy_kwargs = {}
        if workspace_root is not None:
            self.policy_kwargs["workspace_root"] = workspace_root

    def patch(self):
        return patch("backend.tools.office_analyze_tool.get_database", return_value=self.db)

    def context(self):
        return _ctx("sess-1", self.binding.generation)


def _run(env: _BoundWorkspace, **kwargs):
    """绑定上下文内执行一次 office_analyze。"""
    with env.patch():
        token = set_tool_context(env.context())
        try:
            return _tool(OfficeAnalyzeTool, **env.policy_kwargs).execute(**kwargs)
        finally:
            reset_tool_context(token)


# ── 形状声明 ──────────────────────────────────────────────────────────


def test_requires_context_and_declares_read():
    tool = _tool()
    assert tool.requires_tool_context is True
    assert tool.risk is RiskClass.READ


def test_schema_does_not_expose_workspace_path():
    props = _tool().schema.parameters["properties"]
    assert "workspace_path" not in props


def test_without_context_fails_closed():
    result = _tool().execute(file_path="x.xlsx", operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error == "missing_tool_context"


# ── 四类操作 ──────────────────────────────────────────────────────────


def test_describe_returns_numeric_stats(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "describe"}])

    assert result.success is True
    table = result.content["results"][0]["table"]
    for stat in ("count", "mean", "std", "min", "25%", "50%", "75%", "max"):
        assert stat in table
    assert "15.5" in table  # value 列均值
    # 各列非空计数表覆盖字符串列
    assert "category" in table
    assert result.content["file"]["rows"] == 30
    assert result.content["file"]["columns"] == 3


def test_value_counts_counts_correctly(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[{"kind": "value_counts", "column": "category"}],
    )

    assert result.success is True
    table = result.content["results"][0]["table"]
    for cat in ("cat0", "cat1", "cat2"):
        row = [line for line in table.splitlines() if f"| {cat} |" in line]
        assert len(row) == 1, table
        assert "| 10 |" in row[0]


def test_aggregate_group_by_sum_correct(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[
            {"kind": "aggregate", "group_by": "category", "column": "value", "agg": "sum"}
        ],
    )

    assert result.success is True
    table = result.content["results"][0]["table"]
    # 期望值：cat0=165, cat1=145, cat2=155（value = i, i∈1..30, 按 i%3 分组）
    for cat, expected in (("cat0", 165), ("cat1", 145), ("cat2", 155)):
        row = [line for line in table.splitlines() if f"| {cat} |" in line]
        assert len(row) == 1, table
        assert f"| {expected} |" in row[0]


def test_corr_matrix_present(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "corr"}])

    assert result.success is True
    table = result.content["results"][0]["table"]
    assert "| value" in table
    assert "quantity" in table
    # 完全线性相关 → 对角线 1
    assert "| 1 |" in table


def test_operations_execute_in_order(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[
            {"kind": "describe"},
            {"kind": "value_counts", "column": "category"},
        ],
    )

    assert result.success is True
    assert [r["kind"] for r in result.content["results"]] == [
        "describe",
        "value_counts",
    ]


# ── 参数与数据错误 fail-fast ──────────────────────────────────────────


def test_operations_required(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx))
    assert result.success is False
    assert result.error == "operations_required"


def test_too_many_operations_rejected(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "describe"}] * 6)
    assert result.success is False
    assert result.error.startswith("too_many_operations")


def test_unsupported_kind_rejected(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "pivot"}])
    assert result.success is False
    assert result.error.startswith("unsupported_operation")


def test_aggregate_without_column_rejected(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[{"kind": "aggregate", "group_by": "category", "agg": "sum"}],
    )
    assert result.success is False
    assert result.error.startswith("aggregate_column_required")


def test_unknown_column_lists_available(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[{"kind": "value_counts", "column": "nope"}],
    )
    assert result.success is False
    assert result.error.startswith("column_not_found")
    assert "category" in result.error


def test_unknown_sheet_lists_available(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), sheet="ghost", operations=[{"kind": "corr"}])
    assert result.success is False
    assert result.error.startswith("sheet_not_found")
    assert "data" in result.error


def test_unsupported_file_type_rejected(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    docx = env.work / "doc.docx"
    docx.write_bytes(b"not a real docx")
    result = _run(env, file_path=str(docx), operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error.startswith("unsupported_file_type")


def test_requires_doc_id_or_file_path(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    result = _run(env, operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error == "doc_id_or_file_path_required"


def test_rejects_path_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    outside = _make_xlsx(tmp_path / "outside.xlsx")
    result = _run(env, file_path=str(outside), operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")


def test_empty_sheet_rejected(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = env.work / "empty.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "blank"
    wb.save(str(xlsx))
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error.startswith("sheet_empty")


# ── 分析报告（write_report）────────────────────────────────────────────


def test_write_report_creates_xlsx_next_to_source(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")
    before = xlsx.read_bytes()
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[
            {"kind": "describe"},
            {"kind": "aggregate", "group_by": "category", "column": "value", "agg": "sum"},
        ],
        write_report=True,
    )

    assert result.success is True
    report = env.work / "sales-analysis.xlsx"
    assert report.exists()
    content_report = result.content["report"]
    assert content_report["filename"] == "sales-analysis.xlsx"
    assert content_report["bytes"] == report.stat().st_size
    assert content_report["chart_embedded"] is True

    # summary sheet + aggregate sheet（每 op 一 sheet）
    wb = load_workbook(str(report))
    assert "summary" in wb.sheetnames
    assert "aggregate" in wb.sheetnames
    summary_rows = list(wb["summary"].iter_rows(values_only=True))
    flat = [cell for row in summary_rows for cell in row if cell is not None]
    assert any(str(cell) == "sales.xlsx" for cell in flat)
    assert 30 in flat  # 数据行数

    # aggregate sheet 数值正确 + 原生图表 xml 存在（zip 包内）
    agg_rows = {
        row[0]: row[1]
        for row in wb["aggregate"].iter_rows(min_row=2, values_only=True)
        if row[0] is not None
    }
    assert agg_rows == {"cat0": 165.0, "cat1": 145.0, "cat2": 155.0}
    wb.close()
    with zipfile.ZipFile(str(report)) as zf:
        assert any(n.startswith("xl/charts/chart") for n in zf.namelist())

    # 源文件不被改动
    assert xlsx.read_bytes() == before
    # 不残留临时文件
    leftovers = [p.name for p in env.work.iterdir() if p.name.startswith(".analysis-")]
    assert leftovers == []


def test_write_report_overwrites_previous_report(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")
    stale = env.work / "sales-analysis.xlsx"
    stale.write_bytes(b"stale bytes")  # 派生产物：直接覆盖
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[{"kind": "value_counts", "column": "category"}],
        write_report=True,
    )
    assert result.success is True
    report = env.work / "sales-analysis.xlsx"
    assert report.read_bytes() != b"stale bytes"
    with zipfile.ZipFile(str(report)) as zf:
        assert zf.testzip() is None  # 是有效 xlsx（zip）
    assert result.content["report"]["filename"] == "sales-analysis.xlsx"


def test_no_report_without_write_report(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[{"kind": "describe"}])
    assert result.success is True
    assert "report" not in result.content
    assert not (env.work / "data-analysis.xlsx").exists()


# ── doc_id 模式 ───────────────────────────────────────────────────────


def test_doc_id_resolves_managed_document_and_report_lands_managed_dir(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "excel" / "doc-a"
    managed_dir.mkdir(parents=True)
    _make_xlsx(managed_dir / "doc-a.xlsx")
    save_document(
        conn=env.conn,
        summary=_make_doc(doc_id="doc-a", workspace_path=env.binding.workspace_path),
    )

    result = _run(
        env,
        doc_id="doc-a",
        operations=[{"kind": "aggregate", "group_by": "category", "column": "value", "agg": "sum"}],
        write_report=True,
    )

    assert result.success is True
    # 源文件名回显受管名，不回显绝对路径
    assert result.content["file"]["filename"] == "doc-a.xlsx"
    # 报告落受管目录（源文件同目录）
    report = managed_dir / "doc-a-analysis.xlsx"
    assert report.exists()
    assert Path(result.content["report"]["path"]).resolve() == report.resolve()


def test_unknown_doc_id_is_document_not_found(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    result = _run(env, doc_id="ghost", operations=[{"kind": "describe"}])
    assert result.success is False
    assert result.error == "document_not_found"


# ── 依赖与输出上限 ────────────────────────────────────────────────────


def test_pandas_missing_returns_clean_error(tmp_path: Path, monkeypatch):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool().execute(
                file_path=str(xlsx), operations=[{"kind": "describe"}]
            )
        finally:
            reset_tool_context(token)

    assert result.success is False
    assert result.error.startswith("pandas_missing")
    assert "数据分析需要 pandas（本机未安装）" in result.error


def test_output_cap_truncates(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "data.xlsx", rows=30)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzeTool, max_output_bytes=200).execute(
                file_path=str(xlsx),
                operations=[{"kind": "describe"}, {"kind": "corr"}],
            )
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content["truncated"] is True
    assert result.content["max_output_bytes"] == 200
    assert len(result.content["head"].encode("utf-8")) <= 200

