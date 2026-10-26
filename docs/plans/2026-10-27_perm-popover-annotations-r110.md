# R110 聊天顶栏权限弹层标注补齐规格

- 日期：2026-10-27
- 基线：`main` `7412a5c6633430a4fe88fed3263bc79c3230db9e`
- 状态：已开 PR（#2566），待合并
- 编号说明：R110 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：权限 UX 各列表的归属/生效性标注已逐面落地
  （规则 R101、弹窗 R108、遮蔽 R109），只剩聊天顶栏
  徽记弹层（`PermissionModeSwitch`）里的两张表还未
  标：自动放行审计逐条只显示裸 `plugin__…` 工具名
  （「未经我确认放行了什么」恰恰最该能认出来）；会话
  规则（R106）同样按 deny > allow > ask 合并裁决，
  会话内先整插件拒、后单工具放（或反之）就会造出恒
  不生效的行，现象与 R109 修的完全同构。

## 1. 目标与语义

- **审计归属**：弹层打开时取一次生命周期名单
  （`pluginClient.list()`），逐条审计记录用权威名结
  构化归属（长名优先、命名空间比对，镜像后端
  belonging 与 R107 前端口径，绝不切分工具名猜
  名）出所属插件，后缀展示「所属插件: <name>」
  （复用 R108 文案键 `permission.from_plugin`）。
  名单读不到 → 整体不标（与 R107 降级一致）；非插
  件形工具不标。
- **会话规则遮蔽**：会话规则列表内复用 R109 的
  `findShadowedRules` 派生，被同列表更高优先级规
  则覆盖的行显示「被遮蔽」徽标（复用 R106 已先例
  的 `settings.permission.rules.*` 文案键）。
  语义与 R109 相同：所示恒真。持久规则也能遮蔽会
  话行（如持久整插件 deny），但那种组合经 UI 几
  乎不可达（持久 deny 命中时压根不弹审批、造不出
  会话 allow）；本轮只判同列表是诚实子集。
- 派生下沉共享：`findShadowedRules` 从
  `PermissionRulesManager` 移入新
  `src/shared/lib/permissionInsights.ts`（顺带新
  `findPluginToolOwner`），两侧同源，避免
  pages→widgets 反向依赖与逻辑复制。

## 2. 边界

- 纯展示零语义：不改审计台账记录格式与后端任
  何接口；**导出格式不动**（Markdown/JSON 导出沿
  R106 口径逐字不变——归属只是渲染期结合，不进
  `AutoApprovalRecord` 类型与导出串）。
- 取数面收敛：名单只在弹层打开时取（不进 30s 轮
  询/流结束刷新节奏），失败静默降级；徽记计数、
  会话规则增删与导出行为零改动。
- 身份边界不变：归属只用生命周期名单的权威名做
  结构化比对。无新端点/Electron 命令（manifest
  仍 274）。Win7 待对齐（无后端新代码）。

## 3. 实现要点

- 新 `src/shared/lib/permissionInsights.ts`：
  `findShadowedRules`（自 Manager 原样移入）+
  `findPluginToolOwner(toolName, pluginNames|null)`
  （形状判定与长名优先归属，镜像后端
  `tool_names.py` 口径，与 R107 同源纪律）。
- `PermissionRulesManager` 改为从共享模块导入
  （导出面收缩，测试改导入路径，行为不变）。
- `PermissionModeSwitch`：`auditOpen` 时取名单入
  state；审计行在 owner 非空时渲染后缀
  （`data-testid="auto-approval-plugin-<seq>"`）；
  会话规则行渲染遮蔽徽标
  （`data-testid="session-rule-shadowed-<index>"`）。

## 4. 测试计划

- 共享纯函数：owner 的长名优先（`a` 与 `a__b` 共
  存）、非插件形/通配形不归属、名单 null 降级、
  无匹配返回 null；遮蔽沿 R109 既有例迁移。
- 组件（PermissionModeSwitch 既有套件扩展，
  pluginClient 默认 mock 空名单保证旧例不变）：
  审计行显示归属后缀；名单为空/失败时不显示；
  会话规则冲突对子出现遮蔽徽标；Manager 既有回
  归（GeneralTab + shadowed 套件）保持绿。

## 5. 本地证据

- 前端：共享纯函数新增 owner 5 例（长名优先/形
  状与通配不归属/无名单与无匹配降级）；widget 新
  增 3 例（审计归属后缀、名单失败不标、会话规则
  遮蔽徽标）；定向与回归（PermissionModeSwitch
  既有 8、Manager 遮蔽 8、GeneralTab 29）与相邻
  （permissionApi/permissionState/ApprovalDialog）
  共 120 例通过。
- 通用：tsc、ESLint（0 errors；PermissionModeSwitch
  存量 2 条 react-refresh warnings 与 main 一致、
  非本轮引入）、architecture（450/290 行，共享模
  块 83 行新文件）、diff-check、diagnostics（0）
  全绿；manifest 仍 274，后端零改动。
- PR：#2566（2026-10-27 开，CI 结论以 GitHub 为准）。
