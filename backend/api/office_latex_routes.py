"""REST endpoints for read-only LaTeX preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.office.latex.service import (
    analyze_latex_template_file,
    audit_latex_file_service,
    audit_latex_pdf_service,
    check_latex_compliance_service,
    compile_latex_file,
    extract_latex_project_service,
    fill_latex_template_file,
    latex_capabilities,
    latexdiff_files_service,
    read_latex_file,
)

router = APIRouter(prefix="/latex", tags=["latex"])


class LatexReadRequest(BaseModel):
    """Read a workspace .tex file and return structured preview blocks."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


@router.post("/read")
def read_latex_endpoint(req: LatexReadRequest) -> dict:
    """Parse a .tex file inside the workspace and return a preview payload."""
    return read_latex_file(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
    )


class LatexTemplateAnalyzeRequest(BaseModel):
    """Analyze a LaTeX template and return its slots/style/macros."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class LatexTemplateFillRequest(BaseModel):
    """Fill a LaTeX template's slots into a new .tex file."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]


@router.post("/template/analyze")
def analyze_latex_template_endpoint(req: LatexTemplateAnalyzeRequest) -> dict:
    """Extract a LaTeX template profile (slots/style/macros)."""
    return analyze_latex_template_file(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
    )


@router.post("/template/fill")
def fill_latex_template_endpoint(req: LatexTemplateFillRequest) -> dict:
    """Fill a LaTeX template into a new .tex file (never overwrites template)."""
    return fill_latex_template_file(
        Path(req.template_path),
        req.data,
        req.output_filename,
        workspace=Path(req.workspace_path),
    )


class LatexAuditRequest(BaseModel):
    """Run deterministic source-level audit on a .tex project."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    required_sections: List[str] = Field(default_factory=list)


@router.post("/audit")
def audit_latex_endpoint(req: LatexAuditRequest) -> dict:
    """Audit a .tex project and return issues with source anchors."""
    return audit_latex_file_service(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
        required_sections=req.required_sections,
    )


class LatexCompileRequest(BaseModel):
    """Compile a .tex project with a detected external engine."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    output_filename: Optional[str] = None
    engine: Optional[str] = None
    timeout_s: int = Field(default=60, ge=1, le=600)


class LatexDiffRequest(BaseModel):
    """Generate latexdiff source (optionally compile it)."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    original_path: str
    revised_path: str
    output_filename: str = ""
    compile_pdf: bool = False
    engine: Optional[str] = None
    timeout_s: int = Field(default=60, ge=1, le=600)


@router.get("/capabilities")
def latex_capabilities_endpoint() -> dict:
    """Return available TeX engines and latexdiff."""
    return latex_capabilities()


@router.post("/compile")
def compile_latex_endpoint(req: LatexCompileRequest) -> dict:
    """Compile a .tex project to PDF (optional external engine)."""
    return compile_latex_file(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
        output_filename=req.output_filename,
        engine=req.engine,
        timeout_s=req.timeout_s,
    )


@router.post("/diff")
def latexdiff_endpoint(req: LatexDiffRequest) -> dict:
    """Generate latexdiff .tex and optionally compile a redline PDF."""
    return latexdiff_files_service(
        Path(req.original_path),
        Path(req.revised_path),
        workspace=Path(req.workspace_path),
        output_filename=req.output_filename,
        compile_pdf=req.compile_pdf,
        engine=req.engine,
        timeout_s=req.timeout_s,
    )


class LatexProjectExtractRequest(BaseModel):
    """Safely extract a LaTeX/Overleaf project zip into the workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    zip_path: str
    output_dir_name: Optional[str] = None


@router.post("/project/extract")
def extract_latex_project_endpoint(req: LatexProjectExtractRequest) -> dict:
    """Extract a project zip into a new workspace directory (never compiles)."""
    return extract_latex_project_service(
        Path(req.zip_path),
        workspace=Path(req.workspace_path),
        output_dir_name=req.output_dir_name,
    )


class LatexPdfAuditRequest(BaseModel):
    """Audit a PDF's page size/count, embedded fonts and image DPI."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    required_min_pages: Optional[int] = Field(default=None, ge=1, le=5000)
    required_max_pages: Optional[int] = Field(default=None, ge=1, le=5000)
    min_image_dpi: float = Field(default=150.0, ge=1, le=2400)


@router.post("/pdf/audit")
def audit_latex_pdf_endpoint(req: LatexPdfAuditRequest) -> dict:
    """Audit a workspace PDF (read-only; never modifies the file)."""
    return audit_latex_pdf_service(
        Path(req.file_path),
        workspace=Path(req.workspace_path),
        required_min_pages=req.required_min_pages,
        required_max_pages=req.required_max_pages,
        min_image_dpi=req.min_image_dpi,
    )


class LatexComplianceProfileModel(BaseModel):
    """Inline journal-compliance profile."""

    model_config = ConfigDict(extra="forbid")

    required_sections: List[str] = Field(default_factory=list)
    required_metadata: List[str] = Field(default_factory=list)
    allowed_page_sizes: List[str] = Field(default_factory=list)
    required_min_pages: Optional[int] = Field(default=None, ge=1, le=5000)
    required_max_pages: Optional[int] = Field(default=None, ge=1, le=5000)
    require_embedded_fonts: bool = True
    min_image_dpi: float = Field(default=150.0, ge=1, le=2400)
    forbidden_commands: List[str] = Field(default_factory=list)


class LatexComplianceRequest(BaseModel):
    """Check .tex (and optional PDF) against a compliance profile."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    tex_path: str
    pdf_path: Optional[str] = None
    profile: LatexComplianceProfileModel = Field(
        default_factory=LatexComplianceProfileModel
    )


@router.post("/compliance/check")
def check_latex_compliance_endpoint(req: LatexComplianceRequest) -> dict:
    """Run a read-only compliance check over source and optional PDF."""
    profile = (
        req.profile.model_dump()
        if hasattr(req.profile, "model_dump")
        else req.profile.dict()
    )
    return check_latex_compliance_service(
        Path(req.tex_path),
        workspace=Path(req.workspace_path),
        pdf_path=Path(req.pdf_path) if req.pdf_path else None,
        profile=profile,
    )


__all__ = [
    "LatexAuditRequest",
    "LatexCompileRequest",
    "LatexComplianceProfileModel",
    "LatexComplianceRequest",
    "LatexDiffRequest",
    "LatexPdfAuditRequest",
    "LatexProjectExtractRequest",
    "LatexReadRequest",
    "LatexTemplateAnalyzeRequest",
    "LatexTemplateFillRequest",
    "analyze_latex_template_endpoint",
    "audit_latex_endpoint",
    "audit_latex_pdf_endpoint",
    "check_latex_compliance_endpoint",
    "compile_latex_endpoint",
    "extract_latex_project_endpoint",
    "fill_latex_template_endpoint",
    "latex_capabilities_endpoint",
    "latexdiff_endpoint",
    "read_latex_endpoint",
    "router",
]
