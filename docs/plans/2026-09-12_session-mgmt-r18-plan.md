# 会话管理补全（第十八轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/session-mgmt-r18` · 基于 main @ 00296f09
> 来源: 第十七轮差距分析的两条报告（前端 UX / 后端能力）中的会话管理项。
> 与并发批次（manage-frontend、word-repair、gateway）零文件交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 背景（分析结论）

- **无重新生成**: 全 src grep `regenerate` 零命中；主流应用核心交互。
- **置顶无入口**: 数据模型 `is_pinned` 已有、后端 PATCH 已支持
  （legacy_session_routes:135）、SessionItem 只读徽章展示（:308），
  无 pin/unpin 切换、排序不区分置顶。
- **导出仅 HTML**: `export_session_to_html` 单格式；markdown 导出缺失
  （`build_session_payload` 已有结构化数据可复用）。

## 批次任务

### A. 重新生成（M，前端复用 fork-before+重发链路）

- `Message.tsx`: assistant 消息动作区加"重新生成"按钮（RefreshCw）。
- `Chat.tsx`: `handleRegenerate(assistantMessageId)` —— 找到其前最近
  一条 user 消息 → `sessionApi.fork(beforeMessage:true)` 截到该 user
  消息之前 → 切换到 fork 会话 → 原文重发。与编辑重发同一非破坏性
  语义（原会话保留，可对比两次回答），代码路径一致。

### B. 会话置顶（M）

- `sessionApi.setPinned(sessionId, pinned)` → IPC `session_update`
  （body 增量下发 `is_pinned`，title 缺省不下发）。
- `Sidebar.tsx`: `orderedItems` 稳定分区 —— 置顶组在前（组内保持
  手动拖拽顺序），未置顶组在后。
- `SessionItem.tsx`: Pin/PinOff 切换按钮（替代只读徽章的可见性），
  成功后 `updateSession` 原地更新。

### C. 会话 Markdown 导出（S）

- 后端 `session_export.py`: `build_session_markdown(session, messages)`
  —— 标题/元信息 + 每条消息 `**用户**/**Sage**:` 内容（tool 消息
  折叠为摘要行）；`ExportSessionRequest` 加 `format: 'html'|'markdown'`
  （default html，向后兼容），export 路由按 format 分派。
- IPC `commands.ts`: `export_session_markdown` 命令（body 只下发
  format，规避 extra=forbid 422）。
- 前端: `sessionApi.exportMarkdown` + `downloadMarkdownFile` +
  `SessionItem` 第二导出按钮（FileText 图标）。

## 测试

- 后端: `build_session_markdown` 单测（结构/转义/空会话/format 分派
  默认 html 不回归）。
- 前端: Message 重新生成按钮可见性；SessionItem pin 切换调用链。
- lint: eslint/ruff/tsc 全绿。

## 本批不做（后续候选）

- 记忆导出 + SQLite 自动备份（数据安全线，M）
- 首启向导（M）
- prompt 模板库（M）
- 聊天内文件 RAG（L）
