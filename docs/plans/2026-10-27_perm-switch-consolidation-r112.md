# R112 PermissionModeSwitch 供数与导出收口规格

- 日期：2026-10-27
- 基线：`main` `db622f684bdb090c2ac80875cc36183dc05a8418`
- 状态：已开 PR（#2585），待合并
- 编号说明：R112 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R111 新增了共享名单缓存 hook `usePluginNames`，
  而 R110 给聊天顶栏弹层写的还是组件内自取一份名单
  （`auditOpen` 时 `pluginClient.list()` + 本地 state）。
  两处「生命周期名单 → 名字数组」的实现并存会漂移，且
  弹层每次打开都等一次新取数才出归属后缀。本轮把弹层收
  口到同一供数，并顺手把同文件的两个纯函数导出按 R110
  先例下沉共享层。属整合轮，无新功能面。

## 1. 目标与语义

- `PermissionModeSwitch` 改用
  `usePluginNames(auditOpen)`：删本地取数 effect 与
  `pluginNames` state、删 `pluginClient` 直连。审计插件
  归属与转录（R111）自此同源同缓存——转录已预热时弹层
  打开即出后缀，且两面同开只发一次 list()。
- 语义微差（接受并写明）：R110 是「每次打开弹层新取一
  次」；收口后遵循 hook 的 60s TTL，与 R111 转录口径一
  致；名单读不到返回 null 整体不标，与 R110 失败降级
  完全相同。归属判定仍为 `findPluginToolOwner`，标注
  文案/testid 不变。
- `formatPermissionModeMarkdown/Json` 与其时间小帮手
  自组件文件下沉到 `src/shared/lib/permissionInsights.ts`
  （函数体原样，时间帮手以
  `formatPermissionAuditTime` 名导出供组件渲染复用）；
  组件与测试改从共享层导入。导出内容逐字不变。附带效
  果：该文件 2 条存量 react-refresh/only-export-
  components warnings 清零。

## 2. 边界

- 只动上述一个组件的供数与导出位置：审计/会话规则的取
  数节奏（30s 轮询、流结束跳变）、遮蔽标注、导出格式
  与后端/Electron 零改动（manifest 仍 274）。
- 不动 EditAgentForm 的名单取数：它要完整 records 做
  R107 三分类且跟随显式刷新周期，names-only 的 TTL
  缓存不适用，取证后确认保留自取。
- Message.tsx 的同类 format 导出本轮不下沉（热文件、
  无现成共享归属），避免为清 warnings 扩散范围。
- Win7 待对齐（无后端新代码）。

## 3. 测试计划

- PermissionModeSwitch 套件的 pluginClient mock 换为
  对 `usePluginNames` 模块的 mock（归属到达/读不到两
  分支以 hook 返回值驱动；取数次数与失败回 null 的契
  约由 hook 自有套件守护）；format 三例仅改导入源。
- 相邻回归：permissionInsights、usePluginNames、
  Message.pluginOwner 套件保持绿。

## 4. 本地证据

- 定向与相邻回归共 6 文件 60 例通过（Permission-
  ModeSwitch 11、permissionInsights 5、
  usePluginNames 4、Message.pluginOwner 3、
  PermissionRulesManager.shadowed + GeneralTab
  37）；导入修复后核心两套件复测 16 例通过。
- tsc 通过；ESLint 对改动文件 0 errors 0 warnings
  （PermissionModeSwitch.tsx 的 2 条存量 react-
  refresh warnings 随下沉清零，该文件 450 → 393
  行）；architecture-check 通过；diff-check、
  diagnostics(0) 全绿；`ipc:manifest:check` 通过
  （commands 实测 274），后端零改动。
