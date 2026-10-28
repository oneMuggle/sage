# 插件化与自进化总账（plugin-evo）

> 本账本管理"插件怎么装、怎么改"，与两本既有账并列且互不覆盖：
> - [`parity-rounds-index.md`](./parity-rounds-index.md) —— 编码代理能力对标（至 R77）
> - [`dsh-opt-index.md`](./dsh-opt-index.md) —— dsh 运行时机制对标（R1–R32）
> - **本账** —— 插件装配与 harness 级自进化（R78 起）
>
> 方案总纲：`docs/mcp-pluginization-self-evolution-plan-20261021.md`
> 兼容取舍：`docs/mcp-dsh-plugin-adoption-decision-20261021.md`（学机制，不接生态）

## 1. 路线

| 轮次 | 主题 | 状态 |
| --- | --- | --- |
| R78 | 契约 + 内核骨架（EffectScope / EventBus / ServiceRegistry / Fiber） | ✅ #2206 |
| R79 | hook 生命周期收编：`KernelHookProvider` + `fire_hooks` 开关 + 双跑对照 | ✅ #2206 |
| R80 | tool 收编：硬编码装配改为 bundle 注册 + 权限 → RiskClass | ✅ #2206 |
| R81 | 三层配置 + 四预设 + `--dump-config` | ✅ #2206 |
| R82 | 插件 UI / REST（安装、启停、权限确认、日志） | ✅ #2206 |
| R83 | 进程外宿主（含 DSH 边车，仅在触发条件满足时） | ✅ #2206 |
| R84 | harness 文件化 + lock + 差异视图 | ✅ #2206 |
| R85 | 提案引擎（Propose–Probe–Compose + 证据锚定） | ✅ #2206 |
| R86 | 生态（脚手架 / 索引 / 贡献指南） | ✅ #2206 |
| R90 | 进程外插件 tool → 聊天 `ToolRegistry` 桥 | ✅ #2327 |
| R92 | 插件工具 profile 受限通配 + Agent 工具白名单编辑 | ✅ #2360 |
| R94 | 运行中插件工具动态选择器 | ✅ #2407 |
| R95 | 插件工具按插件记住审批决定 | ✅ #2412 |
| R96 | 插件权限规则结构化身份匹配 | ✅ #2413 |
| R97 | 已记住权限规则管理（查看/删除） | ✅ #2418 |
| R98 | 插件 profile 白名单结构化身份匹配 | ✅ #2440 |
| R99 | 已保存权限规则写入完整性（记住去重 + 按内容删除） | ✅ #2452 |
| R100 | 已保存权限规则一键清空（撤销全部持久信任） | ✅ #2474 |
| R101 | 已保存权限规则插件归属标注（孤儿规则可见化） | ✅ #2484 |
| R102 | 按插件删除其全部已保存规则（按归属撤销持久信任） | ✅ #2493 |
| R103 | 已卸载插件孤儿规则在插件页提示并可就地清理（纯前端复用 R101/R102） | ✅ #2500 |
| R104 | 无归属（missing）孤儿规则整组清理（标注矩阵补完） | ✅ #2504 |
| R105 | 仅本次会话记住（session 级 remember，会话规则存储 + gate 会话捕获） | ✅ #2511 |
| R106 | 会话级规则查看与撤销（聊天顶栏就地管理） | ✅ #2530 |
| R107 | Agent 白名单未发布插件条目标注与就地移除（纯前端） | ✅ #2545 |
| R108 | 审批弹窗插件归属可见化（决策时刻横幅 + OS 通知归属，纯前端） | ✅ #2552 |
| R109 | 已保存权限规则遮蔽标注（被更高优先级规则覆盖的行可见化，纯前端） | ✅ #2557 |
| R110 | 聊天顶栏弹层标注补齐（审计插件归属 + 会话规则遮蔽，纯前端） | ✅ #2566 |
| R111 | 聊天历史工具调用插件归属标注（转录通用卡片，纯前端） | ✅ #2576 |
| R112 | PermissionModeSwitch 供数与导出收口（共享名单 hook + format 下沉，纯前端） | ✅ #2585 |
| R113 | 转录工具组折叠头插件归属（纯前端） | ✅ #2589 |
| R114 | 编排任务树实时行（等待审批徽章+事件行）插件归属（纯前端） | ✅ #2614 |
| R115 | Hook 执行历史行插件归属（纯前端） | ✅ #2618 |
| R116 | PluginsTab 纯数据/纯函数抽离 pluginsTabModel（纯重构） | ✅ #2621 |
| R117 | Message 审计辅助抽离 messageAudit（纯重构，清 react-refresh 警告） | 🔄 #2623 |

## 2. 交付总账

