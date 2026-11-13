# Design Studio 内容库与 Craft 工艺规范

> 代码位置：`backend/design/`
> 内容位置：`backend/design/content/`

## 1. 架构总览

Design Studio 采用 **四平面可组合架构**：

| 平面 | 内容 | 加载器 |
|------|------|--------|
| 设计系统 | `content/systems/<id>/{manifest.json,DESIGN.md,tokens.css}` | `DesignSystemRegistry` |
| 模板 | `content/templates/<kind>/<id>/SKILL.md`（+ 可选 `example.html` / `assets/`） | `DesignTemplateRegistry` |
| 工艺规范 | `content/craft/*.md` | `CraftRuleRegistry` |
| 生成 | `PromptComposer` → `DesignGenerator` → `StandaloneBundler` | — |

`kind` 取值为 `prototype`（Web 原型）或 `deck`（幻灯片）。

## 2. Prompt 组装顺序

`PromptComposer.compose()` 按下列顺序拼接：

1. 基础指令（输出 `<artifact>` 包裹的完整 HTML）
2. 品牌设计规范（`DESIGN.md`）
3. CSS 变量（`tokens.css`）
4. 模板生成指令（`SKILL.md`）
5. **工艺规范（`## 工艺规范（必须遵守）`）** — 按 `priority` 升序逐个注入
6. 用户需求（brief）
7. 迭代上下文（仅 `iterate` 时追加当前 HTML + 用户反馈）

Craft 段仅在传入 `craft_rules` 时出现；未传入时 prompt 与旧版逐字一致。

## 3. Craft 规则格式

```markdown
---
id: anti-ai-slop
name: Anti-AI-Slop
description: Reject the visual tells of machine-generated design.
applies_to: both        # both | prototype | deck
priority: 0             # 升序注入
---

# 正文（Markdown）
```

`CraftRuleRegistry.rules_for_kind(kind)` 返回 `applies_to` 为 `both` 或等于该 kind 的规则，并按 `priority` 升序排列。

内置 5 条规范：

| id | 作用 |
|----|------|
| `anti-ai-slop` | P0 拒绝项：默认 indigo、信任渐变、emoji 图标、捏造指标 |
| `typography-hierarchy` | 乘法字阶、字重对比、行高与字距 |
| `color-usage` | 70-20-10 结构、强调色节制、对比度下限 |
| `animation-discipline` | 动效何时成立、时长与缓动、`prefers-reduced-motion` |
| `checklist` | 交付前 P0/P1/P2 自检清单 |

## 4. 注入链路

```
main.py (lifespan)
  └─ CraftRuleRegistry(content_dir)
       └─ DesignStudio(craft_rules=registry)
            ├─ _craft_for(template) → registry.rules_for_kind(template.kind)
            └─ DesignGenerator.generate(..., craft_rules=rules)
                 └─ PromptComposer.compose(..., craft_rules=rules)
```

`craft_rules` 参数在 `DesignStudio` / `DesignGenerator` / `PromptComposer` 三处均为可选，默认 `None`，因此现有调用方与测试无需改动。

## 5. 健壮性约定

- 单个 craft 文件不可读（非 UTF-8 / IO 错误）→ 跳过该文件，不抛异常。
- frontmatter `priority` 非整数（如 `high`）→ 回退为 `99`（排在最后）。
- 多个文件的 frontmatter `id` 重复 → 以 `id` 去重，只保留一个。
- 正文开头的 H1 若重复 `name` 会被剥离，避免 prompt 中出现重复标题。
- 空 frontmatter（`---\n---`）→ 使用文件名 stem 作为 id。

## 6. 内容清单（2026-11-11 扩充后）

| 类型 | 数量 | 条目 |
|------|------|------|
| 设计系统 | 7 | corporate, minimal, editorial, tech-dark, academic, startup, data-report |
| Deck 模板 | 5 | pitch-deck, editorial-magazine, swiss-grid, tech-sharing, weekly-report |
| 原型模板 | 4 | landing-page, dashboard, pricing, docs-page |
| Craft 规范 | 5 | 见上表 |

