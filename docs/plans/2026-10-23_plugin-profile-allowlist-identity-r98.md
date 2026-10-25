# R98 插件 profile 白名单结构化身份匹配规格

- 日期：2026-10-23
- 基线：`main` `2099292efb70ee644caeb361e5439a95b492f74a`
- 状态：PR #2440 待 CI 与合并
- 编号说明：R98 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R92 已定义 `plugin__*` 与 `plugin__<plugin>__*`
  两种受限通配，并让 profile 白名单的三道判定共用
  `tool_name_in_allowlist()`；R96 已让权限规则按桥接权威
  插件身份匹配，但明示 profile 白名单仍是字符串语义。
  本轮把同一结构化口径带到 profile 白名单与前端覆盖
  镜像，不改 profile 数据格式。

## 1. 背景与问题

`tool_name_in_allowlist()` 目前对受限通配只做命名空间
前缀的文本匹配。插件名与 capability 名都可含 `__`，
同一完整工具名字符串可能对应不同结构化身份：条目
`plugin__a__*` 会以文本前缀命中 `plugin__a__b__c`，
而该工具可能实际属于插件 `a__b`（capability 为
`c`）。于是只想放行插件 `a` 的 profile，会把另一个
插件的工具一并暴露给 LLM（schema 过滤）并在执行
边界放行（并行预检与分发前门控）。权限 enforcer 仍
会逐次审批兜底，但 profile 本身是「这个 Agent 能用
哪些工具」的授权边界，字符串串扰等于静默扩围。

前端另有一份覆盖镜像 `findPluginToolWildcardCover`：
它拒绝插件段或 capability 段含 `__` 的情形，与后端
文本口径双向漂移——后端会放行而复选框不显示已覆盖，
或字符串前缀相同但真实插件不同时复选框误报已覆盖。

## 2. 目标

1. `tool_name_in_allowlist()` 增加权威 `plugin_name`
   参数；受限插件通配只按结构化身份命中，语义与
   R96 `PermissionRule.matches()` 完全一致。
2. 三道闸都传入权威身份：registry schema 过滤取已
   注册工具对象自身的发布身份；legacy agent 的并行
   预检与执行边界取桥接当前发布记录。
3. 前端覆盖镜像改用已发布快照中的 `plugin_name`，
   复选框的「被通配覆盖」与后端可见性同口径。
4. 精确条目、`None`/`[]` 语义与「不展开通用 glob」
   全部不变；不改 profile 存储与启动期形状校验。

## 3. 合同

- 签名：`tool_name_in_allowlist(tool_name,
  allowed_tools, plugin_name=None)`。
- `allowed_tools is None` 仍为无白名单放行；显式
  白名单下非字符串工具名仍不放行，坏条目仍不能放
  宽整个白名单。
- 精确条目仍按完整字符串相等命中，不要求身份
  （与 R96 精确权限规则同口径）：profile 显式写出
  的就是这个完整工具名。
- 仅受限通配条目走结构化路径：必须同时满足调用方
  提供了合法权威 `plugin_name`、完整工具名确实
  属于该插件（`plugin_tool_belongs_to_plugin`）；
  `plugin__*` 在此前提下命中，`plugin__<p>__*`
  还须与由权威名重新派生的通配完全一致。身份
  缺失、非法或不匹配时通配不命中（fail-closed）。
- 任何调用方不得按完整工具名切分猜测插件名。
  身份只有一个来源口径：桥接发布记录——registry
  侧是发布时由桥接构造并注册的 `PluginTool` 对象
  自带的 `plugin_name`，agent 侧是
  `_authoritative_plugin_name()` 查桥结果，前端
  侧是 `PublishedPluginTool.plugin_name` 快照字段。
- registry 中没有字符串型 `plugin_name` 的对象
  （内置工具、MCP 工具、伪造名对象）一律按身份
  未知处理：通配不展开到它，精确名仍可命中。
  通配展开因此只覆盖真正已发布的插件工具。
- 前端：`pluginName` 缺失，或 `tool_name` 不在
  `plugin__<pluginName>__` 命名空间内时不算覆盖；
  覆盖只认 `plugin__*` 与由该 `pluginName` 派生
  的单插件通配。插件名/capability 名含 `__` 时
  按身份精确判定，消除旧镜像的双向漂移。

