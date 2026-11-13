---
name: graphify-dark-graph
kind: deck
description: Deep-night theme with force-directed graph backdrop and glass cards
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Graphify Dark Graph

Deep-night 暗底 + 力导向知识图谱覆盖层 + 温暖玻璃拟态卡片。灵感来自 `20260413-graphify/ppt/graphify.html` 的 `#06060c` 渐变底、飘移 orb 光晕、glass 卡片（warm/blue/green/purple 五变体）和 rainbow-text 标题。

**Visual traits:** `#06060c → #0e1020` 斜向渐变、三颗 400-520px blur orb 慢飘动、cover SVG 力导向图谱作为背景、rainbow shift 渐变标题、JetBrains Mono 的 `.cmd-glow` 命令行、玻璃拟态卡片带顶部高光和微妙内阴影、温暖色系 accent (#e8a87c 琥珀 / #7ed3a4 薄荷 / #7eb8da 雾蓝 / #b8a4d6 丁香).

**Use when:** 介绍一个开发者工具、命令行产品、知识图谱 / 数据可视化相关项目；你希望现场演示时视觉有「AI native + 科技感 + 温度」。

**Path:** `templates/full-decks/graphify-dark-graph/index.html`

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
