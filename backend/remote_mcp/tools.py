"""远程工具集（M1 只读 + M2 写入 + M3 命令）。

所有路径参数都是**工作区相对路径**，先经 :mod:`remote_path` 校验，再复用
Sage 内部工具实现（``ReadFileTool`` / ``WriteFileTool`` / ``EditTool`` /
``ApplyPatchTool``），因而继承其限额、BOM、换行保留、版本号、原子写与写互斥。

远程差异：写类工具的 ``expected_version`` **必填**（新文件传 ``"new"``）。
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.domain.tool_policy import ToolPolicy
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import ReadFileTool, WriteFileTool
from backend.tools.patch_tool import ApplyPatchTool

from . import SERVER_VERSION
from .jobs import JobManager
from .remote_path import (
    SKIP_WALK_SEGMENTS,
    RemotePathError,
    is_hidden_entry,
    resolve,
    to_relative,
)

MAX_LIST_ENTRIES = 500
MAX_FIND_RESULTS = 500
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_FILE_BYTES = 1024 * 1024
MAX_WALK_FILES = 20000


class ToolFailure(Exception):  # noqa: N818 — 对外错误名与计划文档一致
    """工具级失败：消息以错误码开头（``PERMISSION_DENIED`` / ``PATH_DENIED`` …）。"""


@dataclass
class ToolContext:
    workspace: Dict[str, Any]
    owner: str
    jobs: JobManager

    @property
    def root(self) -> str:
        return self.workspace["root"]


@dataclass
class RemoteTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    permission: Optional[str]
    handler: Callable[[ToolContext, Dict[str, Any]], Any]
    mutating: bool = False

    def descriptor(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def _schema(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [],
            "additionalProperties": False}


_PATH = {"type": "string", "description": "工作区相对路径，使用 / 分隔，如 src/app.py"}
_VERSION = {"type": "string", "description": 'read_file 返回的 version；新建文件传 "new"。必填'}


def _resolve(ctx: ToolContext, path: Any, **kwargs: Any) -> str:
    try:
        return resolve(ctx.root, path, **kwargs)
    except RemotePathError as exc:
        raise ToolFailure(str(exc)) from None


def _unwrap(result: Any, ctx: ToolContext) -> Dict[str, Any]:
    """ToolResult → dict；失败抛 ToolFailure；回显路径改为相对路径。"""
    if not result.success:
        raise ToolFailure(str(result.error))
    content = dict(result.content) if isinstance(result.content, dict) else {"result": result.content}
    if isinstance(content.get("path"), str):
        try:
            content["path"] = to_relative(ctx.root, content["path"])
        except ValueError:
            content.pop("path", None)
    return content


def _require_version(args: Dict[str, Any]) -> str:
    version = args.get("expected_version")
    if not isinstance(version, str) or not version.strip():
        raise ToolFailure(
            "VERSION_REQUIRED: remote writes must pass expected_version "
            '(the version from read_file, or "new" for a new file)'
        )
    return version


# ── 只读 ─────────────────────────────────────────────────────────────


def _connection_info(ctx: ToolContext, _args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "serverVersion": SERVER_VERSION,
        "transport": "streamable-http (JSON responses)",
        "sessionIdleTimeoutSeconds": 1800,
        "sessionRecovery": "On HTTP 404 SESSION_NOT_FOUND, initialize a new session and "
        "rediscover tools. Running commands do not transfer to the new session.",
        "uncertainResult": "If a mutating call times out, inspect state first; never replay it blindly.",
        "addressLifetime": "Quick Tunnel URLs change whenever the tunnel is recreated.",
        "paths": "All paths are relative to the workspace root and use '/'.",
    }


def _workspace_info(ctx: ToolContext, _args: Dict[str, Any]) -> Dict[str, Any]:
    perms = ctx.workspace.get("permissions", {})
    return {
        "name": ctx.workspace["name"],
        "read": True,
        "write": bool(perms.get("write")),
        "shell": bool(perms.get("shell")),
        "shellSandboxed": False,
        "shellInterpreter": "powershell" if os.name == "nt" else "sh",
        "writesRequireVersion": True,
    }


def _list_directory(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    rel = args.get("path") or "."
    target = _resolve(ctx, rel)
    if not os.path.isdir(target):
        raise ToolFailure("NOT_A_DIRECTORY: path is not a directory")
    entries = []
    names = sorted(os.listdir(target))
    for name in names:
        full = os.path.join(target, name)
        if is_hidden_entry(name) or Path(full).is_symlink():
            continue
        is_dir = os.path.isdir(full)
        entries.append({"name": name, "type": "directory" if is_dir else "file",
                        "size": None if is_dir else _safe_size(full)})
    entries.sort(key=lambda e: (e["type"] != "directory", e["name"].lower()))
    return {"path": to_relative(ctx.root, target), "entries": entries[:MAX_LIST_ENTRIES],
            "truncated": len(entries) > MAX_LIST_ENTRIES}


def _safe_size(path: str) -> Optional[int]:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def _walk_files(ctx: ToolContext, base_rel: str):
    base = _resolve(ctx, base_rel or ".")
    if not os.path.isdir(base):
        raise ToolFailure("NOT_A_DIRECTORY: path is not a directory")
    seen = 0
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs
            if not is_hidden_entry(d) and d not in SKIP_WALK_SEGMENTS
            and not Path(current, d).is_symlink()
        )
        for name in sorted(files):
            full = os.path.join(current, name)
            if is_hidden_entry(name) or Path(full).is_symlink():
                continue
            seen += 1
            if seen > MAX_WALK_FILES:
                return
            yield full


def _find_files(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > 300:
        raise ToolFailure("INVALID_ARGUMENT: pattern required (glob, e.g. **/*.py)")
    results = []
    truncated = False
    for full in _walk_files(ctx, args.get("path") or "."):
        rel = to_relative(ctx.root, full)
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            if len(results) >= MAX_FIND_RESULTS:
                truncated = True
                break
            results.append(rel)
    return {"files": results, "truncated": truncated}


def _search_files(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query or len(query) > 500:
        raise ToolFailure("INVALID_ARGUMENT: query required (max 500 chars)")
    flags = 0 if args.get("case_sensitive") else re.IGNORECASE
    try:
        matcher = re.compile(query if args.get("regex") else re.escape(query), flags)
    except re.error as exc:
        raise ToolFailure(f"INVALID_ARGUMENT: bad regex: {exc}") from None
    glob = args.get("glob")
    matches: List[Dict[str, Any]] = []
    for full in _walk_files(ctx, args.get("path") or "."):
        rel = to_relative(ctx.root, full)
        if isinstance(glob, str) and glob and not (
            fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(os.path.basename(rel), glob)
        ):
            continue
        size = _safe_size(full)
        if size is None or size > MAX_SEARCH_FILE_BYTES:
            continue
        try:
            with open(full, "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if matcher.search(line):
                matches.append({"path": rel, "line": number, "text": line[:300]})
                if len(matches) >= MAX_SEARCH_MATCHES:
                    return {"matches": matches, "truncated": True}
    return {"matches": matches, "truncated": False}


def _read_file(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    target = _resolve(ctx, args.get("path"))
    tool = ReadFileTool(policy=ToolPolicy(workspace_root=ctx.root))
    offset = int(args.get("offset") or 1)
    limit = max(1, min(int(args.get("limit") or 500), 2000))
    return _unwrap(tool.execute(path=target, offset=offset, limit=limit), ctx)


# ── 写入（M2）────────────────────────────────────────────────────────


def _write_file(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    version = _require_version(args)
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolFailure("INVALID_ARGUMENT: content must be a string")
    target = _resolve(ctx, args.get("path"), write=True, may_create=True)
    tool = WriteFileTool(policy=ToolPolicy(workspace_root=ctx.root))
    return _unwrap(tool.execute(path=target, content=content, expected_version=version), ctx)


def _edit_file(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    version = _require_version(args)
    target = _resolve(ctx, args.get("path"), write=True)
    tool = EditTool(policy=ToolPolicy(workspace_root=ctx.root))
    return _unwrap(
        tool.execute(
            file_path=target,
            old_string=args.get("old_string"),
            new_string=args.get("new_string"),
            replace_all=bool(args.get("replace_all", False)),
            expected_version=version,
        ),
        ctx,
    )


def _apply_patch(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    patches = args.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ToolFailure("INVALID_ARGUMENT: patches must be a non-empty list")
    converted = []
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            raise ToolFailure(f"INVALID_ARGUMENT: patches[{index}] must be an object")
        _require_version(patch)
        item = dict(patch)
        item["file_path"] = _resolve(ctx, patch.get("path"), write=True)
        item.pop("path", None)
        converted.append(item)
    tool = ApplyPatchTool(policy=ToolPolicy(workspace_root=ctx.root))
    result = _unwrap(tool.execute(patches=converted), ctx)
    for changed in result.get("files_changed", []):
        if isinstance(changed.get("path"), str):
            changed["path"] = to_relative(ctx.root, changed["path"])
    return result


# ── 命令（M3）────────────────────────────────────────────────────────


def _run_command(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip() or len(command) > 8000:
        raise ToolFailure("INVALID_ARGUMENT: command required (max 8000 chars)")
    cwd = _resolve(ctx, args.get("cwd") or ".")
    if not os.path.isdir(cwd):
        raise ToolFailure("NOT_A_DIRECTORY: cwd is not a directory")
    from .jobs import JobError

    try:
        return ctx.jobs.run(ctx.owner, ctx.workspace["id"], cwd, command,
                            timeout_seconds=int(args.get("timeoutSeconds") or 30))
    except JobError as exc:
        raise ToolFailure(str(exc)) from None


def _job_call(method: str) -> Callable[[ToolContext, Dict[str, Any]], Any]:
    def handler(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
        from .jobs import JobError

        job_id = args.get("jobId")
        if not isinstance(job_id, str):
            raise ToolFailure("INVALID_ARGUMENT: jobId required")
        try:
            return getattr(ctx.jobs, method)(job_id, ctx.owner)
        except JobError as exc:
            raise ToolFailure(str(exc)) from None

    return handler


_PATCH_ITEM = _schema(
    {"path": _PATH, "old_string": {"type": "string"}, "new_string": {"type": "string"},
     "replace_all": {"type": "boolean"}, "expected_version": _VERSION},
    ["path", "old_string", "new_string", "expected_version"],
)

TOOLS: List[RemoteTool] = [
    RemoteTool("connection_info", "Connection diagnostics and recovery rules. Never replay "
               "file writes or commands automatically after a transport failure.",
               _schema({}), None, _connection_info),
    RemoteTool("workspace_info", "Workspace name and current permissions (read/write/shell).",
               _schema({}), None, _workspace_info),
    RemoteTool("list_directory", "List a workspace directory (max 500 entries). Protected "
               "entries (.git, credentials) and symlinks are hidden.",
               _schema({"path": _PATH}), "read", _list_directory),
    RemoteTool("find_files", "Find files by glob pattern (matched against the relative path "
               "and the file name). Skips node_modules, build output and protected paths.",
               _schema({"pattern": {"type": "string"}, "path": _PATH}, ["pattern"]), "read", _find_files),
    RemoteTool("search_files", "Search text in workspace files (literal by default, regex=true "
               "for regular expressions). Max 200 matches; files > 1 MiB and binaries skipped.",
               _schema({"query": {"type": "string"}, "path": _PATH, "glob": {"type": "string"},
                        "regex": {"type": "boolean"}, "case_sensitive": {"type": "boolean"}},
                       ["query"]), "read", _search_files),
    RemoteTool("read_file", "Read a text file. Returns content lines and the whole-file "
               "version (sha256) required by write_file / edit_file / apply_patch.",
               _schema({"path": _PATH, "offset": {"type": "integer", "minimum": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 2000}}, ["path"]),
               "read", _read_file),
    RemoteTool("write_file", "Create or overwrite a file. expected_version is REQUIRED: the "
               'version from read_file, or "new" to create. Parent directory must exist.',
               _schema({"path": _PATH, "content": {"type": "string"}, "expected_version": _VERSION},
                       ["path", "content", "expected_version"]), "write", _write_file, True),
    RemoteTool("edit_file", "Exact string replacement in an existing file (unique match unless "
               "replace_all). expected_version from read_file is REQUIRED.",
               _schema({"path": _PATH, "old_string": {"type": "string"}, "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean"}, "expected_version": _VERSION},
                       ["path", "old_string", "new_string", "expected_version"]), "write", _edit_file, True),
    RemoteTool("apply_patch", "Atomic multi-file exact replacements: all patches validated "
               "first, nothing written if any fails. Each item needs expected_version.",
               _schema({"patches": {"type": "array", "items": _PATCH_ITEM, "maxItems": 32}}, ["patches"]),
               "write", _apply_patch, True),
    RemoteTool("run_command", "Run a shell command in the workspace (PowerShell on Windows, sh "
               "elsewhere). NOT sandboxed: runs with the local user's privileges. Waits up to 10 s, "
               "then returns a jobId; max 120 s total, last 64K chars of output kept.",
               _schema({"command": {"type": "string"}, "cwd": _PATH,
                        "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 120}}, ["command"]),
               "shell", _run_command, True),
    RemoteTool("get_command_output", "Read status and output of this session's command.",
               _schema({"jobId": {"type": "string"}}, ["jobId"]), "shell", _job_call("output")),
    RemoteTool("cancel_command", "Stop this session's command and its process tree.",
               _schema({"jobId": {"type": "string"}}, ["jobId"]), "shell", _job_call("cancel"), True),
]

TOOLS_BY_NAME: Dict[str, RemoteTool] = {t.name: t for t in TOOLS}

__all__ = ["TOOLS", "TOOLS_BY_NAME", "RemoteTool", "ToolContext", "ToolFailure"]
