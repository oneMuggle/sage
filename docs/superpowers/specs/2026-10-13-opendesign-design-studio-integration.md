# Design Studio: OpenDesign 融入 Sage 集成设计

> **状态**: 设计已完成，待实施
> **日期**: 2026-10-13
> **方案**: 方案 B — 设计工作室子系统

---

## 1. 背景与目标

### 1.1 背景

OpenDesign（/home/fz/project/open-design）是 Apache-2.0 开源设计工作室，将编码 agent 变为设计引擎。核心能力：用户写 brief → 选设计系统/模板 → agent 生成真实 HTML/CSS 原型、演示文稿 → iframe 预览 → 导出 HTML/PDF/PPTX/MP4。

Sage 是本地优先 AI 桌面助手，已有完整的办公文档处理能力（Word/Excel/PPT/PDF），但缺乏视觉设计能力。

### 1.2 目标

将 OpenDesign 的设计能力用 Sage 原生技术栈（Python 后端 + React 前端）重写，作为 Sage 的功能模块。第一期聚焦：

1. **原型/页面生成** — HTML/CSS 落地页、仪表盘、表单、卡片等
2. **演示文稿生成** — HTML 多页演示文稿，支持主题和动画

### 1.3 设计原则

- **LLM 是生成器**：OpenDesign 的核心洞察——不需要模板引擎，LLM 组合 system prompt 后直接生成 HTML
- **技术栈统一**：Python 后端 + React 前端，不引入 Node.js 运行时
- **与 office 模块互补**：设计产物（HTML 原型）可通过工具与 office 文档互通
- **渐进式交付**：M1 完成即可内部使用原型生成，后续里程碑补齐其余能力

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                  Sage Electron Shell                 │
│  ┌───────────────────────────────────────────────┐  │
│  │              React Frontend                    │  │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │  │
│  │  │  Chat     │  │  Office  │  │  Design     │ │  │
│  │  │  (exist)  │  │  (exist) │  │  Studio     │ │  │
│  │  │           │  │          │  │  (NEW)      │ │  │
│  │  └─────┬─────┘  └────┬─────┘  └──────┬──────┘ │  │
│  └────────┼──────────────┼───────────────┼────────┘  │
│           │  IPC invoke   │   IPC invoke  │ IPC      │
│  ┌────────┴──────────────┴───────────────┴────────┐  │
│  │            Python/FastAPI Backend               │  │
│  │                                                 │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │  │
│  │  │ Agent +  │  │ Office   │  │  Design      │ │  │
│  │  │ Tools    │  │ Module   │  │  Module (NEW)│ │  │
│  │  │(existing)│  │(existing)│  │              │ │  │
│  │  │          │←→│          │←→│ │ Generator  │ │  │
│  │  │          │  │          │  │ │ Systems    │ │  │
│  │  │          │  │          │  │ │ Templates  │ │  │
│  │  │          │  │          │  │ │ Export     │ │  │
│  │  └──────────┘  └──────────┘  └──────────────┘ │  │
│  │           │              │              │       │  │
│  │  ┌────────┴──────────────┴──────────────┴────┐ │  │
│  │  │     LLM Gateway  │  SQLite (sage.db)      │ │  │
│  │  │     (existing)   │  + design tables       │ │  │
│  │  └──────────────────┴────────────────────────┘ │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 2.1 核心原则

1. **Design 模块与 Office 模块平级**，通过工具互相调用
2. **LLM 是生成器**，复用现有 gateway，不引入新的 AI 调用路径
3. **设计系统和模板是静态内容**，通过注册表管理，随 Sage 分发
4. **产物持久化到 SQLite**（与现有模式一致），HTML 文件存 workspace 目录

### 2.2 关键交互流

```
用户写 brief + 选设计系统 + 选模板
  → DesignStudio.generate()
  → 组合 system prompt (DESIGN.md + template SKILL.md + craft rules + brief)
  → LLM gateway 调用（流式 SSE）
  → 解析 <artifact> HTML 产物
  → 存储到 workspace + SQLite 记录
  → 前端 iframe 实时预览
  → 用户可迭代优化（"改配色"）或导出（HTML/PDF/PPTX）
```