| 轮 | 交付内容 | main PR | win7 PR | 状态 |
| --- | --- | --- | --- | --- |
| R78 | `domain/plugin.py`、`ports/plugin.py`、`application/kernel/{effects,events,services,fiber,cordis_names}.py` + 5 个单测文件 | #2206 | 待对齐 | ✅ 已交付 |
| R79 | `hooks/kernel_provider.py`（provider + `fire_hooks` 开关）+ 30 例单测（含 11 组双跑对照） | #2206 | 待对齐 | ✅ 已交付 |
| R80 | `application/kernel/tool_install.py`（127 行机制）+ `tools/tool_bundles.py`（31 个 bundle / 94 个工具）+ 39 例单测 | #2206 | 待对齐 | ✅ 已交付 |
| R81 | `application/kernel/harness_config.py`（546 行）+ `backend/cli/harness.py`（215 行）+ 删除 legacy/旧开关 + 55 例单测 | #2206 | 待对齐 | ✅ 已交付 |
| R82 | `api/plugin_routes.py` + lifecycle manifest/events 补强 + `pluginClient.ts` / `PluginsTab.tsx` + 后端 59 例相关测试、前端 16 例新增测试 | #2206 | 待对齐 | ✅ 已交付 |
| R83 | `plugins/{host,host_process,host_worker}.py` + runtime REST/审计 + `PluginRuntimePanel.tsx` + 后端 111 例相关测试、前端 19 例定向测试 | #2206 | 待对齐 | ✅ 已交付 |
| R84 | `application/kernel/{harness_files,harness_snapshots}.py` + `cli/harness_export.py` + `files` CLI + 启动 lock gate + 14 例新增单测 | #2206 | 待对齐 | ✅ 已交付 |
| R85 | `application/kernel/{harness_evidence,harness_proposals,harness_proposal_engine}.py` + SkillDraft 审批桥 + `proposals` CLI + 17 例新增测试 | #2206 | 待对齐 | ✅ 已交付 |
| R86 | `plugins/{scaffold_templates,scaffold,index_catalog}.py` + `cli/plugin.py` + hello-tool 示例/静态索引/开发指南 + 25 例新增测试 | #2206 | 待对齐 | ✅ 已交付 |
| R90 | `plugins/tool_bridge.py` + host publish/unpublish 通知与 running 查询 + `plugins` tool bundle + `input_schema` 契约/权限门/桥接测试与文档 | #2327 | 待对齐 | ✅ 已交付 |
| R92 | `domain/tool_names.py` 共享 matcher 与前缀单一来源 + registry/agent 三道闸统一 + 启动期校验识别插件引用 + `EditAgentForm` 工具白名单编辑与测试/文档 | #2360 | 待对齐 | ✅ 已交付 |
| R94 | `PluginToolBridge.published_tools()` 权威快照 + `GET /plugins/runtime/tools` + `pluginClient.runtimeTools()` + Agent 运行中插件工具动态复选框与测试/文档 | #2407 | 待对齐 | ✅ 已交付 |
| R95 | 审批请求权威 `plugin_name` + `remember_scope=tool|plugin` + 后端派生受限插件规则 + ApprovalDialog 范围选择与 Electron 透传/测试/文档 | #2412 | 待对齐 | ✅ 已交付 |
| R96 | `PermissionRule`/`PermissionEnforcer` 权威 `plugin_name` 结构化匹配 + agent/adapter 身份透传与测试/文档 | #2413 | 待对齐 | ✅ 已交付 |
| R97 | `GET /permissions/rules` + 删除端点 + Electron 命令 + 设置页已记住规则列表/删除与测试/文档 | #2418 | 待对齐 | ✅ 已交付 |
| R98 | `tool_name_in_allowlist` 权威 `plugin_name` 结构化匹配 + registry/agent 三道闸与前端覆盖镜像透传与测试/文档 | #2440 | 待对齐 | ✅ 已交付 |
| R99 | remember 追加去重 + 删除端点按内容定位 + Electron/设置页传参切换与测试/文档 | #2452 | 待对齐 | ✅ 已交付 |
| R100 | `POST /permissions/rules/clear` + Electron 命令 + 设置页全部删除（确认后）与测试/文档 | #2474 | 待对齐 | ✅ 已交付 |
| R101 | 规则列表响应只读归属标注（plugin_name/plugin_status）+ 设置页孤儿规则徽标与测试/文档 | #2484 | 待对齐 | ✅ 已交付 |
| R102 | `POST /permissions/rules/delete-by-plugin`（权威插件名选择子）+ Electron 命令 + 设置页按归属删除与测试/文档 | #2493 | 待对齐 | ✅ 已交付 |
| R103 | 插件页已卸载卡片的孤儿规则计数提示 + 就地按归属清理按钮（纯前端）与测试/文档 | #2500 | 待对齐 | ✅ 已交付 |
| R104 | `POST /permissions/rules/delete-orphans`（服务端按 missing 类选集）+ Electron 命令 + 管理器孤儿清理行与测试/文档 | #2504 | 待对齐 | ✅ 已交付 |
| R105 | 会话规则存储（进程内）+ enforcer 合并求值 + 应答 `remember_duration` + 对话框时长选择与测试/文档 | #2511 | 待对齐 | ✅ 已交付 |
| R106 | 会话规则按会话读/删/清端点 + 顶栏徽记与审计弹层会话规则区与测试/文档 | #2530 | 待对齐 | ✅ 已交付 |
| R107 | EditAgentForm 未发布插件条目分类标注（发布快照+生命周期名单前端镜像 R101）+ 就地移除与测试/文档 | #2545 | 待对齐 | ✅ 已交付 |
| R108 | ApprovalDialog 所属插件横幅 + OS 通知归属后缀（复用 R95 权威 plugin_name）与测试/文档 | #2552 | 待对齐 | ✅ 已交付 |
| R109 | PermissionRulesManager 遮蔽派生（等值/插件通配覆盖）+ 徽标与测试/文档 | #2557 | 待对齐 | ✅ 已交付 |
| R110 | permissionInsights 共享派生下沉 + PermissionModeSwitch 审计归属后缀/会话规则遮蔽徽标与测试/文档 | #2566 | 待对齐 | ✅ 已交付 |
| R111 | usePluginNames 共享名单缓存 + Message 通用卡片归属后缀与测试/文档 | #2576 | 待对齐 | ✅ 已交付 |
| R112 | 弹层改用 usePluginNames + formatPermissionMode* 下沉 permissionInsights 与测试/文档 | #2585 | 待对齐 | ✅ 已交付 |
| R113 | Message 工具组组头归属后缀与测试/文档 | #2589 | 待对齐 | ✅ 已交付 |
| R114 | TaskTreeSection 归属后缀（门控供数）与测试/文档 | #2614 | 待对齐 | ✅ 已交付 |
| R115 | HookHistoryPanel 归属后缀（门控供数）与测试/文档 | #2618 | 待对齐 | ✅ 已交付 |
| R116 | pluginsTabModel 新模块 + PluginsTab 改导入与文档 | #2621 | 待对齐 | ✅ 已交付 |
| R117 | messageAudit 新模块 + Message 删尾与测试改导入、文档 | #2623 | 待对齐 | 🔄 |

## 3. R78 交付边界

- **纯新增**：未改动任何存量模块，`backend/hooks` / `backend/tools` / `backend/plugins` 原样不动。
- **零行为变更**：内核只被自身单测引用，生产路径尚未 import。
- **不引第三方**：仅标准库；不引入 Cordis（TS 或 Python 移植）。
- **不接生态**：`cordis_names.py` 只是只读映射常量，供将来桥接时复用。

## 4. R79 交付边界

- **零调用点改动**：14 处 `load_hooks()` + `run_event_hooks()` 原样保留，迁移随 R80 同批进行
  （`legacy_routes.py` 正在被 C 系列拆分，此刻改动必然冲突）。
- **行为等价有证据**：`test_hooks_kernel_provider.py::TestParity` 用 10 组钩子配置 +
  重载后场景，逐字段比对 `HookOutcome`（decision / updated_input / reason / messages /
  additional_context / severity）。
- **开关默认关闭**：`SAGE_KERNEL_HOOKS` 未设置时 `fire_hooks` 走旧路径，逐字节等价。
- **依赖单向**：provider 放在 `backend/hooks/`，由 hooks 侧依赖内核，内核不认识 hooks。
- **卸载可验证**：服务注册走 `EffectScope`，`test_stop_clears_hooks_and_service`
  直接断言卸载后 `host.services.get("hooks") is None`。

## 5. R80 交付边界

- **装配结构变了，装出来的东西没变**：94 个工具的名字、顺序、`declared_risks`、
  `get_schemas_for_llm` 产物由 `test_tool_bundles_parity.py` 在 3 档网络策略 × 2 条路径上
  逐项比对；实测 legacy 0.26s / bundle 0.02s，三者全等。
- **开关默认关**：`SAGE_KERNEL_TOOL_BUNDLES` 未设置时 `register_all_tools` 走
  `_register_all_tools_legacy`，逐字节等价。旧实现当时整体保留为私有函数，R81 已删除。
