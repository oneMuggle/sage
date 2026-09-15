# Prompt 模板库（第二十七轮批次 A）实施计划

> 日期: 2026-09-13 · 分支: `feat/prompts-r27` · 基于 main @ 90d070c5
> 来源: 第二十一轮差距分析 #4——"无用户级提示词库：仅 agent persona 与
> 硬编码斜杠命令"。与并发车道（search-fts / word-h4h5 / win-path）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景（证据）

- 前端斜杠命令是硬编码（`slashCommands.ts`）+ SKILL.md 动态命令；用户
  自定义提示词无处安放，重复输入高频提示词只能靠记忆。
- 后端 preferences KV 模式成熟（`SettingsRepository.get_json/set_json`，
  `session_model_overrides` 先例），加模板存储零迁移成本。

## 实施

### A. 后端 CRUD（S）

`backend/api/prompt_routes.py`（新，router 无条件 include）：

- 存储键 `prompt_templates`（KV JSON 列表，上限 100 条防膨胀）；
- `GET /prompts/templates` → `{templates}`；
- `POST /prompts/templates`（name+content 必填，description 可选）→
  创建（校验非空、长度上限 name≤60/content≤8000）；
- `PUT /prompts/templates/{id}`（部分更新）→ 404 防御；
- `DELETE /prompts/templates/{id}` → `{ok: true}`。

### B. IPC + 前端 API（S）

- `commands.ts`: `prompts_list / prompts_create / prompts_update /
  prompts_delete` 四命令；
- `src/shared/api/promptApi.ts`（新）+ index 导出。

### C. 斜杠面板联动（M）

- `SlashCommand` 增 `mode: 'template'` 与 `content?: string`——
  选中即**填充输入框**（不发送），`{{变量}}` 占位留给用户编辑；
- ChatInput 挂载时 `promptApi.list()` 载入模板，映射为
  `tpl-<名称>` 命令并入斜杠列表（与 SKILL.md 动态命令并存）；
- 新静态命令 `/prompt-save`：把命令后剩余文本存为模板（名称取前
  24 字），保存成功 toast + 重新载入模板列表。

## 测试

- 后端 `test_prompt_routes`: CRUD 全链（TestClient）、非空/长度校验、
  404、上限 100、持久化（fake KV monkeypatch）。
- 前端: `mergePromptTemplates` 纯函数单测（映射/去重/排序）；ChatInput
  模板选中填入不发送。
- ruff / tsc / eslint 全绿。

## 本批不做（后续候选）

- 模板管理 UI（编辑/删除面板，管理面前道后续批）
- `{{变量}}` 填充对话框（选中后弹变量表单）
- 模板导入/导出（与记忆导出同模式）
