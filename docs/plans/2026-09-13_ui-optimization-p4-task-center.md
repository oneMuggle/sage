# UI 优化 P4 批次计划——全局任务中心（第一切片）

> 日期: 2026-09-13
> 目标分支: main（release/win7 按需 cherry-pick，依赖 office 前置特性先移植）
> 前序: #733（P0+P1）、#738（P2）、#740（P3）

## 背景与问题

长任务反馈分散且形态不一（2026-09-13 分析结论）：

| 任务 | 现有反馈 | 位置 | 问题 |
| --- | --- | --- | --- |
| 聊天流（后台会话） | chatStreamStore 会话槽位 | 侧栏徽章 / Chat 页 | 切走会话后全局无聚合视图 |
| office 生成/导出 | 组件局部 busy 布尔 | 表单内按钮 | 切走页面无任何反馈，用户不知道任务还在跑 |
| wiki 导入 | wiki-ingest 进度事件 | wiki 页内 | 同上 |
| 嵌入模型下载 | IPC 事件 | 无（死路径） | 暂不接（见 #738 说明） |

## 方案（本切片 = ①②③，④后延）

1. `src/features/task-center/taskCenterStore.ts` — 独立 zustand store：
   - `tasks: Record<id, { id, kind: 'office'|'wiki'|'custom', title, startedAt, phase }>`
   - `registerTask(id, kind, title)` / `updateTask(id, patch)` / `finishTask(id)`
   - 聊天流不进 store：TaskCenterWidget 直接 selector 读 chatStreamStore 的
     sessions 槽位聚合（单一事实源，避免双写）。
2. `src/widgets/task-center/TaskCenterWidget.tsx` — 全局悬浮胶囊（挂 Layout）：
   - 无活动任务时不渲染；
   - 折叠态：`⚙ N 项进行中`（spinner 图标 + 计数）；
   - 展开态：任务列表（图标 + 标题 + 已耗时），点击跳转对应页面
     （office → /office，wiki → /knowledge，chat → /chat?session=）；
   - Esc / 点外部收起；prefers-reduced-motion 兼容走全局 media query。
3. office 接线：OfficeGenerateForm / OfficePreviewPanel 在 busy 置位时
   register/finish（title 带文档名）。
4. （后延）wiki 导入接线——需把 useWikiIngest 的进度上抬，涉及页面结构，
   独立成下批；聊天后台流聚合一并下批（涉及侧栏徽章去重）。

## 验收

- office 生成期间切到任意页面，右下角胶囊可见且已耗时正确跳动；任务结束
  条目消失。
- store 单测：register/update/finish 生命周期、多任务并存。
- widget 单测：无任务不渲染、有任务渲染计数、展开列出条目。
- tsc / eslint / vitest 全绿（Windows 本机 4 个基线失败除外）。
