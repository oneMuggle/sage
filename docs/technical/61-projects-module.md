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

## 9. P2 落地记录（2026-09-13，feat/projects-p2）

方案：`docs/plans/2026-09-13_projects-p2-plan.md`（含缓行项证据）。
后端与 Electron commands **零改动**，全部复用 P1 面。

- **行展开会话子列表**（ProjectSection）：chevron 展开懒加载
  `listSessions`（≤20 条），轻量子行（title + formatRelativeTime），
  刻意不复用 SessionItem（其订阅 5 个 store + 全套会话操作，嵌套过重）；
  子行点击走 onOpenSession 与会话列表同入口；open/项目内新建成功后
  自动刷新已展开的子列表；子列表按项目缓存，收起再展开不重复拉取。
- **命令面板接入**（CommandPalette + commandItems）：打开面板即
  `projectApi.list()` 渲染"项目"分组（前 8 个，name + path + 会话数），
  回车 `open` → `loadSessions()` → 复用面板既有 handleOpenSession；
  新增 `add-project` ActionCommand（FolderPlus：选目录 → register →
  open → 进入新会话）；键盘 ⌘数字与 onSelect 两条路径的重复 if/else
  收敛为单一 `runAction`。文案沿用该文件硬编码中文惯例（未接 i18n）。
- **缓行**：拖拽登记（应用无全局 drop 面，OfficeFilePicker 的
  `file.path` 模式可行但侧栏 drop 区成本高于收益）；wiki
  recent_projects 统一（其喂 `wiki/project_authorization` 安全白名单、
  search_routes 搜索默认域与 MCP，POSIX-only 原语在 Windows 上 skip
  测试——迁移必须先在 SQLite 上复刻授权语义，独立批次）。
- **win7 对齐**：ProjectSection/测试随 P1 新文件走；CommandPalette 在
  win7 分支分歧大（-237 行），P2 对其改动按 main 结构走，cherry-pick
  需按 win7 本地结构重放（局部小改）；commandItems 纯追加低风险。

## 10. P3 落地记录（2026-09-13，feat/projects-p3）

方案：`docs/plans/2026-09-13_projects-p3-plan.md`。

- **Chat 头部当前项目徽标**（新组件 `src/widgets/chat/ProjectBadge.tsx`，
  Chat.tsx 头部 1 行插入）：绑定工作区时显示 Folder + 项目名 chip，
  tooltip 为完整路径；名称优先精确匹配已登记项目，未登记历史绑定回退
  `basename(path)`；清单拉取失败静默降级。组件纯展示、不依赖 provider
  （workspacePath 由 Chat 既有 `useCurrentWorkspace()` 透传）。
- **否决/缓行**：项目清单拖拽排序否决——清单语义是最近打开排序
  （last_opened_at），手动排序与 recency 打架，负价值；拖拽登记继续
  缓行（同 §9）。
- **win7 对齐**：组件与测试纯新增；Chat.tsx 仅 1 行 JSX 插入（该文件
  在 win7 分支分歧大，机械重放）；无 IPC/后端/依赖变更。

## 11. P4 落地记录（2026-09-13，feat/projects-p4）

方案：`docs/plans/2026-09-13_projects-p4-plan.md`。纯前端收尾批次。

- **子行会话删除**：子行 hover 显现 TwoStepDelete（两步防误触）→
  `sessionApi.delete` → 联动刷新子列表 / 项目清单 / 会话区 store；
  失败 toast 且不收起子列表。
- **清单自动刷新**：订阅 store `sessions` 长度变化（任意来源的会话
  增删）→ 400ms 防抖 `refresh()` + 已展开项目子列表刷新。session_count
  保持后端聚合为唯一事实源，不本地推算。
- **win7 对齐**：改动全部位于 P1/P2 新文件，纯追加；无后端/IPC 变更。

## 12. P5 落地记录（2026-09-13，feat/projects-p5-drag）

方案：`docs/plans/2026-09-13_projects-p5-drag-plan.md`。两轮缓行的拖拽
登记以**区块局部方案**落地：只在"项目"分组内容区接收 drop，不触碰全
局 drop 面（那是缓行的原因）。

- 拖入文件夹 → 批量 `register`（路径取 Electron `File.path`，与
  OfficeFilePicker 同判据；浏览器无 path 静默忽略）；目录有效性由后端
  `validate_workspace` 校验（400 invalid_workspace_path），零新增 IPC；
- 成功 N 个 toast 计数并刷新清单；失败逐条提示；**不自动打开**（区别
  于 + 按钮的登记即打开——拖拽是顺手动作，静默导航会打断工作流）；
- dragOver 高亮虚线框 + 提示文案，dragLeave/drop 复位；
- 迁移注记：Electron ≥32 需将 `File.path` 迁到 `webUtils.getPathForFile`
  （当前 21.4.4 与 win7 LTS 冻结版均支持 File.path，两端一致）。

## 13. P6 落地记录（2026-09-14，feat/wiki-projects-bridge）

方案：`docs/plans/2026-09-14_wiki-projects-bridge-plan.md`。前置变化：
#760（R32 Windows reparse-safe 原语）解除了 recent_projects 的
POSIX-only 阻塞（`test_recent_projects.py` 在 Windows 16/16），两轮
缓行的 wiki 统一得以启动——本批为**最小加法桥接**，非存储迁移。

- **授权桥接**：`authorize_registered_project`（约 24 个 wiki 端点的
  唯一门禁）接受 recents ∪ projects 注册表并集（新增
  `_projects_registry_paths()`：lazy import ProjectRepository，异常 →
  空列表，fail-closed 语义不变）；
- **MCP 对齐**：`_authorized_project_root` 的 registered 集合同样并集；
- **写侧双登记**：wiki open/create 成功后 `register_quietly` 同步进
  侧栏清单（容错，失败不影响 wiki 主流程）——两个域的"用户显式用作
  Sage 工作目录"信任语义对齐；
- **明确不改**：全局搜索 `_search_knowledge` 的 `recents[0].path`
  默认域（改它=静默改变知识库搜索语义）；`GET /wiki/recent-projects`
  响应结构；存储迁移（双轨稳定后再议）。
- 规范化差异用现有 `_same_path`（normcase）吸收，双方向 resolve 后比较。
- win7 对齐：`project_authorization.py` / `mcp_server.py` / `wiki_routes`
  三处均为小块追加；`project_repo.py` 为 P1 新文件；全部 py3.8 兼容。

## 14. W5（2026-09-14，feat/wiki-files-win-unlock）

wiki/files 全量 Windows 解锁（`docs/plans/2026-09-14_wiki-files-win-unlock-plan.md`）：
其余 12 个 secure_* 补 reparse-safe Windows 分支（沿用 R32 原语），wiki
create/open/list 在 Windows 恢复可用；顺带修复两个 R32 原语缺陷
（CREATE_ALWAYS 先截断后复核绕过多链接契约、校验失败句柄泄漏）与
secure_read_text 的 `..` 逃逸缺口。测试侧：path_security /
security_final_paths / project_context / skill_md_importer /
P6 桥接集成的 Windows skip 解除（symlink 夹具改能力探测）。
