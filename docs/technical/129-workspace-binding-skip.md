# 默认工作区解析与项目绑定跳过

> 日期：2026-11-25
> 默认工作区语义：2026-11-20 起，`~/Sage/` 取代原 scratch 目录
> 代码入口：`backend/services/default_workspace.py`、`backend/api/legacy_session_routes.py`、`src/widgets/welcome/ProjectPicker.tsx`

## 1. 定位与目标

Sage 的 git、文件读写、代码检索、checkpoint、浏览器截图/上传、下载、Office 等工具都要先确定一个工作区根目录，否则无法判断仓库根在哪、写盘是否越界。`DefaultWorkspaceResolver` 是"新会话该在哪个目录工作"的唯一决策来源，前端只传递用户意图，不自行推导目录。

三条约束：

1. 用户显式选择项目时，项目目录优先；
2. 用户选择"默认工作区"时，直接绑定 `~/Sage/`，不再让会话留空；
3. 只有所有候选都不可用时才返回 `None`，由调用方降级。

`skip_workspace_binding` 字段名沿用 2026-11-04 的接口命名，**当前语义是"用户选择了默认工作区"**，它不表示"会话没有工作区"，也不表示跳过整个解析逻辑。

## 2. 三种创建入口与结果

| 入口 | 前端调用 | 后端行为 | 会话绑定的目录 |
| --- | --- | --- | --- |
| 新会话页选具体项目 | `projectApi.createSession(projectId)` | `create_project_session()` 新建会话并 `bind_session_workspace(..., project.path)` | 项目目录 |
| 新会话页选"默认工作区（~/Sage/）" | `createSession(true)` → `POST /sessions { skip_workspace_binding: true }` | `resolve_to_default()` | `~/Sage/`（不可创建时回落临时目录） |
| 其他创建路径（未显式选择项目，例如 `@` 触发的草稿会话） | `createSession()` → `POST /sessions { skip_workspace_binding: false }` | `resolve_default_workspace(detected_root=...)` 走完整解析链 | 解析链命中的目录 |

> 草稿会话边界：新会话页的 `@` 草稿在没有项目时调用 `createSession()`（`skip=false`）。如果用户此前打开过项目或 Electron 嗅探到项目根，草稿可能绑定到偏好/检测目录，而不是 `~/Sage/`；提交时若项目选择仍为空，会复用该草稿。

## 3. 默认工作区解析链

### 3.1 `resolve_default_workspace()`

`DefaultWorkspaceResolver.resolve_default_workspace(project_path=None, session_id=None, detected_root=None)` 按顺序返回第一个可用目录：

| 顺序 | 候选 | `WorkspaceSource` | 说明 |
| --- | --- | --- | --- |
| 1 | `project_path` | `project` | 调用方已确定的项目目录；不可用则继续 |
| 2 | 会话绑定 | `session_binding` | 复用已有会话的活绑定 |
| 3 | `last_workspace_path` 偏好 | `user_preference` | 用户显式选择过并记住的目录 |
| 4 | `detected_root` | `detected` | Electron 从启动目录嗅探的项目根，仅作提示，不写入偏好 |
| 5 | 默认工作区 | `default` | `~/Sage/`，`is_fallback=True` |
| 6 | — | — | 返回 `None` |

"可用"指 `validate_workspace()` 通过：路径存在且是目录。任一步失败只降级到下一步，不中断会话创建。

### 3.2 显式默认工作区 `resolve_to_default()`

`skip_workspace_binding=True` 时不走上面的链，直接调用 `resolve_to_default()`：

- 调用 `_ensure_default_workspace()` 创建/确认 `~/Sage/`；
- 返回 `WorkspaceResolution(path=..., source=WorkspaceSource.DEFAULT, is_fallback=False)`；
- 两种目录都创建失败时返回 `None`，由路由层 fail-open（会话照常创建，`workspace_binding` 为 `null`）。

`is_fallback` 的含义：链尾落到默认工作区时为 `True`（没有更具体的候选，用了兜底）；用户显式选择默认工作区时为 `False`（这是用户本意，不是兜底）。

### 3.3 目录位置与回落

