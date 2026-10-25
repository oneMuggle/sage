# R101 已保存权限规则插件归属标注规格

- 日期：2026-10-24
- 基线：`main` `3d0b6a3a7e7d68e61156d686842f4c090a0b2d43`
- 状态：PR #2484 待合并
- 编号说明：R101 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R97（#2418）给出已保存规则的查看与逐条删除，
  R99（#2452）删除改按内容定位，R100（#2474）补一键
  清空。但规则列表只展示原始 `tool_pattern`：插件被
  卸载后其 `plugin__<name>__*` 规则仍在列表里，用户
  无从分辨哪条是「孤儿规则」。本轮只补只读归属标注，
  让插件已卸载/无记录的规则在管理界面可见可辨。

## 1. 问题陈述

- 插件卸载是软删除（status=uninstalled，记录保留且可
  restore，同名插件在记录存在时不能全新安装），因此
  「卸载时自动删规则」会破坏 restore 的合理预期，本轮
  明确不做。
- 但「什么都不做」时，设置页规则列表里混着已卸载插件
  的持久信任，用户逐条比对插件列表才能清理。最后一块
  缺口是**可见性**，不是写能力。

## 2. 目标

1. 规则列表响应为每条规则附带服务端派生的插件归属：
   `plugin_name`（权威归属，无归属为 null）与
   `plugin_status`（生命周期状态，或 `missing`/`all`，
   无归属为 null）。
2. 设置页规则行对 `plugin_status === "uninstalled"`
   显示「插件已卸载」徽标、`"missing"` 显示「插件
   无记录」徽标；其余状态不打扰。
3. 标注是纯只读派生：不写存储、不改变求值、不新增
   任何写端点或筛选参数。

## 3. 非目标

- 插件卸载/恢复联动增删规则。
- 按插件筛选、分组或批量删除规则。
- 规则求值时跳过已卸载插件的规则（求值层不引入
  插件注册表依赖）。
- 改存储格式；归属字段永不落盘。
- Win7 分支同步（继续标待对齐）。

## 4. 合同

### 4.1 后端归属派生（`backend/api/permission_routes.py`）

- `_load_saved_rules()` 保持纯存储口径不变（删除端点
  依赖其 dict 等值与原样写回）。新增标注层只作用于
  **响应视图**：`GET /rules` 与删除成功返回的最新列表
  经标注层输出；清空恒返回空列表，不受影响。
- 插件状态索引：进程内按请求构造
  `PluginLifecycleManager`（与 plugin_routes 同口径，
  不缓存连接），`list_plugins()` 全状态 →
  `{name: status}`。任何失败记 warning 并降级为空
  索引（标注全 null，列表本身永不失败）。
- 归属判定只用权威名单 + 结构化 helper，**不按工具名
  切分猜插件名**：pattern 等于
  `plugin_tool_wildcard_for_plugin(name)` 或
  `plugin_tool_belongs_to_plugin(pattern, name)` 时
  归属该插件。候选按名字长度降序尝试，消除
  `a` 与 `a__b` 两插件共存时的命名空间歧义。
- 无记录命中时只判形状：`plugin__*`（全局插件通配）
  → `plugin_status: "all"`；`is_plugin_tool_reference`
  为真 → `"missing"`（`plugin_name` 恒 null —— 无权威
  记录就不报名字）；其余内置工具 → 两者 null。

### 4.2 前端（类型透传 + 徽标）

- `PermissionRuleItem` 增加 `plugin_name` /
  `plugin_status`（`string | null`）；`parseRuleItems`
  宽容解析：非 string 一律 null。Electron 命令为透传，
  不新增命令、不改 ipc-manifest。
- `PermissionRulesManager` 规则行在决定文案后渲染
  徽标：`uninstalled` → i18n `plugin_uninstalled`；
  `missing` → `plugin_missing`，
  testid `permission-rule-plugin-status-<index>`。
- 删除传参不变：仍只发 `{toolPattern, decision}`，
  标注字段不进入任何请求体。

## 5. 失败与回滚

- 生命周期 DB 不可用 → 标注降级为 null，列表/删除/
  清空行为与 R100 完全一致。
- 整体回滚 = 还原两个响应视图与前端徽标；存储与求值
  无任何累积状态需要迁移。

## 6. 测试计划

- 后端（新文件 `test_permission_rule_plugin_status.py`，
  避开已冻结 831 行的 `test_permission_routes.py`）：
  通配规则归属已卸载插件、精确工具规则归属已启用插件、
  插件形状无记录 → missing、全局通配 → all、内置工具
  → null、删除后响应带标注且写回存储不含标注字段、
  索引失败降级全 null。
- 前端：`permissionApi` 解析透传标注与坏类型归 null；
  GeneralTab 规则行徽标显示（uninstalled/missing）与
  常规规则不显示。
- 通用：tsc、ESLint（改动文件）、Ruff、真实 Py3.8、
  py38 compat、architecture、silent-exceptions、
  diff-check、diagnostics 0。

### 6.1 本地验证记录（2026-10-25）

- 后端新文件 5 例 + `test_permission_routes` 45 例
  通过（存量 3 处响应等值断言按新字段等值更新，行数
  不变、831 baseline 未动）；相邻回归 95 例
  （enforcer/question/telegram/plugin_routes）。
- 前端定向 38 例（permissionApi 解析透传与坏类型归
  null、GeneralTab 徽标、i18n zh/en 新键）；tsc
  （src 与 Electron）与 ESLint 改动文件 0 errors。
- Ruff 全库 `backend/` 通过（SIM108 已按其建议收束）；
  真实 Python 3.8 编译与 py38 compat（0 violations）、
  architecture、silent-exceptions、diff-check 通过；
  diagnostics 0。
