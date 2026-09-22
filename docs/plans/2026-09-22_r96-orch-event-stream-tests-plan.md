# R96 批次计划 —— 编排事件流 client 测试收口（orchEvents/orchEventStream）

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r96-event-clients`（基于 origin/main 35206423）

## 背景

`src/shared/api/orchEventStream.ts`（299 行）与 `orchEvents.ts`（169 行）是编排
实时监控的数据面：NDJSON 解析、信封校验（长度/类型/字段全边界检查）、断行
缓冲、限流（单行 256KB/总缓冲 512KB）、abort 与错误回调。此前零测试。

## 批次内容

1. `src/shared/api/__tests__/orchEvents.test.ts`（5 用例）——类型守卫：
   task/step/control/run 前缀分类（含 `task.step.*` 不属于 task.* 的边界）、
   终态四值判断。
2. `src/shared/api/__tests__/orchEventStream.test.ts`（11 用例）——
   - `parseOrchEventLine`：合法信封、未知 event_type、缺字段/负 seq/非法
     visibility/entity 非对象、非 JSON/空行/数组/超长行；
   - `parseOrchEventFromIpc`：对象通过、垃圾拒绝；
   - `subscribeOrchEvents` direct 兜底路径（stub fetch + 手工 reader）：
     跨 chunk 断行按序产出、残行冲刷、afterSeq URL 与 Accept 头、HTTP 500
     触发 onError 并抛错、AbortError 静默结束、普通网络错误 onError+抛出、
     单行超限抛专用错误。

## 验证矩阵

- 本机 vitest：16/16 通过（junction + 即摘协议）。
- Electron IPC relay 分支（window.electronAPI.listen 队列/error 通道）留待
  补充：需 jsdom+复杂 window stub，本批以 direct 路径行为锁为主。

## 不做

- 不改生产代码。
- desktopEvent/demoChatScript 留待后续。
