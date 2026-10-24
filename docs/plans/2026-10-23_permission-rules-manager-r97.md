# R97 已记住权限规则管理（查看/删除）规格

- 日期：2026-10-23
- 基线：`main` `56b005127a7f83f48086460fdce3192484c18717`
- 状态：已交付（PR #2418，squash 合并为 `main`
  `a29e95ab70dc590d6469fe7c0f867e50f106f756`）
- 编号说明：R97 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R95 已让审批「记住我的选择」把精确工具或整插件
  的 allow/deny 持久化到 `permission_rules`；R96 已让这些
  规则按桥接权威插件身份求值。本轮只补这些已保存规则的
  可见与可撤销，不改规则创建、存储格式或求值语义。

## 1. 背景与问题

`permission_rules` 是长期信任边界：一条整插件 allow 会
覆盖该插件未来新增的全部工具。但设置页至今只能切换权限
模式，并明示「细粒度规则暂不支持界面编辑」；用户看不到
自己攒下了哪些规则，也无法在界面里撤销一条过时或误记的
允许，只能手工处理底层 JSON。R95/R96 明确把规则管理 UI
列为非目标，本轮正面补上这一环。

## 2. 目标

1. 设置页「工具权限」区列出当前有效的已保存规则
   （`tool_pattern` + allow/deny/ask），顺序与
   `parse_rules()` 的求值输入一致。
2. 用户可逐条删除规则；删除经后端校验后写回
   `permission_rules`，并以服务端返回的最新列表刷新 UI，
   前端不直接拼写原始 JSON 存储。
3. 空列表、读取失败与删除失败都有明确文案，不静默吞掉
   失败，也不在失败时假装删除成功。

## 3. 合同

### 3.1 后端（`backend/api/permission_routes.py`）

- `GET /api/v1/permissions/rules` →
  `{ok: true, rules: [{tool_pattern, decision}, ...]}`，
  数据来自 `parse_rules(repo.get_json("permission_rules"))`，
  即 enforcer 实际生效的规则；存储中的非法条目按既有
  语义跳过，不在 UI 中伪装成有效规则。
- `POST /api/v1/permissions/rules/delete`，body 只允许
  `{index: int}`（extra=forbid），并与 preset 写入共用
  Origin 守卫。`index` 指 GET 返回的已解析列表下标；
  服务端重新读取并解析后校验范围，越界返回 400
  `rule index out of range`，不写存储。
- 删除只移除该下标的一条（重复规则逐条删），随后以
  `set_json` 写回规范化后的有效规则列表并返回
  `{ok: true, rules: [...]}`。已失效的非法存储条目会在
  这次写回时被清理——它们本来就不参与求值。
- 不新增「创建/编辑规则」端点：规则仍只能由审批
  remember 生成（精确工具）或由服务端按权威插件名派生
  （整插件），管理端不得借道写入任意 pattern。

### 3.2 Electron 与前端

- `electron/commandRoutes/settings.ts` 新增
  `permissions_list_rules`（GET）与
  `permissions_delete_rule`（POST，body 只透传 `index`），
  并按仓库流程重新生成 `electron/ipc-manifest.json`。
- `permissionApi.listRules()` / `deleteRule(index)` 做
  宽容解析：只保留 `tool_pattern` 为非空字符串且
  decision ∈ {allow, deny, ask} 的条目；demo 模式返回
  空列表。删除返回服务端最新列表供 UI 直接采用。
- `GeneralTab` 权限区在模式选择器下新增已记住规则
  列表：逐行显示 pattern 与决定文案，行尾删除按钮带
  可访问名与 `data-testid`；加载失败显示失败文案，
  删除失败保留原列表并提示。原「暂不支持界面编辑」
  提示改为「可在下方查看并删除；新规则仍由审批记住
  生成」。

## 4. 安全边界

- 删除是收紧或放宽既有持久信任的显式用户动作，必须走
  后端端点（Origin 守卫 + 下标校验），不经通用
  preferences KV 由前端整表回写，避免前端拼错 JSON
  把规则表写坏或绕过解析口径。
- 本轮不提供新增/编辑 pattern 的入口，因此不会新开
  「前端传任意通配」的写面；R95 的元字符拒绝与整插件
  服务端派生规则全部保持。
- 列表口径与求值口径同源（同一个 `parse_rules`），
  UI 看到的就是 enforcer 生效的规则，不展示已失效的
  非法条目充数。

## 5. 非目标

- 不做规则新增/编辑、拖拽排序、批量清空、按插件分组
  或规则搜索；
- 不改 `permission_rules` 存储结构、remember 追加的
  去重策略、审批弹窗与 R96 身份匹配语义；
- 不做远程（Telegram 等）渠道的规则管理，不做 Win7
  同步；Win7 继续如实标待对齐，并避开在途 Win7 PR 的
  文件面（#2414 已核查不覆盖 GeneralTab/settingsClient，
  i18n 新增键按既有惯例留待 Win7 对齐）。

## 6. 测试与验证

- 后端：GET 空/有规则（含非法条目被跳过）；delete
  正常逐条删除且返回新列表、重复规则只删一条、越界
  400 不写存储、非法 Origin 403、extra 字段 422；
  既有 permission routes 回归。
- 前端：permissionApi 解析与命令名/参数；GeneralTab
  列表渲染、空态、删除调用与刷新、失败文案；既有
  权限模式与 GeneralTab 回归。
- Electron：`ipc:manifest:check` 通过，命令路由相关
  测试不回归。
- 通用：tsc、ESLint（改动文件）、Ruff（改动后端文件）、
  py38、architecture、silent-exceptions、diff-check 与
  diagnostics 0 项。

### 6.1 本地验证记录（2026-10-23）

- 后端定向 `test_permission_routes.py` 37 例通过（含新增
  6 例：空列表、非法条目跳过、逐条删除、越界 400、extra
  422、evil Origin 403）；相邻回归 77 例通过（question
  routes、settings repo、permissions enforcer）。
- 前端定向 26 例通过（permissionApi 8、GeneralTab 18，
  含列表渲染/删除刷新/加载与删除失败文案）；相邻 i18n
  与 setting storage 33 例通过。
- tsc（src 与 Electron）通过；ESLint 改动文件 0 errors
  （2 条 react-refresh warning 为 GeneralTab 存量 audit
  导出，非本轮引入）；`ipc:manifest:check` 通过（263
  commands）。
- Ruff、py38 compat（0 violations）与真实 Python 3.8
  编译、architecture、silent-exceptions、diff-check
  通过；backend/src/electron/docs diagnostics 均为 0。
  架构门曾报 GeneralTab 超 800 行，已把规则管理组件
  抽为独立 `PermissionRulesManager.tsx` 后转绿，未抬
  baseline。
- PR #2418 GitHub CI 全绿（14 successful / 2 known
  skipped / 0 failing），已 squash 合并为 `main`
  `a29e95ab70dc590d6469fe7c0f867e50f106f756`。

## 7. 影响与回滚

- 影响只限设置页展示与一个删除端点；规则创建与求值
  路径零改动。误删一条规则的后果是该工具恢复逐次
  审批（fail-closed 方向），用户可重新记住。
- 回滚只需撤销端点、命令与 UI；已保存规则数据不迁移、
  不丢失（删除写回的规范化只清掉本就无效的条目）。
