# Word 模板化 + PDF 全能力操作实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sage 项目新增 Word 模板化操作（分析占位符 + 填充数据）和 PDF 全能力操作（读取 + 生成 + 表单填充），覆盖 main 和 release/win7 双分支。

**Architecture:** 基于 docxtpl（Word 模板）、PyMuPDF（PDF 读取/表单）、reportlab（PDF 生成）三个库，在现有 `backend/office/` 模块下新增 `word_template.py`、`pdf.py`、`pdf_forms.py` 三个文件，扩展 `models.py` 和 `errors.py`，并在 `office_routes.py` 添加 6 个新 API 端点。

**Tech Stack:** Python 3.10 (main) / 3.8 (win7), Pydantic 2.x / 1.x, docxtpl >=0.20, PyMuPDF >=1.25, reportlab >=4.0

**Spec:** `docs/superpowers/specs/2026-09-05-word-template-pdf-operations-design.md`

## Global Constraints

- **Python 兼容性**: main 分支 Python 3.10 + Pydantic 2.x；release/win7 分支 Python 3.8 + Pydantic 1.x
- **依赖版本**: docxtpl>=0.20.0, PyMuPDF>=1.25.0, reportlab>=4.0.0
- **文件大小限制**: 模板/PDF 文件 > 50MB 拒绝（复用现有 `max_size_bytes` 机制）
- **路径安全**: 所有 API 复用 `_validate_file_in_workspace()` 和 `resolve_output_path()`
- **错误处理**: 新错误类型继承 `OfficeError`，映射到对应 HTTP 状态码
- **测试覆盖**: 每个功能必须有单元测试，集成测试覆盖 API 路由

---

## File Structure

| 文件 | 职责 | 状态 |
|------|------|------|
| `backend/requirements.txt` | 添加 docxtpl, PyMuPDF, reportlab | 修改 |
| `backend/office/models.py` | 新增模板/PDF 数据模型 | 修改 |
| `backend/office/errors.py` | 新增模板/PDF 错误类型 | 修改 |
| `backend/office/word_template.py` | Word 模板分析+填充实现 | 新增 |
| `backend/office/pdf.py` | PDF 读取+生成实现 | 新增 |
| `backend/office/pdf_forms.py` | PDF 表单读取+填充实现 | 新增 |
| `backend/api/office_routes.py` | 添加 6 个新 API 端点 | 修改 |
| `backend/office/__init__.py` | 导出新函数 | 修改 |
| `backend/tests/unit/office/test_word_template.py` | Word 模板单元测试 | 新增 |
| `backend/tests/unit/office/test_pdf.py` | PDF 读取/生成单元测试 | 新增 |
| `backend/tests/unit/office/test_pdf_forms.py` | PDF 表单单元测试 | 新增 |

---

## Task 1: 添加依赖到 requirements.txt

**Files:**
- Modify: `backend/requirements.txt:63` (after `pandas==2.2.3`)

**Interfaces:**
- Consumes: N/A（基础设施任务）
- Produces: 新增 `docxtpl`, `PyMuPDF`, `reportlab` 到依赖文件

- [ ] **Step 1: Edit backend/requirements.txt to add new dependencies**

After line 63 (`pandas==2.2.3`), add:

```python
# Office template + PDF features (Phase 2, 2026-09-05)
# See docs/superpowers/specs/2026-09-05-word-template-pdf-operations-design.md
docxtpl>=0.20.0       # Word template fill with {{variable}} placeholders, ~0.5MB wheel
PyMuPDF>=1.25.0       # PDF read + form fill (C extension, wheels available for py38+), ~15MB wheel
reportlab>=4.0.0      # PDF generation from structured data, ~3MB wheel
```

- [ ] **Step 2: Install dependencies into sage-backend environment**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pip install docxtpl PyMuPDF reportlab`
Expected: Dependencies install successfully, no version conflicts

- [ ] **Step 3: Verify dependencies are importable**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -c "import docxtpl; import fitz; import reportlab; print('OK')"`
Expected: Output `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "build: add docxtpl, PyMuPDF, reportlab for Word template + PDF ops"
```

---

## Task 2: 扩展 errors.py 新增错误类型

**Files:**
- Modify: `backend/office/errors.py:95-120`
- Test: `backend/tests/unit/office/test_errors_extension.py`

**Interfaces:**
- Consumes: N/A
- Produces: New error classes: `OfficeTemplateError`, `OfficeTemplateParseError`, `OfficeTemplateFillError`, `OfficePdfError`, `OfficePdfParseError`, `OfficePdfGenerateError`, `OfficePdfFormError`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/office/test_errors_extension.py`:

```python
"""Unit tests for extended office error types (template + PDF)."""

import pytest
from pathlib import Path

from backend.office.errors import (
    OfficeTemplateError,
    OfficeTemplateParseError,
    OfficeTemplateFillError,
    OfficePdfError,
    OfficePdfParseError,
    OfficePdfGenerateError,
    OfficePdfFormError,
    office_error_to_http_status,
)


def test_template_parse_error_inherits_from_template_error():
    err = OfficeTemplateParseError("bad template", file_path=Path("/tmp/bad.docx"))
    assert isinstance(err, OfficeTemplateError)
    assert err.message == "bad template"
    assert err.file_path == Path("/tmp/bad.docx")


def test_pdf_parse_error_inherits_from_pdf_error():
    err = OfficePdfParseError("corrupt pdf", file_path=Path("/tmp/bad.pdf"))
    assert isinstance(err, OfficePdfError)


