# 75 — 项目级文件访问控制（Allowed Paths）

> 2026-09-17 · Phase 1-5 全部落地 · PR #1010 #1013 #1014

## 1. 概述

allowed_paths 为每个项目提供"额外只读路径规则"，让 agent 能读取 workspace 之外的
指定目录/文件。写入仍限于 workspace 内。

| 区域 | 读 | 写 |
|------|----|----|
| workspace 内 | ✅ | ✅ |
| allowed_paths 匹配 | ✅ | ❌ 触发审批 |
| 其他路径 | ❌ 触发审批 | ❌ 触发审批 |

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

- `file_tool.py` — `read_file` / `list_dir` 先检查 workspace 包含，
  不满足时调用 `is_allowed(candidate, project.allowed_paths)`
- `workspace_routes.py` — `/workspace/files` 搜索补充
  `_search_allowed_paths()`：展开规则 → `os.walk` 子树扫描 →
  结果以 `kind: "allowed-{file,ppt,...}"` 返回
- `sageFileUrl.ts` / `sageFileProtocol.ts` — `sage-file://` 协议放行
  allowed_paths 内路径

### 5.2 写入路径

写类工具（`write_file` / `edit_file` / `apply_patch`）**不检查 allowed_paths**，
始终限制在 workspace 内。试图写入 allowed_paths 路径会触发权限审批。

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