---

## 3. 后端模块结构

### 3.1 目录布局

```
backend/design/
├── __init__.py
├── models.py              # Pydantic 数据模型
├── generator.py           # 核心生成器（LLM 调用 + HTML 解析）
├── prompt_composer.py     # System prompt 组装器
├── artifact_parser.py     # 从 LLM 输出中解析 <artifact> HTML
├── standalone_bundler.py  # 独立 HTML 打包（内联 CSS/JS/图片）
├── export.py              # 导出服务（HTML → PPTX/PDF/ZIP）
├── systems.py             # 设计系统注册表
├── templates.py           # 模板注册表
├── design_studio.py       # 顶层编排器（项目生命周期管理）
└── errors.py              # DesignError 异常层次

backend/data/
├── design_repo.py         # 设计项目 + 产物的 SQLite 持久化
└── migrations/
    └── 0XX_add_design_tables.py

backend/tools/
├── design_generate_tool.py
├── design_iterate_tool.py
├── design_export_tool.py
├── design_list_systems_tool.py
└── design_list_templates_tool.py

backend/api/v1/
└── design_routes.py

backend/skills/skill_md/shipped/
├── design-prototype/SKILL.md
└── design-deck/SKILL.md

# 静态内容（从 OpenDesign 移植）
backend/design/content/
├── systems/               # 设计系统（精选 10-15 个）
│   ├── minimal/
│   │   ├── DESIGN.md
│   │   ├── tokens.css
│   │   ├── design-tokens.json
│   │   └── manifest.json
│   ├── corporate/
│   └── ...
└── templates/             # 生成模板
    ├── prototype/
    │   ├── landing-page/
    │   │   ├── SKILL.md
    │   │   └── example.html
    │   └── ...
    └── deck/
        ├── html-ppt/
        │   ├── SKILL.md
        │   └── assets/
        └── ...
```

### 3.2 关键模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `DesignStudio` | 项目生命周期编排（create → generate → iterate → export） | generator, systems, templates, design_repo |
| `Generator` | prompt 组合 → LLM 调用 → HTML 解析 → 产物存储 | prompt_composer, artifact_parser, standalone_bundler, LLMGateway |
| `PromptComposer` | 将 design system + template + brief + 迭代上下文组装为 system prompt | 无外部依赖 |
| `ArtifactParser` | 从 LLM 流式输出中解析 `<artifact>` 标签提取 HTML | 无外部依赖 |
| `StandaloneBundler` | 内联 CSS/JS/图片为 data URL，生成自包含 HTML | 无外部依赖 |
| `DesignExporter` | HTML → PDF/PPTX/ZIP 格式转换 | weasyprint, python-pptx |
| `DesignSystems` | 加载/缓存/查询设计系统（DESIGN.md 解析 + tokens.css） | 文件系统 |
| `DesignTemplates` | 加载/缓存/查询模板（SKILL.md 解析 + assets） | 文件系统 |
| `DesignRepo` | SQLite CRUD（项目 + 产物记录） | sqlite3 |

---

## 4. 数据模型

### 4.1 Pydantic 模型

