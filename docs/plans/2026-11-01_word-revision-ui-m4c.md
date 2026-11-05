# Word M4c：修订生成前端入口

> 日期：2026-11-01 · 分支：`feat/word-revision-ui`
> 基线：`origin/main` = `a1068cc7b`（M4b 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M4）

## 1. 目标

把 M4b 的原生修订写入接到 `/office` 审校面板：

- 「生成修订」按钮：按当前规则包审校结果自动生成修订计划并写入；
- 「添加批注」开关（默认开）；
- 结果区展示 `applied/skipped`、输出路径、逐条 `find → replace`（失败原因）与复检计数；
- 默认输出 `<stem>-revised.docx`；失败（如无可修订 issue）展示错误。

本阶段不做逐条接受/拒绝与修订 diff 视图（后续 M4d/M5）。

## 2. 涉及文件

| 文件 | 作用 |
|---|---|
| `src/shared/api/wordAuditTypes.ts` | 修订请求/结果类型 |
| `src/shared/api/officeWordAuditApi.ts` | `reviseWord` |
| `electron/commandRoutes/office.ts` | `office_word_revise`（rawBody 保护 changes/pack params） |
| `electron/ipc-manifest.json` | 重新生成 |
| `src/features/office/wordAuditFilename.ts` | `defaultRevisedName` |
| `src/features/office/DocumentAuditPanel.tsx` | 按钮/批注开关/结果区 |
| `src/features/office/__tests__/DocumentAuditPanel.test.tsx` | 修订相关测试 |

## 3. 交互

1. 审校完成后点「生成修订」；
2. 服务端按规则包派生修订计划（术语/日期等 fixable 项）；
3. 面板显示已写入/跳过数量、输出路径、逐条变更与复检计数；
4. 取消「添加批注」则不写 comments；
5. 无可修订项时后端 422，前端展示错误；
6. `overwrite` 由 M4b 支持，但本阶段面板默认只写新文件（覆盖模式留给后续 UI）。

## 4. 实施步骤

- [x] 类型 + API 客户端
- [x] IPC 命令 + manifest
- [x] 面板按钮/批注开关/结果区
- [x] 测试：修订成功、批注关闭、结果展示
- [x] 文档：119 前端章节 + README
- [x] 门禁：tsc / eslint / prettier / vitest / IPC 契约 / CI

## 5. 验收

- `/office` 审校面板有「生成修订」按钮；
- 成功显示 applied/skipped、输出路径与逐条变更；
- 关闭批注时请求 `add_comments=false`；
- 错误（无可修订项/后端失败）可见；
- TypeScript、ESLint、Vitest、IPC 契约全绿。

## 6. 非目标

- 修订 diff / 逐条接受拒绝 UI；
- 覆盖模式开关；
- 自定义 changes 编辑；
- LLM 语义修订。
