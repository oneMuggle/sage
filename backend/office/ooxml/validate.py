"""OOXML structural validation + xml:space repair (M5).

Not a full XSD validator: it checks archive safety, required parts, XML
well-formedness and DTD/entity rejection, and repairs the one issue that
silently breaks text fidelity in practice — ``w:t``/``a:t`` values with
leading/trailing whitespace but no ``xml:space="preserve"``.

``auto_repair`` writes a new ``<stem>-repaired.<ext>`` file (never
overwrites the source).
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..errors import OfficeFileNotFoundError, OfficeParseError
from ..path_safety import resolve_within
from ..storage import validate_workspace
from .archive import pack_ooxml, unpack_ooxml, validate_archive_members

logger = logging.getLogger(__name__)

__all__ = [
    "OoxmlValidateIssue",
    "OoxmlValidateRequest",
    "OoxmlValidateResult",
    "validate_ooxml",
]

_SUPPORTED_SUFFIXES = (".docx", ".xlsx", ".pptx")
_REQUIRED_PARTS = {
    ".docx": ("[Content_Types].xml", "_rels/.rels", "word/document.xml"),
    ".xlsx": ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"),
    ".pptx": ("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml"),
}
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class OoxmlValidateIssue(BaseModel):
    """One validation finding."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    message: str
    part: Optional[str] = None


class OoxmlValidateRequest(BaseModel):
    """POST /office/ooxml/validate request."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    auto_repair: bool = Field(
        default=False, description="修复 xml:space 缺失并输出 <stem>-repaired.<ext>"
    )


class OoxmlValidateResult(BaseModel):
    """Validation summary (valid = no error issues)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    valid: bool
    source_path: str
    issues: List[OoxmlValidateIssue] = Field(default_factory=list)
    repaired: bool = False
    repaired_path: Optional[str] = None
    warnings: List[Dict[str, str]] = Field(default_factory=list)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _parse_xml_part(name: str, data: bytes):
    """Return (root, repaired_root_bytes_or_None, issue)."""
    lowered = data.upper()
    if b"<!DOCTYPE" in lowered or b"<!ENTITY" in lowered:
        return None, None, OoxmlValidateIssue(
            code="xml_doctype_forbidden",
            severity="error",
            message="XML 包含 DTD/ENTITY（OOXML 不允许）",
            part=name,
        )
    try:
        from lxml import etree  # noqa: PLC0415 — python-docx guarantees lxml
    except Exception:  # noqa: BLE001 — fallback keeps validation useful
        etree = None
    if etree is None:
        try:
            from xml.etree import ElementTree  # noqa: PLC0415

            root = ElementTree.fromstring(data)
        except Exception as exc:  # noqa: BLE001
            return None, None, OoxmlValidateIssue(
                code="xml_parse_error",
                severity="error",
                message=f"XML 解析失败: {exc}",
                part=name,
            )
        return root, None, None
    try:
        root = etree.fromstring(data)
    except Exception as exc:  # noqa: BLE001
        return None, None, OoxmlValidateIssue(
            code="xml_parse_error",
            severity="error",
            message=f"XML 解析失败: {exc}",
            part=name,
        )
    repaired = 0
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str) or tag.split("}")[-1] != "t":
            continue
        text = element.text or ""
        if not text.strip() or text == text.strip():
            continue
        if _XML_SPACE not in element.attrib:
            element.set(_XML_SPACE, "preserve")
            repaired += 1
    if not repaired:
        return root, None, None
    rebuilt = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return (
        root,
        rebuilt,
        OoxmlValidateIssue(
            code="xml_space_missing",
            severity="warning",
            message=f"{repaired} 个文本节点缺少 xml:space=preserve",
            part=name,
        ),
    )


def _repair_archive(
    source: Path,
    workspace: Path,
    repaired_parts: Dict[str, bytes],
) -> Path:
    suffix = source.suffix.lower()
    target = source.with_name(f"{source.stem}-repaired{suffix}")
    counter = 2
    while target.exists():
        target = source.with_name(f"{source.stem}-repaired-{counter}{suffix}")
        counter += 1
    temp_dir = Path(tempfile.mkdtemp(prefix="sage-ooxml-repair-", dir=str(workspace)))
    try:
        unpack_ooxml(source, temp_dir)
        for name, data in repaired_parts.items():
            part_path = temp_dir / name
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.write_bytes(data)
        pack_ooxml(temp_dir, target)
    finally:
        import shutil  # noqa: PLC0415

        shutil.rmtree(str(temp_dir), ignore_errors=True)
    return target


def validate_ooxml(request: OoxmlValidateRequest) -> OoxmlValidateResult:
    """Validate a managed OOXML file, optionally writing an xml:space repair."""
    workspace = validate_workspace(Path(request.workspace_path))
    source = resolve_within(workspace, Path(request.file_path))
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise OfficeParseError("OOXML 校验仅支持 .docx/.xlsx/.pptx")

    issues: List[OoxmlValidateIssue] = []
    repaired_parts: Dict[str, bytes] = {}

    try:
        archive = zipfile.ZipFile(str(source))
    except (OSError, zipfile.BadZipFile) as exc:
        return OoxmlValidateResult(
            ok=False,
            valid=False,
            source_path=_rel(source, workspace),
            issues=[
                OoxmlValidateIssue(
                    code="archive_invalid",
                    severity="error",
                    message=f"无法打开 OOXML 包: {exc}",
                )
            ],
        )
    with archive:
        try:
            validate_archive_members(archive)
            broken = archive.testzip()
            if broken is not None:
                raise OfficeParseError(f"OOXML 包损坏（首个坏成员 {broken}）")
        except OfficeParseError as exc:
            return OoxmlValidateResult(
                ok=False,
                valid=False,
                source_path=_rel(source, workspace),
                issues=[
                    OoxmlValidateIssue(
                        code="archive_invalid", severity="error", message=str(exc)
                    )
                ],
            )
        names = {info.filename for info in archive.infolist()}
        for required in _REQUIRED_PARTS[source.suffix.lower()]:
            if required not in names:
                issues.append(
                    OoxmlValidateIssue(
                        code="required_part_missing",
                        severity="error",
                        message=f"缺少必需部件 {required}",
                        part=required,
                    )
                )
        for info in archive.infolist():
            name = info.filename
            if not (name.endswith(".xml") or name.endswith(".rels")):
                continue
            try:
                data = archive.read(info)
            except (KeyError, OSError) as exc:
                issues.append(
                    OoxmlValidateIssue(
                        code="part_unreadable",
                        severity="error",
                        message=f"部件无法读取: {exc}",
                        part=name,
                    )
                )
                continue
            _root, rebuilt, issue = _parse_xml_part(name, data)
            if issue is not None:
                issues.append(issue)
            if rebuilt is not None:
                repaired_parts[name] = rebuilt

    valid = not any(issue.severity == "error" for issue in issues)
    repaired_path: Optional[str] = None
    repaired = False
    if request.auto_repair and repaired_parts and valid:
        target = _repair_archive(source, workspace, repaired_parts)
        repaired = True
        repaired_path = _rel(target, workspace)

    return OoxmlValidateResult(
        ok=valid,
        valid=valid,
        source_path=_rel(source, workspace),
        issues=issues,
        repaired=repaired,
        repaired_path=repaired_path,
    )
