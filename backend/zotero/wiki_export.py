"""Zotero → wiki 沉淀（M4）。

只把**显式标记**的文献渲染成 wiki 页面（默认 tag ``sage:wiki``，可在设置页
改 ``zotero_wiki_tag``）。生成两类页面：

- ``wiki/zotero/items/{KEY}.md``   — 文献页（``type: source``）
- ``wiki/zotero/authors/{slug}.md`` — 作者页（``type: entity``，仅当该作者
  至少有一篇标记文献）

图谱由现有 ``backend/wiki/graph.py`` 自动推导（**零改动**）：

- 文献页 ``related: [[作者显示名]]`` → 作者页 ``title`` 精确匹配 → DirectLink
- 作者页 ``related: [[论文标题]]`` → 文献页 ``title`` 精确匹配 → DirectLink
- 两页共享 ``sources: [zotero:KEY]`` → SourceOverlap
- 所有 ``type: source`` 文献页之间 → TypeAffinity

因此 wikilink 的文本**必须等于目标页的 title**。解析顺序是「label 精确匹配 →
id 精确匹配 → slug 匹配」，只有 label 层是无歧义可命中的（id 相对路径、
slug 兜底都可能撞车）。

幂等性：内容未变则不重写文件，避免反复同步抖动 mtime / 触发 wiki 重索引。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.wiki.frontmatter import Frontmatter, ParsedDoc, serialize

logger = logging.getLogger(__name__)

#: 默认 wiki 沉淀 tag
DEFAULT_WIKI_TAG = "sage:wiki"

#: wiki 沉淀根目录（相对 project_root）
WIKI_ZOTERO_DIR = "zotero"


@dataclass
class WikiExportResult:
    """一次沉淀的结果。"""

    items_exported: int = 0
    authors_exported: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items_exported": self.items_exported,
            "authors_exported": self.authors_exported,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# 配置 / 命名
# ---------------------------------------------------------------------------


def wiki_tag_config() -> str:
    """读 ``zotero_wiki_tag`` 设置，缺省 ``sage:wiki``。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        value = SettingsRepository().get("zotero_wiki_tag")
    except Exception:  # pragma: no cover - settings DB 不可用时退回默认
        logger.debug("read zotero_wiki_tag failed", exc_info=True)
        return DEFAULT_WIKI_TAG
    text = (value or "").strip()
    return text or DEFAULT_WIKI_TAG


