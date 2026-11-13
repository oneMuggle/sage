---
name: hermes-cyber-terminal
kind: deck
description: Cyberpunk terminal-style presentation for developer tool reviews
design_system_required: false
source: open-design html-ppt (Apache 2.0)
---

# Hermes Cyber Terminal

黑底 (`#0a0c10`) + 终端 chrome + 扫描线 + 薄荷绿 glow 大字 + JetBrains Mono 全文打字机感。灵感来自 `20260414-hermes-agent/ppt/hermes-record.html` 的 `codebox #15151b` 深色代码盒和 `hermes-vs-openclaw.html` 的实测对比气质 —— 把两者合成一份「honest cyber review」。

**Visual traits:** 56px cyber 网格 + CRT vignette + 半透明 scanlines 叠层、窗口 traffic-light chrome、`$ prompt` 开头的 command-line 标题、薄荷绿 text-shadow glow `#7ed3a4`、monospace 全局、虚拟 bar chart 用 stroke-only 呈现、blinking cursor、amber/green/red 分级标签。

**Use when:** 评测一个开发者工具 / CLI / agent，展示跑分数据、trace、diff；想要即刻给出「技术人 honest review」的视觉语气；适合长 trace / long code 的场景。

**Path:** `templates/full-decks/hermes-cyber-terminal/index.html`

## 生成要求

- 保持本模板的视觉语言（配色 / 字体气质 / 布局节奏），不要替换成通用 AI 风格
- 完整自包含 HTML：内联 CSS，必要时内联 JS，无外部依赖
- 内容用真实文案，禁止 lorem ipsum 与占位符
- 幻灯片为全视口 `<section>`，垂直堆叠、滚轮吸附、方向键翻页
- 字体加载失败时回退到系统无衬线/衬线，不能破版
