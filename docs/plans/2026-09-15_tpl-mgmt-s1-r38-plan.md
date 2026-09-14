# 模板管理面板增强 + 变量记忆管理（第三十八轮批次 A）实施计划

> 日期: 2026-09-15 · 分支: `feat/tpl-mgmt-s1-r38` · 基于 main @ b8da0c90
> 来源: R29/#732 与 R32/#752 的收口项——变量记忆此前只在填充对话框
> 逐条使用，管理面板无查看/清除入口。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施（前端 only，零后端变更）

- `TemplateFillDialog.tsx`: 抽出 `tplStorageKey` 为导出纯函数
  （`export function tplStorageKey`），供管理面板复用同一键口径。
- `PromptTemplatesTab.tsx`: 每个模板卡片增加"变量记忆"区块——
  - 用 `tplStorageKey(tpl.content)` 读取 localStorage 中该模板的
    记忆值（键值对展示，值截断 40 字）；
  - 有记忆时显示"清除记忆"按钮（清 localStorage 键并刷新状态）；
  - 无记忆不显示区块（避免噪音）。
- 空内容模板（无 content）跳过读取。

## 测试

- `PromptTemplatesTab` 新增 2 例: 有记忆值时展示区块与清除调用；
  无记忆时不展示。
- 既有 7 例回归；tsc/eslint 全绿。

## 本批不做

- 记忆值的逐条编辑（低频，清除后重填即可）
- 模板导入冲突的条目级覆盖选择
