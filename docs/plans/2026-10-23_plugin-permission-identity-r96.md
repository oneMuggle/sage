# R96 插件权限规则结构化身份匹配规格

- 日期：2026-10-23
- 基线：`main` `7634de8fc68e9064007706385ac433ec6c965d96`
- 状态：已交付（PR #2413，squash 合并为 `main`
  `56b005127a7f83f48086460fdce3192484c18717`）
- 编号说明：R96 为 `plugin-evo-index.md` 的插件账轮次号，
  与 2026-09 的同号测试收口计划无关。
- 前置：R92 已定义两种受限插件通配；R94 已提供桥接权威
  快照；R95 已让审批“记住”能由服务端派生单个插件的
  `plugin__<plugin>__*` 权限规则。本轮只收紧这些规则在
  执行时的身份匹配，不改规则的创建或存储格式。

## 1. 背景与问题

插件完整工具名为 `plugin__<plugin>__<capability>`，但现有
校验允许插件名与 capability 名内部出现 `__`。因此同一个
字符串可能有两种结构化解释，例如
`plugin__a__b__c` 既可来自插件 `a` 的 capability
`b__c`，也可来自插件 `a__b` 的 capability `c`。

R95 创建整插件规则时已经不按字符串猜插件名，而是使用
`PluginToolBridge.published_tool()` 的权威记录；但规则落库
后，`PermissionEnforcer` 仍只用 fnmatch 对完整工具名做
字符串匹配。于是给插件 `a` 的 `plugin__a__*` 也可能命中
插件 `a__b` 的工具。手动写入的同形规则与 R95 派生规则
都有这个命名空间串扰面。

桥接层“第一发布者胜出”只能避免同一时刻两个同名工具并存，
不能证明未来接管同一字符串的工具仍属于原插件。权限规则
是长期信任边界，执行时必须重新核对当前已发布记录的真实
插件身份。

## 2. 目标

1. `permission_rules` 中受限插件通配
   `plugin__*` 与 `plugin__<plugin>__*` 在
   `PermissionEnforcer` 中改为结构化身份匹配，不再只看
   完整工具名字符串前缀。
2. 单插件通配只在当前工具的权威 `plugin_name` 与规则编码
   的插件名完全一致、且完整工具名确实属于该插件命名空间
   时命中；`a` 与 `a__b`、同字符串的两种解释不得串扰。
3. 调用方只能把桥接已发布记录中的 `plugin_name` 传给
   enforcer；没有权威身份时，受限插件通配一律不命中，
   后续回到既有模式矩阵或其它精确规则，不按字符串猜测。
4. 精确工具规则、普通 fnmatch 规则、规则存储格式与
   deny > allow > ask 的优先级全部不变。

## 3. 后端合同

### 3.1 `PermissionRule.matches`

- 签名扩展为
  `matches(tool_name, plugin_name=None)`；`plugin_name`
  只表示服务端权威记录，不接受由 `tool_name` 切分出的值。
- 若 `tool_pattern` 不是 R92 受限插件通配，保持现有
  大小写敏感 fnmatch 语义。
- 若是受限插件通配：
  1. `plugin_name` 缺失、非法，或完整工具名不能由该
     权威插件名与非空 capability 构成时，不命中；
  2. `plugin__*` 在权威身份存在且归属校验通过时命中
     任意当前已发布插件工具；
  3. `plugin__<plugin>__*` 只在由权威 `plugin_name`
     重新派生的受限通配与规则文本完全相同时命中。
- 上述逻辑对 allow、deny、ask 三种 decision 使用同一
  身份语义；身份不匹配的 allow 不放行，deny/ask 也不
  误伤另一个插件。

### 3.2 `PermissionEnforcer.check`

- 签名扩展为
  `check(tool_name, args=None, plugin_name=None)`，并把
  身份传给规则匹配层；bash 安全网、模式矩阵和路径边界
  校验顺序不变。
- 旧调用方不传 `plugin_name` 时仍可工作，但受限插件通配
  不再命中。这是刻意的 fail-closed 兼容策略：未知身份
  的插件 EXECUTE 工具会回到逐次审批或被无审批通道的
  adapter default-deny，不会继承整插件信任。
- `AutoApproveEnforcer` 与 `TrustEscalationEnforcer`
  必须透传非空 `plugin_name`，不得在包装层丢失身份。

### 3.3 调用方身份来源

- legacy agent 的串行预检、并行资格预检与同步
  `execute_tool` 统一经一个 helper 查询
  `PluginToolBridge.published_tool(tool_name)`；审批请求
  构建复用同一 helper，避免两份口径漂移。
