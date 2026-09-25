# 编码代理对标差距分析·第五十二轮：会话多 run 历史浏览器 MVP（RD23）

- **状态**：批次 A 交付中（分支 `feat-parity-r52-batch-a`，基线 origin/main 4b8e8f8f = #1578）
- **上游文档**：总账 §3 建议 2（唯一遗留）；C1 通道（listSessionRuns + restoreRunToBoard）
- **对标对象**：Claude Code / Devin（多轮会话历史可浏览可切换）
- **编号约定**：延续 RD 系

## 0. 结论速览

Chat.tsx 恢复路径仅取 `resp.runs[0]`（最新一条）——同一会话有多轮编排
时，用户**无法查看或恢复更早的 run**。本轮新增可折叠「历史编排」区块
（ProgressSection 内），展示该会话全部 run（时间/状态/进度/目标摘要），
点击即切换到该 run 的任务板（复用 restoreRunToBoard）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD23 | 多 run 历史不可浏览/切换 | Chat.tsx 仅取 runs[0] | Claude Code 多轮历史 | **P2** |

## 2. 设计（批次 A：RD23）

- **组件**：`SessionRunHistory`（ProgressSection 内折叠面板）。
  展开后调 `orchRunClient.listSessionRuns(currentSessionId)` 获取
  最多 20 条 run；每行显示时间（相对格式化）、状态 Badge、进度
  （done/total）、目标摘要（original_request 前 60 字）。
  点击行 → 回调 `onSelectRun(run)`。
- **Chat.tsx 接线**：`onSelectRun` 回调复用 `restoreRunToBoard` +
  `setTaskBoard` 恢复所选 run 的任务板（与 C1 恢复路径同源）。
- **前端 only**：零后端改动（C1 端点已够）。

## 3. 批次 A 实施与验证记录

- **SessionRunHistory.tsx**：可折叠历史编排面板——展开时调
  `listSessionRuns(sessionId)` 获取最多 20 条 run，每行显示状态 Badge +
  目标摘要（前 60 字）+ 进度 done/total + 时间（相对格式化）。
  点击行触发 `onSelectRun(run)` 回调。
- **接线链**：Chat.tsx（restoreRunToBoard + setTaskBoard）→ RightPanel →
  ProgressSection → SessionRunHistory。
- **前端 only**：零后端改动（C1 端点 + RT26 retry_of 持久化已就绪）。
- **验证**：tsc --noEmit 零新增错误（预存 TerminalPanel/useFileUpload
  问题非本轮引入）；eslint 改动文件零告警。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
