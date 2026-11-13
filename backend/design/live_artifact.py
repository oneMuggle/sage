"""Live Artifact engine (M5b).

Binds a data source (Excel / CSV / JSON) to a design project and re-generates
the artifact when the source changes. The source binding is persisted on disk
as ``source.json`` next to the project's artifact files so that a refresh on
the next session can re-read the same file.

The engine deliberately stays thin: it does not mutate the brief stored in
the database, and it never invokes the LLM directly. Instead, it asks the
``DesignStudio`` to ``generate`` a new artifact version with the augmented
brief (project brief + a compact text rendering of the source data).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict

from backend.design.outline_extractor import OutlineExtractor

logger = logging.getLogger(__name__)

_SOURCE_FILE = "source.json"
_SUPPORTED_EXTS = (".xlsx", ".xls", ".csv", ".json")
_MAX_DATA_ROWS = 30
_MAX_JSON_PREVIEW_CHARS = 4000


class SourceBinding(BaseModel):
    """Persisted source binding for a design project."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    file_path: str
    name: str = ""


def _binding_path(workspace: Path, project_id: str) -> Path:
    return workspace / "design" / project_id / _SOURCE_FILE


def _load_binding(workspace: Path, project_id: str) -> Optional[SourceBinding]:
    path = _binding_path(workspace, project_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SourceBinding(**data)
    except Exception:
        logger.warning("live_artifact: malformed binding at %s", path)
        return None


def _save_binding(
    workspace: Path, project_id: str, binding: SourceBinding,
) -> None:
    path = _binding_path(workspace, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        binding.model_dump_json(indent=2), encoding="utf-8",
    )


def _delete_binding(workspace: Path, project_id: str) -> bool:
    path = _binding_path(workspace, project_id)
    if path.exists():
        path.unlink()
        return True
    return False


def validate_source_path(path: str) -> None:
    """Raise ``ValueError`` if the path isn't a supported data source."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"source not found: {path}")
    if p.suffix.lower() not in _SUPPORTED_EXTS:
        raise ValueError(
            f"unsupported source extension {p.suffix!r} "
            f"(expected one of {_SUPPORTED_EXTS})"
        )


def detect_kind(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        return "xlsx"
    if ext == ".csv":
        return "csv"
    if ext == ".json":
        return "json"
    return "unknown"


def render_summary(binding: SourceBinding) -> str:
    """Render the bound source as a compact text block for the brief.

    Each row is ``key1=value1\tkey2=value2…`` so the LLM sees a tabular
    summary without bloating the prompt.
    """
    ext = Path(binding.file_path).suffix.lower()
    if ext in (".xlsx", ".xls"):
        return _render_excel(binding.file_path)
    if ext == ".csv":
        return _render_excel(binding.file_path, csv_fallback=True)
    if ext == ".json":
        return _render_json(binding.file_path)
    return ""


def _render_excel(file_path: str, *, csv_fallback: bool = False) -> str:
    if csv_fallback:
        from backend.office.excel import read_csv
    else:
        from backend.office.excel import read_xlsx

    result = read_csv(Path(file_path)) if csv_fallback else read_xlsx(
        Path(file_path)
    )
    sections: List[str] = []
    for sheet in result.sheets:
        rows = sheet.rows or []
        if not rows:
            continue
        headers = [str(c).strip() for c in rows[0]]
        headers = [h or f"col{i}" for i, h in enumerate(headers, 1)]
        body_rows = rows[1 : 1 + _MAX_DATA_ROWS]
        lines = [f"## Sheet: {sheet.name}"]
        lines.append(" | ".join(headers))
        for row in body_rows:
            cells = [str(c).strip() for c in (row or [])[: len(headers)]]
            lines.append(" | ".join(cells))
        if len(rows) > 1 + _MAX_DATA_ROWS:
            lines.append(
                f"...（共 {len(rows) - 1} 行，截断为前 {_MAX_DATA_ROWS}）"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _render_json(file_path: str) -> str:
    raw = Path(file_path).read_text(encoding="utf-8")
    if len(raw) > _MAX_JSON_PREVIEW_CHARS:
        raw = raw[:_MAX_JSON_PREVIEW_CHARS] + "…"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


class LiveArtifactEngine:
    """Refresh a design artifact when its source data changes."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace)

    def bind(
        self,
        project_id: str,
        source_path: str,
        *,
        kind: Optional[str] = None,
        name: Optional[str] = None,
    ) -> SourceBinding:
        """Persist the source binding for ``project_id``.

        Raises:
            FileNotFoundError: source_path doesn't exist.
            ValueError: unsupported extension.
        """
        validate_source_path(source_path)
        binding = SourceBinding(
            kind=kind or detect_kind(source_path),
            file_path=str(Path(source_path).resolve()),
            name=name or Path(source_path).stem,
        )
        _save_binding(self._workspace, project_id, binding)
        return binding

    def get_binding(self, project_id: str) -> Optional[SourceBinding]:
        return _load_binding(self._workspace, project_id)

    def unbind(self, project_id: str) -> bool:
        return _delete_binding(self._workspace, project_id)

    def extract_outline(self, docx_path: str) -> Any:
        """Delegate to :class:`OutlineExtractor` for Word → markdown outline."""
        return OutlineExtractor().extract(Path(docx_path))

    async def refresh(self, studio: Any, project_id: str) -> Any:
        """Re-generate the project's artifact with the source summary.

        The original brief is preserved and the source summary is appended.
        If no source binding exists, ``refresh`` falls through to a plain
        regeneration of the current brief.
        """
        binding = self.get_binding(project_id)
        project = studio.get_project(project_id)
        if binding is None:
            brief = project.brief
        else:
            summary = render_summary(binding)
            brief = (
                f"{project.brief}\n\n## 数据源：{binding.name}\n\n{summary}"
            )
        return await studio.generate(project_id, brief=brief)


__all__ = [
    "LiveArtifactEngine",
    "SourceBinding",
    "detect_kind",
    "render_summary",
    "validate_source_path",
]
