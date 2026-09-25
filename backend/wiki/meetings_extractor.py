"""Business 项目会议纪要提取 (2026-09-25)

项目类型分类系统 - Phase 9.5.4
从 wiki/meetings/ 目录聚合会议纪要，生成会议索引。

功能：
- 扫描 meetings 目录下的 Markdown 文件
- 提取会议日期、参与者、决议事项
- 生成会议纪要索引页
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MeetingEntry:
    """会议纪要条目"""

    title: str
    date: Optional[str]  # YYYY-MM-DD format
    attendees: List[str]
    decisions: List[str]
    action_items: List[str]
    source_file: str
    summary: str = ""


def extract_meeting_entry(file_path: Path) -> Optional[MeetingEntry]:
    """从 Markdown 文件提取会议纪要信息。

    支持的格式：
    - YAML front matter: title, date, attendees
    - H1 标题 + 日期匹配
    - ## 决议 / ## Action Items 段落

    Args:
        file_path: Markdown 文件路径

    Returns:
        会议纪要条目，解析失败返回 None
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None

    if not content.strip():
        return None

    title = ""
    date: Optional[str] = None
    attendees: List[str] = []
    decisions: List[str] = []
    action_items: List[str] = []
    summary = ""

    # 解析 YAML front matter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            front_matter = parts[1].strip()
            content_body = parts[2].strip()

            for line in front_matter.split("\n"):
                line = line.strip()  # noqa: PLW2901
                if line.startswith("title:"):
                    title = line[6:].strip().strip('"\'')
                elif line.startswith("date:"):
                    date = line[5:].strip().strip('"\'')
                elif line.startswith("attendees:"):
                    att_str = line[10:].strip()
                    att_str = att_str.strip("[]\"'")
                    attendees = [a.strip().strip('"\'') for a in att_str.split(",")]

            content = content_body

    # 从第一行 H1 提取标题
    lines = content.split("\n")
    for line in lines:
        line = line.strip()  # noqa: PLW2901
        if line.startswith("# "):
            if not title:
                title = line[2:].strip()
            break

    # 从文件名或内容提取日期
    if not date:
        # 尝试从文件名提取 (e.g., 2024-01-15-meeting.md)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", file_path.stem)
        if date_match:
            date = date_match.group(1)
        else:
            # 从内容提取
            date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", content)
            if date_match:
                date = date_match.group(1)

    if not title:
        title = file_path.stem.replace("-", " ").replace("_", " ").title()

    # 提取决议和行动项
    current_section = None
    for line in lines:
        line_stripped = line.strip()

        # 检测段落标题
        if line_stripped.startswith("## "):
            section_name = line_stripped[3:].lower()
            if "决议" in section_name or "decision" in section_name:
                current_section = "decisions"
            elif "行动" in section_name or "action" in section_name:
                current_section = "action_items"
            else:
                current_section = None
            continue

        # 收集列表项
        if line_stripped.startswith("- ") or line_stripped.startswith("* "):
            item = line_stripped[2:].strip()
            if current_section == "decisions":
                decisions.append(item)
            elif current_section == "action_items":
                action_items.append(item)

    # 提取摘要（第一段非标题文本）
    for line in lines:
        line = line.strip()  # noqa: PLW2901
        if line and not line.startswith("#") and not line.startswith("---"):
            summary = line[:200]
            break

    return MeetingEntry(
        title=title,
        date=date,
        attendees=attendees,
        decisions=decisions,
        action_items=action_items,
        source_file=str(file_path),
        summary=summary,
    )


def scan_meetings_directory(project_root: Path) -> List[MeetingEntry]:
    """扫描会议纪要目录，提取所有条目。

    Args:
        project_root: 项目根目录

    Returns:
        会议纪要列表，按日期降序排列
    """
    meetings_dir = project_root / "wiki" / "meetings"
    if not meetings_dir.exists():
        return []

    entries: List[MeetingEntry] = []
    for md_file in meetings_dir.glob("*.md"):
        entry = extract_meeting_entry(md_file)
        if entry:
            entries.append(entry)

    # 按日期降序排列（无日期的排最后）
    entries.sort(key=lambda e: (e.date is not None, e.date or ""), reverse=True)
    return entries


def generate_meetings_index(
    project_root: Path,
    wiki_dir: Optional[Path] = None,
) -> Optional[Path]:
    """生成会议纪要索引页。

    Args:
        project_root: 项目根目录
        wiki_dir: Wiki meetings 目录（默认 project_root/wiki/meetings）

    Returns:
        生成的索引页路径，无会议记录返回 None
    """
    if wiki_dir is None:
        wiki_dir = project_root / "wiki" / "meetings"

    wiki_dir.mkdir(parents=True, exist_ok=True)

    entries = scan_meetings_directory(project_root)
    if not entries:
        return None

    lines: List[str] = []
    lines.append("# 会议纪要索引\n")
    lines.append(f"共 {len(entries)} 次会议记录。\n")

    # 按月份分组
    by_month: Dict[str, List[MeetingEntry]] = {}
    no_date: List[MeetingEntry] = []
    for entry in entries:
        if entry.date and len(entry.date) >= 7:
            month_key = entry.date[:7]  # YYYY-MM
            by_month.setdefault(month_key, []).append(entry)
        else:
            no_date.append(entry)

    # 输出有日期的
    for month in sorted(by_month.keys(), reverse=True):
        lines.append(f"\n## {month}\n")
        for entry in by_month[month]:
            date_str = entry.date or "未知日期"
            lines.append(f"### [{date_str}] {entry.title}\n")
            if entry.attendees:
                lines.append(f"**参与者**: {', '.join(entry.attendees)}\n")
            if entry.decisions:
                lines.append("\n**决议**:\n")
                for d in entry.decisions:
                    lines.append(f"- {d}\n")
            if entry.action_items:
                lines.append("\n**行动项**:\n")
                for a in entry.action_items:
                    lines.append(f"- {a}\n")
            rel_path = Path(entry.source_file).relative_to(wiki_dir)
            lines.append(f"\n[查看原文]({rel_path})\n")

    # 输出无日期的
    if no_date:
        lines.append("\n## 待归档\n")
        for entry in no_date:
            lines.append(f"### {entry.title}\n")
            if entry.attendees:
                lines.append(f"**参与者**: {', '.join(entry.attendees)}\n")
            rel_path = Path(entry.source_file).relative_to(wiki_dir)
            lines.append(f"[查看原文]({rel_path})\n")

    index_file = wiki_dir / "_index.md"
    index_file.write_text("\n".join(lines), encoding="utf-8")
    return index_file
