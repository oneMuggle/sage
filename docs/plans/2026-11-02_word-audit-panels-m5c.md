# Word M5c：批量审校与渲染审计前端面板

> 日期：2026-11-02 · 分支：`feat/word-audit-panels-m5c`
> 基线：`origin/main` = `707796377`（M6b 合并后）
> 上游能力：M5a `POST /office/word/audit/render`、M5b `POST /office/word/audit/batch`

## 1. 目标

把已经具备后端能力、但目前只能通过 LLM 工具触达的两项能力做成前端面板：

| 面板 | 位置 | 后端 |
|---|---|---|
| 渲染级校验（`WordRenderAuditSection`） | Word 预览 → 「规则审校」面板底部 | `POST /api/v1/office/word/audit/render` |
| 批量审校（`WordBatchAuditPanel`） | `/office` 页工作区底部面板区 | `POST /api/v1/office/word/audit/batch` |

- 渲染校验：可选 A4/Letter、页码要求、字体白名单、四边边距；无转换器时展示降级原因而不是报错；
- 批量审校：glob / max_files / 规则包；汇总计数 + 逐文件问题 + Markdown 报告折叠展示。

## 2. 涉及文件

- `electron/commandRoutes/office.ts`：+2 路由（`office_word_audit_batch`、`office_word_audit_render`，均 rawBody）；
- `electron/ipc-manifest.json`：`npm run ipc:manifest` 重新生成；
- `src/shared/api/wordAuditTypes.ts`：批量/渲染结果与请求类型；
- `src/shared/api/officeWordAuditApi.ts`：`batchAuditWord` / `renderAuditWord`；
- `src/features/office/WordBatchAuditPanel.tsx`（新）：批量审校面板；
- `src/features/office/WordRenderAuditSection.tsx`（新）：渲染校验区块；
- `src/features/office/DocumentAuditPanel.tsx`：挂载渲染校验区块；
- `src/pages/Office.tsx`：挂载批量审校面板；
- 测试：两个新组件测试 + `DocumentAuditPanel` 既有测试扩展；
- 文档：119 增补 M5c 一节。

## 3. 技术方案

- 两个新组件沿用 `DocumentAuditPanel` 的硬编码中文 + `data-testid` 风格，不引入 i18n 依赖；
- 渲染校验默认**不自动运行**（依赖 LibreOffice，代价高），由按钮触发；
- 批量审校一次调用返回全量结果，前端只负责展示并按需截断列表渲染（单文件问题最多展示 20 条）；
- IPC 均使用 `rawBody`：`margins_cm` / `rulepack` 属于用户数据，禁止 camelCase 重写。

## 4. 实施步骤

- [x] 计划文档（本文件）
- [x] 类型 + API 客户端
- [x] Electron IPC 路由 + manifest 重新生成
- [x] `WordRenderAuditSection` + 挂载到 `DocumentAuditPanel`
- [x] `WordBatchAuditPanel` + 挂载到 `/office` 页
- [x] 组件测试（渲染降级 / 批量汇总 / 错误路径）
- [x] 文档 121 §7 + 122 §4 + README 索引
- [x] 门禁：typecheck / eslint / vitest / architecture / IPC 契约

## 5. 验收

- Word 预览打开「规则审校」后可运行渲染校验；无转换器时显示「未渲染」与原因；
- `/office` 页可运行批量审校，展示汇总、逐文件状态与 Markdown 报告；
- 工作区为空 / 无 .docx 时给出空状态提示，不报错；
- 后端契约测试（manifest ↔ 路由）通过。

## 6. 非目标

- Win7 同步；
- 批量结果一键修复 / 批量修订；
- 规则包参数编辑与导入导出。
