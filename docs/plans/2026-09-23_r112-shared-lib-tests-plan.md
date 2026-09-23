# R112 批次计划 —— 共享库测试补缺（agentStateMapping / useFileUpload）

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r112-scan`（基于 origin/main ad3892d2）

## 背景

R108 同款扫描发现 `src/shared/lib` 下两个无测试的逻辑模块：

- `agentStateMapping.ts`（137 行）——AgentState → 气泡占位文本的单一真相源
  （MEDIUM-3/4 修复产物），switch 带 assertNever 穷尽守卫；
- `useFileUpload.ts`（126 行）——聊天输入的文件/图片分流、拖放、粘贴 hook。

## 批次内容

1. `src/shared/lib/__tests__/agentStateMapping.test.ts`（31 用例）——
   锁定全部 AgentState 变体的映射：thinking/acting(含 toolName 分支)/
   observing/failed 有占位文本；permission_request/ask_user_question 卡点态
   返回 null（不覆盖气泡）；全部事件态（task_*/reasoning_*/suspended/
   subagent_event/approval_mode/step_done/topic_shifted/orch_preflight 等）
   返回 null。
2. `src/shared/lib/hooks/__tests__/useFileUpload.test.ts`（8 用例）——
   addFile/addImage 通道分流与 dataUrl、非图片拒绝、handleDrop 按类型分流、
   handlePaste 只取图片项、remove 按下标删除、clearAll 清空、handleDragOver
   置位。FileReader 以假类替换 + act 包装 flush。

## 验证矩阵

- 本机 vitest：39/39 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest。

## 不做

- 不改生产代码。
