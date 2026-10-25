# R102 按插件删除其全部已保存规则规格

- 日期：2026-10-25
- 基线：`main` `556cf0858b0f2e01b5f69b8515ea098abf9b00f5`
- 状态：PR #2493 待合并
- 编号说明：R102 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R101（#2484）给规则列表加上只读插件归属标注，
  孤儿规则已经看得见；但清掉一个已卸载插件的全部残留
  规则仍要逐条点删（或全清）。本轮补「按插件撤销其
  全部持久信任」，与逐条删除（R99）、全量清空（R100）
  构成三档撤销粒度。

## 1. 目标

1. 新增 `POST /permissions/rules/delete-by-plugin`：
   以权威插件名为唯一选择子，删除该插件名下的全部已
   保存规则，返回 `{ok, removed, rules（带标注）}`。
2. 设置页按归属汇总出「删除插件 X 的全部规则（N）」
   操作，先经 confirmDialog（danger）确认。
3. 选择集合与 R101 标注同源：复用同一归属判定
   （含 `a` / `a__b` 长名字消歧），保证「徽标标给谁，
   就只删谁的」。

## 2. 安全合同

- 选择子是**插件身份不是 pattern**：客户端只传
  `plugin_name`；服务端要求它命中生命周期记录（任意
  状态，已卸载正是主场景），否则 400 不写。索引不可
  读时 503 不写——校验不了身份就不做写操作。
- 删除集合由服务端按结构化归属选出，只可能删掉该
  插件的现存规则；永不新建、永不改写、永不波及其它
  插件或内置工具规则。这与 R100「清空端点不接受条件
  删除参数」的区别在于：这里的条件是已注册身份，条件
  求值完全在服务端，客户端没有 pattern 表达能力。
- 与逐条删除/清空共用 Origin 守卫；`extra="forbid"`。
- 幂等：该插件无规则时 `removed=0` 返回 ok（信任已
  撤销的状态达成）；`removed=0` 时不写存储。

## 3. 非目标

- 按 decision/pattern 任意条件删除；多选/跨插件批量。
- 「无记录」（missing）孤儿按组删除——没有权威名字
  可作选择子，仍逐条删除或全清。
- 插件卸载联动自动删除（R101 已论证 restore 语义）。
- 求值、存储格式、remember/逐条删除/全清的任何改动。
- Win7 分支同步（继续标待对齐）。

## 4. 设计

### 4.1 后端

- 从 R101 标注中抽出 `_rule_plugin_owner(pattern,
  index)` 共用判定，标注与删除选集同源。
- 端点读取索引（None → 503）→ 名字不在索引 → 400 →
  `_load_saved_rules()` 纯口径过滤 → 有删除才写回纯
  规则 → 响应经标注层输出并带 `removed` 计数，日志
  记录插件名与条数。

### 4.2 Electron / 前端

- 新命令 `permissions_delete_rules_by_plugin`
  （body `{plugin_name}`），重生成 ipc-manifest。
- `permissionApi.deleteRulesByPlugin(pluginName)`。
- 规则管理器从当前列表的 `plugin_name` 汇总出归属项
  （含计数与状态），在列表后逐项渲染删除按钮；文案
  由静态 i18n 片段与名字/计数在代码里拼接（`t()` 无
  插值）。操作中禁用其它删除/清空，失败显示专用文案
  且保留列表。

## 5. 测试计划

- 后端（新文件
  `test_permission_rules_delete_by_plugin.py`）：
  只删目标插件（通配 + 精确）、别家与内置不动；
  `a`/`a__b` 消歧不误删；未知插件 400 不写；索引
  不可用 503 不写；零规则幂等 ok 且不改存储；evil
  Origin 403；额外字段 422；写回纯净与响应标注。
- 前端：`permissionApi` invoke 形态；GeneralTab 归属
  项出现与计数、确认后删除并采用新列表、取消不发
  请求、失败保留列表。
- 通用：ipc-manifest check、tsc、ESLint、Ruff 全库、
  真实 Py3.8 与 py38 compat、architecture、
  silent-exceptions、diff-check、diagnostics 0。

### 5.1 本地验证记录（2026-10-25）

- 后端新文件 7 例 + 既有规则三文件 50 例、相邻回归
  95 例通过（含 a/a__b 消歧、未知插件 400、索引不可用
  503、零规则幂等不写、evil Origin 403、额外字段 422）。
- 前端定向 43 例（permissionApi、GeneralTab 按插件
  删除三态、i18n zh/en 新键）；tsc（src 与 Electron）
  与 ESLint 改动文件 0 errors。
- ipc-manifest 已重生成并 check 通过（265 commands）；
  Ruff 全库 `backend/` 通过；真实 Python 3.8 编译与
  py38 compat（0 violations）、architecture、
  silent-exceptions、diff-check 通过；diagnostics 0。
