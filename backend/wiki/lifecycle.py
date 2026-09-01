"""Source/WikiPage 生命周期管理。

实现级联删除：删除 Source 时自动清理派生 Wiki 页、嵌入向量、死链。
"""
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from . import frontmatter
from .files import (
    iter_wiki_markdown,
    secure_delete_path,
    secure_read_text,
    secure_write_file,
)
from .vectorstore import VectorStore

logger = logging.getLogger(__name__)


def cascade_delete_source(project_root: Path, source_path: str) -> dict:
    """级联删除 Source 及其关联资源。

    删除流程：
    1. 查找并删除所有引用此 source 的 wiki 页面
    2. 删除这些页面的嵌入向量
    3. 清理其他页面中的死链 [[wikilinks]]
    4. 更新 index.md

    Args:
        project_root: 项目根目录
        source_path: 要删除的 source 相对路径（如 "raw/sources/test.pdf"）

    Returns:
        dict: 删除统计信息
            - deleted_wiki_pages: 删除的 wiki 页面列表
            - deleted_vectors: 删除的向量数量
            - cleaned_deadlinks: 清理的死链数量
    """
    stats = {
        "deleted_wiki_pages": [],
        "deleted_vectors": 0,
        "cleaned_deadlinks": 0,
    }

    wiki_dir = project_root / "wiki"
    if not wiki_dir.exists():
        return stats

    # Step 1: 查找引用此 source 的 wiki 页面
    pages_to_delete = []
    for md_file in iter_wiki_markdown(project_root):
        if md_file.name in ("index.md", "log.md", "schema.md"):
            continue
        if any(part.startswith(".") for part in md_file.parts):
            continue

        try:
            content = secure_read_text(project_root, md_file)
        except OSError:
            continue
        parsed = frontmatter.parse(content)

        # 检查 frontmatter.sources 是否包含此 source
        if source_path in parsed.frontmatter.sources:
            pages_to_delete.append(md_file)

    # Step 2: 删除 wiki 页面和嵌入向量
    vector_store = None
    try:
        vector_store = VectorStore.open(project_root, dim=1536)
    except Exception as exc:
        logger.warning("无法打开向量存储: error_type=%s", type(exc).__name__)

    deleted_titles = set()
    for page_path in pages_to_delete:
        relative_path = str(page_path.relative_to(project_root)).replace("\\", "/")

        # Read before deletion; the path must not be reopened after secure delete.
        try:
            page_content = secure_read_text(project_root, page_path)
            parsed_page = frontmatter.parse(page_content)
            if parsed_page.frontmatter.title:
                deleted_titles.add(parsed_page.frontmatter.title)
        except Exception as exc:
            logger.warning("读取待删除页面失败 %s: error_type=%s", relative_path, type(exc).__name__)

        # 删除嵌入向量
        if vector_store:
            try:
                deleted_count = vector_store.delete_by_page(relative_path)
                stats["deleted_vectors"] += deleted_count
                logger.info(f"删除 {relative_path} 的 {deleted_count} 个向量")
            except Exception as exc:
                logger.error("删除向量失败 %s: error_type=%s", relative_path, type(exc).__name__)

        # 删除 wiki 页面文件
        try:
            secure_delete_path(project_root, page_path)
            stats["deleted_wiki_pages"].append(relative_path)
            logger.info(f"删除 wiki 页面: {relative_path}")
        except Exception as exc:
            logger.error("删除文件失败 %s: error_type=%s", relative_path, type(exc).__name__)

    # Step 3: 清理其他页面中的死链
    if pages_to_delete:
        # 遍历所有剩余页面，清理死链
        for md_file in iter_wiki_markdown(project_root):
            if md_file.name in ("index.md", "log.md", "schema.md"):
                continue
            if any(part.startswith(".") for part in md_file.parts):
                continue
            if md_file in pages_to_delete:
                continue  # 跳过已删除的页面

            try:
                content = secure_read_text(project_root, md_file)
                parsed = frontmatter.parse(content)

                # 检查 related 字段中是否有死链
                updated_related = [
                    link for link in parsed.frontmatter.related if link not in deleted_titles
                ]

                if len(updated_related) != len(parsed.frontmatter.related):
                    # 更新 frontmatter
                    parsed.frontmatter.related = updated_related
                    new_content = frontmatter.serialize(parsed)
                    secure_write_file(project_root, md_file, new_content)

                    deadlinks_removed = len(parsed.frontmatter.related) - len(updated_related)
                    stats["cleaned_deadlinks"] += deadlinks_removed
                    logger.info(f"清理 {md_file.name} 中的 {deadlinks_removed} 个死链")
            except Exception as exc:
                logger.error("清理死链失败 %s: error_type=%s", md_file, type(exc).__name__)

    # Step 4: 更新 index.md
    try:
        _update_wiki_index(project_root)
    except Exception as exc:
        logger.error("更新 index.md 失败: error_type=%s", type(exc).__name__)

    logger.info(
        f"级联删除完成: 删除 {len(stats['deleted_wiki_pages'])} 个页面, "
        f"{stats['deleted_vectors']} 个向量, 清理 {stats['cleaned_deadlinks']} 个死链"
    )

    return stats


def _update_wiki_index(project_root: Path) -> None:
    """更新 wiki/index.md。

    扫描所有 wiki 页面，按类型分组，生成索引。
    """
    wiki_dir = project_root / "wiki"
    index_file = wiki_dir / "index.md"

    if not wiki_dir.exists():
        return

    # 收集所有页面
    pages_by_type: Dict[str, List[Tuple[str, str]]] = {}  # type -> [(title, path)]

    for md_file in iter_wiki_markdown(project_root):
        if md_file.name in ("index.md", "log.md", "schema.md"):
            continue
        if any(part.startswith(".") for part in md_file.parts):
            continue

        try:
            content = secure_read_text(project_root, md_file)
        except OSError:
            continue
        try:
            parsed = frontmatter.parse(content)

            title = parsed.frontmatter.title or md_file.stem
            page_type = parsed.frontmatter.page_type or "other"
            relative_path = str(md_file.relative_to(project_root)).replace("\\", "/")

            if page_type not in pages_by_type:
                pages_by_type[page_type] = []
            pages_by_type[page_type].append((title, relative_path))
        except Exception as exc:
            logger.warning("解析 %s 失败: error_type=%s", md_file, type(exc).__name__)

    # 生成 index.md
    from datetime import datetime

    lines = ["# Wiki 索引\n", f"自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]

    for page_type in sorted(pages_by_type.keys()):
        pages = pages_by_type[page_type]
        lines.append(f"\n## {page_type.title()} ({len(pages)})\n")

        for title, path in sorted(pages, key=lambda x: x[0]):
            lines.append(f"- [[{title}]]({path})\n")

    secure_write_file(project_root, index_file, "".join(lines))
    logger.info(f"更新 index.md: {sum(len(p) for p in pages_by_type.values())} 个页面")
