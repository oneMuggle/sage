# R95 插件工具按插件记住审批决定规格

- 日期：2026-10-23
- 基线：`main` `6e8f626696879d3ad826ddf88a7c0e506612f847`
- 状态：✅ 已交付，PR #2412 已 squash 合并为 `main`
  `7634de8fc68e9064007706385ac433ec6c965d96`
- 编号说明：R95 为 `plugin-evo-index.md` 的插件账轮次号，与
  2026-09 的同号测试收口计划无关。
- 前置：R90 已让运行中进程外插件 tool 进入聊天执行面并逐次
  审批；R92 的 `plugin__<plugin>__*` 只属于 Agent profile
  工具白名单，不等于权限审批规则；R94 已提供桥接权威快照。

## 1. 背景与问题

现有审批弹窗的「记住我的选择」只能把当前完整工具名落成
一条精确 `permission_rules`。同一个可信插件有多个
capability 时，用户仍要逐个工具重复批准并逐个记住；若让
用户手写 fnmatch，又会重新打开 `*` 注入成永久 allow-all
的风险。R90、R92、R94 都明确把「按插件记住放行」延后到
有完整产品与安全边界时再做，本轮补齐这条链。

## 2. 目标

1. 插件工具审批时，用户勾选「记住我的选择」后可显式选
   「仅此工具」（默认）或「整个插件」；整插件选项显示真实
   插件名与将落库的 `plugin__<plugin>__*`，并提示会覆盖
   该插件未来新增的工具。
2. 后端只接受范围枚举，不接受客户端提供的 pattern 或插件
   名；整插件 pattern 必须由服务端待审批请求中的权威
   `plugin_name` 派生并严格校验。
3. 精确工具范围、未记住、旧客户端、非插件工具、远程审批
   与权限规则求值语义全部不变。

## 3. 后端合同

### 3.1 权威插件名

- `PluginToolBridge.published_tool(tool_name)` 在锁内按完整
  工具名返回单个 `PublishedPluginTool` 快照或 `None`；它
  与 R94 `published_tools()` 共用同一快照构造。
- `ApprovalRequest` 新增可选 `plugin_name`。只有主 agent
  构造审批请求时，若工具名呈合法插件工具形状且能从当前
  bridge 已发布记录反查到同一完整名，才注入记录里的
  `plugin_name`；查不到或查询失败时保持为空。
- `ApprovalRequest.to_dict()` 仅在 `plugin_name` 非空时
  下发该字段，流事件与 `GET /permissions/pending` 共用。
- 不按第一个 `__` 猜插件名：插件名本身可含下划线，字符串
  切分在极端命名下可能把规则扩到另一个插件。

### 3.2 应答与持久化

- `POST /api/v1/permissions/{request_id}/answer` 请求体新增
  `remember_scope: "tool" | "plugin"`，默认 `"tool"`；
  `ApprovalAnswer` 与 gate 的当前应答语义不增加新字段，
  范围只作用于路由侧规则持久化。
- `remember=false` 时忽略范围且不写 settings。
- `remember_scope="tool"` 保持 FIX-3：完整工具名含
  `* ? [ ]` 任一 fnmatch 元字符时不落规则。
- `remember_scope="plugin"` 仅当待审批请求同时满足以下
  条件时才落 `plugin__<plugin>__*`：
  - 请求带非空服务端 `plugin_name`；
  - 工具名是合法插件工具名，且以
    `plugin__<plugin_name>__` 开头并有非空 capability；
  - 插件名通过现有插件名字符集校验，派生值通过 R92 的
    受限插件通配识别。
- 条件不满足时，本次批准/拒绝仍照常作用，但不落任何规则
  并记录 warning；不得降级猜测、不得接受 `plugin__*`。
- 批准落 allow、拒绝落 deny；仍追加到既有
  `permission_rules`，不改 `PermissionEnforcer` 的
  deny > allow > ask 与后续安全网。

### 3.3 Electron 透传

- `permissions_answer` route body selector 新增
  `remember_scope`，并补齐既有 UI 已发送、后端已支持但
  selector 漏传的拒绝反馈 `reason`。
- `requestId` 继续只进 URL path，不进 body；多余字段继续
  被 selector 剥离，避免后端 `extra="forbid"` 422。

## 4. 前端合同

- `PermissionRequest` 增加可选 `plugin_name`；无此字段时
  弹窗与今天完全一致。
