# R117 Message 审计辅助函数抽离规格

- 日期：2026-10-28
- 基线：`main` `5cd4d5871ce645510f5949966b70d6784fd58e6e`
- 状态：已开 PR（#2623），待合并
- 编号说明：R117 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R116 起对热点文件做纯机械抽离的卫生系列。
  `src/widgets/chat/Message.tsx`（787/800，归属弧
  R111/R113 的转录展示文件）尾部导出两个与渲染无关的
  审计格式化纯函数，是全文件仅有的非组件导出，长期挂
  两条 react-refresh/only-export-components 存量警告
  （实施时以 ESLint 实测为准），且无任何生产调用方
  （仅 Message.test 动态导入）。本轮原样抽离，行为不
  变，不夹带功能。

## 1. 抽离清单（原样搬移）

- 新 `src/widgets/chat/messageAudit.ts`（命名随同目录
  camelCase 非组件模块惯例），承接
  `formatMessageAuditSummary` 与
  `formatMessageAuditJson`（约 19 行）。
- `Message.tsx` 删除尾部两函数后仅导出组件，文件
  实测 787 → 768 行；`Message.test.tsx` 的一处动态导入
  改指新模块。无 barrel 再导出涉入（chat/index.ts 未
  转发这两函数，取证于基线全量 grep）。

## 2. 边界

- 纯重构：渲染输出与转录归属标注（R111/R113）不动；
  后端、IPC 与导出格式不变。
- Win7 待对齐（无后端新代码）。

## 3. 测试计划

- chat widgets 套件（含 Message 十余子套件）原样通
  过；ESLint 对 Message.tsx 期望警告清零。

## 4. 本地证据

- 基线实测：ESLint 对 `Message.tsx` 恰有 2 条
  `react-refresh/only-export-components` 警告（769 /
  774 行，正是两函数定义处）；抽离后三改动文件
  ESLint 0/0。
- 搬移逐字节校验：两函数共 19 行与基线原文比对完全
  一致（脚本断言 identical）。
- chat widgets 全目录 131 文件 647 例通过（含
  Message.test 15 例，审计用例改导入后原样通过）。
- tsc（rc=0）、architecture（rc=0，slack 343 不变）、
  diff-check、diagnostics、manifest 全绿；后端零改
  动，改动代码文件 prettier 干净（暂存 blob 核验）。
