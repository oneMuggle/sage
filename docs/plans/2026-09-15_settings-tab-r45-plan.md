# 设置页 Tab 记忆（第四十五轮批次 A）实施计划

> 日期: 2026-09-16 · 分支: `feat/settings-tab-r45` · 基于 main @ 5056a622
> 来源: UX 改进——设置页每次打开都从"通用"开始，频繁调整多个设置项的
> 用户需反复切换。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施

- Settings.tsx `activeTab` 初始值从 localStorage 键
  `sage:settings-tab` 恢复（默认 'general'）
- `setActiveTab` 封装为 useCallback，切换 tab 时同步持久化到
  localStorage

## 测试

- 既有 settings 套件回归 6 例。tsc/eslint 全绿。

## 本批不做

- 设置搜索高亮匹配项（需要更深层 refactor）