| 位置 | 代码 | 何时使用 |
| --- | --- | --- |
| `~/Sage/` | `default_workspace_path()` = `Path.home() / "Sage"` | 首选；Windows 下为 `%USERPROFILE%\Sage\` |
| `<tmpdir>/sage-workspaces/default` | `_ensure_default_workspace()` 的第二候选 | `~/Sage/` 因权限、只读、磁盘等原因无法 `mkdir` 时 |
| 返回 `None` | — | 两个候选都失败 |

`_ensure_default_workspace()` 用 `mkdir(parents=True, exist_ok=True)` 懒创建，返回 `Path.resolve()` 后的绝对路径。`default_workspace_path()` 本身只拼路径，不检查目录是否存在。

### 3.4 来源枚举与解析结果

`WorkspaceSource` 可取：

| 值 | 含义 |
| --- | --- |
| `project` | 显式项目路径 |
| `session_binding` | 已有会话绑定 |
| `user_preference` | 用户偏好（`last_workspace_path`） |
| `detected` | Electron 嗅探的启动目录 |
| `default` | 默认工作区 `~/Sage/` |
| `scratch` | 旧 scratch 工作区；生产解析路径已不再产生该值 |

`WorkspaceResolution` 是冻结 dataclass：`path: str`（绝对路径）、`source: WorkspaceSource`（命中的解析步骤）、`is_fallback: bool`（是否兜底命中，见 §3.2）。

## 4. `skip_workspace_binding` 的 API 语义

`POST /sessions` 的请求体 `SessionCreate` 中：

| 字段 | 类型 | 默认值 | 当前语义 |
| --- | --- | --- | --- |
| `skip_workspace_binding` | `bool` | `false` | `true` → `resolve_to_default()` 绑定 `~/Sage/`；`false` → `resolve_default_workspace()` 走完整链 |
| `detected_root` | `str \| null` | `null` | 仅 `skip=false` 时参与链的第 4 步 |

`skip=true` 时前端 `store.createSession()` 不调用 `getDetectedProjectRoot()`，避免嗅探结果干扰默认工作区。

## 5. 前后端调用链路

```
ProjectPicker 选"默认工作区（~/Sage/）" → onChange(null)
  ↓
Welcome.tsx handleSubmit: effectiveProjectId === null
  ↓
store.createSession(true)                      // skipBinding=true，跳过 detectedRoot 嗅探
  ↓
invoke('create_session', { detectedRoot: null, skipWorkspaceBinding: true })
  ↓
POST /sessions { skip_workspace_binding: true }
  ↓
legacy_session_routes.create_session
  ├─ repo.create(...)
  ├─ resolver.resolve_to_default()
  ├─ bind_session_workspace(conn, session.id, resolution.path)
  └─ 响应 workspace_binding = { path, source: "default", is_fallback }
```

`skip=false` 时只把 `resolve_to_default()` 换成 `resolve_default_workspace(detected_root=data.detected_root)`，其余相同。工作区解析与绑定整体包在 `try/except` 中：失败只记 `warning`，会话仍创建成功。

前端组件：

| 文件 | 作用 |
| --- | --- |
| `src/pages/Welcome.tsx` | `projectId` 从 `localStorage['welcomeProjectId']` 初始化；提交时 `effectiveProjectId = dialogProjectId ?? projectId`，非空走项目创建，空走 `createSession(true)` |
| `src/shared/lib/store.ts` | `createSession(skipBinding = false, options?)`；`skipBinding=false` 时嗅探 `getDetectedProjectRoot()` |
| `src/widgets/welcome/ProjectPicker.tsx` | `Select` 值 `value ?? 'default'`；选项 `默认工作区（~/Sage/）` 映射为 `null` |
| `src/app/providers/SessionWorkspaceProvider.tsx` | 持有当前会话绑定的唯一前端状态；`bind()` 写会话绑定并异步写偏好，`revoke()` 解绑并异步清除偏好 |

## 6. 工作区如何到达工具

工具侧统一读取 `ToolPolicy.workspace_root`（`backend/domain/tool_policy.py`，`Optional[str]`；`None` 表示不做边界检查）。分发路径有两种：

- **编排路径**：`legacy_routes` 从 `get_workspace_binding(...)` 读取会话绑定，作为 `workspace_root` 传给 `ChatDispatcher`；子代理以该值构造 `ToolPolicy(workspace_root=...)`。
- **主聊天单代理路径**：`SageAgent` 以默认 `ToolPolicy()` 构造工具（`workspace_root=None`）。文件类工具因此不做边界校验，强依赖根目录的工具仍会返回"需要绑定工作区"错误。

需要扫描产物的工具（`bash`、`execute_code`）通过 `resolve_workspace_root(policy)` 定位工作区：优先 `policy.workspace_root`，为空时回退当前会话绑定，仍为空才返回 `None`。

以下工具/能力在没有 workspace root 时会直接报错：

| 工具/能力 | 错误信息 |
| --- | --- |
| `git` | `git 工具需要绑定工作区（workspace）才能定位仓库根` |
| `apply_patch` | `apply_patch 需要绑定工作区（workspace）` |
| `codebase_search` | `codebase_search 需要绑定工作区（workspace）` |
| `symbol_search` | `symbol_search 需要绑定工作区（workspace）` |
| `checkpoint`（创建/列表/恢复） | `checkpoint 工具需要绑定工作区（workspace）` |
| `browser_screenshot` | `browser_screenshot 需要绑定工作区（workspace）` |
| `browser_interact` 的 upload | `browser_interact upload 需要绑定工作区（workspace）` |
| 下载 | `workspace_not_bound: 下载需要先绑定工作区（会话未绑定时不允许写盘）` |
| Office Word 样式模板 | `style_template_id 需要绑定工作区（tool context 无 workspace_root）` |

文件读写/编辑工具在 `workspace_root` 已设置时执行路径边界校验；`bash` / `execute_code` 通过 `resolve_workspace_root(policy)` 定位工作区，用于执行前后的产物快照。

## 7. 用户界面中的工作区

| 组件 | 位置 | 行为 |
| --- | --- | --- |
| `ProjectPicker` | 新会话页工具栏 | 第一项固定为 `默认工作区（~/Sage/）`，其余为已登记项目 |
| `WorkspaceSwitcher` | 聊天页头部 | chip 显示当前目录、来源、健康状态；展开后只能切到已登记项目，切换会 `PUT /sessions/{id}/workspace` 并写入偏好 |
| `WorkspaceBindModal` | Office 页 | 用原生目录选择器绑定/更换目录；`解除绑定` 撤销当前会话绑定；无绑定时提示"当前为默认工作区 ~/Sage/（可切换到具体项目目录）" |

来源标签映射在 `WorkspaceSwitcher` 的 `SOURCE_LABEL_KEYS`：`project` / `session_binding` / `user_preference` / `detected` / `scratch`。**没有 `default` 词条**，因此 `source="default"` 会回退显示 `workspace.switcher.source.detected`（中文"自动检测"）。当前 UI 没有"切回默认工作区"的一键入口；需要回到默认目录时，可在 Office 页手动选择 `Sage` 目录。

注意：`WorkspaceBindModal` 的"解除绑定"只调用 `workspaceApi.revoke()` 并清除偏好，**不会**把会话改绑到 `~/Sage/`；但弹窗的空态文案写的是"当前为默认工作区 ~/Sage/（可切换到具体项目目录）"，两者不一致。解除绑定后该会话实际没有工作区，直到用户重新选择目录或新建会话。

## 8. 与项目绑定的关系

- 选择项目创建会话时，项目路径直接写入会话绑定，并通过 `_remember_workspace_fail_open()` 写入 `last_workspace_path`；之后不带 `skip_workspace_binding` 的创建会优先命中该偏好（`source=user_preference`）。
- 项目分区按工作区路径匹配：`list_project_sessions` 使用 `repo.sessions_for_project(project.path)`。默认工作区会话的工作区是 `~/Sage/`，不会出现在某个项目分区下，除非 `~/Sage/` 本身被登记为项目。
- 会话内切换项目（`WorkspaceSwitcher`）只改会话绑定 + 偏好，不改变项目登记表。

## 9. API 契约

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/sessions` | 创建会话；`skip_workspace_binding` 决定 `resolve_to_default()` 或解析链；响应含 `workspace_binding` |
| `GET` | `/workspace/default` | 只读解析（`session_id`、`detected_root` 查询参数），不绑定 |
| `POST` | `/workspace/preference` | 记住目录（`{ path }`） |
| `DELETE` | `/workspace/preference` | 忘记记住的目录 |
| `POST` | `/workspace/migrate` | 导入旧版 localStorage 路径 |
| `GET` | `/workspace/health` | 检查目录健康状态 |
| `PUT` / `GET` / `DELETE` | `/sessions/{session_id}/workspace` | 绑定 / 查询 / 解除会话工作区 |

