# R100 已保存权限规则一键清空规格

- 日期：2026-10-24
- 基线：`main` `b2ba86e312345d854fb2a35760fc4d6388a0ea9a`
- 状态：PR #2474 待合并
- 编号说明：R100 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R97（#2418）给出已保存规则的查看与逐条删除，但把
  「批量清空」明列为非目标；R99（#2452）完成 remember
  去重与删除按内容定位。本轮补最后一块撤销能力：
  一键撤销全部持久信任。

## 1. 背景与问题

用户改主意想「全部恢复逐次询问」时，目前只能在设置页
逐条点删；规则多（或历史攒下许多条目）时这是纯摩擦。
清空是 fail-safe 方向的操作——删掉的后果仅是所有工具
恢复逐次审批，不会放宽任何信任——但仍属破坏性写操作：
误点会把长期积累的信任决定一次性丢掉，需要一道明确
确认。R97 当轮为控范围未做，本轮单独收口。

## 2. 目标

1. 后端新增 `POST /permissions/rules/clear`：带 Origin
   守卫，把 `settings.permission_rules` 写为空列表并
   返回 `{ok: true, rules: []}`；调用前先数当前生效
   条数并记入日志。
2. Electron 新增 `permissions_clear_rules` 命令并重生成
   ipc-manifest；`permissionApi.clearRules()` 返回
   服务端清空后列表。
3. 设置页在规则列表非空时显示「全部删除」按钮；
   点击先走项目内 `confirmDialog`（danger）确认，
   取消即无事发生；成功后直接采用服务端返回的空
   列表，失败保留原列表并显示失败文案。
4. 规则生成、求值、逐条删除与远程渠道全部不变；
   UI 仍无任何 pattern 输入面。

## 3. 合同

- 清空端点无请求体；不接受任何按 pattern/插件名/
  decision 的筛选参数——语义只有「全部」一种，
  避免它长成条件删除的规则写面。
- 清空只写空列表：存储里 parse 后无效的条目随之
  一并消失（与逐条删除写回规范化同性质）；清空
  无规则可删时同样返回 ok（幂等），不报错。
- Origin 守卫与逐条删除同口径：第三方 Origin 403
  且不写存储。
- Electron body 为空对象透传；前端 demo 模式返回
  `[]` 不触发 invoke，与 listRules/deleteRule 一致。
- 「全部删除」按钮仅在列表非空且无进行中的删除/
  清空时可用；确认文案走 i18n（zh/en），确认前
  不发任何请求。
- 清空失败（含确认后请求失败）保留当前列表并显示
  `settings.permission.rules.clear_failed`，不伪装成功。

## 4. 实现落点

- `backend/api/permission_routes.py`：
  `clear_permission_rules` 端点。
- `electron/commandRoutes/settings.ts`：
  `permissions_clear_rules` 命令；`npm run ipc:manifest`
  重生成 `electron/ipc-manifest.json`。
- `src/shared/api/permissionApi.ts`：`clearRules()`。
- `src/pages/settings/PermissionRulesManager.tsx`：
  全部删除按钮 + confirmDialog + 失败态。
- i18n：`settings.permission.rules.clear_all`、
  `.clear_confirm_title`、`.clear_confirm_message`、
  `.clear_failed`（zh/en）。
- 测试：`backend/tests/api/test_permission_routes.py`、
  `src/shared/api/__tests__/permissionApi.test.ts`、
  `src/pages/settings/__tests__/GeneralTab.test.tsx`。
- 文档：technical 97 号当前契约、本总账（回填 R99
  已合并）；user-manual 21 无规则管理细节，不改。

## 5. 非目标

- 不做按插件/decision 分组清除、多选批量删除、
  规则新建/编辑/排序/分组/搜索；
- 不做清空后撤销（undo）或清空前导出备份；
- 不改 remember、逐条删除、求值优先级或存储格式；
- 不给远程网关增加清空能力；不做 Win7 同步（待对齐）。

## 6. 验证计划

- 后端定向：`test_permission_routes.py` 新增清空用例
  （清空后存储为空且返回空列表、无效存量条目随之
  消失、空存储幂等 ok、evil Origin 403 且不写）。
- 相邻回归：权限 enforcer 与审批路由相邻测试不回归。
- 前端定向：`permissionApi.test.ts` 覆盖 clearRules
  调用与错误透传；`GeneralTab.test.tsx` 覆盖空列表
  不显按钮、确认后采用空列表、取消不清、失败保留。
- 通用：ipc-manifest check、tsc（src 与 Electron）、
  ESLint（改动文件）、Ruff、py38、architecture、
  silent-exceptions、diff-check 与 diagnostics 0 项。

### 6.1 本地验证记录（2026-10-24）

- 后端定向 45 例通过（`test_permission_routes`，
  含清空后为空且无效存量条目一并消失、空存储幂等、
  evil Origin 403 不写）；相邻回归 83 例通过
  （`test_permissions_enforcer`、
  `test_question_routes`、`test_telegram_approvals`）。
- 前端定向 36 例通过（`permissionApi.test`、
  `GeneralTab`、i18n zh/en 新键覆盖，含空列表不显
  按钮、确认后清空、取消不清、失败保留列表）；
  tsc（src 与 Electron）通过，ESLint 改动文件 0 errors。
- ipc-manifest 已重生成并 check 通过（264 commands）；
  Ruff、真实 Python 3.8 编译与 py38 compat
  （0 violations）、architecture（测试文件超 800 行
  已按门禁建议登记 baseline 831）、silent-exceptions、
  diff-check 通过；diagnostics 0。

## 7. 影响与回滚

- 行为增量只是一个经确认的清空入口；误清后果仅为
  全部工具恢复逐次审批（fail-safe），规则可随后续
  remember 自然重建，无数据结构迁移。
- 回滚只需移除端点、命令与 UI 按钮；存量规则数据
  格式不变。