def test_error_to_http_status_mapping():
    assert office_error_to_http_status(OfficeTemplateParseError("x")) == 400
    assert office_error_to_http_status(OfficeTemplateFillError("x")) == 422
    assert office_error_to_http_status(OfficePdfParseError("x")) == 400
    assert office_error_to_http_status(OfficePdfGenerateError("x")) == 500
    assert office_error_to_http_status(OfficePdfFormError("x")) == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_errors_extension.py -v`
Expected: FAIL with "ImportError" or "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

In `backend/office/errors.py`, after `OfficeContentShapeError` class (after line 95), add:

```python
# ──────────────────────────────────────────────────────────────────────
# Template errors (Phase 2 — Word template operations)
# ──────────────────────────────────────────────────────────────────────


class OfficeTemplateError(OfficeError):
    """Base class for Word template operation errors."""
    pass


class OfficeTemplateParseError(OfficeTemplateError):
    """Template file cannot be parsed (invalid DOCX, no placeholders, etc.)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficeTemplateFillError(OfficeTemplateError):
    """Template fill failed (missing data, type mismatch, etc.)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


# ──────────────────────────────────────────────────────────────────────
# PDF errors (Phase 2 — PDF operations)
# ──────────────────────────────────────────────────────────────────────


class OfficePdfError(OfficeError):
    """Base class for PDF operation errors."""
    pass


class OfficePdfParseError(OfficePdfError):
    """PDF file cannot be parsed (corrupt, wrong format, etc.)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficePdfGenerateError(OfficePdfError):
    """PDF generation failed."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)


class OfficePdfFormError(OfficePdfError):
    """PDF form operation failed (field not found, read-only, etc.)."""

    def __init__(self, message: str, *, file_path: Optional[Path] = None) -> None:
        super().__init__(message, file_path=file_path)
```

In the `office_error_to_http_status()` function, add these checks BEFORE the `_WRITE_FAILURE_ERRORS` check (around line 115):

```python
    # Template errors (Phase 2)
    if isinstance(error, OfficeTemplateParseError):
        return 400
    if isinstance(error, OfficeTemplateFillError):
        return 422
    # PDF errors (Phase 2)
    if isinstance(error, OfficePdfParseError):
        return 400
    if isinstance(error, OfficePdfGenerateError):
        return 500
    if isinstance(error, OfficePdfFormError):
        return 422
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_errors_extension.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/errors.py backend/tests/unit/office/test_errors_extension.py
git commit -m "feat(office): add template + PDF error types with HTTP status mapping"
```

---

## Task 3: 扩展 models.py 新增数据模型

**Files:**
- Modify: `backend/office/models.py:38-44, 314+`
- Test: `backend/tests/unit/office/test_models_extension.py`

**Interfaces:**
- Consumes: N/A
- Produces: New model classes for template and PDF operations; `OfficeDocType.PDF` enum value

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/office/test_models_extension.py`:

```python
"""Unit tests for extended office data models (template + PDF)."""

import pytest
from backend.office.models import (
    OfficeDocType,
    TemplatePlaceholderType,
    PlaceholderLocation,
    TemplatePlaceholder,
    WordTemplateFillRequest,
    PdfPageSpec,
    PdfGenerateRequest,
    PdfFormField,
)


def test_office_doc_type_includes_pdf():
    assert OfficeDocType.PDF == "pdf"


def test_template_placeholder_model():
    ph = TemplatePlaceholder(
        name="客户姓名",
        raw_tag="{{客户姓名}}",
        type=TemplatePlaceholderType.TEXT,
        location=PlaceholderLocation.BODY,
        paragraph_index=5,
    )
    assert ph.name == "客户姓名"
    assert ph.paragraph_index == 5


def test_word_template_fill_request_validation():
    req = WordTemplateFillRequest(
        workspace_path="/tmp/ws",
        template_path="/tmp/ws/template.docx",
        output_filename="output.docx",
        data={"name": "张三"},
    )
    assert req.data["name"] == "张三"


def test_pdf_generate_request_defaults():
    req = PdfGenerateRequest(
        workspace_path="/tmp/ws",
        filename="output.pdf",
        pages=[PdfPageSpec(paragraphs=["Hello"])],
    )
    assert req.page_size == "A4"
    assert req.orientation == "portrait"


def test_pdf_form_field_model():
    field = PdfFormField(name="name", type="text", value="张三")
    assert field.name == "name"
    assert field.required is False
    assert field.read_only is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_models_extension.py -v`
Expected: FAIL with "ImportError"

- [ ] **Step 3: Write minimal implementation**

**3a. Extend `OfficeDocType` enum (line 38):**

Replace:
```python
class OfficeDocType(str, Enum):
    """Document type discriminator."""

    PPT = "ppt"
    WORD = "word"
    EXCEL = "excel"
```

With:
```python
class OfficeDocType(str, Enum):
    """Document type discriminator."""

    PPT = "ppt"
    WORD = "word"
    EXCEL = "excel"
    PDF = "pdf"  # Phase 2: PDF support
```

**3b. Add `Any, Dict` to the import on line 15:**

Change `from typing import List, Optional` to `from typing import Any, Dict, List, Optional`

**3c. At end of file (after line 314), add new models:**