- **权限模型零改动**：`RiskClass` 与 `PermissionEnforcer` 早已数据驱动，本轮只动装配，
  避免把「结构重构」与「权限语义」两件事混在一个 PR 里。
- **依赖单向**：`backend.tools` → `backend.application.kernel`，内核不认识任何具体工具；
  机制（顺序/门控/失败策略/报告）与声明（31 个 bundle 清单）分文件承载。
- **一个实测陷阱已固化**：Windows 上 `ssl.create_default_context()` 每次约 2s，9 个出网
  工具让一次装配要 18.5s；测试用共享 SSLContext 降到 0.26s —— 只去掉与等价性无关的 IO。

## 6. R81 交付边界

- **无配置即标准形态**：没有任何 `harness.yaml` 时固定 `standard`，ONLINE 94 个工具
  的名字/顺序由黄金快照逐项钉死；这同时是回滚方式——删掉配置文件即回到默认。
- **三层优先级可导出**：`builtin` < `~/.sage/harness.yaml` <
  `<workspace>/.sage/harness.yaml` < `SAGE_HARNESS_PRESET` < patch；解析结果带
  `sources` 与每个 bundle 的 skipped reason，`dump-config` 可直接定位覆盖来源。
- **四预设只删不重排**：`standard` 94、`focus` 53、`headless` 93、`dev` 94（ONLINE），
  所有子集都保持 `BUNDLES` 声明顺序；bundle 级开关可在预设基线上再打开或关闭一项。
- **flags 只做声明与导出**：`context` / `interactive` / `dev` 已进入 resolved config，
  但上下文压缩、无交互审批与热重载的行为接入不在本轮冒充完成，随 R82+ 落地。
- **坏配置分两档处理**：生产加载 fail-open（warning 后忽略坏层），`cli check` strict
  时以退出码 1 明确失败；自定义 bundle 插入需要代码装载能力，本轮不做。
- **legacy 已收口**：`register_all_tools` 只剩 bundle 一条路径，旧 env 开关同步删除；
  55 例新增/改写单测与 32 例既有相关单测在本地通过，ruff 与 architecture-check 全绿。

## 7. R82 交付边界

- **只管理生命周期记录**：`install_path` 仅落库，不读目录、不导入、不执行插件代码；
  “已启用”在 UI 中明确标为记录状态，代码加载/进程外托管仍是 R83。
- **权限确认后端强制**：manifest 任一能力声明 permissions 且未提交
  `confirm_permissions: true` 时，REST 返回 409 并附扁平权限与按能力分组，
  且数据库不写入记录；设置页只是展示和勾选入口，不能绕过后端。
- **存量 DB 无痛迁移**：旧 `plugins` 表自动补 `manifest` 列，旧记录回退 `{}`；
  新增 `plugin_events` 记录 installed/enabled/disabled/uninstalled/restored/
  config_updated，事件写失败只记 warning，不反噬主操作。
- **安全面同既有高权限路由**：全部插件端点先过 Origin 守卫；错误映射固定为
  404/409/422，全局 `/plugins/logs` 声明在 `/{name}` 前避免被吞。
- **Electron 链路补齐类型化错误**：主进程 relay 对非 2xx 只透传原始 body，
  `pluginClient` 将 409 JSON 还原为确认载荷，UI 按后端权威分组逐项展示。未知权限
  只回退原文，不猜一个更弱的人话标签。
- **本地证据**：后端 59 例相关测试、前端新增 16 例测试与既有设置搜索 12 例通过；
  ruff、tsc、eslint、vite build、architecture-check 全绿（`backend/main.py` 仅 +3 行，
  基线按 ratchet 从 1272 调整到 1275）。

## 8. R83 交付边界

- **默认拒绝自动执行**：install/enable/后端重启都不会拉起插件进程；runtime 只能由
  已认证本地用户显式 start，且仅 `enabled` 记录可启动。后端重启后 runtime 统一
  回到 `pending`，不做跨重启恢复。
- **第一垂直切片只托管 tool**：只加载 manifest 中带 entry_point 的 tool 能力，
  支持 `module:attr`、兼容点路径与模块约定入口，并把进程外代理注册到既有
  `CapabilityRegistry`。本轮不自动暴露给 LLM `ToolRegistry`（这一缺口由
  R90 补齐），也不执行 skill/hook/mcp_server/command。
- **崩溃隔离不是安全沙箱**：worker 是同 OS 用户下的独立 Python 子进程，
  以 stdio JSON-RPC 通信，使用 cwd/env 白名单、1 MiB 消息上限、启动/调用/关闭
  超时与有界 stderr；Windows 优先 Job Object 512 MiB 内存上限，POSIX 在导入
  插件前设置 memory/CPU rlimit。manifest 权限仍是安装确认语义，不宣称内核级
  文件/网络强制。
- **停机联动完整**：disable、uninstall、配置更新都会先停 worker；普通工具异常
  不杀进程，超时/崩溃/协议损坏进入 `failed` 并注销代理，宿主不自动重启。
  FastAPI shutdown 统一停止全部 worker；runtime start/stop/restart/invoke 均写
  `plugin_events` 审计，事件不记录 arguments/config 内容。
- **DSH 边车未触发，不扩围**：T1–T4 触发条件均无新证据满足，本轮不做 Node
  边车、cordis-shim 或 Cordis ABI 兼容；完整设计与残余风险见
  `2026-10-21_out-of-process-plugin-host-r83.md`。
- **本地证据**：后端相关 111 例、前端定向 19 例通过；ruff、py38 兼容、静默异常
  ratchet、tsc、eslint、vite build、architecture-check 全绿。`backend/main.py`
  仅 +8 行 lifespan shutdown 接线，基线按 ratchet 从 1275 调整到 1283。

## 9. R84 交付边界

- **无 lock 即旧行为**：没有 `harness/harness.lock.json` 时，工具装配与后端启动
  与 R83 相同；显式 `files export` 后才算采用。采用根的 lock 在 FastAPI DB
  初始化前校验，漂移时拒绝启动；`SAGE_HARNESS_LOCK_ENFORCE=0` 只作紧急恢复。
- **八面先物化，只接一个新运行时输入**：system、guardrails、memory、
  tool guidance、subagents、skills、scripts、plugins 共 23 份基线文件可
  diff / snapshot / rollback；只有 `plugins.yaml` 的 `harness_config` 段
  进入 R81 合并链，其余是只读投影，不冒充已替换原生加载器。subagents/skills
  继续使用原有文件根，harness 副本不新增第二个加载优先级。
- **差异视图首期是 CLI 契约**：`status` 给 lock 计数，`diff --patch` 给相对
  snapshot 的 unified diff，JSON 形态稳定供 R85 提案审批复用；本轮不新增可
  读取任意本地路径的 REST/UI。snapshot 放在根内 `.snapshots/` 并由生成的
  `.gitignore` 排除，rollback 默认先保存回滚前状态。
