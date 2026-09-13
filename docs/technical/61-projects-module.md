# 61 — 项目模块 P1：侧边栏项目注册表与项目内会话

> 日期: 2026-09-13 · 分支: `feat/projects-module`（基于 main）
> 参考: Cursor Recent Workspaces、Claude Code 项目 → 会话归属、Cline 任务工作区

## 1. 定位

侧边栏"项目"分组此前是占位符（`ProjectSection` "占位 - 项目列表将在
Phase 4 接入"）。本批次将其落地为**项目注册表**：

- "项目" = 用户显式登记的工作目录，独立于会话持久化；
- 点击项目即进入该项目 —— 后端复用该项目**最近的活跃会话**（无则
  新建并绑定项目目录）；
- 会话与目录的归属**不新增第二份数据**，直接复用
  `session_workspace_bindings` 活跃绑定（fork 继承、变更面板、检查点、
  `SAGE.md` 项目上下文发现等既有链路全部自动生效）。

## 2. 架构

```
ProjectSection (src/widgets/sidebar/sections)
  └─ projectApi (src/shared/api/projectApi.ts)
       └─ invoke('projects_*') → electron/commands.ts COMMAND_ROUTES
            └─ HTTP /api/v1/projects* → backend/api/project_routes.py
                 └─ backend/data/project_repo.py (ProjectRepository / open_project)
                      ├─ projects 表 (backend/data/database.py init_db)
                      ├─ session_workspace_bindings 活跃绑定 = 归属判定
                      └─ sessions 表 (SessionRepository.create)
```

### 2.1 数据模型（`projects` 表）

```sql
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,   -- validate_workspace 规范化绝对路径
    name TEXT NOT NULL,          -- 目录 basename
    created_at INTEGER NOT NULL,
    last_opened_at INTEGER NOT NULL
);
```

- `path` UNIQUE + 幂等 upsert：重复登记同一目录只刷新
  `last_opened_at`，不产生重复行；
- 项目行**独立于会话存在**：登记后即使没有任何绑定会话也保留；
- 清单排序：`last_opened_at DESC`，上限 50。

### 2.2 会话归属判定（零新增数据）

```sql
-- project_repo.session_stats()
SELECT b.workspace_path, COUNT(s.id), (最近会话 id 子查询)
FROM session_workspace_bindings b
JOIN sessions s ON s.id = b.session_id AND s.is_archived = 0
WHERE b.revoked_at IS NULL
GROUP BY b.workspace_path;
```

对比另一实现（wiki 域 `backend/storage/recent_projects.py`，JSON 文件、
POSIX-only）：那是 wiki 页面自己的"最近打开的 wiki 目录"记录，域内自
洽；项目模块是全局 SQLite 注册表、跨平台。二者暂不合并，后续批次可
评估把 wiki 域迁到本注册表。

### 2.3 打开语义（`POST /projects/{id}/open`）

1. 取项目行；目录在磁盘上消失 → `410 project_path_missing`
   （不静默重建绑定；前端行内标 ⚠ 并提示移除或重选）；
2. 刷新 `last_opened_at`；
3. `sessions_for_project(path, limit=1)` 命中 → 原样复用
   （`created=false`）；
4. 未命中 → `SessionRepository.create(title=项目名)` +
   `bind_session_workspace`（`created=true`）。

单次 IPC 往返完成"切项目"，前端拿到 `session.id` 后
`loadSessions()` + `setCurrentSessionId` + 按需 `navigate('/chat')`
（`Sidebar.handleOpenSession` 统一入口，与会话列表 onSelect 共用）。

## 3. API 面

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| GET | `/api/v1/projects` | 清单（附 session_count / last_session_id 聚合） |
| POST | `/api/v1/projects` | 登记目录 `{path}`（validate_workspace 校验，400 invalid_workspace_path） |
| DELETE | `/api/v1/projects/{id}` | 移除注册行（不动磁盘与会话），404 project_not_found |
| POST | `/api/v1/projects/{id}/open` | 打开项目（最近会话或新建绑定），410 project_path_missing |
| GET | `/api/v1/projects/{id}/sessions` | 项目下未归档会话（新→旧，≤20） |

