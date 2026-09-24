# R113 批次计划 —— MemoryBrowser UI 测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r113-scan`（基于 origin/main a7591778）

## 背景

`src/widgets/memory/MemoryBrowser.tsx`（490 行，记忆浏览器）无测试。组件含
统计卡、类型/作用域双轴筛选（作用域为纯前端过滤）、错误重试、摘要视图
（getSessionSummaries）与会话跳转（useNavigate）。

## 批次内容

新增 `src/widgets/memory/__tests__/MemoryBrowser.test.tsx`（10 用例）：

- 加载与列表：加载中 '加载中...'；完成渲染标题/来源徽章/作用域徽章/统计卡
  （本周新增）；接口报错显示错误 + 重试按钮；空列表 '暂无记忆'；
- 筛选：类型按钮（'工作记忆'）触发 getMemories('working', …)；作用域按钮
  （'项目'）为前端过滤——用户记忆隐藏、项目记忆保留（缺 scope 的行按
  'user' 展示）；
- 会话跳转：携带 session_id 的记忆渲染 '↳ 会话' 按钮 → navigate
  ('/chat?session=sess-9')；未携带则不渲染跳转按钮；
- 摘要视图：'按会话查看摘要' 切换；空 session_id 点刷新提示
  '请输入会话 ID 以查看摘要' 且不调接口；输入后刷新调用
  getSessionSummaries 并渲染摘要与状态徽章（'已就绪'）。

实现要点：memoryApi 与 react-router-dom（useNavigate）均部分 mock；
react-router-dom 用 importOriginal 保留 MemoryRouter 能力。

## 验证矩阵

- 本机 vitest：10/10 通过（junction + 即摘协议，连跑 3 次稳定）。
- CI：Frontend (TypeScript) lint + typecheck + vitest。

## 不做

- 不改生产代码。
