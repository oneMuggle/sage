"""待办多标签：清洗、序列化、解析与聚合。

``todos.tags`` 存 JSON 数组字符串（如 ``["工作","论文"]``）。标签过滤走
``tags LIKE '%\"tag\"%'``，因此清洗时剔除引号/反斜杠/LIKE 通配符，保证
匹配语义不被破坏。空标签列表存 NULL。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

# 多标签上限与单标签长度上限（本地 personal todo 场景的合理护栏）。
MAX_TAGS = 10
MAX_TAG_LENGTH = 32


def normalize_tags(tags: Optional[List[str]]) -> List[str]:
    """清洗标签：去空白、去重、过滤 LIKE 特殊字符、截断长度与数量。"""
    if not tags:
        return []
    cleaned: List[str] = []
    seen = set()
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()
        for ch in ('"', "\\", "%", "_"):
            tag = tag.replace(ch, "")
        tag = tag[:MAX_TAG_LENGTH].strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def dump_tags(tags: Optional[List[str]]) -> Optional[str]:
    """序列化为 JSON 数组字符串；空标签存 NULL（省空间、过滤更直观）。"""
    normalized = normalize_tags(tags)
    return json.dumps(normalized, ensure_ascii=False) if normalized else None


def parse_tags(tags_raw: Optional[str]) -> List[str]:
    """反序列化行内 tags；坏数据降级为空列表（不阻塞列表渲染）。"""
    try:
        parsed = json.loads(tags_raw) if tags_raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(t) for t in parsed]


def aggregate_tag_counts(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """把 ``SELECT tags ...`` 的结果聚合为 ``[{tag, count}]``（次数降序）。"""
    counts: Dict[str, int] = {}
    for row in rows:
        for tag in parse_tags(row[0]):
            counts[tag] = counts.get(tag, 0) + 1
    return [
        {"tag": tag, "count": count}
        for tag, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
