# 错误重试按钮（第五十轮批次 A）实施计划

> 日期: 2026-09-17 · 分支: `feat/ux-polish-r50` · 基于 main @ 2d72785b
> 来源: R17 错误内联条的增强——此前只有关闭按钮，出错后需手动复制
> 消息重发。与并发车道零交集。Win7 对齐: 不迁。

## 实施

Chat.tsx 错误内联条新增"重试"按钮（在"关闭"旁边），点击后：
1. clearError() 清除错误
2. 取最后一条 user 消息内容
3. 调用 sendMessage(lastUser.content) 重发

这使用户在流式失败后无需手动复制粘贴即可恢复对话。

## 测试

- 既有 Chat.cancel-run + Chat.inline-error 套件 6 例回归全过。
- tsc/eslint 全绿。