```python
# backend/design/models.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Literal

class DesignSystem(BaseModel):
    """设计系统定义"""
    model_config = ConfigDict(extra="forbid")

    id: str                          # "minimal", "corporate"
    name: str                        # "极简主义"
    category: str                    # "general", "tech", "academic"
    description: str
    design_md: str                   # DESIGN.md 内容
    tokens_css: str                  # tokens.css 内容
    design_tokens: dict              # design-tokens.json 解析结果
    tags: list[str]

class DesignTemplate(BaseModel):
    """生成模板定义"""
    model_config = ConfigDict(extra="forbid")

    id: str                          # "landing-page", "html-ppt"
    name: str
    kind: Literal["prototype", "deck"]
    description: str
    skill_md: str                    # SKILL.md 内容（生成指令）
    example_html: str | None         # 参考示例
    assets: dict[str, str]           # 支持文件 {path: content}
    design_system_required: bool

class DesignProject(BaseModel):
    """设计项目"""
    model_config = ConfigDict(extra="forbid")

    id: str                          # UUID
    name: str
    kind: Literal["prototype", "deck"]
    system_id: str
    template_id: str
    brief: str
    status: Literal["draft", "generating", "complete", "error"]
    created_at: datetime
    updated_at: datetime

class DesignArtifact(BaseModel):
    """设计产物"""
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    version: int
    html_content: str
    css_injected: str
    title: str
    file_path: str                   # workspace 中的文件路径
    kind: Literal["html", "deck", "standalone"]
    export_formats: list[str]
    source_prompt: str
    created_at: datetime

class DesignGenerateRequest(BaseModel):
    """生成请求"""
    model_config = ConfigDict(extra="forbid")

    project_id: str
    brief: str
    system_id: str
    template_id: str
    model_id: str | None = None      # 使用用户选择的 LLM，None = 默认

class DesignIterateRequest(BaseModel):
    """迭代请求"""
    model_config = ConfigDict(extra="forbid")

    project_id: str
    feedback: str                    # 用户修改要求
    model_id: str | None = None

class DesignExportRequest(BaseModel):
    """导出请求"""
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    format: Literal["html", "pdf", "pptx", "zip"]
```

### 4.2 SQLite 表

```sql
-- 设计项目表
CREATE TABLE design_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('prototype', 'deck')),
    system_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    brief TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'generating', 'complete', 'error')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 设计产物表
CREATE TABLE design_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('html', 'deck', 'standalone')),
    title TEXT NOT NULL,
    export_formats TEXT NOT NULL DEFAULT '[]',  -- JSON array
    source_prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, version)
);

-- 索引
CREATE INDEX idx_design_artifacts_project ON design_artifacts(project_id);
CREATE INDEX idx_design_projects_status ON design_projects(status);
```

HTML 内容存文件系统（`workspace/design/<project_id>/v<version>.html`），SQLite 只存路径和元数据。

---

## 5. 生成器管道

### 5.1 生成流程

```
DesignStudio.generate(project, brief, system_id, template_id)
  │
  ├─ 1. systems.load(system_id)    → DesignSystem
  ├─ 2. templates.load(template_id) → DesignTemplate
  │
  ├─ 3. PromptComposer.compose(
  │       design_system=system,
  │       template=template,
  │       brief=brief,
  │       iteration_context=None,
  │   )
  │   → 完整 system prompt（~2000-4000 tokens）:
  │     ├── 基础角色指令
  │     ├── DESIGN.md 内容（品牌规范）
  │     ├── SKILL.md 内容（模板生成指令）
  │     ├── Craft rules（通用设计原则）
  │     ├── 用户 brief
  │     └── 输出格式要求（<artifact> 标签包裹 HTML）
  │
  ├─ 4. LLMGateway.stream(messages, model)
  │   → SSE 流式响应
  │
  ├─ 5. ArtifactParser.parse(stream)
  │   → 从 <artifact> 标签提取完整 HTML
  │
  ├─ 6. StandaloneBundler.bundle(html, system.tokens_css, template.assets)
  │   → 内联设计系统 CSS 和模板 assets
  │   → 自包含 HTML
  │
  ├─ 7. 存储:
  │   ├── 文件: workspace/design/<project_id>/v<version>.html
  │   ├── SQLite: design_artifacts 新记录
  │   └── project.status = "complete"
  │
  └─ 8. 返回 DesignArtifact
```

### 5.2 迭代流程

```
DesignStudio.iterate(project, user_feedback)
  │
  ├─ 加载最新版本 HTML 作为上下文
  ├─ PromptComposer.compose(
  │       ...,
  │       iteration_context={
  │           "current_html": latest_artifact.html,
  │           "user_feedback": feedback,
  │       }
  │   )
  └─ 后续步骤同 generate
```

### 5.3 Prompt 组合模板

