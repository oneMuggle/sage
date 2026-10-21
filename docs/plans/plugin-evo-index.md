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
| R80 | tool 收编：硬编码装配改为 bundle 注册 + 权限 → RiskClass | 待启动 |
| R81 | 三层配置 + 四预设 + `--dump-config` | 待启动 |
| R82 | 插件 UI / REST（安装、启停、权限确认、日志） | 待启动 |
| R83 | 进程外宿主（含 DSH 边车，仅在触发条件满足时） | 待启动 |
| R84 | harness 文件化 + lock + 差异视图 | 待启动 |
| R85 | 提案引擎（Propose–Probe–Compose + 证据锚定） | 待启动 |
| R86 | 生态（脚手架 / 索引 / 贡献指南） | 待启动 |

## 2. 交付总账

| 轮 | 交付内容 | main PR | win7 PR | 状态 |
| --- | --- | --- | --- | --- |
| R78 | `domain/plugin.py`、`ports/plugin.py`、`application/kernel/{effects,events,services,fiber,cordis_names}.py` + 5 个单测文件 | #2206 | 待对齐 | ✅ 已交付 |
| R79 | `hooks/kernel_provider.py`（provider + `fire_hooks` 开关）+ 30 例单测（含 11 组双跑对照） | #2206 | 待对齐 | ✅ 已交付 |

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

—— 本账本由插件化循环维护，随轮次追加。
