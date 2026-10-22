"""M5b：Office 只读 + 记忆/Wiki 检索（远程工作区）。

- ``office_read`` / ``office_lint_word``：权限 ``office``；只读；路径经
  :func:`remote_path.resolve` 校验（相对路径、逐段 lstat、拒绝符号链接与受保护路径）。
- ``wiki_search``：权限 ``memory``；只检索本工作区 wiki 目录。
- ``memory_search``：权限 ``memory``（默认关闭）；只读；仅开放 ``user`` /
  ``global`` 作用域（远程调用没有 Sage 会话，``session``/``project`` 无意义且
  可能串到其他会话），不含工作记忆。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from .remote_path import RemotePathError, resolve

MAX_OFFICE_JSON_CHARS = 256 * 1024
MAX_OFFICE_FILE_BYTES = 50 * 1024 * 1024
MAX_MEMORY_RESULTS = 50
MAX_MEMORY_TEXT = 4000
OFFICE_READERS = (".docx", ".xlsx", ".pptx", ".pdf", ".csv")
MEMORY_SCOPES = ("user", "global")
MEMORY_TYPES = ("all", "episodic", "semantic")


def _failure(message: str) -> Exception:
    from .tools import ToolFailure

    return ToolFailure(message)


def _office_path(ctx: Any, path: Any, suffixes: tuple) -> Path:
    try:
        absolute = resolve(ctx.root, path)
    except RemotePathError as exc:
        raise _failure(str(exc)) from None
    target = Path(absolute)
    if target.suffix.lower() not in suffixes:
        raise _failure("UNSUPPORTED_FILE_TYPE: supported: " + ", ".join(suffixes))
    if not target.is_file():
        raise _failure("NOT_FOUND: file does not exist")
    if target.stat().st_size > MAX_OFFICE_FILE_BYTES:
        raise _failure("FILE_TOO_LARGE: office files over 50 MiB are not read remotely")
    return target


def _read_model(target: Path, root: str, formulas: bool) -> Any:
    suffix = target.suffix.lower()
    if suffix == ".docx":
        from backend.office.word import read_docx

        return read_docx(target, workspace_path=root)
    if suffix == ".xlsx":
        from backend.office.excel import read_xlsx

        return read_xlsx(target, workspace_path=root, include_formulas=formulas)
    if suffix == ".csv":
        from backend.office.excel import read_csv

        return read_csv(target, workspace_path=root)
    if suffix == ".pptx":
        from backend.office.ppt import read_ppt

        return read_ppt(target, workspace_path=root)
    from backend.office.pdf import read_pdf

    return read_pdf(target, workspace_path=root)


def _dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        data = model.model_dump(mode="json")
    elif hasattr(model, "dict"):
        data = json.loads(model.json())
    else:
        data = dict(model)
    return data if isinstance(data, dict) else {"result": data}


def _strip_absolute(value: Any, root: str) -> Any:
    """递归去掉返回值里的本机绝对路径（只回显相对路径）。"""
    norm_root = root.replace("\\", "/").rstrip("/")
    if isinstance(value, dict):
        return {k: _strip_absolute(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_absolute(v, root) for v in value]
    if isinstance(value, str) and norm_root and norm_root.lower() in value.replace("\\", "/").lower():
        text = value.replace("\\", "/")
        idx = text.lower().index(norm_root.lower())
        rest = text[idx + len(norm_root):].lstrip("/")
        return rest or "."
    return value


def _fit(data: Dict[str, Any], section: str) -> Dict[str, Any]:
    """按 section 裁剪并保证序列化体积 ≤ MAX_OFFICE_JSON_CHARS。"""
    summary = data.get("summary")
    if section == "summary":
        slim = {"summary": summary} if summary is not None else {
            k: v for k, v in data.items() if not isinstance(v, (list, dict))}  # noqa: UP038 — py38
        slim["section"] = "summary"
        return slim
    out = dict(data)
    out["section"] = section
    out["truncated"] = False
    limit = MAX_OFFICE_JSON_CHARS if section == "all" else MAX_OFFICE_JSON_CHARS // 4
    if len(json.dumps(out, ensure_ascii=False)) <= limit:
        return out
    out["truncated"] = True
    # 逐步截短最大的列表字段，直到体积合规
    for _ in range(64):
        lists = [(k, v) for k, v in out.items() if isinstance(v, list) and v]
        if not lists or len(json.dumps(out, ensure_ascii=False)) <= limit:
            break
        key, items = max(lists, key=lambda kv: len(json.dumps(kv[1], ensure_ascii=False)))
        out[key] = items[: max(0, len(items) // 2)]
    if len(json.dumps(out, ensure_ascii=False)) > limit:
        out = {"summary": summary, "section": section, "truncated": True}
    return out


def _office_read(ctx: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    section = args.get("section") or "summary"
    if section not in ("summary", "head", "all"):
        raise _failure("INVALID_ARGUMENT: section must be summary|head|all")
    target = _office_path(ctx, args.get("path"), OFFICE_READERS)
    try:
        model = _read_model(target, ctx.root, bool(args.get("formulas")))
    except Exception as exc:  # noqa: BLE001 — Office 解析错误统一映射，不泄露路径
        raise _failure(f"OFFICE_READ_FAILED: {type(exc).__name__}") from None
    data = _strip_absolute(_dump(model), ctx.root)
    result = _fit(data, section)
    result["path"] = str(args.get("path"))
    return result


def _office_lint_word(ctx: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    spec_raw = args.get("format_spec")
    if not isinstance(spec_raw, dict) or not spec_raw:
        raise _failure("INVALID_ARGUMENT: format_spec (object) required")
    target = _office_path(ctx, args.get("path"), (".docx",))
    from backend.office.models import WordFormatSpec
    from backend.office.word_lint import lint_docx

    try:
        spec = WordFormatSpec(**spec_raw)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
        raise _failure(f"INVALID_ARGUMENT: format_spec invalid: {str(exc)[:500]}") from None
    try:
        result = lint_docx(target, spec)
    except Exception as exc:  # noqa: BLE001
        raise _failure(f"OFFICE_READ_FAILED: {type(exc).__name__}") from None
    data = _strip_absolute(_dump(result), ctx.root)
    data["path"] = str(args.get("path"))
    return data


def _limit(args: Dict[str, Any], default: int, cap: int) -> int:
    try:
        n = int(args.get("limit") or default)
    except (TypeError, ValueError):
        raise _failure("INVALID_ARGUMENT: limit must be an integer") from None
    return max(1, min(n, cap))


def _query(args: Dict[str, Any]) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise _failure("INVALID_ARGUMENT: query required")
    return query.strip()[:500]


def _wiki_search(ctx: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    query = _query(args)
    from backend.wiki.search import search_wiki

    try:
        response = search_wiki(Path(ctx.root), query, limit=_limit(args, 20, 100))
    except Exception as exc:  # noqa: BLE001
        raise _failure(f"SEARCH_FAILED: {type(exc).__name__}") from None
    hits = [{"title": h.title, "path": h.path, "snippet": h.snippet, "score": h.score}
            for h in response.results]
    return {"results": _strip_absolute(hits, ctx.root), "total": response.total}


def _default_memory() -> Any:
    from backend.memory.registry import get_memory_manager

    return get_memory_manager()


_memory_getter: Callable[[], Any] = _default_memory

_MEMORY_FIELDS = ("id", "memory_type", "content", "title", "summary", "tags", "scope",
                  "importance", "score", "created_at", "updated_at")


def _memory_search(ctx: Any, args: Dict[str, Any]) -> Dict[str, Any]:
    query = _query(args)
    scope = args.get("scope") or "user"
    if scope not in MEMORY_SCOPES:
        raise _failure("INVALID_ARGUMENT: scope must be user|global (session/project scopes "
                       "are not available remotely)")
    memory_type = args.get("memory_type") or "all"
    if memory_type not in MEMORY_TYPES:
        raise _failure("INVALID_ARGUMENT: memory_type must be all|episodic|semantic")
    limit = _limit(args, 20, MAX_MEMORY_RESULTS)
    try:
        manager = _memory_getter()
        rows = manager.search_memories(query, None if memory_type == "all" else memory_type,
                                       limit, session_id=None, scope=scope)
    except Exception as exc:  # noqa: BLE001
        raise _failure(f"SEARCH_FAILED: {type(exc).__name__}") from None
    results: List[Dict[str, Any]] = []
    for row in list(rows or [])[:limit]:
        if not isinstance(row, dict) or row.get("memory_type") == "working":
            continue
        item = {k: row[k] for k in _MEMORY_FIELDS if k in row}
        if isinstance(item.get("content"), str) and len(item["content"]) > MAX_MEMORY_TEXT:
            item["content"] = item["content"][:MAX_MEMORY_TEXT] + "…"
        results.append(item)
    return {"query": query, "scope": scope, "memory_type": memory_type,
            "results": json.loads(json.dumps(results, ensure_ascii=False, default=str))}


def build_tools(RemoteTool: Any, _schema: Callable[..., Dict[str, Any]],  # noqa: N803
                _PATH: Dict[str, Any]) -> List[Any]:  # noqa: N803
    """由 tools.py 注入 RemoteTool/_schema，避免循环导入。"""
    return [
        RemoteTool("office_read", "Read a .docx/.xlsx/.pptx/.pdf/.csv file in the workspace "
                   "(read-only). section: summary (metadata, default) | head (bounded) | all "
                   "(full, truncated past 256K chars). formulas=true reports Excel formulas.",
                   _schema({"path": _PATH,
                            "section": {"type": "string", "enum": ["summary", "head", "all"]},
                            "formulas": {"type": "boolean"}}, ["path"]),
                   "office", _office_read),
        RemoteTool("office_lint_word", "Check a .docx against a FormatSpec (page setup, body, "
                   "headings, numbering, header/footer). Read-only; returns violations.",
                   _schema({"path": _PATH, "format_spec": {"type": "object"}},
                           ["path", "format_spec"]),
                   "office", _office_lint_word),
        RemoteTool("wiki_search", "Search this workspace's wiki pages. Returns ranked hits "
                   "(title, relative path, snippet, score).",
                   _schema({"query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["query"]),
                   "memory", _wiki_search),
        RemoteTool("memory_search", "Search Sage long-term memory (read-only). Only user and "
                   "global scopes are available remotely; working memory is never exposed.",
                   _schema({"query": {"type": "string"},
                            "scope": {"type": "string", "enum": list(MEMORY_SCOPES)},
                            "memory_type": {"type": "string", "enum": list(MEMORY_TYPES)},
                            "limit": {"type": "integer", "minimum": 1,
                                      "maximum": MAX_MEMORY_RESULTS}}, ["query"]),
                   "memory", _memory_search),
    ]


__all__ = ["build_tools"]
