# P9 计划——知识搜索默认域配置化（用户可选最近项目）

> 日期: 2026-09-15 · 基线: main `b8da0c90`（P8 #815 合入后）
> 分支: `feat/knowledge-scope-p9` · 前置: P1-P8、W5

## 1. 缺口

`/search/global` 的知识搜索范围硬编码为 `load_recent()[0].path`（最近
打开的 wiki 项目，search_routes.py L107）——多 wiki 项目并行时，用户无
法选择在哪个项目里搜。P6 曾标注"改默认域 = 静默改变语义，须专门讨论"；
本批不改默认值，而是**增加显式范围参数 + 面板内范围选择**，默认行为零
变化。

## 2. 方案

### 2.1 后端（search_routes.py）

- `global_search` 新增可选 query 参数
  `knowledge_project`（wiki 项目根目录绝对路径）；
- 提供时经 `authorize_registered_project` 校验（recents ∪ projects 注册
  表成员 + `wiki/` 目录存在，P6 桥接已覆盖 projects 来源）——未授权
  403 / 非 wiki 项目 404，与 wiki 其它操作同契约；
- `_search_knowledge(query, limit, project_path=None)`：显式范围优先，
  否则回退 recents[0]（默认行为零变化）。

### 2.2 前端（CommandPalette.tsx）

- 新增"知识范围"分组（命令模式，打开面板即拉 `getRecentWikiProjects`）：
  - 选项 = `默认（最近打开）` + 最近 wiki 项目（path 展示）；
  - onSelect 设置范围并持久化 localStorage
    （`sage:knowledge-scope:v1`），**不关闭面板**（范围选择是调参不是
    导航）；
  - 当前范围以勾选标记展示；未设置时默认项勾选。
- 搜索请求按范围追加 `knowledge_project` 参数。

### 2.3 明确不改

- 默认域仍是 recents[0]（未显式选择时零行为变化）；
- 不做设置页持久化（localStorage 已满足面板级偏好，避免扩设置面）；
- 不改 `search_wiki`（实时扫描，W5 后 Windows 可用）。

## 3. 测试

- 后端（tests/api/test_search_routes.py）：
  - 两个 wiki 项目各含唯一词页面 → `knowledge_project=B` 时只命中 B；
  - 未授权路径 → 403；projects 注册表命中（P6）→ 放行；
  - 非 wiki 项目目录 → 404；不传参数 → 默认行为不变。
- 前端（CommandPalette.test.tsx）：范围选择持久化 + 搜索请求携带
  `knowledge_project`。
- 全量前端套件基线对照。

## 4. win7 对齐

search_routes / CommandPalette 均为小块追加（win7 惯例本地结构重放）；
`authorize_registered_project` 复用现有门禁（win7 侧该文件随 P6 cherry-
pick）；localStorage 无平台差异；py3.8 兼容。