## 7. 扩展方式

- **新增设计系统**：在 `content/systems/<id>/` 放置 `manifest.json`（含 `id/name/category/description/tags`）+ `DESIGN.md` + `tokens.css`，无需改代码。
- **新增模板**：在 `content/templates/<kind>/<id>/` 放置 `SKILL.md`（frontmatter 必含 `name/kind/description/design_system_required`），可选 `example.html` 与 `assets/*.css|*.js`。
- **新增 craft 规则**：在 `content/craft/` 放置 `<id>.md`，frontmatter 必含 `id/name/applies_to/priority`。正文会整体进入 prompt，建议单文件 < 2KB；若某规则只适用于某类产物，用 `applies_to: deck|prototype` 缩小注入面。

## 8. 导出管道（2026-11-13 新增）

Design Studio 支持将生成的 HTML 产物导出为可交付文件格式：

| 格式 | 实现 | 降级策略 |
|------|------|----------|
| **PDF** | LibreOffice headless（`soffice --convert-to pdf`） | reportlab 直绘（纯文本，无复杂布局） |
| **ZIP** | `zipfile` 打包 `index.html` | 无降级（ZIP 始终可用） |
| **HTML** | 原样返回 bundled HTML | 无降级 |

### 8.1 架构

```
POST /api/v1/design/projects/{id}/export
Body: { "format": "pdf" | "zip" | "html" }
  ↓
design_routes.export_artifact()
  ↓
DesignExporter.export(html, output_dir, format)
  ↓
  ├─ PDF → _convert_with_libreoffice() → 失败 → _convert_with_reportlab()
  ├─ ZIP → _export_zip() (zipfile)
  └─ HTML → 直接返回 html_content
```

### 8.2 API

```python
POST /api/v1/design/projects/{project_id}/export
Body: { "format": "pdf" | "zip" | "html" }
Response:
  - format=html: { ok, format, html_content }
  - format=pdf/zip: { ok, format, file_path }
```

### 8.3 LLM 工具

`design_export` 工具新增 `format` 参数（默认 `"html"`，向后兼容）：

```python
design_export(project_id="abc", format="pdf")
# → { file_path: "/workspace/design/abc/v1.pdf", format: "pdf" }
```

### 8.4 LibreOffice 定位

复用 `backend.office.export_pdf._locate_soffice()`，检测顺序：
1. `SAGE_SOFFICE_PATH` 环境变量
2. `shutil.which("soffice")`
3. 平台特定安装路径（Windows/macOS/Linux）

若未找到 soffice，自动降级到 reportlab（仅支持纯文本渲染）。

### 8.5 测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_design_export.py -v
```

覆盖：PDF/ZIP/HTML 三种格式、soffice 缺失降级、超时处理、Unicode 内容、大文件。

## 9. Design Lint 引擎（2026-11-13 新增）

`DesignLinter` 检测生成产物中的 AI 设计"痕迹"（anti-patterns），分 P0（必须修）和 P1（建议修）两级。

### 9.1 规则清单

| 级别 | 规则 ID | 检测内容 |
|------|---------|----------|
| **P0** | `no_default_indigo` | AI 常用 indigo 色板（#6366f1, #4f46e5 等 8 色） |
| **P0** | `no_trust_gradient` | 紫→蓝渐变（"trust gradient"） |
| **P0** | `no_emoji_icons` | Emoji 用作图标（✨🚀🎯 等） |
| **P0** | `no_invented_metrics` | 捏造指标（"10x faster", "99.9% uptime"） |
| **P0** | `no_filler_copy` | 占位文案（"lorem ipsum", "feature one"） |
| **P1** | `no_ai_card_shape` | AI 典型卡片（大圆角 + 彩色左边框） |
| **P1** | `no_ai_buzzwords` | AI 流行语（"seamless", "cutting-edge"） |

### 9.2 架构

```
DesignGenerator.generate()
  └─ html_content = LLM 输出
       └─ DesignLinter.lint(html_content)
            ├─ LintReport.ok == True → 直接返回
            └─ LintReport.ok == False → auto_fix() + generate_feedback()
                 └─ 反馈注入到 iterate prompt → 重试一次
