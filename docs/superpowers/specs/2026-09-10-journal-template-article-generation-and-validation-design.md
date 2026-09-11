# 期刊模板文章生成与格式校验子系统设计

> **状态：** 已获用户批准；待用户 review 后再生成实施计划
> **日期：** 2026-09-10
> **目标分支：** `main`
> **基础 commit：** `main@82eb8d03`
> **示例模板：** `/home/fz/下载/论文模板260909.doc`（WPS Office 生成的 `.doc` 二进制，CFBF/OLE2 格式，非现代 `.docx`）
> **实施分支：** 8 个独立 PR（详见第 12 节），首个为 `feat/journal-subsystem-n1-skeleton`
> **后续阶段：** 用户 review 后调 `writing-plans` 技能产出每 PR 实施计划

---

## 1. 背景与问题边界

Sage 当前 `backend/office/` 体系下已有 docxtpl 模板填入能力（PR #564 / #569），覆盖：

- `word_template.analyze_word_template` —— 抽取 `{{var}}` 占位符
- `word_template.fill_word_template` —— 沙箱 Jinja 填充
- `template_library` —— 10 个内置模板（周报 / 会议纪要 / 简历 / xlsx / pptx）
- `office_template_tool` —— LLM 工具面暴露 `office_analyze_word_template` / `office_fill_word_template`
- `office_routes.py` —— HTTP 路由 `/office/word/analyze-template`、`/office/word/fill-template`、`/office/templates/instantiate`

但这只覆盖 **结构化短文**（报表、会议纪要、简历等）模板。**学术期刊论文模板**有完全不同形态：

| 学术期刊要求 | 现有能力 |
|---|---|
| 必备章节：摘要 / Abstract / 关键词 / Keywords / 引言 / 方法 / 结果 / 讨论 / 结论 / 参考文献 | ❌ 不识别 |
| 长度约束：摘要 ≤ 300 字、关键词 3–8 个、章节段落数 3–7 | ❌ 不检查 |
| 字体字号合规：正文小四宋体、标题小三黑体 | ❌ 不检查 |
| 行距：1.5 倍 + 首行缩进 2 字符 | ❌ 不检查 |
| 页边距：3 cm 上下、2.8 cm 左右 | ❌ 不检查 |
| 引用格式：`[1]` / `(Smith, 2020)` / GB/T 7714 | ❌ 不识别 |
| `.doc` 二进制摄入 | ❌ 严格拒非 `.docx` 后缀 |
| LLM 一键起草 + 自纠 | ❌ 不支持 |

用户给出的示例 `论文模板260909.doc` 是 WPS Office 12.1.0.28043 生成的 3 页、1413 词、中文（Locale 2052）二进制 `.doc`（CFBF/OLE2），必须先经 pandoc 转 `.docx` 才能进入现有解析管线。

## 2. 目标与非目标

### 2.1 目标

1. **C 级完整样式合规校验**：自动从模板 `.docx` 抽取 styles.xml / numbering.xml / theme1.xml / sectPr / 正文标题，产出 `JournalSpec`，并以此校验成稿。
2. **`.doc` 二进制摄入**：通过 pandoc 把 `.doc` 透明地转 `.docx`，缓存于 workspace，用户无感知差异。
3. **结构化填模板**：用户提供 `JournalContent` JSON（章节 / 参考文献），系统按 spec 填入模板并自动跑校验。
4. **LLM 一键生成**：用户给 topic + 可选 outline，系统调 `llm_proxy` 让 LLM 起草 `JournalContent`，再填模板 + 校验，最长 2 轮自纠。
5. **独立校验**：用户上传成稿 + 选 spec，产出 error / warning / info 三级违规清单，每条带段落位置与中文修复建议。
6. **专用侧边面板**：上传模板 / 浏览 spec / 结构化编辑 / 校验结果展示 / LLM 生成入口。
7. **workspace 本地持久化**：解析出的 spec 存 `<workspace>/office/journal/specs/<sha256>.json`，跨 session 复用；元数据进 SQLite。
8. **Win7 LTS 兼容**：`release/win7` v1 默认不自动 cherry-pick；若需求出现按 PR #508 同款 py38 compat check 后手工 cherry-pick。

### 2.2 非目标

- 编辑器富文本所见即所得（v1 用 Tiptap 半结构化编辑，不做 Word 风格 WYSIWYG）
- 模板可视化预览（v1 只展示 spec 摘要字段）
- 期刊投稿系统对接（v1 仅生成本地 `.docx`，不提交任何投稿门户）
- 多模板混排合并（v1 一篇文档 = 一个 spec）
- `.doc` 输出（v1 输出统一 `.docx`）
- OCR / 扫描件识别（v1 仅处理原生电子模板）
- 跨用户模板共享（v1 spec 跟随 workspace 走，不做云端模板市场）
- 移除或合并 `release/win7`
- 修改现有 `word_template.py` / `template_library.py` / `office_template_tool.py` / `office_pdf_tool.py` 等已合并模块（**零改动原则**）

## 3. 已确认的工程决策

| 决策 | 结果 |
|---|---|
| 校验深度 | **C 级** —— B 级（章节 + 长度）+ 字体字号 / 行距 / 页边距 / 引用格式 / 页眉页脚 |
| 规则来源 | **自动提取** —— 从 styles.xml / numbering.xml / theme1.xml / sectPr / 正文标题启发式推导 |
| 生成输入 | **两种模式并存** —— 结构化 fill（用户提供 `JournalContent`）+ LLM 一键生成（调 chat API） |
| UI 集成 | **专用侧边面板** —— `apps/web/src/features/journal/` 独立子目录 |
| 代码组织 | **新子包 `backend/office/journal/`** —— 现有文件零修改 |
| `.doc` 摄入 | **pandoc 子进程转换** —— `subprocess` argv list、`never shell=True`、按 sha256 缓存、超时 30s |
| 持久化 | **workspace 本地 + SQLite 元数据** —— spec JSON 在 `<workspace>/office/journal/specs/`，metadata 进现有 SQLite |
| 测试策略 | **单 + 集 + 契约 + E2E(tier-1)** —— 新模块单元 ≥85% 覆盖；3 个 critical flow 进 PR gate |
| 交付节奏 | **8 个独立 PR 串行**，每个 ≈1 天工作量，单 squash merge |
| Win7 cherry-pick | **v1 默认不 cherry-pick**；按需按 PR #508 同款流程手工处理 |

## 4. 架构与组件