- **lock 是漂移可见性，不是签名**：每文件 SHA-256 + 清单内容摘要能发现未
  审查改动、缺失与未跟踪托管文件；能同时改文件和 lock 的本地写者不在本轮
  信任模型内。`proposals/**`、`evidence/**` 仅 README 受管，其余为 R85 预留。
- **导出不触发外部发现、不复制秘密**：tool guidance 排除会发现外部服务器的
  `mcp` bundle，只枚举内置 schema/risk；不导出记忆正文、settings 密钥、
  skill 附带脚本或二进制。完整设计见
  `2026-10-21_harness-files-lock-diff-r84.md`。
- **本地证据**：新增 14 例单测中 13 passed、1 skipped（Windows 无 symlink
  权限）；harness 相关全集 42 passed/1 skipped，tool parity/risk/lifespan
  64 passed；ruff、py38 兼容、静默异常 ratchet、architecture-check 全绿。

## 10. R85 交付边界

- **只离线提案，不改 chat 热路径**：候选由 JSON 导入或 CLI 显式调用既有
  ReviewService provider 生成 invariant/domain 两 lane；生成、Probe、
  Compose、submit 都不改托管 harness，在线自动采纳仍默认关闭。
- **无轨迹证据与指标退化双硬门**：每条 edit 必须引用 session/message/
  tool trajectory/LLM replay 中至少一份内容哈希锚定的摘录；离线 Probe
  必须逐 edit 标记 supported，且任一共享行为指标退化即淘汰整个 candidate。
  Compose 对同结果合并、对冲突按分数选一、平分冲突丢弃，无入选即
  `compose_failed`。
- **仍用既有人工审批面**：pending 提案镜像为 `SkillDraft` 的
  `harness_proposal` 待审项，详情直接带 evidence、Probe 摘要与 unified
  diff。UI 批准的语义是最终“批准并采纳”，CLI 则拆为 `approve` 后
  `adopt` 两步；普通技能草稿批准写 `SKILL.md` 的路径不变。
- **Probe 诚实分层**：内置 `--static` 只把 candidate 物化到隔离根并做
  lock/YAML/JSON/plugins strict/SKILL.md 静态校验，不执行候选脚本；
  行为指标来自外部离线 replay/shadow 报告契约。仓库内尚无通用同任务
  shadow runner，本轮不冒充已实现在线影子执行。
- **采纳可回滚、漂移不猜合并**：提案锚定 base lock 与逐文件 hash；批准/
  采纳时漂移进入 stale/拒绝。采纳前创建 R84 `pre-proposal-*` snapshot，
  应用后刷新 lock；提案 rollback 默认要求当前仍是采纳后 lock，后续漂移
  必须显式 `--force`。完整设计见
  `2026-10-21_harness-proposal-engine-r85.md`。
- **本地证据**：新增 17 例测试；R85 定向（含既有审批 API）34 passed，
  R84/draft/review/harness CLI 回归 77 passed/1 skipped；ruff 与
  architecture-check 全绿。

## 11. R86 交付边界

- **30 分钟路径以真实宿主收口**：`plugin init -> validate -> dev -> index
  build/validate/search` 全走现有 manifest、R82 lifecycle 与 R83 进程外宿主；
  `dev` 用临时生命周期库做一次显式 invoke 后停机，不改应用数据库，也不提供
  watch/hot-reload。
- **只有 tool 标为已托管**：脚手架提供 tool/hook/mcp/skill 四模板；tool 标记
  supported，其余三类标记 preview 并由校验器给出 `RUNTIME_PREVIEW_ONLY`。
  进程外 tool 仍只注册到 `CapabilityRegistry`，不自动暴露给 LLM
  `ToolRegistry`（这一边界由 R90 改变）。仓库尚无 UI capability 与前端
  插件加载器，本轮不生成不可运行的 `npm create`/TS widget 假模板。
- **静态索引只做目录，不做市场**：`plugins/index.json` 可离线 build、
  validate 与 search，登记 git/archive/local 来源、兼容矩阵与可选签名元数据；
  不下载、不安装、不验签，也不建立信任根。没有 Win7 实测的条目固定
  `win7=unknown`。
- **生成物可独立维护**：插件包只依赖 Python 标准库并兼容 3.8，脚手架默认
  拒绝覆盖既有文件，`--force` 不删除额外文件；包校验只做 AST 静态解析，
  不导入插件代码。权限仍是安装确认与审计语义，不是 OS 沙箱。
- **贡献面分三层**：L1 内容走 skill/prompt/harness 校验，L2 插件走本轮
  CLI 闭环，L3 新 capability/provider/宿主语义继续 spec 先行与评审；
  仓库内 hello-tool 示例与种子索引由 backend CI 显式校验。
- **本地证据**：新增 25 例生态测试、四模板自带 7 例测试、插件相关全集
  126 passed；ruff、py38 hazard scan、diagnostics 与 architecture-check
  全绿。完整设计见 `2026-10-21_plugin-ecosystem-r86.md`。

## 12. R90 交付边界

- **只发布运行中且有参数契约的 tool**：install/enable/后端重启都不会让
  插件工具进入聊天；只有用户显式 start 的 R83 session，且 capability
  提供 object 形 `input_schema`（或 R86 兼容的 `config_schema` 参数
  schema）时才发布。无 schema 的 tool 保持 REST/设置页 API-only。
- **动态同步有精确所有权**：工具名为
  `plugin__<plugin>__<capability>`，桥接以弱引用 fan-out 到存活
  `ToolRegistry`；stop、restart、failed、保存配置/禁用/卸载引发停机时按
  桥接自己的发布记录精确注销。第一注册者胜出，插件不能覆盖内置工具。
- **风险不靠自报降级**：`PluginTool` 的 `RiskClass` 下限为 EXEC，
  network/external 信号升 EXTERNAL；旧权限执行器把 `plugin__*` 归为
  EXECUTE，默认逐次审批、`read_only` 拒绝。工具声明
  `concurrency_safe=False`、`is_blocking=True`，且不接收宿主 ToolContext。
- **profile 在 R90 是精确白名单**：R90 不展开 `plugin__*` 通配（该
  限制由 R92 受限放宽，见 §13），不把插件
  工具塞进子代理只读面；无插件 runtime 时 94 个静态 schema 的集合与顺序
  不变。R84 harness 静态导出排除 `plugins` 动态 bundle，不把临时 runtime
  schema 写入 lock。完整的参数归一化、冲突与验收标准见
  `2026-10-22_plugin-tools-llm-r90.md`。
- **不扩围**：仍非 OS 沙箱，不自动启动、不做市场/下载/验签，不启动
  parked 的 DSH ABI/Node 边车；Win7 继续标“待对齐”，等待既有同步链路，
  本账不冒称完成。

## 13. R92 交付边界

> R91 是 Windows `skills_dir` 路径语义修复（非插件轮次，见
> `2026-10-22_r91-windows-skills-dir-path-semantics.md`），故本账由
> R90 直接续 R92。