```python
SYSTEM_PROMPT_TEMPLATE = """\
你是一个专业的 HTML/CSS 设计专家。根据用户的设计需求和品牌规范，生成高质量的 HTML 页面。

## 品牌设计规范
{design_md}

## 模板生成指令
{skill_md}

## 通用设计原则
- 使用语义化 HTML5 标签
- CSS 使用 Flexbox/Grid 布局
- 响应式设计（mobile-first）
- 无障碍基础（aria 属性、语义化标签）
- 所有样式使用 design system 提供的 CSS 变量

## 输出格式要求
将生成的完整 HTML 包裹在 <artifact> 标签中：
<artifact identifier="{identifier}" type="text/html" title="{title}">
<!DOCTYPE html>
<html>
...完整 HTML 文档...
</html>
</artifact>

## 用户需求
{brief}
"""

ITERATION_PROMPT_ADDENDUM = """\
## 当前版本 HTML
```html
{current_html}
```

## 用户修改要求
{user_feedback}

请基于当前 HTML 进行修改，保持整体结构不变，仅修改用户要求的部分。
输出修改后的完整 HTML（同样使用 <artifact> 标签包裹）。
"""
```

---

## 6. 导出系统

### 6.1 导出能力

| 格式 | 方法 | 依赖 | 说明 |
|------|------|------|------|
| HTML | `export_html()` | 无 | 自包含 HTML（StandaloneBundler 结果） |
| PDF | `export_pdf()` | weasyprint | HTML → 多页 PDF，支持 CSS3 |
| PPTX | `export_pptx()` | python-pptx | 解析 slide 元素 → 截图 → 组装 PPTX |
| ZIP | `export_zip()` | 无 | 完整项目包（HTML + assets + tokens） |

### 6.2 PPTX 导出细节

```
1. 解析 HTML 中的 <section> 或 .slide 元素
2. 每个 slide 用 Chromium 截图为 PNG
   - 优先复用 Electron 的 Chromium（通过 IPC）
   - 备选：pyppeteer 独立 Chromium
3. 用 python-pptx 组装:
   - 每页一张全屏图片
   - 从 HTML speaker notes 提取备注
   - 设置 16:9 比例
```

---

## 7. 工具集成

### 7.1 新工具清单

| 工具名 | Risk | 职责 |
|--------|------|------|
| `design_generate` | WRITE_LOCAL | 根据 brief + 系统 + 模板生成 HTML |
| `design_iterate` | WRITE_LOCAL | 基于反馈迭代优化产物 |
| `design_export` | WRITE_LOCAL | 导出为 HTML/PDF/PPTX/ZIP |
| `design_list_systems` | READ | 列出可用设计系统 |
| `design_list_templates` | READ | 列出可用模板 |

### 7.2 与现有工具互操作

- `design_generate` 可被 agent 在 office 工作流中调用（如"先设计原型，再生成 PPT"）
- `office_read` 可为 design 提供内容素材（读取 Word 内容作为 brief）
- `design_export` 导出的 PPTX 可被 `office_update` 进一步编辑

### 7.3 技能定义

**design-prototype/SKILL.md**:
```yaml
---
name: design-prototype
description: |
  生成 HTML/CSS 视觉原型：落地页、仪表盘、表单、卡片等。
  支持品牌设计系统，可迭代优化和导出。
triggers:
  - "设计原型"
  - "生成页面"
  - "做一个落地页"
  - "design prototype"
when_to_use: |
  当用户需要创建视觉原型、网页设计、UI mockup 时使用。
allowed-tools:
  - design_generate
  - design_iterate
  - design_export
  - design_list_systems
  - design_list_templates
---
# 工作流程
1. 理解用户设计需求
2. 调用 design_list_systems 推荐设计系统
3. 调用 design_list_templates 选择模板
4. 调用 design_generate 生成原型
5. 展示预览，询问是否需要调整
6. 如有反馈，调用 design_iterate
7. 满意后调用 design_export
```

**design-deck/SKILL.md**:
```yaml
---
name: design-deck
description: |
  生成 HTML 演示文稿（幻灯片），支持多主题和动画效果。
  可导出为 PPTX 格式。
triggers:
  - "做演示文稿"
  - "生成幻灯片"
  - "presentation"
  - "deck"
when_to_use: |
  当用户需要创建演示文稿、幻灯片、pitch deck 时使用。
allowed-tools:
  - design_generate
  - design_iterate
  - design_export
  - design_list_systems
  - design_list_templates
---
```

---

## 8. API 路由