def _one_line(text: str) -> str:
    """压成单行：frontmatter 一个字段只能占一行。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def slugify_author(author: Dict[str, Any]) -> str:
    """把 ``{lastName, firstName}`` 变成稳定的文件名 slug。

    规则 ``{lastName}-{firstName首字母}``，小写，非字母数字归一为 ``-``。
    例：``{"lastName": "Vaswani", "firstName": "Ashish"}`` → ``vaswani-a``。

    CJK 等纯非 ASCII 名字保留原字符（``[^a-z0-9一-鿿]+``），
    避免不同中文名全部塌缩到 ``unknown`` 导致作者页互相覆盖；
    仍无法得到任何字符时回退到 ``lastName`` 前 8 位 hex SHA，保证唯一。
    """
    last = str(author.get("lastName") or "").strip().lower()
    first = str(author.get("firstName") or "").strip()
    initial = first[:1].lower()
    raw = f"{last}-{initial}" if last else initial
    slug = re.sub(r"[^a-z0-9一-鿿]+", "-", raw).strip("-")
    if slug:
        return slug
    if last:
        import hashlib

        return hashlib.sha256(last.encode("utf-8")).hexdigest()[:8]
    return "unknown"


def author_display_name(author: Dict[str, Any]) -> str:
    """作者页 title，同时用作文献页里的 wikilink 文本。

    ``{lastName, firstName}`` → ``"Vaswani, A."``；只有单一字段时原样返回。
    """
    last = _one_line(str(author.get("lastName") or ""))
    first = _one_line(str(author.get("firstName") or ""))
    if last and first:
        return f"{last}, {first[:1]}."
    return last or first or "Unknown"


def _valid_author(author: Any) -> bool:
    return isinstance(author, dict) and bool(author.get("lastName") or author.get("firstName"))


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def _authors_brief(authors: List[Dict[str, Any]]) -> str:
    """文献页正文里的作者串：``Vaswani, A.; Shazeer, N.``。"""
    parts = [author_display_name(a) for a in authors or [] if _valid_author(a)]
    return "; ".join(parts)


def _year(date_text: str) -> str:
    """Zotero ``date`` 是自由文本（``2017-06-12`` / ``June 2017``），取首个年份。"""
    match = re.search(r"\d{4}", date_text or "")
    return match.group(0) if match else ""


def _tag_names(item: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for tag in item.get("tags") or []:
        name = str(tag.get("name") if isinstance(tag, dict) else tag).strip()
        if name:
            names.append(name)
    return names


def _collection_names(item: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for coll in item.get("collections") or []:
        if isinstance(coll, dict):
            name = str(coll.get("name") or coll.get("key") or "").strip()
        else:
            name = str(coll).strip()
        if name:
            names.append(name)
    return names


def render_item_page(
    item: Dict[str, Any],
    annotations: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """把一条 Zotero 文献渲染成 wiki 文献页（frontmatter + body）。"""
    key = str(item.get("key") or "")
    title = _one_line(str(item.get("title") or "")) or key
    authors = [a for a in (item.get("authors") or []) if _valid_author(a)]

    frontmatter = Frontmatter(
        title=title,
        page_type="source",
        tags=_tag_names(item),
        related=[author_display_name(a) for a in authors],
        sources=[f"zotero:{key}"] if key else [],
    )

    lines = [f"# {title}", ""]

    authors_text = _authors_brief(authors)
    if authors_text:
        lines.append(f"**Authors**: {authors_text}")

    year = _year(str(item.get("date") or ""))
    item_type = str(item.get("item_type") or "")
    meta: List[str] = []
    if year:
        meta.append(f"Year: {year}")
    if item_type:
        meta.append(f"Type: {item_type}")
    if meta:
        lines.append(" | ".join(meta))

    doi = str(item.get("doi") or "").strip()
    if doi:
        lines.append(f"**DOI**: [{doi}](https://doi.org/{doi})")

    if key:
        key_line = f"**Zotero**: `{key}`"
        colls = _collection_names(item)
        if colls:
            key_line += f" | **Collections**: {', '.join(colls)}"
        lines.append(key_line)

    abstract = str(item.get("abstract") or "").strip()
    if abstract:
        lines.extend(["", "## Abstract", "", abstract])

    visible = [
        a for a in (annotations or [])
        if isinstance(a, dict) and (a.get("text") or a.get("comment"))
    ]
    if visible:
        lines.extend(["", "## Annotations", ""])
        for anno in visible:
            lines.append(_render_annotation(anno))

    body = "\n".join(lines)
    return serialize(ParsedDoc(frontmatter=frontmatter, body=body))


def _render_annotation(anno: Dict[str, Any]) -> str:
    color = str(anno.get("color") or "").strip()
    text = _one_line(str(anno.get("text") or ""))
    comment = _one_line(str(anno.get("comment") or ""))
    prefix = f"[{color}] " if color else ""
    if text and comment:
        return f'- {prefix}"{text}" — {comment}'
    if text:
        return f'- {prefix}"{text}"'
    return f"- {prefix}{comment}"


def render_author_page(
    author: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> str:
    """把一位作者的若干标记文献渲染成作者页。"""
    display = author_display_name(author)

    frontmatter = Frontmatter(
        title=display,
        page_type="entity",
        tags=["author"],
        related=[
            _one_line(str(it.get("title") or "")) or str(it.get("key") or "")
            for it in items
            if it.get("title") or it.get("key")
        ],
        sources=[f"zotero:{it.get('key')}" for it in items if it.get("key")],
    )

    lines = [f"# {display}", ""]
    for it in items:
        title = _one_line(str(it.get("title") or "")) or str(it.get("key") or "")
        year = _year(str(it.get("date") or ""))
        bullet = f"- {title}"
        if year:
            bullet += f" ({year})"
        lines.append(bullet)

    body = "\n".join(lines)
    return serialize(ParsedDoc(frontmatter=frontmatter, body=body))


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


def _write_if_changed(path: Path, content: str) -> bool:
    """内容未变则不写，保持幂等。返回 ``True`` 表示内容未变或成功写入。"""
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return True
        path.write_text(content, encoding="utf-8")
        return True
    except OSError as exc:  # pragma: no cover - 磁盘异常不应中断整批
        logger.warning("wiki write failed for %s: %s", path, exc)
        return False


def export_wiki(
    client: Any,
    project_root: Path,
    wiki_tag: Optional[str] = None,
) -> WikiExportResult:
    """把带 wiki tag 的文献沉淀到 ``<project_root>/wiki/zotero/``。

    Args:
        client: 提供 ``items_by_tag`` / ``get_item`` / ``get_annotations`` 的
            Zotero 客户端。
        project_root: 项目根目录（wiki 位于其下的 ``wiki/``）。
        wiki_tag: 沉淀 tag；``None`` 时读设置（缺省 ``sage:wiki``）。

    尽力而为：单篇文献失败只记 ``errors``，不中断整批。
    """
    tag = wiki_tag or wiki_tag_config()
    root = Path(project_root)
    base = root / "wiki" / WIKI_ZOTERO_DIR
    items_dir = base / "items"
    authors_dir = base / "authors"
    result = WikiExportResult()

    try:
        items_dir.mkdir(parents=True, exist_ok=True)
        authors_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"mkdir failed: {exc}")
        return result

    try:
        tagged = list(client.items_by_tag(tag))
    except Exception as exc:  # pragma: no cover - 客户端异常
        result.errors.append(f"items_by_tag failed: {exc}")
        return result

    # slug → {"author": entry, "items": [item, ...]}
    author_index: Dict[str, Dict[str, Any]] = {}
    exported_item_keys: set = set()

    for summary in tagged:
        key = str(summary.get("key") or "")
        if not key:
            continue
        try:
            full = client.get_item(key)
            annotations = client.get_annotations(key)
        except Exception as exc:  # noqa: BLE001 - 单篇失败不影响整批
            result.errors.append(f"item {key}: {exc}")
            continue

        if _write_if_changed(items_dir / f"{key}.md", render_item_page(full, annotations)):
            result.items_exported += 1
            exported_item_keys.add(key)
        else:
            result.errors.append(f"item {key}: write failed")

        for author in full.get("authors") or []:
            if not _valid_author(author):
                continue
            slug = slugify_author(author)
            slot = author_index.setdefault(slug, {"author": author, "items": []})
            slot["items"].append(full)

    exported_author_slugs: set = set()
    for slug, payload in author_index.items():
        if _write_if_changed(
            authors_dir / f"{slug}.md",
            render_author_page(payload["author"], payload["items"]),
        ):
            result.authors_exported += 1
            exported_author_slugs.add(slug)
        else:
            result.errors.append(f"author {slug}: write failed")

    # 清理残留页面：用户移除 wiki tag 后，旧页面应被删除，避免图谱边持续存在
    _cleanup_stale_pages(items_dir, exported_item_keys, result)
    _cleanup_stale_pages(authors_dir, exported_author_slugs, result)

    return result


def _cleanup_stale_pages(directory: Path, keep: set, result: WikiExportResult) -> None:
    """删除目录中不在 ``keep`` 集合内的 .md 文件；失败只记 errors。"""
    try:
        for path in directory.glob("*.md"):
            stem = path.stem
            if stem not in keep:
                try:
                    path.unlink()
                    logger.info("removed stale wiki page: %s", path)
                except OSError as exc:
                    result.errors.append(f"stale cleanup {path.name}: {exc}")
    except OSError as exc:  # pragma: no cover - 目录级异常
        result.errors.append(f"stale cleanup failed: {exc}")
