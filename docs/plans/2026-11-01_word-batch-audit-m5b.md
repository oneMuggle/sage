# Word M5b：批量审校与报告

> 日期：2026-11-01 · 分支：`feat/word-batch-audit`
> 基线：`origin/main` = `b32733350`（M5a 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M5）

## 1. 目标

在工作区内批量审校 `.docx` 并生成报告：

- 文件来源：显式 `file_paths` 或 glob `pattern`（默认 `**/*.docx`）；
- 跳过隐藏目录与 `.git/.sage/node_modules/dist/...` 等构建目录；
- 逐文件大小上限；解析失败/超限记为失败文件，不中断整批；
- 汇总文件数、通过/失败、错误/警告总数；
- 可选 Markdown 报告（JSON 结果始终返回）。

只读：不修改任何文档、不生成 PDF。

## 2. 接口

```http
POST /api/v1/office/word/audit/batch
```

```json
{
  "workspace_path": "/ws",
  "file_paths": ["docs/a.docx", "docs/b.docx"],
  "pattern": "**/*.docx",
  "max_files": 20,
  "rulepack_id": "general-quality",
  "include_report": true,
  "max_size_bytes": 52428800
}
```

`file_paths` 优先；否则按 `pattern` 扫描。响应含 `totals`、`files[]`
（source_path/ok/issue_count/error_count/warning_count/issues/warnings/error）
与 `report_markdown`。

`ok` = 无失败文件且错误级 issue 为 0。

## 3. 报告格式

```markdown
# Word 批量审校报告

- 工作区: `/ws`
- 规则包: `general-quality`（Word 通用质量检查）
- 文件: 2（通过 2 / 失败 0）
- 问题: 3 错误 / 1 警告

## ✅ docs/a.docx
- 0 错误 / 0 警告

## ❌ docs/b.docx
- 3 错误 / 1 警告
- [error] content/placeholder_residue: …
```

单文件最多列 20 条 issue，超出提示剩余数量。

## 4. 实施步骤

- [x] 模型：批量文件结果/汇总/总结果
- [x] 引擎：文件收集、逐文件审校、Markdown 报告
- [x] 路由 `/audit/batch`
- [x] 测试：收集/越界/模式/汇总/失败文件/大小上限 + 路由
- [x] 文档：121 批量章节 + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 5. 验收

- 显式列表与 glob 均可用，隐藏/构建目录被跳过；
- 单个坏文件不会中断整批；
- 汇总与 Markdown 报告正确；
- 路径越界/非法 pattern 被拒绝；
- 旧单文档接口行为不变。

## 6. 非目标

- 批量修复/修订；
- 报告导出为 docx/PDF；
- 前端批量面板（M5c 之后）；
- 渲染级批量校验（可后续按文件复用 M5a）。
