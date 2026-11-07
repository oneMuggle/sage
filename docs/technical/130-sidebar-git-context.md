# 侧边栏 Git 面板：上下文对齐与后端解析去重

> 日期：2026-11-04
> 分支：`fix/sidebar-git-context-alignment`（main #2854）/ `fix/sidebar-git-context-alignment-win7`（win7 #2856）
> 方案：左栏 Git 面板与右栏变更 Tab 绑定同一目录；`git status` 解析收敛到单一共享实现

## 1. 定位与目标

Sage 的左侧边栏有 Git 状态面板，右侧聊天区有「变更」Tab。两者一度显示不一致的信息：左栏有文件列表，右栏却提示"非 Git 仓库"。

**根因**：两个面板读取了**不同的目录**。

| 面板 | 目录来源 | 代码位置 |
| --- | --- | --- |
| 左侧 Git | `projectApi.list()` → 按 `lastOpenedAt` 排序取第一条 | `GitStatusSection.tsx` |
| 右侧变更 | 当前会话绑定的 `session_workspace` | `workspace_routes.py` |

当会话绑定的是 scratch 目录（非 git），而"最近打开的项目"恰好是 git 仓库时，两者必然打架。

**目标**：

- **P0**：左栏 Git 面板改绑"当前上下文"（会话 workspace），与右栏同源；非 git 时显示实际检查的目录路径，便于排查；
- **P1**：`git status` 的解析逻辑在 `git_tool.py` 与 `git_status_routes.py` 两处重复实现，容易漂移——抽取共享解析器。

## 2. 前端：数据源对齐

### 2.1 解析顺序

`src/widgets/sidebar/sections/GitStatusSection.tsx` 的 `resolveContextPath()`：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | `useCurrentWorkspace()` | 当前会话绑定的 workspace，与右栏变更 Tab 同源 |
| 2 | `projectApi.list()` 兜底 | 无会话上下文时，按 `lastOpenedAt` 取最近打开的项目 |
| 3 | `null` | 两者皆空 → 显示"未选择项目" |

`useCurrentWorkspace()` 来自 `src/shared/lib/workspaceContext.tsx`，由 `AppProviders` 挂载的 `SessionWorkspaceProvider` 提供，全局可用。

### 2.2 空状态

非 git 仓库时，除了原有的"当前目录不是 Git 仓库"提示，还会把**正在检查的目录路径**渲染出来（等宽字体、截断、hover 显示全路径），让用户立刻能看出上下文错位的原因。

路径字号使用设计令牌 `text-ui-xs`（默认 14px 基准下等于 10px），而非硬编码 `text-[10px]`——后者会被 font-scale 门禁拦下。

## 3. 后端：共享解析器

### 3.1 `backend/tools/git_status_parser.py`

新增单一解析入口：

```python
parse_status_porcelain_v1_z(stdout: str) -> Dict[str, Any]
```

消费 `git status --porcelain=v1 -z -b` 的输出（NUL 分隔记录），返回：

| 字段 | 说明 |
| --- | --- |
| `branch` | 分支名；detached HEAD 为 `"HEAD"`；unborn 分支取 `## No commits yet on <branch>` 的名字 |
| `upstream` | 上游分支名 |
| `ahead` / `behind` | 领先 / 落后提交数 |
| `entries` | 逐条文件变更：`index_status` / `worktree_status` / `path`（rename 时含 `old_path`） |

解析器相对旧实现修正了两处缺陷：

- 旧正则 `^## (?P<branch>[^\s.]+)` 会在含点分支名（如 `release/v0.5.4`）处截断——新实现按 `##` 头后首个空格切分，不受点号影响；
- 支持 unborn 分支头 `## No commits yet on main`。

### 3.2 两个消费方

| 消费方 | 用法 |
| --- | --- |
| `backend/tools/git_tool.py`（`GitStatusTool`） | 替换原先内联的 `-z` 记录遍历 |
| `backend/api/git_status_routes.py`（`GET /git/status`） | 替换原先"rev-parse 取分支 + 非 -z porcelain"的两次调用，改为单次 `status --porcelain=v1 -z -b` |

`-z` 模式让中文与含空格路径原样返回，不需要引号转义再反转义。

### 3.3 语义状态映射

路由层把 porcelain 的 XY 两位状态映射成面板语义，优先级：

```
conflicted  >  staged (index)  >  working tree  >  untracked
```

conflicted 的判定覆盖 `U`（未合并）以及 `AA` / `DD`（双侧新增 / 双侧删除）。排序上 conflicted 最前、renamed 最后。

## 4. 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/unit/test_git_status_parser.py` | 分支头 / ahead-behind / 中文路径 / 含点分支 / unborn / detached / rename 旧路径 |
| `backend/tests/unit/api/test_git_status_routes.py` | 路由层回归，含中文路径与含点分支名用例 |
| `src/widgets/sidebar/sections/__tests__/GitStatusSection.test.tsx` | 数据源优先级：workspace 优先 / 最近项目兜底 / 两者皆空不请求 / 非 git 时显示路径 |

## 5. 已知事项

- `backend/tests/unit/test_git_tool.py` 中 3 个 commit / stash 用例在本机 `LANG=zh_CN` 下会失败（git 输出中文，断言英文 `"nothing"`）。这是既有的环境性失败，与本次改动无关；`LC_ALL=C` 下全绿。
- 未做 Electron 实机的左右面板对照验证（需启动桌面端并绑定 scratch 会话），单元测试已覆盖数据源选择逻辑。
- 后续（不在本次范围）：左栏改名「仓库状态」、右栏改名「本次变更」以明确分工；builtin 检查点入口收敛到项目工作台。
