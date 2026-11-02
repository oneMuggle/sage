# Word M2b：确定性修复与自动复检

> 日期：2026-11-01 · 分支：`feat/word-rulepack-fix`
> 基线：`origin/main` = `3b14a52df`（M2a 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M2）

## 1. 背景与目标

M2a 已能按规则包产出带锚点的确定性 issue，但只能“发现问题”。M2b 补齐
“能机械修的自动修 + 修完复检”：

- 新增 `/office/word/audit/fix`：按规则包执行确定性修复，输出新文件或原地覆盖；
- 修复仅覆盖可机械判定且可无损修改的项：页面、样式、连续空段落、页码域；
- 修复后自动用同一规则包复检，返回 `remaining`；
- 幂等：对已修复文档再次修复，`fixed_count=0` 且复检结果不变；
- 不可机械修复的项（占位符、标题编号、题注/引用连续性）保留在 `remaining`。

## 2. 修复器

| kind | 修复动作 | 规则需 `fixable=true` |
|---|---|---|
| `page.size` | 所有节设为 A4/Letter（保留方向） | 是 |
| `page.orientation` | 交换宽高并设置方向枚举 | 是 |
| `page.margins` | 设置上下左右边距 | 是 |
| `page.page_number` | 缺失时插入 PAGE 域；设置 pgNumType 格式 | 是 |
| `style.font` | 设置样式字体（含 eastAsia）、字号、粗体等 | 是 |
| `style.paragraph` | 设置样式行距/首行缩进/对齐 | 是 |
| `content.empty_paragraphs` | 删除超出上限的空段落（从后往前删） | 是 |

其余 kind 即使标记 `fixable=true` 也只产生 `fix_unsupported_kind` warning，不写文档。
内置 `general-quality` 的 `content/empty_paragraphs` 改为 `fixable=true`。

## 3. 接口

`POST /api/v1/office/word/audit/fix`

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "rulepack_id": "gb-t-9704-general",
  "output_filename": "doc-fixed.docx",
  "overwrite": false
}
```

- `overwrite=false`（默认）：输出 `output_filename`（缺省 `<stem>-fixed.docx`），
  不允许覆盖已有文件或源文件；
- `overwrite=true`：临时文件 + 原子替换源文件；此时不能同时给 `output_filename`；
- 修复后复检结果放在 `remaining`（完整 `WordAuditResult`）。

响应：

```json
{
  "ok": true,
  "source_path": "doc.docx",
  "output_path": "doc-fixed.docx",
  "overwritten": false,
  "rule_pack_id": "gb-t-9704-general",
  "actions": [{"rule_id": "page/margins", "kind": "page.margins", "fixed_count": 4, "message": "..."}],
  "fixed_count": 7,
  "before": {"rules_checked": 5, "issue_count": 5, "error_count": 5, "warning_count": 0, "paragraphs": 1, "tables": 0, "sections": 1},
  "remaining": {"ok": true, "issues": []},
  "warnings": []
}
```

## 4. 安全约束

- 工作区围栏 + 50 MiB 上限（与审校一致）；
- 输出名不允许路径分隔符，必须以 `.docx` 结尾；
- 默认不覆盖源文件；overwrite 原子替换并带 Windows 文件锁退避重试；
- 修复器只改目标属性，不动其他内容；不执行任何语义改写。

## 5. 实施步骤

- [x] 模型：`WordFixAction` / `WordAuditFixResult`
- [x] 引擎：`backend/office/word_fix.py`（修复器注册表 + 原子写）
- [x] 内置包：`content/empty_paragraphs` 标记可修复
- [x] 路由：`POST /office/word/audit/fix`
- [x] 测试：单测 7 项 + 集成 4 项（含幂等/覆盖/安全）
- [x] 文档：119 增补 fix 小节 + README 行
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 6. 验收

- 默认 Letter/Calibri 文档经 GB 包修复后：A4、页边距、仿宋三号、页码域全部满足；
- 原始文件在非 overwrite 模式下零改动；
- 连续修复两次，第二次 `fixed_count=0`；
- 不可修复 issue 保留且 `ok=false`；
- 非法输出名/已存在输出/越界路径/超限文件被拒绝。

## 7. 非目标

- 前端一键修复入口（M2c）；
- 语义修复、原生修订（M4）；
- 标题编号/题注/引用的自动重排（保留给后续增强）；
- 表格/内容控件级修复。
