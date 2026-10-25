# R90：进程外插件 Tool 接入聊天 Agent 的 ToolRegistry

> 日期：2026-10-22
> 状态：实施中
> 分支：`feat/plugin-tools-llm-r90`
> 基线：`origin/main` P142 `ab4f85f8dfdf765679607b8057ccd0021f99e91e`

## 1. 背景与问题

R78--R86 已交付插件 manifest、生命周期记录、进程外宿主、权限确认、配置、
脚手架与离线索引。当前进程外 `tool` capability 在用户显式启动 runtime 后，
只登记到插件域的 `CapabilityRegistry`，可经 REST/设置页/CLI dev 显式调用。

插件总账与开发指南都明确记录了同一边界：进程外插件工具**不会自动暴露给
LLM 的内置 `ToolRegistry`**。因此用户已经安装、确认权限、启用并显式启动
的插件，仍不能在普通聊天中被 Agent 选择和调用；插件生态与聊天主链之间
缺少最后一座桥。

R90 补这条已在总账中明示的缺口。它不重启已 parked 的 DSH ABI/生态兼容，
也不接手他人的 Win7 对齐工作。

## 2. 目标

1. 已启用且由用户显式 `start` 的进程外 Python `tool` capability，可被聊天
   Agent 通过现有 `ToolRegistry` 发现和调用。
2. Agent 在插件 runtime 启动前构建时，后续启动也能动态看到工具；Agent 在
   runtime 已启动后构建时，构造阶段即可同步看到工具。
3. runtime 停止、重启、失败、禁用/卸载/保存配置引发停止时，LLM 工具同步
   注销，不留下可调用的陈旧入口。
4. 插件工具与内置工具命名隔离，永远不能遮蔽或覆盖既有工具。
5. 参数 schema 有明确 manifest 契约；没有可信 schema 的工具保持 API-only，
   不用空 schema 假装可供 LLM 安全调用。
6. 风险与审批语义保守、诚实：调用插件 handler 是执行第三方代码，不因
   manifest 的自报权限而降为纯读。
7. 无插件 runtime 时，现有 94 个内置 LLM schema 的集合与顺序不变。

## 3. 非目标

- 不自动启动插件：后端启动、安装、启用、Agent 构建、工具同步均不拉起
  插件进程；唯一启动入口仍是既有显式 runtime start。
- 不在宿主进程内 import/执行插件代码；只调用 R83 的进程外 JSON-RPC 宿主。
- 不把进程隔离描述成 OS 安全沙箱；插件仍以当前 OS 用户运行。
- 不暴露 `skill`、`hook`、`mcp_server`、`command` capability。
- 不根据 `CapabilityRegistry` 的任意登记自动暴露工具；只有
  `PluginHostManager` 的运行中 session 才能发布 LLM 工具。
- 不做插件市场、网络下载、自动安装、签名验证或信任分级。
- 不做 DSH ABI、Node 边车、声明式 UI 槽位或 Win7 分支同步。
- 不修改 profile 的通配语义；profile 仍须用完整工具名精确放行。

## 4. 已定契约

### 4.1 工具命名

LLM 可见名固定为：

```text
plugin__<plugin_name>__<capability_name>
```

例如示例插件的 `hello_tool` capability 暴露为：

```text
plugin__hello-tool__hello_tool
```

执行时不靠反解析工具名寻找插件；每个工具对象保存精确的 plugin/capability
身份并调用其宿主。桥接层以完整工具名为键跟踪发布记录：

- 与既有注册表工具重名时，第一注册者胜出，插件工具跳过并记 warning；
- 两个 plugin/capability 组合意外拼出同一完整名时，后到者跳过并记 warning；
- 完整名只允许 `[A-Za-z0-9_.-]` 且最长 128 字符；不合规时只跳过该工具的
  LLM 暴露，不影响 CapabilityRegistry/API 调用。

### 4.2 参数 Schema

`PluginCapability` 新增：

```json
"input_schema": {
  "type": "object",
  "properties": {
    "name": {"type": "string", "default": "World"}
  },
  "required": [],
  "additionalProperties": false
}
```