- **只承认两种插件通配**：profile `tools` 中 `plugin__*`（全部插件）与
  `plugin__<plugin>__*`（单个插件全部 capability）会被展开；普通条目
  仍精确匹配，`*`、`memory_*`、`plugin__demo*` 等其它写法不通配、
  fail-closed。三道闸（registry schema 过滤、agent 并行预检、agent
  执行边界）共用 `domain/tool_names.py` 的单一 matcher，`plugin__`
  前缀也收敛为 domain 单一来源。
- **通配只决定可见性**：插件仍须用户显式 start 才发布，调用仍按
  EXECUTE/EXTERNAL 逐次审批，权限规则不变；通配会让插件将来新增的
  capability 自动对该 Agent 可见，最小权限场景应继续写完整精确名。
  默认种子 profile 不新增任何插件通配。
- **配置入口补齐**：Agent 管理页可直接编辑工具白名单（文本形式，
  保存时去重）；启动期 `validate_profile_tools` 对合法插件精确名与
  通配不再误告警，无效写法仍告警。完整语义与验收见
  `2026-10-22_plugin-profile-wildcard-r92.md`。
- **不扩围**：不做通用 glob、不做运行中工具动态复选框、不做「按插件
  记住放行」；动态复选框留给后续运行中工具清单接口，Win7 继续标
  “待对齐”。

## 14. R94 交付边界

> R93 是 async bridge 超时异常合同（非插件轮次），故本账由 R92
> 续 R94。

- **清单以桥接发布面为准**：`GET /api/v1/plugins/runtime/tools`
  只返回 `PluginToolBridge` 已向聊天发布的工具，字段为插件名、
  capability 名、完整工具名、描述、派生风险与规范化声明权限。
  读取前只 attach/refresh 已运行 session，不启动插件；未运行、
  无可用 schema 或冲突落败的工具不出现在选择器里。
- **动态复选框不发明新权限语义**：Agent 编辑页勾选只把完整名
  写进现有 `tools` 文本草稿，保存后才对 profile 生效，调用仍走
  逐次审批。被 R92 的 `plugin__*` / `plugin__<plugin>__*` 覆盖
  但未单独列名的工具显示为已选且禁用，取消须改通配条目；刷新
  快照不会删除已保存的未运行工具名或通配条目。
- **权限快照不陈旧**：`PluginTool` 保留去空、去重、保序的声明
  权限，权限进入发布 fingerprint；同风险下只改权限也会重发布，
  选择器不会继续展示旧权限摘要。
- **不扩围**：不自动启动、不做「按插件记住放行」、通用 glob、
  内置/MCP 工具动态目录或其它 capability 托管；Win7 继续标
  “待对齐”。完整语义与验收见
  `2026-10-23_plugin-runtime-tool-picker-r94.md`。
- **本地证据**：桥/路由 37 例与其余插件文件 114 例通过，前端
  定向 18 例通过；Ruff、py38、tsc、ESLint、静默异常 ratchet、
  architecture-check、diff-check 与 diagnostics 全绿；PR #2407
  GitHub CI attempt 2 与 E2E PR Gate 全绿，已 squash 合并为
  `main` `6e8f626696879d3ad826ddf88a7c0e506612f847`。

## 15. R95 交付边界

> spec：`2026-10-23_plugin-approval-remember-r95.md`。R95 是
> 本插件账轮次号，与 2026-09 的同号测试计划无关。

- **只扩“记住”的范围，不发明第二套权限系统**：既有审批
  `remember` 仍写 `settings.permission_rules`，求值仍走
  `PermissionEnforcer` 的 deny > allow > ask；新增的只有
  `remember_scope=tool|plugin` 与单个插件的受限 pattern
  `plugin__<plugin>__*`。
- **插件名只信服务端权威记录**：审批请求创建时按
  `PluginToolBridge` 已发布记录注入 `plugin_name`；客户端只
  传范围枚举，永不传 pattern 或插件名。权威记录缺失或工具名
  与插件名不匹配时，plugin 范围不落任何规则，当前应答语义
  不变。
- **默认仍是精确工具**：未勾选记住、旧客户端、非插件工具与
  远程审批路径全部保持既有行为；整插件范围会明确提示覆盖
  该插件未来新增的工具，批准与拒绝共用同一范围语义。
- **不扩围**：不做全部插件 `plugin__*`、通用 glob、规则管理
  UI、自动信任升级、profile 白名单改动或 Win7 同步；Win7
  继续标“待对齐”。
- **本地证据**：后端核心/相邻 208 例、前端与 Electron
  137 例通过；tsc（src/Electron）、ESLint、Ruff、py38、
  architecture、silent-exceptions、diff-check 与 diagnostics
  全绿；PR #2412 GitHub CI 与 E2E PR Gate 全绿，已 squash
  合并为 `main`
  `7634de8fc68e9064007706385ac433ec6c965d96`。

## 16. R96 交付边界

> spec：`2026-10-23_plugin-permission-identity-r96.md`。
> R96 是本插件账轮次号，与 2026-09 的同号测试计划无关。

- **只收紧执行期解释，不改已存规则**：`permission_rules`
  仍保存 R95 的 `plugin__<plugin>__*` 文本；R96 只让
  `PermissionEnforcer` 用桥接当前发布记录的权威
  `plugin_name` 核对它，不再把完整工具名字符串前缀当作
  插件身份。
- **双下划线不再串扰持久信任**：插件名与 capability 名
  仍可含 `__`，但 `a` 的整插件规则不能命中插件
  `a__b`，同字符串工具名也只能按当前发布记录的真实
  插件解释；无权威身份时受限插件通配不命中。
- **其它规则口径不变**：精确规则与普通 fnmatch、deny >
  allow > ask、bash 安全网、profile 白名单和审批弹窗
  全部保持；本轮不做规则管理 UI、命名禁令或 Win7 同步。
- **本地证据**：后端定向 134 例与相邻权限/插件回归
  113 例通过；Ruff、py38、architecture、
  silent-exceptions、diff-check 与 diagnostics 全绿；
  PR #2413 GitHub All checks successful，已 squash
  合并为 `main`
  `56b005127a7f83f48086460fdce3192484c18717`。

## 17. R97 交付边界

> spec：`2026-10-23_permission-rules-manager-r97.md`。
> R97 是本插件账轮次号，与其它账本的同号计划无关。

- **只补可见与可撤销，不开新的规则写面**：已保存规则
  仍只能由审批 remember（精确工具）或服务端权威派生
  （整插件）生成；设置页只列出 `parse_rules` 口径下
  实际生效的规则并支持逐条删除，不提供新增/编辑
  pattern 的入口。
- **删除走后端校验，不整表回写**：删除端点带 Origin
  守卫与下标范围校验，写回规范化后的有效列表并返回
  最新列表；前端不直接拼写 `permission_rules` 原始
  JSON。重复规则逐条删，误删后果只是恢复逐次审批。
- **其它口径不变**：存储结构、remember 追加策略、
  R96 身份匹配、审批弹窗与远程渠道全部保持；本轮
  不做批量清空、分组/搜索或 Win7 同步。
