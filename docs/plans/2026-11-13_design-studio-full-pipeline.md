# Design Studio 全链路能力扩充方案（M1–M5）

> **状态：** 计划中
> **日期：** 2026-11-13
> **分支：** `feat/design-studio-pipeline`
> **基线：** origin/main `3699ee1bb`（已含 PR #3033 设计工作室内容库扩充 + Craft 工艺规范层）
> **范围：** M1 导出闭环 → M5 Office 融合 + Live Artifact 全量

---

## 0. TL;DR

在 PR #3033 完成的设计工作室内容库扩充基础上（7 系统 + 9 模板 + 5 craft），继续推进 5 个里程碑，把 Design Studio 从"能生成 HTML 预览"升级为"**可交付真文件、可前端使用、可与 Office 深度编辑互通**"的完整创作平台。

| 里程碑 | 内容 | 预估规模 | 独立可发布 |
|--------|------|----------|------------|
| **M1** | 导出闭环：HTML → PDF / ZIP（复用 soffice） | ~400 行 | ✅ |
| **M2** | 内容库扩容（15+ 系统、html-ppt 主题库）+ 设计产物 lint | ~2k 行 | ✅ |
| **M3** | HTML → PPTX 结构化映射（python-pptx） | ~1.5k 行 | ✅ |
| **M4** | 前端 `/design` 工作台（iframe 预览 + 迭代聊天） | ~3k 行 | ✅ |
| **M5** | Office ↔ Design 融合 + Live Artifact | ~3k 行 | ✅ |

每个里程碑一个独立 PR，可单独评审/合并/回滚。

---

## 1. 背景与目标

### 1.1 背景

PR #3033 完成后，Design Studio 现状：

- ✅ 后端架构完整（DesignSystemRegistry / TemplateRegistry / CraftRuleRegistry / PromptComposer / DesignGenerator / Bundler / DesignStudio 编排器）
- ✅ 内容库初具规模（7 系统 / 9 模板 / 5 craft 规范）
- ✅ LLM 工具调用链路完整（design_generate / iterate / export / list_*）
- ❌ **产物只能以 HTML 形式返回，无法导出真文件（PDF/PPTX/ZIP）**——最大断点
- ❌ **无前端工作台**——用户只能通过 LLM 工具触发，不可视
- ❌ **Office 与 Design 链路割裂**——HTML deck 无法变成 .pptx，Word 报告也无法驱动 deck 生成
- ❌ **内容库仍单薄**——相比 open-design 154 系统 / 116 模板，差距明显

### 1.2 目标

按 MoSCoW 排序：

| 优先级 | 目标 |
|--------|------|
| **Must** | M1：HTML → PDF / ZIP 导出（复用 soffice，最小可用） |
| **Must** | M3：HTML → PPTX 结构化映射（保留字体/配色/布局） |
| **Should** | M2：内容库扩容到 15+ 系统 + 设计产物 lint（反 AI 味） |
| **Should** | M4：前端 `/design` 工作台（创建/预览/迭代/导出） |
| **Could** | M5a：Office ↔ Design 融合（Word→deck、图表 inline、双向转换） |
| **Could** | M5b：Live Artifact（从数据源刷新重生成） |

### 1.3 非目标

- 不引入云端渲染服务（保持本地优先）
- 不做协同编辑
- 不做设计版本控制（git-like 分支/合并）
- 不做移动端适配（桌面应用即可）

---

## 2. 涉及的文件与模块

### 2.1 新增文件（按里程碑）

**M1：导出闭环**
```
backend/design/export.py                          # 导出核心：HTML→PDF/ZIP
backend/design/pptx_mapper.py                     # (M3) HTML→PPTX 结构化映射
backend/tests/unit/test_design_export.py          # 导出测试
backend/tests/unit/test_pptx_mapper.py            # (M3) 映射测试
```

**M2：内容库扩容 + lint**
```
backend/design/content/systems/<8-13 新系统>/     # 新设计系统
backend/design/content/craft/ai-tell-detector.md  # 新增 AI 味检测 craft
backend/design/lint.py                            # 设计产物 lint
backend/tests/unit/test_design_lint.py            # lint 测试
```

**M3：HTML→PPTX**（见 M1 新增）

