"""M6d：Excel 原生图表的读侧数据提取（类别 / 系列名 / 系列值）。

`_extract_sheet_charts` 原先只有 `type/series(数量)/title`；这里把
类别与系列值也读出来（≤50 点/系列），供结构化预览画迷你图。
兼容：
- 同表 / 跨表引用（含需要引号的表名）；
- 引用无法解析时回退缓存值；两者都缺失时给空列表而不是报错。
"""

from __future__ import annotations

from pathlib import Path

from backend.office.excel import read_xlsx

MAX_POINTS = 50


def _make_chart_book(
    path: Path,
    *,
    row_count: int = 3,
    data_sheet: str | None = None,
    with_title: bool = True,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "报表"
    data_ws = workbook.create_sheet(data_sheet) if data_sheet else worksheet
    data_ws["A1"] = "月份"
    data_ws["B1"] = "数量"
    for i in range(row_count):
        data_ws.cell(row=2 + i, column=1, value=f"Q{i + 1}")
        data_ws.cell(row=2 + i, column=2, value=i + 1)
    chart = BarChart()
    if with_title:
        chart.title = "销售"
    chart.add_data(
        Reference(data_ws, min_col=2, min_row=1, max_row=1 + row_count),
        titles_from_data=True,
    )
    chart.set_categories(
        Reference(data_ws, min_col=1, min_row=2, max_row=1 + row_count)
    )
    worksheet.add_chart(chart, "D2")
    workbook.save(str(path))
    return path


def test_excel_chart_exposes_categories_and_series_values(tmp_path: Path) -> None:
    path = _make_chart_book(tmp_path / "chart.xlsx")

    result = read_xlsx(path)
    chart = result.sheets[0].charts[0]

    assert chart["series"] == 1
    assert chart["categories"] == ["Q1", "Q2", "Q3"]
    items = chart["series_items"]
    assert len(items) == 1
    assert items[0]["name"] == "数量"
    assert items[0]["values"] == [1.0, 2.0, 3.0]
    assert chart["truncated"] is False


def test_excel_chart_resolves_quoted_cross_sheet_reference(tmp_path: Path) -> None:
    path = _make_chart_book(tmp_path / "chart.xlsx", data_sheet="Data Sheet")

    result = read_xlsx(path)
    chart = result.sheets[0].charts[0]

    assert chart["categories"] == ["Q1", "Q2", "Q3"]
    assert chart["series_items"][0]["values"] == [1.0, 2.0, 3.0]


def test_excel_chart_caps_points_and_flags_truncation(tmp_path: Path) -> None:
    path = _make_chart_book(tmp_path / "chart.xlsx", row_count=MAX_POINTS + 10)

    result = read_xlsx(path)
    chart = result.sheets[0].charts[0]

    assert chart["truncated"] is True
    assert len(chart["series_items"][0]["values"]) == MAX_POINTS
    assert len(chart["categories"]) == MAX_POINTS


def test_excel_chart_unresolvable_reference_yields_empty_values(tmp_path: Path) -> None:
    path = _make_chart_book(tmp_path / "chart.xlsx")

    # 读入后篡改系列引用指向不存在的表，再原样保存 —— 模拟外部工具写出
    # 的坏引用。读取侧必须降级为空列表而不是抛异常。
    from openpyxl import load_workbook

    workbook = load_workbook(str(path))
    chart = workbook["报表"]._charts[0]
    chart.series[0].val.numRef.f = "Missing!$B$2:$B$4"
    workbook.save(str(path))

    result = read_xlsx(path)
    chart_payload = result.sheets[0].charts[0]

    assert chart_payload["series_items"][0]["values"] == []
    assert chart_payload["type"] == "BarChart"


def test_chart_reference_range_is_capped_before_materializing(
    tmp_path: Path, monkeypatch
) -> None:
    from openpyxl import Workbook

    from backend.office.excel import MAX_CHART_REF_CELLS, _resolve_reference

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Data"
    calls: dict = {}
    real_iter_rows = worksheet.iter_rows

    def _spy(**kwargs):
        calls.update(kwargs)
        return real_iter_rows(**kwargs)

    monkeypatch.setattr(worksheet, "iter_rows", _spy)

    # 用户可控引用可以是整列（1048576 行）——必须在物化前裁剪。
    values = _resolve_reference(workbook, "'Data'!$A$1:$A$1048576")

    assert len(values) <= MAX_CHART_REF_CELLS
    assert calls["max_row"] <= MAX_CHART_REF_CELLS


def test_chart_ref_values_falls_back_to_num_cache_for_categories() -> None:
    from backend.office.excel import _chart_ref_values

    class _Point:
        v = 7

    class _Cache:
        pt = [_Point(), _Point()]

    class _Ref:
        numCache = _Cache()  # noqa: N815 — 镜像 openpyxl 的 XML 属性名

    # 纯缓存的数值类别存于 numCache；numeric=False 也不应整列为空。
    assert _chart_ref_values(None, _Ref(), numeric=False) == [7, 7]