- **本地证据**：后端定向 37 例与相邻 77 例、前端定向
  26 例与相邻 33 例通过；tsc、ESLint（0 errors）、
  Ruff、py38、architecture、silent-exceptions、
  ipc-manifest、diff-check 与 diagnostics 全绿；
  PR #2418 GitHub All checks successful，已 squash
  合并为 `main`
  `a29e95ab70dc590d6469fe7c0f867e50f106f756`。

## 18. R98 交付边界

> spec：`2026-10-23_plugin-profile-allowlist-identity-r98.md`。
> R98 是本插件账轮次号，与其它账本的同号计划无关。

- **只收紧 profile 通配解释，不改已存 profile**：
  白名单条目文本与存储不变；本轮只让三道判定在
  命中受限插件通配前先核对桥接发布身份，不再把
  完整工具名字符串前缀当作插件身份。
- **与 R96 同一口径**：`plugin__a__*` 不能再带飞
  实际属于插件 `a__b` 的工具；身份缺失、非法或
  不匹配时通配不命中。精确条目、通用 glob 不
  展开、逐次审批与权限规则全部保持。
- **前端镜像同口径**：运行中插件工具复选框的通配
  覆盖改用已发布快照的 `plugin_name`，消除旧字符串
  镜像对含 `__` 名字的双向漂移；UI 不新增任何
  pattern 写面。
- **本地证据**：后端定向 70 例与相邻 93 例、前端
  定向 10 例通过；tsc、ESLint（0 errors）、Ruff、
  py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 全绿；PR #2440 GitHub
  All checks successful，已 squash 合并为 `main`
  `905bb49638a555668f64740290dd91c9bf378107`。

## 19. R99 交付边界

> spec：`2026-10-24_permission-rules-integrity-r99.md`。
> R99 是本插件账轮次号，与其它账本的同号计划无关。

- **只收口规则列表写入卫生，不开新写面**：remember
  仍是唯一规则来源；本轮仅让重复 remember 不再攒
  完全相同条目，并让删除按 `(tool_pattern, decision)`
  内容定位，消除 R97 下标漂移删错规则的窗口。
- **删除选择子不等于规则写面**：删除体携带的 pattern
  只用于指出撤销存储中已存在且完全一致的一条，
  无法创建或放宽规则；UI 只回传列表行自带字段，
  没有 pattern 输入入口。
- **冲突语义不动**：同 pattern 不同 decision 不去重、
  不自动清理存量重复；deny > allow > ask 与存储
  格式、远程网关口径保持，Win7 继续标待对齐。
- **本地证据**：后端定向 42 例与相邻 83 例、前端
  定向 28 例通过；tsc、ESLint（0 errors）、Ruff、
  py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 全绿；PR #2452 GitHub
  All Checks pass，已 squash 合并为 `main`
  `b2ba86e312345d854fb2a35760fc4d6388a0ea9a`。

## 20. R100 交付边界（已合并）

> spec：`2026-10-24_permission-rules-clear-r100.md`。
> R100 是本插件账轮次号，与其它账本的同号计划无关。

- **只补「全部撤销」，不开规则写面**：清空端点无请求体、
  不带任何筛选参数，永远只能把规则列表写空；规则生成、
  逐条删除与求值语义全部保持，UI 无 pattern 输入入口。
- **破坏性操作先确认**：设置页「全部删除」先走项目内
  confirmDialog（danger）才发请求；清空后果是全部恢复
  逐次审批（fail-safe），不做 undo 或备份导出。
- **本地证据**：后端定向 45 例与相邻 83 例、前端定向
  36 例通过；ipc-manifest（264 commands）、tsc、
  ESLint（0 errors）、Ruff、py38、architecture、
  silent-exceptions、diff-check 与 diagnostics 全绿；
  PR #2474 GitHub All Checks pass，已 squash 合并为
  `main` `3d0b6a3a7e7d68e61156d686842f4c090a0b2d43`。

## 21. R101 交付边界（已合并）

> spec：`2026-10-24_permission-rules-plugin-status-r101.md`。
> R101 是本插件账轮次号，与其它账本的同号计划无关。

- **只补可见性，不动写面与求值**：规则列表响应附带
  服务端派生的 `plugin_name`/`plugin_status` 只读标注，
  设置页对插件已卸载/无记录的规则显示徽标；标注永不
  落盘，删除写回仍是纯 `(tool_pattern, decision)`。
- **归属只认权威名单**：用生命周期记录集合 + 结构化
  命名空间 helper 判定归属，不按工具名字符串切分猜
  插件名；无记录命中时只报形状（missing/all）不报名字。
- **卸载联动删规则明确不做**：卸载是可 restore 的软
  删除，清规则会破坏恢复预期；本轮只让孤儿规则可见，
  删留仍由用户在规则管理界面决定。
- **本地证据**：后端新文件 5 例 + 既有 45 例、相邻
  95 例，前端定向 38 例通过；tsc、ESLint（0 errors）、
  Ruff 全库、py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 全绿；PR #2484 GitHub
  All Checks pass，已 squash 合并为 `main`
  `556cf0858b0f2e01b5f69b8515ea098abf9b00f5`。

## 22. R102 交付边界（已合并）

> spec：`2026-10-25_permission-rules-by-plugin-r102.md`。
> R102 是本插件账轮次号，与其它账本的同号计划无关。

- **按身份撤销，只减不增**：delete-by-plugin 的唯一
  选择子是生命周期记录中的权威插件名，删除集合由
  服务端用 R101 同款结构化归属（含长名字消歧）选出，
  客户端不传 pattern、无条件表达能力；与 R100 的
  「清空不带筛选参数」不冲突——那是对全清端点的约束，
  本轮是独立的按身份撤销端点。
- **校验不了身份就不用写**：名字不在册 400 不写，
  插件索引不可读 503 不写；无规则时幂等 ok 且不写
  存储。missing 孤儿无权威名字，不在此端点范围。
- **本地证据**：后端新文件 7 例 + 既有 50 例、相邻
  95 例，前端定向 43 例通过；ipc-manifest
  （265 commands）、tsc、ESLint（0 errors）、Ruff
  全库、py38、architecture、silent-exceptions、
  diff-check 与 diagnostics 全绿；PR #2493 GitHub
  All Checks pass，已 squash 合并为 `main`
  `3e89943ae1e8e8b99e09d904d02a9779f624204b`。

## 23. R103 交付边界（已合并）

> spec：`2026-10-25_plugin-orphan-rules-r103.md`。
> R103 是本插件账轮次号，与其它账本的同号计划无关。

- **把孤儿提示送到产生孤儿的地方**：插件页 best-effort
  拉 R101 标注规则并按归属计数，已卸载且仍有规则的
  卡片就地提示并可一键走 R102 按插件删除；卸载本身
  不自动删规则（restore 语义不变）。
