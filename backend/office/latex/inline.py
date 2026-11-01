"""Inline Markdown/plain-text conversion for the LaTeX parser."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import List, Optional

from .models import LatexAnchor
from .scanner import Command, line_col, parse_command

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

_FORMAT_COMMANDS = {
    "textbf": ("**", "**"),
    "textit": ("*", "*"),
    "emph": ("*", "*"),
    "texttt": ("`", "`"),
    "textsl": ("*", "*"),
    "textsc": ("", ""),
    "underline": ("", ""),
    "text": ("", ""),
    "mathrm": ("", ""),
    "mathbf": ("", ""),
    "mathit": ("", ""),
    "mathcal": ("", ""),
    "mbox": ("", ""),
}

_IGNORE_COMMANDS = {
    "noindent", "indent", "centering", "raggedright", "raggedleft",
    "small", "footnotesize", "scriptsize", "tiny", "normalsize",
    "large", "Large", "LARGE", "huge", "Huge", "vspace", "hspace",
    "vfill", "hfill", "setlength", "addtolength", "pagestyle",
    "thispagestyle", "pagenumbering", "linespread", "selectfont",
    "fontsize", "renewcommand", "newcommand", "providecommand", "def",
    "newenvironment", "renewenvironment", "usepackage", "RequirePackage",
    "documentclass", "geometry",
}


class _InlineMixin:
    def _to_markdown(
        self, text: str, file_path: Path, source: str, base_pos: int
    ) -> str:
        out: List[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                cmd = parse_command(text, i)
                if cmd is None:
                    out.append(ch)
                    i += 1
                    continue
                out.append(self._command_to_markdown(cmd, file_path, source, base_pos + i))
                i = cmd.end
                continue
            if ch == "$":
                end = self._find_math_end(text, i + 1)
                if end < 0:
                    out.append(text[i:])
                    break
                out.append(text[i : end + 1])
                i = end + 1
                continue
            if ch == "~" or ch == "\n" or ch in " \t\r":
                out.append(" ")
            else:
                out.append(ch)
            i += 1
        return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()

    def _command_to_markdown(  # noqa: PLR0911
        self, cmd: Command, file_path: Path, source: str, pos: int
    ) -> str:
        name = cmd.name
        if name == "label":
            key = cmd.args[0].strip() if cmd.args else ""
            if key:
                self._labels_set(
                    key,
                    "section",
                    0,
                    self.current_heading or key,
                    self._anchor(file_path, source, pos),
                )
            return ""
        if name in ("ref", "eqref", "autoref", "pageref", "nameref"):
            target = cmd.args[0].strip() if cmd.args else ""
            return f"{{{{ref:{target}}}}}"
        if name in ("cite", "citep", "citet", "citeauthor", "citeyear", "parencite", "textcite"):
            keys = [k.strip() for k in (cmd.args[0] if cmd.args else "").split(",") if k.strip()]
            for key in keys:
                if key not in self.cite_keys:
                    self.cite_keys.append(key)
            return "[{}]".format(", ".join(keys))
        if name in ("footnote", "footnotetext"):
            plain = self._to_plain_text(cmd.args[0] if cmd.args else "")
            return f"（脚注：{plain}）"
        if name == "url":
            url = cmd.args[0].strip() if cmd.args else ""
            return f"<{url}>" if url else ""
        if name == "href":
            url = cmd.args[0].strip() if cmd.args else ""
            label = self._to_markdown(cmd.args[1], file_path, source, pos) if len(cmd.args) > 1 else url
            return f"[{label}]({url})" if url else label
        if name in _FORMAT_COMMANDS:
            left, right = _FORMAT_COMMANDS[name]
            inner = self._to_markdown(cmd.args[0], file_path, source, pos) if cmd.args else ""
            return left + inner + right
        if name in ("multicolumn", "multirow"):
            if len(cmd.args) >= 2:
                return self._to_markdown(cmd.args[-1], file_path, source, pos)
            return ""
        if name in ("includegraphics", "caption", "centering", "hline", "toprule", "midrule", "bottomrule"):
            return ""
        if name in _IGNORE_COMMANDS:
            return ""
        if name in ("textwidth", "linewidth", "columnwidth"):
            return ""
        if name in ("LaTeX", "TeX", "XeLaTeX", "LuaLaTeX"):
            return name
        if name in ("%", "&", "_", "#", "{", "}", "$"):
            return name
        if name in ("\\", "newline", "linebreak"):
            return " "
        if name in (",", ";", ":", "!"):
            return " "
        plain = " ".join(
            self._to_plain_text(arg) for arg in cmd.args if arg is not None
        ).strip()
        warn_key = (name, file_path.name)
        if warn_key not in self._warned_unknown:
            self._warned_unknown.add(warn_key)
            self._warn(
                "unknown_command",
                f"未识别命令 \\{name}，已按文本渲染",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"command": name},
            )
        return plain

    def _to_plain_text(self, text: str) -> str:
        out: List[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                cmd = parse_command(text, i)
                if cmd is None:
                    out.append(ch)
                    i += 1
                    continue
                if cmd.name in _FORMAT_COMMANDS and cmd.args:
                    out.append(self._to_plain_text(cmd.args[0]))
                elif cmd.name in ("ref", "eqref", "autoref") and cmd.args or cmd.name in ("cite", "citep", "citet") and cmd.args:
                    out.append(f"[{cmd.args[0].strip()}]")
                elif cmd.name == "label":
                    pass
                elif cmd.name in ("LaTeX", "TeX") or cmd.name in ("%", "&", "_", "#", "{", "}", "$"):
                    out.append(cmd.name)
                elif cmd.name in ("\\", "newline", "linebreak", ",", ";", ":", "!"):
                    out.append(" ")
                elif cmd.name in _IGNORE_COMMANDS:
                    pass
                elif cmd.args:
                    out.append(" ".join(self._to_plain_text(arg) for arg in cmd.args))
                i = cmd.end
                continue
            if ch == "$":
                end = self._find_math_end(text, i + 1)
                if end < 0:
                    out.append(text[i:])
                    break
                out.append(text[i : end + 1])
                i = end + 1
                continue
            if ch == "~":
                out.append(" ")
            elif ch not in "{}":
                out.append(ch)
            i += 1
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def _find_math_end(self, text: str, start: int) -> int:
        i = start
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "$":
                return i
            i += 1
        return -1

    # ---------- helpers ----------

    def _anchor(self, file_path: Path, text: str, pos: int) -> LatexAnchor:
        line, column = line_col(text, pos)
        return LatexAnchor(self._rel(file_path), line, column)

    def _first_command_arg(self, text: str, name: str) -> Optional[str]:
        pos = 0
        while True:
            idx = text.find("\\", pos)
            if idx < 0:
                return None
            cmd = parse_command(text, idx)
            if cmd is None:
                pos = idx + 1
                continue
            if cmd.name == name:
                return cmd.args[0] if cmd.args else ""
            pos = cmd.end if cmd.end > idx else idx + 1

    def _strip_command(self, text: str, name: str) -> str:
        parts: List[str] = []
        pos = 0
        while True:
            idx = text.find("\\", pos)
            if idx < 0:
                parts.append(text[pos:])
                break
            cmd = parse_command(text, idx)
            if cmd is None:
                parts.append(text[pos : idx + 1])
                pos = idx + 1
                continue
            parts.append(text[pos:idx])
            if cmd.name != name:
                parts.append(text[idx:cmd.end])
            pos = cmd.end
        return "".join(parts)

    def _image_data_url(  # noqa: PLR0911
        self, raw: str, file_path: Path, source: str, pos: int
    ) -> Optional[str]:
        target = raw.strip().strip('"')
        if not target:
            return None
        if target.startswith(("http://", "https://", "data:")):
            self._warn(
                "external_image",
                "外部图片不内联，已跳过",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"target": target},
            )
            return None
        candidates = [file_path.parent / target, self.root / target]
        image = next((p for p in candidates if p.is_file()), None)
        if image is None:
            self._warn(
                "missing_image",
                f"图片文件不存在: {target}",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"target": target},
            )
            return None
        suffix = image.suffix.lower()
        if suffix not in _IMAGE_EXTS:
            self._warn(
                "unsupported_image_format",
                f"图片格式 {suffix} 暂不支持内联预览",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"target": target},
            )
            return None
        try:
            size = image.stat().st_size
        except OSError:
            size = 0
        if size > self.limits.max_image_bytes:
            self._warn(
                "image_too_large",
                "图片超过内联预览上限，已跳过",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"target": target},
            )
            return None
        try:
            payload = image.read_bytes()
        except OSError:
            self._warn(
                "image_read_error",
                "图片读取失败",
                file_path=file_path,
                text=source,
                pos=pos,
                detail={"target": target},
            )
            return None
        mime = mimetypes.guess_type(str(image))[0] or "application/octet-stream"
        return "data:{};base64,{}".format(
            mime,
            base64.b64encode(payload).decode("ascii"),
        )

    def _labels_set(
        self,
        key: str,
        kind: str,
        number: int,
        text: str,
        anchor: LatexAnchor,
    ) -> None:
        if not key:
            return
        self.labels[key] = {
            "kind": kind,
            "number": number,
            "text": text,
            "anchor": anchor,
        }

    def _resolve_references(self) -> None:
        for block in self.blocks:
            if block.text:
                block.text = self._resolve_text(block.text)
            if block.caption:
                block.caption = self._resolve_text(block.caption)
            for item in block.items:
                item.text = self._resolve_text(item.text)
            block.headers = [self._resolve_text(cell) for cell in block.headers]
            block.rows = [
                [self._resolve_text(cell) for cell in row] for row in block.rows
            ]
            for entry in block.entries:
                if "text" in entry:
                    entry["text"] = self._resolve_text(entry["text"])

    def _resolve_text(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            target = match.group(1).strip()
            info = self.labels.get(target)
            if info is None:
                self._warn(
                    "undefined_reference",
                    f"未找到标签 {target}",
                    detail={"target": target},
                )
                return f"[{target}]"
            kind = info.get("kind")
            number = info.get("number") or 0
            if kind == "figure":
                return "Figure %d" % number
            if kind == "table":
                return "Table %d" % number
            if kind == "equation":
                return "Equation %d" % number
            return str(info.get("text") or target)

        return re.sub(r"\{\{ref:([^}]+)\}\}", repl, text)