```

### 9.3 API

```python
from backend.design.lint import DesignLinter

linter = DesignLinter()
report = linter.lint(html_content)

if not report.ok:
    # 自动修复可修复的问题（如 indigo → slate）
    fixed_html = linter.auto_fix(html_content, report.issues)
    # 生成 LLM 可理解的反馈
    feedback = linter.generate_feedback(report)
```

### 9.4 测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_design_lint.py -v
```

覆盖：7 条规则的正例/反例（34 个测试），`LintReport` 模型，`auto_fix` 颜色替换，`generate_feedback` 反馈生成。

## 10. HTML → PPTX 结构化映射（2026-11-13 新增）

`backend/design/pptx_mapper.py` 提供 `HtmlToPptxMapper`：

- 解析 `<section class="slide">` → h1/h2（标题/副标题）→ p/ul/ol（正文与列表）→ img（仅记录 src）
- 每个 section 映射为一张空白版式幻灯片（`slide_layouts[6]`），标题 36pt / 副标题 24pt / 正文 18pt
- `PPTX_AVAILABLE=False` 时构造器抛错；`DesignExporter._export_pptx()` 捕获后回落到 `soffice --convert-to pptx`
- 导出端点与 `design_export` 工具均接受 `format="pptx"`

失败降级顺序：python-pptx 映射 → LibreOffice 转换 → 返回明确错误（两者皆不可用时）。

## 11. 前端设计工作台（2026-11-13 新增）

页面 `/design`（`src/pages/DesignStudio.tsx`），侧栏「工具」组入口：

| 层 | 文件 | 职责 |
|---|---|---|
| 类型 | `src/entities/design/types.ts` | `DesignSystem` / `DesignTemplate` / `DesignProject` / `DesignArtifact` / `DesignProjectDetail` |
| API | `src/entities/design/designApi.ts` | `backendRequest` 封装；generate/iterate 以 `responseType: 'text'` 读取 SSE 并解析 `complete` / `error` 事件 |
| Store | `src/entities/design/designStore.ts` | 元数据、项目列表、当前项目/产物、生成与迭代状态 |
| 页面 | `src/pages/DesignStudio.tsx` | 列表 / 向导 / 详情三视图切换 |
| 特性 | `src/features/design/*` | 项目卡片网格、4 步创建向导、生成视图（`HtmlPreviewHost` 预览 + 迭代聊天）、导出面板 |

要点：

- 生成/迭代端点是 SSE，Electron IPC relay 会等响应完成后以 text 返回，前端一次性解析；UI 在等待期间显示生成中状态
- 预览复用 `HtmlPreviewHost` 的 sandbox 隔离（桌面端 `sage-preview://`，Web/测试回落 `srcDoc`）
- 导出面板支持 PDF / PPTX / ZIP / HTML；HTML 走浏览器 Blob 下载，其余显示后端落盘路径
- 版本历史暂以当前版本徽章呈现（后端尚未暴露产物列表端点）

## 12. 测试（Craft 相关）

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_craft_loader.py \
  backend/tests/unit/test_prompt_composer.py \
  backend/tests/unit/test_design_generator.py \
  backend/tests/unit/test_design_studio.py \
  backend/tests/unit/test_design_routes.py \
  backend/tests/unit/test_design_tools.py -q
```

`test_craft_loader.py` 覆盖：frontmatter 解析、缺省/空 frontmatter 回退、非法与带引号的 priority、H1 去重、按 priority 排序、缺失目录、按 kind 过滤、不可读文件跳过、id 去重、缓存行为。

## 13. 来源说明

系统/模板/craft 内容为原创撰写，遵循 OpenDesign 的四平面架构模式，未逐字复制其文本，故未附加 Apache 2.0 NOTICE。
