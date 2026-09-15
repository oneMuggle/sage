# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for office_analyze write_report 的 PNG 图表产物（Round2 R6）.

覆盖：

- aggregate + write_report → ``<stem>-analysis-chart.png`` 落报告同目录、
  是合法 PNG（magic bytes）、report info 回显 chart_png（path/filename/bytes）。
- PNG 经 ``_record_artifact_safely`` 注册为 artifact（与报告 xlsx 同机制，
  detect_artifact_kind → kind="image"）。
- matplotlib 缺失 → 分析结果照常 success，chart_png=None、无 PNG 残留
  （best-effort 降级，与原生图表的容错姿态一致）。
- 无 aggregate op → 不渲染 PNG。
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest
from openpyxl import Workbook

from backend.data.database import Database
from backend.office.session_workspace import bind_session_workspace
from backend.tools.context import reset_tool_context, set_tool_context
from backend.tools.office_analyze_tool import OfficeAnalyzeTool

pytestmark = pytest.mark.unit

pandas = pytest.importorskip("pandas")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ── Helpers（同 test_office_analyze_tool.py 的测试机形态） ─────────────


def _make_xlsx(path: Path, rows: int = 30) -> Path:
    """30 行数据：category（3 类）+ value（float）；cat0 求和=165。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "data"
    ws.append(["category", "value"])
    for i in range(1, rows + 1):
        ws.append([f"cat{i % 3}", float(i)])
    wb.save(str(path))
    return path


class _BoundWorkspace:
    """一台测试机：in-memory DB + 绑定工作区 + patch 过的 get_database。"""

    def __init__(self, tmp_path: Path):
        self.db = Database(db_path=str(tmp_path / "t.db"))
        self.db.init_db()
        self.conn = self.db.get_connection()
        self.conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("sess-1", "t", 1, 1),
        )
        self.conn.commit()
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.binding = bind_session_workspace(
            self.conn, "sess-1", str(self.work), now_ms=1
        )

    def patch(self):
        from unittest.mock import patch

        return patch(
            "backend.tools.office_analyze_tool.get_database",
            return_value=self.db,
        )


def _run(env: _BoundWorkspace, **kwargs):
    """绑定上下文内执行一次 office_analyze。"""
    from backend.tools.context import ToolExecutionContext

    ctx = ToolExecutionContext(
        session_id="sess-1",
        stream_id="stream-x",
        binding_generation=env.binding.generation,
        office_doc_scope=frozenset(),
    )
    with env.patch():
        token = set_tool_context(ctx)
        try:
            from backend.domain.tool_policy import ToolPolicy

            tool = OfficeAnalyzeTool(policy=ToolPolicy())
            return tool.execute(**kwargs)
        finally:
            reset_tool_context(token)


_AGG_OP = {"kind": "aggregate", "group_by": "category", "column": "value", "agg": "sum"}


# ── R6：PNG 图表产物 ──────────────────────────────────────────────────


def test_write_report_renders_png_next_to_report(tmp_path: Path):
    pytest.importorskip("matplotlib")
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")
    result = _run(env, file_path=str(xlsx), operations=[dict(_AGG_OP)], write_report=True)

    assert result.success is True
    png = env.work / "sales-analysis-chart.png"
    assert png.exists()
    assert png.read_bytes().startswith(_PNG_MAGIC)

    report = result.content["report"]
    assert report["chart_png"] is not None
    assert report["chart_png"]["filename"] == "sales-analysis-chart.png"
    assert report["chart_png"]["path"] == str(png)
    assert report["chart_png"]["bytes"] == png.stat().st_size
    # 报告 xlsx 本身照旧
    assert (env.work / "sales-analysis.xlsx").exists()
    assert report["chart_embedded"] is True


def test_png_registered_as_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """PNG 与报告 xlsx 走同一注册机制 _record_artifact_safely（kind=image）。"""
    pytest.importorskip("matplotlib")
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")

    recorded: List[Tuple[str, int]] = []

    def _recorder(resolved_path: str, size: int) -> None:
        recorded.append((resolved_path, size))

    monkeypatch.setattr(
        "backend.tools.office_analyze_tool._record_artifact_safely", _recorder
    )
    result = _run(env, file_path=str(xlsx), operations=[dict(_AGG_OP)], write_report=True)

    assert result.success is True
    png = env.work / "sales-analysis-chart.png"
    paths = [p for p, _ in recorded]
    assert paths == [str(env.work / "sales-analysis.xlsx"), str(png)]
    assert recorded[1][1] == png.stat().st_size


def test_matplotlib_missing_keeps_analysis_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """matplotlib 缺失：PNG 渲染失败被吞掉，分析结果与报告 xlsx 照常。"""
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")

    real_import = builtins.__import__

    def _no_matplotlib(name: str, *args: Any, **kwargs: Any):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("matplotlib disabled for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_matplotlib)
    result = _run(env, file_path=str(xlsx), operations=[dict(_AGG_OP)], write_report=True)

    assert result.success is True
    report: Optional[dict] = result.content["report"]
    assert report is not None
    assert report["chart_png"] is None
    assert (env.work / "sales-analysis.xlsx").exists()
    assert not (env.work / "sales-analysis-chart.png").exists()
    # 不残留渲染中转目录/临时文件
    leftovers = [p.name for p in env.work.iterdir() if p.name.startswith("tmp")]
    assert leftovers == []


def test_no_png_without_aggregate_op(tmp_path: Path):
    """无 aggregate op：不渲染 PNG（chart_png=None），报告 xlsx 照常。"""
    env = _BoundWorkspace(tmp_path)
    xlsx = _make_xlsx(env.work / "sales.xlsx")
    result = _run(
        env,
        file_path=str(xlsx),
        operations=[{"kind": "value_counts", "column": "category"}],
        write_report=True,
    )

    assert result.success is True
    report = result.content["report"]
    assert report["chart_png"] is None
    assert not (env.work / "sales-analysis-chart.png").exists()
    assert (env.work / "sales-analysis.xlsx").exists()
