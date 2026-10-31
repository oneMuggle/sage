"""A small, fault-tolerant LaTeX scanner (no TeX execution, no third-party deps).

This is deliberately *not* a TeX engine. It understands just enough structure
for a semantic preview: commands and their brace/bracket arguments,
environments, comments, and top-level splitting for tabular rows/cells.
Unknown or malformed constructs are returned as raw text so the parser can
degrade gracefully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Command:
    name: str
    args: List[str] = field(default_factory=list)
    optional: List[str] = field(default_factory=list)
    starred: bool = False
    start: int = 0
    end: int = 0
    line: int = 0
    column: int = 0


_WS = " \t\r\n"


def line_col(text: str, pos: int) -> Tuple[int, int]:
    """Return 1-based (line, column) for ``pos``."""
    if pos < 0:
        pos = 0
    if pos > len(text):
        pos = len(text)
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    column = pos - last_nl
    return line, column


def strip_comments(text: str) -> str:
    """Remove ``%`` comments while preserving offsets/newlines.

    ``\\%`` is an escaped percent sign and is kept. Comment characters are
    replaced with spaces so line/column positions stay stable.
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            j = i
            while j < n and text[j] != "\n":
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)


def skip_ws(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos] in _WS:
        pos += 1
    return pos


def parse_group(
    text: str, pos: int, open_ch: str = "{", close_ch: str = "}"
) -> Tuple[Optional[str], int]:
    """Parse a balanced group starting at ``pos``.

    Returns ``(content, end_pos)``; ``content`` is ``None`` when ``pos`` does
    not point at ``open_ch``. Unbalanced input returns the remainder and the
    end of string so callers can still render something.
    """
    if pos >= len(text) or text[pos] != open_ch:
        return None, pos
    depth = 0
    i = pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[pos + 1 : i], i + 1
        i += 1
    return text[pos + 1 :], n


def _is_name_char(ch: str) -> bool:
    return ch.isalpha() or ch == "@"


def parse_command(text: str, pos: int) -> Optional[Command]:
    """Parse a command at ``pos`` (which must be ``\\``)."""
    if pos >= len(text) or text[pos] != "\\":
        return None
    start = pos
    i = pos + 1
    n = len(text)
    if i >= n:
        return None
    if _is_name_char(text[i]):
        j = i
        while j < n and _is_name_char(text[j]):
            j += 1
        name = text[i:j]
        i = j
    else:
        name = text[i]
        i += 1
    starred = False
    if i < n and text[i] == "*":
        starred = True
        i += 1
    optional: List[str] = []
    while True:
        j = skip_ws(text, i)
        if j < n and text[j] == "[":
            content, end = parse_group(text, j, "[", "]")
            if content is None or end <= j:
                break
            optional.append(content)
            i = end
        else:
            break
    args: List[str] = []
    while True:
        j = skip_ws(text, i)
        if j < n and text[j] == "{":
            content, end = parse_group(text, j, "{", "}")
            if content is None or end <= j:
                break
            args.append(content)
            i = end
        else:
            break
    line, column = line_col(text, start)
    return Command(
        name=name,
        args=args,
        optional=optional,
        starred=starred,
        start=start,
        end=i,
        line=line,
        column=column,
    )


def find_environment(
    text: str, search_from: int, name: str
) -> Optional[Tuple[int, int, int]]:
    """Find the matching ``\\end{name}`` for a ``\\begin{name}``.

    ``search_from`` must point just after the opening ``\\begin{name}``.
    Returns ``(content_start, content_end, end_after)`` or ``None``.
    """
    pattern = re.compile(
        r"\\(begin|end)\s*\{\s*" + re.escape(name) + r"\s*\}", re.S
    )
    depth = 1
    for match in pattern.finditer(text, search_from):
        if match.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return search_from, match.start(), match.end()
    return None


def find_environment_start(text: str, pos: int) -> Optional[Tuple[str, int, int]]:
    """Parse ``\\begin{name}`` at ``pos``.

    Returns ``(name, content_start, command_end)``.
    """
    cmd = parse_command(text, pos)
    if cmd is None or cmd.name != "begin" or not cmd.args:
        return None
    name = cmd.args[0].strip()
    return name, cmd.end, cmd.end


def split_top_level(text: str, separator: str) -> List[str]:
    """Split on a single-character separator at brace depth 0.

    Math delimiters are tracked so ``&`` inside ``$...$`` is not split.
    Backslash-escaped separators are kept.
    """
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    in_math = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            buf.append(ch)
            if i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        elif ch == "$":
            in_math = not in_math
        if ch == separator and depth == 0 and not in_math:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def split_rows(text: str) -> List[str]:
    """Split tabular body on top-level ``\\\\`` (or ``\\tabularnewline``)."""
    rows: List[str] = []
    buf: List[str] = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            if text.startswith("\\tabularnewline", i):
                if depth == 0:
                    rows.append("".join(buf))
                    buf = []
                i += len("\\tabularnewline")
                continue
            if i + 1 < n and text[i + 1] == "\\":
                if depth == 0:
                    rows.append("".join(buf))
                    buf = []
                i += 2
                # Optional spacing after \\, e.g. \\[2pt]
                j = skip_ws(text, i)
                if j < n and text[j] == "[":
                    _, end = parse_group(text, j, "[", "]")
                    i = end
                continue
            buf.append(ch)
            if i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        buf.append(ch)
        i += 1
    rows.append("".join(buf))
    return rows


def strip_row_noise(row: str) -> str:
    """Remove rules/whitespace commands that carry no cell content."""
    row = re.sub(
        r"\\(?:hline|toprule|midrule|bottomrule|endhead|endfirsthead|endfoot|endlastfoot)\b",
        " ",
        row,
    )
    row = re.sub(r"\\cline\s*\{[^{}]*\}", " ", row)
    return row.strip()


def split_cells(row: str) -> List[str]:
    cells = split_top_level(strip_row_noise(row), "&")
    return [cell.strip() for cell in cells]