`workspace_binding` 与 `GET /workspace/default` 的响应字段均为 `path`、`source`、`is_fallback`。

## 10. 边界与已知缺口

1. **fail-open**：解析或绑定抛异常时，`create_session` 仍返回成功，`workspace_binding` 为 `null`。
2. **默认目录不可写**：`~/Sage/` 与临时目录都失败才返回 `None`；只要临时目录可写，会话仍有工作区。
3. **旧 scratch 目录不再参与解析**：`_ensure_scratch_workspace()` 与 `scratch_workspace_path()` 仍保留，但生产解析路径只调用 `_ensure_default_workspace()`；`WorkspaceSource.SCRATCH` 只出现在测试 mock 中。
4. **偏好不会因目录暂不可用而删除**：解析只读偏好；只有 `forget_workspace()` 或用户重新选择才会覆盖。
5. **来源标签缺口**：`source="default"` 在头部 chip 显示为"自动检测"（见 §7）。
6. **单代理路径的 workspace_root 为空**：主聊天单代理未把会话绑定注入 `ToolPolicy`，强依赖根目录的工具在该路径仍会报"需要绑定工作区"（见 §6）。
7. **解除绑定后的空态文案不准确**：`revoke()` 只解绑 + 清偏好，不会改绑默认工作区，但 `WorkspaceBindModal` 的空态仍显示"当前为默认工作区 ~/Sage/"（见 §7）。

## 11. 测试覆盖

| 测试文件 | 覆盖点 |
| --- | --- |
| `backend/tests/integration/test_skip_workspace_binding.py` | `skip=true` 调 `resolve_to_default()`、不调 `resolve_default_workspace()`；`skip=false` 与缺省字段调 `resolve_default_workspace()` |
| `backend/tests/unit/services/test_default_workspace.py` | 显式项目优先、会话绑定优先于偏好、失效偏好降级、默认工作区懒创建与幂等、`resolve_to_default()` 返回 `~/Sage/`、`default_workspace_path()` 等于 `home/Sage` |
| `src/pages/__tests__/Welcome.skipWorkspaceBinding.test.tsx` | 项目为空时 `createSession(true)` |
| `src/features/workspace/__tests__/WorkspaceSwitcher.test.tsx`、`WorkspaceBindModal.test.tsx` | 切换项目、绑定/解除绑定、健康状态展示 |
