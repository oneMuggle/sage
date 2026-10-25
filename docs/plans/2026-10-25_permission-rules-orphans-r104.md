# R104 无归属（missing）孤儿规则整组清理规格

- 日期：2026-10-25
- 基线：`main` `58afc32d329b40371be8c1a6051b555ac4a15d0c`
- 状态：实施完成，PR #2504 待合并
- 编号说明：R104 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：标注驱动的规则管理矩阵已覆盖「按在册插件整组删」
  （R102，含已卸载，插件页就地入口见 R103）与「全清」
  （R100），唯独 R101 徽标标出的 missing 一类（插件形
  状但无生命周期记录）只能逐条删：它们没有在册名字可
  作 R102 选择子（名字不在册 400 是刻意设计）。本轮补
  上这一块，让每类标注都有对应处置。

## 1. 选型记录（本轮评估后搁置的方向）

「仅本次会话记住」（session 级 remember）经取证确认不
适合单轮落地：`PermissionEnforcer.check()` 无 session
参数且规则集合在构造时冻结，构造点分散（旧 agent
`_build_permission_enforcer`、`InprocToolAdapter`、技能
inproc、subagent 与 trust-escalation 包装等）；会话语义
还须定义子代理是否继承、会话结束如何回收、与持久 deny
规则的优先级。属独立多轮安全特性，单独立项，不在本轮
强行缝合。

## 2. 目标

`POST /permissions/rules/delete-orphans`（无请求体）：

- 删除集合由服务端按 R101 同一分类口径选出：标注状态
  为 `missing` 的规则（无生命周期归属 + 插件形状）。
  抽出 `_rule_plugin_status()` 供标注与选集共用，保证
  界面标出的正是会被删掉的。
- 全局插件通配（`plugin__*`）、有归属规则（任何生命
  周期状态）与内置工具规则永不命中。
- 索引不可读 → 503 不写（分不清「无归属」与「读不
  到」时不删，防把在册规则误删成孤儿）。
- `removed=0` 幂等返回 ok 且不写存储；Origin 守卫；
  返回 `{ok, removed, rules（标注）}`，与 R102 同形。
- Electron `permissions_delete_orphan_rules` +
  `permissionApi.deleteOrphanRules()`。
- 规则管理器在 missing 计数 >0 时显示「无归属插件
  规则 · N」行，confirmDialog（danger）确认后调用；
  失败保留列表并显失败文案（沿用 R102 模式）。

## 3. 边界

- 不接受任何客户端选择子（pattern/名字/状态筛选）：
  无请求体，语义只有「全部 missing」一种，防长成条件
  删除面（R100 纪律）。
- 不动求值（enforcer）、存储结构（仍仅
  `(tool_pattern, decision)`）与既有端点行为；标注重
  构只抽函数、不变输出。
- 不做 uninstall 联动删除（R101 结论不变）；missing
  产生路径（旧版本数据、记录缺失等）不在本轮修复范围。
- Win7 分支按既有口径待对齐（新端点/命令/py38 语法在
  本轮保持兼容写法）。

## 4. 测试计划

- 后端新文件：仅删 missing（在册/已卸载/全局通配/内
  置工具全保留）；长名字消歧下不误伤；空索引时插件
  形全清但全局通配保留；removed=0 不写；索引 503
  不写；恶意 Origin 403。
- 前端：管理器孤儿行显隐/确认删除/取消不调/失败显
  错保列表；permissionApi 透传与错误传播。
- 通用：相邻后端套件回归（routes/status/by-plugin）、
  Ruff 全库、py38、ipc-manifest、tsc、ESLint、
  architecture、silent-exceptions、diff-check、
  diagnostics 0。

## 5. 本地证据（2026-10-25）

- 后端：新契约 6 例 + by-plugin 7 例 + plugin-status
  与 routes 相邻套件共 63 例通过；Ruff 全库、py38
  （0 violations）、silent-exceptions 全绿。
- 前端/Electron：定向 58 例通过（管理器孤儿行 3 例 +
  permissionApi 2 例新增）；ipc-manifest 266
  commands；tsc、ESLint 改动文件、architecture、
  diff-check、diagnostics（0）全绿。
