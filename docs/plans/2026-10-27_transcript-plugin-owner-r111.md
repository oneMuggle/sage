# R111 聊天历史工具调用插件归属标注规格

- 日期：2026-10-27
- 基线：`main` `688559415cca57e1a8b33e8cbed508caf5671807`
- 状态：已合并（PR #2576）
- 编号说明：R111 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：归属可见化弧已覆盖规则（R101）、白名单
  （R107）、审批时刻（R108）与顶栏审计（R110），唯
  独聊天历史本身还没标：转录里的工具调用卡片对插件
  工具只显示人性化标题与弱化的裸名
  `plugin__<name>__<tool>`，回看历史（尤其是排查
  「这步是谁干的」）时认不出工具属于哪个插件。

## 1. 目标与语义

- 通用工具调用卡片（插件工具恒走此路径，专用渲染器
  只有内置工具）的标题行在裸名后追加弱化后缀
  「所属插件: <name>」（复用 R108 文案键
  `permission.from_plugin`，
  `data-testid="tool-call-plugin-owner-<index>"`）。
- 归属口径与 R110 审计完全同一：生命周期名单的权
  威名长名优先结构化比对
  （`permissionInsights.findPluginToolOwner`），
  绝不切分工具名猜名；名单读不到 / 非插件形 → 不标。
- 名单经新共享 hook `usePluginNames(enabled)` 供数：
  模块级缓存 + 在途合并，多个 Message 实例只触发
  一次取数；TTL 60s 后台刷新、内容未变不换引用
  （避免全体已渲染消息无谓重渲染）；仅当消息带工具
  调用时才启用（纯文本消息不取数）。

## 2. 边界

- 热路径纪律：`Message` 是 memo 化重组件，新增
  hook 只在组件顶层调用一次；归属到达至多引发一
  次性补标重渲染（内容 chunks 已 memo），不进流
  式 delta 循环；不改 memo 比较函数。
- 只动通用卡片标题行：专用渲染器、工具组折叠汇
  总、结果区与导出/审计串（formatMessageAudit*）
  零改动；后端与 Electron 零改动（manifest 仍
  274），转录存储形状不变（渲染期结合）。
- 陈旧性如实：缓存 TTL 内新装/卸载插件的归属可
  能短暂滞后（至多多标/少标一个弱化后缀），属展
  示层可接受；Win7 待对齐（无后端新代码）。

## 3. 实现要点

- 新 `src/shared/lib/hooks/usePluginNames.ts`：
  模块级 `{names, fetchedAt, inFlight}` 缓存；
  `pluginClient.list()` 失败回 null 不毒化缓存
  （下次 enabled 挂载可重试）。
- `src/widgets/chat/Message.tsx`：`toolCalls` 归一
  化后 `usePluginNames(toolCalls.length > 0)`；通用
  卡片 map 内预计算每条 owner，标题行条件渲染后
  缀。文件 754 行 + 约 14 行，仍在 800 线内。

## 4. 测试计划

- hook（resetModules 隔离缓存）：enabled=false 不
  取数；成功返回名单名；失败返回 null；双实例同
  挂载只发一次 list（在途合并）；TTL 内复用缓存。
- 组件（新 Message.pluginOwner 套件）：插件工具
  调用渲染出归属后缀；名单失败/内置工具不渲染；
  既有 Message 套件在未 mock pluginClient 时靠降
  级路径保持绿。

## 5. 本地证据

- 定向与相邻回归共 14 个文件 74 例通过：新 hook
  套件 4 例、Message.pluginOwner 3 例、Message
  既有全组（未 mock pluginClient，证明名单读失败
  的降级路径不影响既有渲染）、permissionInsights
  与 PermissionModeSwitch。
- tsc 通过；ESLint 0 errors（Message.tsx 2 条
  react-refresh warnings 为存量审计导出所致，仅
  行号随 +14 行平移）；architecture-check 通过
  （Message.tsx 768 行 < 800 线）；diff-check、
  diagnostics(0) 全绿；`ipc:manifest:check` 通过
  （commands 实测 274），后端零改动。
