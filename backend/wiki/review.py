"""Wiki 审核系统 - 检测知识库中的内容质量问题

检测类型:
- duplicate: 重复页(基于标题/内容相似度)
- contradiction: 元数据或内容冲突(基于 frontmatter 矛盾)
- missing-page: 被引用但不存在的页(断链指向)
- confirm: 需要人工确认(基于低置信度匹配)
- suggestion: 改进建议(如短页、缺 frontmatter)

实现为确定性启发式，不依赖 LLM，便于测试和稳定复现。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

# 复用 lint 中的 wikilink 正则
try:
    from .lint import WIKILINK_PATTERN
except Exception:  # pragma: no cover - fallback
    WIKILINK_PATTERN = re.compile(r"\[\[([^\]#|]+?)(?:\|[^\]]+)?\]\]")


class ReviewType(str, Enum):
    DUPLICATE = "duplicate"
    CONTRADICTION = "contradiction"
    MISSING_PAGE = "missing-page"
    CONFIRM = "confirm"
    SUGGESTION = "suggestion"


@dataclass
class ReviewItem:
    """单条审核项"""

    id: str
    type: ReviewType
    title: str
    description: str
    affected_pages: List[str]
    confidence: float  # 0.0 - 1.0
    detail: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "affected_pages": list(self.affected_pages),
            "confidence": self.confidence,
            "detail": self.detail,
            "suggestion": self.suggestion,
        }


@dataclass
class ReviewResult:
    """审核结果集合"""

    items: List[ReviewItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {t.value: 0 for t in ReviewType}
        for item in self.items:
            counts[item.type.value] += 1
        return counts

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "by_type": self.by_type,
            "items": [i.to_dict() for i in self.items],
        }


def _stable_id(type_: ReviewType, *keys: str) -> str:
    """生成内容稳定的 ID（blake2b 64 位 → 16 hex）

    相同 (type, keys) 永远得到同一 id，
    便于前端持久化/去重/用户"已忽略"映射。
    """
    payload = f"{type_.value}:" + "|".join(keys)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()
    return f"rv-{digest}"


def _strip_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """极简 frontmatter 抽取(无 yaml 依赖)，返回 (fields, body)"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip()
    body = text[end + 4 :]
    fields: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fields[k.strip().lower()] = v.strip().strip('"').strip("'")
    return fields, body