- **纯前端复用**：零新后端端点/Electron 命令/全局
  i18n 键；计数拉取失败静默降级不显提示，插件页主
  功能不受影响。在册插件与 missing 孤儿仍在通用
  设置页管理，插件页只管「自己刚卸掉的」这一面。
- **本地证据**：前端定向 53 例通过（新增 PluginsTab
  5 例覆盖计数提示/确认删除/取消/失败保提示/降级）；
  tsc/ESLint/architecture/diff-check/diagnostics
  全绿；交互抽为 `PluginOrphanRules` 组件，PluginsTab
  仅 +21 行登记 baseline 820。PR #2500 GitHub All
  Checks pass，已 squash 合并为 `main`
  `58afc32d329b40371be8c1a6051b555ac4a15d0c`。

## 24. R104 交付边界（已合并）

> spec：`2026-10-25_permission-rules-orphans-r104.md`。
> R104 是本插件账轮次号，与其它账本的同号计划无关。

- **补完标注处置矩阵**：missing 一类（插件形状但无
  生命周期记录）此前只能逐条删；本轮
  `delete-orphans` 由服务端用 R101 同一分类口径整组
  选集，索引不可读 503 fail-closed 不写。
- **零客户端选择子**：无请求体，语义只有「全部
  missing」；全局通配/在册归属/内置工具规则永不命
  中。会话级 remember 经取证属多轮安全特性，本轮记
  录搁置理由（spec §1），不强行缝合。
- **本地证据**：后端 63 例（新 6 例覆盖仅删
  missing/长名字不误伤/空索引保全局通配/幂等/
  503/403）、前端 58 例通过；Ruff 全库、py38、
  ipc-manifest（266）、tsc、ESLint、architecture、
  silent-exceptions、diff-check、diagnostics 全绿。
  PR #2504 GitHub All Checks pass，已 squash 合
  并为 `main` `1708e1efe6fadb39084b9ee534ceb3a7157d753a`。

## 25. R105 交付边界（已合并）

> spec：`2026-10-25_session-remember-r105.md`。
> R105 是本插件账轮次号，与其它账本的同号计划无关。

- **记住分时长**：审批记住新增 `session` 时长（默认
  permanent 与从前一致）；会话规则只存进程内存、按
  chat 会话隔离，重启即失，不再为「这次先放行」被
  迫攒永久规则。
- **求值安全位不变**：会话规则与持久规则同按 deny >
  allow > ask 合并，持久 deny 不可被会话授权绕开；
  会话归属由服务端从 ToolExecutionContext 捕获，客
  户端不可指定；无归属时降级不记、绝不转永久。
- **本地证据**：后端新增 15 例（单测 9 + API 6）
  与相邻/集成共 235 例、前端 96 例（ApprovalDialog
  新增 4 例）通过；Ruff 全库、py38、tsc、ESLint、
  architecture、silent-exceptions、diff-check、
  diagnostics 全绿，manifest 仍 266。

## 26. R106 交付边界（已合并）

> spec：`2026-10-26_session-rules-manage-r106.md`。
> R106 是本插件账轮次号，与其它账本的同号计划无关。

- **会话规则可管可撤**：聊天顶栏可查看本会话已记
  住的决定并逐条撤销或整会话清空，记错的整插件
  deny 不再只能靠结束会话/重启挽回；设置页仍只管
  持久规则。
- **写面不扩大**：端点只读/只删，创建仍只经审批应
  答由服务端捕获会话归属；删除按内容定位、清空无
  筛选，方向恒为回到逐次询问。
- **本地证据**：后端新增 13 例（单测 4 + API 9）
  与相邻/集成共 262 例、前端与 Electron 相邻套件共
  286 例通过；Ruff 全库、py38、tsc、ESLint、
  architecture、silent-exceptions、diff-check、
  diagnostics 全绿，manifest 266 → 269；
  permission_routes.py（855 行）按 ratchet 登记
  baseline。

## 27. R107 交付边界（已合并）

> spec：`2026-10-26_profile-stale-plugin-entries-r107.md`。
> R107 是本插件账轮次号，与其它账本的同号计划无关。

- **白名单孤儿可见化**：EditAgentForm 标注当前未发
  布的插件形条目（已卸载/无记录/当前未发布三类，
  口径镜像 R101），可逐条就地移除（草稿级、仍需保
  存）；profile 侧至此与规则管理矩阵对齐。
- **纯前端零新面**：复用发布快照与生命周期名单两
  处权威数据，不新增端点/命令（manifest 仍
  269），不改存储与后端匹配；名单读不到整体不标
  注，与 R101 降级一致。
- **本地证据**：前端新增 9 例（分类 6 + 组件 3），
  与 agents 及 Agents 页/PluginsTab/pluginClient 相
  邻套件共 10 文件 53 例通过；tsc、ESLint、
  architecture、diff-check、diagnostics 全绿，
  manifest 仍 269，后端零改动。

## 28. R108 交付边界（已合并）

> spec：`2026-10-26_approval-plugin-badge-r108.md`。
> R108 是本插件账轮次号，与其它账本的同号计划无关。

- **决策时刻归属可见**：ApprovalDialog 工具行下
  新增「所属插件」横幅、OS 通知 body 追加插件归
  属后缀，均只读后端注入的权威 `plugin_name`
  （R95）；归属可见化弧（事后规则 R101/插件页
  R103/白名单 R107）至决策时刻闭合。
- **纯展示零语义**：不切分工具名猜插件、非插件
  工具逐字不变；应答/记住/远程渠道零改动，
  无新端点/命令（manifest 仍 269）。
- **本地证据**：前端新增 4 例（横幅 2 + 通知 2），
  与 permission 及 permissionState/permissionApi/
  i18n 相邻套件共 21 文件 94 例通过；tsc、ESLint、
  architecture、diff-check、diagnostics 全绿，
  manifest 仍 269，后端零改动。

## 29. R109 交付边界（已合并）

> spec：`2026-10-26_rule-shadowed-annotation-r109.md`。
> R109 是本插件账轮次号，与其它账本的同号计划无关。

- **生效性可见化**：管理器在同列表内派生「被更高
  优先级规则覆盖」的行并徽标提示（裁决恒为
  deny > allow > ask，「明明放行却不生效」自此有解
  读）；继归属（R101）之后补规则治理的第二只读维度。
- **保守可证**：只判等值与插件通配两族覆盖，归属
  只认 R101 权威标注；一般 fnmatch 包含不判，永不
  误报。纯前端只读，不改存储/求值/写面（manifest
  仍 274）。
- **本地证据**：前端新增 8 例（纯函数 6 + 组件 2），
  与 GeneralTab 既有回归及
  permissionApi/i18n/PluginsTab 相邻套件共 18 文件
  101 例通过；tsc、ESLint、architecture、diff-check、
  diagnostics 全绿，manifest 仍 274，后端零改动。

## 30. R110 交付边界（已合并）

> spec：`2026-10-27_perm-popover-annotations-r110.md`。
> R110 是本插件账轮次号，与其它账本的同号计划无关。

