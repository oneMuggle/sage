"""YAML frontmatter 解析和序列化。

支持解析 Markdown 文件中的 YAML frontmatter，提取 wikilinks，序列化回 Markdown。
用于 Wiki 页面（区别于 backend/skills/skill_md/frontmatter.py 用于 SKILL.md）。
"""

from dataclasses import dataclass, field


@dataclass
class Frontmatter:
    """YAML frontmatter 数据。"""

    title: str | None = None
    page_type: str | None = None  # "source"/"entity"/"concept"/...
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # wikilink 目标
    sources: list[str] = field(default_factory=list)
    created: str | None = None
    updated: str | None = None
    extra: dict[str, str] = field(default_factory=dict)  # 未知字段


@dataclass
class ParsedDoc:
    """解析后的文档。"""

    frontmatter: Frontmatter
    body: str


def parse(content: str) -> ParsedDoc:
    """解析 Markdown 内容，提取 frontmatter 和 body。

    Args:
        content: Markdown 文件内容

    Returns:
        ParsedDoc: 包含 frontmatter 和 body 的文档
    """
    if not content.startswith("---\n"):
        return ParsedDoc(Frontmatter(), content)

    # 查找结束的 ---
    remainder = content[4:]
    end_idx = remainder.find("\n---")
    if end_idx == -1:
        return ParsedDoc(Frontmatter(), content)

    yaml_str = remainder[:end_idx]
    body_start = end_idx + 5  # 跳过 "\n---"
    # 跳过最多 2 个换行
    while body_start < len(remainder) and remainder[body_start] == "\n":
        body_start += 1
    body = remainder[body_start:]

    # 解析 YAML（简化版，逐行解析）
    frontmatter = _parse_yaml(yaml_str)
    return ParsedDoc(frontmatter, body)


def _parse_yaml(yaml_str: str) -> Frontmatter:
    """解析 YAML 字符串为 Frontmatter。

    Args:
        yaml_str: YAML 字符串

    Returns:
        Frontmatter: 解析后的 frontmatter
    """
    fm = Frontmatter()

    for raw_line in yaml_str.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # 分割 key: value
        colon_idx = line.find(":")
        if colon_idx == -1:
            continue

        key = line[:colon_idx].strip()
        value = line[colon_idx + 1 :].strip()

        # 映射已知字段
        if key == "title":
            fm.title = value
        elif key == "type":
            fm.page_type = value
        elif key == "tags":
            fm.tags = _parse_list_value(value)
        elif key == "related":
            fm.related = _parse_related_value(value)
        elif key == "sources":
            fm.sources = _parse_list_value(value)
        elif key == "created":
            fm.created = value
        elif key == "updated":
            fm.updated = value
        else:
            fm.extra[key] = value

    return fm


def _parse_list_value(value: str) -> list[str]:
    """解析列表值（支持 [a, b, c] 格式）。

    Args:
        value: 值字符串

    Returns:
        list[str]: 解析后的列表
    """
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]

    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _parse_related_value(value: str) -> list[str]:
    """解析 related 字段（提取 [[X]] wikilinks）。

    Args:
        value: 值字符串

    Returns:
        list[str]: 提取的 wikilinks
    """
    return extract_wikilinks(value)


def extract_wikilinks(content: str) -> list[str]:
    """提取内容中的所有 wikilinks [[X]]。

    Args:
        content: Markdown 内容

    Returns:
        list[str]: 提取的 wikilinks（去重，保持顺序）
    """
    links = []
    seen = set()

    i = 0
    while i < len(content) - 1:
        if content[i] == "[" and content[i + 1] == "[":
            # 找到 ]]
            end_idx = content.find("]]", i + 2)
            if end_idx != -1:
                inner = content[i + 2 : end_idx]
                # 处理 [[X|Y]] 格式，取 X
                if "|" in inner:
                    inner = inner.split("|")[0]
                inner = inner.strip()
                if inner and inner not in seen:
                    links.append(inner)
                    seen.add(inner)
                i = end_idx + 2
                continue
        i += 1

    return links


def serialize(doc: ParsedDoc) -> str:
    """序列化 ParsedDoc 为 Markdown 字符串。

    Args:
        doc: 解析后的文档

    Returns:
        str: Markdown 字符串
    """
    lines = ["---"]

    if doc.frontmatter.title:
        lines.append(f"title: {doc.frontmatter.title}")
    if doc.frontmatter.page_type:
        lines.append(f"type: {doc.frontmatter.page_type}")
    if doc.frontmatter.tags:
        lines.append(f"tags: [{', '.join(doc.frontmatter.tags)}]")
    if doc.frontmatter.related:
        related_str = " ".join(f"[[{r}]]" for r in doc.frontmatter.related)
        lines.append(f"related: {related_str}")
    if doc.frontmatter.sources:
        lines.append(f"sources: [{', '.join(doc.frontmatter.sources)}]")
    if doc.frontmatter.created:
        lines.append(f"created: {doc.frontmatter.created}")
    if doc.frontmatter.updated:
        lines.append(f"updated: {doc.frontmatter.updated}")

    # 额外字段
    for key, value in doc.frontmatter.extra.items():
        lines.append(f"{key}: {value}")

    lines.append("---")
    lines.append(doc.body)

    return "\n".join(lines)