**M4：前端工作台**
```
src/pages/DesignStudio.tsx                        # 主页面
src/pages/design/
  ├── DesignLayout.tsx                            # 布局
  └── officeTabs.ts                               # tab 配置
src/features/design/
  ├── DesignProjectsList.tsx                      # 项目列表
  ├── DesignCreateWizard.tsx                      # 创建向导
  ├── DesignGenerationView.tsx                    # 生成视图（SSE + iframe）
  ├── DesignIterationChat.tsx                     # 迭代聊天
  ├── DesignVersionHistory.tsx                    # 版本历史
  ├── DesignExportPanel.tsx                       # 导出面板
  ├── useDesignProjects.ts                        # 项目 hook
  └── useDesignGeneration.ts                      # 生成 hook
src/entities/design/
  ├── designStore.ts                              # store
  └── designApi.ts                                # API client
```

**M5：Office 融合**
```
backend/design/outline_extractor.py               # 从 Word/大纲提取内容
backend/design/chart_embedder.py                  # matplotlib 图 → base64
backend/design/live_artifact.py                   # Live Artifact 引擎
```

### 2.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `backend/api/v1/design_routes.py` | 新增 POST `/projects/{id}/export` 端点 |
| `backend/tools/design_export_tool.py` | 补 `format` 参数 |
| `backend/design/design_studio.py` | 集成 export / lint / outline / live |
| `backend/design/prompt_composer.py` | lint 反馈注入 |
| `src/App.tsx` | 注册 `/design` 路由 |
| `backend/main.py` | lifespan 装配 lint registry / live artifact engine |

---

## 3. 技术方案

### 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  前端 /design 工作台 (M4)                                   │
│  创建向导 ── 生成视图 (iframe 预览) ── 迭代聊天 ── 导出面板  │
└─────────────────────────────────────────────────────────────┘
                              │ REST + SSE
┌─────────────────────────────────────────────────────────────┐
│  Design Studio 编排层                                        │
│  create_project / generate / iterate / export                │
└─────────────────────────────────────────────────────────────┘
                              │
┌───────────┬──────────┬──────────┬──────────┬────────────────┐
│ Prompt    │ Design   │ Lint     │ Export   │ Live Artifact  │
│ Composer  │ Generator│ Engine   │ Pipeline │ Engine (M5b)   │
│ + Craft   │ (LLM)    │ (M2)     │ (M1/M3)  │                │
└───────────┴──────────┴──────────┴──────────┴────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  内容库 + 注册表                                             │
│  DesignSystemRegistry / TemplateRegistry / CraftRegistry     │
│  content/systems/  content/templates/  content/craft/        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  Office 模块（已有）                                         │
│  office_read / office_create / office_update / charts.py     │
│  export_pdf._locate_soffice / ppt_template.py                │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 M1：导出闭环（HTML → PDF / ZIP）

**核心设计**：

```python
# backend/design/export.py

class DesignExporter:
    """Export design artifacts to PDF / ZIP."""

    def __init__(self) -> None:
        self._soffice_lock = threading.Lock()  # 复用 office/export_pdf 的进程锁

    def to_pdf(self, html: str, output_path: Path) -> bool:
        """HTML → PDF via soffice headless.
        Falls back to reportlab if soffice unavailable.
        """
        # 1. 写临时 HTML 文件
        # 2. 调用 soffice --headless --convert-to pdf
        # 3. 超时/失败 → 静默回落 reportlab 直绘（office/export_pdf 既有范式）
        # 4. 返回 True/False

    def to_zip(self, html: str, assets: dict, output_path: Path) -> None:
        """Bundle HTML + assets into self-contained ZIP."""
        # 1. StandaloneBundler.bundle(html, css, assets)
        # 2. zipfile.ZipFile 写入 index.html + 资源
```

**API 端点**：

```python
POST /api/v1/design/projects/{project_id}/export
Body: { "format": "pdf" | "zip" | "html" }
Response:
  - format=html: { "html_content": "...", "file_path": "..." }  # 当前行为
  - format=pdf/zip: { "file_path": "...", "download_url": "file://..." }
```

**工具接口**：

```python
design_export(project_id: str, format: str = "html") -> ToolResult
```

向后兼容：format 默认 "html" 保持现有行为。

### 3.3 M2：内容库扩容 + Design Lint

**内容来源策略**：
- **设计系统**：从 open-design 精选 8-13 个（覆盖：apple/google/airbnb-inspired、financial、medical、government、education），Apache 2.0 保留署名
- **html-ppt 主题**：从 open-design 的 36 主题中精选 8-10 个，保持 tokens.css 格式兼容
- **Craft 新增**：`ai-tell-detector.md` — 硬规则（7 条）+ lint 引擎自动校验