- **最后一张未标注表**：顶栏弹层的自动放行审计逐
  条标注所属插件（生命周期权威名结构化归属）、
  会话规则复用 R109 遮蔽派生；权限 UX 全部列表
  （规则/审计/会话规则/审批/白名单）的归属与生效
  性标注至此齐备。
- **导出与节奏不变**：审计台账格式与 Markdown/
  JSON 导出逐字不动（R106 口径），名单只在弹层打
  开时取、失败降级不标；派生下沉 shared/lib 两侧
  同源。无新端点/命令（manifest 仍 274）。
- **本地证据**：前端新增 8 例（owner 5 + widget 3），
  与定向回归及 permissionApi/permissionState/
  ApprovalDialog 相邻套件共 120 例通过；tsc、
  ESLint（0 errors，存量 warnings 不变）、
  architecture、diff-check、diagnostics 全绿，
  manifest 仍 274，后端零改动。

## 31. R111 交付边界（已合并）

> spec：`2026-10-27_transcript-plugin-owner-r111.md`。
> R111 是本插件账轮次号，与其它账本的同号计划无关。

- **历史可见化收官**：聊天转录通用卡片标注插件工
  具的所属插件，口径与审计（R110）/审批
  （R108）同一权威归属；至此用户能看到工具名字
  的全部界面都带归属。
- **热路径收敛**：名单经模块级缓存 hook 供数（在
  途合并 + TTL + 内容未变不换引用），只动通用卡
  标题行；memo 比较、专用渲染器、导出串零改动，
  后端零改动（manifest 仍 274）。
- **本地证据**：新 hook 套件、Message.pluginOwner
  与 Message 既有全组及 permissionInsights/
  PermissionModeSwitch 共 14 文件 74 例通过；
  tsc、ESLint（0 errors，存量 warnings 不变）、
  architecture（Message 768/800）、diff-check、
  diagnostics 全绿，manifest 仍 274，后端零改动。

## 32. R112 交付边界（已合并）

> spec：`2026-10-27_perm-switch-consolidation-r112.md`。
> R112 是本插件账轮次号，与其它账本的同号计划无关。

- **供数单一事实源**：生命周期名单的读取实现自此只剩
  共享缓存 hook 一处（转录 R111 + 顶栏审计 R110 两
  个消费面），弹层打开即出归属、与转录同开合并取数；
  EditAgentForm 因需完整 records 且随显式刷新取证保
  留自取。
- **纯函数归位**：弹层导出格式化随派生函数同置共享
  层，组件文件只导出组件；导出文本逐字不变，后端零
  改动（manifest 仍 274）。
- **本地证据**：PermissionModeSwitch/insights/hook/
  pluginOwner 与 shadowed+GeneralTab 共 6 文件
  60 例通过；tsc、ESLint（0/0，弹层文件存量
  warnings 清零，450→393 行）、architecture、
  diff-check、diagnostics 全绿，manifest 仍 274，
  后端零改动。

## 33. R113 交付边界（已合并）

> spec：`2026-10-27_tool-group-plugin-owners-r113.md`。
> R113 是本插件账轮次号，与其它账本的同号计划无关。

- **转录可见性收官**：折叠组头补上去重归属后，转录的
  折叠态与展开态都能一眼看出插件参与，与审批
  （R108）/审计（R110）/逐卡（R111）口径一致。
- **零新增取数**：复用 R111 已在 Message 作用域内的
  名单与归属派生；后端零改动（manifest 仍 274）。
- **本地证据**：Message 全组 12 文件 62 例与定
  向三套件 20 例通过；tsc、ESLint（0 errors，存
  量 warnings 不变）、architecture（Message
  787/800）、diff-check、diagnostics 全绿，
  manifest 仍 274，后端零改动。

## 34. R114 交付边界（已合并）

> spec：`2026-10-27_tasktree-plugin-owner-r114.md`。
> R114 是本插件账轮次号，与其它账本的同号计划无关。

- **编排面补齐**：多智能体运行中「哪个插件的工具在
  等审批/在执行」在任务行与实时动态里可见，口径与
  转录（R111/R113）同一名单派生；事件协议与编排逻
  辑零改动。
- **门控与文件风格**：无实时工具事件不取数；后缀跟
  随本文件硬编码中文，不为一处文案引入 i18n 依赖。
- **本地证据**：pluginOwner 新套件与既有七套件
  共 8 文件 60 例通过（无 live 夹具门控关、零
  影响）；tsc、ESLint（0/0）、architecture、
  diff-check、diagnostics 全绿，manifest 仍
  274，后端零改动。

## 35. R115 交付边界（已合并）

> spec：`2026-10-28_hook-history-plugin-owner-r115.md`。
> R115 是本插件账轮次号，与其它账本的同号计划无关。

- **展示面收官**：Hook 历史补齐后，R113 扫描到的全
  部策展工具名界面（规则/白名单/审批/审计/转录逐
  卡与组头/编排实时行/Hook 历史）均带同一口径归
  属；仅剩通用载荷镜像与远程渠道在边界外。
- **本地证据**：pluginOwner 新套件与 settings
  Hook 相关套件等共 11 文件 59 例通过；tsc、
  ESLint（0/0）、architecture、diff-check、
  diagnostics 全绿，manifest 284（他人推进，
  本轮后端零改动）。

## 36. R116 交付边界（已合并）

> spec：`2026-10-28_plugins-tab-model-r116.md`。
> R116 是本插件账轮次号，与其它账本的同号计划无关。

- **为后续让路**：PluginsTab 自 R111 起顶格多次挡下
  插件面候选；本轮纯机械抽离文案/常量/纯函数约 140
  行到同目录模型模块，行为逐字不变，行数预算回到可
  维护区间（基线不 tighten）。
- **本地证据**：settings 全目录 59 文件 365 例通过
  （PluginsTab 14 例原样）；搬移逐字性经字符串字面
  量多重集机械校验（126 个全等）；PluginsTab
  819 → 686 行；tsc、ESLint（0/0）、architecture、
  diff-check、diagnostics 全绿，后端零改动。

## 37. R117 交付边界（PR #2623 待合并）

> spec：`2026-10-28_message-audit-extract-r117.md`。
> R117 是本插件账轮次号，与其它账本的同号计划无关。

- **卫生续轮**：继 R116 把审计格式化纯函数自转录组
  件尾部抽离至同目录模块，组件文件回到单一导出并清
  除其仅有的 react-refresh 存量警告；归属标注语义
  与渲染行为逐字不变。
- **本地证据**：基线 ESLint 实测 Message.tsx 恰 2
  条 react-refresh 警告（769/774 行），抽离后 0/0；
  两函数 19 行逐字节全等；chat 全目录 131 文件
  647 例通过；Message.tsx 787 → 768 行；tsc、
  architecture、diff-check、diagnostics 全绿，后
  端零改动。

—— 本账本由插件化循环维护，随轮次追加。
