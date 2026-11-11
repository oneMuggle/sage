from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ._shared import OfficeDocumentSummary, WordMetadataSpec, _constrained_list


class ExcelSheetContent(BaseModel):
    """One Excel sheet."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rows: List[List[str]]
    max_row: int = Field(ge=0)
    max_col: int = Field(ge=0)
    # Item 1.4 公式视图：仅 read_xlsx(include_formulas=True) 时填充，默认
    # None 保持既有 IPC 契约不变（additive 字段，前端可忽略）。
    formulas: Optional[List[str]] = Field(
        default=None,
        description=(
            "公式单元格列表，格式 'B4=SUM(B2:B3)'；有缓存值时为 "
            "'B4=SUM(B2:B3) → 30'。None 表示未启用公式视图或无公式。"
        ),
    )
    note: Optional[str] = Field(
        default=None,
        description="公式缺缓存值时的一行提示（openpyxl 无法计算公式）。",
    )


class OfficeExcelReadResult(BaseModel):
    """Result of POST /api/v1/office/excel/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    sheets: List[ExcelSheetContent]
    # Round 51：core properties 回读（文档无属性时为 None）。
    metadata: Optional[WordMetadataSpec] = None



class ExcelSheetSpec(BaseModel):
    """One sheet in a generated Excel workbook.

    Round 14 新增四项格式控制（全部可选，缺省零变化）：表头样式 /
    冻结首行 / 自适应列宽 / 按列名数字格式。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=31, description="Excel sheet name max length")
    headers: _constrained_list(str, max_length=100) = Field(default_factory=list)
    rows: _constrained_list(_constrained_list(str), max_length=10000) = Field(default_factory=list)
    # 批次 2.3：按列序号给出列宽（index 0 = A 列），单位为 Excel 字符宽度。
    column_widths: Optional[_constrained_list(float, max_length=200)] = Field(
        default=None,
        description="列宽列表，如 [20, 12, 30] 对应 A/B/C 列；None 不设置",
    )
    header_style: bool = Field(
        default=False,
        description="表头行加粗 + 浅灰底(D9D9D9) + 居中",
    )
    freeze_header: bool = Field(
        default=False,
        description="冻结首行（滚动长表时表头保持可见）",
    )
    # Round 31：冻结窗格参数化（A1 记法）。与 freeze_header 同给时本字段优先。
    freeze_panes: Optional[str] = Field(
        default=None,
        max_length=10,
        pattern=r"^[A-Za-z]{1,3}[0-9]{1,7}$",
        description="冻结窗格 A1 记法，如 'B2' 冻结首行+首列；None 不设置",
    )
    autofit_columns: bool = Field(
        default=False,
        description="按内容自适应列宽（显式 column_widths 的列优先）",
    )
    number_formats: Optional[Dict[str, str]] = Field(
        default=None,
        description="按列名映射 Excel 数字格式，如 {'金额': '#,##0.00'}；未知列名忽略",
    )
    # Round 17：条件格式（数据条/色阶/重复值高亮），全部可选。
    conditional_formats: _constrained_list(ExcelConditionalFormatSpec, max_length=50) = Field(
        default_factory=list
    )
    # Round 23：打印设置（方向/缩放/打印区域），全部可选。
    print_setup: Optional[ExcelPrintSetupSpec] = None
    # Round 18：下拉数据验证（状态/分类列防手输错值），全部可选。
    data_validations: _constrained_list(ExcelDataValidationSpec, max_length=20) = Field(
        default_factory=list
    )


class ExcelDataValidationSpec(BaseModel):
    """单条下拉数据验证规则（Round 18）。

    内联列表 formula1 为 '"opt1,opt2,…"' 形式，总长超 255 字符（Excel
    硬限制）时该条跳过（warning），不阻断生成。
    """

    model_config = ConfigDict(extra="forbid")

    range: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Za-z]{1,3}[0-9]+:[A-Za-z]{1,3}[0-9]+$",
        description="应用范围，A1 记法，如 'B2:B100'",
    )
    options: _constrained_list(str, min_length=1, max_length=100) = Field(
        description="下拉选项列表（每项 ≤50 字符）"
    )
    allow_blank: bool = Field(default=True, description="允许空值")
    prompt_title: Optional[str] = Field(default=None, max_length=60)
    prompt: Optional[str] = Field(default=None, max_length=200)


class ExcelConditionalFormatSpec(BaseModel):
    """单条条件格式规则（Round 17）。`rule_type` 三选一，各自可选项不同。

    openpyxl 的 DataBar/ColorScale 由 min/max 端点着色；duplicate 用
    COUNTIF 公式 + 纯色填充。range 为 A1 记法（如 "B2:B100"）。
    """

    model_config = ConfigDict(extra="forbid")

    rule_type: Literal["data_bar", "color_scale", "duplicate", "icon_set"]
    range: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Za-z]{1,3}[0-9]+:[A-Za-z]{1,3}[0-9]+$",
        description="应用范围，A1 记法，如 'B2:B100'",
    )
    icon_style: Optional[Literal[
        "3Arrows",
        "3TrafficLights1",
        "3Signs",
        "3Symbols",
        "4Arrows",
        "4RedToBlack",
        "4Rating",
        "5Arrows",
        "5Rating",
    ]] = Field(
        default="3Arrows",
        description="icon_set 图标样式（Round 19）；其他规则类型忽略",
    )
    color: Optional[str] = Field(
        default=None,
        description="data_bar 条形颜色，6 位 RGB hex（默认 638EC6）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )
    min_color: Optional[str] = Field(
        default=None,
        description="color_scale 最小值端颜色（默认 F8696B 红）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )
    max_color: Optional[str] = Field(
        default=None,
        description="color_scale 最大值端颜色（默认 63BE7B 绿）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )
    fill_color: Optional[str] = Field(
        default=None,
        description="duplicate 重复值填充色（默认 FFFF00 黄）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )


class ExcelPrintSetupSpec(BaseModel):
    """打印设置（Round 23）。全字段可选，None = 不设置。"""

    model_config = ConfigDict(extra="forbid")

    orientation: Optional[Literal["portrait", "landscape"]] = Field(
        default=None, description="纸张方向（默认纵向）"
    )
    fit_to_width: Optional[int] = Field(
        default=None, ge=1, le=20, description="缩放到 N 页宽（1 = 单页宽）"
    )
    print_area: Optional[str] = Field(
        default=None,
        max_length=50,
        pattern=r"^[A-Za-z]{1,3}[0-9]+:[A-Za-z]{1,3}[0-9]+$",
        description="打印区域，A1 记法，如 'A1:F40'",
    )
    title_rows: Optional[str] = Field(
        default=None,
        max_length=20,
        pattern=r"^\$?[0-9]+:\$?[0-9]+$",
        description="每页重复的标题行，如 '1:1'（长表打印每页带表头）",
    )
    # Round 31：打印页边距（厘米），全可选；None 用 Excel 默认。
    margins_cm: Optional[ExcelPrintMarginsSpec] = None
    # Round 32：打印页眉/页脚文本（页码用 &P 占位，Excel HeaderFooter 语法）。
    print_header: Optional[str] = Field(
        default=None, max_length=200, description="打印页眉文本"
    )
    print_footer: Optional[str] = Field(
        default=None, max_length=200, description="打印页脚文本（&P = 页码）"
    )


class ExcelPrintMarginsSpec(BaseModel):
    """打印页边距（厘米，Round 31）。全字段可选。"""

    model_config = ConfigDict(extra="forbid")

    top: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    bottom: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    left: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    right: Optional[float] = Field(default=None, ge=0.0, le=10.0)


class ExcelCellRange(BaseModel):
    """openpyxl Reference 风格的矩形单元格区域（1-based，含端点）。"""

    model_config = ConfigDict(extra="forbid")

    min_col: int = Field(ge=1, le=16384)
    min_row: int = Field(ge=1, le=1048576)
    max_col: int = Field(ge=1, le=16384)
    max_row: int = Field(ge=1, le=1048576)


class ExcelChartSpec(BaseModel):
    """批次 2.1：生成 xlsx 时挂载的 Excel 原生图表（openpyxl Chart）。

    ``sheet`` 缺省挂到第一个 sheet；``data_ref`` 指向图表数据矩形
    （``titles_from_data=True`` 时首行/首列按 ``from_rows`` 解释为系列名）。
    """

    model_config = ConfigDict(extra="forbid")

    sheet: Optional[str] = Field(default=None, max_length=31)
    type: Literal["line", "bar", "pie"]
    anchor: str = Field(min_length=2, max_length=10, description="左上角锚点单元格，如 'A10'")
    data_ref: ExcelCellRange
    titles_from_data: bool = False
    from_rows: bool = False
    categories_ref: Optional[ExcelCellRange] = None
    title: Optional[str] = Field(default=None, max_length=200)


#: Round 50：Excel 与 Word 的核心属性字段同一集合（author→creator 等
#: 映射是格式差异，模型无差异）——别名复用避免双份定义漂移。
ExcelMetadataSpec = WordMetadataSpec


class OfficeExcelGenerateRequest(BaseModel):
    """POST /api/v1/office/excel/generate."""

    model_config = ConfigDict(extra="forbid")

    # P7 (2026-09-14): 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询）
    task_id: Optional[str] = Field(default=None, max_length=100)

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    sheets: _constrained_list(ExcelSheetSpec, min_length=1, max_length=50)
    # 批次 2.1：数据写完后统一挂载的原生图表。
    charts: _constrained_list(ExcelChartSpec, max_length=20) = Field(default_factory=list)
    # Round 50：文档核心属性（与 Word R49 对称；author→creator 等映射
    # 在生成器内完成）。
    metadata: Optional[ExcelMetadataSpec] = Field(
        default=None,
        description="文档核心属性；None 不写（不臆造作者）",
    )


class ChartSeriesSpec(BaseModel):
    """matplotlib 图表的一条数据系列。``x`` 可省略（bar/pie 用 labels 补位）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    x: Optional[List[Union[str, float]]] = Field(
        default=None,
        description="横轴取值（数值或类别文本）；bar/pie 常省略",
    )
    y: _constrained_list(float, min_length=1, max_length=10000)


class ChartSpec(BaseModel):
    """批次 2.1：matplotlib 图表渲染规格（render_chart_png 输入）。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["line", "bar", "hbar", "pie"]
    title: Optional[str] = Field(default=None, max_length=200)
    series: _constrained_list(ChartSeriesSpec, min_length=1, max_length=10)
    labels: Optional[_constrained_list(str, max_length=10000)] = Field(
        default=None,
        description="类别标签（bar/hbar/pie 或 line 分类轴）；series 无 x 时必选",
    )


