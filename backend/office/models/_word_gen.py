from __future__ import annotations

from typing import Dict, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from ._shared import ImageSourceSpec, WordMetadataSpec, _constrained_list

try:
    from pydantic import field_validator
except ImportError:  # pragma: no cover — release/win7 runs v1
    from pydantic import validator as field_validator  # type: ignore


class WordParagraphSpec(BaseModel):
    """One paragraph in a generated Word document.

    Round 20：heading 扩展到 h4/h5，并收紧为 Literal（非法层级在
    模型层拒绝，而非生成期静默跳过）。
    """

    model_config = ConfigDict(extra="forbid")

    heading: Optional[Literal["h1", "h2", "h3", "h4", "h5"]] = Field(
        default=None, description="'h1' | 'h2' | 'h3' | 'h4' | 'h5' or None"
    )
    style: Optional[Literal["bullet", "numbered"]] = Field(
        default=None,
        description="'bullet' 或 'numbered' 列表样式（与 heading 二选一）",
    )
    text: str = Field(min_length=1, max_length=10000)
    # 批次 2.3 样式分级（round a）：作用于该段落全部 runs 的可选样式。
    font_size: Optional[float] = Field(default=None, gt=0, le=400, description="磅值，如 12 / 14.5")
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    color: Optional[str] = Field(
        default=None,
        description="字体颜色，6 位 RGB 十六进制（如 'FF0000'，可带 #）",
    )
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    # Round 9：文中引用（references 条目的 key 列表）。渲染为段落尾部
    # 上标标记（"[1]" / 连续编号合并 "[1-3]"），编号=全文首次出现顺序。
    citations: _constrained_list(str, max_length=10) = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# 参考文献引用（Round 9）：结构化条目 + 确定性 GB/T 7714-2015 格式化。
# 模型仅 pydantic（维持 canary 前提）；格式化在 references.py（零 docx）。
# 简化范围：顺序编码制常用条目形状；不覆盖译者/版次/丛书等边角。
# ──────────────────────────────────────────────────────────────────────

ReferenceType = Literal[
    "journal",
    "book",
    "thesis",
    "conference",
    "report",
    "webpage",
    "patent",
    "standard",
    "newspaper",
]


class ReferenceSpec(BaseModel):
    """一条结构化参考文献（引用引擎的输入单元）。

    ``key`` 供 ``paragraphs[].citations`` 回链；格式化所需字段按
    ``ref_type`` 选用（如 journal 用 source/volume/issue/pages，
    book 用 address/publisher）。``language`` 缺省时按 title 是否含
    CJK 自动判定（影响"等/et al"截断词）。
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    ref_type: ReferenceType = "journal"
    title: str = Field(min_length=1, max_length=500)
    authors: _constrained_list(str, max_length=50) = Field(default_factory=list)
    year: Optional[str] = Field(default=None, max_length=20)
    source: Optional[str] = Field(
        default=None, max_length=300, description="刊名/会议名/机构/报纸名"
    )
    volume: Optional[str] = Field(default=None, max_length=30)
    issue: Optional[str] = Field(default=None, max_length=30)
    pages: Optional[str] = Field(default=None, max_length=50)
    publisher: Optional[str] = Field(default=None, max_length=300)
    address: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=2000)
    doi: Optional[str] = Field(default=None, max_length=200)
    access_date: Optional[str] = Field(
        default=None, max_length=30, description="电子资源引用日期，如 2026-09-11"
    )
    language: Optional[Literal["zh", "en"]] = Field(
        default=None, description="缺省按 title CJK 自动判定"
    )


class BibliographySpec(BaseModel):
    """文末参考文献节样式（Round 9）。全字段可选。"""

    model_config = ConfigDict(extra="forbid")

    heading_text: str = Field(default="参考文献", max_length=50)
    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    hanging_indent_cm: Optional[float] = Field(default=None, ge=0.0, le=5.0)


class WordTocSpec(BaseModel):
    """目录域设置（Round 13）。

    TOC 域由 Word/WPS/LibreOffice 按标题样式渲染（打开后更新域/F9 生成），
    生成器只负责插入域与占位提示——与"标题编号交给引擎"同一思路。
    """

    model_config = ConfigDict(extra="forbid")

    heading_text: str = Field(default="目录", max_length=50)
    levels: str = Field(
        default="1-3",
        pattern=r"^[1-9]-[1-9]$",
        description="收录标题级别范围，如 '1-3'（TOC \\o 开关）",
    )
    placeholder_text: str = Field(
        default='（目录：在 Word 中按 F9 或右键"更新域"生成）',
        max_length=200,
        description="域未更新时的占位提示",
    )

    @field_validator("levels")
    @classmethod
    def _check_level_order(cls, value: str) -> str:
        first, last = value.split("-")
        if int(first) > int(last):
            raise ValueError("levels 起始级别不能大于结束级别")
        return value

    def level_range(self) -> Tuple[int, int]:
        first, last = self.levels.split("-")
        return int(first), int(last)


class BibTeXParseRequest(BaseModel):
    """POST /api/v1/office/word/parse-bibtex（Round 9）。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000_000, description=".bib 文件内容")


