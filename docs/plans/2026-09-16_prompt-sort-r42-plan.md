# Prompt 模板拖拽排序（第四十二轮批次 A）实施计划

> 日期: 2026-09-16 . 分支: feat/prompt-sort-r42 . 基于 main @ 6119d288
> 来源: R27/#716 的收口项：管理面板模板列表无排序控制。
> Win7 对齐: 新功能不 cherry-pick 到 release/win7。

## 实施

- 后端: PUT /prompts/templates/reorder 端点（ordered_ids 列表重排存储数组）
- IPC: prompts_reorder 命令
- promptApi: reorder(orderedIds) 方法
- PromptTemplatesTab: HTML5 drag-and-drop（原生 API，零依赖），
  拖拽中高亮目标行 + 源行半透明，释放后乐观更新 + API 持久化，
  失败回滚到刷新前状态

## 测试
- filterTabs 既有 3 例回归
- tsc/eslint 全绿
