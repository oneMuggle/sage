# {{变量}} 填充对话框（第二十九轮批次 A）实施计划

> 日期: 2026-09-13 · 分支: `feat/tpl-vars-r29` · 基于 main @ 3be8333d
> 来源: R27 (#716) 的收口项——选中含 {{变量}} 占位的模板此前只是把
> 原文塞进输入框，用户需手工逐个替换占位。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施（前端 only，零后端变更）

- `src/widgets/chat/TemplateFillDialog.tsx`（新）:
  - 纯函数 `extractTemplateVars`（按出现顺序抽取 {{占位}}、去重、
    裁剪空白）与 `resolveTemplate`（已填替换、留空保留占位原样）；
  - 对话框组件：逐变量输入框 + 确认/取消；无变量模板显示提示。
- `ChatInput` 模板分支: 有占位 → 打开填充对话框，确认后以解析文本
  回填输入框；无占位 → 保持原直接填入行为。
- i18n: tplfill.* 5 组键（zh/en）。

## 测试

- `TemplateFillDialog.test.tsx` 10 例（抽取/解析/组件确认与取消/
  无变量提示）；`ChatInput.templates.test.tsx` 更新为 R29 契约
  （含变量弹对话框 + 无变量直填两用例），chat 套件 41 文件 254 例
  全过。tsc/eslint 全绿。

## 本批不做

- 变量记忆（记住上次填写值）
- 模板导入/导出
