# R94 运行中插件工具动态选择器规格

- 日期：2026-10-23
- 基线：`main` `1508168e01251298b42eae19f97ce24bec167c81`
- 状态：实施中
- 前置：R90 已把显式启动的进程外插件 tool 发布到聊天
  `ToolRegistry`；R92 已提供 profile 受限通配与 Agent 工具白名单
  文本编辑。R93 为 async bridge 超时异常合同（非插件轮），故本
  插件账续为 R94。

## 1. 背景与问题

R92 已允许在「智能体」页编辑 `tools` 白名单，但用户仍必须记住
并手写完整名 `plugin__<plugin>__<capability>`。插件改名、增删
capability 或工具尚未发布时，文本框不能告诉用户当前实际上有
哪些工具可选。R92 规格明确把「从运行中插件工具动态生成
复选框」延后，因为它需要运行时工具清单接口；R94 补齐这条链。

## 2. 目标

1. 后端提供**桥接权威快照**：只列出已经由 `PluginToolBridge`
   发布到聊天工具面的运行中插件工具，不从 lifecycle 记录或
   manifest 猜测。
2. Agent 编辑页动态展示这些工具的复选框，勾选同步写入完整
   工具名，取消勾选只移除完整名；原文本编辑与 R92 两种插件
   通配继续可用。
3. 若完整名未单独列出、但被 `plugin__*` 或
   `plugin__<plugin>__*` 覆盖，复选框显示为已选且禁用，并提示
   需改通配条目；前端不得假装删除完整名即可撤销通配覆盖。
4. 工具停止、失败、卸载或改名后，重新打开编辑页或点击刷新
   即可看到新快照；已保存但当前未运行的工具名仍保留在文本
   白名单中，不因打开编辑页被自动删除。

## 3. 后端合同

### 3.1 桥接快照

- `PluginTool` 保存 capability 声明的规范化权限（去空、去重、
  保序），以只读 tuple 暴露；权限进入发布 fingerprint，权限
  变化即使映射风险未变也会触发重发布。
- 新增不可变 `PublishedPluginTool` 快照，字段为：
  `plugin_name`、`capability_name`、`tool_name`、`description`、
  `risk`、`permissions`。
- `PluginToolBridge.published_tools()` 在锁内复制记录，按
  `(plugin_name, capability_name, tool_name)` 稳定排序返回；
  既有 `published_tool_names()` 不变。

### 3.2 REST

- `GET /api/v1/plugins/runtime/tools`，路由必须排在
  `GET /api/v1/plugins/{name}` 前，避免被插件详情吞掉。
- 调用前在 executor 中把进程级 host attach/refresh 到其已注入
  bridge（未注入时用进程级 bridge），以修复失败 session 的陈旧发布；该动作**不启动**
  任何插件。
- 响应：`{"tools": [PublishedPluginTool...], "count": <int>}`。
- 继续执行插件 router 既有 Origin 守卫；不返回参数 schema、
  plugin config、invoke 句柄或其他宿主内部对象。

## 4. 前端合同

- `pluginClient.runtimeTools()` 调用上述端点并解包 `tools`。
- `EditAgentForm` 打开时加载一次快照，提供刷新；加载失败只
  显示可重试错误，不影响文本白名单编辑与其它表单字段。
- 纯函数负责勾选状态与同步：
  - 精确名在白名单中：已选，可取消；
  - 未列精确名但被合法插件通配覆盖：已选且禁用；
  - 非法或非插件通配按 R92 一样 fail-closed，不算覆盖；
  - 勾选追加完整名时去重保序，取消时只过滤该完整名。
- 复选框区展示 plugin/capability、完整工具名、描述、风险与
  权限摘要；文本框仍是最终可编辑事实源，保存合同不变。

## 5. 安全边界

- 清单接口是只读的，不 start/stop/invoke 插件，不改 profile，
  不改变权限审批。勾选工具只是把完整名写进用户正在编辑的
  profile 草稿，仍需点保存；实际调用继续 EXECUTE/EXTERNAL
  逐次审批与 profile 三道闸。
- 只列桥接已发布工具：未运行、`input_schema` 不可用、名字
  冲突被 first-wins 跳过或已停机的工具不出现在选择器中。
- 不新增默认 profile 通配，不自动把任何工具加入白名单。
- 通配覆盖状态只做 UI 呈现；执行语义仍以
  `backend/domain/tool_names.py` 的 matcher 为唯一权威。

## 6. 非目标

- 不做「按插件记住放行」、权限规则编辑或自动审批；
- 不做插件 start/stop/restart 控件复制到 Agent 页；
- 不把未运行插件的 manifest tool 伪装成当前可选工具；
- 不支持内置/MCP 工具的动态目录，不改 R92 通配语义；
- 不做 Win7 同步、市场/下载/验签、OS 沙箱或 parked DSH ABI；
  Win7 列继续如实标待对齐。

## 7. 测试与验证

后端：

1. `published_tools()` 排序、身份、description、risk 与权限
   规范化；无可用 schema 的 tool 不进入快照；
2. 权限只改声明不改风险时 fingerprint 变化并重发布；
3. `GET /plugins/runtime/tools` 返回运行中工具且不启动进程，
   stop 后消失；全局路由不被 `/{name}` 吞掉；Origin 守卫与
   既有 runtime 全链不回归。

前端：

1. `pluginClient.runtimeTools()` 请求路径与解包；
2. 覆盖判定只认 R92 两种插件通配，含插件名内 `__` 的文本
   前缀口径；
3. toggle helper 追加/移除、去重保序、通配文本不变；
4. 定向 Vitest、TypeScript 与目标 ESLint。

通用：Ruff、逐文件 py38 hazard scan、`git diff --check`、
改动文件 diagnostics；最终以 PR CI 为权威门禁。

## 8. 撞车与回滚

- 开工时在途 #2354/#2355、#2269 与本轮目标文件零重叠；
  实施期间 main 又合入 P173 #2401 与 P174 #2403，文件面仍与
  本轮零直接重叠，最终基线更新为 `1508168e0` 后再开 PR。
- 回滚只需撤销快照/端点/client/选择器与文档；profile 数据仍是
  普通字符串数组，无数据迁移，R92 文本编辑可独立保留。

## 9. 本地验证（2026-10-23）

- 后端：桥与插件路由定向测试 37 passed；其余插件测试文件
  （host/lifecycle/manifest/CLI/index/scaffold/domain）114 passed。
- 前端：`pluginClient` 与 `EditAgentForm.tools` 定向 Vitest
  18 passed；TypeScript `tsc --noEmit` 与目标 ESLint 通过。
- 通用：目标 Ruff、py38 compat gate 与 3.8 `py_compile`、
  silent-exception ratchet、architecture-check、
  `git diff --check`、改动范围 diagnostics 0 项均通过。
- PR CI 仍是最终权威门禁；本地结果不替代 GitHub 全量检查。
