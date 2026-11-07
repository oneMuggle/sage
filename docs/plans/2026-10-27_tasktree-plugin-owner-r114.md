# R114 编排任务树实时行插件归属规格

- 日期：2026-10-27
- 基线：`main` `df23587ee530e19acb3a0c0404f7f407bb317635`
- 状态：已合并（PR #2614）
- 编号说明：R114 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R113 扫描时曾把编排任务树记为范围外（他人活跃
  区）；复核后确认其两处行内文案直接拼裸工具名——运行中
  任务的「⏳ 等待审批: <tool>」徽章与「实时动态」事件
  行——在多智能体运行里是决策相关信息（哪个插件的工具
  在等审批/在执行）。后端子代理事件只带 `tool_name`、
  不带 `plugin_name`，故按 R111/R113 的前端名单派生口
  径补齐，改动面仅限该组件的文案拼装，不触编排逻辑。

## 1. 目标与语义

- 任务行等待审批徽章与实时动态事件行（等待审批/工具
  结果/工具调用三类）在工具名后追加「（所属插件:
  <name>）」，与 R111 相同的名单派生
  （`usePluginNames` + `findPluginToolOwner`），读不
  到/非插件工具不加。
- 供数门控：仅当任务板上存在带工具名的实时事件或等
  待审批工具名时才启用 hook；无编排实时数据的普通
  渲染不取数（既有测试夹具无 live 数据，零影响）。
- 文案跟随本文件既有硬编码中文风格（该文件未接
  i18n，「（错误）」同为全角括号硬编码），不为一处后
  缀引入 `useI18n`（无 Provider 会抛错、且会打破现
  有裸渲染测试）。

## 2. 边界

- 只改 TaskTreeSection 的文案拼装与供数：编排状态
  机、事件协议（后端 `subagent_events` 不加字段）、
  Drawer/EventTimeline 的通用载荷镜像不动；行内实
  时步骤 `liveStep` 是后端预拼装串，前端不二次加工。
- 后端/Electron 零改动（manifest 仍 274）；Win7 待
  对齐（无后端新代码）。

## 3. 测试计划

- 新 TaskTreeSection.pluginOwner 套件（mock
  usePluginNames）：徽章与事件行命中显示、名单不可
  用整体不加、内置工具不加；既有 TaskTree 四套件在
  无 live 夹具下不受影响（门控关）保持绿。

## 4. 本地证据

- 定向与相邻回归共 8 文件 60 例通过（新
  TaskTreeSection.pluginOwner 2、既有
  TaskTreeSection 17；ProgressSection/
  TaskTreeHierarchy/DependsOn/rerun/
  EventTimeline/SubagentDetailDrawer 共 41——
  无 live 夹具、门控关，保持绿）。
- tsc 通过；ESLint 改动文件 0 errors 0
  warnings；architecture-check 通过；
  diff-check、diagnostics(0) 全绿；
  `ipc:manifest:check` 通过（commands 实测
  274），后端零改动。
