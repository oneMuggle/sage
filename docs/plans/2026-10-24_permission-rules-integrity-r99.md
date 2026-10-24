# R99 已保存权限规则写入完整性规格

- 日期：2026-10-24
- 基线：`main` `905bb49638a555668f64740290dd91c9bf378107`
- 状态：PR #2452 待 CI 与合并
- 编号说明：R99 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R95（#2412）让审批 remember 按工具或整插件把
  决定追加为 `settings.permission_rules` 规则；
  R97（#2418）补上已保存规则的查看与按下标逐条删除；
  R98（#2440）完成 profile 白名单结构化身份匹配。
  本轮只收口这条存储的两个写入卫生问题，不改规则
  本体的生成方式与求值口径。

## 1. 背景与问题

两个问题都出在 `permission_routes.py` 的规则列表写入：

1. **remember 无条件追加**：`_persist_remembered_rule`
   解析现有规则后直接 `append` 新条目，不查重复。
   同一工具被多次「记住我的选择」会攒下多条完全相同
   的 `(tool_pattern, decision)`。求值不受影响（重复
   条目等价），但列表只长不收，设置页里要逐条删。
2. **删除按下标定位**：R97 的删除体是 GET 列表下标。
   设置页打开后，若别处的审批 remember 追加了新规则，
   下标随之漂移：用户点击删除的那一行，已不是服务端
   同一位置的规则，最坏删掉另一条（甚至想保留的一条
   `deny` 保护），且删除后界面直接采用服务端新列表，
   用户不易察觉删错。R97 规格已把该窗口记录为已接受
   取舍（误删后果偏 fail-safe）；本轮把它消除。

## 2. 目标

1. remember 追加前去重：已存在完全相同的
   `(tool_pattern, decision)` 时不再重复落规则。
2. 删除改按内容定位：删除体传目标规则的
   `tool_pattern` 与 `decision`，服务端删除第一条
   完全匹配的生效规则；无匹配返回 400 且不写存储。
3. Electron 命令与设置页同步切到按内容删除；
   `permissionApi.deleteRule` 改为传规则对象。
4. 求值（deny > allow > ask）、存储格式、Origin 守卫、
   审批弹窗与远程网关全部不变。

## 3. 合同

- 去重只跳过「完全相同」的新条目；同一 pattern 下
  decision 不同照常追加——并存的 allow/deny 仍由
  既有求值优先级裁决，本轮不借去重做冲突合并，
  也不让后一次 remember 静默推翻先前落定的规则。
- 去重命中时只记 info、不写存储（连带不触发写回
  规范化）；当次审批应答语义不变。存量重复规则不
  自动清理，仍可在设置页逐条删。
- 删除请求体为 `{tool_pattern, decision}`，
  `extra="forbid"`；旧下标体 `{index}` 不再被接受
  （422）。桌面端前端/Electron/后端同版本打包，
  本地端点无外部客户端兼容面。
- 删除时服务端以 `parse_rules` 口径重读生效列表，
  删第一条等值匹配，写回规范化列表并返回最新列表；
  无等值匹配 → 400 `{ok: false, error: "rule not
  found"}` 且不写。存量重复规则逐条删的语义保持：
  每次删除恰好移除一条。
- 删除体中的 pattern 只是「撤销哪一条」的选择子：
  永远只能删掉存储里已存在且完全一致的一条，无法
  创建、改写或放宽任何规则——这与「规则本体只能
  由审批 remember 或服务端派生生成」的边界不冲突；
  其权限与旧下标删除同级，但比下标更精确。
- UI 不出现任何 pattern 输入面：设置页只把服务端
  列表行自带的 `tool_pattern`/`decision` 原样回传。
  行级 `data-testid` 与禁用态仍按渲染下标（DOM
  身份不变），删错规则的风险由服务端内容定位消除。

## 4. 实现落点

- `backend/api/permission_routes.py`：
  `PermissionRuleDeleteBody` 改内容字段、删除端点
  改等值匹配删除、`_persist_remembered_rule` 追加
  前去重。
- `electron/commandRoutes/settings.ts`：
  `permissions_delete_rule` 的 body 改透传
  `{tool_pattern, decision}`。
- `src/shared/api/permissionApi.ts`：`deleteRule`
  签名改传 `PermissionRuleItem`。
- `src/pages/settings/PermissionRulesManager.tsx`：
  删除处理改传行规则对象。
- 测试：`backend/tests/api/test_permission_routes.py`、
  `src/shared/api/__tests__/permissionApi.test.ts`、
  `src/pages/settings/__tests__/GeneralTab.test.tsx`。
- 文档：technical 97 号当前契约、本总账；user-manual
  21 号无下标细节，不改。

## 5. 非目标

- 不做规则新建/编辑/排序/批量清空/分组/搜索；
- 不做冲突规则合并、求值优先级或存储格式改动；
- 不自动清理存量重复或无效条目之外的任何存量规则
  （无数据迁移）；
- 不给远程网关（Telegram 等低信任渠道）增加
  remember 或规则管理能力；
- 不做 Win7 同步（继续标待对齐）。

## 6. 验证计划

- 后端定向：`test_permission_routes.py` 全过；新增/
  改写用例覆盖 remember 同条去重（含整插件范围）、
  不同 decision 不去重、按内容删一条重复规则、
  列表追加后仍删中目标、无匹配 400 不写、旧下标体
  422、额外字段 422、evil Origin 403 保持。
- 相邻回归：权限 enforcer 与审批路由相邻测试不回归。
- 前端定向：`permissionApi.test.ts` 与
  `GeneralTab.test.tsx` 覆盖新删除参数与列表回填。
- 通用：tsc（src 与 Electron）、ESLint（改动文件）、
  Ruff、py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 0 项。

### 6.1 本地验证记录（2026-10-24）

- 后端定向 42 例通过（`test_permission_routes`，
  含同条/整插件 remember 去重、不同 decision 不去重、
  按内容删一条重复规则、位置无关删除、无匹配 400
  不写、旧下标体 422、额外字段 422、evil Origin
  403）；相邻回归 83 例通过
  （`test_permissions_enforcer`、
  `test_question_routes`、`test_telegram_approvals`）。
- 前端定向 28 例通过（`permissionApi.test`、
  `permissionApi.p145`、`GeneralTab`）；tsc（src 与
  Electron）通过，ESLint 改动文件 0 errors。
- Ruff、py38 compat（0 violations）与真实
  Python 3.8 对 2 个改动 Python 文件编译、
  architecture、silent-exceptions、diff-check
  通过；diagnostics 0。

## 7. 影响与回滚

- 影响只限规则列表的写入方式：新 remember 不再制造
  完全重复条目；删除永远删中界面上选中的那条规则。
  既有规则、求值与审批行为不变。
- 存储格式不变、无迁移；存量重复规则原样保留，
  逐条删不受影响。
- 回滚只需还原删除端点请求体、三处前端/Electron
  传参与去重分支；已写规则数据不丢失。
