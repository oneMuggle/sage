"""REST endpoints for read-only LaTeX preview."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.office.latex.service import read_latex_file

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


__all__ = ["LatexReadRequest", "read_latex_endpoint", "router"]
