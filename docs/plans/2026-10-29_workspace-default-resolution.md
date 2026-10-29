# 默认工作区决策优化方案

> 创建日期：2026-10-29
> 分支：`feat/workspace-optimization`
> 优先级：P0（核心决策链）→ P2（增强）
> 关联文档：`docs/technical/61-projects-module.md`

---

## 1. 背景与目标

### 1.1 现状问题

Sage 当前工作区决策逻辑分散，存在 **5 个实质缺陷**：

| # | 缺陷 | 影响 |
|---|---|---|
| D1 | `cwd` 探测失败时直接降级，用户无感知 | 用户以为是"项目会话"实际未绑定 |
| D2 | 通过 `project.open_project` 打开项目不写 `preferences` | 跨设备/重装后丢失上次路径 |
| D3 | 未绑定会话降级到"无工作区模式" | 工具不可用、知识不可见，但 UI 无警告 |
| D4 | `ProjectBadge` 只读 chip，不可切换 | 用户无法主动修改绑定 |
| D5 | 决策逻辑分散（前端 store + 后端 workspace） | 无测试覆盖，难以维护 |

### 1.2 设计目标

- **显式性 > 智能猜测**（主流应用共识：Cursor/Cline/Aider 都要求用户显式选择）
- **失败可感知**：决策失败时 UI 必须给出明确反馈
- **跨设备可恢复**：上次工作区路径持久化到 SQLite，跨重装/跨设备同步
- **决策集中化**：单一后端函数 + 完整测试覆盖

---

## 2. 主流应用对照（参考）

调研主流 AI 应用的兜底风格（2026-10 实测）：

| 应用 | 默认工作区 | 无项目时的兜底方式 |
|---|---|---|
| **Cursor** | 编辑器打开的文件夹 | 静默回落到 `$HOME` |
| **Cline** | VS Code 工作区 | 静默回落到 `~/Desktop` |
| **Windsurf / Devin / Zed** | 编辑器文件夹 | 展示欢迎页 + "打开文件夹" CTA |
| **Aider** | 进程 cwd | 显式提示「No git repo found, create one…?」 |
| **Claude Code** | 进程 cwd | cwd（必然存在） |
| **Claude.ai Projects** | 用户显式创建 | 云端沙盒 |
| **Sage 现状** | localStorage → cwd 探测 | 无任何兜底（未绑定即全功能失效） |

**关键启示**：「folder-opened = workspace」是普遍共识。「无项目」时主流应用分三种流派：
- **静默兜底派**（Cursor / Cline）：悄悄落到 HOME/Desktop，功能受限但不打断
- **显式提示派**（Aider）：弹窗让用户选择
- **引导欢迎派**（Windsurf / Zed）：欢迎页 + CTA

**Sage 选择 A 派（静默兜底 + 状态可见）**：
- 与 Cursor/Cline 的主流桌面工具习惯一致
- 草稿区天然就是"无项目时的合理落点"
- 通过 `WorkspaceSwitcher` 的"来源标签"让状态可见

---

## 3. 优化方案（8 项改动）

### 改动 1：集中化决策逻辑（P0，核心）

**文件**：新建 `backend/services/default_workspace.py`

```python
class WorkspaceResolution(BaseModel):
    """工作区决策结果"""
    path: Path
    source: Literal["project", "user_preference", "scratch"]
    is_fallback: bool = False

class DefaultWorkspaceResolver:
    """统一工作区决策（6 优先级）"""
    def resolve_default_workspace(self) -> WorkspaceResolution:
        """
        决策优先级：
        1. 显式 project_path 参数（来自 project.open_project）
        2. 会话绑定路径（来自 session_workspace_bindings）
        3. 用户偏好（来自 preferences 表）—— 跨设备同步
        4. localStorage 迁移（首次启动时从前端迁移到 preferences）
        5. 草稿工作区（<userData>/workspaces/default，惰性创建）
        6. null（彻底失败，UI 显示引导）
        """
```

### 改动 2：草稿工作区（P0）

**路径**：`<userData>/workspaces/default`（Electron app.getPath('userData')）

**创建时机**：仅在决策链路需要兜底时惰性创建（`mkdir -p`）

