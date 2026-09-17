# 主题切换快捷键 + 快捷键注册表补全（第四十七轮批次 A）

> 日期: 2026-09-17 . 分支: feat/theme-toggle-r47 . 基于 main @ 2d72785b
> 来源: UX 改进——暗色/亮色模式切换缺键盘快捷键。Win7 不迁。

## 实施
- App.tsx: Ctrl+Shift+D 全局快捷键切换暗色/亮色主题
  （直接操作 html.classList.toggle(.dark) + localStorage 持久化）
- shortcuts.ts: 注册表新增 Ctrl+N / Ctrl+F / Ctrl+Shift+D 三项
  （与 R40/R33 实现同步，帮助面板数据源）
## 测试
- chat 套件 197 例回归。tsc/eslint 全绿。