**Design Lint 引擎**：

```python
# backend/design/lint.py

class DesignLinter:
    """Lint a generated HTML design for anti-patterns."""

    RULES = [
        # P0 硬规则（必须修）
        "no_default_indigo",         # #6366f1 / #4f46e5 等
        "no_trust_gradient",         # purple→blue 等
        "no_emoji_icons",            # ✨🚀🎯 等
        "no_invented_metrics",       # "10x faster" / "99.9% uptime"
        "no_filler_copy",            # lorem ipsum / "feature one"
        # P1 软规则（建议修）
        "display_font_matches_seed", # h1/h2 必须用 var(--font-display)
        "no_ai_card_shape",          # 圆角 + 彩色左边框
    ]

    def lint(self, html: str) -> list[LintIssue]:
        """Return list of issues, empty if clean."""

    def auto_fix(self, html: str, issues: list[LintIssue]) -> str:
        """Apply safe fixes (e.g., color replacement)."""
```

**集成**：生成后自动 lint → 若 P0 问题 → 重试一次（将 lint 反馈注入 prompt）→ 最终产物附带 lint 报告。

### 3.4 M3：HTML → PPTX 结构化映射

**核心思路**：解析 HTML deck 的 `<section class="slide">` 结构，映射到 python-pptx。

```python
# backend/design/pptx_mapper.py

class HtmlToPptxMapper:
    """Map HTML deck to PPTX preserving structure and style."""

    def map(self, html: str, output_path: Path) -> None:
        """Parse HTML, create PPTX with matching slides."""
        # 1. BeautifulSoup 解析 HTML
        # 2. 提取 <section class="slide"> 列表
        # 3. 对每个 section：
        #    - 提取标题 (h1/h2) → 标题占位符
        #    - 提取正文 (p, ul, ol) → 内容占位符
        #    - 提取图片 (img) → 图片占位符
        #    - 提取配色 (style/class) → 应用主题色
        # 4. Presentation.save()
```

**降级策略**：若 python-pptx 映射失败，回落到 soffice --convert-to pptx。

### 3.5 M4：前端 /design 工作台

**页面结构**：

```
/design
├── 项目列表（卡片网格 / 列表视图切换）
│   └── 缩略图（首张 slide 截图 / HTML 首屏）
├── 创建向导（4 步）
│   ├── Step 1: 选择 kind（prototype / deck）
│   ├── Step 2: 选择设计系统（卡片网格 + 预览）
│   ├── Step 3: 选择模板（卡片网格 + 预览）
│   └── Step 4: 填写 brief（文本框 + 示例）
├── 生成视图（项目详情页）
│   ├── 左侧：iframe 预览（sandbox, 复用 HtmlPreviewHost）
│   ├── 右侧：迭代聊天（对话式修改）
│   ├── 底部：版本历史时间线
│   └── 顶部：导出按钮（PDF / PPTX / ZIP）
```

**关键实现点**：
- **iframe 预览**：复用 `HtmlPreviewHost`（已有 sandbox 安全隔离）
- **SSE 流式生成**：复用现有 `useDesignGeneration` hook 模式
- **迭代聊天**：类似 Chat 组件，但输入是 feedback 而非消息
- **版本历史**：读取 `design_artifacts` 表的 version 字段

### 3.6 M5：Office ↔ Design 融合

**M5a：Word → Deck**：

```python
# backend/design/outline_extractor.py

class OutlineExtractor:
    """Extract outline from Word document for deck generation."""

    def extract(self, docx_path: Path) -> str:
        """Return structured outline as markdown.
        Uses office_read to parse Word, then summarizes into slide-friendly outline.
        """
```

工作流：`office_read(docx)` → `OutlineExtractor.extract()` → 生成 brief → `design_generate(kind="deck")`

**M5a：图表 inline**：

```python
# backend/design/chart_embedder.py

class ChartEmbedder:
    """Embed matplotlib charts into HTML."""

    def embed(self, figure, html: str) -> str:
        """Convert matplotlib figure to base64 data URL, inject into HTML."""
        # 1. fig.savefig(buffer, format='png')
        # 2. base64.b64encode(buffer.getvalue())
        # 3. 替换 HTML 中的占位符或追加到 <img src="data:image/png;base64,...">
```

