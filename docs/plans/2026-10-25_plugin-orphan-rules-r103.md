# R103 已卸载插件孤儿规则就地提示与清理规格

- 日期：2026-10-25
- 基线：`main` `3e89943ae1e8e8b99e09d904d02a9779f624204b`
- 状态：实施完成，PR #2500 待合并
- 编号说明：R103 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R101（#2484）让孤儿规则在通用设置页带徽标可见，
  R102（#2493）给出按插件整组删除。但孤儿规则是在插件
  页点「卸载」那一刻产生的：用户当时不知道还有规则残留，
  事后在插件页看到「已卸载」卡片也无从知道它名下仍有
  几条已记住规则。本轮把同一信息送到产生孤儿的地方。

## 1. 目标

插件页做三件事（纯前端，复用既有 API）：

1. 刷新时顺带 best-effort 拉取规则列表（R101 标注），按
   `plugin_name` 汇总计数；拉取失败静默降级（不显计数、
   不影响插件页其它功能）。
2. 已卸载且名下仍有规则的插件卡片显示「卸载后仍保留的
   已记住规则 · N」提示与「删除其全部规则」按钮；
   confirmDialog（danger）确认后调用既有
   `permissionApi.deleteRulesByPlugin`（R102），成功后
   刷新计数并给出 notice，失败走既有 actionError 通路。
3. 卸载动作完成后计数一并刷新，提示当场出现，不必等
   用户下次打开页面。

## 2. 边界

- **不做自动删除**：卸载仍保持软删除可 restore 的语义，
  删规则永远是用户在卡片上的又一次显式点击（R101 结论
  不变）。
- **只覆盖已卸载卡片**：在册插件的规则在通用设置页管理
  （R102 归属行），插件页不重复提供全量规则管理；
  missing 孤儿没有插件卡片，仍回通用设置页处理。
- **零新后端面**：不新增端点、字段或 Electron 命令；
  计数全部由前端用 R101 标注本地汇总。
- 不改 pluginClient、permissionApi 的既有签名。
- Win7 分支不涉及（本轮无后端差异；总账口径仍以各轮
  win7 列为准）。

## 3. 实现要点

- `PluginsTab.refresh()` 的 Promise.all 增加
  `permissionApi.listRules().catch(() => [])`，结果
  汇总为 `ruleCounts: Record<string, number>` 存 state。
- 卡片 `<dl>` 之后、操作行之前插入孤儿提示块
  （testid `plugin-orphan-rules-<name>` /
  `plugin-delete-rules-<name>`）；忙碌态用独立
  `rulesBusyName` 并与卡片既有 `busy` 合并禁用。
- 文案进 PluginsTab 既有的本地 `copy`（zh/en 三元），
  不新增全局 i18n 键；名字/计数代码拼接。

## 4. 测试计划

- PluginsTab：已卸载插件带计数提示、在册插件不提示；
  确认后调 deleteRulesByPlugin 且提示消失；取消不调；
  删除失败现 actionError 且提示仍在；listRules 失败时
  页面照常渲染且无提示。
- 通用：vitest 定向（PluginsTab/permissionApi/
  GeneralTab 相邻）、tsc、ESLint 改动文件、
  architecture、diff-check、diagnostics 0。

## 5. 本地证据（2026-10-25）

- 前端定向：PluginsTab（新增 5 例：计数提示仅限已卸载、
  确认删除并消失、取消不删、失败显错保提示、计数拉取
  失败降级）+ permissionApi + GeneralTab 共 53 例通过。
- tsc、ESLint 改动文件、architecture、diff-check、
  diagnostics（0）全绿。提示与删除逻辑抽为同目录
  `PluginOrphanRules` 组件；PluginsTab 自 800 行门槛
  仅 +21 行（计数在 refresh 汇总），登记 baseline 820
  后续只降不升。
