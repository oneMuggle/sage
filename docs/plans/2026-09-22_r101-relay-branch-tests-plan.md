# R101 批次计划 —— orchEventStream Electron IPC relay 分支测试

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r101-relay-tests`（基于 origin/main f56c1c57）

## 背景

r96 只覆盖了 direct fetch 兜底路径；IPC relay 路径（生产主路径：
`window.electronAPI.listen` 订阅 + error 通道 + abort 清理）当时因需
window stub 留待后续，本批补齐。

## 批次内容

新增 `src/shared/api/__tests__/orchEventStream.relay.test.ts`（5 用例）：

- afterSeq=0 订阅 `orch-events-{runId}`；afterSeq>0 订阅
  `orch-events-{runId}-seq-{n}`（断点续传通道命名）；
- 信封按序产出；非法载荷（非信封对象/null）被忽略；
- error 通道 `{message}` → 生成器以该消息 reject 终结；
- abort → 事件/错误两路 unlisten 均被调用，生成器收尾 done。

关键机制（踩坑记录）：
1. 异步生成器惰性执行 —— 必须先 `gen.next()` 把主体推到 `await listen`
   注册处，flush 后再推事件，否则注册尚未发生、事件丢失；
2. 生成器悬在永不 resolve 的 wakeup promise 上时 `gen.return()` 不会返回，
   需走 error 通道或 abort 干净终结；
3. 生产 preload 的 listen 返回 `Promise<UnlistenFn>`（源码对 error 通道
   结果链 `.catch`），stub 必须返回 Promise 而非裸函数。

## 验证矩阵

- 本机 vitest：5/5 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest（含覆盖率棘轮门禁
  #1406，纯新增测试只增不减）。

## 不做

- 不改生产代码；demoChatScript 维持不测。
