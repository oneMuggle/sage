"""代码库画像采集器（确定性扫描，不调 LLM，2026-10-27）。

为 `project_analysis_agent` 提供结构化画像：技术栈、构建命令、测试框架、
lint 配置、CI 流水线、已有规则文件、目录结构、源码采样与 Git 统计。

与 `project_type_detector` 的分工：
- detector 负责**判定类型**（信号打分 → L1/L2）
- profiler 负责**采集全貌**（供 LLM 生成治理方案与专属规则）

安全约束（不可放宽）：
- 源码采样排除敏感路径（``.env*`` / ``secrets/`` / ``*.pem`` / ``*.key`` /
  ``id_rsa*`` / ``credentials*`` / ``.git/``）
- 采样总量上限 8 文件 × 120 行，防止 prompt 爆炸
- 所有候选路径 ``resolve()`` 后必须仍位于 root 之内，防路径穿越
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from backend.services.git_integration import _run_git
from backend.services.project_type_detector import (
    detect_project_type,
    detect_tech_stack,
    detect_vcs_mode,
)

logger = logging.getLogger(__name__)

#: 采样文件数上限
MAX_SAMPLE_FILES = 8
#: 单文件采样行数上限
MAX_SAMPLE_LINES = 120
#: 顶层目录条目数上限
MAX_DIRECTORY_ENTRIES = 20
#: 目录遍历条目预算（防大仓库卡死）
MAX_SCAN_ENTRIES = 4000
#: 单文件读取字节上限
MAX_FILE_BYTES = 128 * 1024

#: 采样时始终跳过的目录
SKIP_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".claude",
    ".sage",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".gradle",
    "coverage",
    "htmlcov",
    ".worktrees",
    "site-packages",
    "vendor",
}

#: 敏感文件名/目录名模式（命中即排除，不进入采样）
_SENSITIVE_NAME_PATTERNS = (
    re.compile(r"^\.env", re.IGNORECASE),
    re.compile(r"^secrets?$", re.IGNORECASE),
    re.compile(r"^\.?credentials?", re.IGNORECASE),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)", re.IGNORECASE),
    re.compile(r"^\.?(netrc|npmrc|pypirc)$", re.IGNORECASE),
    re.compile(r"^secrets?\.", re.IGNORECASE),
)

#: 敏感文件后缀
_SENSITIVE_SUFFIXES = frozenset(
    {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer", ".ppk"}
)

#: 可作为源码采样的扩展名 → 语言
SOURCE_LANGUAGES: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".vue": "vue",
    ".svelte": "svelte",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".tex": "latex",
    ".ipynb": "notebook",
    ".sh": "shell",
}

#: 源码采样优先目录（命中则优先于其他目录）
PRIORITY_SOURCE_DIRS = (
    "src",
    "backend",
    "server",
    "app",
    "lib",
    "core",
    "electron",
    "src-tauri",
    "packages",
    "cmd",
    "internal",
)

#: 被视为「框架」的技术栈标记
FRAMEWORK_MARKERS = frozenset(
    {
        "react",
        "react-native",
        "vue",
        "svelte",
        "next",
        "nuxt",
        "angular",
        "electron",
        "tauri",
        "fastapi",
        "django",
        "flask",
        "uvicorn",
        "spring-boot",
        "express",
        "nest",
        "tailwind",
        "vite",
        "webpack",
        "pandas",
        "numpy",
        "torch",
        "tensorflow",
        "scikit-learn",
        "sqlalchemy",
        "pydantic",
        "axum",
        "actix",
        "gin-gonic",
        "grpc",
        "flutter",
        "expo",
    }
)

#: 已有规则文件候选（相对路径或 glob）
RULE_FILE_CANDIDATES = (
    "SAGE.md",
    "CLAUDE.md",
    "AGENTS.md",
    "CONVENTIONS.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".editorconfig",
    ".github/copilot-instructions.md",
    ".cursor/rules/*.mdc",
    ".github/instructions/*.instructions.md",
)

#: lint / 类型检查配置文件候选
LINT_CONFIG_CANDIDATES = (
    "ruff.toml",
    ".ruff.toml",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.json",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.ts",
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.js",
    "biome.json",
    "mypy.ini",
    ".mypy.ini",
    ".flake8",
    "setup.cfg",
    "tsconfig.json",
    "pyrightconfig.json",
)

#: CI 流水线候选
CI_CANDIDATES = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    ".travis.yml",
    "Jenkinsfile",
)


@dataclass(frozen=True)
class SourceSample:
    """单个源码采样。"""

    path: str
    language: str
    lines: int
    content: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.language,
            "lines": self.lines,
            "content": self.content,
        }


@dataclass
class GitStats:
    """Git 仓库统计。"""

    is_repo: bool = False
    current_branch: Optional[str] = None
    commit_count: int = 0
    recent_commit_count: int = 0
    branch_count: int = 0
    last_commit_at: Optional[str] = None
    dirty_files: int = 0

    def to_dict(self) -> dict:
        return {
            "is_repo": self.is_repo,
            "current_branch": self.current_branch,
            "commit_count": self.commit_count,
            "recent_commit_count": self.recent_commit_count,
            "branch_count": self.branch_count,
            "last_commit_at": self.last_commit_at,
            "dirty_files": self.dirty_files,
        }


@dataclass
class CodebaseProfile:
    """代码库画像。"""

    root: str
    level1_type: Optional[str] = None
    sub_type: Optional[str] = None
    tech_stack: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    build_commands: List[str] = field(default_factory=list)
    test_frameworks: List[str] = field(default_factory=list)
    lint_configs: List[str] = field(default_factory=list)
    ci_workflows: List[str] = field(default_factory=list)
    existing_rule_files: List[str] = field(default_factory=list)
    directory_layout: List[str] = field(default_factory=list)
    source_samples: List[SourceSample] = field(default_factory=list)
    git_stats: GitStats = field(default_factory=GitStats)
    vcs_mode: str = "builtin"

    def to_dict(self, include_source_content: bool = True) -> dict:
        """转为可序列化字典。

        Args:
            include_source_content: 是否包含采样源码正文。API 直接回传时置 False，
                避免响应体过大。
        """
        return {
            "root": self.root,
            "level1_type": self.level1_type,
            "sub_type": self.sub_type,
            "tech_stack": list(self.tech_stack),
            "frameworks": list(self.frameworks),
            "build_commands": list(self.build_commands),
            "test_frameworks": list(self.test_frameworks),
            "lint_configs": list(self.lint_configs),
            "ci_workflows": list(self.ci_workflows),
            "existing_rule_files": list(self.existing_rule_files),
            "directory_layout": list(self.directory_layout),
            "source_samples": [
                sample.to_dict()
                if include_source_content
                else {
                    "path": sample.path,
                    "language": sample.language,
                    "lines": sample.lines,
                }
                for sample in self.source_samples
            ],
            "git_stats": self.git_stats.to_dict(),
            "vcs_mode": self.vcs_mode,
        }


# ── 敏感路径判定 ────────────────────────────────────────────────────────────


def is_sensitive_path(relative_path: str) -> bool:
    """判断相对路径是否属于敏感路径（不可采样）。

    Args:
        relative_path: 相对项目根的路径（POSIX 分隔符）

    Returns:
        True 表示敏感，必须排除
    """
    parts = relative_path.replace("\\", "/").split("/")
    for part in parts:
        if not part:
            continue
        if any(pattern.search(part) for pattern in _SENSITIVE_NAME_PATTERNS):
            return True
        suffix = Path(part).suffix.lower()
        if suffix in _SENSITIVE_SUFFIXES:
            return True
    return False


def _is_inside(root: Path, candidate: Path) -> bool:
    """校验候选路径位于 root 之内（防路径穿越）。"""
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return False
    return True


# ── 各维度采集 ──────────────────────────────────────────────────────────────


def _collect_directory_layout(root: Path) -> List[str]:
    """采集顶层目录结构（排除隐藏目录与跳过目录）。"""
    entries: List[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if len(entries) >= MAX_DIRECTORY_ENTRIES:
                break
            if entry.name.startswith("."):
                continue
            if entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                entries.append(f"{entry.name}/")
            elif entry.is_file():
                entries.append(entry.name)
    except (OSError, PermissionError):
        return entries
    return entries


def _collect_rule_files(root: Path) -> List[str]:
    """采集项目内已有的 AI 规则文件。"""
    found: List[str] = []
    for candidate in RULE_FILE_CANDIDATES:
        if "*" in candidate:
            for match in sorted(root.glob(candidate)):
                if _is_inside(root, match) and not is_sensitive_path(match.name):
                    found.append(match.relative_to(root).as_posix())
        else:
            target = root / candidate
            if target.is_file() and _is_inside(root, target):
                found.append(candidate)
    return found


def _collect_lint_configs(root: Path) -> List[str]:
    """采集 lint / 类型检查配置文件。"""
    found: List[str] = []
    for candidate in LINT_CONFIG_CANDIDATES:
        target = root / candidate
        if target.is_file() and _is_inside(root, target):
            found.append(candidate)
    return found


def _collect_ci_workflows(root: Path) -> List[str]:
    """采集 CI 流水线定义文件。"""
    found: List[str] = []
    for candidate in CI_CANDIDATES:
        if "*" in candidate:
            for match in sorted(root.glob(candidate)):
                if _is_inside(root, match):
                    found.append(match.relative_to(root).as_posix())
        else:
            target = root / candidate
            if target.is_file() and _is_inside(root, target):
                found.append(candidate)
    return found


def _parse_package_scripts(root: Path) -> List[str]:
    """从 package.json 的 scripts 提取构建/测试命令。"""
    target = root / "package.json"
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return []
    preferred = ("build", "dev", "test", "lint", "typecheck", "check", "start")
    names = [name for name in preferred if name in scripts]
    names.extend(sorted(name for name in scripts if name not in preferred))
    return [f"npm run {name}" for name in names[:8]]


def _parse_makefile_targets(root: Path) -> List[str]:
    """从 Makefile 提取目标名。"""
    target = root / "Makefile"
    if not target.is_file():
        return []
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: List[str] = []
    for line in raw.splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)", line)
        if not match:
            continue
        name = match.group(1)
        if name not in names:
            names.append(name)
    return [f"make {name}" for name in names[:8]]


def _parse_poetry_scripts(root: Path) -> List[str]:
    """从 pyproject.toml 的 [tool.poetry.scripts] 提取入口命令。"""
    target = root / "pyproject.toml"
    if not target.is_file():
        return []
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: List[str] = []
    in_section = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped.replace(" ", "") == "[tool.poetry.scripts]"
            continue
        if not in_section or "=" not in stripped or stripped.startswith("#"):
            continue
        name = stripped.split("=", 1)[0].strip().strip('"').strip("'")
        if name and name not in names:
            names.append(name)
    return [f"poetry run {name}" for name in names[:6]]


def _collect_build_commands(root: Path) -> List[str]:
    """汇总构建/测试命令。"""
    commands: List[str] = []
    for group in (
        _parse_package_scripts(root),
        _parse_makefile_targets(root),
        _parse_poetry_scripts(root),
    ):
        for command in group:
            if command not in commands:
                commands.append(command)
    return commands


def _collect_test_frameworks(root: Path, tech_stack: List[str]) -> List[str]:
    """检测测试框架。"""
    stack = {item.lower() for item in tech_stack}
    found: List[str] = []

    def _add(name: str) -> None:
        if name not in found:
            found.append(name)

    if "pytest" in stack or (root / "pytest.ini").is_file() or (root / "tox.ini").is_file():
        _add("pytest")
    if "vitest" in stack or any(root.glob("vitest.config.*")):
        _add("vitest")
    if "jest" in stack or any(root.glob("jest.config.*")):
        _add("jest")
    if "playwright" in stack or any(root.glob("playwright.config.*")):
        _add("playwright")
    if "cypress" in stack or (root / "cypress.config.ts").is_file():
        _add("cypress")
    if "unittest" in stack:
        _add("unittest")
    if (root / "tests").is_dir() and not found:
        _add("directory-convention")
    return found


def _iter_source_candidates(root: Path) -> List[Path]:
    """遍历项目，收集可采样的源码文件（已排除敏感路径与跳过目录）。"""
    candidates: List[Path] = []
    budget = MAX_SCAN_ENTRIES
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _exc: None):
        if budget <= 0:
            break
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIRS
            and not name.startswith(".")
            and not is_sensitive_path(name)
        ]
        for filename in filenames:
            budget -= 1
            if budget <= 0:
                break
            suffix = Path(filename).suffix.lower()
            if suffix not in SOURCE_LANGUAGES:
                continue
            if is_sensitive_path(filename):
                continue
            candidate = Path(dirpath) / filename
            if not candidate.is_file():
                continue
            if not _is_inside(root, candidate):
                continue
            candidates.append(candidate)
    return candidates


def _rank_source_candidates(root: Path, candidates: List[Path]) -> List[Path]:
    """按「优先目录 → 层级浅 → 路径短」排序采样候选。"""

    def _key(path: Path) -> tuple:
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        parts = relative.parts[:-1]
        priority_rank = len(parts)
        for index, part in enumerate(parts):
            if part.lower() in PRIORITY_SOURCE_DIRS:
                priority_rank = index
                break
        return (priority_rank, len(parts), len(relative.parts), str(relative))

    return sorted(candidates, key=_key)


def _read_sample(path: Path) -> Optional[SourceSample]:
    """读取单个采样文件（截断到上限行数）。"""
    suffix = path.suffix.lower()
    language = SOURCE_LANGUAGES.get(suffix, "text")
    try:
        raw = path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    except (OSError, PermissionError):
        return None
    lines = raw.splitlines()
    truncated = lines[:MAX_SAMPLE_LINES]
    return SourceSample(
        path=str(path),
        language=language,
        lines=len(truncated),
        content="\n".join(truncated),
    )


def _collect_source_samples(root: Path) -> List[SourceSample]:
    """采集核心源码样本（≤8 文件 × 120 行）。"""
    candidates = _iter_source_candidates(root)
    ranked = _rank_source_candidates(root, candidates)
    samples: List[SourceSample] = []
    dir_counts: Dict[Path, int] = {}
    for candidate in ranked:
        if len(samples) >= MAX_SAMPLE_FILES:
            break
        try:
            parent = candidate.parent.resolve()
        except (OSError, RuntimeError):
            continue
        # 同一目录最多采 2 个文件，保证覆盖面
        if dir_counts.get(parent, 0) >= 2:
            continue
        sample = _read_sample(candidate)
        if sample is None:
            continue
        dir_counts[parent] = dir_counts.get(parent, 0) + 1
        samples.append(sample)
    return samples


def _collect_git_stats(root: Path) -> GitStats:
    """采集 Git 统计（失败时返回空统计）。"""
    stats = GitStats()
    if not (root / ".git").exists():
        return stats

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], str(root))
    if branch is None:
        return stats
    stats.is_repo = True
    stats.current_branch = branch.strip()

    count = _run_git(["rev-list", "--count", "HEAD"], str(root))
    if count:
        try:
            stats.commit_count = int(count.strip())
        except ValueError:
            stats.commit_count = 0

    recent = _run_git(["rev-list", "--count", "--since=30.days", "HEAD"], str(root))
    if recent:
        try:
            stats.recent_commit_count = int(recent.strip())
        except ValueError:
            stats.recent_commit_count = 0

    branches = _run_git(["branch", "--list", "--format=%(refname:short)"], str(root))
    if branches:
        stats.branch_count = len([line for line in branches.splitlines() if line.strip()])

    last = _run_git(["log", "-1", "--format=%cI"], str(root))
    if last:
        stats.last_commit_at = last.strip() or None

    status = _run_git(["status", "--porcelain=v1"], str(root))
    if status:
        stats.dirty_files = len([line for line in status.splitlines() if line.strip()])

    return stats


# ── 对外入口 ────────────────────────────────────────────────────────────────


def profile_project(root: Union[str, Path]) -> CodebaseProfile:
    """采集项目代码库画像。

    Args:
        root: 项目根目录

    Returns:
        CodebaseProfile；目录不存在时返回空画像
    """
    root_path = Path(root).expanduser()
    try:
        root_path = root_path.resolve()
    except (OSError, RuntimeError):
        root_path = root_path.absolute()

    profile = CodebaseProfile(root=str(root_path))
    if not root_path.is_dir():
        return profile

    detection = detect_project_type(root_path)
    profile.level1_type = detection.project_type
    profile.sub_type = detection.sub_type

    tech_stack = detect_tech_stack(root_path)
    profile.tech_stack = tech_stack
    profile.frameworks = [item for item in tech_stack if item in FRAMEWORK_MARKERS]
    profile.vcs_mode = detect_vcs_mode(root_path, detection.project_type)

    profile.build_commands = _collect_build_commands(root_path)
    profile.test_frameworks = _collect_test_frameworks(root_path, tech_stack)
    profile.lint_configs = _collect_lint_configs(root_path)
    profile.ci_workflows = _collect_ci_workflows(root_path)
    profile.existing_rule_files = _collect_rule_files(root_path)
    profile.directory_layout = _collect_directory_layout(root_path)
    profile.source_samples = _collect_source_samples(root_path)
    profile.git_stats = _collect_git_stats(root_path)
    return profile


__all__ = [
    "CI_CANDIDATES",
    "CodebaseProfile",
    "GitStats",
    "LINT_CONFIG_CANDIDATES",
    "MAX_SAMPLE_FILES",
    "MAX_SAMPLE_LINES",
    "RULE_FILE_CANDIDATES",
    "SKIP_DIRS",
    "SOURCE_LANGUAGES",
    "SourceSample",
    "is_sensitive_path",
    "profile_project",
]