## 4. 实现落点

- `backend/domain/tool_names.py`：matcher 签名与
  通配分支改结构化；模块注释补 R98 口径。
- `backend/tools/registry.py`：schema 过滤把
  `getattr(tool, "plugin_name", None)` 传入
  matcher；docstring 同步。
- `backend/core/legacy/agent.py`：三处白名单判定
  （两处并行批级预检、`_pre_dispatch_gate` 执行
  边界）传入 `_authoritative_plugin_name()` 结果。
- `src/widgets/agents/EditAgentForm.tsx`：
  `findPluginToolWildcardCover` /
  `pluginToolSelectionState` 增加 `pluginName`
  参数并改结构化覆盖；渲染处传入快照的
  `tool.plugin_name`。
- 测试：`test_tool_names.py` matcher 合同、
  `test_tools_registry.py` schema 过滤、
  `test_agent_tool_gate.py` 执行边界、
  `EditAgentForm.tools.test.ts` 前端镜像。
- 文档：technical 97 号当前契约、user-manual
  21 号白名单段、本总账。

## 5. 非目标

- 不改 profile 存储格式、条目文法与
  `validate_profile_tools` 的形状级启动校验；
- 不改权限规则与 enforcer（R96 已交付）、审批
  弹窗、远程渠道或 R95 `remember_scope` 合同；
- 不改精确条目的字符串语义，不禁止插件名或
  capability 名中的 `__`，不做命名迁移；
- 不新增任何由客户端指定 pattern 或插件名的
  写面；不做 Win7 同步（继续标待对齐，避开
  Win7 对齐 PR 文件面）。

## 6. 验证计划

- 后端定向：`test_tool_names.py`、
  `test_tools_registry.py`、`test_agent_tool_gate.py`
  全过；新增用例覆盖身份缺失不命中、串扰字符串
  按真实插件判定、含 `__` 的插件名单插件通配、
  `plugin__*` 也要求身份、精确条目不受影响。
- 相邻回归：插件桥、权限 enforcer、并行预检与
  profile 校验相关测试不回归。
- 前端定向：`EditAgentForm.tools.test.ts` 覆盖
  结构化覆盖、串扰不覆盖、缺身份不覆盖、
  `__` 插件名/capability 名正确覆盖。
- 通用：tsc（src）、ESLint（改动文件）、Ruff、
  py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 0 项。

### 6.1 本地验证记录（2026-10-23）

- 后端定向 70 例通过（`test_tool_names`、
  `test_tools_registry`、`test_agent_tool_gate`；
  含身份缺失两种通配均不命中、串扰字符串按真实
  插件身份翻转判定、registry 只把通配展开到带
  发布身份且相符的工具、执行边界对未发布/串扰
  工具按 profile 拒绝）；相邻回归 93 例通过
  （`test_agent_loop_guards`、
  `test_plugin_tool_bridge`、
  `test_permissions_enforcer`）。
- 前端定向 10 例通过（`EditAgentForm.tools`
  8 例，含结构化覆盖、串扰不覆盖、缺身份不覆盖、
  含 `__` 的插件名/capability 名正确覆盖；
  `EditAgentForm.p133` 2 例）；tsc（src 与
  Electron）通过，ESLint 改动文件 0 errors。
- Ruff、py38 compat（0 violations）与真实
  Python 3.8 对 3 个生产文件编译、architecture、
  silent-exceptions、diff-check 通过；
  backend/src/docs diagnostics 均为 0。

## 7. 影响与回滚

- 影响只限 profile 通配的执行期解释。配置正确的
  profile（通配写的就是目标插件）行为不变；此前
  靠字符串串扰被 `plugin__a__*` 带飞的其它插件
  工具将不再暴露/放行，这是预期的安全收紧，用户
  把条目改写为真实插件的通配或完整工具名即可。
- 未发布的插件工具名本就不在 registry 中，schema
  可见性无变化；执行边界对伪造/未发布名的通配
  命中改为拒绝，与 R96 身份未知口径一致。
- 回滚只需还原 matcher 与四处调用点；profile
  数据不迁移、不丢失。
