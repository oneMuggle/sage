# 55 — Word 版式引擎 FormatSpec（Round 7）

> 日期: 2026-09-11 · 分支: `feat/word-format-spec-engine` · 方案:
> `docs/plans/2026-09-11_word-format-spec-round7-plan.md`
> 系列: Word 写作能力增强 P0（项目文档/期刊论文/内部资料写作场景）

## 1. 问题

`generate_docx`（`backend/office/word.py`）历史实现从空白文档堆叠标题/段落，
格式仅两项全局字体。期刊论文、项目文档、公文类写作有硬性格式要求（页边距/
行距/页眉页脚/页码/标题样式），此前只能靠 LLM 在 prompt 里"口头约定"，生成
后无法保证；docxtpl 模板填充虽可保证版式，但要求"先有模板文件"。

## 2. 方案："版式即配置"

把格式要求结构化为可选参数 `format_spec`，由确定性代码注入文档：

```
OfficeWordGenerateRequest.format_spec: WordFormatSpec (models.py, 纯 pydantic)
        │
        ▼
word_layout.apply_format_spec(doc, spec)   ← word.py generate_docx 惰性调用
        │  page    → sections[0] 纸张/方向/页边距
        │  body    → Normal 样式（字号/行距/首行缩进/段距/对齐）
        │  title   → Title 样式
        │  headings→ Heading 1-3 样式（h1/h2/h3 键）
        │  header  → 页眉文本 + 对齐
        │  footer  → 页脚 + PAGE 域（w:fldSimple，Word/WPS/LibreOffice 免更新渲染）
        ▼
styles.xml / document.xml
```

关键设计约定：

1. **全字段 Optional，None = 该项不设置**。不传 `format_spec` 时生成结果与
   历史版本行为一致（测试锁定默认页边距/方向/页眉页脚未触碰）。
2. **模型与引擎分离**：FormatSpec 系列 pydantic 模型放在 `models.py`
   （零 docx 依赖），应用逻辑在 `word_layout.py`（惰性导入）——维持
   `scripts/verify-office-paths.py` canary "models 仅依赖 pydantic" 的前提。
3. **样式补丁只动字号/加粗/颜色/间距/对齐**；字体（rFonts）仍由
   `set_doc_default_font` 统一负责，两条路径不互相覆盖。
4. **颜色写入时清除 `w:themeColor` 等 theme 属性**——与
   `_patch_style_rfonts` 清 theme 引用同理，theme 属性优先级高于显式值，
   不清掉部分渲染端会忽略显式颜色。
5. **数值边界是合理性钳制**（字号 1-72 磅、边距 0-10 厘米、行距 1.0-3.0 倍），
   防 LLM 传 9999 磅字号，不是排版学约束。

## 3. 接入面（三条通路全覆盖）

| 通路 | 接入点 |
|---|---|
| REST | `POST /api/v1/office/word/generate` 请求体新增 `format_spec`（pydantic 自动解析） |
| Agent 工具（直通路径） | `office_create` 的 `content.format_spec`（JSON Schema 已声明，dict 直达请求模型） |
| Agent 工具（受管路径） | `tool_service._coerce_word_request` 显式透传 `format_spec` |

writer profile 的 system prompt 同步提示：用户明示的硬性格式要求应映射进
`content.format_spec`，而不是写进正文。

前端 IPC 契约（`src/shared/api/types.ts`）按 models.py 的同步要求补充
`WordFormatSpec` 系列接口与 `OfficeWordGenerateRequest.format_spec?` 可选
字段；本轮不新增前端 UI（表单可后续再加版式选择器）。

## 4. Win7 对齐

新功能，**不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。但 office
栈在 win7 有捆绑，因此：零新增依赖（纯 python-docx + oxml）；新代码沿用
`typing.Optional/List` 注解风格，降低未来 backport 成本。

## 5. 测试

`backend/tests/integration/test_office_word_format_spec.py`：向后兼容
（不传 spec 行为不变）、页边距/横向 A4（EMU 回读）、正文/标题样式补丁
（含 theme 属性清除断言）、页眉文本、页脚 PAGE 域、pydantic 校验拒绝
（额外键/越界/坏颜色/h4 键）、工具链路端到端。

## 6. 后续（Word 增强系列）

- Round 8（P1）: 行内插图 + 题注自动编号、三线表/合并单元格/表头跨页、
  多级标题自动编号
- Round 9（P2）: 引用体系（文献库 + GB/T 7714 formatter + 文中引用 +
  参考文献表）
- Round 10（P3）: docx 格式 Linter（对照 FormatSpec 校验产出 + 一键修复）、
  `paper-writing` / `report-writing` 技能