**特点**：
- 不是临时目录，是持久化草稿区
- 用户在其中的文件操作可保存
- 跨会话持续存在
- UI 通过 `WorkspaceSwitcher` 展示"来源：草稿"标签

### 改动 3：会话创建路径统一到后端（P1）

**删除**：`src/shared/lib/store.ts:252-283` 的 auto-bind 逻辑

**新增**：后端 `create_session` 时返回 `workspace_binding` 字段

```python
# backend/api/session_routes.py
class CreateSessionResponse(BaseModel):
    session: Session
    workspace_binding: WorkspaceResolution | None  # 后端决策结果
```

**前端**：收到响应后直接渲染，无需二次决策

### 改动 4：项目 open 同步写用户偏好（P1）

**文件**：`backend/data/project_repo.py:409 open_project`

**改动**：

```python
def open_project(self, path: str) -> Session:
    # 现有逻辑：复用会话或新建 bind
    # 新增：同步写入 preferences
    self._write_user_preference("last_workspace_path", path)
    return session
```

### 改动 5：`WorkspaceSwitcher` UI 组件（P2）

**文件**：`src/features/workspace/WorkspaceSwitcher.tsx`（新建）

**替换**：`src/widgets/chat/ProjectBadge.tsx`（只读 chip）

**功能**：
- 点击展开下拉菜单
- 选项：当前绑定 / 切换项目 / 切换草稿 / 查看历史
- 展示"来源标签"（项目 / 用户偏好 / 草稿）
- 草稿状态下显示轻提示「当前为草稿工作区，可切换至项目目录」

### 改动 6：工作区健康检查（P2）

**新增**：`backend/services/workspace_health.py`

```python
class WorkspaceHealthChecker:
    def check(self, workspace_path: Path) -> WorkspaceHealthStatus:
        """
        检查项：
        - 目录是否存在
        - 是否是目录（非文件）
        - 是否可访问（权限）
        - 是否有写权限（可选，仅警告）
        """
```

**触发时机**：
- 会话加载时（`loadSessions`）
- 切换工作区时
- 后端启动时（可选）

### 改动 7：per-project 默认工作区（P2，可选）

**新增**：`backend/data/project_repo.py` 增加字段

```python
class Project:
    default_workspace: str | None  # 该项目默认打开的工作区
    recent_workspaces: list[str]  # 该项目最近使用的工作区（最多 5 个）
```

**UI 影响**：`WorkspaceSwitcher` 下拉增加"为当前项目设置默认工作区"选项

### 改动 8：cwd 探测降级为最低优先级（P1）

**文件**：`electron/projectDetector.ts`

**改动**：
- `detectProjectRoot` 返回值从"首选"降为"参考"
- 仅当用户偏好为空时使用
- 失败时不静默降级，记录日志 + 返回 null

---

## 4. 接口契约

### 4.1 后端新增 API

```python
# backend/services/default_workspace.py

from pathlib import Path
from pydantic import BaseModel
from typing import Literal

class WorkspaceResolution(BaseModel):
    path: Path
    source: Literal["project", "user_preference", "scratch"]
    is_fallback: bool = False
    health_status: Literal["healthy", "missing", "inaccessible"] = "healthy"

class DefaultWorkspaceResolver:
    def __init__(self, database, electron_ipc=None):
        self.db = database
        self.electron_ipc = electron_ipc  # 可选：探测 cwd

    def resolve_default_workspace(
        self,
        project_path: str | None = None,
        session_id: str | None = None,
    ) -> WorkspaceResolution | None:
        """
        6 优先级决策链。
        返回 None 表示彻底失败（UI 显示引导）。
        """
```

### 4.2 前端修改 API

```typescript
// src/shared/lib/store.ts - 删除
// ❌ 删除 auto-bind 逻辑（252-283 行）

// backend/api/session_routes.py - 修改
class CreateSessionResponse(BaseModel):
    session: Session
    workspace_binding: WorkspaceResolution | None

// src/shared/lib/store.ts - 新增
createSession: async () => {
  const response = await invoke<CreateSessionResponse>('create_session', { title: '新对话' });
  set((state) => ({
    sessions: [response.session, ...state.sessions],
    currentSessionId: response.session.id,
  }));
  // workspace_binding 由后端决策，前端直接渲染
  if (response.workspace_binding) {
    setWorkspaceInfo(response.workspace_binding);
  }
  return response.session.id;
}
```

