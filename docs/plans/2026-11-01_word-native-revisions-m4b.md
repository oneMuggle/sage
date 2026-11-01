# Word M4b：原生修订写入

> 日期：2026-11-01 · 分支：`feat/word-native-revisions`
> 基线：`origin/main` = `a694ed544`（M4a 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M4）

## 1. 目标

把审校/修复计划写成 Word/WPS 可识别的**原生修订**：

- `w:del`（删除旧文本）+ `w:ins`（插入新文本），带 author/date/id；
- 可选 `add_comment` 批注（复用现有 comments part 写入）；
- 默认输出 `<stem>-revised.docx`，`overwrite=true` 原子替换；
- 未显式给 changes 时，从规则包审校结果自动生成计划：
  - `content.terminology`：variant → preferred；
  - `content.date_format`：实际日期样本 → 期望格式；
  - 仅处理 `fixable=true` 的规则与 issue；
- 修订后用同一规则包复检，返回 `remaining`。

## 2. 接口

```http
POST /api/v1/office/word/audit/revise
```

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "rulepack": {"id": "...", "name": "...", "rules": [...]},
  "changes": [{"rule_id": "content/terminology", "find": "AI", "replace": "人工智能", "comment": "统一术语"}],
  "output_filename": "doc-revised.docx",
  "overwrite": false,
  "author": "Sage",
  "add_comments": true
}
```

`changes` 省略时由服务端根据 `rulepack` 审校结果生成；无可用计划 → 422。

响应：`planned/applied/skipped`、逐条 `changes[{find,replace,comment,applied,reason}]`、
`output_path/overwritten`、`remaining`（修复后复检）与 `warnings`。

## 3. 实现要点

- `word_revision_writer.py`：
  - 定位首个包含 `find` 的段落（正文/表格单元格，复用 edit 的定位器）；
  - 按字符偏移切分 run，保留首个受影响 run 的 `rPr`；
  - `w:del` 内每个受影响 run 用 `w:delText`，`w:ins` 内写替换文本（`\n` → `w:br`）；
  - revision id 从现有 `w:ins/w:del` 最大值递增；
  - 批注在替换前添加（锚定整段），失败只产生 warning，不阻塞修订；
  - 输出安全：拒绝路径分隔符/非 .docx/覆盖源文件/已存在文件；overwrite 原子替换。
- `build_revision_plan`：术语 issue 的 `actual` 按逗号拆分逐个 variant；日期 issue 解析数字并格式化为期望样式；其他 kind 暂不自动修订。

## 4. 已知限制

- `python-docx` 的 `paragraph.text` 不包含 `w:ins` 内容、也不包含 `w:delText`，
  因此修订后的结构化预览/审校看不到“待接受的新文本”；Word/WPS 打开可见。
- 只处理段落直接子级的普通 run；超链接/域等复杂结构中的文本暂不支持。
- 批注锚定整段而非精确字符范围。

## 5. 实施步骤

- [x] 模型：`WordRevisionChange` / `WordRevisionResult`
- [x] 写入模块：tracked replace + comments + 计划生成
- [x] 路由 `/audit/revise` + 复检
- [x] 测试：writer 7 项 + 路由 4 项
- [x] 文档：119 修订章节/测试/限制 + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 6. 验收

- 术语/日期问题可生成 `w:ins/w:del`，author/date 正确；
- 批注可写入 comments part；批注失败不阻塞修订；
- overwrite 二次修订因旧文本已进入 delText 而安全跳过；
- 修订后复检不再报同一问题；
- 非法输出/越界/超限文件被拒绝。

## 7. 非目标

- 修订视图与逐条接受/拒绝 UI（M4c）；
- LLM 语义修订建议；
- 超链接/域/复杂 run 的修订；
- 表格结构级修订。
