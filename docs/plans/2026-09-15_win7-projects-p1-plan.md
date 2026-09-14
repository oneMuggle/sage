# P10 计划——项目模块 P1 核心对齐 release/win7

> 日期: 2026-09-15 · 基线: release/win7 `de8dad67`
> 分支: `feat/win7-projects-p1` · 上游: main 项目模块系列（#727/#734/#739/#743/#772/#775/#802/#810/#815/#818）

## 1. 动机

目标要求"注意 main 分支与 win7 分支的对齐"。项目模块系列十批已全部
落 main，但对齐至今停留在文档级适配说明；本批开始**执行**对齐——首
批移植 P1 核心（注册表 + 侧栏 + 打开流），后续批次按需跟进。

## 2. 前置核实（本批可行性依据）

- win7 分支 requirements 为 **pydantic 2.5.0**（非旧文档所称 1.x）——
  `ConfigDict(extra="forbid")` 路由模型可直接移植，无需降级改写；
- 占位 `ProjectSection` / `SiderSection(maxHeight)` / `TwoStepDelete
  (data-testid)` / `store.loadSessions` / `desktopInvoke.InvokeError` /
  `session_workspace_bindings` 表全部在位；
- 全部 P1 新文件为 py3.8 兼容（typing.Dict/Tuple、无海丝）；
- 后端新文件不依赖 wiki/files 等平台差异面。

## 3. 范围（仅 P1 核心；P2+ 依赖 win7 分歧面较大的文件，另行评估）

| 文件 | 动作 |
| --- | --- |
| backend/data/project_repo.py | 新增（自 main e102f55e 提取，py3.8 已验） |
| backend/api/project_routes.py | 新增（pydantic v2 写法，win7 2.5.0 兼容） |
| backend/tests/integration/test_project_routes.py | 新增 |
| src/shared/api/projectApi.ts | 新增 |
| src/widgets/sidebar/sections/ProjectSection.tsx | 占位 → P1 实现（列表/登记/打开/移除/缺失标记） |
| src/widgets/sidebar/sections/ProjectSection.test.tsx | 新增 |
| backend/data/database.py | projects 建表块（session_workspace_bindings 之后） |
| backend/main.py | import + include_router 各 1 行 |
| electron/commands.ts | projects_* 六命令（workspace_revoke 后追加） |
| src/widgets/layout/Sidebar.tsx | handleOpenSession 抽取 + ProjectSection 传参 |
| src/shared/lib/i18n/{zh,en}.ts | sider.project.* 词条 |
| src/shared/api/index.ts | export projectApi |

**不含**（依赖 win7 分歧面较大文件或后续批次语义）：P2 子列表/命令面板、
P3 徽标、P4 删除/刷新、P5 拖拽、P6 wiki 桥接、P7 搜索、P8 存储迁移。

## 4. 测试

- 后端：test_project_routes.py 全绿（本机 3.12 冒烟 + CI 的
  "Backend (Python 3.8, Win7 LTS)" 真实 3.8 验证）；
- 前端：ProjectSection.test.tsx（P1 版 7 例）+ 全量对照；
- ruff / eslint / tsc。

## 5. 流程

PR **base: release/win7**（本批的对齐目标分支），CI 走 win7 通道
（Backend py3.8 LTS job 将真实执行）；绿后 squash merge，清理，win7
分支同步。commit 前缀按 win7 惯例 `cherry(win7):`。
