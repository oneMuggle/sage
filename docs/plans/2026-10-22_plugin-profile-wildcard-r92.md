# R92 插件工具 profile 通配与 Agent 工具白名单编辑规格

- 日期：2026-10-22
- 基线：`main` `880bf8ad1cb1d4f2d651bd2ccebc2580ed32460b`（R91 已合并）
- 状态：实施中（本 PR）
- 前置：R90 已把运行中进程外插件 tool 桥入聊天 `ToolRegistry`

## 1. 背景与问题

R90 的 profile 边界是精确白名单：只有把完整工具名
`plugin__<plugin>__<capability>` 写进 `profile.tools`，该 Agent 才能看到并
调用对应插件工具；`plugin__demo__*` 当前按普通字符串处理，匹配不到任何工具。
这对动态插件面有两个实际问题：

1. 插件新增、改名或增删 capability 后，每个自定义 profile 都要逐项同步完整
   工具名，否则新 capability 对该 Agent 静默不可见；
2. Agent 管理页只能编辑名称、描述、系统提示、模型与迭代上限，不能编辑
   `tools` 白名单；用户只能绕 UI 通过 API 或导入档案配置插件工具。

R92 用一个受限通配语法补齐这两处，不改变 R90 的启动、发布与审批边界。

## 2. 通配语义（唯一合同）

`profile.tools` 的每一项按以下规则匹配工具名：

| 条目 | 语义 |
|---|---|
| 普通完整工具名 | 与既有行为完全一致，精确匹配 |
| `plugin__*` | 匹配全部合法形状的插件工具 `plugin__<plugin>__<capability>` |
| `plugin__<plugin>__*` | 只匹配该插件命名空间前缀下的全部 capability |
| 其它含 `*` 的条目 | **不做通配展开**，只按精确字符串处理（实际匹配不到合法工具名） |

明确不展开的例子：`*`、`memory_*`、`mcp__*`、`plugin__demo*`、
`plugin__*__hello`、`plugin____*`。这样可避免把一次插件便利性扩展误变成
对内置工具或 MCP 工具的通用 glob 授权。

`allowed_tools=None` 仍表示无 profile 白名单；显式 `[]` 仍表示不暴露任何
工具。无效条目一律 fail-closed，不因一条坏条目放宽整个白名单。

插件名若本身含 `__`，完整工具名在文本层存在既有的拼接歧义（R90 已以
first-wins 处理跨插件同名冲突）。R92 通配只按命名空间前缀做文本匹配；
这类插件应优先使用完整精确名，文档须如实说明。

## 3. 安全边界

- 通配只影响 **profile 可见性与执行边界的白名单判定**，不绕过权限层：
  插件工具仍是 EXECUTE（network/external 信号为 EXTERNAL），仍走默认逐次
  审批、`read_only` 拒绝与用户 deny/allow 规则。
- 插件仍只能由用户显式 start 后发布；install/enable/后端重启不会因为
  profile 里有通配而自动启动任何进程。
- `plugin__<plugin>__*` 是对该插件 **未来 capability** 的常驻可见性授权：
  插件升级新增 capability 后会自动对该 Agent 可见（调用仍逐次审批）。
  最小权限场景应继续使用完整精确名，文档与 UI 帮助文本都须写明。
- 默认种子 profile 本轮 **不新增** `plugin__*`：是否把插件工具带给某个
  Agent 仍由用户显式写入白名单决定。
- 本轮不做「按插件记住放行」：权限规则层已有 fnmatch 能力，但其产品 UX
  与风险提示需真实使用数据另行设计，不能跟 profile 通配捆绑静默放行。

## 4. 实施范围

### 4.1 共享名字语义（防四处漂移）

- 在纯标准库的 `backend/domain/tool_names.py` 定义
  `PLUGIN_TOOL_PREFIX`、插件工具名/引用识别与
  `tool_name_in_allowlist(tool_name, allowed_tools)` 单一匹配函数；
  插件动态名不进入 `ALL_BUILTIN_TOOL_NAMES`。
