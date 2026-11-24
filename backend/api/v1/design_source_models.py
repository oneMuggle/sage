"""Request bodies for design routes that accept an Office source.

``file_path`` and ``doc_id`` are mutually exclusive. The validator is
branched on the installed pydantic major version because v1's root validator
takes ``(cls, values)`` while v2's model validator takes ``self`` — the
shims below only rename symbols, they do not adapt signatures.

This module is deliberately self-contained (no ``backend.compat`` import) so
that ``main`` and ``release/win7`` keep byte-identical copies.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

try:  # pydantic 2.x —— main 分支
    from pydantic import ConfigDict, model_validator

    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover — win7 py38 钉 pydantic 1.10
    from pydantic import root_validator

    PYDANTIC_V2 = False

    def ConfigDict(**kwargs: Any) -> Dict[str, Any]:  # noqa: N802
        """v1 没有 ConfigDict；返回普通 dict，交给 win7 的 metaclass 钩子。"""
        return dict(kwargs)

    def model_validator(*, mode: str = "after", **kw: Any):  # noqa: N802
        """v1 的 root_validator 不接受 mode 参数。"""
        return root_validator(**kw)


def _require_exactly_one(file_path: Any, doc_id: Any) -> None:
    has_path = bool(file_path and str(file_path).strip())
    has_id = bool(doc_id and str(doc_id).strip())
    if has_path == has_id:
        raise ValueError("必须且只能提供 file_path 或 doc_id 之一")


class OfficeSourceBody(BaseModel):
    """Base body carrying the mutually exclusive source selectors."""

    model_config = ConfigDict(extra="forbid")

    file_path: Optional[str] = None
    doc_id: Optional[str] = None

    if PYDANTIC_V2:

        @model_validator(mode="after")
        def _exactly_one_source(self) -> OfficeSourceBody:
            _require_exactly_one(self.file_path, self.doc_id)
            return self

    else:  # pragma: no cover — win7 py38 + pydantic 1.10

        @model_validator()
        @classmethod
        def _exactly_one_source(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            _require_exactly_one(
                values.get("file_path"), values.get("doc_id"),
            )
            return values


class OutlineRequest(OfficeSourceBody):
    """POST /design/outline body."""


class SourcePreviewRequest(OfficeSourceBody):
    """POST /design/source/preview body."""


class BindSourceRequest(OfficeSourceBody):
    """POST /design/projects/{id}/source body."""

    kind: Optional[str] = None
    name: Optional[str] = None
