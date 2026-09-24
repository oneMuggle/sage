"""项目类型自动检测（项目类型分类系统，2026-09-24）。

扫描目录内容推断项目类型（coding/research/business/personal）。
检测规则基于文件特征信号，按权重累加得出最终类型。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DetectionSignal:
    """单个检测信号。"""

    type: str  # 信号描述
    weight: float  # 权重 (0.0-1.0)


@dataclass
class DetectionResult:
    """检测结果。"""

    project_type: Optional[str]  # "coding"|"research"|"business"|"personal"|None
    confidence: float = 0.0  # 0.0-1.0
    signals: List[DetectionSignal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "confidence": self.confidence,
            "signals": [{"type": s.type, "weight": s.weight} for s in self.signals],
        }


# 编码项目的强信号文件（存在即高置信度）
CODING_STRONG_SIGNALS = [
    (".git", 0.5),  # git 仓库
    ("package.json", 0.4),  # Node.js
    ("pyproject.toml", 0.4),  # Python modern
    ("setup.py", 0.35),  # Python legacy
    ("requirements.txt", 0.3),  # Python deps
    ("Cargo.toml", 0.4),  # Rust
    ("go.mod", 0.4),  # Go
    ("pom.xml", 0.4),  # Maven
    ("build.gradle", 0.4),  # Gradle
    ("Makefile", 0.3),  # C/C++ build
    ("CMakeLists.txt", 0.4),  # CMake
    ("Gemfile", 0.35),  # Ruby
    ("composer.json", 0.35),  # PHP
]

# 科研项目的信号
RESEARCH_SIGNALS = [
    ("*.tex", 0.4),  # LaTeX
    ("*.bib", 0.4),  # BibTeX
    ("references/", 0.3),  # 参考文献目录
    ("data/raw/", 0.25),  # 原始数据
    ("notebooks/", 0.2),  # Jupyter notebooks
    ("*.ipynb", 0.25),  # Jupyter
]

# 事务/商务项目的信号
BUSINESS_SIGNALS = [
    ("*.docx", 0.15),  # Word 文档
    ("*.xlsx", 0.15),  # Excel 表格
    ("*.pptx", 0.15),  # PPT 演示
    ("*.pdf", 0.1),  # PDF 文档
]


def _count_pattern(path: Path, pattern: str) -> int:
    """统计匹配 glob 模式的文件数量（最多 10）。"""
    try:
        return min(len(list(path.glob(pattern))), 10)
    except (OSError, PermissionError):
        return 0


def detect_project_type(path: Path) -> DetectionResult:
    """根据目录内容推断项目类型。

    扫描策略：
    1. 强信号优先：.git、典型配置文件存在即高置信度
    2. 累加弱信号：Office 文档数量、学术文件等
    3. 按总分选最高类型

    Args:
        path: 要检测的目录路径

    Returns:
        DetectionResult 包含推断类型、置信度和检测信号
    """
    if not path.is_dir():
        return DetectionResult(project_type=None, confidence=0.0, signals=[])

    signals: List[DetectionSignal] = []
    scores = {"coding": 0.0, "research": 0.0, "business": 0.0}

    # 检查编码项目的强信号
    for filename, weight in CODING_STRONG_SIGNALS:
        check_path = path / filename
        if check_path.exists():
            signals.append(DetectionSignal(type=f"{filename} exists", weight=weight))
            scores["coding"] += weight

    # 检查科研项目信号
    for pattern, weight in RESEARCH_SIGNALS:
        if pattern.endswith("/"):
            # 目录
            if (path / pattern.rstrip("/")).is_dir():
                signals.append(DetectionSignal(type=f"{pattern} dir exists", weight=weight))
                scores["research"] += weight
        else:
            # 文件 glob
            count = _count_pattern(path, pattern)
            if count > 0:
                # 多个文件增加置信度，但不超过权重
                adjusted = min(weight * (1 + count * 0.1), weight * 1.5)
                signals.append(DetectionSignal(type=f"{pattern} x{count}", weight=adjusted))
                scores["research"] += adjusted

    # 检查商务项目信号（Office 文档）
    office_count = 0
    for pattern, weight in BUSINESS_SIGNALS:
        count = _count_pattern(path, pattern)
        if count > 0:
            office_count += count
            signals.append(DetectionSignal(type=f"{pattern} x{count}", weight=weight * count))
            scores["business"] += weight * count

    # Office 文档数量较多时额外加分
    if office_count >= 5:
        signals.append(DetectionSignal(type="many office docs", weight=0.2))
        scores["business"] += 0.2

    # 选最高分的类型
    if not scores or max(scores.values()) < 0.2:
        # 无明显特征，返回 None
        return DetectionResult(
            project_type=None,
            confidence=0.0,
            signals=signals,
        )

    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    # 置信度 = 分数归一化到 0-1（上限 0.95）
    confidence = min(best_score / 1.0, 0.95)

    return DetectionResult(
        project_type=best_type,
        confidence=round(confidence, 2),
        signals=signals,
    )


def detect_vcs_mode(path: Path, project_type: Optional[str]) -> str:
    """推断 VCS 模式。

    - coding 项目且有 .git → "git"
    - 其他 → "builtin"

    Args:
        path: 项目目录
        project_type: 项目类型

    Returns:
        "git" | "builtin"
    """
    if project_type == "coding" and (path / ".git").exists():
        return "git"
    return "builtin"


__all__ = [
    "DetectionResult",
    "DetectionSignal",
    "detect_project_type",
    "detect_vcs_mode",
]