**M5a：双向转换**：
- HTML → PPTX：M3 已实现
- PPTX → HTML：复用 `ppt.py` 的读取能力，提取结构化内容 → 生成 HTML deck

**M5b：Live Artifact**：

```python
# backend/design/live_artifact.py

class LiveArtifactEngine:
    """Refresh artifacts from source data."""

    def refresh(self, project_id: str, source_data: dict) -> DesignArtifact:
        """Re-generate artifact with updated data.
        Binds source data (e.g., Excel cells) to template variables,
        then re-runs generation with the same brief + updated data.
        """
```

数据源绑定：
- Excel 文件 → 读取单元格 → 注入模板变量
- JSON 文件 → 读取 → 注入模板变量
- API 响应 → 读取 → 注入模板变量

---

## 4. 实施步骤

### M1：导出闭环（独立 PR）

- [x] **步骤 1**：实现 `backend/design/export.py`（HTML→PDF/ZIP）
  - 复用 `office/export_pdf._locate_soffice`
  - 超时/失败回落 reportlab
  - 单元测试：PDF 生成、ZIP 打包、soffice 缺失回落
- [x] **步骤 2**：新增 API 端点 `POST /design/projects/{id}/export`
  - 参数：format=pdf|zip|html
  - 返回：file_path + download_url
  - 集成测试：端点调用、文件落盘
- [x] **步骤 3**：修改 `design_export` 工具，补 `format` 参数
  - 向后兼容：format 默认 "html"
  - 单元测试：format 参数传递
- [x] **步骤 4**：文档更新（docs/technical/151-design-studio-content-craft.md 补导出章节）
- [ ] **步骤 5**：本地 smoke test + 提交 PR

**验证点**：生成一个 deck → 导出 PDF → 用 PDF 阅读器打开确认内容完整。

### M2：内容库扩容 + Design Lint（独立 PR）

- [x] **步骤 1**：从 open-design 精选 8-13 个设计系统导入
  - 每个系统：manifest.json + DESIGN.md + tokens.css
  - 保留 Apache 2.0 署名
- [x] **步骤 2**：导入 html-ppt 主题库 8-10 个
  - 转换为 Sage 模板格式（SKILL.md + example.html + assets/）
  - 8 个新主题：course-module, presenter-mode-reveal, product-launch, hermes-cyber-terminal, knowledge-arch-blueprint, graphify-dark-graph, xhs-white-editorial, obsidian-claude-gradient
- [x] **步骤 3**：实现 `backend/design/lint.py`
  - 5 条硬规则（P0）+ 2 条软规则（P1）
  - 单元测试：每条规则的正例/反例（34 个测试全部通过）
- [x] **步骤 4**：集成 lint 到生成链路
  - 生成后自动 lint → P0 问题 → 重试一次（注入 lint 反馈）
  - 产物附带 lint 报告（JSON）
  - 抽取 `_apply_lint()` 异步辅助方法，`generate()` 与 `iterate()` 统一调用
- [x] **步骤 5**：文档更新（docs/technical/151 新增 §9 Design Lint 引擎）
- [ ] **步骤 6**：本地 smoke test + 提交 PR

**验证点**：生成 3 个不同系统的 deck → lint 通过率 > 80%。

### M3：HTML → PPTX 结构化映射（独立 PR）

- [ ] **步骤 1**：实现 `backend/design/pptx_mapper.py`
  - BeautifulSoup 解析 HTML
  - 映射 section → slide，h1/h2 → 标题，p/ul/ol → 内容，img → 图片
  - 单元测试：简单 HTML → PPTX
- [ ] **步骤 2**：集成到 export.py
  - `to_pptx(html, output_path)` 调用 pptx_mapper
  - 失败回落 soffice --convert-to pptx
- [ ] **步骤 3**：API + 工具补 format=pptx
- [ ] **步骤 4**：本地 smoke test（生成 deck → 导出 PPTX → PowerPoint 打开验证）
- [ ] **步骤 5**：提交 PR

**验证点**：生成一个 pitch-deck → 导出 PPTX → PowerPoint/WPS 打开确认布局/字体/配色保留。

### M4：前端 /design 工作台（独立 PR）

- [ ] **步骤 1**：创建 `src/entities/design/designApi.ts` + `designStore.ts`
  - API client：list/create/generate/iterate/export
  - Store：项目列表 + 当前项目 + 生成状态
