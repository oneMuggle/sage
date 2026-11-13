---
name: obsidian-claude-gradient
kind: deck
description: GitHub-dark theme with purple ambient glow and gradient display text
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Obsidian Claude Gradient

GitHub-dark (`#0d1117`) + 紫色 ambient radial + 60px 遮罩网格 + 紫→蓝→绿渐变文字。灵感来自 `20260406-obsidian-claude/slides.html` 的 `--accent #7c3aed`、`.cbg` 双 radial cover、`.cgrid` 60px 遮罩网格以及 `.g` 三停渐变。

**Visual traits:** 深灰蓝底 + 紫蓝 radial 晕染 + 暗网格遮罩、居中对齐的标题/正文、圆角紫色 pill tag、linear `#a855f7→#60a5fa→#34d399` 渐变字、GitHub-ish 代码色 (`#010409` 背景 + 紫/蓝/橙/绿 token)、紫色左边框 highlight 块、简洁 step 列表。

**Use when:** 讲一个开发者友好的工作流、MCP / Agent / Dev tool 教程；你希望气质接近 GitHub Blog / Linear Changelog；内容以配置文件 + 步骤为主。

**Path:** `templates/full-decks/obsidian-claude-gradient/index.html`

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
