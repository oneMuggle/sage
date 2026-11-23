"""Word 命名样式预设（样式模板的「画像」形态）。

把常见中文排版规范（通用报告 / 党政机关公文 GB/T 9704 / 学术论文）
固化为可复用的 ``WordFormatSpec``：

- ``list_style_presets()`` 供 REST / 前端 / LLM 工具发现可用预设；
- ``get_style_preset()`` 返回预设规范；
- ``resolve_effective_format_spec()`` 把「预设 + 显式 format_spec」深合并
  为最终规范：逐字段合并，None 不覆盖，显式字段优先。

约定：预设只覆盖样式子模型（page/body/title/headings/caption/table_text/
header/footer），不设置 numbering/toc 等生成期开关——这些仍由显式
format_spec 控制。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .errors import OfficeGenerateError
from .models import WordFormatSpec

#: 内置预设原始数据（模块导入时经 WordFormatSpec 校验，fail fast）
_PRESET_DATA: Dict[str, Dict[str, Any]] = {
    "default": {
        "name": "默认版式",
        "description": "沿用生成器历史默认（宋体/Times New Roman、默认页边距），不额外指定样式。",
        "spec": {},
    },
    "report": {
        "name": "通用报告",
        "description": "A4 公文式报告：正文宋体 12pt、1.5 倍行距；各级标题黑体；题注宋体 10.5pt。",
        "spec": {
            "page": {
                "size": "A4",
                "margins_cm": {"top": 2.54, "bottom": 2.54, "left": 3.18, "right": 3.18},
            },
            "body": {
                "font_family": "宋体",
                "ascii_font": "Times New Roman",
                "font_size_pt": 12,
                "line_spacing": 1.5,
            },
            "title": {
                "font_family": "黑体",
                "font_size_pt": 22,
                "bold": True,
                "align": "center",
            },
            "headings": {
                "h1": {"font_family": "黑体", "font_size_pt": 16, "bold": True},
                "h2": {"font_family": "黑体", "font_size_pt": 14, "bold": True},
                "h3": {"font_family": "黑体", "font_size_pt": 12, "bold": True},
                "h4": {"font_family": "黑体", "font_size_pt": 12, "bold": True},
                "h5": {"font_family": "黑体", "font_size_pt": 12, "bold": True},
            },
            "caption": {
                "font_family": "宋体",
                "ascii_font": "Times New Roman",
                "font_size_pt": 10.5,
            },
        },
    },
    "gb9704-gongwen": {
        "name": "党政机关公文（GB/T 9704）",
        "description": (
            "A4 纵向，上 3.7 / 下 3.5 / 左 2.8 / 右 2.6cm；正文仿宋_GB2312 三号"
            "（16pt）固定行距 28 磅、首行缩进 1.1cm、两端对齐；标题宋体小标宋 22pt；"
            "一级标题黑体、二级标题楷体_GB2312、三级以下仿宋加粗；页脚居中页码。"
        ),
        "spec": {
            "page": {
                "size": "A4",
                "orientation": "portrait",
                "margins_cm": {"top": 3.7, "bottom": 3.5, "left": 2.8, "right": 2.6},
            },
            "body": {
                "font_family": "仿宋_GB2312",
                "ascii_font": "Times New Roman",
                "font_size_pt": 16,
                "line_spacing_pt": 28,
                "first_line_indent_cm": 1.1,
                "align": "justify",
            },
            "title": {
                "font_family": "方正小标宋简体",
                "font_size_pt": 22,
                "align": "center",
            },
            "headings": {
                "h1": {"font_family": "黑体", "font_size_pt": 16},
                "h2": {"font_family": "楷体_GB2312", "font_size_pt": 16},
                "h3": {"font_family": "仿宋_GB2312", "font_size_pt": 16, "bold": True},
                "h4": {"font_family": "仿宋_GB2312", "font_size_pt": 16, "bold": True},
                "h5": {"font_family": "仿宋_GB2312", "font_size_pt": 16, "bold": True},
            },
            "caption": {"font_family": "楷体_GB2312", "font_size_pt": 10.5},
            "footer": {"page_number": True, "align": "center"},
        },
    },
    "academic-thesis": {
        "name": "学术论文（通用）",
        "description": "A4 学位/期刊论文通用版式：正文宋体 12pt、1.5 倍行距；三级以内标题黑体；题注宋体 10.5pt。",
        "spec": {
            "page": {
                "size": "A4",
                "margins_cm": {"top": 2.5, "bottom": 2.5, "left": 3.0, "right": 2.5},
            },
            "body": {
                "font_family": "宋体",
                "ascii_font": "Times New Roman",
                "font_size_pt": 12,
                "line_spacing": 1.5,
            },
            "title": {
                "font_family": "黑体",
                "font_size_pt": 22,
                "bold": True,
                "align": "center",
            },
            "headings": {
                "h1": {"font_family": "黑体", "font_size_pt": 15, "bold": True},
                "h2": {"font_family": "黑体", "font_size_pt": 14, "bold": True},
                "h3": {"font_family": "黑体", "font_size_pt": 12, "bold": True},
                "h4": {"font_family": "黑体", "font_size_pt": 12},
                "h5": {"font_family": "黑体", "font_size_pt": 12},
            },
            "caption": {
                "font_family": "宋体",
                "ascii_font": "Times New Roman",
                "font_size_pt": 10.5,
            },
        },
    },
}

#: id → (name, description, validated spec)
_PRESETS: Dict[str, Tuple[str, str, WordFormatSpec]] = {
    preset_id: (
        str(raw["name"]),
        str(raw["description"]),
        WordFormatSpec(**raw["spec"]),
    )
    for preset_id, raw in _PRESET_DATA.items()
}


def list_style_presets() -> List[Dict[str, str]]:
    """列出内置预设元信息（id/name/description），供 REST/工具发现。"""
    return [
        {"id": preset_id, "name": name, "description": description}
        for preset_id, (name, description, _spec) in _PRESETS.items()
    ]


def get_style_preset(preset_id: str) -> Optional[WordFormatSpec]:
    """按 id 取预设规范；未知 id 返回 None（不抛错，供探测场景）。"""
    entry = _PRESETS.get(preset_id)
    return entry[2] if entry is not None else None


def _model_field_names(model: BaseModel) -> List[str]:
    """pydantic v2 (model_fields) / v1 (__fields__) 兼容的字段名列表。"""
    fields = getattr(type(model), "model_fields", None)
    if fields is None:
        fields = type(model).__fields__
    return list(fields.keys())


def _merge_value(base: Any, override: Any) -> Any:
    """逐字段深合并：override 为 None 时保留 base；模型/dict 递归合并。"""
    if override is None:
        return base
    if base is None:
        return override
    if isinstance(base, BaseModel) and isinstance(override, BaseModel):
        return _merge_models(base, override)
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge_value(merged.get(key), value)
        return merged
    return override


def _merge_models(base: BaseModel, override: BaseModel) -> BaseModel:
    data = {
        name: _merge_value(getattr(base, name), getattr(override, name))
        for name in _model_field_names(base)
    }
    return type(base)(**data)


def resolve_effective_format_spec(
    preset_id: Optional[str], spec: Optional[WordFormatSpec]
) -> Optional[WordFormatSpec]:
    """解析最终生效的样式规范。

    - 无预设：原样返回 spec（None 保持生成器历史行为）；
    - 仅预设：返回预设规范；
    - 预设 + 显式 spec：逐字段深合并，显式字段优先；
    - 未知预设：抛 OfficeGenerateError（请求级错误，不静默降级）。
    """
    if preset_id is None:
        return spec
    entry = _PRESETS.get(preset_id)
    if entry is None:
        available = ", ".join(sorted(_PRESETS))
        raise OfficeGenerateError(
            f"unknown_style_preset: {preset_id!r}（可用：{available}）"
        )
    base = entry[2]
    if spec is None:
        return base
    return _merge_models(base, spec)


__all__ = [
    "get_style_preset",
    "list_style_presets",
    "resolve_effective_format_spec",
]
