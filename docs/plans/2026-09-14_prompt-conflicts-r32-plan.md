# 模板冲突合并策略 + 变量记忆清除入口（第三十二轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/prompt-conflicts-r32` · 基于 main @ 7310444e
> 来源: R27/#716、R29/#732、R30/#737 的收口项。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施

### A. 导入同名冲突策略（S，后端 + 前端两阶段）

- `ImportEnvelope.conflict`: `'skip'`（默认，同名跳过并返回
  `conflicts=[同名清单]`）| `'overwrite'`（同名以导入内容覆盖，**保留
  现有 id** —— 斜杠 `tpl-<名称>` 映射与变量记忆 key 不断链）；
  非法 conflict 值按 skip 处理。
- `PromptTemplatesTab` 导入两阶段：先 skip；响应带 conflicts 时
  confirm 询问"是否覆盖"，确认后以 overwrite 重导并报告。

### B. 变量记忆清除入口（S）

- `clearRememberedValues(content)`（localStorage 删键）；
- `TemplateFillDialog` footer 左侧"清除记忆"按钮（仅当有记忆值时
  显示）——点击清空本模板记忆并重置输入框。

## 测试

- 后端 `test_prompt_import_export` 新增 2 例（skip 模式 conflicts 清单
  + 内容不被覆盖；overwrite 覆盖且保留 id；非法 conflict 值按 skip）
  —— 全套 6 例。
- 前端既有对话框/记忆 16 例回归；tsc/eslint 全绿。

## 本批不做

- `{{变量}}` 填充对话框的变量下拉建议
- 模板管理面板的拖拽排序