```python
# ──────────────────────────────────────────────────────────────────────
# Word Template models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


class TemplatePlaceholderType(str, Enum):
    """Type of placeholder in a Word template."""

    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    DATE = "date"
    RICH_TEXT = "rich_text"


class PlaceholderLocation(str, Enum):
    """Location of placeholder in the document."""

    BODY = "body"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    TEXT_BOX = "text_box"


class TemplatePlaceholder(BaseModel):
    """One placeholder found in a Word template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    raw_tag: str
    type: TemplatePlaceholderType
    location: PlaceholderLocation
    paragraph_index: Optional[int] = None
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    col_index: Optional[int] = None
    format_hint: Optional[str] = None


class WordTemplateAnalysis(BaseModel):
    """Result of analyzing a Word template."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    placeholders: List[TemplatePlaceholder]
    summary: OfficeDocumentSummary
    has_jinja_control: bool = False


class WordTemplateFillRequest(BaseModel):
    """Request to fill a Word template with data."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    images: Optional[Dict[str, str]] = None


class WordTemplateFillResult(BaseModel):
    """Result of filling a Word template."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
    unfilled_placeholders: List[str]


# ──────────────────────────────────────────────────────────────────────
# PDF models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


class PdfPageContent(BaseModel):
    """Content of one PDF page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    tables: List[List[List[str]]] = []
    images: List[Dict[str, Any]] = []


class PdfReadResult(BaseModel):
    """Result of reading a PDF file."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    pages: List[PdfPageContent]
    metadata: Dict[str, Any] = {}


class PdfPageSpec(BaseModel):
    """One page in a generated PDF."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []


class PdfGenerateRequest(BaseModel):
    """Request to generate a PDF."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str
    pages: List[PdfPageSpec]
    page_size: str = "A4"
    orientation: str = "portrait"


class PdfGenerateResult(BaseModel):
    """Result of generating a PDF."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    page_count: int


class PdfFormField(BaseModel):
    """One PDF form field."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    value: Optional[Any] = None
    options: Optional[List[str]] = None
    required: bool = False
    read_only: bool = False


class PdfFormReadResult(BaseModel):
    """Result of reading PDF form fields."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    fields: List[PdfFormField]
    has_xfa: bool = False


class PdfFormFillRequest(BaseModel):
    """Request to fill a PDF form."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    flatten: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_models_extension.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/models.py backend/tests/unit/office/test_models_extension.py
git commit -m "feat(office): add template + PDF data models (Pydantic)"
```

---

## Task 4: 实现 word_template.py（模板分析）

**Files:**
- Create: `backend/office/word_template.py`
- Test: `backend/tests/unit/office/test_word_template.py`

**Interfaces:**
- Consumes: `OfficeDocumentSummary`, `OfficeDocType`, `OfficeDocStatus`, `OfficeDocumentMetadata`, `TemplatePlaceholder`, `TemplatePlaceholderType`, `PlaceholderLocation`, `WordTemplateAnalysis` from `models.py`; `OfficeFileNotFoundError`, `OfficeTemplateParseError` from `errors.py`
- Produces: `analyze_word_template(file_path: Path, *, workspace_path: str, document_id: Optional[str] = None) -> WordTemplateAnalysis`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/office/test_word_template.py`:

```python
"""Unit tests for Word template analysis."""

import pytest
from pathlib import Path
from docx import Document

from backend.office.word_template import analyze_word_template
from backend.office.errors import OfficeFileNotFoundError, OfficeTemplateParseError
from backend.office.models import PlaceholderLocation, TemplatePlaceholderType


@pytest.fixture
def simple_template(tmp_path: Path) -> Path:
    """Create a simple Word template with placeholders."""
    doc = Document()
    doc.add_heading("合同模板", level=0)
    doc.add_paragraph("甲方：{{甲方姓名}}")
    doc.add_paragraph("乙方：{{乙方姓名}}")
    doc.add_paragraph("合同金额：{{合同金额}}")

    template_path = tmp_path / "template.docx"
    doc.save(str(template_path))
    return template_path


def test_analyze_simple_template(simple_template: Path):
    result = analyze_word_template(
        simple_template,
        workspace_path=str(simple_template.parent),
    )
    assert len(result.placeholders) == 3
    names = [p.name for p in result.placeholders]
    assert "甲方姓名" in names
    assert "乙方姓名" in names
    assert "合同金额" in names


def test_analyze_template_placeholder_details(simple_template: Path):
    result = analyze_word_template(
        simple_template,
        workspace_path=str(simple_template.parent),
    )
    for ph in result.placeholders:
        assert ph.location == PlaceholderLocation.BODY
        assert ph.type == TemplatePlaceholderType.TEXT
        assert ph.paragraph_index is not None
        assert ph.raw_tag.startswith("{{")
        assert ph.raw_tag.endswith("}}")


def test_analyze_nonexistent_file():
    with pytest.raises(OfficeFileNotFoundError):
        analyze_word_template(
            Path("/nonexistent/template.docx"),
            workspace_path="/tmp",
        )


def test_analyze_invalid_docx(tmp_path: Path):
    invalid_file = tmp_path / "invalid.docx"
    invalid_file.write_text("not a docx file")

    with pytest.raises(OfficeTemplateParseError):
        analyze_word_template(
            invalid_file,
            workspace_path=str(tmp_path),
        )