class BibTeXParseResponse(BaseModel):
    """BibTeX 解析结果（Round 9）。条目可直接传入 word generate references。"""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    references: _constrained_list(ReferenceSpec, max_length=200)




class WordCellMergeSpec(BaseModel):
    """表格合并区域（Round 8）：0-based 含端点矩形（与 rows/headers 下标
    心智模型一致，区别于 ExcelCellRange 的 1-based）。生成期校验越界。"""

    model_config = ConfigDict(extra="forbid")

    min_row: int = Field(ge=0)
    max_row: int = Field(ge=0)
    min_col: int = Field(ge=0)
    max_col: int = Field(ge=0)


class WordTableSpec(BaseModel):
    """One table in a generated Word document.

    Round 8 新增：表题注（自动 "表N　caption"）、三线表样式、表头跨页
    重复、列宽、合并单元格；全部可选，None/false 保持既有默认网格行为。
    """

    model_config = ConfigDict(extra="forbid")

    headers: _constrained_list(str, min_length=1, max_length=50)
    rows: _constrained_list(_constrained_list(str), max_length=1000) = Field(default_factory=list)
    caption: Optional[str] = Field(default=None, max_length=200)
    style: Optional[Literal["grid", "three_line"]] = Field(
        default=None,
        description="None/'grid' = 默认网格；'three_line' = 学术三线表",
    )
    header_repeat: bool = Field(default=False, description="表头跨页重复")
    column_widths_cm: Optional[_constrained_list(float, max_length=50)] = Field(
        default=None,
        description="各列列宽（厘米）；None 不设置，长度须等于列数",
    )
    # Round 36：表头行样式（加粗 + 浅灰底 + 居中），与 Excel header_style 对称。
    header_style: bool = Field(
        default=False, description="表头行加粗 + 浅灰底(D9D9D9) + 居中"
    )
    merges: _constrained_list(WordCellMergeSpec, max_length=200) = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Word 版式规范（Round 7 FormatSpec —— "版式即配置"）
#
# 设计约定：
# - 所有字段 Optional，None = 该项不设置（生成器保持既有默认行为），
#   保证不传 ``format_spec`` 时生成结果与历史版本逐字节等价；
# - 模型只依赖 pydantic（不含 docx），维持
#   ``scripts/verify-office-paths.py`` canary "models 仅依赖 pydantic"
#   的前提；docx 侧的应用逻辑在 ``word_layout.py``；
# - 长度/数值边界为合理性钳制（防 LLM 传 9999 磅字号），不是排版学约束。
# ──────────────────────────────────────────────────────────────────────


