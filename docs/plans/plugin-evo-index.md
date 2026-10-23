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
| R94 | 运行中插件工具动态选择器 | 实施中 |

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
| R94 | `PluginToolBridge.published_tools()` 权威快照 + `GET /plugins/runtime/tools` + `pluginClient.runtimeTools()` + Agent 运行中插件工具动态复选框与测试/文档 | 实施中 | 待对齐 | 实施中 |

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
  architecture-check、diff-check 与 diagnostics 全绿，最终以
  PR CI 为准。

—— 本账本由插件化循环维护，随轮次追加。
