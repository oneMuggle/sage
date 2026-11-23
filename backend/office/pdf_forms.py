"""PDF form (AcroForm) read and fill using PyMuPDF.

Security posture mirrors ``pdf.py`` and ``word_template.py``:

- Every untrusted path goes through ``validate_workspace`` + ``resolve_within``
  so ``..`` traversal and symlink escapes are rejected at the boundary.
- ``_validate_pdf_file`` performs preflight size/page-count checks *before*
  fitz opens the file, matching the pattern in ``pdf.py``.
- Catch-all ``except Exception`` blocks wrap with **generic** messages —
  internal paths and low-level exception text never reach the user.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    import pymupdf

from .errors import (
    OfficeFileNotFoundError,
    OfficePathError,
    OfficePdfFormError,
    OfficePdfParseError,
    OfficeSizeLimitError,
)
from .models import (
    PdfFormField,
    PdfFormFillRequest,
    PdfFormFillResult,
    PdfFormReadResult,
)
from .path_safety import resolve_within
from .pdf import MAX_PDF_OUTPUT_SIZE, _validate_pdf_file
from .storage import validate_workspace


# Phase 3.5：pymupdf(~300ms) 只在真正读写 PDF 表单时才用得上；启动路径
# （会话列表 / 聊天）不触发 → 改为按需惰性导入。
def __getattr__(name: str) -> Any:
    from backend.core.lazy import load_module

    if name == "pymupdf":
        return load_module("pymupdf", "pymupdf", globals())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Widget field-type int -> human-readable name.
# Values match PyMuPDF's PDF_WIDGET_TYPE_* constants (valid range 1-7).
_WIDGET_TYPE_NAMES: Dict[int, str] = {
    1: "pushbutton",
    2: "checkbox",
    3: "combobox",
    4: "listbox",
    5: "radiobutton",
    6: "signature",
    7: "text",
}


def _widget_type_name(widget: pymupdf.Widget) -> str:
    """Map a PyMuPDF widget field_type int to a string name."""
    return _WIDGET_TYPE_NAMES.get(widget.field_type, "unknown")


def read_pdf_form(
    file_path: Path,
    *,
    workspace_path: str,
) -> PdfFormReadResult:
    """Read PDF form fields (AcroForm).

    Mirrors the workspace-boundary pattern from
    ``word_template.analyze_word_template``: validate the workspace, check
    existence, resolve within, then preflight.
    """
    file_path = Path(file_path)
    workspace = validate_workspace(Path(workspace_path))

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    file_path = resolve_within(workspace, file_path)

    if not file_path.is_file():
        raise OfficePathError("Path is not a regular file", file_path=file_path)

    _validate_pdf_file(file_path)

    try:
        from backend.core.lazy import load_module

        pymupdf = load_module("pymupdf", "pymupdf", globals())
        doc = pymupdf.open(str(file_path))
    except OfficeSizeLimitError:
        raise
    except OfficePdfParseError:
        raise
    except Exception as exc:
        raise OfficePdfParseError(
            "Failed to open PDF", file_path=file_path
        ) from exc

    fields: List[PdfFormField] = []
    has_xfa = False
    try:
        # Check for XFA (dynamic forms) — must happen while doc is open.
        xfa = getattr(doc, "xfa", None)
        has_xfa = bool(xfa)

        for page in doc:
            widgets = page.widgets()
            if not widgets:
                continue
            for widget in widgets:
                options = None
                if hasattr(widget, "choice_values"):
                    options = widget.choice_values
                fields.append(
                    PdfFormField(
                        name=widget.field_name or "",
                        type=_widget_type_name(widget),
                        value=widget.field_value,
                        options=options,
                        required=(
                            bool(widget.field_flags & 2)
                        ),
                        read_only=(
                            bool(widget.field_flags & 1)
                        ),
                    )
                )
    finally:
        doc.close()

    return PdfFormReadResult(
        file_path=str(file_path),
        fields=fields,
        has_xfa=has_xfa,
    )


def fill_pdf_form(req: PdfFormFillRequest) -> PdfFormFillResult:
    """Fill a PDF form with data and write to a new file.

    Mirrors the output-path validation from ``pdf.generate_pdf``:
    reject empty / absolute / traversal / separator filenames, resolve
    within workspace, reject existing outputs.
    """
    template_path = Path(req.template_path)
    workspace = validate_workspace(Path(req.workspace_path))

    if not template_path.exists():
        raise OfficeFileNotFoundError(template_path)
    template_path = resolve_within(workspace, template_path)

    if not template_path.is_file():
        raise OfficePathError(
            "Path is not a regular file", file_path=template_path
        )

    _validate_pdf_file(template_path)

    # ── Output filename validation ──────────────────────────────────────
    filename = req.output_filename
    if not filename or Path(filename).is_absolute() or ".." in filename:
        raise OfficePdfFormError("Invalid output filename")
    if "/" in filename or "\\" in filename:
        raise OfficePdfFormError("Invalid output filename")

    try:
        output_path = resolve_within(workspace, workspace / filename)
    except OfficePathError as exc:
        raise OfficePdfFormError("Invalid output filename") from exc

    if output_path.is_dir():
        raise OfficePdfFormError("Invalid output filename")
    if output_path.exists():
        raise OfficePdfFormError("Invalid output filename")

    # ── Open template ───────────────────────────────────────────────────
    try:
        from backend.core.lazy import load_module

        pymupdf = load_module("pymupdf", "pymupdf", globals())
        doc = pymupdf.open(str(template_path))
    except OfficeSizeLimitError:
        raise
    except OfficePdfParseError:
        raise
    except Exception as exc:
        raise OfficePdfParseError(
            "Failed to open PDF", file_path=template_path
        ) from exc

    # ── Fill fields ─────────────────────────────────────────────────────
    filled_count = 0
    try:
        for page in doc:
            widgets = page.widgets()
            if not widgets:
                continue
            for widget in widgets:
                name = widget.field_name
                if name in req.data:
                    widget.field_value = req.data[name]
                    widget.update()
                    filled_count += 1

        if req.flatten:
            bake = getattr(doc, "bake", None)
            if bake is not None:
                # True flatten: render widget appearances into page content
                # and remove the fields (annotations stay untouched).
                bake(annots=False, widgets=True)
            else:
                # 极老运行时兜底：bake() 自 PyMuPDF 1.24.0 起提供
                # （release/win7 钉 1.24.11 → 可用），这里只防更早的版本。
                # 退化行为：把字段置为只读（field_flags bit 0）。
                for page in doc:
                    widgets = page.widgets()
                    if not widgets:
                        continue
                    for widget in widgets:
                        widget.field_flags = widget.field_flags | 1
                        widget.update()

        # 先写同目录的隐藏临时文件 → 体积检查 → 原子改名到最终落点。
        # 直接写 output_path 再检查体积有两个问题：超限时磁盘上已经留下
        # 一个超大文件（虽然随后被删，但删除失败就留垃圾），而且检查期间
        # output_path 已经「存在」。
        # 临时名保留 .pdf 后缀 —— PyMuPDF 的 save() 按扩展名推断输出格式。
        tmp_output = output_path.with_name(f".{output_path.stem}.sage-tmp.pdf")
        try:
            doc.save(str(tmp_output))
            output_size = tmp_output.stat().st_size
            if output_size > MAX_PDF_OUTPUT_SIZE:
                # 产物超上限 —— 删掉半成品，不给磁盘留下垃圾。
                # 不带 file_path：错误文案里不能出现绝对路径。
                raise OfficeSizeLimitError(output_size, MAX_PDF_OUTPUT_SIZE)
            tmp_output.replace(output_path)
        finally:
            with contextlib.suppress(OSError):
                tmp_output.unlink()
    except OfficePdfFormError:
        raise
    except OfficeSizeLimitError:
        raise
    except OfficePdfParseError:
        raise
    except Exception as exc:
        raise OfficePdfFormError("PDF form fill failed") from exc
    finally:
        doc.close()

    return PdfFormFillResult(
        output_path=str(output_path),
        filename=filename,
        file_size_bytes=output_path.stat().st_size,
        filled_count=filled_count,
    )
