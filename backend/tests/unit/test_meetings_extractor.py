"""会议纪要提取单元测试 (2026-09-25)

项目类型分类系统 - Phase 9.5.4
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.wiki.meetings_extractor import (
    MeetingEntry,
    extract_meeting_entry,
    generate_meetings_index,
    scan_meetings_directory,
)


class TestExtractMeetingEntry:
    """extract_meeting_entry 测试"""

    def test_extracts_yaml_front_matter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "2024-01-15-sprint.md"
        md_file.write_text(
            "---\n"
            "title: Sprint Review\n"
            "date: 2024-01-15\n"
            "attendees: [Alice, Bob, Charlie]\n"
            "---\n\n"
            "# Sprint Review\n\n"
            "## 决议\n"
            "- 发布 v1.0\n"
            "- 更新文档\n\n"
            "## Action Items\n"
            "- Alice 负责部署\n",
            encoding="utf-8",
        )

        entry = extract_meeting_entry(md_file)
        assert entry is not None
        assert entry.title == "Sprint Review"
        assert entry.date == "2024-01-15"
        assert len(entry.attendees) == 3
        assert "发布 v1.0" in entry.decisions
        assert "Alice 负责部署" in entry.action_items

    def test_extracts_date_from_filename(self, tmp_path: Path) -> None:
        md_file = tmp_path / "2024-03-20-weekly.md"
        md_file.write_text(
            "# Weekly Standup\n\n" "Participants discussed project status.",
            encoding="utf-8",
        )

        entry = extract_meeting_entry(md_file)
        assert entry is not None
        assert entry.date == "2024-03-20"
        assert entry.title == "Weekly Standup"

    def test_extracts_date_from_content(self, tmp_path: Path) -> None:
        md_file = tmp_path / "meeting.md"
        md_file.write_text(
            "# Team Meeting\n\n" "Date: 2024-02-28\n\n" "Discussed roadmap.",
            encoding="utf-8",
        )

        entry = extract_meeting_entry(md_file)
        assert entry is not None
        assert entry.date == "2024-02-28"

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")

        entry = extract_meeting_entry(md_file)
        assert entry is None

    def test_fallback_to_filename_title(self, tmp_path: Path) -> None:
        md_file = tmp_path / "project-kickoff.md"
        md_file.write_text("Some content without title.", encoding="utf-8")

        entry = extract_meeting_entry(md_file)
        assert entry is not None
        assert entry.title == "Project Kickoff"


class TestScanMeetingsDirectory:
    """scan_meetings_directory 测试"""

    def test_scans_markdown_files(self, tmp_path: Path) -> None:
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        (meetings_dir / "2024-01-10.md").write_text(
            "# Meeting A\ndate: 2024-01-10", encoding="utf-8"
        )
        (meetings_dir / "2024-02-15.md").write_text(
            "# Meeting B\ndate: 2024-02-15", encoding="utf-8"
        )

        entries = scan_meetings_directory(tmp_path)
        assert len(entries) == 2
        # 按日期降序
        assert entries[0].date == "2024-02-15"
        assert entries[1].date == "2024-01-10"

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        entries = scan_meetings_directory(tmp_path)
        assert entries == []

    def test_sorts_no_date_last(self, tmp_path: Path) -> None:
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        (meetings_dir / "no-date.md").write_text("# No Date Meeting", encoding="utf-8")
        (meetings_dir / "2024-01-01.md").write_text(
            "# Dated Meeting\n2024-01-01", encoding="utf-8"
        )

        entries = scan_meetings_directory(tmp_path)
        assert len(entries) == 2
        assert entries[0].date == "2024-01-01"
        assert entries[1].date is None


class TestGenerateMeetingsIndex:
    """generate_meetings_index 集成测试"""

    def test_generates_index_page(self, tmp_path: Path) -> None:
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        (meetings_dir / "2024-01-15.md").write_text(
            "---\ntitle: Jan Meeting\ndate: 2024-01-15\n---\n"
            "# Jan Meeting\n\n## 决议\n- Decision A",
            encoding="utf-8",
        )
        (meetings_dir / "2024-02-20.md").write_text(
            "---\ntitle: Feb Meeting\ndate: 2024-02-20\n---\n"
            "# Feb Meeting\n\n## 决议\n- Decision B",
            encoding="utf-8",
        )

        result = generate_meetings_index(tmp_path)
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "# 会议纪要索引" in content
        assert "共 2 次会议记录" in content
        assert "2024-02" in content
        assert "2024-01" in content
        assert "Jan Meeting" in content

    def test_returns_none_when_no_entries(self, tmp_path: Path) -> None:
        result = generate_meetings_index(tmp_path)
        assert result is None

    def test_groups_by_month(self, tmp_path: Path) -> None:
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        (meetings_dir / "2024-01-10.md").write_text(
            "---\ntitle: Early Jan\ndate: 2024-01-10\n---\n# Early Jan",
            encoding="utf-8",
        )
        (meetings_dir / "2024-01-25.md").write_text(
            "---\ntitle: Late Jan\ndate: 2024-01-25\n---\n# Late Jan",
            encoding="utf-8",
        )
        (meetings_dir / "2024-02-05.md").write_text(
            "---\ntitle: Early Feb\ndate: 2024-02-05\n---\n# Early Feb",
            encoding="utf-8",
        )

        result = generate_meetings_index(tmp_path)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "2024-02" in content
        assert "2024-01" in content
        # 2024-02 应在 2024-01 之前（降序）
        assert content.index("2024-02") < content.index("2024-01")
