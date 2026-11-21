"""OOXML channel (M5): safe archive handling, structural validation, run coalescing."""

from .archive import pack_ooxml, unpack_ooxml, validate_archive_members
from .runs import OoxmlMergeRunsRequest, OoxmlMergeRunsResult, merge_docx_runs
from .validate import OoxmlValidateRequest, OoxmlValidateResult, validate_ooxml

__all__ = [
    "OoxmlMergeRunsRequest",
    "OoxmlMergeRunsResult",
    "OoxmlValidateRequest",
    "OoxmlValidateResult",
    "merge_docx_runs",
    "pack_ooxml",
    "unpack_ooxml",
    "validate_archive_members",
    "validate_ooxml",
]
