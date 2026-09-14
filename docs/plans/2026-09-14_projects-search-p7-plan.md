# P7 计划——全局搜索接入项目分组

> 日期: 2026-09-14 · 基线: main `9d501fcd`（W5 #802 合入后）
> 分支: `feat/projects-search-p7` · 前置: P1-P5、W5

## 1. 缺口

命令面板（P1-3.7 全局搜索）：搜索词 <2 字符的命令模式已列项目（P2），
但 **≥2 字符的搜索模式**只覆盖会话/记忆/知识——按项目名/路径片段找项
目并直达是主流工具的标准能力（Cursor cmdk 搜 workspace）。

## 2. 方案

- **后端** `backend/api/search_routes.py`：
  - `ProjectRepository` 新增 `search(query, limit)`（name/path LIKE，
    last_opened_at 排序——与 session_repo.search 同风格）；
  - `_search_projects(query, limit)`：命中行附 session_count 聚合；
  - `global_search`：默认 `wanted` 增 `"project"`，types 描述与 docstring
    同步；响应组 `projects: [{id, name, path, session_count}]`。
- **前端** `CommandPalette.tsx`：
  - `GlobalSearchResult` 增 `projects?`；搜索模式渲染"项目"分组
    （Folder 图标 + name/path + 会话数），onSelect 复用 P2 的
    `handleOpenProject`（open → loadSessions → 进会话）。

## 3. 明确不改

- 知识搜索默认域（P6 已记录语义敏感）；
- LIKE 转义（`%`/`_` 不转义，与 session_repo.search 同约定）。

## 4. 测试

- 后端集成：登记项目后 `GET /api/v1/search/global?q=<片段>` 命中
  `projects` 组；`types=project` 过滤生效；空库返回空组或缺省不含。
- 前端：CommandPalette 搜索模式渲染项目分组 + 点击走 open 流。

## 5. win7 对齐

search_routes 为小文件，追加式改动 cherry-pick 机械；CommandPalette
改动与 P2 同位（win7 需本地结构重放，已在 61 号文档记录惯例）；
`project_repo.search` 为 P1 新文件纯追加，py3.8 兼容。
