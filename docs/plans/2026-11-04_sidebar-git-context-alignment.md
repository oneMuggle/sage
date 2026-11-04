# 侧边栏 Git 面板上下文对齐方案

> **分支**: `fix/sidebar-git-context-alignment`
> **日期**: 2026-11-04
> **状态**: 进行中

## 背景与目标

### 问题

左侧边栏 Git 面板（`GitStatusSection`）与右侧变更 Tab（`ChangesSection`）显示不一致信息：左侧有内容，右侧显示"非 Git 仓库"。

### 根因

两个面板读取**不同的目录**：

| 面板 | 目录来源 | 代码位置 |
|---|---|---|
| 左侧 Git | `projectApi.list()` → 按 `lastOpenedAt` 排序取第一条 | `GitStatusSection.tsx:103-116` |
| 右侧变更 | 当前会话绑定的 `session_workspace` | `workspace_routes.py:325-332` |

当会话绑定 scratch 目录（非 git）而最近打开的项目是 git 仓库时，必然出现不一致。

### 目标

1. **P0**: 统一数据源——左侧 Git 面板绑定"当前上下文"而非"最近打开项目"
2. **P1**: 后端 git status 逻辑去重，避免漂移
3. **P2**: 优化空状态文案，显示正在检查的目录路径

## 涉及的文件与模块

### 前端

| 文件 | 改动 |
|---|---|
| `src/widgets/sidebar/sections/GitStatusSection.tsx` | 数据源从 `projectApi.list()[0]` 改为 `useCurrentWorkspace()` + 兜底逻辑 |
| `src/shared/lib/workspaceContext.tsx` | 已有 `useCurrentWorkspace()` hook，无需改动 |
| `src/widgets/layout/Sidebar.tsx` | 可选：传递 sessionId 给 GitStatusSection（若需要） |

### 后端（P1）

| 文件 | 改动 |
|---|---|
| `backend/api/git_status_routes.py` | 复用 `git_tool.py` 的 git status 解析逻辑 |
| `backend/tools/git_tool.py` | 提取 git status 解析为可复用函数 |

### 测试

| 文件 | 改动 |
|---|---|
| `src/widgets/sidebar/sections/__tests__/GitStatusSection.test.tsx`（新建） | 验证数据源优先级 |
| `backend/tests/api/test_git_status_routes.py` | 验证复用逻辑无回归 |

## 技术方案

### P0: 前端数据源对齐

**当前逻辑**（`GitStatusSection.tsx:103-116`）：

```typescript
const resolveProjectPath = useCallback(async () => {
  const projects = await projectApi.list();
  const sorted = [...projects].sort((a, b) => 
    (b.lastOpenedAt ?? 0) - (a.lastOpenedAt ?? 0)
  );
  setProjectPath(sorted[0].path);
  return sorted[0].path;
}, []);
```

**新逻辑**（上下文解析器）：

```typescript
import { useCurrentWorkspace } from '../../../shared/lib/workspaceContext';

const resolveContextPath = useCallback(async () => {
  // 1. 优先取当前会话绑定的 workspace
  const currentWs = useCurrentWorkspace();
  if (currentWs) {
    setProjectPath(currentWs);
    return currentWs;
  }
  
  // 2. 兜底：最近打开的项目
  const projects = await projectApi.list();
  if (projects.length > 0) {
    const sorted = [...projects].sort((a, b) => 
      (b.lastOpenedAt ?? 0) - (a.lastOpenedAt ?? 0)
    );
    setProjectPath(sorted[0].path);
    return sorted[0].path;
  }
  
  setProjectPath(null);
  return null;
}, []);
```

**空状态优化**（非 git 时显示目录路径）：

```tsx
if (!loading && status && !status.is_git_repo) {
  return (
    <SiderSection sectionKey="git" label={t('git.title')}>
      <div className="px-3 py-4 text-xs text-muted-foreground">
        <p>当前目录不是 Git 仓库</p>
        {projectPath && (
          <p className="mt-1 font-mono text-[10px] opacity-70">
            {projectPath}
          </p>
        )}
      </div>
    </SiderSection>
  );
}
```