class WordPageMarginsSpec(BaseModel):
    """页边距（厘米）。None 的边保持 Word 默认。"""

    model_config = ConfigDict(extra="forbid")

    top: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    bottom: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    left: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    right: Optional[float] = Field(default=None, ge=0.0, le=10.0)


class WordPageSetupSpec(BaseModel):
    """页面设置：纸张/方向/页边距。"""

    model_config = ConfigDict(extra="forbid")

    size: Optional[Literal["A4", "letter"]] = Field(default=None)
    orientation: Optional[Literal["portrait", "landscape"]] = Field(default=None)
    margins_cm: Optional[WordPageMarginsSpec] = Field(default=None)
    # Round 53：节内页码格式/起始号（w:pgNumType，论文前置罗马页码场景）
    page_number_format: Optional[
        Literal["decimal", "upperRoman", "lowerRoman", "upperLetter", "lowerLetter"]
    ] = Field(default=None)
    page_number_start: Optional[int] = Field(default=None, ge=0)
    # Round 58：该节脚注编号每节重排（w:footnotePr/numRestart=eachSect；
    # 论文/书籍分章脚注场景）。默认 False 零触碰。
    footnote_restart_each_section: bool = Field(default=False)


class WordBodyStyleSpec(BaseModel):
    """正文（Normal 样式）默认排版。行距为倍数（如 1.5 倍）。"""

    model_config = ConfigDict(extra="forbid")

    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    line_spacing: Optional[float] = Field(default=None, ge=1.0, le=3.0)
    first_line_indent_cm: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    space_after_pt: Optional[float] = Field(default=None, ge=0.0, le=48.0)
    align: Optional[Literal["left", "center", "right", "justify"]] = None


