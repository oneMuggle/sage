"""Fault-tolerant LaTeX project parser for read-only semantic preview.

The parser never executes TeX. It resolves ``\\input``/``\\include`` within a
workspace root, extracts common journal-paper structure, and degrades unknown
commands/environments to text + warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within

from .environments import _EnvironmentMixin
from .inline import _InlineMixin
from .models import (
    LatexAnchor,
    LatexBlock,
    LatexDocument,
    LatexMetadata,
    LatexWarning,
)
from .scanner import (
    Command,
    find_environment,
    line_col,
    parse_command,
    strip_comments,
)
from .utils import split_keywords


@dataclass
class LatexLimits:
    max_file_bytes: int = 5 * 1024 * 1024
    max_project_bytes: int = 20 * 1024 * 1024
    max_include_depth: int = 20
    max_files: int = 200
    max_blocks: int = 5000
    max_image_bytes: int = 2 * 1024 * 1024


_HEADING_LEVELS = {
    "part": 1,
    "chapter": 1,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}

_BLOCK_COMMANDS = set(_HEADING_LEVELS) | {
    "maketitle",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "appendix",
    "newpage",
    "clearpage",
    "pagebreak",
    "bibliography",
    "bibliographystyle",
    "printbibliography",
    "input",
    "include",
    "subfile",
    "title",
    "author",
    "affil",
    "affiliation",
    "institute",
    "email",
    "date",
    "keywords",
    "par",
}

class _Parser(_InlineMixin, _EnvironmentMixin):
    def __init__(self, root: Path, limits: LatexLimits) -> None:
        self.root = root.resolve()
        self.limits = limits
        self.metadata = LatexMetadata()
        self.blocks: List[LatexBlock] = []
        self.warnings: List[LatexWarning] = []
        self.includes: List[str] = []
        self.visited: set = set()
        self.labels: Dict[str, Dict[str, Any]] = {}
        self.cite_keys: List[str] = []
        self.figure_no = 0
        self.table_no = 0
        self.equation_no = 0
        self.current_heading: Optional[str] = None
        self.total_bytes = 0
        self._warned: set = set()
        self._warned_unknown: set = set()
        self._block_limit_warned = False
        self._fatal_main: Optional[Path] = None

    # ---------- public ----------

    def parse(self, main_path: Path) -> LatexDocument:
        self._parse_file(main_path, depth=0, is_main=True)
        self._resolve_references()
        return LatexDocument(
            source_path=self._rel(main_path),
            metadata=self.metadata,
            blocks=self.blocks,
            warnings=self.warnings,
            includes=list(self.includes),
            citations=list(self.cite_keys),
        )

    # ---------- file/project ----------

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.name

    def _warn(
        self,
        code: str,
        message: str,
        *,
        file_path: Optional[Path] = None,
        text: Optional[str] = None,
        pos: int = 0,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        anchor = None
        if file_path is not None:
            line, column = line_col(text or "", pos)
            anchor = LatexAnchor(self._rel(file_path), line, column)
        key = (code, message, anchor.file if anchor else "", anchor.line if anchor else 0)
        if key in self._warned:
            return
        self._warned.add(key)
        self.warnings.append(
            LatexWarning(code=code, message=message, anchor=anchor, detail=detail or {})
        )

    def _append_block(self, block: LatexBlock) -> None:
        if len(self.blocks) >= self.limits.max_blocks:
            if not self._block_limit_warned:
                self._block_limit_warned = True
                self._warn(
                    "block_limit",
                    "文档块数超过上限，后续内容已截断",
                    detail={"max_blocks": self.limits.max_blocks},
                )
            return
        self.blocks.append(block)

    def _read_text(self, path: Path, *, is_main: bool) -> Optional[str]:  # noqa: PLR0911
        try:
            resolved = path.resolve()
        except OSError as exc:
            if is_main:
                raise OfficeParseError("无法解析 LaTeX 路径") from exc
            self._warn("include_resolve_error", "无法解析 include 路径", file_path=path)
            return None
        if not is_within(self.root, resolved):
            message = "路径不在工作区/项目目录内"
            if is_main:
                raise OfficePathError(message, file_path=path)
            self._warn(
                "include_path_escape",
                message,
                file_path=path,
                detail={"target": str(path)},
            )
            return None
        if not resolved.is_file():
            if is_main:
                raise OfficeFileNotFoundError(path)
            self._warn(
                "missing_include",
                "include 文件不存在",
                file_path=path,
                detail={"target": str(path)},
            )
            return None
        try:
            size = resolved.stat().st_size
        except OSError:
            size = 0
        if size > self.limits.max_file_bytes:
            if is_main:
                raise OfficeSizeLimitError(size, self.limits.max_file_bytes)
            self._warn(
                "include_too_large",
                "include 文件超过大小上限，已跳过",
                file_path=path,
                detail={"size": size},
            )
            return None
        self.total_bytes += size
        if self.total_bytes > self.limits.max_project_bytes:
            self._warn(
                "project_size_limit",
                "项目总大小超过上限，后续 include 已跳过",
                file_path=path,
            )
            return None
        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            if is_main:
                raise OfficeParseError("读取 LaTeX 文件失败") from exc
            self._warn("include_read_error", "读取 include 文件失败", file_path=path)
            return None

    def _parse_file(self, path: Path, *, depth: int, is_main: bool) -> None:
        if depth > self.limits.max_include_depth:
            self._warn("include_depth_exceeded", "include 深度超过上限", file_path=path)
            return
        if len(self.visited) >= self.limits.max_files:
            self._warn("include_file_limit", "include 文件数超过上限", file_path=path)
            return
        try:
            resolved = path.resolve()
        except OSError:
            self._warn("include_resolve_error", "无法解析 include 路径", file_path=path)
            return
        if resolved in self.visited:
            self._warn(
                "include_cycle",
                "检测到循环 include，已跳过",
                file_path=path,
                detail={"target": self._rel(path)},
            )
            return
        raw = self._read_text(resolved, is_main=is_main)
        if raw is None:
            return
        self.visited.add(resolved)
        if is_main:
            self._fatal_main = resolved
        self.includes.append(self._rel(resolved))
        text = strip_comments(raw)
        preamble, body = self._split_document(text, is_main=is_main)
        if is_main and preamble:
            self._parse_preamble(preamble, resolved)
        if body.strip():
            self._parse_blocks(body, resolved, depth)

    def _split_document(self, text: str, *, is_main: bool) -> Tuple[str, str]:
        match = re.search(r"\\begin\s*\{\s*document\s*\}", text)
        if match is None:
            return (text, "") if is_main else ("", text)
        end = text.rfind("\\end{document}")
        body_end = end if end >= match.end() else len(text)
        return text[: match.start()], text[match.end() : body_end]

    # ---------- preamble ----------

    def _parse_preamble(self, text: str, file_path: Path) -> None:
        pos = 0
        n = len(text)
        while pos < n:
            idx = text.find("\\", pos)
            if idx < 0:
                break
            cmd = parse_command(text, idx)
            if cmd is None:
                pos = idx + 1
                continue
            if cmd.name == "documentclass" and cmd.args:
                self.metadata.document_class = cmd.args[0].strip()
                if cmd.optional:
                    self.metadata.document_options = [
                        part.strip()
                        for part in cmd.optional[0].split(",")
                        if part.strip()
                    ]
            elif cmd.name == "title" and cmd.args:
                self.metadata.title = self._to_plain_text(cmd.args[0])
            elif cmd.name == "author" and cmd.args:
                self.metadata.authors = self._split_authors(cmd.args[0])
            elif cmd.name in ("affil", "affiliation", "institute") and cmd.args:
                self.metadata.affiliations = self._split_authors(cmd.args[0])
            elif cmd.name == "email" and cmd.args:
                email = self._to_plain_text(cmd.args[0]).strip()
                if email:
                    self.metadata.emails.append(email)
            elif cmd.name == "date" and cmd.args:
                self.metadata.date = self._to_plain_text(cmd.args[0])
            elif cmd.name == "keywords" and cmd.args:
                self.metadata.keywords = split_keywords(
                    self._to_plain_text(cmd.args[0])
                )
            elif cmd.name == "begin" and cmd.args:
                env = cmd.args[0].strip()
                found = find_environment(text, cmd.end, env)
                if found is not None:
                    content_start, content_end, end_after = found
                    content = text[content_start:content_end]
                    if env == "abstract":
                        self.metadata.abstract = self._to_plain_text(content).strip()
                    elif env in ("keywords", "keyword"):
                        self.metadata.keywords = split_keywords(
                            self._to_plain_text(content)
                        )
                    pos = end_after
                    continue
            pos = cmd.end if cmd.end > idx else idx + 1

    def _split_authors(self, value: str) -> List[str]:
        parts = re.split(r"\\and\b", value)
        if len(parts) == 1:
            parts = re.split(r"\\\\(?:\[[^\]]*\])?", value)
        return [p.strip() for p in (self._to_plain_text(x) for x in parts) if p.strip()]

    # ---------- body ----------

    def _parse_blocks(self, text: str, file_path: Path, depth: int) -> None:
        pos = 0
        n = len(text)
        buf: List[str] = []
        para_start: Optional[int] = None

        def flush() -> None:
            nonlocal buf, para_start
            if not buf:
                para_start = None
                return
            raw = "".join(buf)
            md = self._to_markdown(raw, file_path, text, para_start or 0)
            if md.strip():
                anchor = self._anchor(file_path, text, para_start or 0)
                self._append_block(LatexBlock("paragraph", text=md.strip(), anchor=anchor))
            buf = []
            para_start = None

        while pos < n:
            ch = text[pos]
            if text.startswith("\\[", pos):
                flush()
                end = text.find("\\]", pos + 2)
                if end < 0:
                    end = n
                    self._warn(
                        "unclosed_math",
                        "未闭合的 \\[ 数学块",
                        file_path=file_path,
                        text=text,
                        pos=pos,
                    )
                latex = text[pos + 2 : end]
                self._append_equation(latex, file_path, text, pos)
                pos = end + 2
                continue
            if text.startswith("\\(", pos):
                if para_start is None:
                    para_start = pos
                end = text.find("\\)", pos + 2)
                if end < 0:
                    end = n
                buf.append("$" + text[pos + 2 : end] + "$")
                pos = end + 2
                continue
            if ch == "\\":
                cmd = parse_command(text, pos)
                if cmd is None:
                    if para_start is None:
                        para_start = pos
                    buf.append(ch)
                    pos += 1
                    continue
                if cmd.name == "begin" and cmd.args:
                    found = find_environment(text, cmd.end, cmd.args[0].strip())
                    flush()
                    if found is None:
                        self._warn(
                            "unclosed_environment",
                            f"环境缺少对应的 \\end{{{cmd.args[0].strip()}}}",
                            file_path=file_path,
                            text=text,
                            pos=cmd.start,
                        )
                        pos = cmd.end
                        continue
                    content_start, content_end, end_after = found
                    self._handle_environment(
                        cmd.args[0].strip(),
                        text[content_start:content_end],
                        file_path,
                        text,
                        cmd,
                        depth,
                    )
                    pos = end_after
                    continue
                if cmd.name == "end":
                    pos = cmd.end
                    continue
                if cmd.name in _HEADING_LEVELS:
                    flush()
                    title = self._to_markdown(
                        cmd.args[0] if cmd.args else "", file_path, text, cmd.start
                    )
                    level = _HEADING_LEVELS[cmd.name]
                    self.current_heading = title
                    self._append_block(
                        LatexBlock(
                            "heading",
                            level=level,
                            text=title,
                            anchor=self._anchor(file_path, text, cmd.start),
                        )
                    )
                    pos = cmd.end
                    continue
                if cmd.name in ("input", "include", "subfile"):
                    flush()
                    if cmd.args:
                        self._parse_include(cmd.args[0], file_path, depth, cmd, text)
                    pos = cmd.end
                    continue
                if cmd.name == "bibliography":
                    flush()
                    if cmd.args:
                        self._add_bibliography_file(
                            cmd.args[0], file_path, cmd, text
                        )
                    pos = cmd.end
                    continue
                if cmd.name == "keywords":
                    flush()
                    if cmd.args:
                        self.metadata.keywords = split_keywords(
                            self._to_plain_text(cmd.args[0])
                        )
                    pos = cmd.end
                    continue
                if cmd.name in _BLOCK_COMMANDS:
                    flush()
                    pos = cmd.end
                    continue
                if para_start is None:
                    para_start = pos
                buf.append(text[pos : cmd.end])
                pos = cmd.end
                continue

            if text.startswith("$$", pos):
                flush()
                end = text.find("$$", pos + 2)
                if end < 0:
                    end = n
                    self._warn(
                        "unclosed_math",
                        "未闭合的 $$ 数学块",
                        file_path=file_path,
                        text=text,
                        pos=pos,
                    )
                latex = text[pos + 2 : end]
                self._append_equation(latex, file_path, text, pos)
                pos = end + 2
                continue
            if ch == "$":
                if para_start is None:
                    para_start = pos
                end = self._find_math_end(text, pos + 1)
                if end < 0:
                    buf.append(text[pos:])
                    pos = n
                    continue
                buf.append(text[pos : end + 1])
                pos = end + 1
                continue
            if ch == "\n":
                j = pos + 1
                while j < n and text[j] in " \t\r":
                    j += 1
                if j >= n or text[j] == "\n":
                    flush()
                    pos = j
                    continue
                if buf:
                    buf.append(" ")
                pos += 1
                continue
            if ch in " \t\r":
                if buf:
                    buf.append(" ")
                pos += 1
                continue
            if para_start is None:
                para_start = pos
            buf.append(ch)
            pos += 1
        flush()

    # ---------- environments ----------

    def _parse_include(
        self,
        raw: str,
        file_path: Path,
        depth: int,
        cmd: Command,
        text: str,
    ) -> None:
        target = raw.strip().strip('"')
        if not target:
            return
        if target.startswith(("http://", "https://")) or "|" in target:
            self._warn(
                "include_unsafe_target",
                "拒绝 URL/管道 include",
                file_path=file_path,
                text=text,
                pos=cmd.start,
                detail={"target": target},
            )
            return
        candidates = [file_path.parent / target, self.root / target]
        if not Path(target).suffix:
            candidates = [
                file_path.parent / (target + ".tex"),
                self.root / (target + ".tex"),
            ] + candidates
        chosen = next((p for p in candidates if p.is_file()), None)
        if chosen is None:
            self._warn(
                "missing_include",
                "include 文件不存在",
                file_path=file_path,
                text=text,
                pos=cmd.start,
                detail={"target": target},
            )
            return
        try:
            chosen.resolve().relative_to(self.root)
        except ValueError:
            self._warn(
                "include_path_escape",
                "include 路径不在项目目录内",
                file_path=file_path,
                text=text,
                pos=cmd.start,
                detail={"target": target},
            )
            return
        self._parse_file(chosen, depth=depth + 1, is_main=False)

    # ---------- inline markdown ----------


def _detect_main_tex(root: Path) -> Path:
    candidates: List[Path] = []
    for path in root.rglob("*.tex"):
        try:
            if path.stat().st_size > 5 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\\documentclass\b", text):
            candidates.append(path)
    if not candidates:
        raise OfficeParseError("未找到包含 \\documentclass 的 .tex 主文件")
    preferred = ("main.tex", "paper.tex", "document.tex", "template.tex", "sample.tex")
    for name in preferred:
        for path in candidates:
            if path.name.lower() == name:
                return path
    return sorted(candidates)[0]


def parse_latex_project(
    main_path: Path,
    *,
    root: Optional[Path] = None,
    limits: Optional[LatexLimits] = None,
) -> LatexDocument:
    """Parse a LaTeX file/project for read-only preview."""
    source = Path(main_path)
    root_path = Path(root).resolve() if root is not None else source.resolve().parent
    if not root_path.is_dir():
        raise OfficeParseError("LaTeX 项目根目录不存在")
    if source.is_dir():
        source = _detect_main_tex(root_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析 LaTeX 文件路径") from exc
    if not is_within(root_path, resolved):
        raise OfficePathError("LaTeX 文件不在项目目录内", file_path=source)
    parser = _Parser(root_path, limits or LatexLimits())
    return parser.parse(resolved)