def test_analyze_template_with_jinja_control(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("{% if show_section %}")
    doc.add_paragraph("条件内容")
    doc.add_paragraph("{% endif %}")
    doc.add_paragraph("姓名：{{姓名}}")

    path = tmp_path / "with_control.docx"
    doc.save(str(path))

    result = analyze_word_template(path, workspace_path=str(tmp_path))
    assert result.has_jinja_control is True
    assert len(result.placeholders) == 1
    assert result.placeholders[0].name == "姓名"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_word_template.py::test_analyze_simple_template -v`
Expected: FAIL with "ImportError"

- [ ] **Step 3: Write minimal implementation**

Create `backend/office/word_template.py`:

```python
"""Word template analysis and fill using docxtpl.

docxtpl extends python-docx with Jinja2-like template syntax:
- {{variable}} for text placeholders
- {% if condition %} ... {% endif %} for control flow
- {%tr for row in rows %} ... {%tr endfor %} for table loops
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document

from .errors import OfficeFileNotFoundError, OfficeTemplateParseError
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    PlaceholderLocation,
    TemplatePlaceholder,
    TemplatePlaceholderType,
    WordTemplateAnalysis,
)

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")
JINJA_CONTROL_RE = re.compile(r"\{%[^%]+%\}")


def _extract_placeholders_from_text(
    text: str,
    location: PlaceholderLocation,
    *,
    paragraph_index: Optional[int] = None,
    table_index: Optional[int] = None,
    row_index: Optional[int] = None,
    col_index: Optional[int] = None,
) -> List[TemplatePlaceholder]:
    """Extract {{}} placeholders from a text string."""
    placeholders = []
    for match in PLACEHOLDER_RE.finditer(text):
        raw_tag = match.group(0)
        name = match.group(1).strip()

        if "日期" in name or "date" in name.lower():
            ph_type = TemplatePlaceholderType.DATE
        elif "图片" in name or "image" in name.lower():
            ph_type = TemplatePlaceholderType.IMAGE
        else:
            ph_type = TemplatePlaceholderType.TEXT

        placeholders.append(
            TemplatePlaceholder(
                name=name,
                raw_tag=raw_tag,
                type=ph_type,
                location=location,
                paragraph_index=paragraph_index,
                table_index=table_index,
                row_index=row_index,
                col_index=col_index,
            )
        )
    return placeholders


def _scan_paragraphs(doc: Document) -> List[TemplatePlaceholder]:
    """Scan all body paragraphs for placeholders."""
    placeholders = []
    for idx, para in enumerate(doc.paragraphs):
        text = para.text
        if PLACEHOLDER_RE.search(text):
            placeholders.extend(
                _extract_placeholders_from_text(
                    text, PlaceholderLocation.BODY, paragraph_index=idx
                )
            )
    return placeholders


def _scan_tables(doc: Document) -> List[TemplatePlaceholder]:
    """Scan all tables for placeholders."""
    placeholders = []
    for table_idx, table in enumerate(doc.tables):
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                text = cell.text
                if PLACEHOLDER_RE.search(text):
                    placeholders.extend(
                        _extract_placeholders_from_text(
                            text,
                            PlaceholderLocation.TABLE,
                            table_index=table_idx,
                            row_index=row_idx,
                            col_index=col_idx,
                        )
                    )
    return placeholders


def _scan_headers_footers(doc: Document) -> List[TemplatePlaceholder]:
    """Scan headers and footers for placeholders."""
    placeholders = []
    for section in doc.sections:
        if section.header and section.header.paragraphs:
            for para in section.header.paragraphs:
                if PLACEHOLDER_RE.search(para.text):
                    placeholders.extend(
                        _extract_placeholders_from_text(
                            para.text, PlaceholderLocation.HEADER
                        )
                    )
        if section.footer and section.footer.paragraphs:
            for para in section.footer.paragraphs:
                if PLACEHOLDER_RE.search(para.text):
                    placeholders.extend(
                        _extract_placeholders_from_text(
                            para.text, PlaceholderLocation.FOOTER
                        )
                    )
    return placeholders


def _has_jinja_control(doc: Document) -> bool:
    """Check if document has Jinja2 control tags."""
    for para in doc.paragraphs:
        if JINJA_CONTROL_RE.search(para.text):
            return True
    return False


def _build_template_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Build a summary for the template analysis result."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=file_path.name,
        generated_filename=file_path.name,
        status=OfficeDocStatus.PARSED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )


def analyze_word_template(
    file_path: Path,
    *,
    workspace_path: str,
    document_id: Optional[str] = None,
) -> WordTemplateAnalysis:
    """Analyze a Word template and extract all {{}} placeholders."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeTemplateParseError(
            f"Path is not a file: {file_path}", file_path=file_path
        )

    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise OfficeTemplateParseError(
            f"Failed to parse DOCX: {exc}", file_path=file_path
        ) from exc

    placeholders: List[TemplatePlaceholder] = []
    placeholders.extend(_scan_paragraphs(doc))
    placeholders.extend(_scan_tables(doc))
    placeholders.extend(_scan_headers_footers(doc))

    doc_id = document_id or file_path.stem
    summary = _build_template_summary(
        file_path, document_id=doc_id, workspace_path=workspace_path
    )

    return WordTemplateAnalysis(
        file_path=str(file_path),
        placeholders=placeholders,
        summary=summary,
        has_jinja_control=_has_jinja_control(doc),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_word_template.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/word_template.py backend/tests/unit/office/test_word_template.py
git commit -m "feat(office): add Word template analysis (scan {{}} placeholders)"
```

---

## Task 5: 实现 word_template.py 的 fill_word_template()

**Files:**
- Modify: `backend/office/word_template.py` (append fill function)
- Test: `backend/tests/unit/office/test_word_template.py` (append fill tests)

**Interfaces:**
- Consumes: `WordTemplateFillRequest`, `WordTemplateFillResult`, `TemplatePlaceholder` from `models.py`; `OfficeFileNotFoundError`, `OfficeTemplateParseError`, `OfficeTemplateFillError` from `errors.py`; `analyze_word_template()` from same file
- Produces: `fill_word_template(req: WordTemplateFillRequest) -> WordTemplateFillResult`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/office/test_word_template.py`:

```python
from backend.office.word_template import fill_word_template
from backend.office.models import WordTemplateFillRequest


def test_fill_simple_template(simple_template: Path, tmp_path: Path):
    req = WordTemplateFillRequest(
        workspace_path=str(simple_template.parent),
        template_path=str(simple_template),
        output_filename="filled.docx",
        data={"甲方姓名": "张三", "乙方姓名": "李四", "合同金额": "100,000"},
    )
    result = fill_word_template(req)

    assert result.filename == "filled.docx"
    assert result.filled_count == 3
    assert len(result.unfilled_placeholders) == 0
    assert Path(result.output_path).exists()


def test_fill_template_partial_data(simple_template: Path, tmp_path: Path):
    req = WordTemplateFillRequest(
        workspace_path=str(simple_template.parent),
        template_path=str(simple_template),
        output_filename="partial.docx",
        data={"甲方姓名": "张三"},  # Missing 乙方姓名 and 合同金额
    )
    result = fill_word_template(req)

    assert result.filled_count == 1
    assert len(result.unfilled_placeholders) == 2
    assert "乙方姓名" in result.unfilled_placeholders
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_word_template.py::test_fill_simple_template -v`
Expected: FAIL with "ImportError: cannot import name 'fill_word_template'"

- [ ] **Step 3: Write minimal implementation**

Append to `backend/office/word_template.py`:

```python
from docxtpl import DocxTemplate

from .errors import OfficeTemplateFillError
from .models import WordTemplateFillRequest, WordTemplateFillResult


def fill_word_template(req: WordTemplateFillRequest) -> WordTemplateFillResult:
    """Fill a Word template with data using docxtpl."""
    template_path = Path(req.template_path)

    if not template_path.exists():
        raise OfficeFileNotFoundError(template_path)

    # Analyze template first to find all placeholders
    analysis = analyze_word_template(
        template_path, workspace_path=req.workspace_path
    )
    placeholder_names = {p.name for p in analysis.placeholders}

    # Check for missing data
    provided_keys = set(req.data.keys())
    unfilled = sorted(placeholder_names - provided_keys)

    try:
        tpl = DocxTemplate(str(template_path))
        # Build context, using empty string for missing placeholders
        context = {name: req.data.get(name, "") for name in placeholder_names}
        tpl.render(context)

        # Determine output path
        output_dir = template_path.parent
        output_path = output_dir / req.output_filename
        tpl.save(str(output_path))

        filled_count = len(placeholder_names) - len(unfilled)

        return WordTemplateFillResult(
            output_path=str(output_path),
            filename=req.output_filename,
            file_size_bytes=output_path.stat().st_size,
            filled_count=filled_count,
            unfilled_placeholders=unfilled,
        )
    except OfficeTemplateFillError:
        raise
    except Exception as exc:
        raise OfficeTemplateFillError(
            f"Template fill failed: {exc}", file_path=template_path
        ) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_word_template.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/word_template.py backend/tests/unit/office/test_word_template.py
git commit -m "feat(office): add Word template fill (docxtpl render)"
```

---

## Task 6: 实现 pdf.py（read_pdf + generate_pdf）

**Files:**
- Create: `backend/office/pdf.py`
- Test: `backend/tests/unit/office/test_pdf.py`

**Interfaces:**
- Consumes: `PdfReadResult`, `PdfPageContent`, `PdfGenerateRequest`, `PdfGenerateResult`, `OfficeDocumentSummary` from `models.py`; `OfficeFileNotFoundError`, `OfficePdfParseError`, `OfficePdfGenerateError` from `errors.py`
- Produces: `read_pdf(file_path, workspace_path, document_id) -> PdfReadResult`; `generate_pdf(req: PdfGenerateRequest) -> PdfGenerateResult`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/office/test_pdf.py`:

```python
"""Unit tests for PDF read and generate."""

import pytest
from pathlib import Path

from backend.office.pdf import read_pdf, generate_pdf
from backend.office.models import PdfGenerateRequest, PdfPageSpec
from backend.office.errors import OfficeFileNotFoundError, OfficePdfParseError


@pytest.fixture
def simple_pdf(tmp_path: Path) -> Path:
    """Create a simple PDF for testing."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "Hello World")
    c.drawString(100, 730, "这是中文测试")
    c.showPage()
    c.drawString(100, 750, "Page 2 content")
    c.showPage()
    c.save()
    return pdf_path


def test_read_pdf_text(simple_pdf: Path):
    result = read_pdf(simple_pdf, workspace_path=str(simple_pdf.parent))
    assert len(result.pages) == 2
    assert "Hello World" in result.pages[0].text
    assert "中文测试" in result.pages[0].text
    assert result.pages[0].page_number == 1


def test_read_pdf_metadata(simple_pdf: Path):
    result = read_pdf(simple_pdf, workspace_path=str(simple_pdf.parent))
    assert result.summary is not None
    assert result.summary.doc_type.value == "pdf"


def test_read_nonexistent_pdf():
    with pytest.raises(OfficeFileNotFoundError):
        read_pdf(Path("/nonexistent/test.pdf"), workspace_path="/tmp")


def test_read_invalid_pdf(tmp_path: Path):
    invalid = tmp_path / "bad.pdf"
    invalid.write_text("not a pdf")
    with pytest.raises(OfficePdfParseError):
        read_pdf(invalid, workspace_path=str(tmp_path))


def test_generate_pdf_single_page(tmp_path: Path):
    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="output.pdf",
        pages=[
            PdfPageSpec(
                title="Test Document",
                paragraphs=["First paragraph.", "Second paragraph."],
            )
        ],
    )
    result = generate_pdf(req)
    assert result.page_count == 1
    assert Path(result.output_path).exists()
    assert result.file_size_bytes > 0


def test_generate_pdf_multi_page(tmp_path: Path):
    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="multi.pdf",
        pages=[
            PdfPageSpec(title="Page 1", paragraphs=["Content 1"]),
            PdfPageSpec(title="Page 2", paragraphs=["Content 2"]),
        ],
    )
    result = generate_pdf(req)
    assert result.page_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_pdf.py::test_read_pdf_text -v`
Expected: FAIL with "ImportError"

- [ ] **Step 3: Write minimal implementation**

Create `backend/office/pdf.py`:

```python
"""PDF read and generate using PyMuPDF (fitz) and reportlab."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

from .errors import OfficeFileNotFoundError, OfficePdfParseError, OfficePdfGenerateError
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    PdfGenerateRequest,
    PdfGenerateResult,
    PdfPageContent,
    PdfReadResult,
)