- `InprocToolAdapter` 的权限 choke point 执行同样查询；
  非插件工具不查桥，桥查询异常按无权威身份处理。
- skill adapter 只检查固定工具名 `skill`，不涉及插件
  身份；本轮不为它增加无意义的桥查询。

## 4. 安全边界

- 本轮不按第一个或最后一个 `__` 从完整工具名反推插件
  名；结构化身份只来自当前桥接发布记录。
- 已保存的整插件 allow/deny/ask 规则文本不迁移、不删除；
  只是从本轮起按真实插件身份解释。若桥接记录暂时缺失，
  通配不命中，用户仍可逐次批准当前调用。
- 手动规则 `plugin__a__b__*` 按 R92 既有受限通配文法
  解释为“插件 `a__b`”，不再被当作插件 `a` 下任意
  `b__*` capability 的普通 fnmatch 前缀。
- profile 工具白名单仍是可见性边界，本轮不改
  `tool_name_in_allowlist()` 的字符串语义；实际执行时
  仍由本轮收紧后的权限 enforcer 与审批闸口兜底。
- 不禁止插件名/capability 名中的 `__`，也不改桥接的
  同名第一发布者胜出规则；本轮只消除持久权限规则的
  身份串扰，不做破坏性的命名迁移。

## 5. 非目标

- 不新增权限规则管理 UI，不改 `permission_rules` 的
  存储结构、审批弹窗或 R95 的 `remember_scope` 合同；
- 不做全部规则的结构化重写、通用 glob 废弃、插件命名
  禁令、市场/签名、OS 沙箱或其它 capability 托管；
- 不改 profile 白名单结构化匹配、远程/Telegram 审批或
  渐进式授权的风险口径；
- 不做 Win7 同步；Win7 继续如实标待对齐，并避开正在
  进行的 Win7 对齐 PR 文件面。

## 6. 测试与验证

后端定向：

1. `PermissionRule`：单插件通配命中真实插件；`a` 的规则
   不命中 `a__b`，`a__b` 的规则不命中插件 `a` 的
   `b__c`；同字符串两种结构只命中权威身份对应的一方；
2. `PermissionEnforcer`：无 `plugin_name` 时整插件 allow
   不再放行、deny/ask 不误命中；有正确身份时三种 decision
   仍按 deny > allow > ask；精确规则与普通 fnmatch 不回归；
3. legacy agent 与 InprocToolAdapter：仅已发布插件工具把
   权威插件名传给 enforcer，未发布/非插件工具不传或
   传空，桥异常不放宽；
4. 两个 enforcer 包装器透传非空插件身份，旧的无身份
   调用仍兼容既有 fake/调用方。

通用：

- 目标 pytest、相关相邻权限/插件回归；
- 目标 Ruff、py38 compat、真实 Python 3.8 `py_compile`；
- architecture-check、silent-exceptions、`git diff --check`
  与改动范围 diagnostics 0 项。

### 6.1 本地验证记录（2026-10-23）

- 后端定向 134 例通过：`test_permissions_enforcer.py`、
  `test_agent_tool_gate.py`、`test_inproc_tool_adapter.py`、
  `orchestration/test_subagent_approval.py` 与
  `test_trust_escalation.py`。
- 相邻回归 113 例通过：审批 gate、插件桥、并行中断、
  subagent 事件、skill/tool policy/compute adapter、必填参数，
  以及 agent/chat service 两条权限集成流。
- 改动 Python 文件 Ruff check 通过；`check_py38_compat.py`
  为 0 violations，真实 Python 3.8 对 5 个生产文件
  `py_compile` 通过。
- architecture-check、silent-exceptions、
  `git diff --check` 通过；backend 与 docs 改动范围
  diagnostics 均为 0 项。
- GitHub PR #2413：All checks successful（14 successful、
  2 skipped、0 failing），已 squash 合并为 `main`
  `56b005127a7f83f48086460fdce3192484c18717`；合并后
  tree 与 PR head 逐文件一致，分支与 worktree 已清理。

## 7. 影响与回滚

- 影响只限权限规则执行期解释；规则创建、审批 UI、工具
  发布与 profile 保存数据均不改。
- 若某条历史整插件规则此前靠字符串串扰命中了另一插件，
  本轮后会改为逐次审批或被无审批通道拒绝，这是预期的
  安全收紧，不是数据丢失；用户可对真实插件重新逐次
  批准并按 R95 记住。
- 回滚只需撤销身份参数与受限通配的结构化解释；已保存
  规则无需迁移。
