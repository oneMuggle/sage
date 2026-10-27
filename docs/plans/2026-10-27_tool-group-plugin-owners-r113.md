# R113 转录工具组折叠头插件归属规格

- 日期：2026-10-27
- 基线：`main` `c9218b989e1a264fdbb8759cee24dd448f4644bd`
- 状态：已开 PR（#2589），待合并
- 编号说明：R113 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R111 给转录的每张通用工具卡加了归属后缀，但多
  步调用的默认形态是折叠组（≥3 次调用时只显示「已执
  行 N 步工具调用 (名×数 · …)」的组头，卡片明细收
  起）——折叠态下插件参与完全不可见，必须展开才能确认
  一组调用里有没有、有哪些插件的工具。本轮补组头这一
  最后一块转录缺口。

## 1. 目标与语义

- 工具组组头在计数摘要后追加弱化后缀「所属插件:
  <名1>、<名2>」（组内全部工具调用的归属去重、按首
  次出现排序；复用 `permission.from_plugin` 文案，
  `data-testid="tool-calls-group-plugin-owners"`）。
- 归属口径与 R111 逐卡完全同一：`Message` 内既有的
  `usePluginNames` 名单 + `findPluginToolOwner` 结构
  化比对；名单读不到 / 组内无插件工具 → 不显示。组
  头摘要本体（名称计数）不变。

## 2. 边界

- 只动 Message 组头一处派生与渲染（名单 hook 已在
  作用域，零新增取数）；展开/折叠行为、逐卡后缀
  （R111）、导出与审计串零改动，后端零改动
  （manifest 仍 274）。
- Message.tsx 768 行 + 约 16 行（仍 <800）；下一次
  再动此文件应先抽离（本轮记账提醒）。
- 编排任务树（TaskTreeSection）的事件行也显示裸工具
  名，但属编排域的明细级界面且为他人活跃区，本轮不
  碰；Hook 历史面板同理（低频诊断面）。
- Win7 待对齐（无后端新代码）。

## 3. 测试计划

- Message.pluginOwner 套件增组头三例：多插件组显示
  去重归属（demo、extra 顺序按首现）、名单不可用不
  显示、全内置组不显示；既有逐卡三例与 Message 全
  组回归保持绿。

## 4. 本地证据

- Message 全组 12 文件 62 例通过（pluginOwner 套
  件 6 例含新组头三例，其余套件未 mock 名单、靠
  降级路径保持绿）；定向 PermissionModeSwitch
  11、permissionInsights 5、usePluginNames 4 例
  亦通过。
- tsc 通过；ESLint 0 errors（Message.tsx 2 条
  react-refresh 存量 warnings 仅行号平移）；
  architecture-check 通过（Message.tsx 787 行
  < 800 线）；diff-check、diagnostics(0) 全绿；
  `ipc:manifest:check` 通过（commands 实测
  274），后端零改动。
