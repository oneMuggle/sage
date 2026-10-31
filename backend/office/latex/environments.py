"""Environment handlers for the LaTeX parser (figure/table/list/bibliography)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from .models import LatexAnchor, LatexBlock, LatexListItem
from .scanner import (
    Command,
    find_environment,
    parse_command,
    split_cells,
    split_rows,
    strip_row_noise,
)
from .utils import split_keywords


class _EnvironmentMixin:
    def _handle_environment(
        self,
        name: str,
        content: str,
        file_path: Path,
        text: str,
        cmd: Command,
        depth: int,
    ) -> None:
        anchor = self._anchor(file_path, text, cmd.start)
        base = name.rstrip("*")
        if base == "figure":
            self._handle_figure(content, file_path, text, anchor)
        elif base in ("table", "longtable") or base in ("tabular", "tabularx", "tabular*"):
            self._handle_table(content, file_path, text, anchor)
        elif base in (
            "equation",
            "align",
            "gather",
            "multline",
            "eqnarray",
            "displaymath",
            "math",
        ):
            self._append_equation(content, file_path, text, cmd.start, anchor=anchor)
        elif base in ("itemize", "enumerate", "description"):
            self._handle_list(base, content, file_path, text, anchor)
        elif base == "thebibliography":
            self._handle_thebibliography(content, file_path, text, anchor)
        elif base in ("verbatim", "lstlisting", "minted"):
            self._append_block(LatexBlock("code", text=content, anchor=anchor))
        elif base in ("quote", "quotation"):
            md = self._to_markdown(content, file_path, text, cmd.start)
            self._append_block(LatexBlock("quote", text=md.strip(), anchor=anchor))
        elif base == "abstract":
            self.metadata.abstract = self._to_plain_text(content).strip()
        elif base in ("keywords", "keyword"):
            self.metadata.keywords = split_keywords(self._to_plain_text(content))
        elif base in ("center", "flushleft", "flushright", "minipage", "document"):
            self._parse_blocks(content, file_path, depth)
        elif base in ("theorem", "lemma", "corollary", "definition", "proof", "remark"):
            label = self._first_command_arg(content, "label")
            body = self._to_markdown(
                self._strip_command(content, "label"), file_path, text, cmd.start
            )
            prefix = f"**{base.capitalize()}.** "
            self._append_block(
                LatexBlock("paragraph", text=(prefix + body).strip(), anchor=anchor)
            )
            if label:
                self._labels_set(label, "paragraph", 0, body.strip(), anchor)
        else:
            self._warn(
                "unknown_environment",
                f"未识别环境 {name}，已按文本渲染",
                file_path=file_path,
                text=text,
                pos=cmd.start,
                detail={"environment": name},
            )
            md = self._to_markdown(content, file_path, text, cmd.start)
            if md.strip():
                self._append_block(
                    LatexBlock("paragraph", text=md.strip(), anchor=anchor)
                )

    def _handle_figure(self, content: str, file_path: Path, text: str, anchor: LatexAnchor) -> None:
        caption = self._first_command_arg(content, "caption")
        label = self._first_command_arg(content, "label")
        graphics = self._first_command_arg(content, "includegraphics")
        src = None
        if graphics:
            src = self._image_data_url(graphics, file_path, text, 0)
        caption_md = (
            self._to_markdown(caption, file_path, text, 0) if caption else None
        )
        self.figure_no += 1
        block = LatexBlock(
            "figure",
            src=src,
            caption=caption_md,
            label=label,
            anchor=anchor,
        )
        self._append_block(block)
        if label:
            self._labels_set(label, "figure", self.figure_no, caption_md or "", anchor)

    def _handle_table(self, content: str, file_path: Path, text: str, anchor: LatexAnchor) -> None:
        caption = self._first_command_arg(content, "caption")
        label = self._first_command_arg(content, "label")
        table_body = self._find_tabular_body(content)
        if table_body is None:
            table_body = content
        rows = self._parse_tabular_rows(table_body, file_path, text)
        if not rows:
            self._warn(
                "empty_table",
                "未解析到表格行",
                file_path=file_path,
                text=text,
                pos=0,
            )
        headers: List[str] = []
        body_rows: List[List[str]] = []
        if len(rows) > 1:
            headers = rows[0]
            body_rows = rows[1:]
        elif rows:
            body_rows = rows
        caption_md = (
            self._to_markdown(caption, file_path, text, 0) if caption else None
        )
        self.table_no += 1
        block = LatexBlock(
            "table",
            headers=headers,
            rows=body_rows,
            caption=caption_md,
            label=label,
            anchor=anchor,
        )
        self._append_block(block)
        if label:
            self._labels_set(label, "table", self.table_no, caption_md or "", anchor)

    def _find_tabular_body(self, content: str) -> Optional[str]:
        for name in ("tabularx", "tabular*", "tabular", "longtable"):
            pattern = re.compile(
                r"\\begin\s*\{\s*" + re.escape(name) + r"\s*\}", re.S
            )
            match = pattern.search(content)
            if match is None:
                continue
            begin_cmd = parse_command(content, match.start())
            search_from = begin_cmd.end if begin_cmd is not None else match.end()
            found = find_environment(content, search_from, name)
            if found is not None:
                return content[found[0] : found[1]]
        return None

    def _parse_tabular_rows(
        self, body: str, file_path: Path, text: str
    ) -> List[List[str]]:
        rows: List[List[str]] = []
        for raw_row in split_rows(body):
            row = strip_row_noise(raw_row)
            if not row:
                continue
            cells = split_cells(row)
            if not cells:
                continue
            rows.append(
                [
                    self._to_markdown(cell, file_path, text, 0).strip()
                    for cell in cells
                ]
            )
        return rows

    def _handle_list(
        self,
        name: str,
        content: str,
        file_path: Path,
        text: str,
        anchor: LatexAnchor,
    ) -> None:
        items: List[LatexListItem] = []
        parts = re.split(r"\\item\b", content)
        for raw_part in parts[1:]:
            part = raw_part.strip()
            if not part:
                continue
            term = None
            if name == "description" and part.startswith("["):
                close = part.find("]")
                if close > 0:
                    term = self._to_plain_text(part[1:close]).strip()
                    part = part[close + 1 :]
            md = self._to_markdown(part, file_path, text, 0).strip()
            if term:
                md = f"**{term}**: {md}"
            items.append(LatexListItem(md))
        self._append_block(
            LatexBlock(
                "list",
                ordered=(name == "enumerate"),
                items=items,
                anchor=anchor,
            )
        )

    def _handle_thebibliography(
        self, content: str, file_path: Path, text: str, anchor: LatexAnchor
    ) -> None:
        entries: List[Dict[str, str]] = []
        matches = list(re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", content))
        for idx, match in enumerate(matches):
            key = match.group(1).strip()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            body = content[match.end() : end].strip()
            body = self._to_markdown(body, file_path, text, 0).strip()
            entries.append({"key": key, "text": body})
        self._append_block(LatexBlock("bibliography", entries=entries, anchor=anchor))

    def _add_bibliography_file(
        self, value: str, file_path: Path, cmd: Command, text: str
    ) -> None:
        names = [part.strip() for part in value.split(",") if part.strip()]
        for raw_name in names:
            name = raw_name
            if not name.endswith(".bib"):
                name += ".bib"
            candidates = [file_path.parent / name, self.root / name]
            bib_path = next((p for p in candidates if p.is_file()), None)
            if bib_path is None:
                self._warn(
                    "missing_bibliography",
                    f"未找到参考文献文件 {name}",
                    file_path=file_path,
                    text=text,
                    pos=cmd.start,
                    detail={"target": name},
                )
                continue
            try:
                from backend.office.bibtex import parse_bibtex_file

                specs = parse_bibtex_file(str(bib_path))
            except Exception as exc:  # noqa: BLE001 — preview must degrade
                self._warn(
                    "bibliography_parse_error",
                    f"参考文献文件解析失败: {exc}",
                    file_path=file_path,
                    text=text,
                    pos=cmd.start,
                    detail={"target": name},
                )
                continue
            entries = []
            for spec in specs:
                authors = ", ".join(spec.authors or [])
                parts = [authors, spec.title or "", spec.source or "", spec.year or ""]
                entries.append(
                    {
                        "key": spec.key,
                        "text": ". ".join(part for part in parts if part),
                    }
                )
            if entries:
                self._append_block(
                    LatexBlock(
                        "bibliography",
                        entries=entries,
                        anchor=self._anchor(file_path, text, cmd.start),
                    )
                )

    def _append_equation(
        self,
        latex: str,
        file_path: Path,
        text: str,
        pos: int,
        *,
        anchor: Optional[LatexAnchor] = None,
    ) -> None:
        label = self._first_command_arg(latex, "label")
        clean = self._strip_command(latex, "label").strip()
        self.equation_no += 1
        actual_anchor = anchor or self._anchor(file_path, text, pos)
        self._append_block(
            LatexBlock(
                "equation",
                latex=clean,
                display=True,
                label=label,
                anchor=actual_anchor,
            )
        )
        if label:
            self._labels_set(label, "equation", self.equation_no, "", actual_anchor)

    # ---------- includes ----------

