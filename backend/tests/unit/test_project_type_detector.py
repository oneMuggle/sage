"""project_type_detector 单元测试 (项目类型分类系统, 2026-09-24)。

覆盖:
- detect_project_type: 根据目录内容推断项目类型
- detect_vcs_mode: 推断 VCS 模式
- DetectionResult/DetectionSignal: 数据结构

使用 conftest.py 的 autouse ``setup_test_db`` fixture。
"""

from __future__ import annotations

import pytest
from pathlib import Path

from backend.services.project_type_detector import (
    CODING_STRONG_SIGNALS,
    RESEARCH_SIGNALS,
    BUSINESS_SIGNALS,
    DetectionResult,
    DetectionSignal,
    detect_project_type,
    detect_vcs_mode,
)


class TestDetectionResult:
    """DetectionResult 数据结构。"""

    def test_to_dict(self):
        """to_dict 序列化。"""
        result = DetectionResult(
            project_type="coding",
            confidence=0.8,
            signals=[
                DetectionSignal(type=".git exists", weight=0.5),
                DetectionSignal(type="package.json exists", weight=0.4),
            ],
        )
        d = result.to_dict()
        assert d["project_type"] == "coding"
        assert d["confidence"] == 0.8
        assert len(d["signals"]) == 2
        assert d["signals"][0]["type"] == ".git exists"


class TestDetectProjectType:
    """detect_project_type: 根据目录内容推断项目类型。"""

    def test_coding_strong_signal_git(self, tmp_path):
        """.git 目录 → coding。"""
        (tmp_path / ".git").mkdir()
        result = detect_project_type(tmp_path)
        assert result.project_type == "coding"
        assert result.confidence >= 0.5

    def test_coding_strong_signal_package_json(self, tmp_path):
        """package.json → coding。"""
        (tmp_path / "package.json").write_text("{}")
        result = detect_project_type(tmp_path)
        assert result.project_type == "coding"
        assert result.confidence >= 0.4

    def test_coding_strong_signal_pyproject(self, tmp_path):
        """pyproject.toml → coding。"""
        (tmp_path / "pyproject.toml").write_text("")
        result = detect_project_type(tmp_path)
        assert result.project_type == "coding"
        assert result.confidence >= 0.4

    def test_coding_multiple_signals(self, tmp_path):
        """多个编码信号 → 高置信度。"""
        (tmp_path / ".git").mkdir()
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        result = detect_project_type(tmp_path)
        assert result.project_type == "coding"
        assert result.confidence >= 0.5  # 多个信号累加

    def test_research_latex(self, tmp_path):
        """LaTeX 文件 → research。"""
        (tmp_path / "paper.tex").write_text("\\documentclass{article}")
        (tmp_path / "refs.bib").write_text("@article{...}")
        result = detect_project_type(tmp_path)
        assert result.project_type == "research"
        assert result.confidence > 0.0

    def test_research_directories(self, tmp_path):
        """references/ 和 notebooks/ → research。"""
        (tmp_path / "references").mkdir()
        (tmp_path / "notebooks").mkdir()
        result = detect_project_type(tmp_path)
        assert result.project_type == "research"

    def test_business_office_docs(self, tmp_path):
        """多个 Office 文档 → business。"""
        (tmp_path / "report.docx").write_bytes(b"")
        (tmp_path / "data.xlsx").write_bytes(b"")
        (tmp_path / "slides.pptx").write_bytes(b"")
        (tmp_path / "manual.pdf").write_bytes(b"")
        result = detect_project_type(tmp_path)
        assert result.project_type == "business"
        assert result.confidence > 0.0

    def test_business_many_docs_bonus(self, tmp_path):
        """大量 Office 文档额外加分。"""
        for i in range(6):
            (tmp_path / f"doc{i}.docx").write_bytes(b"")
        result = detect_project_type(tmp_path)
        assert result.project_type == "business"
        # 6 个 docx × 0.15 = 0.9 + 0.2 bonus = 1.1 → capped at 0.95
        assert result.confidence >= 0.9

    def test_empty_dir_returns_none(self, tmp_path):
        """空目录 → None。"""
        result = detect_project_type(tmp_path)
        assert result.project_type is None
        assert result.confidence == 0.0

    def test_nonexistent_dir_returns_none(self, tmp_path):
        """不存在目录 → None。"""
        result = detect_project_type(tmp_path / "nonexistent")
        assert result.project_type is None
        assert result.confidence == 0.0

    def test_weak_signals_below_threshold(self, tmp_path):
        """弱信号低于阈值 → None。"""
        # 单个 pdf 权重 0.1 < 0.2 阈值
        (tmp_path / "doc.pdf").write_bytes(b"")
        result = detect_project_type(tmp_path)
        assert result.project_type is None
        assert result.confidence == 0.0

    def test_coding_beats_research(self, tmp_path):
        """编码信号强于科研信号 → coding。"""
        (tmp_path / ".git").mkdir()  # 0.5
        (tmp_path / "package.json").write_text("{}")  # 0.4
        (tmp_path / "paper.tex").write_text("\\document")  # 0.4
        result = detect_project_type(tmp_path)
        assert result.project_type == "coding"

    def test_signals_list_populated(self, tmp_path):
        """signals 列表包含检测到的信号。"""
        (tmp_path / ".git").mkdir()
        (tmp_path / "requirements.txt").write_text("fastapi")
        result = detect_project_type(tmp_path)
        assert len(result.signals) >= 2
        signal_types = [s.type for s in result.signals]
        assert any(".git" in t for t in signal_types)
        assert any("requirements.txt" in t for t in signal_types)


class TestDetectVcsMode:
    """detect_vcs_mode: 推断 VCS 模式。"""

    def test_coding_with_git(self, tmp_path):
        """coding 项目且有 .git → git。"""
        (tmp_path / ".git").mkdir()
        assert detect_vcs_mode(tmp_path, "coding") == "git"

    def test_coding_without_git(self, tmp_path):
        """coding 项目但无 .git → builtin。"""
        assert detect_vcs_mode(tmp_path, "coding") == "builtin"

    def test_research_always_builtin(self, tmp_path):
        """research 项目 → builtin。"""
        (tmp_path / ".git").mkdir()  # 即使有 .git
        assert detect_vcs_mode(tmp_path, "research") == "builtin"

    def test_business_always_builtin(self, tmp_path):
        """business 项目 → builtin。"""
        assert detect_vcs_mode(tmp_path, "business") == "builtin"

    def test_none_type_returns_builtin(self, tmp_path):
        """类型 None → builtin。"""
        assert detect_vcs_mode(tmp_path, None) == "builtin"


class TestSignalConstants:
    """信号常量检查。"""

    def test_coding_signals_not_empty(self):
        """CODING_STRONG_SIGNALS 非空。"""
        assert len(CODING_STRONG_SIGNALS) > 0

    def test_research_signals_not_empty(self):
        """RESEARCH_SIGNALS 非空。"""
        assert len(RESEARCH_SIGNALS) > 0

    def test_business_signals_not_empty(self):
        """BUSINESS_SIGNALS 非空。"""
        assert len(BUSINESS_SIGNALS) > 0

    def test_weights_positive(self):
        """所有权重为正数。"""
        for _, weight in CODING_STRONG_SIGNALS:
            assert weight > 0
        for _, weight in RESEARCH_SIGNALS:
            assert weight > 0
        for _, weight in BUSINESS_SIGNALS:
            assert weight > 0
