# 75 — 项目级文件访问控制（Allowed Paths）

> 2026-09-17 · Phase 1-5 全部落地 · PR #1010 #1013 #1014
> 2026-11-02 · 读写边界放宽：读任意路径、写走白名单/审批

## 1. 概述

allowed_paths 为每个项目提供"额外信任路径规则"。2026-11-02 起读写边界拆开：
读取任意路径无需审批（与 `read_file` 对齐）；写入 workspace 内直接放行，
workspace 外命中 allowed_paths 自动放行、未命中走审批。

| 区域 | 读 | 写 |
|------|----|----|
| workspace 内 | ✅ | ✅ |
| allowed_paths 匹配 | ✅ | ✅ |
| 其他路径 | ✅ 无需审批 | ⚠️ 触发审批 |

## 2. 数据模型

```sql
ALTER TABLE projects ADD COLUMN allowed_paths TEXT DEFAULT '[]'
-- JSON 数组，存储路径规则字符串
```

`Project` dataclass（`backend/data/project_repo.py`）新增 `allowed_paths: List[str]`，
默认空列表。REST API（`backend/api/project_routes.py`）在 create/update/GET 响应中
暴露该字段。

## 3. 路径规则语法

类 `.gitignore` glob，由 `backend/office/allowed_paths.py` 解析：

| 规则 | 含义 |
|------|------|
| `~/Documents/**` | Documents 及所有子目录 |
| `~/Desktop/*.pdf` | 桌面所有 PDF |
| `/tmp/scratch/*` | 直接子文件（不含子目录） |
| `~/projects/shared` | 精确匹配 |

- `~` → `Path.home()`
- 相对路径 → 相对于项目根目录
- 前端 `AllowedPathsEditor` 输入规则，经 `projectApi.updateAllowedPaths` 写入
- 新建项目（`register_project`）在请求未显式提供 `allowed_paths`（`None`）时预填
  `default_allowed_paths()`：`~/Documents/**`、`~/Desktop/**`、`~/Downloads/**`
  （仅实际存在的目录；Windows 追加 `D:/Documents/**`、`E:/Documents/**`）。
  显式 `[]` 尊重清空选择；`ON CONFLICT(path)` 更新不会覆盖用户已编辑的规则。

## 4. 匹配引擎

```
is_allowed(candidate, allowed_paths) → bool
  ├─ 展开规则 (_expand_rule)
  ├─ 目录规则: candidate.relative_to(rule_path) 成功 → True
  └─ glob 规则: _glob_match / _doublestar_match → bool
```

- `_glob_match`: 单星 `*` 不跨目录分隔符
- `_doublestar_match`: `**` 跨任意层级目录
- 跨平台：Windows 路径自动归一化

## 5. 读写分离

### 5.1 读取路径

- `file_tool.py` — `read_file` / `list_dir` 不设工作区围栏，可读取任意路径
- Office READ 工具（`office_list` / `office_read` / `office_read_pdf` /
  `office_analyze` / LaTeX & Word intelligence 读取工具）同样移除硬拒绝；
  service 层围栏基座使用 `workspace_for_policy()`：输入在绑定工作区内时用绑定
  工作区，否则回退到输入父目录（保留 `..` / symlink 防护）
- `workspace_routes.py` — `/workspace/files` 搜索补充
  `_search_allowed_paths()`：展开规则 → `os.walk` 子树扫描 →
  结果以 `kind: "allowed-{file,ppt,...}"` 返回
- `sageFileUrl.ts` / `sageFileProtocol.ts` — `sage-file://` 协议放行
  allowed_paths 内路径

### 5.2 写入路径

`BaseTool._enforce_workspace` 四层判定（`backend/tools/base.py`）：

1. 路径在 `workspace_root` 内 → 放行
2. 命中当前 session 绑定项目的 `allowed_paths` → 放行
3. 落在本次调用的已审批路径作用域内（`enter_approved_paths` 注入的 ContextVar）→ 放行
4. 其余 → 拒绝 `path_outside_workspace`

`office_create` / `office_update` / `office_delete` 及模板填充、PDF 生成、LaTeX
编译等写工具都在权限边界 specs 中登记；工作区外未命中白名单的写入由审批闸口
放行本次调用。

### 5.3 @-mention 附件

`backend/chat/attachment_resolver.py` 的 `_resolve_attachment_path()` 接受
`allowed_paths` / `project_root`：命中白名单的工作区外文件放行（读取基座回退到
文件父目录），未命中返回 `skipped_reason: "outside_workspace"`，并在
`<attachments_skipped>` 段向模型说明跳过原因。legacy / hex 路由在事件循环内查询
`get_session_allowed_paths(session_id)` 后传入线程池，避免 DB 访问落在 worker 线程。

## 6. 审批流扩展

`permission_gate.py` 新增：

- `extract_target_path(args)` — 从工具参数提取路径（`path` / `file_path` /
  `target_path` / `directory` / `file` 键）
- `ApprovalRequest.target_path` — 携带目标路径到前端

前端 `ApprovalDialog` 新增"项目级允许"按钮：

1. 查找当前 workspace 对应的项目
2. 生成规则：目录追加 `/**`，文件原样
3. 调用 `projectApi.updateAllowedPaths` 持久化
4. 自动批准请求

## 7. 前端搜索集成

`FileSearchKind` / `WorkspaceSearchKind` 新增 `allowed-{file,ppt,word,excel,pdf}`：

- `classifyAtFileSelection()`: `allowed-file` → `'file'`（纯文件插入 `@path`）
- `fileSearchResultToChatOfficeRef()`: `allowed-file` → `null`（不伪造 OfficeRef）
- `allowed-ppt/word/excel/pdf`（docId=null）→ `'office-import'`（走导入流程）
- `AtFileMenu.KIND_ICON`: 映射 `allowed-*` 图标

## 8. 文件清单

| 文件 | 改动 |
|------|------|
| `backend/data/database.py` | projects 表添加 `allowed_paths` 列 |
| `backend/data/project_repo.py` | Project 模型 + CRUD |
| `backend/office/allowed_paths.py` | 匹配引擎（新增） |
| `backend/api/project_routes.py` | REST API 暴露 allowed_paths |
| `backend/api/workspace_routes.py` | 搜索补充 `_search_allowed_paths` |
| `backend/tools/file_tool.py` | read_file/list_dir 检查 |
| `backend/services/permission_gate.py` | target_path 提取 |
| `src/shared/api/types.ts` | WorkspaceSearchKind + PermissionRequest.target_path |
| `src/shared/api/fileSearchClient.ts` | FileSearchKind + 分类逻辑 |
| `src/shared/api/projectApi.ts` | updateAllowedPaths |
| `src/features/chat/AtFileMenu.tsx` | KIND_ICON allowed-* |
| `src/widgets/permission/ApprovalDialog.tsx` | 项目级允许按钮 |
| `src/widgets/sidebar/sections/AllowedPathsEditor.tsx` | 规则编辑器（新增） |
| `electron/sageFileUrl.ts` | matchesAllowedRule |
| `electron/sageFileProtocol.ts` | 协议放行 |
| `electron/commands.ts` | IPC 命令 |