- `ApprovalDialog` 新增 `rememberScope` 局部状态，默认
  `tool`，每个新 request 到达时与 `remember` 一起重置。
- 仅当 `remember=true` 且请求带 `plugin_name` 时展示两个
  单选项：仅此工具 / 整个插件。整插件文案包含插件名、
  派生 pattern 与“包含未来新增工具”的警告。
- 应答 invoke 始终发送 `rememberScope`；Electron selector
  映射为后端 `remember_scope`。项目级路径允许按钮不借此
  扩大范围，仍走原路径规则与当前应答。
- 新增中英文 i18n；不把插件名拼进可翻译 key，动态值只做
  文本插值。

## 5. 安全边界

- 整插件 allow 是用户显式、逐请求选择的持久授权，不是
  插件启动、安装、profile 勾选或连续批准后的自动升级。
- pattern 永远由服务端从已发布记录派生；LLM 工具名与
  客户端字段都不能指定任意 fnmatch，更不能生成
  `plugin__*` 或裸 `*`。
- 已保存的整插件规则按既有 fnmatch 生效，因此同一插件
  后来新增的 capability 也会被覆盖；UI 必须在落库前明确
  告知。插件改名会形成新命名空间，不继承旧规则。
- profile 白名单仍是“模型能看见/能调用哪些工具”的边界，
  权限规则仍是“调用是否需审批”的边界；本轮不合并两层。

## 6. 非目标

- 不做全部插件一次记住、通用 glob、按参数/路径/会话范围
  记住、过期时间或使用次数上限；
- 不新增权限规则管理 UI，不改既有规则的查看/删除方式；
- 不改渐进式授权（trust escalation）、权限三档、远程 MCP
  审批或 Telegram 审批；
- 不做 Win7 同步、市场/签名、其它 capability 托管或 OS
  沙箱；Win7 继续如实标待对齐。

## 7. 测试与验证

后端：

1. bridge 单项快照命中/未命中与发布后消失；
2. agent 审批请求只为已发布插件工具注入权威插件名；
3. permission route：默认精确范围不回归；plugin allow /
   deny 落受限 pattern；无权威插件名、名字不匹配、非插件
   工具或非法范围不能落整插件规则；旧请求体仍可应答。

前端与 Electron：

1. 非插件请求不展示范围选项；插件请求勾选记住后展示，
   默认精确、选择整插件后发送 `rememberScope="plugin"`，
   新请求重置范围；
2. route selector 透传 `remember_scope` 与 `reason`，继续
   剥离 `requestId` 与未知字段；
3. 定向 Vitest、TypeScript、目标 ESLint。

通用：Ruff、py38 逐文件扫描、silent-exceptions、
architecture-check、`git diff --check` 与改动 diagnostics；
最终以 PR CI 为权威门禁。

## 8. 撞车与回滚

- 在途 Win7 PR #2410 正在同步 R92 期插件 routes/frontend
  到 `release/win7`，与本轮 main 文件可能同名但目标分支
  不同；本轮不碰 Win7，后续同步须以 #2410 合并后的 Win7
  基线重新盘点。
- 回滚只需撤销可选字段、范围枚举、派生规则、弹窗选项与
  文档；已经落库的 `plugin__<plugin>__*` 是普通既有规则，
  回滚代码不会自动删除用户规则。

## 9. 本地验证（2026-10-23）

- 后端核心定向：`test_tool_names`、`test_plugin_tool_bridge`、
  `test_permission_gate`、`test_agent_tool_gate`、
  `test_permission_routes` 共 119 passed。
- 后端相邻回归：`test_permissions_enforcer`、
  `test_permission_diff_preview`、`test_approval_decisions`、
  `test_plugin_routes` 共 89 passed。
- 前端/Electron：ApprovalDialog、commands、invoke 共
  124 passed；notify 与 permissionState 相邻组 13 passed。
- 静态门：`tsc --noEmit`、Electron tsconfig、目标 ESLint、
  目标 Ruff、py38 compat、真实 Python 3.8 `py_compile`、
  architecture-check、silent-exceptions、`git diff --check`
  与改动范围 diagnostics 0 项均通过；commands 测试文件按
  ratchet 协议只更新自身 baseline（1166 → 1183）。
- GitHub 证据：PR #2412 的 CI run `39911664679` 与 E2E
  PR Gate run `39911664683` 均 success，随后 squash
  合并为 `main`
  `7634de8fc68e9064007706385ac433ec6c965d96`。