```python
# backend/api/v1/design_routes.py
router = APIRouter(prefix="/design", tags=["design"])

# === 设计系统 & 模板 ===
GET  /api/v1/design/systems              # 列出所有设计系统
GET  /api/v1/design/systems/{id}         # 设计系统详情
GET  /api/v1/design/templates            # 列出模板（?kind=prototype|deck）
GET  /api/v1/design/templates/{id}       # 模板详情

# === 设计项目 CRUD ===
POST   /api/v1/design/projects                    # 创建项目
GET    /api/v1/design/projects                     # 列出项目
GET    /api/v1/design/projects/{id}                # 项目详情
DELETE /api/v1/design/projects/{id}                # 删除项目

# === 生成 & 迭代（SSE 流式） ===
POST   /api/v1/design/projects/{id}/generate       # 触发生成
POST   /api/v1/design/projects/{id}/iterate        # 迭代优化
GET    /api/v1/design/projects/{id}/artifacts       # 产物列表
GET    /api/v1/design/projects/{id}/artifacts/{vid} # 特定版本内容

# === 导出 ===
POST   /api/v1/design/artifacts/{id}/export         # 导出（?format=html|pdf|pptx|zip）
```

生成和迭代使用 SSE 流式响应，与现有 chat 端点模式一致。

---

## 9. 前端组件

### 9.1 文件结构

```
src/features/design/
├── DesignStudio.tsx           # 全页面设计工作台
├── BriefComposer.tsx          # Brief 输入 + 系统/模板选择
├── DesignSystemPicker.tsx     # 设计系统选择器
├── TemplatePicker.tsx         # 模板选择器
├── ArtifactPreview.tsx        # 沙箱 iframe 预览
├── IterationChat.tsx          # 迭代对话面板
├── ArtifactHistory.tsx        # 版本历史时间线
├── ExportPanel.tsx            # 导出选项
├── DesignProjectsList.tsx     # 项目列表
├── useDesignProjects.ts       # 数据 hook
├── useDesignGeneration.ts     # 生成/迭代 SSE hook
└── designApi.ts               # IPC → API 桥接
```

### 9.2 UI 布局

```
┌─────────────────────────────────────────────────────┐
│  Design Studio                          [项目列表 ▼] │
├───────────┬─────────────────────────────────────────┤
│           │                                         │
│  左侧面板  │           主工作区                       │
│           │                                         │
│  ┌───────┐│  ┌─────────────────────────────────┐   │
│  │ Brief ││  │                                 │   │
│  │ 输入  ││  │      iframe 预览                 │   │
│  │       ││  │      (沙箱渲染 HTML)             │   │
│  ├───────┤│  │                                 │   │
│  │ 设计  ││  └─────────────────────────────────┘   │
│  │ 系统  ││                                         │
│  │ 选择  ││  ┌─────────────────────────────────┐   │
│  ├───────┤│  │  迭代对话区                      │   │
│  │ 模板  ││  │  [用户]: 把按钮改成圆角           │   │
│  │ 选择  ││  │  [Agent]: 已修改，请查看预览      │   │
│  ├───────┤│  │  > 输入修改要求...         [发送] │   │
│  │ 导出  ││  └─────────────────────────────────┘   │
│  │       ││                                         │
│  └───────┘│  ┌─────────────────────────────────┐   │
│           │  │  v3 (当前) ← v2 ← v1            │   │
│  ┌───────┐│  │  [点击切换版本]                   │   │
│  │ 版本  ││  └─────────────────────────────────┘   │
│  │ 历史  ││                                         │
│  └───────┘│                                         │
└───────────┴─────────────────────────────────────────┘
```

### 9.3 路由入口

- `src/pages/` 新增 `DesignStudioPage.tsx`
- 侧边栏/导航增加"设计工作室"入口（与 Chat、Office 并列）

---

## 10. 静态内容移植策略

### 10.1 设计系统（精选 10-15 个）

从 OpenDesign 的 164 个设计系统中精选覆盖不同场景的系统：