解析优先级：

1. `capabilities[].input_schema`；
2. 若缺失，回退既有 `capabilities[].config_schema`。

回退不是把两个概念永久混为一谈，而是兼容 R86 脚手架和
`examples/plugins/hello-tool`：它们已把 `{"name": ...}` 这类**调用参数**
schema 写在 `config_schema` 中，而生命周期配置 schema 另在 manifest 顶层
`user_config`。R90 起新脚手架和示例改用语义准确的 `input_schema`。

桥接层只接受可归一为 JSON object 的参数 schema：

- 必须是 JSON 可序列化的对象，且序列化大小有上限；
- `type` 缺失且带对象形 `properties` 时补 `type: "object"`；
- `type` 非 `object`、`properties` 非对象、schema 不是对象时跳过 LLM 暴露；
- `required` 只保留字符串项；无效的顶层形态不猜测、不拼凑；
- 缺少 schema 的 capability 继续可由 REST/设置页显式 invoke，但不进入
  `ToolRegistry`。

这样，是否给 LLM 用由 manifest 作者明确提供参数契约来决定；桥接层不会为
任意已启动 handler 猜参数。

### 4.3 风险、并发与审批

第三方 handler 一经调用就会执行任意插件代码；manifest `permissions` 目前
是安装确认/审计声明，不是 OS 强制隔离。因此：

- `PluginTool.risk` 下限为 `RiskClass.EXEC`；
- 权限中出现 network/http/https/url/internet/external 等出站信号时升为
  `RiskClass.EXTERNAL`；
- 不允许以 `file:read` 等自报权限把风险降到 `READ`；
- `concurrency_safe = False`：同一 worker 是 single-flight JSON-RPC；
- `is_blocking = True`：宿主 invoke 是同步等待，须由 Agent 卸载到 executor；
- `requires_tool_context = False`：插件 handler 只收显式 JSON 参数，不向其
  泄露宿主 `ToolContext`；
- 旧权限执行器对 `plugin__*` 统一归类 `ToolCapability.EXECUTE`。结果是：
  `read_only` 拒绝，`workspace_write` 与 `prompt` 逐次审批，`full_access`
  放行；用户已有的 deny/allow/ask 规则仍按既有优先级生效，deny 永远胜出。

显式启动 runtime 表示用户同意运行该插件进程，不等于预先同意 LLM 用任意
参数调用它；逐次审批是 R90 的默认安全姿态。用户可用既有规则显式放行
例如 `plugin__hello-tool__*`。

### 4.4 Profile 与子代理

- 无 profile 白名单时，已发布插件工具与其它注册工具一样可见，但仍受
  上述权限执行器逐次审批。
- 有 `allowed_tools` 的 profile 只做完整名精确匹配；R90 不新增
  `plugin__*` 通配展开，避免插件一启动就越过 profile 边界。
- 子代理的显式只读白名单不加入插件工具。

## 5. 架构

### 5.1 `backend/plugins/tool_bridge.py`

新增桥接模块，包含：

- `plugin_tool_name(plugin_name, capability_name)`：生成命名空间名；
- `resolve_input_schema(capability)` / schema 归一化帮助函数；
- `risk_for_permissions(permissions)`：EXEC 下限与 EXTERNAL 升级；
- `PluginTool(BaseTool)`：保存 plugin/capability/schema/宿主 invoke，执行时
  调用 `host.invoke(...)`，不缓存 worker process 对象；
- `PluginToolBridge`：弱引用跟踪存活 `ToolRegistry`，维护自己发布的工具
  记录，负责 sync、publish、unpublish 与重发布替换；
- `get_plugin_tool_bridge()` 与 `register_plugin_tools(registry)`：生产单例
  与 bundle 接入点。接入时 attach 现有插件宿主单例并同步运行中 session，
  但不启动任何插件。

桥接记录必须记住来源宿主与完整工具名，注销时按精确记录删除，不能用
`plugin__<name>__` 前缀盲删而误伤名称相近的插件。重发布同一 plugin 时先
注销其旧记录再登记新记录，使 restart 后 schema 更新可见。