### 4.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│  前端：专用期刊模板侧边面板                                          │
│  apps/web/src/features/journal/                                      │
│  React + Tiptap/Mantine；通过 IPC + HTTP 与后端通信                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HTTP 路由:backend/api/office_routes.py   新增 /office/journal/*    │
│  LLM 工具:backend/tools/office_journal_*_tool.py  (4 个)            │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  backend/office/journal/  (新子包)                                   │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌─────────────────┐   │
│  │ parser.py  │→│ models.py  │→│ persistence│ │ pandoc_adapter  │   │
│  │ (模板 →   │ │ (JournalSp │ │ (workspace │ │ .py             │   │
│  │  spec)     │ │ ec, Rule,  │ │  本地+SQLite)│ (.doc → .docx)  │   │
│  └────────────┘ │ Violation) │ └────────────┘ └─────────────────┘   │
│        │ ▲                                                        │
│        ▼ ▲                                                        │
│  ┌────────────┐  ┌────────────┐                                     │
│  │validator.py│  │generator.py│                                     │
│  │ (doc → 违 │←┤ (content → │                                     │
│  │  规清单)   │ │  doc, 两   │                                     │
│  └────────────┘ │  种模式)   │                                     │
│                 └────────────┘                                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  复用（零修改）：                                                  │
│  • backend/office/word_template.py    (现有 {{var}} 机制)           │
│  • backend/office/template_library.py (现有 10 个内置模板)          │
│  • backend/office/path_safety.py      (workspace 路径围栏)         │
│  • backend/office/storage.py          (受管文档布局)                │
│  • backend/office/errors.py           (OfficeError 层级)           │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 组件职责

| 组件 | 职责 | 输入 | 输出 |
|---|---|---|---|
| `pandoc_adapter.py` | 通过 `subprocess pandoc` 把 `.doc`（CFBF/OLE2）转 `.docx`；按内容 sha256 缓存；sandbox 安全；**仅用于摄入** | `.doc` 路径 | 转换后的 `.docx` 路径 |
| `parser.py` | 解析期刊模板 `.docx`，生成 `JournalSpec`：抽取 sections（按 style + outline level 识别标题段落）、字体（从 `styles.xml` 的 `w:rPr`）、行距（`w:spacing line`）、页边距（`w:pgMar`）、必需/可选章节（启发式：outline level + 摘要 / Abstract / 参考文献 等关键词）、摘要长度提示、引用模式（模板里 `[1]` / `(Author, Year)` / 上标式标记正则扫描） | `.docx` 路径 | `JournalSpec` |
| `models.py` | Pydantic v2 模型：`JournalSpec`、`FontRule`、`SectionRule`、`SpacingRule`、`MarginsRule`、`ValidationViolation`、`RuleSeverity`（error / warning / info）、`JournalContent`、`JournalGenerationRequest`、`JournalGenerationResult` | — | — |
| `persistence.py` | 每个 workspace 持久化解析后的 spec：`<workspace>/office/journal/specs/<sha256>.json`。列出 API。同一模板幂等再解析 | 模板路径、解析出的 `JournalSpec` | 加载出的 `JournalSpec` |
| `validator.py` | 对一篇文档（路径或内存 `Document`）应用 `JournalSpec`，产出 `ValidationViolation` 列表。每个规则类型一个纯函数（font_check / section_check / length_check / spacing_check / margin_check / citation_check） | 路径或 `Document` + `JournalSpec` | `List[ValidationViolation]` |
| `generator.py` | 两种模式：(a) `generate_from_content(spec, JournalContent)` —— 填充 `{{var}}` 占位符和结构化章节槽位（python-docx）；(b) `generate_via_llm(spec, outline, llm_call)` —— 调用注入的 LLM 回调起草章节内容，然后填模板；两者跑完后自动调用 validator，违规嵌入结果 | `JournalSpec` + `JournalContent`（或 outline） | `JournalGenerationResult(output_path, violations)` |

### 4.3 设计原则

- **隔离**：pandoc_adapter 是唯一 IO 重模块；其余模块纯解析/校验逻辑，便于单元测试
- **一次性 vs 按需**：parser 一次性运行（用户上传模板时触发）；validator / generator 按需运行
- **路径复用**：persistence workspace 本地，让用户携带自己的 spec 跨 session
- **模型风格**：models.py 模仿 `backend/office/models.py` 的 Pydantic v2 模式（适当 `frozen=True`）
- **零回归**：现有 `word_template.py` / `template_library.py` / `office_template_tool.py` / `office_pdf_tool.py` 一行不改

## 5. 数据流与场景

### 5.1 场景 1：模板解析（用户上传 `.doc` / `.docx`）

```
用户拖文件到面板 / chat @office_journal_parse_template(file_path)
        │
        ▼
office_journal_parse_template_tool.execute(file_path)
        │
        ├─1. _resolve_template_input（复用 office_template_tool 模式）
        │   ├─ doc_id 模式 → workspace binding 查 doc
        │   └─ file_path 模式 → 强制绝对路径 + 后缀校验
        │
        ├─2. 扩展后缀白名单：.docx 直接进；.doc → pandoc_adapter.convert_doc_to_docx()
        │   ├─ pandoc 进程（subprocess，argv list，never shell=True）
        │   ├─ 超时 30s，失败 → OfficeTemplateParseError
        │   ├─ 输出到 workspace 缓存目录 .sage-cache/journal/<sha256>.docx
        │   └─ 缓存命中（同 sha256 已存在）直接复用
        │
        ├─3. JournalParser.parse(cached_docx_path)
        │   ├─ Document(str(path)) — python-docx
        │   ├─ 遍历 sections → sectPr → 提取 page setup（margins/orientation）
        │   ├─ 遍历 styles → w:styles w:rPr → 提取字号、字体名、中文字体
        │   ├─ 遍历 numbering.xml → w:numFmt → 编号样式
        │   ├─ 遍历 body paragraphs → 检测 Heading 1/2/3 + 关键词
        │   │      （"摘要"/"Abstract"/"关键词"/"Keywords"/"引言"/"参考文献"/...）
        │   ├─ 启发式：统计模板正文字号 → body_font；标题字号 → heading_font
        │   ├─ 启发式：从 sectPr 提 line spacing、w:pgMar 提 margins
        │   └─ JournalParseError 包裹所有解析异常
        │
        ├─4. persistence.save_spec(workspace, template_sha256, JournalSpec)
        │   └─ 写 <workspace>/office/journal/specs/<sha256>.json（原子 rename）
        │
        └─5. 返 ToolResult(success, JournalSpec 摘要：sections/required_styles/margins)
            同时返回 spec_id (sha256) 供后续 fill/validate 用
```

**关键不变量：**

- `.doc` 只在**摄入阶段**出现一次，后续所有环节都用 `.docx`
- pandoc 缓存按内容 sha256 失效 —— 同一文件绝不重复转换
- spec **幂等可重放**：同一模板任何时刻解析出来的 spec 一致（允许 hash 字段差异）

### 5.2 场景 2：结构化内容填入（用户给 JSON → 文档）

```
chat @office_journal_fill_from_content(spec_id, content)
        │
        ▼
office_journal_fill_from_content_tool.execute(spec_id, content)
        │
        ├─1. persistence.load_spec(workspace, spec_id)
        │   └─ 缺失 → spec_not_found
        │
        ├─2. 校验 content 形状（JournalContent）
        │   ├─ 必填字段缺失 → content_incomplete（列出缺哪些）
        │   ├─ 字段长度超限 → length_warning
        │   └─ 字段类型错 → content_shape_invalid
        │
        ├─3. generator.generate_from_content(spec, content)
        │   ├─ 3a. 用 spec_id 找回原始 .docx 路径（persistence 元数据）
        │   ├─ 3b. 复制模板到 output 临时名（.fill-<uuid>.docx）
        │   ├─ 3c. 用 docxtpl 填充 {{var}} 占位符（title/author/date）
        │   ├─ 3d. 结构化章节写入：遍历 content.sections，匹配 spec.sections
        │   │      ├─ 每个章节起始插入对应 outline level 的标题段落
        │   │      ├─ 章节正文按 spec.body_style 应用字体字号
        │   │      └─ 缺失的 required section → 跳过（交由 validator 报）
        │   ├─ 3e. 参考文献：解析 content.references[](number, text) →
        │   │      按 spec.citation_format 排版
        │   ├─ 3f. 落盘：tmp → resolve_within → os.replace(output_path)
        │   └─ 3g. 异常 → OfficeTemplateFillError 包裹
        │
        ├─4. validator.validate_doc(output_path, spec)
        │   ├─ Document(output_path) 重新读取
        │   ├─ 逐条规则检查，产出 violations
        │   └─ 失败不抛（校验失败≠生成失败，违规可降级）
        │
        └─5. 返 ToolResult(success, output_path, violations: [...])
```

### 5.3 场景 3：LLM 驱动生成（outline → 文档）

```
chat @office_journal_generate_article(spec_id, topic, outline?, max_iterations=2)
        │
        ▼
office_journal_generate_article_tool.execute(spec_id, topic, outline?)
        │
        ├─1. persistence.load_spec + 形状校验（同场景 2）
        │
        ├─2. 调用 LLM 起草结构化内容（spec_id, topic, outline）
        │   ├─ 系统 prompt 注入 JournalSpec 的 sections + required fields
        │   ├─ 要求 LLM 输出 JSON：JournalContent 形状
        │   ├─ max_iterations=2：首轮输出不合规 → 反馈 violations 让 LLM 修订
        │   └─ 仍不合规 → 接受 best-effort + violations 全量回传
        │
        ├─3. 后续同场景 2 第 3-5 步
        │
        └─4. 返 ToolResult(output_path, violations, llm_iterations_used)
```

**LLM 注入方式**：用 sage 现有的 `llm_proxy` HTTP API（`backend.api.llm_proxy_routes`），工具内部通过 `httpx` 调 `/api/v1/llm/chat`，注入 system prompt + spec 上下文。模型选择跟随当前 chat 的 profile 默认值（`writer` profile 模型）。**不**直接调任何特定 vendor SDK。

### 5.4 场景 4：独立校验（用户上传成稿 → 违规清单）

```
面板 / chat @office_journal_validate(spec_id, doc_path)
        │
        ▼
office_journal_validate_tool.execute(spec_id, doc_path)
        │
        ├─1. 解析 doc_path 后缀；.doc → pandoc 临时转换（不缓存——单次使用）
        │
        ├─2. persistence.load_spec
        │
        ├─3. validator.validate_doc(doc_path, spec)
        │   ├─ font_check：每个 run 的 w:rFonts + w:sz → 与 spec.body_font / heading_font 对比
        │   │      容差：同族字体（如 宋体/SimSun）算匹配；大小差异 ±0.5pt 算匹配
        │   ├─ section_check：遍历文档，匹配 spec.required_sections
        │   │      缺失 → error；顺序错 → warning；多余标题 → info
        │   ├─ length_check：摘要字数、关键词数量（3-8）、各 section 段落数
        │   ├─ spacing_check：w:spacing line → 1.5 倍/单倍；首行缩进 w:ind firstLine
        │   ├─ margin_check：sectPr w:pgMar → top/bottom/left/right 与 spec.margins 一致
        │   └─ citation_check：正则扫描参考文献区，核对 spec.citation_format
        │
        └─4. 返 ToolResult(violations: List[ValidationViolation])
            每条带 {rule_id, severity, location(paragraph_index / section),
            message(中文), suggested_fix}
```

**关键设计点：**

- **校验降级**：任何规则检查器自身抛异常 → 把该条规则降级为 info（"规则 X 检查失败，跳过"），不阻断其他规则
- **位置精度**：violation 必须携带 `paragraph_index`（0-based）和 `section_name`，前端才能精准高亮
- **suggested_fix**：对每类规则预置中文修复建议（"将字体改为 宋体 小四"、"在参考文献前插入 '参考文献' 标题"）

## 6. 规则提取策略

### 6.1 抽取源全景

OOXML 模板里"格式规则"分散在 4 个 XML 部件：

| OOXML 部件 | 包含的规则信息 | 提取难度 |
|---|---|---|
| `word/styles.xml` | 命名样式（Normal / Heading 1-9 / Title / Caption / Quote...）的字体、字号、行距、对齐 | ★★ 中等 |
| `word/document.xml` | body 段落的实际样式引用 `w:pStyle`、章节标题文字、文献编号模式 | ★★ 中等 |
| `word/numbering.xml` | 多级列表（参考文献 `[1]` `[2]`）、标题自动编号（1.1.1 1.1.1） | ★★★ 较难 |
| `word/theme/theme1.xml` | 主题字体（majorFont / minorFont）—— WPS/Word 默认字体 | ★ 简单 |
| `word/settings.xml` | 默认 tab、视图缩放、字符间距 | ★ 简单 |
| `w:sectPr`（在 document.xml 里） | 页面尺寸、页边距、行距默认值、页眉页脚引用 | ★★ 中等 |

### 6.2 字体提取（三级 fallback）

```python
def extract_body_font(doc: Document) -> FontRule:
    # 1. 优先：NamedStyle "Normal" 的 w:rPr → w:rFonts + w:sz
    normal_style = doc.styles.element.find(".//w:style[@w:styleId='a']")  # Normal
    if rpr := find_rpr(normal_style):
        if fonts := parse_w_rfonts(rpr):  # ascii/hAnsi/eastAsia
            return FontRule(
                ascii=fonts.ascii,            # 如 "Times New Roman"
                east_asia=fonts.east_asia,    # 如 "宋体" / "SimSun"
                size_pt=parse_w_sz(rpr),      # 如 12pt（w:sz 单位 = 半磅，12*2=24）
                source="styles:Normal",
            )

    # 2. fallback：theme1.xml majorFont/minorFont
    theme_fonts = parse_theme_fonts(theme_xml)
    return FontRule(
        ascii=theme_fonts.minor_ascii,
        east_asia=theme_fonts.minor_east_asia,
        size_pt=12.0,  # OOXML 默认正文大小
        source="theme1",
    )

    # 3. 末位 fallback：正文段落实际使用的字体（启发式，取第一段非空 run）
    # 不实现 —— spec 应直接报 source="unknown" 让用户手动补
```

**关键 WPS vs Word 兼容性处理：**

| 差异 | WPS 命名 | Word 命名 | 处理 |
|---|---|---|---|
| 正文字体 | `a` (Normal) | `a` (Normal) | 同一 |
| 一级标题 | `1` (Heading 1) | `1` (Heading 1) | 同一 |
| 中文标题字体 | `黑体` / `SimHei` | `黑体` / `SimHei` | 同字体名（关键要识别 `w:eastAsia` 而非 `w:ascii`） |
| 表格内字体 | `a3` (TableNormal) | `a3` (TableNormal) | 同一 |
| 自定义样式 | 用户命名（`自定义标题_1`） | 用户命名 | 不抽取 —— 仅匹配系统样式 |

**字体族归一化**（降低 WPS 误报）：

```python
_FONT_FAMILY_ALIASES = {
    "宋体": {"宋体", "SimSun", "宋体-简", "Songti SC", "Noto Serif CJK SC"},
    "黑体": {"黑体", "SimHei", "黑体-简", "Heiti SC", "Noto Sans CJK SC"},
    "楷体": {"楷体", "KaiTi", "楷体-简", "Kaiti SC"},
    "微软雅黑": {"微软雅黑", "Microsoft YaHei", "MS YaHei", "MicrosoftYaHei"},
    "Times New Roman": {"Times New Roman", "Times", "Liberation Serif"},
    "Arial": {"Arial", "Liberation Sans", "Helvetica"},
}

def normalize_font(name: str) -> str:
    for canonical, aliases in _FONT_FAMILY_ALIASES.items():
        if name in aliases:
            return canonical
    return name  # 未知字体原样保留
```

`validate_doc` 时做归一化比对，**同族字体不算违规**。

### 6.3 字号提取

OOXML 单位：`w:sz` 和 `w:szCs` 单位是**半点**（half-point）。`w:sz="24"` = 12pt。

**字号归一化**：

```python
_PT_TO_CN = {
    42: "初号", 36: "小初", 26: "一号", 24: "小一",
    22: "二号", 18: "小二", 16: "三号", 15: "小三",
    14: "四号", 12: "小四", 11: "五号", 9: "小五",
    7.5: "六号", 6.5: "小六", 5.5: "七号", 4.5: "八号",
}
```

校验时输出中文名（`"正文应为 小四(12pt)，实际为 五号(10.5pt)"`），不用裸 pt 数。

### 6.4 行距提取

```xml
<!-- sectPr 中的页面设置，作用于整个 section -->
<w:pgMar w:top="2125" w:right="1701" w:bottom="2125"
         w:left="2125" w:header="850" w:footer="992" w:gutter="0"/>
<!-- 行距（可在段落的 w:pPr 或 styles 的 w:pPr 里） -->
<w:spacing w:line="360" w:lineRule="auto"/>
```

- `w:line` + `w:lineRule="auto"` → 240 = 单倍 / 360 = 1.5 倍 / 480 = 双倍
- `w:line` + `w:lineRule="exact"` → 单位是 twip（1/20pt），如 `w:line="480"` = 24pt

```python
def parse_line_spacing(paragraph_or_style) -> Optional[float]:
    spacing = find_w_spacing(paragraph_or_style)
    if spacing is None:
        return None
    line = int(spacing.get("w:line", "0"))
    rule = spacing.get("w:lineRule", "auto")
    if rule == "auto":
        return line / 240.0  # 1.0/1.5/2.0
    if rule == "exact":
        return line / 20.0  # pt
    return None
```

### 6.5 页边距提取

OOXML 单位：twip（1/20pt）= 1/1440 inch。**`w:pgMar` 字段单位 = twip**。

```python
def parse_margins(sectpr) -> MarginsRule:
    pgmar = sectpr.find("w:pgMar")
    return MarginsRule(
        top_cm=twip_to_cm(int(pgmar.get("w:top"))),
        bottom_cm=twip_to_cm(int(pgmar.get("w:bottom"))),
        left_cm=twip_to_cm(int(pgmar.get("w:left"))),
        right_cm=twip_to_cm(int(pgmar.get("w:right"))),
    )

def twip_to_cm(twip: int) -> float:
    return round(twip / 567.0, 2)  # 567 twip ≈ 1 cm
```

**容差**：边距差 ≤0.3cm 算匹配（`abs(actual - spec) <= 0.3`）。

### 6.6 章节识别

```python
_HEADING_KEYWORDS = [
    # 中文期刊常见章节（按出现顺序启发式排序）
    ("摘要", "abstract"),
    ("Abstract", "abstract"),
    ("关键词", "keywords"),
    ("Keywords", "keywords"),
    ("引言", "introduction"),
    ("前言", "introduction"),
    ("Introduction", "introduction"),
    ("材料与方法", "methods"), ("方法", "methods"),
    ("Methods", "methods"), ("Materials and Methods", "methods"),
    ("结果", "results"), ("结果与分析", "results"),
    ("Results", "results"),
    ("讨论", "discussion"),
    ("Discussion", "discussion"),
    ("结论", "conclusion"),
    ("Conclusion", "conclusion"),
    ("参考文献", "references"),
    ("References", "references"),
    ("致谢", "acknowledgements"),
    ("Acknowledg(e)ments", "acknowledgements"),
]

def extract_sections(doc) -> List[SectionRule]:
    sections = []
    for p_idx, para in enumerate(doc.paragraphs):
        style_name = para.style.name
        outline_level = para.style.element.find(".//w:outlineLvl")
        is_heading = (
            "Heading" in style_name
            or "标题" in style_name
            or (outline_level is not None and int(outline_level.get("w:val", "9")) <= 2)
        )
        if not is_heading:
            continue
        text = para.text.strip()
        if not text:
            continue
        matched_key = None
        for kw, canonical in _HEADING_KEYWORDS:
            if kw.lower() in text.lower():
                matched_key = canonical
                break
        if matched_key:
            sections.append(SectionRule(
                name=matched_key, raw_text=text, paragraph_index=p_idx,
                outline_level=outline_level or 0,
            ))
    return dedupe_preserve_order(sections)  # 同一 canonical 只保留首条
```

**启发式局限性：**

- 模板不含关键词的章节（如某些期刊的"实验部分"用"3 Experimental Section"）→ 标 `unknown_section`，提示用户手动标注
- 多级标题嵌套（1. 引言 / 1.1 背景）→ 用 outline_level 区分，但 spec 只记录顶层章节名

### 6.7 引用格式识别（numbering.xml + 正文扫描）

```python
_CITATION_PATTERNS = [
    (re.compile(r"\[\d+\]"),                              "numeric"),         # [1] [2]
    (re.compile(r"\(\d+\)"),                              "numeric_paren"),   # (1) (2)
    (re.compile(r"[①②③]"),                                "numeric_circle"),  # ①②③
    (re.compile(r"[一-龥]+\s*et\s+al\.?,\s*\d{4}"), "author_year"),       # 张三 et al., 2020
    (re.compile(r"\(\w+,\s*\d{4}\)"),                     "author_year_paren"),  # (Smith, 2020)
    (re.compile(r"\b(?:GB/T|GB)\s*7714\b"),               "gb_t_7714"),       # 显式标注
]

def detect_citation_format(template_text: str) -> CitationFormat:
    hits = {}
    for pattern, fmt in _CITATION_PATTERNS:
        hits[fmt] = len(pattern.findall(template_text))
    if not hits or max(hits.values()) == 0:
        return CitationFormat.UNKNOWN
    return max(hits.items(), key=lambda x: x[1])[0]
```

**多重引用样式场景**（国内期刊常有"正文 `[1]` / 参考文献 著者-出版年"）→ spec 同时记录两种，validator 检查正文用 numeric，参考文献区用 author_year。

### 6.8 parser 性能预算

- 模板 ≤ 2MB + ≤200 段落 + ≤20 表格 → 解析 ≤ 500ms
- 重复解析同一模板（命中 spec 缓存）≤ 50ms
- 缓存键 = `sha256(file_content)`，**不是** `file_path`（路径变但内容不变 → 命中）

## 7. 持久化

### 7.1 两层结构

```
<workspace>/
├── office/
│   ├── journal/
│   │   ├── specs/                  # 解析后的 JournalSpec（JSON）
│   │   │   └── <sha256>.json
│   │   ├── cache/                  # pandoc 转换缓存（.doc → .docx）
│   │   │   └── <sha256>.docx
│   │   └── generation_history.jsonl # 每次生成留痕（append-only）
│   ├── word/<uuid>/<filename>.docx  # 复用现有 managed 文档布局
│   └── excel/...
└── templates/<user_uploaded>.docx # 用户上传的原模板（只读）
```

### 7.2 SQLite 元数据表

在现有 `office` 数据库里追加（**不**新建 DB 文件）：

```sql
CREATE TABLE IF NOT EXISTS office_journal_specs (
    spec_id TEXT PRIMARY KEY,            -- sha256(template_content)
    template_filename TEXT NOT NULL,     -- 原 .docx / .doc 文件名
    template_sha256 TEXT NOT NULL,
    template_size_bytes INTEGER NOT NULL,
    spec_json TEXT NOT NULL,             -- 完整 JournalSpec JSON
    spec_version INTEGER NOT NULL,       -- schema 版本号
    created_at INTEGER NOT NULL,         -- epoch milliseconds
    updated_at INTEGER NOT NULL,         -- epoch milliseconds
    last_generated_at INTEGER,           -- epoch milliseconds，可空
    generation_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS office_journal_generations (
    gen_id TEXT PRIMARY KEY,
    spec_id TEXT NOT NULL,
    output_path TEXT NOT NULL,
    mode TEXT NOT NULL,                  -- 'structured' / 'llm'
    topic TEXT,
    violations_json TEXT,                -- 生成时的违规快照
    created_at INTEGER NOT NULL,         -- epoch milliseconds
    FOREIGN KEY (spec_id) REFERENCES office_journal_specs(spec_id)
);
CREATE INDEX idx_office_journal_gen_spec ON office_journal_generations(spec_id);
```

### 7.3 persistence.py 接口

```python
def save_spec(workspace: Path, template_path: Path, spec: JournalSpec) -> str:
    """返回 spec_id (= sha256(template_content))。幂等：同内容不重复写。"""

def load_spec(workspace: Path, spec_id: str) -> JournalSpec:
    """先 workspace SQLite，再 fallback 到 <workspace>/office/journal/specs/<id>.json。"""

def list_specs(workspace: Path) -> List[SpecSummary]:
    """返回 [{spec_id, template_filename, section_count, created_at}]。"""

def record_generation(workspace: Path, spec_id: str, output_path: Path,
                      mode: str, topic: Optional[str],
                      violations: List[ValidationViolation]) -> str:
    """追加 office_journal_generations 一行，返 gen_id。"""

def list_generations(workspace: Path, spec_id: str, limit: int = 20) -> List[GenerationRecord]:
    """前端面板"生成历史"用。"""
```

## 8. LLM 工具面

镜像 `backend/tools/office_template_tool.py` 的安全姿态：

| 工具名 | risk class | 模式 | 输入 | 输出 |
|---|---|---|---|---|
| `office_journal_parse_template` | READ | doc_id \| file_path | `.doc` / `.docx` 路径 | spec_id + JournalSpec 摘要 |
| `office_journal_fill_from_content` | WRITE_LOCAL | doc_id（spec_id） | spec_id + JournalContent JSON | output_path + violations |
| `office_journal_generate_article` | WRITE_LOCAL + LLM | doc_id（spec_id） | spec_id + topic + outline? | output_path + violations + llm_iterations |
| `office_journal_validate` | READ | doc_id \| file_path | spec_id + 待校验文档路径 | violations 列表 |

### 8.1 `office_journal_fill_from_content` 的 schema

```python
class OfficeJournalFillFromContentTool(BaseTool):
    requires_tool_context = False  # 写工具，但 workspace 内安全
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_journal_fill_from_content",
            description=(
                "根据已解析的期刊模板（spec_id）填充结构化内容，生成符合模板格式的"
                "Word 文档。content 必须是 JournalContent JSON，包含 sections"
                "（按模板章节顺序）、references（参考文献列表）、可选的 authors/"
                "abstract/keywords 覆盖。生成后自动跑格式校验，违规以列表形式回传。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "模板 spec 的 sha256 id（由 office_journal_parse_template 返回）",
                    },
                    "content": {
                        "type": "object",
                        "description": "JournalContent: {title, authors[], abstract, "
                                       "keywords[], references[{number, text}]}",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "输出文件名（workspace 内相对路径，不带斜杠）",
                    },
                },
                "required": ["spec_id", "content", "output_filename"],
            },
        )
```

### 8.2 LLM 调用契约

```python
def _call_llm_for_content(spec: JournalSpec, topic: str,
                          outline: Optional[str], feedback: Optional[str]) -> JournalContent:
    """调 /api/v1/llm/chat（system+user messages），返 JournalContent。
    system prompt 包含：
      - JournalSpec.sections（章节名 + 必填/可选）
      - abstract_max_chars, keywords_min/max
      - 当前 feedback（若不是首轮）
    user prompt: topic + outline（若提供）+ 反馈要求
    response_format: json_schema（JournalContent shape）
    """
```

### 8.3 Profile 白名单更新

`backend/agents/profiles.py`：

- `writer` profile 加全部 4 个 journal_* 工具（LLM 写论文是该角色典型工作）
- `primary` profile 加 `parse_template` + `validate`（允许主对话中"先看模板、再校验"）
- `editor` profile 加 `fill_from_content` + `validate`（编辑审稿场景）
- 同步更新 `_PRIMARY_CURRENT_DEFAULT_TOOLS` / `_WRITER_CURRENT_DEFAULT_TOOLS` / `_EDITOR_CURRENT_DEFAULT_TOOLS`（避免 PR #412 重蹈"工具进了代码但没进白名单"的覆辙）

## 9. 前端专用侧边面板

### 9.1 目录约定（模仿 `apps/web/src/features/artifacts/`）

```
apps/web/src/features/journal/
│
├── JournalPanel.tsx                 # 主壳 —— 可折叠侧边栏
├── components/
│   ├── TemplateUpload.tsx           # 拖拽上传 .doc / .docx，显示解析进度
│   ├── SpecList.tsx                 # 列出已解析模板，sha256 + 文件名 + 章节数
│   ├── SpecDetail.tsx               # 单个 spec 的 sections/styles 预览
│   ├── ContentEditor.tsx            # Tiptap 富文本按 sections 分块编辑
│   ├── GenerateForm.tsx             # LLM 一键生成的 topic + outline 表单
│   ├── ViolationList.tsx            # 违规清单 —— 红/黄/蓝三色徽章 + 修复建议
│   └── GenerationHistory.tsx        # 历史生成记录（persistence.list_generations）
├── hooks/
│   ├── useJournalSpec.ts            # SWR 风格缓存 spec
│   ├── useJournalTools.ts           # 调 4 个 LLM 工具的 IPC wrapper
│   └── useTemplateUpload.ts         # 上传 + 进度跟踪
├── store/
│   └── journalStore.ts              # zustand 状态（specs 列表、当前选中、生成中状态）
└── types.ts                         # 与后端 JournalSpec Pydantic 对齐的 TS 类型
```

### 9.2 主面板布局

```
┌─────────────────────────────────────────────────────────────┐
│  📄 期刊模板生成助手                            [_][□][×]   │
├─────────────────────────────────────────────────────────────┤
│ [上传模板] [我的模板 ▾] [生成历史]                            │
│                                                             │
│ 📋 当前模板：计算机学报_v1.docx                              │
│   sha256: a3f9c2... │ 章节: 7 │ 解析于 14:23                │
│                                                             │
│  ──────────────────────────────────────────────             │
│  ▼ 章节结构                                                 │
│  1. 摘要 (必填，≤300字)                                    │
│  2. 关键词 (必填，3-8个)                                    │
│  3. Abstract                                                │
│  4. Keywords                                                │
│  5. 引言                                                    │
│  6. 方法                                                    │
│  7. 结果                                                    │
│  8. 讨论与结论                                              │
│  9. 参考文献                                                │
│                                                             │
│  ──────────────────────────────────────────────             │
│  ▼ 样式规则                                                 │
│  字体：宋体（西文 Times New Roman）                         │
│  字号：正文小四（12pt）标题小三（15pt）                     │
│  行距：1.5 倍   首行缩进：2字符                             │
│  页边距：上 3.75 下 3.75 左 2.8 右 2.8 cm                   │
│  引用：[1] 顺序编码                                         │
│                                                             │
│  [✏️ 结构化编辑] [🤖 LLM 一键生成] [🔍 校验]                  │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 IPC + HTTP 桥接

```typescript
// apps/web/src/features/journal/hooks/useJournalTools.ts
async function fillFromContent(req: FillFromContentRequest): Promise<FillFromContentResult> {
  return window.electronAPI.invoke('journal:fill-from-content', req);
}

// electron/preload.ts 暴露
contextBridge.exposeInMainWorld('electronAPI', {
  invoke: (channel, payload) => ipcRenderer.invoke(channel, payload),
  ...
});

// electron/main.ts 注册 IPC handler
ipcMain.handle('journal:fill-from-content', async (_e, req) => {
  return await officeJournalToolService.fillFromContent(req);
});
```

`officeJournalToolService` 是 electron 端的服务层，**直接调用** `backend/office/journal/generator.py` 的导出函数（不走 HTTP，本地子进程调用，避免 IPC 双重序列化）。HTTP `/office/journal/*` 路由给非 Electron 客户端用（未来 web 版）。

### 9.4 安全姿态

- `requires_tool_context`：3 个写工具不要求（同 `office_fill_word_template`）；`validate` 要求（读工具）
- workspace 路径围栏：`resolve_within(workspace, output_path)`（同 `path_safety.py`）
- output 不存在检查（`final.exists() and final != template.resolve()` → 拒绝）
- 大小限制：生成的 .docx ≤50MB（同 `_validate_docx_zip` 阈值）
- LLM 输出校验：`JournalContent.parse_raw()` 失败 → 整轮拒绝，重新调 LLM；最多 2 轮
- 文件格式白名单：`spec_id` 必须匹配 `^[a-f0-9]{64}$`；`output_filename` 必须匹配 `^[^/\\]+\.docx$`

## 10. 错误处理

### 10.1 分层降级

| 错误源头 | 降级路径 | 用户可见表现 |
|---|---|---|
| pandoc 进程超时/退出非0 | pandoc_adapter 捕获 → `OfficeTemplateParseError("pandoc_failed: ...")` | 弹 toast "模板转换失败，请检查 .doc 是否损坏" |
| .docx 内嵌 ZIP 损坏/超大 | `_validate_docx_zip` → `OfficeSizeLimitError` | 红 banner + 路径回显 |
| parser 抛出（XML 解析失败） | `JournalParserParseError` | spec 标 `status="parse_failed"`，列表仍展示 |
| content 形状不对（missing field） | `content_incomplete` 错误，列出缺的字段名 + 类型期望 | LLM 工具层面调用 |
| LLM 输出 JSON 解析失败 | 重试（max 2 轮），仍失败 → `llm_output_invalid` + best-effort 返回 | |
| LLM 输出不合 spec（字数超/缺关键词） | violation 不算 error，作为 warning 回传；不在 LLM 失败条件里 | |
| validator 自身抛异常（某条规则崩溃） | 该条规则降级为 info（"规则 X 检查失败，跳过"），不阻断其他规则 | |
| workspace 路径越界 | `OfficePathError` → `path_invalid` | 工具返 ToolResult(error=...) |
| docx 已存在（覆盖检查失败） | `file_exists` 错误 + 建议改名 | 提示用户换 output_filename |

### 10.2 新增错误码

继承现有 `OfficeError` 层级：

```python
# backend/office/journal/errors.py
class JournalError(OfficeError): pass
class JournalParseError(JournalError):   # parser 失败
    pass
class JournalSpecNotFoundError(JournalError):  # spec_id 不存在
    pass
class JournalContentShapeError(JournalError):  # content JSON 形状错
    pass
class JournalPandocError(JournalError):  # .doc→.docx 转换失败
    pass
class JournalGenerationError(JournalError):  # 生成失败（模板/IO/...）
    pass
```

### 10.3 LLM 工具错误信封

```python
{
    "success": False,
    "error_code": "spec_not_found",  # 稳定错误码
    "error_message": "找不到 spec_id=a3f9c2... 对应的模板",
    "details": { "spec_id": "a3f9c2..." }
}
```

错误码稳定，前端面板可基于错误码做 i18n 与分支处理。

## 11. 测试策略

### 11.1 层级覆盖

| 层级 | 范围 | 工具 | 目标覆盖率 |
|---|---|---|---|
| **单元** | `parser.py` 各 XML 解析函数 / `validator.py` 各 check 函数 / `pandoc_adapter.py` 缓存逻辑 / `persistence.py` CRUD / `models.py` Pydantic 校验 | pytest | ≥ 85%（新模块） |
| **集成** | `generator.py` 端到端（给 JSON content → 期望 .docx） / `validate` 全规则组合 / SQLite schema 迁移 | pytest + tmp_path fixture | 关键路径覆盖 |
| **契约** | `office_journal_*_tool` 输入/输出形状 / `office_routes.py` /office/journal/* 路由 schema / 错误码稳定性 | pytest | 全部 |
| **E2E（tier-1）** | 3 个 critical user flow 进 PR gate（同 PR #569 模式） | Playwright | 必过 |

### 11.2 测试 fixture

写在 `backend/tests/fixtures/journal/`：

```
fixtures/journal/
├── simple_chinese_journal_template.docx   # 自制最小期刊模板
│                                          # - 7 个标准章节 + 摘要 + 参考文献
│                                          # - 标题小三黑体、正文小四宋体、行距 1.5
│                                          # - 页边距 3cm
├── wps_generated_template.doc             # .doc 二进制（用 WPS 导出或 pandoc 模拟）
│                                          # 测 .doc → .docx 转换路径
├── ieee_style_template.docx               # 英文期刊样式（英文模板分支）
│                                          # - Times New Roman + Author-Year 引用
├── bad_template_corrupt.docx              # ZIP 损坏
├── too_large_template.docx                # >50MB
├── good_filled_paper.docx                 # 完整填好的样例，测 validator pass 路径
└── bad_filled_paper.docx                  # 故意缺章节、改字体，测 validator fail 路径
```

### 11.3 关键 E2E 用例（进 tier-1 gate）

| # | 场景 | 步骤 | 断言 |
|---|---|---|---|
| 1 | 模板解析 + 列出 | 上传 .docx → 等待 spec_id 出现 | spec 在 list 中，sections 数 ≥ 6 |
| 2 | 结构化 fill | 选 spec → 输入 content JSON → 点生成 | output 文件存在 + 校验违规数 ≤ 3 |
| 3 | 校验坏论文 | 上传故意违规 .docx → 选 spec → 校验 | 违规数 ≥ 1 + 每条带 suggested_fix |

### 11.4 WPS/Word 兼容性测试矩阵

每个矩阵跑 2 套 fixture，作为 `pytest.mark.parametrize`：

| 矩阵维度 | 取值 |
|---|---|
| 模板来源 | Word2019 / WPS Office12 / LibreOffice 7 |
| 章节命名风格 | 中文核心期刊标准 / IEEE / ACM |
| 引用格式 | numeric / author_year / gb_t_7714 |

## 12. 阶段性交付（PR 切分）

项目级约定：遵循 `.claude/CLAUDE.md` 的"feature branch + worktree"模式。每个 PR 一个 commit（squash），按依赖顺序串行。

| PR | 标题 | 工作量 | 依赖 | 关键交付 |
|---|---|---|---|---|
| **#N1** | `feat(journal): 子包骨架 + pandoc_adapter + models + errors` | 0.5d | 无 | `backend/office/journal/{__init__,errors,models,pandoc_adapter}.py` + 单元测试 |
| **#N2** | `feat(journal): parser + persistence + spec schema` | 1d | #N1 | `parser.py` + `persistence.py` + SQLite migration + fixture 准备 + 解析测试 |
| **#N3** | `feat(journal): validator + 6 大规则 check 函数` | 1.5d | #N2 | `validator.py` + 规则 fixture + 校验测试 |
| **#N4** | `feat(journal): generator (structured fill 模式)` | 1d | #N2 | `generator.py` generate_from_content + 端到端测试 |
| **#N5** | `feat(journal): LLM generate_article 模式 + llm_proxy 集成` | 1d | #N3 + #N4 | generate_via_llm + max 2 轮重试 + 测试（mock LLM） |
| **#N6** | `feat(journal): 4 个 LLM 工具 + HTTP 路由 + Profile 白名单` | 1d | #N1-#N5 | 4 个 `office_journal_*_tool` + `office_routes` 新段 + profile wiring + 工具测试 |
| **#N7** | `feat(journal): 前端侧边面板 (upload + spec + 编辑 + 生成 + 校验)` | 2d | #N6 | `apps/web/src/features/journal/*` + IPC bridge + E2E |
| **#N8** | `feat(journal): E2E tier-1 gate + 文档` | 0.5d | #N7 | 3 个 critical flow 进 ci.yml gate + `docs/technical/55` + `docs/user-manual/11` |

**总计**：**8.5d**（单一 PR ≈ 1 天，实际会因为 review/feedback 多 1-2 天）。

## 13. Win7 兼容性（`release/win7` 分支）

`.claude/CLAUDE.md` 规定：`release/win7` 长期支持到 2027-12-13，Python 3.8 + pydantic 1.x。

| 风险点 | 影响 | 应对 |
|---|---|---|
| `pandoc` 3.8 默认安装路径 | Win7 用户需手动装 | spec 文档写明"win7 需 pandoc ≥3.0"；`pandoc_adapter` 检测不到时返清晰错误 |
| `python-docx` 1.1.2 已在 win7 requirements-py38.txt | OK | 无 |
| `httpx`（LLM 工具调 chat API） | win7 requirements-py38.txt 是否含？ | 在 PR #N5 实施前先 grep 确认；缺失则 cherry-pick 时一并加 |
| 前端 Electron21.4.4 | win7 主线已用 | OK |
| SQLite schema migration | win7 路径一致 | 无 |

**cherry-pick 计划**：`#N1` ~ `#N8` 全部**默认不** cherry-pick 到 win7（v1 先在 main 验证）；若 win7 用户有需求，按 PR #508 同样的 py38 compat check 跑一遍 + 手工补齐差异（PEP 604/585 + pydantic v1/v2 差异）。

## 14. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| LLM 生成内容质量低 | 高 | 用户体验差 | validator 仅报违规不阻断；UI 显式标"AI 起草 + 人工审阅" |
| pandoc 转换丢格式 | 中 | spec 提取失真 | `parser.py` 不假设完美；启发式 + 多级 fallback；解析失败明确报错而非默默接受坏 spec |
| WPS/Word 字体名差异致校验误报 | 高 | 用户困惑 | 字体族归一化（第 6.2 节）；容差 ±0.5pt；UI 提供"忽略该条规则"操作 |
| 模板过复杂导致 spec 解析 > 1s | 低 | 用户感知卡顿 | 性能预算 500ms；spec 缓存 sha256；UI 显示进度 |
| LLM API 调用超时 | 中 | 生成失败 | httpx 30s timeout；失败时降级为"先返回 LLM 部分输出 + 违规提示" |
| 模板含宏/嵌入对象 | 中 | parser 崩 | `_validate_docx_zip` 已有；另加 ZIP member 类型白名单（只读 document.xml/styles.xml/numbering.xml/theme1.xml/settings.xml） |
| 模板超大段落（单段 >5000字） | 低 | validator 全段扫卡顿 | validator 内部按段落流式处理，单条规则 check 限时 100ms |

## 15. 文档交付

| 文档 | 路径 | 内容 |
|---|---|---|
| **Spec（本设计）** | `docs/superpowers/specs/2026-09-10-journal-template-article-generation-and-validation-design.md` | 完整设计（本文件） |
| **技术手册** | `docs/technical/55-journal-template-subsystem.md` | PR #N8 合并后写；面向开发者，API、架构、规则提取算法详解、Win7 适配 |
| **用户手册** | `docs/user-manual/11-journal-template-panel.md` | PR #N8 合并后写；面向最终用户：如何上传模板、编辑内容、运行校验、解读违规 |
| **CHANGELOG** | `CHANGELOG.md` | 每 PR 一行，Keep a Changelog 格式 |

## 附录 A：与现有 office 子系统的对比

| 维度 | 现有 `word_template.py` / `template_library.py` | 新 `journal/` 子包 |
|---|---|---|
| 模板类型 | 短文（周报/会议纪要/简历） | 学术期刊长文 |
| 占位符语法 | docxtpl `{{var}}` + Jinja 控制 | 同上 + 结构化 sections JSON |
| 样式合规 | ❌ 不检查 | ✅ 自动校验（fonts/spacing/margins/citations） |
| `.doc` 摄入 | ❌ 仅 `.docx` | ✅ pandoc 自动转换 |
| 长度约束 | ❌ | ✅ abstract ≤300、keywords 3-8、section 段落数 3-7 |
| 章节大纲 | ❌ | ✅ outline level + 关键词启发式 |
| LLM 一键生成 | ❌ | ✅ 调 llm_proxy，最长 2 轮自纠 |
| 专用 UI | ❌ 复用 Office artifacts panel | ✅ 独立侧边面板 |
| 持久化 | `BUILTIN_TEMPLATES` 静态 + `<workspace>/office/templates/` | workspace 本地 + SQLite 元数据 |

## 附录 B：Open Questions（实施时再确认）

- [ ] 字体族归一化白名单覆盖是否够？是否需要更激进的 fallback（任何衬线字体归"宋体族"）？
- [ ] 章节识别关键词白名单从 20 条扩到 ~50 条是否值得？
- [ ] 是否要把 pandoc 进程超时做成可配置（不同模板大小不同）？
- [ ] 是否在前端面板加"忽略某条规则"白名单（用户长期接受某违规）？
- [ ] LLM 提示词模板是否需要支持多语言（中英双语）？