- [ ] **步骤 2**：实现 `src/pages/DesignStudio.tsx` + 布局
  - 项目列表（卡片网格）
  - 创建向导（4 步）
- [ ] **步骤 3**：实现生成视图 + iframe 预览
  - 复用 `HtmlPreviewHost`
  - SSE 流式生成进度
- [ ] **步骤 4**：实现迭代聊天 + 版本历史
  - 对话式 feedback 输入
  - 版本时间线
- [ ] **步骤 5**：实现导出面板
  - 格式选择器（PDF / PPTX / ZIP）
  - 下载按钮
- [ ] **步骤 6**：路由注册 + i18n
  - `src/App.tsx` 注册 `/design`
  - i18n 文案
- [ ] **步骤 7**：本地 smoke test + 提交 PR

**验证点**：用户可以从 `/design` 创建项目 → 生成 → 迭代 → 导出 PDF，全程无需 LLM 工具。

### M5：Office 融合 + Live Artifact（独立 PR）

- [ ] **步骤 1**：实现 `outline_extractor.py`（Word → 大纲）
  - 调用 `office_read` 解析 Word
  - 提取标题/段落 → markdown 大纲
  - 单元测试
- [ ] **步骤 2**：实现 `chart_embedder.py`（matplotlib → base64 inline）
  - 单元测试：figure → data URL
- [ ] **步骤 3**：集成 Word→Deck 工作流
  - 用户选择 Word 文件 → 提取大纲 → 生成 deck
  - 端到端测试
- [ ] **步骤 4**：实现 `live_artifact.py`（Live Artifact 引擎）
  - 数据源绑定（Excel/JSON）
  - 刷新触发（手动按钮）
  - 单元测试
- [ ] **步骤 5**：前端集成 Live Artifact
  - 项目详情增加"数据源"绑定 UI
  - "刷新"按钮
- [ ] **步骤 6**：本地 smoke test + 提交 PR

**验证点**：选择 Excel 数据源 → 生成 deck → 修改 Excel → 点击刷新 → deck 自动更新数据。

---

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| soffice 未安装 | M1 PDF 导出失败 | 静默回落 reportlab（已有范式） |
| Win7 / py38 兼容性 | cherry-pick 到 release/win7 失败 | 各文件加 `from __future__ import annotations`，避免 PEP 585/604 |
| HTML→PPTX 映射质量 | 字体/布局丢失 | 失败回落 soffice --convert-to pptx |
| 前端工作量超预期 | M4 延期 | 优先做核心功能（创建/生成/导出），迭代聊天/版本历史可降级 |
| Live Artifact 复杂度 | M5b 难以交付 | M5b 标记为 Could，M5a（Office 融合）为 Should |
| 内容库版权 | Apache 2.0 合规 | 保留 NOTICE + 署名，逐步原创替换 |
| LLM 成本 | lint 重试增加调用 | lint 反馈注入 prompt 时复用上下文，不新增完整调用 |

**依赖**：
- M1 无依赖（可立即开始）
- M2 无依赖（可与 M1 并行）
- M3 依赖 M1（复用 export.py 框架）
- M4 依赖 M1（导出面板需要导出 API）
- M5 依赖 M3（HTML↔PPTX 双向）

---

## 6. 双分支策略

本方案在 `main` 分支实施。每个里程碑 PR 合并后，cherry-pick 到 `release/win7` 并做 py38 / pydantic v1 适配：

- `dict[str, str]` → `Dict[str, str]`（typing）
- `X | Y` → `Union[X, Y]`
- pydantic `ConfigDict(extra="forbid")` → `class Config: extra = "forbid"`
- `from __future__ import annotations` 必加

---

## 7. 文档更新

每个里程碑合并后，更新对应文档：
- `docs/technical/151-design-studio-content-craft.md` → 补充导出/lint/前端/融合章节
- `docs/user-manual/` → 新增 Design Studio 使用指南
- `src/content/help/design.md` → 帮助文档

---

## 8. 执行顺序

**推荐**：M1 → M2 → M3 → M4 → M5（串行，每个 PR 独立可发布）

**并行加速**（可选）：
- M1 + M2 可并行（导出与内容库无依赖）
- M3 + M4 可并行（PPTX 映射与前端无依赖）

**本次实施**：从 M1 开始，完成后可继续 M2-M5（视时间与用户反馈）。