IPC 命令（`electron/commands.ts`）：`projects_list` / `projects_register`
/ `projects_remove` / `projects_open` / `projects_create_session` /
`projects_list_sessions`。

## 4. 前端行为

- 标题行 `+`：`selectDirectory({intent:'open'})` 原生选目录 → 登记 →
  直接打开（新目录立即建会话进入，对标 Cursor "Open Folder"）；
- 行点击：打开项目（见 2.3）；行 hover：`+`（项目内显式新建会话）、
  TwoStepDelete 两步确认移除（图标用 folder-minus 语义，弱化"删文件"
  误读）；
- 会话计数徽标 + 路径副行；目录缺失行内 ⚠（`text-warning`）；
- i18n：`sider.project.*`（zh/en 齐备）。

## 5. 安全与边界

- 路径校验复用 `backend/office/storage.validate_workspace`（拒绝
  `..`、不存在、非目录；resolve 规范化），与 workspace 绑定同口径；
- DELETE/open 均不触达文件系统写操作；移除项目不删除任何会话、
  绑定或磁盘内容（会话删除仍走既有 delete_session → 绑定级联清理）;
- 响应不泄露 workspace 内部结构（仅登记路径本身），与
  `workspace_routes._search_model` 的"不回传 source_path"同一立场。

## 6. 测试

- 后端集成：`backend/tests/integration/test_project_routes.py`（8 用例：
  幂等登记、非法路径 400、移除后 404、open 建绑定并复用、缺失目录
  410、清单聚合、移除保留会话绑定）；
- 前端组件：`src/widgets/sidebar/sections/ProjectSection.test.tsx`
  （7 用例：空态/列表/行点击 open/hover 新建/TwoStepDelete/添加流/
  410 缺失标记）；
- IPC 契约：`electron/__tests__/commands.test.ts` 增加 `projects_*`
  路由断言（受既有 "/api/v1 前缀" guard 全量覆盖）。

## 7. main ↔ release/win7 对齐说明

本批次以 main 为基线；`release/win7`（LTS，仅 hotfix）按需
cherry-pick 时注意：

1. **新文件零冲突**：`project_repo.py` / `project_routes.py` /
   `projectApi.ts` / `ProjectSection.tsx` / 三个测试文件均为新增；
   `project_repo.py` 语法保持 Python 3.8 兼容（typing.Dict/Tuple、
   无海象/无 match）。
2. **共享文件均为小步增量**，冲突机械可解：
   - `backend/data/database.py`：`init_db` 中 `session_workspace_bindings`
     块之后追加 `projects` 建表（幂等 `CREATE TABLE IF NOT EXISTS`，
     旧库升级零迁移成本）；
   - `backend/main.py`：1 行 import + 1 行 `include_router`；
   - `electron/commands.ts`：`workspace_revoke` 之后追加 6 个命令映射；
   - `Sidebar.tsx` / `i18n zh,en` / `shared/api/index.ts`：小块追加。
3. **pydantic 版本差异**：main 的 `project_routes.py` 用 pydantic v2
   风格（`ConfigDict(extra="forbid")`，与同目录 `workspace_routes.py`
   一致）；win7 仍是 pydantic 1.x，cherry-pick 时需照其
   `workspace_routes.py` 的写法改写模型声明（`class Config: extra =
   "forbid"`），路由/仓储/前端层无需改动。
4. win7 无 Electron 21 之上的 API 依赖：`selectDirectory` 与
   `invoke` 漏斗均为既有设施。

## 8. 后续批次（非本批范围）

- P2 候选：项目行展开显示会话子列表（`GET /projects/{id}/sessions`
  已就绪）；命令面板接入（`projects_open`）；拖拽文件夹到侧栏登记；
  wiki 域 recent_projects 迁移统一。
