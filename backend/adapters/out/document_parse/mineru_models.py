"""MinerU v1 Tasks 响应模型、请求体与结果包解包（纯函数）。"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .mineru_errors import MineruRemoteError

TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "canceled"})
FILE_STATUSES = frozenset(
    {"waiting-file", "pending", "running", "completed", "failed", "canceled"}
)
_MAX_ZIP_MEMBERS = 5000


@dataclass(frozen=True)
class UploadTarget:
    url: str
    headers: Dict[str, str]


@dataclass(frozen=True)
class TaskFile:
    file_id: Optional[str]
    file_name: str
    status: str
    size: Optional[int]
    upload: Optional[UploadTarget]
    result_url: Optional[str]


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    status: str
    files: List[TaskFile]
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class MineruOutput:
    markdown: str = ""
    structured: Optional[Dict[str, Any]] = None
    images: Dict[str, bytes] = field(default_factory=dict)
    file_bytes: Optional[bytes] = None
    file_ext: Optional[str] = None
    status: str = "completed"


def build_create_body(
    *,
    filename: str,
    content: bytes,
    page_range: Optional[str],
    output_formats: Sequence[str],
    tier: Optional[str],
    ocr_mode: Optional[str],
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "file_name": filename,
        "bytes": len(content),
        "sha256sum": hashlib.sha256(content).hexdigest(),
    }
    if page_range:
        item["page_range"] = page_range
    body: Dict[str, Any] = {"files": [item], "output_formats": list(output_formats)}
    if tier:
        body["tier"] = tier
    if ocr_mode:
        body["ocr_mode"] = ocr_mode
    return body


def _upload_target(raw: Any, file_status: str) -> Optional[UploadTarget]:
    if raw is None:
        return None
    if not isinstance(raw, dict) or file_status != "waiting-file":
        raise MineruRemoteError("invalid_response", "invalid task upload descriptor")
    url = raw.get("url")
    headers = raw.get("headers") or {}
    if not isinstance(url, str) or not url:
        raise MineruRemoteError("invalid_response", "upload.url missing")
    if not isinstance(headers, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
    ):
        raise MineruRemoteError("invalid_response", "upload.headers must be a string mapping")
    return UploadTarget(url=url, headers=dict(headers))


def parse_task_snapshot(payload: Any) -> TaskSnapshot:
    if not isinstance(payload, dict):
        raise MineruRemoteError("invalid_response", "response must be a JSON object")
    task_id = payload.get("task_id")
    status = payload.get("status")
    files = payload.get("files")
    if (
        not isinstance(task_id, str)
        or not task_id
        or not isinstance(status, str)
        or status not in FILE_STATUSES | TERMINAL_STATUSES
        or not isinstance(files, list)
        or len(files) != 1
        or not isinstance(files[0], dict)
    ):
        raise MineruRemoteError("invalid_response", "inconsistent Tasks response")
    item = files[0]
    file_status = item.get("status")
    if not isinstance(file_status, str) or file_status not in FILE_STATUSES:
        raise MineruRemoteError("invalid_response", "invalid task file state")
    name = item.get("file_name")
    if not isinstance(name, str) or not name:
        raise MineruRemoteError("invalid_response", "task file_name missing")
    task_file = TaskFile(
        file_id=item.get("file_id") if isinstance(item.get("file_id"), str) else None,
        file_name=name,
        status=file_status,
        size=item.get("bytes") if isinstance(item.get("bytes"), int) else None,
        upload=_upload_target(item.get("upload"), file_status),
        result_url=item.get("result_url")
        if isinstance(item.get("result_url"), str)
        else None,
    )
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return TaskSnapshot(
        task_id=task_id,
        status=status,
        files=[task_file],
        error_code=error.get("code") if isinstance(error.get("code"), str) else None,
        error_message=error.get("message")
        if isinstance(error.get("message"), str)
        else None,
    )


def unpack_result_payload(
    payload: bytes,
    output_formats: Sequence[str],
    status: str,
) -> MineruOutput:
    formats = list(output_formats)
    if formats in (["docx"], ["html"]):
        return MineruOutput(file_bytes=payload, file_ext=formats[0], status=status)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise MineruRemoteError("invalid_zip_output", "result is not a valid ZIP") from exc
    with archive:
        names = archive.namelist()
        if len(names) > _MAX_ZIP_MEMBERS:
            raise MineruRemoteError("invalid_zip_output", "result ZIP has too many members")
        name_set = set(names)
        markdown = (
            archive.read("markdown.md").decode("utf-8", "replace")
            if "markdown.md" in name_set
            else ""
        )
        structured: Optional[Dict[str, Any]] = None
        for candidate in ("middle_json.json", "layout.json"):
            if candidate not in name_set:
                continue
            try:
                loaded = json.loads(archive.read(candidate))
            except json.JSONDecodeError as exc:
                raise MineruRemoteError(
                    "invalid_middle_json_output", "middle_json is not valid JSON"
                ) from exc
            if isinstance(loaded, dict):
                structured = loaded
            break
        images = {
            name: archive.read(name)
            for name in sorted(name_set)
            if name.startswith("images/") and not name.endswith("/")
        }
    return MineruOutput(
        markdown=markdown,
        structured=structured,
        images=images,
        status=status,
    )