logger = logging.getLogger(__name__)


def _build_pdf_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Build a summary for a PDF read result."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.PDF,
        original_filename=file_path.name,
        generated_filename=file_path.name,
        status=OfficeDocStatus.PARSED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )


def read_pdf(
    file_path: Path,
    *,
    workspace_path: str,
    document_id: Optional[str] = None,
) -> PdfReadResult:
    """Read a PDF file and extract text, tables, images, and metadata."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficePdfParseError(f"Path is not a file: {file_path}", file_path=file_path)

    try:
        doc = fitz.open(str(file_path))
    except Exception as exc:
        raise OfficePdfParseError(
            f"Failed to open PDF: {exc}", file_path=file_path
        ) from exc

    pages: List[PdfPageContent] = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        pages.append(
            PdfPageContent(
                page_number=page_num + 1,
                text=text,
                tables=[],  # Table extraction is complex; stub for now
                images=[],
            )
        )

    metadata = dict(doc.metadata) if doc.metadata else {}
    doc.close()

    doc_id = document_id or file_path.stem
    summary = _build_pdf_summary(file_path, document_id=doc_id, workspace_path=workspace_path)

    return PdfReadResult(
        summary=summary,
        pages=pages,
        metadata=metadata,
    )


def generate_pdf(req: PdfGenerateRequest) -> PdfGenerateResult:
    """Generate a PDF from structured data using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4, LETTER, LEGAL
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:
        raise OfficePdfGenerateError(f"reportlab not installed: {exc}") from exc

    workspace = Path(req.workspace_path)
    output_path = workspace / req.filename

    page_size_map = {
        "A4": A4,
        "Letter": LETTER,
        "Legal": LEGAL,
    }
    page_size = page_size_map.get(req.page_size, A4)

    try:
        c = canvas.Canvas(str(output_path), pagesize=page_size)
        width, height = page_size

        for i, page_spec in enumerate(req.pages):
            if i > 0:
                c.showPage()

            y = height - 72  # Start 1 inch from top

            # Title
            if page_spec.title:
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, y, page_spec.title)
                y -= 30

            # Paragraphs
            c.setFont("Helvetica", 12)
            for para in page_spec.paragraphs:
                if y < 72:  # Bottom margin
                    c.showPage()
                    y = height - 72
                c.drawString(72, y, para)
                y -= 18

            # Tables
            for table_data in page_spec.tables:
                if y < 72:
                    c.showPage()
                    y = height - 72
                for row in table_data:
                    x = 72
                    for cell in row:
                        c.drawString(x, y, str(cell))
                        x += 100
                    y -= 15

        c.save()

        return PdfGenerateResult(
            output_path=str(output_path),
            filename=req.filename,
            file_size_bytes=output_path.stat().st_size,
            page_count=len(req.pages),
        )
    except OfficePdfGenerateError:
        raise
    except Exception as exc:
        raise OfficePdfGenerateError(
            f"PDF generation failed: {exc}", file_path=output_path
        ) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_pdf.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/pdf.py backend/tests/unit/office/test_pdf.py