class WordHeadingStyleSpec(BaseModel):
    """标题样式覆盖（作用于 Title / Heading 1-3 样式定义本身）。"""

    model_config = ConfigDict(extra="forbid")

    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    bold: Optional[bool] = None
    color: Optional[str] = Field(
        default=None,
        description="字体颜色，6 位 RGB 十六进制（如 '2F5496'，可带 #）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    space_before_pt: Optional[float] = Field(default=None, ge=0.0, le=96.0)
    space_after_pt: Optional[float] = Field(default=None, ge=0.0, le=96.0)


class WordHeaderFooterSpec(BaseModel):
    """页眉/页脚设置。``page_number`` 仅在 footer 上生效（居中 PAGE 域）。"""

    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(default=None, max_length=200)
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    page_number: bool = False


class WordSectionBreakSpec(BaseModel):
    """分节设置（Round 26）：start_paragraph 前插入 NEW_PAGE 分节，
    新节应用 page_setup（横排宽表/财务页场景）。复用 WordPageSetupSpec。
    """

    model_config = ConfigDict(extra="forbid")

    start_paragraph: int = Field(ge=0, description="该 0-based 段落下标起进入新节")
    page_setup: WordPageSetupSpec = Field(description="新节的页面设置")


class WordFormatSpec(BaseModel):
    """Word 文档版式规范。

    传入 ``generate_docx`` 后由 ``word_layout.apply_format_spec`` 以确定性
    代码注入 styles.xml / document.xml —— 格式要求不再依赖 LLM 在 prompt
    里"口头约定"。全字段可选，None 项不触碰。
    """

    model_config = ConfigDict(extra="forbid")

    page: Optional[WordPageSetupSpec] = None
    body: Optional[WordBodyStyleSpec] = None
    # Round 20：headings 键扩展到 h4/h5（Heading 4/5 样式覆盖）。
    headings: Optional[
        Dict[Literal["h1", "h2", "h3", "h4", "h5"], WordHeadingStyleSpec]
    ] = None
    title: Optional[WordHeadingStyleSpec] = None
    header: Optional[WordHeaderFooterSpec] = None
    footer: Optional[WordHeaderFooterSpec] = None
    # Round 8：多级标题自动编号（h1-h5 计数器，字面 "N.M.K" 文本前缀）。
    # Round 20：编号级别扩展到 5 级。
    numbering: bool = Field(default=False, description="为 h1-h5 生成 1 / 1.1 / 1.1.1 … 编号前缀")
    # Round 9：文末参考文献节样式。None 时仍生成参考文献节（默认样式），
    # 仅当请求不带 references 时该子项才完全不生效。
    bibliography: Optional[BibliographySpec] = None
    # Round 13：目录域。None = 不插入目录。
    toc: Optional[WordTocSpec] = None
    # Round 33：首页不同页眉页脚（封面页场景）。启用后首页用
    # first_page_header/first_page_footer 的独立内容。
    first_page_different: bool = Field(
        default=False, description="启用首页不同的页眉页脚"
    )
    first_page_header: Optional[WordHeaderFooterSpec] = None
    first_page_footer: Optional[WordHeaderFooterSpec] = None
    # Round 34：奇偶页不同页眉页脚（书籍排版）。启用后偶数页用
    # even_page_header/even_page_footer 的独立内容。
    odd_even_pages: bool = Field(
        default=False, description="启用奇偶页不同的页眉页脚"
    )
    even_page_header: Optional[WordHeaderFooterSpec] = None
    even_page_footer: Optional[WordHeaderFooterSpec] = None
    # Round 26：横排/分节。每个 break 在 start_paragraph（0-based）前
    # 插入 NEW_PAGE 分节并对新节应用 page_setup；按列表顺序依次生效。
    section_breaks: _constrained_list(WordSectionBreakSpec, max_length=20) = Field(
        default_factory=list
    )
    # Round 42：图目录/表目录（TOC \c 收录 SEQ 题注；None = 不插入）。
    figure_index: Optional[WordIndexSpec] = None
    table_index: Optional[WordIndexSpec] = None


class WordIndexSpec(BaseModel):
    r"""图目录/表目录设置（Round 42）。

    TOF 域（``TOC \h \z \c "<图|表>"``）由 Word 收录 SEQ 题注段；
    生成器插入域与静态缓存条目（无页码——由渲染器/COM 刷新域计算），
    与 R13 目录域同一思路。
    """

    model_config = ConfigDict(extra="forbid")

    heading_text: str = Field(default="图目录", max_length=50)
    placeholder_text: str = Field(
        default='（图目录：在 Word 中按 F9 或右键"更新域"生成）',
        max_length=200,
        description="域未更新时的占位提示",
    )


class WordImageSpec(ImageSourceSpec):
    """Word 文档插图（Round 8）：在 ImageSourceSpec 基础上支持行内放置与题注。

    ``after_paragraph`` 为 ``paragraphs`` 的 0-based 下标，图片插入到该段落
    之后；None = 文末追加（Round 7 之前的既有行为）。越界在生成期钳到末尾。
    ``caption`` 非空时生成居中题注（"图N　caption"），图号全文独立计数。
    """

    model_config = ConfigDict(extra="forbid")

    caption: Optional[str] = Field(default=None, max_length=200)
    after_paragraph: Optional[int] = Field(default=None, ge=0)


class OfficeWordGenerateRequest(BaseModel):
    """POST /api/v1/office/word/generate."""

    model_config = ConfigDict(extra="forbid")

    # P7 (2026-09-14): 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询）
    task_id: Optional[str] = Field(default=None, max_length=100)

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: _constrained_list(WordParagraphSpec, max_length=5000) = Field(default_factory=list)
    tables: _constrained_list(WordTableSpec, max_length=100) = Field(default_factory=list)
    # 批次 2.1：可选插图。Round 8 起为 WordImageSpec——支持行内放置
    # （after_paragraph）与题注（caption）；旧 payload（仅 source/宽高）兼容。
    # Union 子类在前：dict 输入由 WordImageSpec 承接（新字段生效），
    # 既有调用方构造的 ImageSourceSpec 父类实例也继续被接受。
    images: _constrained_list(Union[WordImageSpec, ImageSourceSpec], max_length=20) = Field(
        default_factory=list
    )
    # Round 7 FormatSpec：显式版式（页边距/正文/标题/页眉页脚）。
    format_spec: Optional[WordFormatSpec] = Field(
        default=None,
        description="版式规范；None 保持默认版式（行为与历史版本一致）",
    )
    # Round 49：文档核心属性（core properties，期刊/公文归档要求）。
    metadata: Optional[WordMetadataSpec] = Field(
        default=None,
        description="文档核心属性；None 只写 title（取请求 title）",
    )
    # Round 9：结构化参考文献 + 文中引用标记。带 references 时文末自动
    # 生成参考文献节；paragraphs[].citations 按 key 回链，编号=首现顺序。
    references: _constrained_list(ReferenceSpec, max_length=200) = Field(default_factory=list)
    citation_style: Literal["gbt7714", "apa"] = Field(
        default="gbt7714",
        description="参考文献格式；gbt7714=GB/T 7714-2015 顺序编码制",
    )
    font_family: Optional[str] = Field(
        default=None,
        description="中文正文字体名（如'宋体'/'微软雅黑'/'等线'），默认宋体",
    )
    ascii_font: Optional[str] = Field(
        default=None,
        description="西文字体名，默认 Times New Roman",
    )


# ──────────────────────────────────────────────────────────────────────
# Word 格式 Linter（Round 10）：对照 FormatSpec 校验任意 .docx。
# 规则与生成器对偶——spec 未提供的项不产生规则（None = 不检查）。
# ──────────────────────────────────────────────────────────────────────


class WordLintIssue(BaseModel):
    """单条格式违规。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(
        min_length=1, max_length=80,
        description="规则标识，如 page/margins、caption/sequence",
    )
    severity: Literal["error", "warning"]
    message: str = Field(min_length=1, max_length=1000, description="含实测值 vs 期望值")
    fix_hint: str = Field(default="", max_length=1000, description="中文修复建议")


class WordLintResult(BaseModel):
    """Linter 汇总结果。``ok`` = 无 error 级违规。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    issue_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    checked_rules: _constrained_list(str, max_length=100) = Field(default_factory=list)
    issues: _constrained_list(WordLintIssue, max_length=500) = Field(default_factory=list)


class WordLintRequest(BaseModel):
    """POST /api/v1/office/word/lint。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000, description="待校验 .docx 路径")
    format_spec: WordFormatSpec
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Reject files larger than this"
    )


class WordRepairResult(BaseModel):
    """自动修复结果（Round 12）。``ok`` = 修复后复检无 error 级违规。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    repaired_rules: _constrained_list(str, max_length=100) = Field(
        default_factory=list, description="本次修复的规则 rule_id 列表"
    )
    output_path: str = Field(min_length=1, max_length=2000, description="修复后文件路径")
    overwrite: bool = Field(default=False, description="是否原地替换了原文件")
    remaining: WordLintResult = Field(description="修复后的复检结果")


class WordRepairRequest(BaseModel):
    """POST /api/v1/office/word/repair。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000, description="待修复 .docx 路径")
    format_spec: WordFormatSpec
    overwrite: bool = Field(
        default=False,
        description="false（默认）= 修复结果写 <stem>-repaired.docx 新文件；true = 原地原子替换",
    )
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Reject files larger than this"
    )
<<<<<<< HEAD

# pydantic v1 在类创建时解析注解；以下模型引用了后置定义的类，
# 需在全部类定义后显式解析前向引用（v2 走 model_rebuild，v1 走 update_forward_refs）。
if hasattr(WordFormatSpec, "model_rebuild"):
    WordFormatSpec.model_rebuild()
else:
    WordFormatSpec.update_forward_refs()
=======
>>>>>>> origin/main
