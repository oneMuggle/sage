# R97 批次计划 —— shared/api 小面收口（utils/desktopEvent/demoFlag）

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r97-small-clients`（基于 origin/main a0e5633f）

## 背景

r90/r93/r96 已收口大面 client。剩余未测小面中，`utils.ts`（全部 client 共用的
重试/错误包装基座）、`desktopEvent.ts`（listen 垫片）、`demoFlag.ts`（演示模式
优先级链）价值密度最高——它们的契约变化会波及所有 client。

## 批次内容

1. `utils.test.ts`（11 用例）——sanitizeInput 转义顺序（& 先行不二次转义）与
   非字符串兜底；UUID 校验正/反例；withRetry 首试成功/退避重试后成功
   （fake timers）/maxRetries=0 单次耗尽抛最后错误；handleApiError 四分支
   （ApiException 同实例透传、结构化 error/message、内层 LLM 错误保留
   llmError 对象、UNKNOWN_ERROR 的 Error/非对象两种来源）。
2. `desktopEvent.test.ts`（3 用例）——payload→{payload} 包装还原、streamId
   第三参透传、无 electronAPI 抛可读错误。
3. `demoFlag.test.ts`（5 用例）——isDemoMode 优先级链：override 最高
   （false 压过 electron/store）、electronAPI.demoMode 次之、settings store
   兜底、全关为假。demoRuntime/settingsStore 均以 vi.mock 替身注入。

## 验证矩阵

- 本机 vitest：19/19 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest。

## 不做

- 不改生产代码。
- demoChatScript（324 行演示数据）低价值，不测。