### 4.3 localStorage 迁移

```python
# backend/services/workspace_migration.py

def migrate_last_workspace_from_local_storage(frontend_ipc) -> str | None:
    """
    首次启动时从 localStorage 迁移到 preferences 表。
    一次性操作，迁移后删除 localStorage key。
    """
```

---

## 5. 实施步骤

### 里程碑 M1：P0 核心决策链（2-3 天） ✅ 2026-10-29 完成

- [x] 新建 `backend/services/default_workspace.py`
  - [x] `WorkspaceResolution` dataclass（frozen=True，pydantic-free 兼容 win7）
  - [x] `DefaultWorkspaceResolver` 类 + `resolve_default_workspace` 方法
  - [x] 4 优先级决策链实现（project / session_binding / user_preference / scratch）
- [x] 新增草稿工作区目录惰性创建逻辑
  - [x] `<userData>/workspaces/default` 目录管理（含 tmpdir 二级兜底）
  - [x] 跨平台路径处理（`Path.resolve()`）
- [x] 单元测试覆盖（`backend/tests/unit/services/test_default_workspace.py`）
  - [x] 6 种优先级场景测试（project / session_binding / user_preference / scratch + stale）
  - [x] 草稿目录创建测试（idempotent + env 路径）
  - [x] 失败场景测试（返回 scratch 兜底 / 不可用路径 fall-through）
- [ ] 集成测试（M2 完成后验证）
  - [ ] 新建会话时自动绑定决策结果
  - [ ] 跨会话决策一致性

### 里程碑 M2：P1 决策链整合（2 天） ✅ 2026-10-29 完成

- [x] 修改 `backend/api/legacy_session_routes.py`（`create_session` 返回 `workspace_binding`）
  - [x] `create_session` 返回 `workspace_binding`
- [x] 修改 `backend/api/project_routes.py`
  - [x] `open_project` 写入 `preferences`
- [x] 修改 `electron/projectDetector.ts`
  - [x] `detectProjectRoot` 降为最低优先级
  - [x] 失败时记录日志 + 返回 null
- [x] 修改 `src/shared/lib/store.ts`
  - [x] 删除 auto-bind 逻辑（252-283 行）
  - [x] 改用后端返回的 `workspace_binding`（`SessionWorkspaceProvider` 承载）
- [x] localStorage 迁移
  - [x] 新建 `backend/services/workspace_migration.py`
  - [x] 后端启动时一次性迁移（IPC `workspace_migrate_preference`）
  - [x] 迁移后删除 localStorage key

### 里程碑 M3：P2 UI 增强（3-4 天） ✅ 2026-10-29 完成

- [x] 新建 `src/features/workspace/WorkspaceSwitcher.tsx`
  - [x] 下拉菜单 UI
  - [x] 来源标签展示
  - [x] 草稿状态轻提示
- [x] 替换 `src/widgets/chat/ProjectBadge.tsx`（组件 + 2 个测试文件已删除）
- [x] 工作区健康检查
  - [x] 新建 `backend/services/workspace_health.py`
  - [x] `GET /workspace/health` 路由 + Electron IPC `workspace_health`
  - [x] UI 展示健康状态（颜色/图标）
- [ ] per-project 默认工作区（可选，本迭代不实现）
  - [ ] `Project` 模型增加字段
  - [ ] UI 设置入口

---

## 6. win7 同步策略

### 6.1 同步范围

| 改动 | win7 同步？ | 说明 |
|---|---|---|
| P0 核心决策链 | ✅ 必须 | 后端逻辑，pydantic 1.x 兼容 |
| P1 决策链整合 | ✅ 必须 | 后端 + 前端，零 pydantic 差异 |
| P2 UI 增强 | ✅ 必须 | 纯前端，零 pydantic 差异 |
| localStorage 迁移 | ✅ 必须 | 后端逻辑，pydantic 1.x 兼容 |

### 6.2 已知适配点

- **pydantic 1.x**：`WorkspaceResolution` 使用 `Literal`（win7 需 `typing_extensions` 回退）
- **路径处理**：`Path` 在 win7 上需 `os.fspath` 兼容（已验证）
- **前端 API**：零差异，直接 cherry-pick

### 6.3 同步时机

