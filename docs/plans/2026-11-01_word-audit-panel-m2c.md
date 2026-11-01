# Word M2c：前端审校面板与点击定位

> 日期：2026-11-01 · 分支：`feat/word-audit-panel`
> 基线：`origin/main` = `ed07cc492`（M2b 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M2）

## 1. 目标

把 M2a/M2b 的后端能力接到 `/office` 页面：

- Word 预览工具栏新增「规则审校」开关；
- `DocumentAuditPanel`：规则包选择、自动审校、严重级别过滤、issue 卡片（期望/实测/来源/修复建议）；
- 点击 issue → 结构化 `WordPreview` 滚动到对应段落并高亮；
- 一键修复：默认输出 `<stem>-fixed.docx`，可勾选覆盖原文件；展示 before/after 与复检剩余问题；
- IPC 桥新增 4 个命令并重新生成 `electron/ipc-manifest.json`。

## 2. 涉及文件

| 文件 | 作用 |
|---|---|
| `src/shared/api/wordAuditTypes.ts` | 规则包/审校/修复类型 |
| `src/shared/api/officeApi.ts` | `listWordRulePacks/auditWord/fixWord` |
| `electron/commandRoutes/office.ts` | 4 个 IPC 路由（audit/fix 用 rawBody 保护规则 params） |
| `src/features/office/DocumentAuditPanel.tsx` | 审校与修复面板 |
| `src/features/office/wordAuditFilename.ts` | 默认修复文件名 |
| `src/features/office/OfficeStructuredPreviews.tsx` | `WordPreview` 段落锚点/高亮/自动扩展渲染窗口 |
| `src/features/office/OfficePreviewPanel.tsx` | word 工具栏开关、定位回调、面板挂载 |
| `src/features/office/index.ts` | barrel 导出 |

## 3. 交互

1. 打开 word 文档预览 → 点「规则审校」→ 自动以 `general-quality` 审校；
2. 规则包下拉切换后自动重跑；
3. 过滤「全部 / 错误 / 警告」；
4. 点 issue（有 `anchor.paragraph_index`）→ 关闭高保真视图 → 结构化预览滚动并高亮段落；
5. 「一键修复」：
   - 默认写 `<stem>-fixed.docx`，展示 `fixed_count`、输出路径、复检计数与逐规则修复数；
   - 勾选「覆盖原文件」→ 原子覆盖并触发父级重新读取；
6. 不可修复问题继续留在 issue 列表/复检结果中。

## 4. 实施步骤

- [x] 类型与 API 客户端
- [x] IPC 路由 + manifest 重新生成
- [x] `DocumentAuditPanel`
- [x] `WordPreview` 锚点高亮
- [x] `OfficePreviewPanel` 集成
- [x] 测试：面板 6 项 + WordPreview 3 项 + IPC/预览回归
- [x] 文档：119 增补前端章节 + README
- [x] 门禁：tsc / eslint / vitest / backend IPC 契约 / CI

## 5. 验收

- `/office` 打开 word 文档可看到「规则审校」；
- 审校结果显示错误/警告计数与带锚点 issue；
- 点击 issue 后结构化预览滚动并高亮对应段落；
- 修复默认生成新文件，覆盖模式刷新预览；
- TypeScript、ESLint、Vitest、IPC 契约测试全绿。

## 6. 非目标

- 规则包编辑器/规则抽取 UI（M3）；
- 原生 docx 渲染视图中的段落定位（docx-preview DOM 不暴露稳定段落索引）；
- 表格/单元格级定位；
- 语义修订视图（M4）。
