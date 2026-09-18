# ChatInput 卸载竞态修复

## 失败证据

Win7 PR #904 的 CI run 35085484106：前端 2342 项断言通过，但出现一次未处理 rejection，导致 frontend 和 All Checks 失败。

错误为 `ReferenceError: window is not defined`，来源 `src/widgets/chat/ChatInput.tsx` 技能列表请求的 catch 回调；请求完成时 `Chat.auto-scroll.test.tsx` 的测试环境已经销毁。这不是覆盖率阈值问题，不应忽略未处理异常或仅靠重跑绕过。

## 修复

技能加载 effect 内维护自身的 disposed 标记，cleanup 时置位；成功和失败回调均禁止在卸载后更新 state，成功回调也不再处理迟到数据。标记属于每一次 effect，兼容 StrictMode cleanup/re-run。请求本身未被取消，底层重试仍可能结束于卸载之后。

新增 `src/widgets/chat/__tests__/ChatInput.lifetime.test.tsx`，覆盖迟到成功数据不再处理及迟到 rejection 正常消费。与 `src/pages/__tests__/Chat.auto-scroll.test.tsx` 联合回归，不改动已有自动滚动断言。

## 验证边界

main/Win7 应保持同一实现；提交前执行相关测试、TypeScript 和 ESLint，更新 PR 后以新 SHA 的 CI 为准。旧 run 的绿灯不是本次修改的验证证据。最终结果记录在 PR #903/#904。

Office 引用核对仍是只读工具，不具备删除许可；真实 Win7 OS 和安装包回滚验收仍需相应环境。
