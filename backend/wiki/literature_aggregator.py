"""Research 项目文献综述聚合 (2026-09-25)

项目类型分类系统 - Phase 9.5.3
从 wiki/literature/ 目录聚合文献条目，生成文献综述摘要。

功能：
- 扫描 literature 目录下的 Markdown 文件
- 提取标题、作者、年份、引用信息
- 生成文献综述索引页
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class LiteratureEntry:
    """文献条目"""

    title: str
    authors: List[str]
    year: Optional[int]
    source_file: str
    summary: str = ""
    tags: List[str] = field(default_factory=list)


def extract_literature_entry(file_path: Path) -> Optional[LiteratureEntry]:
    """从 Markdown 文件提取文献条目信息。

    支持的元数据格式：
    - YAML front matter: title, authors, year, tags
    - 第一行 H1: 标题
    - 匹配常见引用格式

    Args:
        file_path: Markdown 文件路径

    Returns:
        文献条目，解析失败返回 None
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None

    if not content.strip():
        return None

    title = ""
    authors: List[str] = []
    year: Optional[int] = None
    tags: List[str] = []
    summary = ""

    # 解析 YAML front matter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            front_matter = parts[1].strip()
            content_body = parts[2].strip()

            # 简单 YAML 解析（不引入 PyYAML 依赖）
            for line in front_matter.split("\n"):
                line = line.strip()  # noqa: PLW2901
                if line.startswith("title:"):
                    title = line[6:].strip().strip('"\'')
                elif line.startswith("year:"):
                    with contextlib.suppress(ValueError):
                        year = int(line[5:].strip())
                elif line.startswith("authors:"):
                    authors_str = line[8:].strip()
                    # 支持 [a, b] 或 "a, b" 格式
                    authors_str = authors_str.strip("[]\"'")
                    authors = [a.strip().strip('"\'') for a in authors_str.split(",")]
                elif line.startswith("tags:"):
                    tags_str = line[5:].strip()
                    tags_str = tags_str.strip("[]\"'")
                    tags = [t.strip().strip('"\'') for t in tags_str.split(",")]

            content = content_body

    # 从第一行 H1 提取标题（如果 front matter 没有）
    if not title:
        lines = content.split("\n")
        for line in lines:
            line = line.strip()  # noqa: PLW2901
            if line.startswith("# "):
                title = line[2:].strip()
                break

    # 提取摘要（第一段非标题文本）
    lines = content.split("\n")
    for line in lines:
        line = line.strip()  # noqa: PLW2901
        if line and not line.startswith("#") and not line.startswith("---"):
            summary = line[:200]  # 截取前 200 字符
            break

    # 从文件名回退
    if not title:
        title = file_path.stem.replace("-", " ").replace("_", " ").title()

    # 尝试从内容提取年份
    if year is None:
        year_match = re.search(r"\b(19|20)\d{2}\b", content)
        if year_match:
            year = int(year_match.group())

    return LiteratureEntry(
        title=title,
        authors=authors,
        year=year,
        source_file=str(file_path),
        summary=summary,
        tags=tags,
    )


def scan_literature_directory(project_root: Path) -> List[LiteratureEntry]:
    """扫描文献目录，提取所有条目。

    Args:
        project_root: 项目根目录

    Returns:
        文献条目列表
    """
    literature_dir = project_root / "wiki" / "literature"
    if not literature_dir.exists():
        return []

    entries: List[LiteratureEntry] = []
    for md_file in literature_dir.glob("*.md"):
        entry = extract_literature_entry(md_file)
        if entry:
            entries.append(entry)

    # 按年份降序排列（无年份的排最后）
    entries.sort(key=lambda e: (e.year is None, -(e.year or 0)))
    return entries


def generate_literature_review(
    project_root: Path,
    wiki_dir: Optional[Path] = None,
) -> Optional[Path]:
    """生成文献综述索引页。

    Args:
        project_root: 项目根目录
        wiki_dir: Wiki literature 目录（默认 project_root/wiki/literature）

    Returns:
        生成的索引页路径，无文献条目返回 None
    """
    if wiki_dir is None:
        wiki_dir = project_root / "wiki" / "literature"

    wiki_dir.mkdir(parents=True, exist_ok=True)

    entries = scan_literature_directory(project_root)
    if not entries:
        return None

    lines: List[str] = []
    lines.append("# 文献综述索引\n")
    lines.append(f"共 {len(entries)} 篇文献。\n")

    # 按年份分组
    by_year: Dict[int, List[LiteratureEntry]] = {}
    no_year: List[LiteratureEntry] = []
    for entry in entries:
        if entry.year:
            by_year.setdefault(entry.year, []).append(entry)
        else:
            no_year.append(entry)

    # 输出有年份的
    for year in sorted(by_year.keys(), reverse=True):
        lines.append(f"\n## {year} 年\n")
        for entry in by_year[year]:
            authors_str = ", ".join(entry.authors) if entry.authors else "未知作者"
            lines.append(f"### {entry.title}\n")
            lines.append(f"**作者**: {authors_str}\n")
            if entry.tags:
                lines.append(f"**标签**: {', '.join(entry.tags)}\n")
            if entry.summary:
                lines.append(f"\n{entry.summary}\n")
            rel_path = Path(entry.source_file).relative_to(wiki_dir)
            lines.append(f"[查看原文]({rel_path})\n")

    # 输出无年份的
    if no_year:
        lines.append("\n## 待分类\n")
        for entry in no_year:
            authors_str = ", ".join(entry.authors) if entry.authors else "未知作者"
            lines.append(f"### {entry.title}\n")
            lines.append(f"**作者**: {authors_str}\n")
            if entry.tags:
                lines.append(f"**标签**: {', '.join(entry.tags)}\n")
            if entry.summary:
                lines.append(f"\n{entry.summary}\n")
            rel_path = Path(entry.source_file).relative_to(wiki_dir)
            lines.append(f"[查看原文]({rel_path})\n")

    index_file = wiki_dir / "_index.md"
    index_file.write_text("\n".join(lines), encoding="utf-8")
    return index_file
