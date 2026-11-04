# Word M3c：规则抽取复核 UI

> 日期：2026-11-01 · 分支：`feat/word-rule-review-ui`
> 基线：`origin/main` = `2d875b2b5`（M3a 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M3）

## 1. 目标

把 M3a 的抽取 API 接到 `/office` 页面，形成可复核的闭环：

- 选择规范/范本文档 → 抽取候选规则；
- 展示规则标题、参数、置信度、来源摘录与冲突标记；
- 逐条启停 / 全部启停；
- 保存启用项为工作区规则包（后端强制来源非空）；
- 抽取失败、冲突、warning 如实展示。

## 2. 涉及文件

| 文件 | 作用 |
|---|---|
| `src/shared/api/wordAuditTypes.ts` | 抽取结果/候选/冲突/请求类型 |
| `src/shared/api/officeWordAuditApi.ts` | `extractWordRules` / `saveExtractedRulePack` |
| `electron/commandRoutes/office.ts` | 2 个 IPC 命令（rawBody 保护规则 params） |
| `electron/ipc-manifest.json` | 重新生成 |
| `src/features/office/WordRuleExtractionPanel.tsx` | 复核面板 |
| `src/pages/Office.tsx` | 挂载面板 |

## 3. 交互

1. 选择抽取类型（规范文档 / 范本模板）与文件路径（文本输入、原生选择、拖拽）；
2. 填写规则包 id/名称，点击「抽取规则」；
3. 结果区展示 `N 条规则 · M 个冲突 · K 个警告` 与源文件；
4. 冲突以黄色警示块展示 kind/消息/涉及规则；warning 列表；
5. 每条候选：启用勾选、标题、规则 id、置信度、冲突徽章、来源摘录、params JSON；
6. 「全部停用/全部启用」；「保存规则包（N 条）」仅保存启用项；
7. 保存成功显示规则包 id 与条数；无启用规则时拒绝保存。

## 4. 实施步骤

- [x] 类型 + API 客户端
- [x] IPC 路由 + manifest
- [x] `WordRuleExtractionPanel`
- [x] `/office` 挂载
- [x] 测试：面板 5 项 + Office/IPC 回归
- [x] 文档：120 增补前端章节 + README
- [x] 门禁：tsc / eslint / prettier / vitest / IPC 契约 / CI

## 5. 验收

- `/office` 页面可看到「Word 规则抽取」面板；
- 抽取后候选规则带置信度/来源/冲突标记；
- 启停后保存只包含启用规则；
- 无来源规则无法保存（后端 422，前端展示错误）；
- TypeScript、ESLint、Vitest、IPC 契约测试全绿。

## 6. 非目标

- 规则参数在线编辑（先用固定参数 + 启停复核；M3c+ 再补）；
- 规则包版本对比/导出/导入；
- 规则「试运行」按钮（可直接用 M2c 审校面板选择已保存规则包）；
- LLM 语义候选（M3b）。
