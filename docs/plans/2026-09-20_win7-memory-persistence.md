# Win7 记忆持久化与管理链路修复实施计划

## 背景与目标

Win7 `v0.4.9-alpha.45-win7` 的记忆管理链路存在多处契约断点：renderer 使用的 `window.electronAPI.memory` 运行时桥接缺失；搜索 IPC 使用 POST 而后端仅支持 GET；手工保存未携带会话上下文且返回契约过窄；数据库路径虽然已有 packaged resolver，但缺少有效诊断，升级后可能读取合法空库。目标是让保存、列表、搜索、删除和管理页始终经过同一套可测试契约，并让数据库路径/PID/构建版本问题可定位，不自动覆盖用户旧数据。

## 范围

- Electron preload 的 memory runtime bridge 与类型声明。
- Memory 页面统一使用 `memoryApi`，不再直接依赖旧式 `window.electronAPI.memory` 数据方法。
- memory IPC/API 的 GET/POST、字段名、session_id、响应 envelope 和输入校验。
- packaged Win7 数据库路径的脱敏诊断、启动日志和旧库发现提示所需后端/前端接口。
- main 与 release/win7 兼容的单元、集成、TypeScript 测试；不改变两个长期分支的依赖策略，不自动迁移或删除数据库。

## 技术方案

1. 保留 `sage:invoke` 作为唯一认证 HTTP 入口，在 `electron/preload.ts` 暴露薄的 `memory` facade；facade 只转发命令，不复制 HTTP 逻辑。
2. `src/pages/Memory.tsx` 的 all/profile/summary/save/delete 流程统一改用 `memoryApi`。`MemoryBrowser` 作为列表展示组件继续复用同一封装，成功空 envelope 与真实错误分别呈现。
3. 将 `search_memory` 改成 GET query 参数，与 `legacy_routes.py` 对齐；保存请求显式携带可选 `session_id`，后端校验 `memory_type` 与 importance，未知类型/非法输入返回 4xx 而非伪成功。
4. 增加只读运行时诊断信息：构建版本、后端 PID、数据库路径的 basename/hash 或路径类别，不暴露原始 token；保留 `SAGE_DB_PATH` 显式覆盖优先级，检测并报告它，不静默复制旧库。
5. 所有新增行为先写失败测试，再以最小修改实现；Win7 代码避免 PEP 604/585，使用 `typing.Optional/List/Dict`。

## 实施步骤

### Task 1: 建立记忆桥接与页面入口回归护栏

**Status:** [x] 完成。命令路由、preload runtime bridge、保存/搜索契约测试已补齐。

### Task 2: Implement the runtime bridge and unify the Memory page

**Status:** [x] 完成。新增薄 `memory` facade；当前页面已使用 `memoryApi`，并修正保存响应类型。

### Task 3: Align search/save contracts and validate persistence inputs

**Status:** [x] 完成。搜索改 GET query，保存透传 `session_id`，后端校验类型、importance、空内容和伪成功。

### Task 4: Add safe database/runtime diagnostics

**Status:** [x] 完成。新增脱敏 `/memory/diagnostics`、Electron route/facade/API 及路径指纹测试；不改变路径选择、不自动迁移。

### Task 5: Cross-environment verification and compatibility hardening

**Status:** [ ] 进行中。前端测试/typecheck、Python 3.10 后端测试、py38 AST 通过；py38 `backend.main` 导入受当前 main 基线的 Pydantic v1/v2 分支问题阻塞。

### Task 6: Review and delivery preparation

**Status:** [ ] 待代码审查和最终验证。

## 风险与依赖

- alpha.45 安装包内的旧 `dist-electron` 无法由源码仓库直接替换；修复必须重新构建 Win7 安装包。
- 旧数据库可能位于旧 userData 或安装目录；本次只提供发现与诊断，不自动合并，避免覆盖或重复写入。
- release/win7 使用 Python 3.8/Pydantic v1 约束；共享后端代码不得引入仅 Python 3.10+ 的注解语法。
- 后端路径诊断必须对用户路径做脱敏，日志不得输出本地授权 token。