### 5.2 `PluginHostManager` 通知点

宿主新增可选的 tool bridge 挂点与只读运行状态查询：

- `_register_proxies()` 在 CapabilityRegistry 登记成功后 publish LLM 工具；
- 所有既有 `_unregister()` 路径同时 unpublish LLM 工具；
- `running_tool_capabilities()` 只返回 reconcile 后仍 running 的 session
  capability；发现 FAILED 时沿既有 `_unregister()` 清理；
- 桥接异常不得破坏 runtime start/stop/API invoke 的既有结果，须记录日志
  并降级为“该工具暂不向 LLM 暴露”；
- 隔离测试/CLI dev 可显式注入独立 bridge；生产宿主单例使用生产 bridge。

这保持依赖方向：宿主只发通知，工具对象与注册表 fan-out 都留在桥接模块。

### 5.3 Tool bundle 接入

`backend/tools/tool_bundles.py` 新增 `plugins` 动态 bundle：

- 放在 `mcp` 之后，与另一类外部动态工具相邻；
- `critical=False`，桥接失败不拖垮内置工具装配；
- 没有 running plugin 时注册 0 个工具，静态 schema 基线不变；
- bundle 注册时把当前 `ToolRegistry` 交给 bridge 弱引用跟踪，并同步已
  running 的插件工具；
- R84 harness 文件导出与 `mcp` 一样排除这个动态 bundle，避免把当前进程
  临时运行的第三方 schema 烘焙进静态 harness/lock 基线。

更新 bundle 名单/数量的既有硬编码测试，但不改静态工具名清单。

### 5.4 清单、脚手架与示例

- `backend/plugins/manifest.py`：`PluginCapability.input_schema`；
- `backend/plugins/scaffold_templates.py`：tool 模板改用 `input_schema`；
- `examples/plugins/hello-tool/plugin.json`：改用 `input_schema`；
- 前端 manifest 类型与设置页模板同步展示 `input_schema`，生成 README
  说明启动后出现的 `plugin__...` 工具名；
- `plugins/index.json`：用现有 CLI 重建，避免索引内嵌 manifest 漂移。

旧 manifest 只有 `config_schema` 时仍可按第 4.2 节兼容，不要求插件作者
立即迁移。

## 6. 生命周期同步表

| 事件 | CapabilityRegistry（既有） | ToolRegistry（R90） |
|---|---|---|
| 安装记录 | 不登记、不执行 | 不暴露 |
| 启用记录 | 不登记、不执行 | 不暴露 |
| 显式 start 成功 | 登记进程外 proxy | publish 到全部存活 registry |
| Agent 在 start 后构建 | 已有 proxy | bundle sync 时登记 |
| restart | 先注销旧 proxy 再登记新 proxy | 先 unpublish 再 publish 新 schema |
| stop / shutdown | 注销 proxy | 精确注销该 plugin 的工具 |
| 保存配置/禁用/卸载（路由先停 runtime） | 注销 proxy | 随 stop 注销 |
| status/invoke 发现 FAILED | 注销 proxy | 随 `_unregister()` 注销 |
| start 失败回滚 | `_unregister()` | 不得残留工具 |
| schema 缺失或无效 | 仍登记 proxy，可 API invoke | 跳过并记录原因 |

后端重启后 runtime session 不存在，因此不会仅凭 enabled DB 记录恢复 LLM
工具；用户必须再次显式 start，沿用 R83 的安全契约。

## 7. 执行与错误语义

`PluginTool.execute(**kwargs)` 将 kwargs 原样作为一个 JSON object 交给
`PluginHostManager.invoke(plugin_name, capability_name, kwargs)`：

- 不注入 workspace、配置值、环境变量或 `ToolContext`；
- 生命周期配置仍只走既有 worker `configure(config)` 通道；
- 字符串结果原样返回，其他 JSON 结果按 JSON 文本返回给 ToolRegistry；
- 宿主未运行、超时、崩溃、协议错误等异常不伪造成成功，交给现有
  ToolRegistry 错误通道；若 session 已转 FAILED，宿主既有清理会同步注销；