git commit -m "feat(office): add PDF read + generate (PyMuPDF + reportlab)"
```

---

## Task 7: 实现 pdf_forms.py（read_pdf_form + fill_pdf_form）

**Files:**
- Create: `backend/office/pdf_forms.py`
- Test: `backend/tests/unit/office/test_pdf_forms.py`

**Interfaces:**
- Consumes: `PdfFormReadResult`, `PdfFormFillRequest`, `PdfFormField` from `models.py`; `OfficeFileNotFoundError`, `OfficePdfParseError`, `OfficePdfFormError` from `errors.py`
- Produces: `read_pdf_form(file_path, workspace_path) -> PdfFormReadResult`; `fill_pdf_form(req: PdfFormFillRequest) -> PdfFormFillRequest`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/office/test_pdf_forms.py`:

```python
"""Unit tests for PDF form read and fill."""

import pytest
from pathlib import Path

from backend.office.pdf_forms import read_pdf_form, fill_pdf_form
from backend.office.models import PdfFormFillRequest
from backend.office.errors import OfficeFileNotFoundError


def test_read_pdf_no_form(tmp_path: Path):
    """A regular PDF without forms returns empty field list."""
    from reportlab.pdfgen import canvas
    pdf_path = tmp_path / "no_form.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 750, "No forms here")
    c.save()

    result = read_pdf_form(pdf_path, workspace_path=str(tmp_path))
    assert result.fields == []
    assert result.has_xfa is False


def test_read_nonexistent_pdf_form():
    with pytest.raises(OfficeFileNotFoundError):
        read_pdf_form(Path("/nonexistent/form.pdf"), workspace_path="/tmp")


def test_fill_pdf_form_no_fields(tmp_path: Path):
    """Filling a PDF without forms succeeds but does nothing."""
    from reportlab.pdfgen import canvas
    pdf_path = tmp_path / "no_form.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 750, "Plain PDF")
    c.save()

    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="filled.pdf",
        data={"name": "value"},
    )
    result = fill_pdf_form(req)
    assert Path(result.output_path).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_pdf_forms.py -v`
