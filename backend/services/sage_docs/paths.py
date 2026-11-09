# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Sage 内置文档库路径解析（sage-guide 知识源）。

文档目录按以下优先级解析（第一个存在的目录胜出）：

1. ``SAGE_DOCS_DIR`` 环境变量（测试 / 高级排障显式覆盖）；
2. Electron 打包态由 ``spawnBackend()`` 注入的 ``<resourcesPath>/docs``；
3. PyInstaller ``sys._MEIPASS/docs``；
4. 仓库布局 ``<repo_root>/docs``。

第 2、4 项实际落在同一个推导式上：``paths.py`` 位于
``<root>/backend/services/sage_docs/``，向上三级即 ``<root>``，
再拼 ``docs``。因此开发态得到 ``<repo>/docs``，打包态得到
``<resources>/docs``。

全部不存在时返回 ``None``，检索层 fail-open 为空结果。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

#: 文档根目录覆盖（应指向包含 ``user-manual/`` 与 ``technical/`` 的目录）。
DOCS_ENV_VAR = "SAGE_DOCS_DIR"

#: 索引库目录覆盖（测试隔离用）。
INDEX_ENV_VAR = "SAGE_DOCS_INDEX_DIR"

#: 打包进安装包的技术手册白名单（与 electron-builder.yml /
#: scripts/backend.spec 的白名单保持一致）。
TECHNICAL_WHITELIST = (
    "README.md",
    "15-state-ownership.md",
    "18-hexagonal.md",
    "20-electron.md",
    "22-agents-crud.md",
    "24-skills-system.md",
    "32-settings-canonicalization.md",
    "41-sage-doctor.md",
    "47-git-worktree-workflow.md",
    "133-specialist-persona.md",
    "135-specialist-asset-hub.md",
    "139-specialist-dm-group-chat.md",
    "142-sage-guide-specialist.md",
)


def resolve_docs_root() -> Optional[Path]:
    """返回文档根目录；所有候选都不存在时返回 ``None``。"""
    env = os.environ.get(DOCS_ENV_VAR)
    if env:
        candidate = Path(env)
        if candidate.is_dir():
            return candidate.resolve()

    candidates: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "docs")
    candidates.append(Path(__file__).resolve().parents[3] / "docs")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def resolve_index_dir() -> Path:
    """返回索引库目录（不保证存在，调用方负责创建）。"""
    env = os.environ.get(INDEX_ENV_VAR)
    if env:
        return Path(env)
    user_data = os.environ.get("SAGE_USER_DATA_DIR")
    base = Path(user_data) if user_data else Path.home() / ".sage"
    return base / "sage-docs-index"


def iter_doc_files(docs_root: Path) -> List[Path]:
    """枚举需入库的文档：``user-manual`` 全量 + 技术手册白名单。"""
    files: List[Path] = []
    user_manual = docs_root / "user-manual"
    if user_manual.is_dir():
        files.extend(sorted(user_manual.rglob("*.md")))
    technical = docs_root / "technical"
    for name in TECHNICAL_WHITELIST:
        candidate = technical / name
        if candidate.is_file():
            files.append(candidate)
    return files