def _tokenize(text: str) -> List[str]:
    """简易 token 化:小写 + 拆分非字母数字，过滤短 token"""
    cleaned = text.lower()
    tokens = re.findall(r"[a-z0-9一-鿿]+", cleaned)
    return [t for t in tokens if len(t) > 1]


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _read_frontmatter(path: Path) -> Tuple[Dict[str, str], str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    return _strip_frontmatter(text)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _resolve_wikilink(target: str, wiki_dir: Path) -> Optional[Path]:
    """尝试把 wikilink 解析为现有 .md 文件"""
    target = target.strip()
    if not target:
        return None
    # 跳过跨目录/相对路径的复杂形式，仅处理简单名
    if "/" in target or "\\" in target or target.startswith("."):
        return None
    candidates = [
        wiki_dir / f"{target}.md",
        wiki_dir / target / "index.md",
        wiki_dir / target.capitalize() / "index.md",
    ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except OSError:
            continue
    return None


class WikiReview:
    """Wiki 审核系统：扫描项目，产出待人工/LLM 复核的条目"""

    SHORT_PAGE_THRESHOLD = 150  # 字符数

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.wiki_dir = self.project_root / "wiki"

    # ------------------------------------------------------------------ public

    def check_all(self) -> ReviewResult:
        """运行所有检查，返回合并后的 ReviewResult"""
        result = ReviewResult()
        result.items.extend(self.check_missing_pages())
        result.items.extend(self.check_duplicates())
        result.items.extend(self.check_contradictions())
        result.items.extend(self.check_suggestions())
        result.items.extend(self.check_confirm())
        return result

    # ------------------------------------------------------------- detectors

    def check_missing_pages(self) -> List[ReviewItem]:
        """找出被 [[wikilink]] 引用但实际不存在的页"""
        if not self.wiki_dir.exists():
            return []

        # 先收集 wiki 下所有现有 page 的"别名集"(stem 与 path)
        existing_targets: Set[str] = set()
        for md in self.wiki_dir.rglob("*.md"):
            stem = md.stem.lower()
            existing_targets.add(stem)
            rel = _rel(md, self.wiki_dir).replace("\\", "/")
            # py3.8 无 str.removesuffix（py3.9+）
            if rel.endswith(".md"):
                rel = rel[: -len(".md")]
            existing_targets.add(rel.lower())

        items: List[ReviewItem] = []
        # target → 指向它的源文件列表
        broken_map: Dict[str, List[str]] = {}
        for md in self.wiki_dir.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in WIKILINK_PATTERN.finditer(text):
                target = m.group(1).strip()
                if not target:
                    continue
                if target.lower() in existing_targets:
                    continue
                if _resolve_wikilink(target, self.wiki_dir) is not None:
                    continue
                broken_map.setdefault(target, []).append(_rel(md, self.project_root))

        for target, sources in sorted(broken_map.items()):
            items.append(
                ReviewItem(
                    id=_stable_id(ReviewType.MISSING_PAGE, target),
                    type=ReviewType.MISSING_PAGE,
                    title=f"缺失页: [[{target}]]",
                    description=(
                        f"页 '{target}' 被 {len(sources)} 处引用但不存在。"
                        "建议创建该页，或修正引用方的 wikilink。"
                    ),
                    affected_pages=sorted(set(sources)),
                    confidence=1.0,
                    detail=f"broken_target={target}",
                    suggestion=f"创建 wiki/{target}.md 或修正引用",
                )
            )
        return items

    def check_duplicates(self) -> List[ReviewItem]:
        """基于标题 token 重叠检测可能重复的页"""
        if not self.wiki_dir.exists():
            return []

        pages: List[Tuple[Path, str, List[str]]] = []  # (path, title, tokens)
        for md in self.wiki_dir.rglob("*.md"):
            fields, _body = _read_frontmatter(md)
            title = fields.get("title") or md.stem
            tokens = _tokenize(title)
            if tokens:
                pages.append((md, title, tokens))

        items: List[ReviewItem] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        threshold = 0.6

        for i in range(len(pages)):
            for j in range(i + 1, len(pages)):
                pa, ta, tka = pages[i]
                _pb, tb, tkb = pages[j]
                score = _jaccard(tka, tkb)
                if score < threshold:
                    continue
                # 要求 token 集合有一定规模，避免两个单字标题误判
                if len(tka) < 2 or len(tkb) < 2:
                    continue
                key_a = _rel(pa, self.project_root)
                key_b = _rel(pages[j][0], self.project_root)
                pair_key = (min(key_a, key_b), max(key_a, key_b))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                items.append(
                    ReviewItem(
                        id=_stable_id(ReviewType.DUPLICATE, pair_key[0], pair_key[1]),
                        type=ReviewType.DUPLICATE,
                        title=f"疑似重复: {ta} ↔ {tb}",
                        description=(
                            f"两个页标题 token 重叠度 {score:.0%}，可能是重复条目。"
                            "建议合并或明确区分范围。"
                        ),
                        affected_pages=[key_a, key_b],
                        confidence=min(score, 0.99),
                        detail=f"jaccard={score:.2f}",
                        suggestion="合并两页，或在 frontmatter 中明确各自的区分维度",
                    )
                )
        return items

    def check_contradictions(self) -> List[ReviewItem]:
        """检测 frontmatter 元数据矛盾(如 created > updated)"""
        if not self.wiki_dir.exists():
            return []

        items: List[ReviewItem] = []
        for md in self.wiki_dir.rglob("*.md"):
            fields, _ = _read_frontmatter(md)
            created = fields.get("created") or fields.get("date")
            updated = fields.get("updated")
            if created and updated and created > updated:
                items.append(
                    ReviewItem(
                        id=_stable_id(ReviewType.CONTRADICTION, _rel(md, self.project_root), "dates"),
                        type=ReviewType.CONTRADICTION,
                        title=f"日期矛盾: {_rel(md, self.project_root)}",
                        description=(
                            f"frontmatter 中 created='{created}' 晚于 updated='{updated}'，"
                            "时间顺序不一致。"
                        ),
                        affected_pages=[_rel(md, self.project_root)],
                        confidence=1.0,
                        detail=f"created={created},updated={updated}",
                        suggestion="检查并修正 frontmatter 中的 created/updated 字段",
                    )
                )
        return items

    def check_suggestions(self) -> List[ReviewItem]:
        """基于启发式的改进建议(短页、缺 frontmatter 等)"""
        if not self.wiki_dir.exists():
            return []

        items: List[ReviewItem] = []
        for md in self.wiki_dir.rglob("*.md"):
            rel = _rel(md, self.project_root)
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fields, body = _strip_frontmatter(text)
            # 短页
            if len(body.strip()) < self.SHORT_PAGE_THRESHOLD:
                items.append(
                    ReviewItem(
                        id=_stable_id(ReviewType.SUGGESTION, rel, "short"),
                        type=ReviewType.SUGGESTION,
                        title=f"页过短: {rel}",
                        description=(
                            f"正文仅 {len(body.strip())} 字符，"
                            f"低于阈值 {self.SHORT_PAGE_THRESHOLD}。"
                            "建议补充更多上下文或合并到相关页。"
                        ),
                        affected_pages=[rel],
                        confidence=0.6,
                        detail="short_page",
                        suggestion="扩充内容，或合并到更相关的页",
                    )
                )
            # 缺 title
            if not fields.get("title"):
                items.append(
                    ReviewItem(
                        id=_stable_id(ReviewType.SUGGESTION, rel, "no-title"),
                        type=ReviewType.SUGGESTION,
                        title=f"缺 title: {rel}",
                        description="frontmatter 未声明 title，UI 和搜索会用文件名兜底。",
                        affected_pages=[rel],
                        confidence=0.9,
                        detail="missing_title",
                        suggestion="在 frontmatter 中添加 title: ...",
                    )
                )
        return items

    def check_confirm(self) -> List[ReviewItem]:
        """低置信度确认项(需要人工判断):例如无 wikilink 的孤立页"""
        if not self.wiki_dir.exists():
            return []

        # 统计每个页被引用的次数
        referenced: Dict[str, int] = {}
        all_pages: List[str] = []
        for md in self.wiki_dir.rglob("*.md"):
            rel = _rel(md, self.project_root)
            all_pages.append(rel)
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in WIKILINK_PATTERN.finditer(text):
                target = m.group(1).strip()
                if not target:
                    continue
                referenced[target.lower()] = referenced.get(target.lower(), 0) + 1

        items: List[ReviewItem] = []
        exempt = {"wiki/schema.md", "wiki/overview.md"}
        for rel in all_pages:
            if rel in exempt:
                continue
            stem = Path(rel).stem.lower()
            if referenced.get(stem, 0) == 0:
                items.append(
                    ReviewItem(
                        id=_stable_id(ReviewType.CONFIRM, rel, "orphan"),
                        type=ReviewType.CONFIRM,
                        title=f"无入链，请确认: {rel}",
                        description="没有任何其他页通过 wikilink 引用此页。"
                        "可能是孤立条目，也可能是有意为之，请人工确认。",
                        affected_pages=[rel],
                        confidence=0.5,
                        detail="zero_incoming",
                        suggestion="从相关页添加指向此页的 [[wikilink]]，或移入 overview",
                    )
                )
        return items
