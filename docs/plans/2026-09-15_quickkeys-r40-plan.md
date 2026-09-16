# 键盘快捷键补全（第四十轮批次 A）实施计划

> 日期: 2026-09-15 . 分支: feat/quickkeys-r40 . 基于 main @ 59d44f0d
> 来源: 差距分析 D6 前端报告：快捷键缺 Ctrl+N/Ctrl+F。与并发车道零交集。
> Win7 对齐: 新功能不 cherry-pick 到 release/win7。

## 实施

- App.tsx: Ctrl+N 新建会话（createSession + setCurrentSessionId + navigate）
- ConversationsSection: Ctrl+F 聚焦搜索框（window 自定义事件
  sage:focus-search + input ref）
- Layout.tsx: Ctrl+F 事件派发 + Ctrl+N 创建后导航到 /chat
- shortcuts.ts: 注册表不变（已在 R17 承诺）

## 测试
- chat 套件 197 例回归。tsc/eslint 全绿。