- `backend/plugins/tool_bridge.py` 与 `backend/tools/permissions.py`
  改为从 domain 导入同一 `PLUGIN_TOOL_PREFIX`，消除现有两份字面量副本；
  原模块级名字保持可导入。

### 4.2 三道白名单闸口统一走匹配函数

1. `ToolRegistry.get_schemas_for_llm()`：schema 暴露过滤；
2. SageAgent 的并行资格预检与执行组规划：批级预检；
3. SageAgent 的 `_pre_dispatch_gate()`：执行边界再校验。

三处不得再各写一份 `in set(...)` 精确判定，避免「LLM 看得到但执行被拒」
或反向漂移。

### 4.3 启动期 profile 校验

`validate_profile_tools()` 对合法形状的插件精确名与两种合法通配不再告警；
无效通配（如 `plugin__demo*`）仍按未注册名告警，帮助用户发现写法错误。
MCP 等其它动态名字的既有告警口径不变。

### 4.4 Agent 管理页工具白名单编辑

- `EditAgentForm` 新增「工具白名单」多行文本编辑：每行一项，也可用逗号
  分隔；保存时去空白、去重并保持顺序。
- 帮助文本写明精确名与 `plugin__*` / `plugin__<插件名>__*` 两种通配，
  以及清空表示该 Agent 不暴露任何工具。
- 本轮不做从运行中插件工具动态生成复选框；那需要运行时工具清单接口与
  更大的 UX 设计，留作后续。

### 4.5 文档

- `docs/plans/plugin-evo-index.md`：R90 改记已交付（#2327），新增 R92
  总账行与交付边界；
- 插件开发/清单现行文档同步 profile 通配写法与风险提示；
- 本规格。

## 5. 非目标

- 不支持内置工具、MCP 工具或任意 `fnmatch` 风格的通用通配；
- 不修改默认 profile 种子，不自动把插件工具带给 primary；
- 不改权限模式、审批、用户规则与「记住放行」行为；
- 不改插件命名、schema 契约、发布/注销与冲突 first-wins 语义；
- 不做市场、下载、验签、OS 沙箱与 parked 的 DSH 兼容；
- 不处理 Win7 同步，Win7 列继续如实标待对齐。

## 6. 测试与验证

后端：

1. domain 匹配函数：精确名、两种合法通配、无效通配、通用 glob 不展开、
   `None`/`[]`、非字符串条目与歧义前缀；
2. `ToolRegistry.get_schemas_for_llm()`：通配只暴露插件工具，不误伤内置；
3. R90 桥接测试：把「通配必为空」的旧断言改为新合同，并覆盖跨插件隔离；
4. SageAgent 执行闸口：通配内工具不被白名单拒绝、通配外仍拒绝，且既有
   enforcer 调用顺序不变；并行预检口径与执行边界一致；
5. `validate_profile_tools()`：合法插件引用零告警、无效通配仍告警；
6. 插件桥、权限、profile 种子与工具注册相关回归集。

前端：

1. 工具文本 parse/format helper：分隔符、去重、顺序与通配条目原样保留；
2. 定向 Vitest、TypeScript typecheck 与目标 ESLint。

通用：改动文件 diagnostics、Ruff、逐文件 py38 hazard scan、
`git diff --check`，最终以 PR CI 为权威门禁。

## 7. 撞车与风险

- 在途 main PR #2354/#2345 同样触及 `backend/core/legacy/agent.py`，但其
  hunk 位于超时/上限错误区域，与本轮 import 及三处白名单判定不重叠；
  开 PR 前仍须 fetch 复核，必要时 update-branch 后复验 CI。
- 通配让未来 capability 自动可见是显式产品语义而非实现副作用，必须在
  UI 与文档中写明；逐次审批仍是最后一道用户闸口。
- 回滚只需撤销本轮提交：已保存的通配条目会退回 R90 的精确字符串语义
  （匹配不到工具，fail-closed），不涉及数据迁移。
