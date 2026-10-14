"""Compose system prompts for design generation."""
from __future__ import annotations

from typing import Optional

from backend.design.models import DesignSystem, DesignTemplate

_BASE_INSTRUCTIONS = """\
你是一个专业的 HTML/CSS 设计专家。根据用户的设计需求和品牌规范，\
生成高质量的 HTML 页面。

## 输出格式要求
将生成的完整 HTML 包裹在 <artifact> 标签中：
<artifact identifier="{identifier}" type="text/html" title="{title}">
<!DOCTYPE html>
<html>
...完整 HTML 文档...
</html>
</artifact>

## 通用设计原则
- 使用语义化 HTML5 标签
- CSS 使用 Flexbox/Grid 布局
- 响应式设计（mobile-first）
- 无障碍基础（aria 属性、语义化标签）
- 所有颜色/间距/字体使用 design system 的 CSS 变量
"""

_ITERATION_ADDENDUM = """\

## 当前版本 HTML
```html
{current_html}
```

## 用户修改要求
{user_feedback}

请基于当前 HTML 进行修改，保持整体结构不变，仅修改用户要求的部分。
输出修改后的完整 HTML（同样使用 <artifact> 标签包裹）。
"""


class PromptComposer:
    """Assemble system prompts from design system + template + brief."""

    @staticmethod
    def compose(
        design_system: DesignSystem,
        template: DesignTemplate,
        brief: str,
        iteration_context: Optional[dict] = None,
    ) -> str:
        """Compose a complete system prompt for design generation."""
        identifier = template.id
        title = template.name

        parts = [
            _BASE_INSTRUCTIONS.format(
                identifier=identifier, title=title,
            ),
            "",
            "## 品牌设计规范",
            design_system.design_md,
            "",
            "## CSS 变量定义",
            "```css",
            design_system.tokens_css,
            "```",
            "",
            "## 模板生成指令",
            template.skill_md,
            "",
            "## 用户需求",
            brief,
        ]

        if iteration_context:
            parts.append(
                _ITERATION_ADDENDUM.format(
                    current_html=iteration_context.get("current_html", ""),
                    user_feedback=iteration_context.get("user_feedback", ""),
                )
            )

        return "\n".join(parts)
