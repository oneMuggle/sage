---
name: xhs-white-editorial
kind: deck
description: Clean white editorial magazine style for dense Chinese content posts
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Xhs White Editorial

白底杂志风、强调重点块、macaron soft-card 分组。灵感来自 `20260409 升级版知识库/小红书图文/v2-白底版/slide_01_cover.html` 的顶部彩虹条 + 大字标题，以及 `20260412-AI测试与安全/xhs-ai-testing-safety-v2.html` 的 `.focus` 黑底白字强重点和 macaron 软色卡片系统。

**Visual traits:** 纯白背景、顶部 10 色彩虹条、巨型 80-110px 标题配轻微负字距、渐变 brand 文字（紫→蓝→绿→橙→粉）、macaron 软色卡（soft-purple / pink / blue / green / orange）、胶囊 tag + dot、黑底 `.focus` 强调框、hero quote box 带淡阴影。

**Use when:** 你需要一份能当小红书图文、也能当横屏 deck 用的白底内容帖；文字多、重点密集、需要一眼抓住关键词；面向中文读者为主。

**Path:** `templates/full-decks/xhs-white-editorial/index.html`

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
