# Prompt 模板管理面板（第二十八轮批次 A）实施计划

> 日期: 2026-09-13 · 分支: `feat/prompt-mgmt-r28` · 基于 main @ 44ff4a59
> 来源: R27 (#716) 的收口项——模板的编辑/删除此前仅能走 API，无用户入口。
> 与并发车道（word-h4h5 / win-path / ui-optimization）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景

R27 (#716) 落地了模板 CRUD 后端 + 斜杠联动（`/tpl-<名称>` 填充、
`/prompt-save` 保存），但管理面缺失：查看列表、编辑、删除没有 UI 入口。

## 实施（前端 only，零后端变更）

- `src/pages/settings/PromptTemplatesTab.tsx`（新）:
  - 列表态：模板卡片（名称/描述/内容预览 120 字截断）+ 编辑/删除；
  - 表单态：名称/描述/内容三字段（长度上限与后端对齐 60/300/8000），
    新建与编辑复用同一表单；
  - 删除为即时操作（模板非 destructive 关键数据，且斜杠重建成本极低）；
  - 错误条 + 加载态 + 空态提示（引导 /prompt-save）。
- `Settings.tsx`: 注册 `prompts` tab（记忆与网络之间），渲染组件。

## 测试

- `PromptTemplatesTab.test.tsx`（mock promptApi）: 列表渲染 / 新建保存
  调用链与写入形态 / 编辑回填与更新 / 删除调用 / 错误展示 / 空态。
- tsc / eslint 全绿。

## 本批不做（后续候选）

- `{{变量}}` 填充对话框（选中模板后弹变量表单，S/M）
- 模板导入/导出
