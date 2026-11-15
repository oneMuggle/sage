# 模板规则抽取优化：补充特殊样式段落格式

> **状态**: 进行中  
> **创建**: 2026-11-15  
> **分支**: feat/template-rule-paragraph-format

## 背景与目标

当前模板规则抽取只抽取了 **字体规则** (`style.font`) 覆盖标题和特殊样式（作者/摘要/图题/表题/参考文献等），但**段落格式规则** (`style.paragraph`) 只针对 Normal 正文样式抽取。

实际模板中，标题和特殊样式都有重要的段落格式属性：
- Heading 1: 居中对齐、4倍行距
- 作者: 居中对齐
- 图题/表题: 居中对齐、段前段后间距
- 参考文献: 居中对齐、双倍行距

**目标**: 补全这些特殊样式的段落格式规则，预期从 24 条规则扩展到 ~40 条。

## 涉及的文件与模块

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `backend/office/word_rule_extract_template.py` | 修改 | 扩展 `_extract_heading_styles` 和 `_extract_special_styles` 函数 |
| `backend/office/doc_profile.py` | 检查 | 确认样式数据包含段落格式字段 |

## 技术方案

### 当前实现分析

```python
# _extract_heading_styles (line 226-268)
# 只抽取字体属性
for field_name in ("font_ascii", "font_east_asia", "size_pt", "bold", "italic"):
    if style.get(field_name) is not None:
        params[field_name] = style[field_name]
add_candidate(candidates, "style.font", params, ...)

# _extract_special_styles (line 271-302)
# 同样只抽取字体属性
```

### 优化方案

为每个 Heading 和特殊样式**同时生成** `style.font` 和 `style.paragraph` 两条规则（如果该样式有段落格式属性）。

```python
# 段落格式字段
PARAGRAPH_FIELDS = (
    "alignment",           # LEFT/CENTER/RIGHT/JUSTIFY
    "line_spacing",        # 倍数行距
    "line_spacing_pt",     # 固定行距(pt)
    "space_before_pt",     # 段前间距
    "space_after_pt",      # 段后间距
    "first_line_indent_cm",  # 首行缩进
    "left_indent_cm",      # 左缩进
)

# 为每个样式生成 style.paragraph 规则
para_params = {"style": style_label}
for field in PARAGRAPH_FIELDS:
    if style.get(field) is not None:
        para_params[field] = style[field]
if len(para_params) > 1:  # 有段落格式属性
    add_candidate(candidates, "style.paragraph", para_params, ...)
```

## 实施步骤

- [x] 1. 检查 `doc_profile.py` 确认样式数据包含段落格式字段
- [x] 2. 修改 `_extract_heading_styles` 增加段落格式抽取
- [x] 3. 修改 `_extract_special_styles` 增加段落格式抽取
- [x] 4. 添加单元测试验证新规则生成
- [x] 5. 用论文模板验证实际效果

## 实施结果

- **规则总数**: 24 → 39 条 (+62%)
- **段落格式规则**: 1 → 16 条
- 新增样式: Heading 1-9, 页眉, 参考文献, 作者, 图题, 表题, 作者(英文), 表文字
- 所有 12 个单元测试通过

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| `doc_profile.py` 未返回段落格式字段 | 无法抽取 | 先检查数据源，必要时扩展 |
| 规则合并冲突 | 同一样式多条规则可能冲突 | 使用 `style` 字段区分 |
| 前端显示兼容 | 新规则类型需要前端支持 | `style.paragraph` 已有支持 |

## 依赖

- 无外部依赖
- 需要确保 `doc_profile.py` 返回的 `styles` 列表包含段落格式字段
