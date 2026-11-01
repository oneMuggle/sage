# Word M2a：规则包与确定性审校

> 日期：2026-11-01 · 分支：`feat/word-rulepack-audit`
> 基线：`origin/main` = `190a6c9b5`（M1c 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M2）

## 1. 背景与目标

M0/M1 已提供 Word `DocumentProfile`（只读事实源）与模板 Profile/填充。M2 解决
第二个使用场景：**读取规范文档 → 提取/编译规则 → 审校目标文档并定位问题**。

本阶段（M2a）只做确定性部分：

- `RulePack` / `Rule` 模型与三层存储：内置、工作区（`.sage/word-rulepacks`）、请求内联；
- 规则编译器/检查器注册表，覆盖页面、样式、结构、内容四类可机械判定项；
- Issue 扩展：锚点、期望/实测、来源、可修复标记；
- 内置规则包：GB/T 9704 通用版面参数 + 通用质量检查；
- REST：规则包列表/详情/保存/删除 + 文档审校。

非目标（后续里程碑）：

- 确定性修复执行与复检（M2b）；
- 前端 `DocumentAuditPanel`、点击定位/高亮（M2c）；
- 规范/范本文档 → 规则抽取（M3）；
- 语义审校与原生修订（M4）；渲染级校验（M5）。

## 2. 规则模型

```json
{
  "id": "page/margins",
  "title": "页边距符合公文通用参数",
  "description": "GB/T 9704 通用页边距",
  "category": "page",
  "severity": "error",
  "kind": "page.margins",
  "params": {"top_cm": 3.7, "bottom_cm": 3.5, "left_cm": 2.8, "right_cm": 2.6, "tolerance_cm": 0.1},
  "source": "GB/T 9704-2012（通用参数摘要）",
  "fixable": true,
  "fix_hint": "在页面设置中把边距改为上 3.7 / 下 3.5 / 左 2.8 / 右 2.6 cm"
}
```

- `kind` 决定检查器；未知 kind 在审校前直接 422；
- 同一规则可对多处产出多条 issue（如逐页边距、逐段空行）；
- `source` 用于追溯标准/范本来源；内置 GB/T 9704 包只收录通用参数，不复制标准全文。

## 3. 检查器（M2a）

| kind | 作用 | 锚点 |
|---|---|---|
| `page.size` | 纸张 A4/Letter | 节 |
| `page.orientation` | 纵向/横向 | 节 |
| `page.margins` | 上下左右页边距与容差 | 节 |
| `page.page_number` | 页码域存在/页码格式 | 节 |
| `style.font` | 样式字体（西文/中文）、字号、粗体等 | 样式的首个使用段落 |
| `style.paragraph` | 样式行距、首行缩进、对齐 | 样式的首个使用段落 |
| `structure.heading_sequence` | 多级标题编号连续/前缀存在 | 标题段落 |
| `structure.required_headings` | 必含章节标题 | 文档 |
| `content.placeholder_residue` | 未解析 `{{}}`/`<<>>`/`[[ ]]`/`【】`/交叉引用占位符 | 段落 |
| `content.empty_paragraphs` | 连续空段落超限 | 空行起点段落 |
| `content.caption_sequence` | 图/表题注编号连续 | 题注段落 |
| `content.citation_coverage` | 引用标记编号缺号 | 首个引用段落 |

## 4. 接口

- `GET /api/v1/office/word/rulepacks?workspace_path=...`
- `GET /api/v1/office/word/rulepacks/{pack_id}?workspace_path=...`
- `POST /api/v1/office/word/rulepacks`（保存工作区规则包，不允许覆盖内置）
- `DELETE /api/v1/office/word/rulepacks/{pack_id}?workspace_path=...`
- `POST /api/v1/office/word/audit`

审校请求：

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "rulepack_id": "gb-t-9704-general",
  "rulepack": null
}
```

`rulepack`（内联）优先于 `rulepack_id`；两者都缺省时使用 `general-quality`。

响应 issue 附带 `anchor`（`WordTextAnchor`）与 `scope`，供 M2c 前端定位。

## 5. 实施步骤

- [x] 模型：`word_rulepack_models.py`
- [x] 内置规则包：`word_rulepack_builtin.py`（GB/T 9704 通用 + 通用质量）
- [x] 存储：`word_rulepack_store.py`（内置/工作区/内联）
- [x] 审校引擎：`word_audit.py`（注册表 + 12 个检查器 + 锚点）
- [x] 路由：`office_word_audit_routes.py` 并注册到 `office_routes.py`
- [x] 单元测试：规则包 CRUD、各检查器、锚点、未知 kind
- [x] 集成测试：列表/详情/保存/删除/审校
- [x] 文档：`docs/technical/119-word-rulepack-audit.md` + README 行
- [x] 门禁：ruff / py38 / architecture / 相关 pytest / CI

## 6. 验收

- 内置包可列出并审校；工作区包可保存/加载/删除，内置包不可覆盖；
- 页面、样式、结构、内容规则在样本上正确报错，且 issue 带锚点或明确的文档级 scope；
- 干净文档返回 `ok=true`；
- 未知 `kind`、缺失参数、越界路径、超大文件均被拒绝；
- 旧 `/word/lint`、`/word/repair` 行为零变化。

## 7. 风险

- 字体名（如“仿宋_GB2312” vs “仿宋”）存在实现差异：内置包使用标准常见名，误报可通过自定义规则包调整；
- 内容控件/表格内文本在 `DocumentProfile.paragraphs` 不可见：M2a 对占位符补充扫描 `w:sdt`，表格规则留到 M2b；
- 双次解析 docx（Profile + 原始 Document）：审校非热路径，先保证正确性。