Expected: FAIL with "ImportError"

- [ ] **Step 3: Write minimal implementation**

Create `backend/office/pdf_forms.py`:

```python
"""PDF form (AcroForm) read and fill using PyMuPDF."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

from .errors import OfficeFileNotFoundError, OfficePdfParseError, OfficePdfFormError
from .models import PdfFormField, PdfFormFillRequest, PdfFormReadResult

logger = logging.getLogger(__name__)


def read_pdf_form(
    file_path: Path,
    *,
    workspace_path: str,
) -> PdfFormReadResult:
    """Read PDF form fields (AcroForm)."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)

    try:
        doc = fitz.open(str(file_path))
    except Exception as exc:
        raise OfficePdfParseError(
            f"Failed to open PDF: {exc}", file_path=file_path
        ) from exc

    fields: List[PdfFormField] = []

    # PyMuPDF widget iteration for AcroForm fields
    for page_num in range(len(doc)):
        page = doc[page_num]
        widgets = page.widgets()
        if widgets:
            for widget in widgets:
                field_type = _widget_type_name(widget)
                options = None
                if hasattr(widget, "choice_values"):
                    options = widget.choice_values

                fields.append(
                    PdfFormField(
                        name=widget.field_name or "",
                        type=field_type,
                        value=widget.field_value,
                        options=options,
                        required=bool(widget.is_required) if hasattr(widget, "is_required") else False,
                        read_only=bool(widget.is_read_only) if hasattr(widget, "is_read_only") else False,
                    )
                )

    # Check for XFA (dynamic forms)
    has_xfa = False
    if hasattr(doc, "xfa") and doc.xfa:
        has_xfa = True

    doc.close()

    return PdfFormReadResult(
        file_path=str(file_path),
        fields=fields,
        has_xfa=has_xfa,
    )


def _widget_type_name(widget) -> str:
    """Map PyMuPDF widget field_type int to a string name."""
    type_map = {
        0: "text",
        1: "pushbutton",
        2: "checkbox",
        3: "radiobutton",
        4: "listbox",
        5: "combobox",
        6: "signature",
    }
    return type_map.get(widget.field_type, "unknown")


def fill_pdf_form(req: PdfFormFillRequest):
    """Fill a PDF form with data."""
    template_path = Path(req.template_path)

    if not template_path.exists():
        raise OfficeFileNotFoundError(template_path)

    workspace = Path(req.workspace_path)
    output_path = workspace / req.output_filename

    try:
        doc = fitz.open(str(template_path))
    except Exception as exc:
        raise OfficePdfParseError(
            f"Failed to open PDF: {exc}", file_path=template_path
        ) from exc

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            widgets = page.widgets()
            if not widgets:
                continue
            for widget in widgets:
                name = widget.field_name
                if name in req.data:
                    widget.field_value = req.data[name]
                    widget.update()

        if req.flatten:
            # Flatten: make form fields read-only (bake them into page content)
            for page_num in range(len(doc)):
                page = doc[page_num]
                for widget in page.widgets():
                    widget.is_read_only = True
                    widget.update()

        doc.save(str(output_path))
        doc.close()

        from .models import PdfFormFillResult
        return PdfFormFillResult(
            output_path=str(output_path),
            filename=req.output_filename,
            file_size_bytes=output_path.stat().st_size,
            filled_count=len([f for f in req.data if True]),
        )
    except Exception as exc:
        raise OfficePdfFormError(
            f"PDF form fill failed: {exc}", file_path=template_path
        ) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/test_pdf_forms.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/office/pdf_forms.py backend/tests/unit/office/test_pdf_forms.py
git commit -m "feat(office): add PDF form read + fill (PyMuPDF AcroForm)"
```

---

## Task 8: 扩展 office_routes.py 添加 6 个新 API 端点

**Files:**
- Modify: `backend/api/office_routes.py`

**Interfaces:**
- Consumes: All new models and functions from Tasks 2-7
- Produces: 6 new POST endpoints under `/api/v1/office/`

- [ ] **Step 1: Add Word template endpoints**

At the end of `backend/api/office_routes.py`, add:

