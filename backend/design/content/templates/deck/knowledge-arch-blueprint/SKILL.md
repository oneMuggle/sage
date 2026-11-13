---
name: knowledge-arch-blueprint
kind: deck
description: Architecture blueprint style for technical whitepaper-style decks
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Knowledge Arch Blueprint

奶油纸 (`#F0EAE0`) 底 + 锈红 (`#B5392A`) 单一 accent + 硬黑描边卡片 + 虚线反馈回路箭头。灵感来自 `20260405 架构图v2.html` —— 那是一张真正的「技术白皮书架构图」，像建筑蓝图。

**Visual traits:** 暖米色纸底、微弱 48px 网格做 blueprint 感、硬朗 2px 黑边卡片、pipeline step-box 一字排开配 hero box 凸起、右上 insight 红色 callout、大小写 kicker 2.5-4px 字距、SVG 反馈回路虚线 + 箭头、Playfair 大字号衬线数据、无渐变无阴影极度克制。

**Use when:** 讲系统架构、数据流向、流程拆解；你想让内容看起来像一份正经技术白皮书而不是营销贴；需要严肃感、印刷感、可直接截图塞进 README。

**Path:** `templates/full-decks/knowledge-arch-blueprint/index.html`

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
