# R108 审批弹窗插件归属可见化规格

- 日期：2026-10-26
- 基线：`main` `1d988266005b22a6ea33f87e3c7174826f0c03ce`
- 状态：已合并（PR #2552）
- 编号说明：R108 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R95 起后端 `ApprovalGate` 从桥接已发布记
  录向审批请求注入权威 `plugin_name`，但前端仅在
  用户勾选「记住」展开范围选择时才用到它；主决策
  区（工具行）与审批等待 OS 通知仍只展示裸的
  `plugin__<name>__<tool>` 命名空间名。R101（事后
  规则标注）/R103（插件页提示）/R107（白名单表
  单）已先后补齐各治理面的归属可见性，剩下的盲区
  恰是信任决策本身发生的时刻——用户按下允许/拒
  绝之前，看不见这个工具到底属于哪个插件。

## 1. 目标与语义

- ApprovalDialog 在工具行下方新增「所属插件」横
  幅（`data-testid="permission-plugin-context"`），
  仅当请求携带权威 `plugin_name` 时渲染，样式与
  既有子代理上下文横幅同族——两者回答同一个问
  题：「谁在要权限」。
- 审批等待 OS 通知的 `body` 在 `plugin_name` 存
  在时追加 ` · 插件 <name>` 后缀（排在子任务上下
  文之后）。通知是用户不在窗口前时唯一的决策线
  索，裸命名空间名在该场景最难解读。
- 只渲染后端注入的权威 `plugin_name`，绝不从
  `tool_name` 字符串切分猜名（与 R95/R96 身份边
  界、`PermissionRequest.plugin_name` 字段注释一
  致）。非插件工具的弹窗与通知逐字不变。

## 2. 边界

- 纯前端展示：不新增后端字段/端点/Electron 命
  令（manifest 仍 269），不改应答载荷与审批语
  义，不改「记住」范围/时长逻辑。
- 远程渠道语义不变（R105/R106 同族边界）：
  `RemoteApprovalBridge` 与后端远程审批消息不在
  本轮；本轮只动本地弹窗与其 OS 通知。
- ApprovalDialog 是 i18n 文件，新增文案键
  `permission.from_plugin`（zh 源 + en 镜像）；
  OS 通知标题/正文在该文件内为硬编码中文，后缀
  随宿主惯例硬编码。Win7 按既有口径待对齐（本
  轮无后端新代码）。

## 3. 实现要点

- `src/widgets/permission/ApprovalDialog.tsx`：
  通知 effect 构造 `body` 时按 `plugin_name` 真
  值拼后缀；工具行后在 `pluginName` 存在时渲染
  横幅（文案 `t('permission.from_plugin')` +
  插件名）。既有 `pluginPattern`/记住范围逻辑不
  动。
- `src/shared/lib/i18n/locales/{zh,en}/settingsAndModels.ts`：
  `permission.tool` 后新增 `permission.from_plugin`
  （所属插件 / From plugin）。

## 4. 测试计划

- 组件（ApprovalDialog.test.tsx）：`plugin_name`
  存在 → 横幅可见且含插件名；缺省 → 无横幅（既
  有渲染例保持）。
- 通知（ApprovalDialog.notify.test.tsx）：插件工
  具 → `body` 为「工具名 · 插件 <name>」；插件
  + 子任务 → 子任务段与插件段都有；既有两例逐
  字不变（非插件 `body` 不变）。

## 5. 本地证据

- 前端：ApprovalDialog 新增 2 例（plugin_name 存
  在→横幅含插件名、缺省→无横幅）+ 通知新增 2 例
  （插件后缀、子任务与插件两段叠加；既有非插件例
  逐字不变）；permission 组件 4 文件 34 例与相邻
  回归（permissionState/permissionApi/i18n 含
  en/zh 键一致性）17 文件 60 例通过。
- 通用：tsc、ESLint（改动文件 0 问题）、
  architecture（ApprovalDialog 439 行）、
  diff-check、diagnostics（0）全绿；无新 Electron
  命令（`ipc:manifest:check` 仍 269），后端零改动。
- PR：#2552（2026-10-26 开，CI 结论以 GitHub 为准）。
