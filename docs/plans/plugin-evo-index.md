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
| R83 | 进程外宿主（含 DSH 边车，仅在触发条件满足时） | 待启动 |
| R84 | harness 文件化 + lock + 差异视图 | 待启动 |
| R85 | 提案引擎（Propose–Probe–Compose + 证据锚定） | 待启动 |
| R86 | 生态（脚手架 / 索引 / 贡献指南） | 待启动 |

## 2. 交付总账

| 轮 | 交付内容 | main PR | win7 PR | 状态 |
| --- | --- | --- | --- | --- |
| R78 | `domain/plugin.py`、`ports/plugin.py`、`application/kernel/{effects,events,services,fiber,cordis_names}.py` + 5 个单测文件 | #2206 | 待对齐 | ✅ 已交付 |
| R79 | `hooks/kernel_provider.py`（provider + `fire_hooks` 开关）+ 30 例单测（含 11 组双跑对照） | #2206 | 待对齐 | ✅ 已交付 |
| R80 | `application/kernel/tool_install.py`（127 行机制）+ `tools/tool_bundles.py`（31 个 bundle / 94 个工具）+ 39 例单测 | #2206 | 待对齐 | ✅ 已交付 |
| R81 | `application/kernel/harness_config.py`（546 行）+ `backend/cli/harness.py`（215 行）+ 删除 legacy/旧开关 + 55 例单测 | #2206 | 待对齐 | ✅ 已交付 |
| R82 | `api/plugin_routes.py` + lifecycle manifest/events 补强 + `pluginClient.ts` / `PluginsTab.tsx` + 后端 59 例相关测试、前端 16 例新增测试 | #2206 | 待对齐 | ✅ 已交付 |

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

—— 本账本由插件化循环维护，随轮次追加。
