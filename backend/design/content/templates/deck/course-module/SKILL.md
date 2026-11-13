---
name: course-module
kind: deck
description: Educational course module with structured lessons
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Course Module

7-slide teaching module: cover (title + meta), objectives, core concept, worked example, exercise, check-your-understanding (MCQ), summary.

Academic but friendly look: warm off-white paper, Playfair Display display type, a green/terracotta accent pair. A persistent **left sidebar** on content slides lists the module's learning objectives and checks them off as you progress — students always know where they are.

**Use when:** online course modules, lecture handouts, onboarding curricula, workshop units.
**Feel:** a good textbook opened to a chapter — structured, quiet, encouraging.

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
