# R115 Hook 执行历史插件归属规格

- 日期：2026-10-28
- 基线：`main` `761fd8f42c301b3aaf6553b1a889a88e902a9e96`
- 状态：已合并（PR #2618）
- 编号说明：R115 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R113 的展示面扫描里，设置页 Hook 执行历史是除
  载荷镜像（EventTimeline）与远程渠道（边界外）之外
  最后一个拼裸工具名的策展界面——行内
  `{hook_id} → {tool_name}` 认不出插件工具的出处（排
  查「哪个插件的工具总被 hook 拦」时要靠人脑拆名字）。
  本轮按同一名单派生补齐，归属可见化弧就此覆盖全部策
  展展示面。

## 1. 目标与语义

- 历史行工具名后追加「（所属插件: <name>）」（与
  R111/R113/R114 同一名单派生：`usePluginNames` +
  `findPluginToolOwner`；读不到/非插件工具/通配
  `*` 行不加）。
- 供数门控：仅当已加载记录里存在带工具名的行时启
  用；空历史不取数。后缀文案跟随本文件硬编码中文
  （未接 i18n，与 R114 先例一致）。

## 2. 边界

- 只动 HookHistoryPanel 的行内拼装与供数：历史端
  点/记录形状/清空行为不变，后端零改动（manifest
  284，本轮未涉）；EventTimeline 的通用载荷镜像与远程渠
  道维持边界外。
- Win7 待对齐（无后端新代码）。

## 3. 测试计划

- 新 HookHistoryPanel.pluginOwner 套件（mock
  backendRequest + usePluginNames）：插件工具行命
  中显示、内置行不带、名单不可用整体不加；既有
  HookHistoryPanel 四例保持绿（真实 hook 失败降
  级路径）。

## 4. 本地证据

- 定向与相邻回归共 11 文件 59 例通过（新
  pluginOwner 2、既有 HookHistoryPanel 4 与
  settings 其余 Hook 相关套件、usePluginNames、
  permissionInsights）。
- tsc 通过；ESLint 改动文件 0 errors 0
  warnings；architecture-check 通过；
  diff-check、diagnostics(0) 全绿；
  `ipc:manifest:check` 通过（commands 实测 284
  ——基线已被他人推进，本轮未动后端/Electron）。