| 系统 ID | 场景 | 来源 |
|---------|------|------|
| `minimal` | 极简/通用 | 原创 |
| `corporate` | 企业/商务 | 原创 |
| `tech-startup` | 科技/创业 | 参考 Linear/Vercel |
| `academic` | 学术/论文 | 原创 |
| `creative-agency` | 创意/设计 | 原创 |
| `ecommerce` | 电商/零售 | 参考 Shopify |
| `dashboard` | 数据/仪表盘 | 原创 |
| `healthcare` | 医疗/健康 | 原创 |
| `fintech` | 金融/支付 | 参考 Stripe |
| `saas-landing` | SaaS 落地页 | 原创 |
| `portfolio` | 个人作品集 | 原创 |
| `newsletter` | 邮件/通讯 | 原创 |

每个系统包含：DESIGN.md + tokens.css + design-tokens.json + manifest.json。

### 10.2 模板（精选）

**原型类**:
- `landing-page` — 产品落地页
- `dashboard` — 管理后台/仪表盘
- `form` — 表单页
- `pricing` — 定价页
- `blog-post` — 博客文章
- `card-grid` — 卡片网格
- `profile` — 个人/团队介绍

**演示文稿类**:
- `html-ppt` — 通用 HTML 幻灯片（从 OpenDesign 移植，含 36 主题 + 27 动画 + 31 布局 + 15 完整 deck）

### 10.3 许可与归属

OpenDesign 使用 Apache-2.0 许可，允许移植和修改。移植时需：
- 在 `backend/design/content/` 下保留 LICENSE 文件
- 在 Sage 的 about 页面注明 "Design systems and templates derived from OpenDesign (Apache-2.0)"
- 保留每个设计系统的原始归属信息

---

## 11. 分阶段交付

| 里程碑 | 内容 | 预估 | 可验证输出 |
|--------|------|------|-----------|
| M1: 核心生成器 | generator + prompt_composer + artifact_parser + models + design_repo + 迁移 + 2 个基础系统 + 1 个原型模板 | 1 周 | 后端单测：brief → HTML → 存储 → 读取 |
| M2: 工具 + API | 5 个工具 + design_routes + design-prototype SKILL.md | 3-4 天 | Agent 通过工具生成原型；API curl 可调用 |
| M3: 前端工作台 | DesignStudio + BriefComposer + ArtifactPreview + 选择器 | 1 周 | UI 完成：选系统→选模板→写 brief→生成→预览 |
| M4: 演示文稿 | html-ppt 模板移植 + design-deck SKILL.md + deck 选择器 | 3-4 天 | 可生成多页 HTML 演示文稿 |
| M5: 迭代 + 导出 | IterationChat + ArtifactHistory + ExportPanel + export.py | 1 周 | 迭代优化 + 导出 HTML/PDF/PPTX |
| M6: 打磨 + 内容 | 补充设计系统到 10-15 个 + 更多模板 + 错误处理 | 3-4 天 | 端到端可用 |

**总计约 5-6 周**。M1-M3 完成后即可内部使用原型生成。

---

## 12. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 生成 HTML 质量不稳定 | 用户体验差 | 提供高质量模板示例 + 严格的 prompt 工程 + 自检验步骤 |
| weasyprint 渲染与浏览器不一致 | PDF 导出视觉差异 | 备选方案：调用 Electron Chromium 截图后转 PDF |
| 设计系统内容量大 | 移植工作超预期 | 第一期只移植 5 个核心系统，后续按使用频率补充 |
| iframe 沙箱兼容性 | 某些 CSS/JS 特性受限 | 使用 srcdoc 模式 + 明确沙箱策略（允许 style/script） |
| 与现有 office 模块耦合 | 代码冲突 | design 模块独立，仅通过工具接口与 office 互通 |

---

## 13. 与 OpenDesign 的持续关系

移植后，Sage 的 design 模块是独立演进的。但保留以下互通能力：
- **设计系统格式兼容**：DESIGN.md + tokens.css 格式与 OpenDesign 兼容，可从 OpenDesign 生态导入更多系统
- **模板格式兼容**：SKILL.md 模板格式与 OpenDesign 兼容
- **可选的 MCP 互通**：未来可将 OpenDesign 作为 MCP server 接入（如果 Sage 用户需要 OpenDesign 的完整能力）
