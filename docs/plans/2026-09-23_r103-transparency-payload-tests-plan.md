# R103 批次计划 —— transparencyPayload 载荷校验器测试

日期：2026-09-23 ｜ worktree：`.worktrees/fix-r103-payload-tests`（基于 origin/main 6e2718c0）

## 背景

#1411（R97 透明度事件载荷校验收口）把主路径 / 重接路径 / /btw 浮层三处
共用的 `/chat/stream` 事件载荷契约收敛到 `transparencyPayload.ts`，
但未带测试。校验器是防伪造/畸形数据进气泡文案的最后一道闸，契约必须
锁定。

## 批次内容

新增 `src/features/send-message/__tests__/transparencyPayload.test.ts`
（11 用例）：

- `isValidSourcesPayload`：四 kind 白名单通过；空数组拒绝（sources 必须
  非空，与其余校验器不同）；未知 kind / 缺 kind / null 项 / 非数组拒绝；
- `isValidMemoriesPayload`：string id 契约；空数组合法；缺 id / id 非字符串
  / null 项 / 非数组拒绝；
- `isValidSkillsPayload`：string name 契约；
- `isValidCitationsPayload`：string media_id 契约；
- `isValidCompactPayload`：before/after/removed 三数字齐全，缺字段 /
  非数字 / null / 数组拒绝。

## 验证矩阵

- 本机 vitest：11/11 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest（覆盖率棘轮只增不减）。

## 不做

- 不改生产代码；demoChatScript 维持不测。
