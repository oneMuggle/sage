# 模板变量记忆（第三十一轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/tpl-memory-r31` · 基于 main @ 5d9976c5
> 来源: R29 (#732) 的收口项——模板变量每次都要重新填写，高频周报/
> 纪录类模板体验割裂。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施（前端 only，零后端变更）

`TemplateFillDialog.tsx` 增补：

- 纯函数 `tplStorageKey(content)`（djb2 内容哈希 →
  `sage:tplfill:<hash>`）+ `loadRememberedValues` / `saveRememberedValues`
  （localStorage 读写，失败静默降级）；
- **只记非空值**——用户清空某变量输入 = 遗忘该变量（不会把旧值永久
  焊死）；
- 对话框打开时用记忆值预填各变量输入框；确认时保存本次填写。

## 测试

- `TemplateFillDialog.memory.test.tsx` 6 例: save/load 往返、跨模板
  隔离（按内容哈希分键）、空值不写入、损坏 JSON 容错、组件确认后
  重开预填、既有纯函数回归。
- chat 套件 47 文件 277 例全过；tsc/eslint 全绿。

## 本批不做

- 变量记忆的清除入口（可在管理面板加"清除记忆"，低优先）
- 模板导入/导出对记忆的包含（记忆是本机隐私，不随模板导出）