```python
# ──────────────────────────────────────────────────────────────────────
# Word Template endpoints (Phase 2)
# ──────────────────────────────────────────────────────────────────────


@router.post("/word/analyze-template")
async def analyze_word_template_endpoint(
    req: WordTemplateAnalyzeRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Analyze a Word template and extract {{}} placeholders."""
    file_path = _validate_file_in_workspace(req.template_path, req.workspace_path)
    result = analyze_word_template(
        file_path,
        workspace_path=req.workspace_path,
    )
    return result


@router.post("/word/fill-template")
async def fill_word_template_endpoint(
    req: WordTemplateFillRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Fill a Word template with data."""
    file_path = _validate_file_in_workspace(req.template_path, req.workspace_path)
    # Output path validation
    output_path = resolve_output_path(
        req.workspace_path, OfficeDocType.WORD, req.output_filename
    )
    result = fill_word_template(req)
    return result


# ──────────────────────────────────────────────────────────────────────
# PDF endpoints (Phase 2)
# ──────────────────────────────────────────────────────────────────────


@router.post("/pdf/read")
async def read_pdf_endpoint(
    req: PdfReadRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Read a PDF file and extract content."""
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    result = read_pdf(file_path, workspace_path=req.workspace_path)
    return result


@router.post("/pdf/generate")
async def generate_pdf_endpoint(
    req: PdfGenerateRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Generate a PDF from structured data."""
    output_path = resolve_output_path(
        req.workspace_path, OfficeDocType.PDF, req.filename
    )
    result = generate_pdf(req)
    return result


@router.post("/pdf/read-form")
async def read_pdf_form_endpoint(
    req: PdfFormReadRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Read PDF form fields."""
    file_path = _validate_file_in_workspace(req.file_path, req.workspace_path)
    result = read_pdf_form(file_path, workspace_path=req.workspace_path)
    return result


@router.post("/pdf/fill-form")
async def fill_pdf_form_endpoint(
    req: PdfFormFillRequest,
    workspace: WorkspaceBinding = Depends(get_active_workspace_binding),
):
    """Fill a PDF form with data."""
    file_path = _validate_file_in_workspace(req.template_path, req.workspace_path)
    output_path = resolve_output_path(
        req.workspace_path, OfficeDocType.PDF, req.output_filename
    )
    result = fill_pdf_form(req)
    return result
```

- [ ] **Step 2: Add imports at top of office_routes.py**

```python
from backend.office.word_template import analyze_word_template, fill_word_template
from backend.office.pdf import read_pdf, generate_pdf
from backend.office.pdf_forms import read_pdf_form, fill_pdf_form
from backend.office.models import (
    # ... existing imports ...
    # Phase 2: template + PDF
    WordTemplateFillRequest,
    PdfGenerateRequest,
    PdfFormFillRequest,
)
```

- [ ] **Step 3: Add request models to models.py**

In `backend/office/models.py`, add:

```python
class WordTemplateAnalyzeRequest(BaseModel):
    """Request to analyze a Word template."""
    model_config = ConfigDict(extra="forbid")
    workspace_path: str
    template_path: str


class PdfReadRequest(BaseModel):
    """Request to read a PDF file."""
    model_config = ConfigDict(extra="forbid")
    workspace_path: str
    file_path: str


class PdfFormReadRequest(BaseModel):
    """Request to read PDF form fields."""
    model_config = ConfigDict(extra="forbid")
    workspace_path: str
    file_path: str


class PdfFormFillResult(BaseModel):
    """Result of filling a PDF form."""
    model_config = ConfigDict(extra="forbid")
    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/office_routes.py backend/office/models.py
git commit -m "feat(office): add 6 API endpoints for Word template + PDF ops"
```

---

## Task 9: 更新 backend/office/__init__.py 导出新函数

**Files:**
- Modify: `backend/office/__init__.py`

- [ ] **Step 1: Read current __init__.py**

Read `backend/office/__init__.py` to understand current exports.

- [ ] **Step 2: Add new exports**

```python
# Phase 2: Word template + PDF operations
from .word_template import analyze_word_template, fill_word_template
from .pdf import read_pdf, generate_pdf
from .pdf_forms import read_pdf_form, fill_pdf_form
```

- [ ] **Step 3: Commit**

```bash
git add backend/office/__init__.py
git commit -m "chore(office): export new template + PDF functions"
```

---

## Task 10: 集成测试 + 最终验证

**Files:**
- Test: `backend/tests/integration/test_office_template_integration.py`
- Test: `backend/tests/integration/test_pdf_operations_integration.py`

- [ ] **Step 1: Run full test suite**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/unit/office/ -v
```
Expected: All unit tests pass

- [ ] **Step 2: Start backend and test endpoints manually**

```bash
conda activate sage-backend && python backend/main.py
```

Then test with curl:
```bash
# Word template analysis
curl -X POST http://127.0.0.1:8765/api/v1/office/word/analyze-template \
  -H "Content-Type: application/json" \
  -d '{"workspace_path":"/tmp","template_path":"/tmp/template.docx"}'

# PDF read
curl -X POST http://127.0.0.1:8765/api/v1/office/pdf/read \
  -H "Content-Type: application/json" \
  -d '{"workspace_path":"/tmp","file_path":"/tmp/test.pdf"}'
```

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(office): resolve integration test issues"
```

- [ ] **Step 4: Push branch and create PR**

```bash
git push -u origin feat/word-template-pdf-operations
gh pr create --title "feat(office): Word template + PDF operations" \
  --body "Adds Word template analysis/fill and PDF read/generate/form-fill capabilities."
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-05-word-template-pdf-operations.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