- 工具对象不自动 restart/reconnect 插件进程。

描述统一带 `[Plugin:<plugin_name>]` 前缀并设长度上限，避免插件元数据
无限占用 LLM 上下文。每插件发布数量设上限，超出部分跳过并记 warning。

## 8. 测试计划

新增以 fake host 为主、真实子进程为辅的桥接测试，至少覆盖：

1. `input_schema` 生成正确 namespaced schema；`config_schema` 回退；
   两者同时存在时 `input_schema` 胜出。
2. schema 缺失、非 object、不可序列化或超限时跳过，且不影响其它工具。
3. 风险下限 EXEC、network 权限升 EXTERNAL；`concurrency_safe=False`、
   `is_blocking=True`。
4. execute 精确转发 plugin/capability/arguments，并保持 JSON 结果语义。
5. sync 只登记 running capability，绝不调用 host.start；publish 能 fan-out
   到已跟踪 registry；unpublish 精确删除；republish 替换旧 schema。
6. 与内置/既有工具同名时第一注册者胜出；跨插件拼接同名时后到者跳过。
7. profile 精确白名单：列入完整插件工具名才可见，未列入不可见。
8. 真实进程外集成：start 后工具出现并可经 ToolRegistry 调用，stop 后
   消失；失败路径不残留。
9. bundle：无插件时静态 schema 集合/顺序不变，bundle 名单新增 `plugins`。
10. 权限：`plugin__*` 在 read_only 拒绝、workspace_write/prompt 审批、
    full_access 放行，用户 deny/allow 规则优先级不变。
11. manifest round-trip、脚手架生成物、示例与离线索引一致性。

验证命令按仓库规则先跑新增/定向用例，再跑插件全集、tool bundle/parity、
权限与 Agent 相关集，最后做 diagnostics 与全仓收集；以实际 CI 为最终门。

## 9. 文档更新

- `docs/user-manual/21-plugin-development.md`：删除“不会自动暴露”的旧
  边界，补 `input_schema`、命名、审批、profile 与动态注销说明；
- `docs/technical/97-plugin-manifest.md`：现行契约头注加入 R90；
- `docs/plans/plugin-evo-index.md`：增加 R90 总账并修正 R83/R86 的旧边界
  表述；win7 列保持“待对齐”，不冒称完成。

## 10. 验收标准

- 用户显式启动带 `input_schema` 的进程外 tool 后，现有与新建 Agent 都能
  在下一轮 schema 获取时看到 `plugin__...` 工具；经权限审批后可调用并
  得到真实子进程结果。
- 停止、重启、失败、禁用/卸载/配置保存后，工具在全部存活 registry 中
  消失或被新版本替换，无陈旧可调用入口。
- 未启动 runtime、仅 install/enable、后端重启后未再 start 时，LLM 看不到
  插件工具，后台也不产生插件进程。
- 无有效参数 schema 的工具不向 LLM 暴露，但原 REST/设置页 invoke 不回归。
- 插件工具不能覆盖内置工具；冲突有日志且第一注册者保持不变。
- 无插件运行时静态工具面与基线完全一致；插件、bundle、权限、索引测试
  与 CI 全绿（仓库既有且与本轮无关的失败须单独如实报告，不弱化门禁）。

## 11. 风险与后续

- 逐次审批会增加交互次数，但这是任意第三方代码进入 LLM 主链的必要默认；
  后续可基于真实使用数据评估“按插件记住放行”的 UX，不能在 R90 静默放行。
- schema 只是调用契约，不验证 handler 的真实副作用；文档必须继续强调
  “审阅代码、非沙箱”。
- profile 尚不支持插件通配或 UI 动态勾选；这需要单独的 profile/UX 设计，
  不与本桥接捆绑。
- 若未来引入真正 OS 沙箱或可信签名，才有资格重新讨论风险下限与默认审批。