- M1 完成后立即 cherry-pick 到 `release/win7`
- M2/M3 在 win7 分支逐个 PR 同步
- 预期总同步 PR 数量：3-4 个

---

## 7. 风险评估

### 7.1 高风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| localStorage 迁移失败 | 用户丢失上次工作区 | 迁移前备份 localStorage 到 `localStorage_backup.json` |
| 草稿目录权限问题 | 无法创建草稿工作区 | 降级到 `os.tmpdir()` + UI 警告 |
| 后端决策与前端状态不一致 | 会话显示错误工作区 | 前端收到响应后立即更新本地状态，不二次决策 |

### 7.2 中风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| pydantic 1.x/2.x 差异 | win7 分支构建失败 | 使用 `Literal` 时加 `# noqa: UP038` |
| cwd 探测逻辑变更 | 老用户路径丢失 | 保留 1 个月 localStorage 兜底（迁移后不清除） |
| WorkspaceSwitcher UI 复杂度 | 开发周期延长 | P2 拆分为 3 个子 PR（基础 UI / 健康检查 / per-project） |

### 7.3 低风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 单元测试覆盖不足 | 决策逻辑回归 | 6 种优先级场景 + 2 种失败场景，覆盖率 >80% |
| 文档更新滞后 | 后续维护困难 | 每个 PR 同步更新 `docs/technical/61-projects-module.md` |

---

## 8. 验收标准

### 8.1 功能验收

- [x] 新建会话时自动绑定到决策结果（项目 / 偏好 / 草稿）
- [x] 通过 `project.open_project` 打开项目时同步写入 `preferences`
- [x] 未绑定会话降级到草稿工作区（非"无工作区"）
- [x] `WorkspaceSwitcher` 可切换工作区
- [x] 工作区健康状态在 UI 可见

### 8.2 性能验收

- [ ] 决策函数执行时间 <100ms（含磁盘 IO）
- [ ] localStorage 迁移耗时 <500ms（一次性）
- [ ] 草稿目录创建耗时 <50ms（惰性）

### 8.3 兼容性验收

- [ ] win7 分支构建通过
- [ ] pydantic 1.x/2.x 双版本测试通过
- [ ] 前端 API 零差异

---

## 9. 后续优化（不在本期范围）

- 工作区历史记录（最近 10 个）
- 工作区搜索（模糊匹配路径）
- 工作区收藏夹（固定常用项目）
- 工作区模板（预置目录结构）

---

## 10. 附录

### 10.1 相关文件清单

**后端**：
- `backend/services/default_workspace.py`（新建）
- `backend/services/workspace_health.py`（新建）
- `backend/services/workspace_migration.py`（新建）
- `backend/api/session_routes.py`（修改）
- `backend/data/project_repo.py`（修改）
- `backend/data/database.py`（参考 `preferences` 表）

**前端**：
- `src/shared/lib/store.ts`（修改）
- `src/features/workspace/WorkspaceSwitcher.tsx`（新建）
- `src/widgets/chat/ProjectBadge.tsx`（删除）
- `src/shared/lib/lastWorkspace.ts`（迁移后删除）

**Electron**：
- `electron/projectDetector.ts`（修改）

**测试**：
- `backend/tests/services/test_default_workspace.py`（新建）
- `backend/tests/services/test_workspace_health.py`（新建）

### 10.2 决策优先级示例

**场景 1：用户在项目中打开 Sage**
```
project_path = /home/user/my-project
→ 优先级 1 命中：返回 WorkspaceResolution(path=/home/user/my-project, source="project")
```

**场景 2：用户上次打开过项目**
```
project_path = None
session_binding = None
user_preference = /home/user/old-project
→ 优先级 3 命中：返回 WorkspaceResolution(path=/home/user/old-project, source="user_preference")
```

**场景 3：首次使用，无历史**
```
project_path = None
session_binding = None
user_preference = None
localStorage = None
→ 优先级 5 命中：创建草稿目录，返回 WorkspaceResolution(path=<userData>/workspaces/default, source="scratch", is_fallback=True)
```

**场景 4：彻底失败**
```
project_path = None
session_binding = None
user_preference = None
localStorage = None
草稿目录创建失败（权限不足）
→ 返回 None，UI 显示引导弹窗
```