### P1: 后端 git status 去重

**当前问题**：`git_status_routes.py` 和 `git_tool.py` 各自实现 git status 解析（ahead/behind、porcelain 等），容易漂移。

**方案**：提取 `git_tool.py` 的解析逻辑为独立函数，让 `git_status_routes.py` 复用。

```python
# backend/tools/git_status_parser.py（新建）
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class GitStatusInfo:
    branch: Optional[str]
    upstream: Optional[str]
    ahead: int
    behind: int
    files: List[dict]

def parse_git_status(repo_path: str) -> GitStatusInfo:
    """统一 git status 解析入口"""
    # ... 实现 ...
```

```python
# backend/api/git_status_routes.py
from backend.tools.git_status_parser import parse_git_status

async def get_git_status(path: str):
    info = parse_git_status(path)
    return GitStatusResponse(
        is_git_repo=True,
        branch=info.branch,
        ahead=info.ahead,
        behind=info.behind,
        files=info.files,
    )
```

## 实施步骤

- [x] 步骤 1：修改 `GitStatusSection.tsx`，引入 `useCurrentWorkspace()` 作为主数据源
- [x] 步骤 2：优化非 git 空状态文案，显示目录路径
- [x] 步骤 3：编写前端单元测试 `GitStatusSection.test.tsx`，验证数据源优先级
- [x] 步骤 4：后端提取 `git_status_parser.py`，统一解析逻辑
- [x] 步骤 5：修改 `git_status_routes.py` 复用新解析器
- [x] 步骤 6：编写后端测试验证无回归
- [ ] 步骤 7：本地端到验证（左右面板一致性）
  - 已完成：前端 13 例（含数据源优先级/空状态路径）、后端 59 例（含真实 tmp 仓库）、`tsc --noEmit`、eslint。
  - 未完成：Electron 实机左右面板对照（需启动桌面端并绑定 scratch 会话），本次未执行。

> 实施记录：
> - 共享解析器 `backend/tools/git_status_parser.py` 暴露 `parse_status_porcelain_v1_z`，
>   `GitStatusTool` 与 `GET /git/status` 均改为消费它。
> - `/git/status` 由「rev-parse 取分支 + 非 -z porcelain」改为单次
>   `status --porcelain=v1 -z -b`，中文/空格路径原样返回；`_get_branch_info` 删除。
> - 解析器修正旧正则 `[^\s.]+` 截断含点分支名（如 `release/v0.5.4`）的缺陷，
>   并支持 unborn 分支头 `## No commits yet on <branch>`。
> - 测试：`test_git_status_parser.py`（6 例）+ 路由新增中文路径/含点分支 2 例；
>   `LC_ALL=C` 下 59 例全绿（默认环境下 3 个 commit/stash 用例因 git 中文输出失败，
>   属已知环境性失败）。

## 风险评估与依赖

### 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `useCurrentWorkspace()` 在非 chat 页返回 undefined | 中 | 低 | 已设计兜底逻辑（最近打开项目） |
| 后端解析器提取引入行为差异 | 低 | 中 | 充分测试覆盖 + 灰度发布 |
| 用户期望"左侧永远是某个固定项目" | 低 | 中 | 空状态显示路径，让用户立刻看出上下文 |

### 依赖

- 无新增依赖
- `useCurrentWorkspace()` 已存在于 `src/shared/lib/workspaceContext.tsx`
- `AppProviders` 已挂载 `SessionWorkspaceProvider`，全局可用

## 验证计划

1. **单元验证**：前端 `GitStatusSection.test.tsx` 验证数据源优先级；后端 `test_git_status_routes.py` 验证解析无回归
2. **集成验证**：在 /chat 页（有 session）和 /projects 页（无 session）分别验证左右面板数据源一致
3. **回归验证**：CI 绿（现有测试无破坏）

## 后续（不在本次范围）

- P2: 左栏改名「仓库状态」、右栏改名「本次变更」，明确分工文案
- P3: builtin 检查点入口收敛到项目工作台
