"""Wiki 质量检查（Lint）系统。

扫描 Wiki 项目中的 Markdown 文件，检测以下问题：

1. **结构检查 (structure.required_dir / structure.required_file)** —
   检查必需目录 (wiki/entities, wiki/concepts, wiki/sources, wiki/queries)
   是否存在。

2. **Frontmatter 检查 (frontmatter.missing / frontmatter.title)** —
   每个 Wiki 页面应有 YAML frontmatter，且包含 `title` 字段。

3. **Wikilink 断链检查 (wikilink.broken)** —
   扫描 `[[目标]]` 链接，检查目标页面是否存在。

4. **孤立页面检查 (orphan)** —
   检测未被任何 wikilink 引用的页面（schema.md / overview.md 除外）。

输出数据模型参考 llm_wiki 的 LintResult / LintItem 形状。
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set


class LintSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LintType(str, Enum):
    """Lint 检查类型。"""

    REQUIRED_DIR = "required_dir"
    REQUIRED_FILE = "required_file"
    FRONTMATTER_MISSING = "frontmatter_missing"
    FRONTMATTER_TITLE = "frontmatter_title"
    WIKILINK_BROKEN = "wikilink_broken"
    ORPHAN_PAGE = "orphan"


REQUIRED_DIRS = [
    "wiki/entities",
    "wiki/concepts",
    "wiki/sources",
    "wiki/queries",
]

REQUIRED_FILES = [
    "wiki/schema.md",
]

# 被排除在孤立检查之外的页面
ORPHAN_EXEMPT = {"wiki/schema.md", "wiki/overview.md"}

WIKILINK_PATTERN = re.compile(r"\[\[([^\]#|]+?)(?:\|[^\]]+)?\]\]")


@dataclass
class LintIssue:
    """单个 Lint 问题。"""

    type: LintType
    severity: LintSeverity
    page: str
    detail: str
    # Wikilink 断链专用字段
    broken_target: Optional[str] = None
    suggested_target: Optional[str] = None
    suggested_source: Optional[str] = None
    # 受影响页面列表（orphan 检查时使用）
    affected_pages: Optional[List[str]] = None

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "page": self.page,
            "detail": self.detail,
            "broken_target": self.broken_target,
            "suggested_target": self.suggested_target,
            "suggested_source": self.suggested_source,
            "affected_pages": self.affected_pages,
        }


@dataclass
class LintResult:
    """Lint 检查结果（整体）。"""

    issues: List[LintIssue] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.issues)

    @property
    def by_severity(self) -> dict:
        return {
            "error": sum(1 for i in self.issues if i.severity == LintSeverity.ERROR),
            "warning": sum(1 for i in self.issues if i.severity == LintSeverity.WARNING),
            "info": sum(1 for i in self.issues if i.severity == LintSeverity.INFO),
        }

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "by_severity": self.by_severity,
            "issues": [i.to_dict() for i in self.issues],
        }


class WikiLint:
    """Wiki 质量检查器。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.wiki_dir = project_root / "wiki"

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def check_all(self) -> LintResult:
        """运行所有检查。"""
        result = LintResult()
        result.issues.extend(self.check_structure())
        result.issues.extend(self.check_frontmatter())
        result.issues.extend(self.check_wikilinks())
        result.issues.extend(self.check_orphans())
        return result

    # ------------------------------------------------------------------
    # 结构检查
    # ------------------------------------------------------------------

    def check_structure(self) -> List[LintIssue]:
        """检查必需目录和文件。"""
        issues: List[LintIssue] = []

        for dir_path in REQUIRED_DIRS:
            if not (self.project_root / dir_path).exists():
                issues.append(
                    LintIssue(
                        type=LintType.REQUIRED_DIR,
                        severity=LintSeverity.ERROR,
                        page=dir_path,
                        detail=f"必需目录缺失: {dir_path}",
                        suggested_target=f"创建目录: mkdir -p {dir_path}",
                    )
                )

        for file_path in REQUIRED_FILES:
            if not (self.project_root / file_path).exists():
                issues.append(
                    LintIssue(
                        type=LintType.REQUIRED_FILE,
                        severity=LintSeverity.ERROR,
                        page=file_path,
                        detail=f"必需文件缺失: {file_path}",
                        suggested_target=f"创建文件: touch {file_path}",
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # Frontmatter 检查
    # ------------------------------------------------------------------

    def check_frontmatter(self) -> List[LintIssue]:
        """检查每个 Wiki 页面的 frontmatter。"""
        issues: List[LintIssue] = []

        for md_file in self._iter_wiki_pages():
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel_path = self._rel_path(md_file)

            if not content.startswith("---"):
                issues.append(
                    LintIssue(
                        type=LintType.FRONTMATTER_MISSING,
                        severity=LintSeverity.WARNING,
                        page=rel_path,
                        detail="缺少 YAML frontmatter",
                        suggested_source=(
                            "在文件开头添加 ---\ntitle: ...\n---"
                        ),
                    )
                )
                continue

            end = content.find("---", 3)
            if end == -1:
                # 只有开头的 --- 没有结束标记，也算缺少
                issues.append(
                    LintIssue(
                        type=LintType.FRONTMATTER_MISSING,
                        severity=LintSeverity.WARNING,
                        page=rel_path,
                        detail="YAML frontmatter 缺少结束分隔符",
                    )
                )
                continue

            frontmatter_text = content[3:end].strip()

            # 检查 title 字段
            has_title = False
            for line in frontmatter_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("title:") and stripped[len("title:"):].strip():
                    has_title = True
                    break

            if not has_title:
                issues.append(
                    LintIssue(
                        type=LintType.FRONTMATTER_TITLE,
                        severity=LintSeverity.WARNING,
                        page=rel_path,
                        detail="frontmatter 缺少 title 字段",
                        suggested_source='在 frontmatter 中添加 title: "页面标题"',
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # Wikilink 断链检查
    # ------------------------------------------------------------------

    def check_wikilinks(self) -> List[LintIssue]:
        """检查 wikilink 是否指向存在的页面。"""
        issues: List[LintIssue] = []

        # 收集所有已有页面的相对路径（去扩展名，用于匹配）
        known_targets = self._collect_known_targets()

        for md_file in self._iter_wiki_pages():
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel_path = self._rel_path(md_file)

            for match in WIKILINK_PATTERN.finditer(content):
                link_target = match.group(1).strip()

                # 检查目标是否已知
                resolved = self._resolve_wikilink(md_file, link_target)
                if resolved is None and link_target not in known_targets:
                    # 断链
                    issues.append(
                        LintIssue(
                            type=LintType.WIKILINK_BROKEN,
                            severity=LintSeverity.WARNING,
                            page=rel_path,
                            detail=f"断链: [[{link_target}]]",
                            broken_target=link_target,
                            suggested_target=f"创建页面: {link_target}.md",
                        )
                    )

        return issues

    # ------------------------------------------------------------------
    # 孤立页面检查
    # ------------------------------------------------------------------

    def check_orphans(self) -> List[LintIssue]:
        """检测未被任何 wikilink 引用的页面。"""
        issues: List[LintIssue] = []

        # 收集所有被引用的目标
        referenced: Set[str] = set()
        for md_file in self._iter_wiki_pages():
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in WIKILINK_PATTERN.finditer(content):
                link_target = match.group(1).strip()
                referenced.add(link_target)
                # 也记录可能的 .md 扩展名形式
                referenced.add(link_target + ".md")

        # 扫描所有页面，找出未被引用的
        for md_file in self._iter_wiki_pages():
            rel_path = self._rel_path(md_file)

            # 排除豁免名单
            if rel_path in ORPHAN_EXEMPT:
                continue

            # 页面文件名（无扩展名）是否被引用
            stem = md_file.stem
            if stem not in referenced and rel_path not in referenced:
                issues.append(
                    LintIssue(
                        type=LintType.ORPHAN_PAGE,
                        severity=LintSeverity.INFO,
                        page=rel_path,
                        detail="孤立页面: 未被任何 wikilink 引用",
                        suggested_source=(
                            f"在相关页面中添加 [[{stem}]] 链接，"
                            f"或将页面移入 wiki/queries/ 作为临时笔记"
                        ),
                    )
                )

        return issues

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _iter_wiki_pages(self):
        """迭代所有 wiki 目录下的 Markdown 文件。"""
        if not self.wiki_dir.exists():
            return
        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.is_file():
                yield md_file

    def _rel_path(self, p: Path) -> str:
        return str(p.relative_to(self.project_root)).replace("\\", "/")

    def _collect_known_targets(self) -> Set[str]:
        """收集所有 wiki 页面的标题/路径作为已知引用目标。"""
        targets: Set[str] = set()
        for md_file in self._iter_wiki_pages():
            rel = self._rel_path(md_file)
            # 相对路径无扩展名
            no_ext = rel.rsplit(".md", 1)[0] if rel.endswith(".md") else rel
            targets.add(no_ext)
            # 纯文件名（无目录前缀）
            targets.add(md_file.stem)
            # 完整相对路径
            targets.add(rel)
        return targets

    def _resolve_wikilink(
        self, source_file: Path, link_target: str
    ) -> Optional[str]:
        """尝试将 wikilink 目标解析为已存在文件的相对路径。

        返回 None 表示未找到。
        """
        candidates = [
            self.wiki_dir / f"{link_target}.md",
            self.wiki_dir / link_target / "index.md",
            # 相对 source 文件解析
            source_file.parent / f"{link_target}.md",
        ]

        for candidate in candidates:
            if candidate.exists():
                return self._rel_path(candidate)
        return None
