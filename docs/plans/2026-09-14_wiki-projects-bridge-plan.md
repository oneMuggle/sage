# P6 计划——wiki 授权桥接 projects 注册表（读侧统一第一步）

> 日期: 2026-09-14 · 基线: main `af9bb80d`（P5 #772 合入后）
> 分支: `feat/wiki-projects-bridge` · 前置: P1 #727 / P2 #734 / P3 #739 / P4 #743 / P5 #772

## 1. 背景变化

P2/P3 两轮把 "wiki recent_projects 统一" 列为缓行，依据有二：
1. POSIX-only 安全原语阻塞（Windows 无测试覆盖）；
2. 授权语义敏感，须独立批次。

第 1 条已被 **#760（R32 Windows 原生 reparse-safe 文件读写原语，"recent_projects
解锁"）**解除——`test_recent_projects.py` 在 Windows 上 16/16 通过。
本批即处理第 2 条，且收敛为**最小加法桥接**（不是存储迁移）。

## 2. 现状事实（Explore 结论）

- `authorize_registered_project`（backend/wiki/project_authorization.py
  L42-63）是约 24 个 wiki 端点的**唯一授权门禁**：canonicalize →
  `load_recent()` 成员判定（`_same_path` normcase 比较）→ 不在则 403
  "项目未授权"；注册表不可读 → fail-closed；
- `authorize_registration` 名不副实：只做目录有效性校验，无成员判定；
- open/create 端点无条件 `record_recent`（首次打开自登记）；
- MCP `_authorized_project_root`（mcp_server.py L132）同样以 recents
  构建授权集；全局搜索 `_search_knowledge` 取 `recents[0].path` 为默认域。

## 3. 方案（P6 落地）

1. **授权桥接**：`authorize_registered_project` 在 recents 成员判定
   之外，**并集** projects 注册表路径（新增模块内
   `_projects_registry_paths()`：lazy import `ProjectRepository`，
   异常/空库 → 空列表，维持 fail-closed）。lazy import 同时保证既有
   测试的 monkeypatch 风格可平移。
2. **写侧双登记**：wiki `open_project` / `create_project` 成功路径在
   `record_recent` 之后调用 `ProjectRepository().register(...)`（异常
   吞掉记日志——注册表写入失败绝不影响 wiki 操作）。效果：打开过的
   wiki 项目自动进侧栏"项目"清单，两个域的用户信任语义对齐
   （"用户显式用作 Sage 工作目录"）。
3. **MCP 对齐**：`_authorized_project_root` 的 registered 集合同样并集
   注册表路径（同一信任来源，fail-closed 不变）。
4. **明确不改**：
   - 全局搜索 `_search_knowledge` 的 `recents[0].path` 默认域——改它
     会静默改变知识库搜索结果语义，留待专门讨论；
   - `GET /wiki/recent-projects` 响应结构（前端 picker 未渲染 recents
     列表，合并无用户可见价值）；
   - 存储迁移（recents JSON → SQLite）：双轨稳定后再议。

## 4. 规范化差异（风险点）

`validate_workspace`（projects 表入库存的绝对路径）与
`canonical_project_path`（wiki 侧 `resolve(strict=False)`）规范化口径
不同；桥接比较统一走现有 `_same_path`（normcase + str 比较）并双方向
resolve 后比较，Windows 大小写差异已被 normcase 吸收。

## 5. 测试

- 单测（test_project_authorization.py 风格扩展）：
  - 仅注册表命中（recents 为空）→ 授权通过；
  - 注册表读取异常 → fail-closed 403；
  - 注册表命中但目录已删 → 404 语义不变。
- wiki_routes 集成：open 一个已注册项目 → 200 且 `projects` 表
  last_opened_at 刷新；create → projects 表新增行。
- MCP 单测：注册表路径通过授权。

## 6. win7 对齐

改动集中在 wiki 域 3 个文件 + 测试；`project_repo.py` 为 P1 新文件。
wiki_routes 在 win7 分支分歧大，但本批仅在其 open/create 两处各加 2-3
行注册调用，cherry-pick 机械重放。全部代码保持 Python 3.8 兼容
（lazy import + typing.Dict/List，无海丝/无 match）。
