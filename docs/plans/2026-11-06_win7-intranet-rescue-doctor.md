# 2026-11-06 Win7 内网管控环境：Sage 修复工具（Rescue Doctor）与自愈方案

**状态**：提案待确认（未实施）
**目标分支**：main 首发 → cherry-pick `release/win7`（Python 3.8 适配）
**关联文档**：技术 §20 Electron / §29 Electron 日志 / §31 Win7 LTS / §41 sage doctor / §16 可观测性；用户手册 §01 / §06 / §11 / §15

---

## 1. 背景

内网 Win7 SP1 现场反馈：安装 Sage 后前端会"闪退"。这类机器的共同点是装有终端管控/EDR 类软件（单位强制安装），它可能通过以下方式干扰 Chromium 106（Electron 21.4.4 内置）：

- 终止 `electron.exe` 的 renderer / GPU / utility 子进程（应用控制或行为规则）；
- 向进程注入 DLL/hook，使旧版 Chromium 在初始化或渲染时崩溃；
- 拦截安装目录、`%APPDATA%\sage` 的写入或 DLL 加载；
- 拦截 Electron→Python 子进程链（后端被杀）；
- 按白名单阻断未签名可执行文件。

用户当前遇到的双重困境是：

1. **前端起不来时，没有任何前端之外的入口**去配置端点/模型、做体检、看崩溃原因；
2. **应用自身没有崩溃循环检测/安全模式/自动降级**，同一台机器每次启动都重复闪退。

现有基础设施（可复用，不必从零造）：

| 能力 | 位置 | 现状 |
|---|---|---|
| 启动前环境自检 18 项 | `backend/cli/doctor.py` + `backend/cli/checks/*` | 文本/JSON、退出码、fail-open；Electron 启动时自动跑且只写日志（技术 §41） |
| Win32 运行库检测 | `electron/runtime-check.ts` | VC++/KB 缺失时弹原生对话框（4 按钮） |
| 崩溃事件兜底 | `electron/crashGuard.ts` | 写 `<userData>/sage-emergency.log`；`crashReporter.start()` 当前每次都失败（`submitURL` 参数错误），**没有 minidump** |
| 渲染进程崩溃监听 | `electron/main.ts:1234` | 只写一行 NDJSON，无 UI/无恢复 |
| 启动失败对话框 | `electron/showStartupFailureDialog.ts` | 只有「打开日志目录 / 重试 / 退出」；`loadFile` 路径的重试是空操作 |
| 诊断包导出 | `electron/diagnosticExport.ts` + `backend/api/diagnostic_routes.py` | 只导出 LLM trace，依赖后端存活 |
| 自透明工具 | `sage_doctor` / `sage_self_status` / `read_sage_config` | 仅聊天内可用；前端崩溃后全部失效 |
| 后端解释器解析 | `electron/backendLauncher.ts` | 打包后固定 `resources/python/python.exe`，PYTHONPATH 已解决 |

> 结论：**不缺检查逻辑，缺"前端之外的可执行入口"和"自愈状态机"**。

---

## 2. 故障模型：先取证，再修复

不同拦截方式对应的自救手段完全不同。方案第一阶段必须把故障分类做出来，否则"自动修复"只是猜。

| 故障类型 | 可观测信号（新增/现有） | 应用侧可做的处理 | 不能做的 |
|---|---|---|---|
| 渲染进程被终止 | `render-process-gone` reason=`killed`；renderer pid 消失；EDR 清单存在 | 安全模式降级；提示放行清单 | 无法阻止外部终止 |
| 渲染进程自身崩溃 | reason=`crashed` / `oom`；minidump | 禁用 GPU/合成器/非核心窗口；升级兼容档位 | 无法保证修复 |
| GPU/utility 子进程被杀 | `child-process-gone` type=`GPU`/`Utility` | 进一步软件合成；`--single-process` 实验档 | — |
| 后端被拦截/杀 | spawn `error`/exitCode；`/health/proof` 超时；Python 路径 | 换启动解释器（打包版只有 bundled python）；提示放行 python.exe | 无权限替换安全软件规则 |
| 文件/目录写入被拦 | `sqlite_writable` / `frontend_dist` / 安装包完整性 | 修复权限、迁移 userData、提示放行目录 | — |
| 网络管控 | 端点连通性检查（DNS/连接超时/TLS/401/404） | 指导配置代理/端点；导入管理员预置配置 | — |
| 可执行文件被应用控制阻断 | 主进程无任何日志、上次运行标记为 running 后消失 | 取证 + 放行清单；遗留产品走 §6.7 处置流程 | 不做静默处置（必须用户确认） |
| 系统运行库缺失 | `runtime-check`（已有） | 已有下载/安装引导 | — |

**原则：Sage 默认只做"应用侧降级 + 取证"；当管控软件为无人维护的遗留产品、IT 放行不可行时，提供 §6.7 的主动处置能力（停止/禁用/修改/绕过），但必须用户知情确认、全程留痕、可回滚。**

---

## 3. 目标与非目标

### 核心原则

**通用自检修基座**：所有修复能力都不依赖前端/renderer 可用，具备主动处置遗留管控软件的能力。

- 配置逃生舱（端点/模型）通过 Python CLI 直接写 SQLite，完全绕过 Electron/Chromium；
- 原生对话框由 Electron 主进程弹出，renderer 崩溃仍可交互；
- 安全模式档位是通用降级策略（L0–L3），不针对特定 EDR 规则，逐级"试错"而非"对症"；
- **遗留管控软件处置**：内网管控软件多为 2014 年前后开发的遗留产品，早已无人维护，IT 无法协助放行。方案必须具备主动处置能力：停止服务、禁用注入、修改配置、或直接绕过，以 Sage 能正常运行为目标；
- 支持包/放行清单提供通用故障分类（渲染被杀 / 自身崩溃 / 后端被杀 / 补丁缺失 / 可执行文件阻断 / **管控软件拦截**），不假设具体拦截机制；
- 实现**不依赖现场信息作为前置条件**：所有能力在 M0/M1 即具备通用可用性；现场信息（管控软件名/版本、EDR 清单、崩溃日志）仅作为后续打磨特定产品体验的**锦上添花**，不是实现阻塞项。

### 目标

1. 前端完全不可用时，用户仍可通过**独立于 Electron/Chromium 的控制台修复工具**完成：
   - 一键体检（复用 18 项 + 新增打包/DB/端点/EDR/崩溃史检查）；
   - **配置端点与模型**（增删改、测试连接、设为当前模型、导入管理员配置包）；
   - 安全修复（缓存、窗口状态、孤儿端口、损坏配置、日志膨胀）；
   - 生成支持包 / 管控软件放行清单，交给 IT 或支持人员。
2. 应用能在**连续闪退**时自动进入下一档**兼容模式**，并给出原生对话框（不依赖 renderer）让用户选择"安全模式重启 / 运行修复工具 / 生成诊断包 / 退出"。
3. 崩溃现场可回传：`last-run` 标记、崩溃时间线、minidump、EDR 清单、doctor 报告，且诊断包生成**不依赖后端存活**。
4. 所有修复动作可回滚、有备份、有审计记录。

### 非目标

- ❌ 重写 Electron/React 或迁移 WebView（属 §31 的长期 Web 通道议题）；
- ❌ 自动上传任何诊断数据（仅本地生成 zip，由用户决定发送对象）。

> **重要说明**：本方案**不再将"绕过管控软件"列为非目标**。内网管控软件多为 2014 年前后开发的遗留产品（如早期 360 天擎、北信源、启明星辰等），早已无人维护，IT 无法协助放行。当 Sage 被这类遗留软件拦截时，方案必须具备主动处置能力：停止服务、禁用注入、修改配置、或直接绕过。所有处置动作必须：
> - 明确告知用户即将执行的操作；
> - 记录操作日志（`rescue-actions.jsonl`）；
> - 提供回滚能力（恢复服务/配置）；
> - 仅在用户确认后执行。

---

## 4. 方案选型

| 方案 | 说明 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A. 复用 bundled Python，新增 `backend.cli.rescue` + 原生对话框向导（推荐）** | 终端 REPL 为主入口；Electron 主进程另提供不依赖 renderer 的 dialog 向导 | 复用现有 doctor 注册表、SettingsRepository/SecretBox、probe_endpoint；无新运行时；Win7 Py3.8 可跑 | 需处理控制台编码/EDR 拦截 cmd 的极端情况 | **采用** |
| B. 独立静态 `SageRescue.exe`（Go/C#） | 单独编译的控制台/GUI 工具，不依赖 Python/Electron | 最抗 EDR 误伤、无 Python 依赖 | 需第三套运行时与构建链、配置层要重写、维护成本高；YAGNI | 暂不采用，保留为 M4 备选 |
| C. 只增强现有启动前 doctor + 托盘入口 | 最小改动 | 成本低 | 解决不了"前端崩溃后配置端点"的核心诉求；托盘也依赖 renderer 可用 | 作为 M0 的一部分，不单独成案 |

参考的主流产品做法：

- **Claude Code**：`/doctor`、`/status`、`/config` 把"健康检查 + 配置"做成确定性命令，而不是只靠聊天；
- **VS Code**：窗口反复崩溃后提示"以禁用扩展模式重新打开"，并提供 `--status` 诊断输出；
- **Chrome/Electron 系**：Crashpad minidump + "页面崩溃后重新加载"；
- **Flutter/Docker**：`flutter doctor` / 诊断打包，检查项带 `fix hint` 并可逐项修复。

Sage 的差异点：目标环境是**禁用外网、无管理员权限、用户非技术型**的内网 Win7，所以"终端 REPL + 中文编号菜单"比"命令行参数"更重要；同时必须有**不依赖 renderer 的原生对话框**兜底。

---

## 5. 总体架构

```
┌──────────────────────── Sage.exe（Electron 主进程，renderer 崩溃后仍存活）────────────────────────┐
│ 启动看门狗（新增）                                                                              │
│  ├─ last-run.json：running/clean + 启动阶段时间线                                               │
│  ├─ crash-journal.jsonl：render-process-gone / child-process-gone / 心跳丢失 / 外部终止推断       │
│  ├─ crash-loop 计数 ──> compat.json（兼容档位 L0–L3）──> Chromium flags + 功能裁剪              │
│  └─ 原生 dialog 向导：体检 / 安全模式重启 / 运行修复工具 / 生成诊断包（不依赖 renderer）          │
│                                                                                                │
│ 心跳：renderer 每 15s IPC 一次；60s 无心跳 → 记录 + 弹一次恢复对话框                              │
└───────────────┬────────────────────────────────────────────────────────────────────────────────┘
                │ 正常模式 spawn                              │ 用户手动 / dialog 调起
                ▼                                             ▼
 resources\python\python.exe                        SageDoctor.cmd（安装目录 / 开始菜单）
   ├─ backend.main（FastAPI 8765）                    └─ python -m backend.cli.rescue
   └─ backend.cli.rescue --json（供 dialog 向导调用）       ├─ REPL（中文编号菜单）
                                                          ├─ config 端点/模型向导
                                                          ├─ repair 安全修复
                                                          ├─ report 支持包
                                                          ├─ allowlist 放行清单
                                                          ├─ security 遗留管控软件处置（§6.7）
                                                          └─ safe-mode 兼容档位
                                                                    │
                                    共享 action 层：backend/services/rescue/*
                                    ├─ SettingsRepository + SecretBox（DPAPI）
                                    ├─ SQLite 备份 / quick_check / 迁移版本
                                    ├─ model_catalog.probes.probe_endpoint（连通性）
                                    └─ zipfile 支持包（不依赖后端）
```

关键决策：

1. **Doctor 由用户直接启动，而不是由 Electron spawn**。管控软件常见规则是"限制父进程为 electron.exe 的子进程"；用户手动双击 `SageDoctor.cmd` 走的是 explorer→cmd→python，可规避这一类父子链规则（不规避安全策略本身）。
2. **主运行时用 bundled Python**（main 3.11.9 / win7 3.8.10），不引入新运行时。所有配置读写复用 `SettingsRepository`，自动获得 SecretBox（Windows DPAPI 用户级）加密。
3. **双前端、单 action 层**：控制台 REPL 与 Electron 原生对话框只是两种 UI，执行同一套 `rescue` 子命令（`--json`），避免逻辑分叉。
4. **兼容档位是机器本地状态**（`%APPDATA%\sage\compat.json`），不进用户配置、不跨设备同步、可一键复位。

---

## 6. 组件设计

### 6.1 取证层（M0，先行）

#### 6.1.1 `last-run.json` 与启动阶段时间线

`<userData>/diagnostics/last-run.json`：

```json
{
  "schema": 1,
  "bootId": "2026-11-06T09:12:31Z-7f3a",
  "appVersion": "0.4.9-alpha.77",
  "electron": "21.4.4",
  "startedAt": "2026-11-06T09:12:31Z",
  "stage": "first_paint",
  "stages": [
    ["process_start", 0], ["app_ready", 812], ["backend_spawned", 840],
    ["window_created", 910], ["did_finish_load", 1540], ["first_paint", 1762]
  ],
  "endedAt": null,
  "endReason": null,
  "safeModeLevel": 0
}
```

- 启动时写 `running`；正常退出（`before-quit`/`will-quit`）写 `clean`；
- 下次启动发现上次是 `running` 且未写 `clean` → 记为**上次异常退出**（可区分"进程被外部终止"与"应用内崩溃"）；
- `first_paint` 由 renderer 在 React 首帧后经 IPC 上报（新增 `sage:boot:first-paint`）；避免只看 `ready-to-show`。

#### 6.1.2 `crash-journal.jsonl` 字段

在 `crashGuard.ts` 基础上新增结构化 journal（emergency log 保留为最后兜底）：

```json
{"ts":"...","bootId":"...","event":"render-process-gone","reason":"killed","exitCode":1,
 "type":"renderer","rendererPid":4321,"url":"file:///.../index.html","route":"/chat",
 "windowAgeMs":2300,"safeModeLevel":0,"edr":{"products":["..."],"services":["..."]}}
```

同时修复两处既有缺口：

- `crashReporter.start()` 改为 `uploadToServer: false`（Electron 21 下不传 `submitURL` 会抛错），让 Crashpad 真正产出 dump；
- `loadFile` 失败路径的"重试"按钮目前丢弃返回值，改为真正重试（顺手修复）。

#### 6.1.3 前端心跳与"未崩溃但白屏"

- renderer 每 15s 发 `sage:heartbeat`（轻量 IPC，不落日志）；
- 主进程 60s 未收到且窗口可见 → 写 `frontend-heartbeat-lost`，弹一次原生恢复对话框（重新加载 / 安全模式重启 / 运行修复工具 / 退出）；
- 不反复弹窗（每 boot 只弹一次）。

#### 6.1.4 新增 doctor 检查项

| 检查 | 目的 | 失败级别 |
|---|---|---|
| `packaged_runtime` | `resources/python/python.exe`、`resources/backend`、`dist/index.html` 完整性 | CRITICAL（打包模式） |
| `db_integrity` | `PRAGMA quick_check` + schema 版本 + `preferences` 可读 | CRITICAL |
| `endpoint_reachability` | 每个 endpoint TCP+`/v1/models` 探测（5s 超时），区分 DNS/拒绝/超时/401/404 | WARN |
| `crash_history` | 读 `crash-journal.jsonl`，汇总最近 7 天崩溃原因/次数 | WARN |
| `security_software` | 识别既有安全产品/服务/注入模块（仅信息，处置见 §6.7） | INFO |
| `port_ownership` | 8765 监听者 PID 与命令行（识别孤儿 backend） | WARN |
| `data_dir_paths` | userData/日志/缓存/备份目录可写与大小 | WARN |

`edr_inventory` **只列出**检测到的安全产品名称/服务，不做任何修改；匹配失败 fail-open 为 INFO。

### 6.2 救援入口 `backend.cli.rescue`

#### 6.2.1 入口形态

| 入口 | 实现 | 说明 |
|---|---|---|
| 开始菜单「Sage 修复工具」 | NSIS `customInstall` 创建快捷方式 → `SageDoctor.cmd` | 主入口，普通用户可发现 |
| 安装目录 `SageDoctor.cmd` | electron-builder `extraFiles` | 双击即用；内容见 §11 |
| `Sage.exe --doctor` | 后续可选：`ELECTRON_RUN_AS_NODE=1` 运行 JS 薄壳 | 不依赖 Python 的备选，M3 再评估 |
| 托盘/菜单「运行修复工具」「打开最近诊断报告」 | Electron `shell.openPath` | 应用正常时也可用 |
| 原生对话框向导 | `electron/rescueDialogs.ts` | cmd 被策略禁用时的兜底 |

#### 6.2.2 REPL 交互（默认模式）

```
Sage 修复工具 v0.4.9  (Windows 7 SP1 x64)
安装目录: C:\Users\x\AppData\Local\Programs\Sage
数据目录: C:\Users\x\AppData\Roaming\sage
上次启动: 2026-11-06 09:12:31  异常退出（renderer killed, exitCode=1）

[1] 一键体检
[2] 配置模型端点
[3] 修复启动问题
[4] 生成诊断包（发给 IT/支持）
[5] 生成管控软件放行清单
[6] 处置遗留管控软件（停止/禁用/绕过）
[7] 查看崩溃记录
[q] 退出
请选择>
```

非交互子命令（供脚本/对话框向导调用）：

```
SageDoctor.cmd diag --json
SageDoctor.cmd config list
SageDoctor.cmd config test --endpoint-id local
SageDoctor.cmd repair cache|window|logs|port|config|db
SageDoctor.cmd report [--include-crashdumps]
SageDoctor.cmd allowlist
SageDoctor.cmd security detect
SageDoctor.cmd security stop --target <service|process> [--yes]
SageDoctor.cmd security disable --target <service> [--yes]
SageDoctor.cmd security bypass --mode parent|dir|delay
SageDoctor.cmd security restore
SageDoctor.cmd safe-mode status|set 0|1|2|3|off
```

实现约束：

- 交互 TTY 下按系统 ANSI/OEM 代码页输出（中文 Win7 控制台默认 cp936），管道/被 Electron 调用时输出 UTF-8（现有 doctor 已按 UTF-8 对齐，需区分 TTY）；
- 不使用花哨 TUI/盒线字符，避免 Win7 光栅字体乱码；
- 每个危险动作先打印"将做什么 + 备份位置"，需输入 `y` 确认；
- 所有动作追加审计到 `<userData>/diagnostics/rescue-actions.jsonl`。

### 6.3 端点/模型配置逃生舱（用户主诉求）

#### 6.3.1 数据源与安全

- **唯一真相源**是 SQLite `preferences` 表的 `app_settings` 行（`endpoints` + `modelSelections`，camelCase 字段；白名单定义在 `backend/data/settings_canonicalizer.py:132-244`），通过 `SettingsRepository.set_json("app_settings", ...)` 读写；写侧自动经 SecretBox 加密（Windows DPAPI 用户级），读侧透明解密。`config.yaml`、`.env` 里的 `LLM_*` 变量只作用于 embedder/wiki 回退，**聊天主链路不读任何 env**，救援工具必须直写 DB（这是推荐路径：offline、绕过 local_auth token、复用 canonicalizer 与 SecretBox；详细对比见下方"端点写入路径对比"）。
- **前提**：Sage 必须未运行（`tasklist` 查 `Sage.exe`、端口 8765 监听者）；否则拒绝写入并提示先退出，避免与后端/前端缓存并发覆盖。**不要启动第二个 backend 实例**：会与主 backend 抢端口/抢 DB/抢 token。
- **写前强制备份**：优先调用 `backup_service.create_backup("rescue")`，或自带 `sqlite3.Connection.backup()` 备份到 `<userData>/backups/sage-YYYYMMDD-HHMMSS-before-rescue.db`。
- **写入前校验 schema 与字段**：
  - 读 `schema_version` 表 `MAX(version)`（当前最新 v13），若 > 工具已知最新则拒绝写入（说明 DB 来自更新版 app，工具白名单可能过严）；
  - 复用 `validate_settings_shape` + `validate_settings_payload`（`settings_canonicalizer.py`）；
  - 端点 CRUD 逻辑参照 `backend/tools/config_tool.py:779-930`（已是 LLM agent 用过的参考实现）。
- **显式约束**（必须写入 CLI help）：
  - ❌ **不要改 `endpoint.id`**：macOS/Linux 下 id 是 keychain/secret-tool 的 account，改了旧 key 会变空（DPAPI 不受影响，但跨平台一致）；
  - ❌ **不要写入空 `apiKey` 表示"保持"**：`preserve_endpoint_api_keys` 把空串视为"不变"，会让用户看到"未配置"；要么写完整新 key，要么原样保留旧密文；
  - ❌ **不要直写裸 SQL**：绕开 canonicalizer 的 JSON 会带未知字段或漏加密，导致 app 后续 422 或明文 apiKey 落盘。
- **写完后触发 catalog 同步**：调用 `reconcile_endpoint_bindings(CatalogRepository(db), settings, endpoint_id=<新 id>)`，让 routing engine 立刻拿到候选模型；不调则下次启动会补，但首次使用体验会变差。
- **输出一律脱敏**：`sk-****abcd`（只展示前缀 + 末 4 位）；支持包中默认不含明文 key。
- **同用户约束**：DPAPI/keychain/secret-tool 都绑定 OS 用户；跨用户救援工具无法解密现有 apiKey。

**端点写入路径对比**（确认"直写 DB"是唯一可行路径）：

| 路径 | 可行性 | 原因 |
|---|---|---|
| 直写 SQLite（offline，app 关闭） | ✅ | 复用 SettingsRepository + SecretBox + canonicalizer；绕过 local_auth token |
| 调本地 API（带 token） | ⚠️ 不采用 | 必须拿到 `SAGE_LOCAL_AUTH_TOKEN`（从不回传前端）；GET 脱敏读不到真实 key；与主 backend lost-update 风险 |
| 环境变量覆盖端点 | ❌ 不可行 | 无任何 env 作用于聊天主链路；`LLM_*` env 只作用于 embedder/wiki |
| 整库备份替换 | ⚠️ 粒度粗 | 只适合"整库回滚到已知好备份"，不适合"只改端点" |

#### 6.3.2 向导流程

1. 选择「已有端点」或「新建」；
2. 输入 Base URL（给出示例：`http://10.0.0.5:8000/v1`）；
3. 输入 API Key（掩码输入）；
4. 选择协议：`openai-compatible`（默认）/ `anthropic` / `gemini` / `ollama`；
5. 调用 `backend/model_catalog/probes.probe_endpoint` 拉模型列表；失败允许手填 `modelId`；
6. **测试连接**：5s 超时，分类报错（DNS / 拒绝连接 / 超时 / 401 / 404 / 非 JSON）；
7. 保存（备份 + SecretBox 加密 + 更新 `discoveredModels/lastDiscoveredAt`）；
   - **新建端点**：生成新 `id`（参考 `config_tool.py:846-852` 的 id 唯一性策略）；
   - **已有端点改 key/URL**：**保持原 `id` 不变**（macOS/Linux 下 id 是 keychain/secret-tool account，改了旧 key 会变空）；
   - 调用 `reconcile_endpoint_bindings` 同步 catalog，让 routing engine 立刻拿到候选模型。
8. 设为当前聊天模型（更新 `modelSelections`）。

#### 6.3.3 管理员配置包（内网离线分发，M3）

```json
{
  "schema": 1,
  "exportedAt": "2026-11-06T09:00:00Z",
  "endpoints": [
    { "id": "intranet-gw", "name": "内网网关", "baseUrl": "http://10.0.0.5:8000/v1",
      "protocol": "openai-compatible", "apiKey": "sk-...", "modelId": "qwen2.5-7b-instruct",
      "reasoningEffort": null, "thinkingBudget": null }
  ],
  "modelSelections": { "...": { "endpointId": "intranet-gw", "modelId": "qwen2.5-7b-instruct" } }
}
```

- 管理员在联网机器生成，U 盘拷入内网；用户在 doctor 中 `config import`，先展示 diff，确认后写入并立即加密；
- 包内含明文 key 时文件头提示"导入后请删除该文件"；
- 可选 `--secrets-only` 导入（只补 key，不动 URL/模型）。

#### 6.3.4 已知陷阱：localStorage 旧 key 回灌

`src/entities/setting/storage.ts:restoreRedactedApiKeys` 会在后端返回 `hasApiKey=true, apiKey=""` 时，用 localStorage 中同 id 的旧 key 还原。若 doctor 改了**已存在端点的 key**，下次启动前端可能用旧 key 覆盖显示并随聊天请求发给后端。

处理（M1 必须一起做）：

- 给 `EndpointConfig` 增加 `apiKeyUpdatedAt?: number`；doctor 写入 key 时设为当前时间；
- `restoreRedactedApiKeys` 仅在 `localEp.apiKeyUpdatedAt` 不存在或 `>= remote.apiKeyUpdatedAt` 时还原，否则不还原并删除本地缓存中的旧 key；
- 新增前端单测覆盖"doctor 改 key 后旧缓存不得回灌"。

### 6.4 自愈状态机（兼容档位）

#### 6.4.1 档位定义

| 档位 | Chromium / 应用行为 | 适用信号 | 可逆 |
|---|---|---|---|
| L0 正常 | 现有 Win7 flags（`--disable-gpu`、`--in-process-gpu`、`--no-sandbox`、Viz 关闭等） | 默认 | — |
| L1 保守渲染 | 追加 `--disable-gpu-compositing`、`--disable-accelerated-2d-canvas`；关闭桌宠、HTML 预览宿主、内置浏览器桥 | renderer crashed/killed 连续 2 次 | 是 |
| L2 最小窗口 | 追加 `--disable-site-isolation-trials`、减少非核心窗口/定时器；禁用自定义协议预览；仅保留主窗口 | L1 后 10 分钟内再崩溃 | 是 |
| L3 实验单进程 | `--single-process`（仅当 journal 显示 renderer/GPU 子进程被 `killed`） | L2 后仍失败 | 是（默认 7 天后提示复位） |
| 浏览器回退（M3 可选） | 只启动后端 + 用系统浏览器打开 `127.0.0.1:8765` 的救援页 | Electron 渲染被彻底阻断 | 是 |

> 浏览器回退需要后端静态托管前端资源 + 一次性本地票据，涉及安全评审，单列 M3，不阻塞主方案。

#### 6.4.2 触发与恢复

- 计数源：`last-run.json` 的异常退出 + `crash-journal.jsonl` 的 `render-process-gone`/`child-process-gone`；
- 升级：同一档位连续 2 次异常退出（或 10 分钟内 2 次 renderer gone）→ 下次启动升一档，并弹原生对话框说明原因；
- 稳定：本次启动连续运行 ≥ 5 分钟 → 清空连续计数；
- 降档：在 L>0 连续 3 次 clean 启动后**自动降一档**（`stableBoots` 计数，异常退出清零），避免一次误判永久降级；
- 手动：doctor `safe-mode set 0..3|off` 可覆盖；`SAGE_SAFE_MODE` 环境变量供支持人员强制指定。

#### 6.4.3 原生恢复对话框（不依赖 renderer）

在 `app.on('render-process-gone')`（主进程级）与心跳丢失时，由主进程弹出：

```
标题：Sage 窗口意外关闭
说明：检测到前端进程异常退出（第 2 次，疑似被系统管控软件终止）。
按钮：[安全模式重启] [运行修复工具] [生成诊断包] [退出]
```

- 先写 journal，再弹窗（沿用现有"日志先于对话框"约定）；
- 「运行修复工具」`shell.openPath(SageDoctor.cmd)`（以资源管理器方式启动，避免 Electron 父子链）；
- 「生成诊断包」由主进程直接调 `rescue report --json`（不依赖后端）；
- 对话框每 boot 最多弹一次；用户可勾选"不再提示"（写入 compat.json）。

### 6.5 支持包与放行清单

#### 6.5.1 支持包（不依赖后端）

`<userData>/diagnostics/sage-support-YYYYMMDD-HHMMSS.zip`：

```
manifest.json         版本 / OS / locale / bootId / EDR 清单 / 生成时间
doctor.json           rescue diag --json 全量结果
crash-journal.jsonl
last-run.json / boot-state.json / compat.json
logs/*.ndjson         最近 3 天
backend-logs/*.log    最近 3 天
sage-emergency.log
config-summary.json   端点 id/name/baseUrl/model/hasApiKey（无明文 key）
rescue-actions.jsonl
crashdumps/           minidump 文件名+大小；--include-crashdumps 才打包内容
README.txt            怎么发送、隐私说明
```

脱敏：用户名/主机名默认替换；`apiKey`、token、cookie 永不入包；LLM prompt/trace 不在包内（与现有诊断包职责分离）。

#### 6.5.2 放行清单与遗留管控软件处置指引

`allowlist.md` + `allowlist.json`，包含：

- 可执行文件：`Sage.exe`、`resources\python\python.exe`（SHA-256）；
- 进程链：`Sage.exe → python.exe (backend.main)`、renderer/GPU 子进程；
- 目录：安装目录、`%APPDATA%\Sage`、日志目录、备份目录；
- 回环端口：`127.0.0.1:8765`（仅本机）；
- 说明：优先由单位 IT 管理员按制度评估放行；若管控软件已停止维护、IT 无法放行，则引导用户到 §6.7 的主动处置流程。

### 6.7 遗留管控软件处置（主动干预）

> 适用场景：内网管控软件为 2014 年前后开发的遗留产品，厂商已停止维护，IT 无法协助放行。当 Sage 被其拦截且安全模式无法解决时，由用户在知情确认后主动处置。

#### 6.7.1 识别

`sage doctor` / REPL 的 `edr_inventory` 检查扩展为 `security_software`：

- 枚举 `SecurityCenter2`（WMI）中的杀软/管控产品；
- 枚举 `sc query` 服务，匹配常见遗留管控软件服务名（如 `360tray`、`QHSafeTray`、`VrvProtect`、`VRV`、`edrservice`、`TopSecGuard` 等，维护一个可配置的特征表）；
- 枚举注入到 `Sage.exe` / `electron.exe` / `python.exe` 的非系统 DLL（`tasklist /m` 或 `Get-Process -Module`），识别 hook 来源；
- 输出：产品名、服务名、驱动名（如有）、注入模块、是否启用。

识别结果仅用于呈现给用户，不自动执行任何处置。

#### 6.7.1.1 常见遗留产品的拦截机制与对应动作

| 拦截机制 | 典型特征 | 首选动作 | 备注 |
|---|---|---|---|
| 用户态服务/托盘进程 | `sc query` 可见服务；托盘进程常驻 | A 临时结束 → B 停止服务 → C 禁用服务 | 多数 2014 版产品的主控方式 |
| 内核文件/进程过滤驱动 | `fltmc filters` 可见 minifilter；`sc query type= driver` | 停止服务 → `fltmc unload <name>`（需管理员） | 驱动卸载可能需重启；动作 F |
| DLL 注入/hook | `tasklist /m` 显示非系统 DLL 注入到 `Sage.exe` | G 更换启动链/目录、延迟启动；H 环境隔离 | 已注入模块无法安全热卸载，优先"让它不注入" |
| 应用白名单（按路径/哈希） | 进程启动即被终止或无日志消失 | G 复制到白名单外路径/改名/更换父进程；E 修改白名单配置 | 老产品常用路径前缀匹配，改名/换目录即可 |
| 网络过滤（LSP/WFP/代理） | 端点连接被重置/超时 | B/C 停止服务；或配置系统代理绕行 | 需区分"管控软件拦截"与"网络策略" |
| 注册表/文件保护 | 目标目录写入失败、配置文件被回滚 | 更换 userData/安装目录到非保护路径；E 修改保护规则 | 老产品常保护特定系统目录，不保护用户目录 |
| 启动项/计划任务监控 | 服务被停后自动拉起 | D 禁用启动项/计划任务 → 再 B/C | 存在看门狗时需先断 watchdog |

#### 6.7.2 处置动作（按风险从低到高）

| 动作 | 实现 | 风险 | 可逆 |
|---|---|---|---|
| **A. 临时结束进程** | `taskkill /IM <proc> /T`（不 `/F`，先尝试优雅退出） | 低（重启后恢复） | 自动（重启即恢复） |
| **B. 停止服务** | `sc stop <service>` | 低-中（服务控制管理器记录状态） | `sc start` 恢复 |
| **C. 禁用服务** | `sc config <service> start= disabled` | 中（重启后仍禁用） | 记录原 `start=` 值，`sc config` 恢复 |
| **D. 禁用启动项** | 备份并删除 `Run`/`RunOnce`/计划任务中的相关项 | 中 | 备份 `.reg`/任务 XML，提供恢复命令 |
| **E. 修改白名单配置** | 若产品本地有白名单配置文件/注册表键，写入 Sage 安装目录与 `python.exe` 路径 | 中（改厂商配置格式） | 先备份原配置，提供恢复 |
| **F. 禁用内核驱动** | `sc stop <driver>`（需管理员）；不建议 `sc config disabled` | 高（可能导致系统不稳定/蓝屏） | 需重启恢复，提供安全模式引导 |
| **G. 绕过（行为级）** | 更换启动父进程（`explorer.exe` 直接启动）、复制到不同目录/改文件名、延迟启动、分离启动链 | 低-中 | 无状态，删除副本即可 |
| **H. 环境隔离** | 仅对 Sage 使用独立的用户账户/虚拟机/沙箱 | 低 | 删除隔离环境 |

**执行前置条件**（全部满足才允许）：

1. 用户已阅读动作说明并输入 `y` 确认；
2. 非管理员权限时，仅允许 A/G/H；B–F 需要以管理员身份重新运行；
3. 每个动作先备份：服务状态（`sc qc` 输出）、注册表键（`reg export`）、配置文件（复制到 `backups/security/`）；
4. 动作写入 `rescue-actions.jsonl`（含时间、动作、目标、结果、回滚命令）；
5. 动作完成后自动复检 Sage 关键链路（renderer 启动 / 后端 spawn / 端点连通）。

**入口**：控制台 REPL 与原生对话框向导均可触发处置动作。需要管理员权限的动作（B–F）由主进程通过 `ShellExecute(runas)` 或独立的提权助手启动（打包时附带 `SageElevate.exe` 薄壳，或复用 `cmd /c sc ...` 配合 UAC），不以管理员身份常驻运行整个 Sage 进程。

#### 6.7.3 REPL 交互

```
[3] 修复启动问题
  ...
  [7] 处置遗留管控软件
      检测到：VrvProtect 服务（2014 版北信源）、注入模块 VrvHook.dll
      [1] 临时结束进程（重启后恢复）
      [2] 停止服务（可恢复）
      [3] 禁用服务（需管理员，记录原状态）
      [4] 修改白名单配置（先备份）
      [5] 绕过启动链（更换父进程/目录）
      [6] 查看恢复命令
      [q] 返回
```

#### 6.7.4 安全与合规提示

- 控制台与文档必须明确：处置管控软件可能违反单位 IT 管理规定；本工具仅提供能力，是否使用由用户与所在单位自行决定；
- 所有处置动作**默认不做静默执行**，必须显式选择；
- 提供一键恢复：`safe-mode restore-security`（从 `backups/security/` 恢复服务状态/配置/启动项）；
- 不提供"永久删除/卸载"管控软件的选项（超出救援工具边界，且不可逆）。

### 6.8 Electron 侧接线清单

| 文件 | 改动 |
|---|---|
| `electron/crashGuard.ts` | 修 `crashReporter.start`；结构化 journal（字段见 §6.1.2）；保留 emergency log |
| `electron/main.ts` | 启动阶段时间线 + `last-run` 标记；读 `compat.json` 应用 flags/功能裁剪；主进程级 renderer gone 处理器；心跳超时对话框；启动失败对话框增加「运行修复工具」 |
| `electron/heartbeat.ts`（新） | renderer 心跳接收/超时判定（纯逻辑可测） |
| `electron/compatProfile.ts`（新） | compat.json 读写、档位→flags/功能映射（纯函数） |
| `electron/lastRunState.ts`（新） | running/clean/异常退出判定、连续失败计数 |
| `electron/rescueDialogs.ts`（新） | 原生对话框向导；调 `rescue --json` |
| `electron/backendLauncher.ts` | 增加 `resolveRescueLaunchCommand()`（复用 doctor 的解析逻辑） |
| `electron/showStartupFailureDialog.ts` | 增加按钮与 `diagnosticPath` 展示（从 win7 分支对齐） |
| `electron/tray.ts` / `electron/menu.ts` | 增加「运行修复工具」「打开最近诊断报告」 |
| `electron-builder.yml` / `build/installer.nsh` | 打包 `SageDoctor.cmd`；开始菜单快捷方式 |

---

## 7. 涉及文件与模块（预期）

### 新增

```
backend/cli/rescue.py                     # 子命令 + REPL 入口
backend/services/rescue/__init__.py
backend/services/rescue/actions.py        # diag/report/repair/safe-mode 动作层
backend/services/rescue/config_wizard.py  # 端点/模型读写向导（复用 SettingsRepository）
backend/services/rescue/support_bundle.py # zip 打包 + 脱敏
backend/services/rescue/allowlist.py      # 放行清单生成
backend/services/rescue/security_software.py # 遗留管控软件识别/处置/回滚（§6.7）
backend/services/rescue/compat_profile.py # compat.json schema/档位（与 Electron 纯逻辑对齐）
backend/cli/checks/{packaged_runtime,db_integrity,endpoint_reachability,crash_history,security_software,port_ownership,data_dir_paths}.py
electron/heartbeat.ts
electron/compatProfile.ts
electron/lastRunState.ts
electron/crashJournal.ts
electron/rescueDialogs.ts
resources/SageDoctor.cmd
docs/technical/144-win7-rescue-doctor.md   # 已完成归档
docs/user-manual/45-win7-rescue-tool.md    # 已完成归档
```

### 修改

```
backend/cli/doctor.py                     # 允许 rescue 复用注册表；TTY 编码策略
backend/tools/config_tool.py              # 抽出可共享的字段白名单/校验（行为不变）
backend/tools/permissions.py              # （如新增工具则登记；CLI 不涉及）
electron/crashGuard.ts / main.ts / backendLauncher.ts / showStartupFailureDialog.ts / tray.ts / menu.ts
electron-builder.yml / build/installer.nsh / package.json（无新依赖）
src/entities/setting/types.ts / storage.ts # apiKeyUpdatedAt 防回灌（§6.3.4）
```

---

## 8. 实施步骤

### M0 通用自检修基础设施（P0，M1 的前置依赖）—— 已落地

- [x] 修复 `crashReporter.start`（`uploadToServer:false`），确认 Crashpad 产出 dump
- [x] `last-run.json` + 启动阶段时间线 + `first_paint` IPC
- [x] `crash-journal.jsonl`（renderer/child gone、心跳丢失、EDR 快照）
- [x] `doctor-last.json` 稳定落盘（`<userData>/diagnostics/`）
- [x] 新增 7 项检查（§6.1.4）
- [x] `rescue report` v0：纯 Python 打包日志/journal/doctor，不依赖后端

**验收**：REPL 工具可生成支持包，包含足够的信息用于通用故障分类（渲染被杀/自身崩溃/后端被杀/补丁缺失/可执行文件阻断中的哪一类）。

### M1 修复工具 MVP（P0，用户主诉求）—— 已落地

- [x] `backend/cli/rescue.py`：子命令 + REPL 编号菜单 + `--json`
- [x] `config list/add/update/remove/test/use/import/export`（备份 + SecretBox + 白名单校验）
- [x] `repair cache/window/logs/port/config/db`（每个动作幂等、先备份、先确认）
- [x] `SageDoctor.cmd` + NSIS 开始菜单快捷方式；打包版路径解析（`resources/python`、`SAGE_USER_DATA_DIR`）
- [x] TTY 编码策略（cp936 交互 / UTF-8 管道），Py3.8 兼容
- [x] `apiKeyUpdatedAt` 防 localStorage 回灌（前端小改 + 单测）
- [x] 「运行修复工具」入口：启动失败对话框 / 托盘 / 菜单

**验收**：在一台没有 conda、只有安装包产物的 Win7 机器上，双击开始菜单即可配置内网端点并测试成功；无需任何开发者环境。

### M2 自愈（P1）—— 核心已落地，自动化降档待补

- [x] `compat.json` + 档位映射（纯函数 + 单测）
- [x] crash-loop 计数与自动升档（上次异常退出 → 升一档）
- [x] 连续 3 次 clean 启动自动降一档（`stableBoots`）
- [x] 主进程级 renderer gone → 原生恢复对话框（安全模式重启/修复工具/诊断包/退出）
- [x] 心跳超时 → 同一对话框（每 boot 一次；心跳丢失也标记 unclean）
- [x] 功能裁剪：桌宠、HTML 预览宿主、内置浏览器桥、更新启动健康检查（L1–L3）
- [ ] 修复 `loadFile` 失败对话框"重试"空操作（待补）

**验收**：用 `webContents.forcefullyCrashRenderer()` 模拟连续崩溃，第二次启动自动进入 L1，对话框可一键切安全模式/生成诊断包。

### M3 协作、处置与回退（P1/P2）—— 处置已落地，回退待评估

- [x] `allowlist` 放行清单（SHA-256 + 进程链 + 目录 + 端口）
- [x] 管理员配置包导入/导出（diff 预览、明文提示、导入即加密）
- [x] **遗留管控软件处置**（§6.7）：
  - [x] `security_software` 识别（服务/进程/注入模块特征表）
  - [x] 动作 A–E（结束进程 / 停止服务 / 禁用服务 / 禁用启动项（建议）/ 修改白名单配置（建议））
  - [x] 动作 G（绕过启动链建议）/ H（环境隔离建议）
  - [ ] 动作 F（禁用内核驱动）—— 需管理员 + 强警告 + 安全模式引导，最后实现
  - [x] 备份与一键恢复：`security restore`
  - [x] `rescue-actions.jsonl` 审计与回滚命令输出
- [ ] （可选）浏览器回退模式：后端静态托管 + 一次性本地票据 + 安全评审
- [ ] `Sage.exe --doctor`（ELECTRON_RUN_AS_NODE）备选入口评估

### M4 现场验证与归档（P0，发布前）

- [ ] Win7 + 实际管控软件 pilot：连续 3 台机器验证闪退可观测、可恢复、可放行
- [ ] `release/win7` cherry-pick（Py3.8 + `requirements-py38.txt`；两分支独立基线数值）
- [ ] 用户手册（含截图、开始菜单入口、配置向导、放行清单交给谁）
- [ ] 技术文档归档；计划文档删除

---

## 9. 测试与验收

| 层级 | 用例 |
|---|---|
| 单元（Python） | `rescue config` 读写 roundtrip（含 SecretBox 加密断言、备份生成）；`repair` 幂等；支持包脱敏；`compat_profile`/`last_run` 纯逻辑；Py3.8 兼容（CI 双环境） |
| 单元（TS） | `compatProfile` 档位→flags 映射；`lastRunState` 异常退出判定；`crashJournal` 字段完整性；心跳超时；`restoreRedactedApiKeys` + `apiKeyUpdatedAt` 回归 |
| 集成 | doctor 新检查用临时 DB/目录；`rescue --json` 退出码；打包路径解析（`resources/python` mock） |
| E2E | Electron：`forcefullyCrashRenderer` → 计数/升档/对话框；启动失败对话框新按钮；`SAGE_SAFE_MODE=1` 功能裁剪 |
| 人工（Win7） | 开始菜单启动修复工具 → 配置端点 → 测试连接 → 保存 → 启动 Sage 聊天成功；撤销/复位档位；诊断包可打开 |

CI 门禁：沿用现有 coverage/architecture-baseline；新增 Python 文件纳入 ruff/mypy/py38 兼容扫描。

---

## 10. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 根因未知，可能不是 EDR 而是旧补丁/GPU | 方案打偏 | M0 提供通用故障分类；安全模式逐级试错不依赖根因；现场包仅用于后续调优 |
| 管控软件同时禁用 cmd/脚本 | REPL 不可用 | 原生对话框向导兜底（§6.4.3）；若对话框也被拦截，走 §6.7 处置 |
| EDR 拦截 `resources\python\python.exe` | 修复工具与后端都无法运行 | 放行清单 + §6.7 处置（结束/停止/禁用/绕过）；这是主动处置的主要场景 |
| 配置写入与前端 localStorage 冲突 | key 被旧缓存覆盖 | §6.3.4 `apiKeyUpdatedAt` 方案 + 单测 |
| 并发写 DB | 配置丢失/锁 | 强制 Sage 未运行 + 备份 + 短事务 + `quick_check` |
| Win7 控制台编码 | 中文乱码/异常退出 | TTY/管道双策略；不用盒线字符；Py3.8 兼容 |
| `--single-process` 不稳定 | L3 本身崩溃 | 仅实验档、可一键复位、不默认启用 |
| 安全边界/合规风险 | 处置遗留管控软件可能违反单位 IT 管理规定 | 默认不执行；动作前展示风险声明并需显式确认；全程审计与一键恢复；不提供永久删除/卸载 |
| 处置动作导致系统不稳定 | 禁用内核驱动可能蓝屏 | 动作 F 最后实现、需管理员、强警告、提供安全模式恢复引导；优先 A–E/G–H 低风险动作 |
| 双分支实现漂移 | win7 失配 | main 首发后 cherry-pick；Py3.8 CI；两分支独立架构基线 |

依赖：`backend.cli.doctor` 注册表、`SettingsRepository`/SecretBox、`model_catalog.probes`、现有 NSIS 打包链。无新增第三方依赖。

---

## 11. `SageDoctor.cmd` 参考实现

```bat
@echo off
rem Sage 修复工具启动器（由 electron-builder extraFiles 放入安装目录）
setlocal
set "ROOT=%~dp0"
set "SAGE_IS_PACKAGED=1"
set "SAGE_USER_DATA_DIR=%APPDATA%\sage"
set "SAGE_DB_PATH=%APPDATA%\sage\sage.db"
set "PYTHONPATH=%ROOT%resources\backend;%ROOT%resources\sage-core"
"%ROOT%resources\python\python.exe" -m backend.cli.rescue %*
if errorlevel 1 (
  echo.
  echo 修复工具异常退出，请截图本窗口并附上：
  echo   %SAGE_USER_DATA_DIR%\diagnostics\
)
pause
```

> 交互模式由 `rescue.py` 自行按控制台代码页输出；不强制 `PYTHONUTF8`，避免 Win7 光栅字体乱码。

---

## 12. 可选打磨：特定 EDR 产品体验优化

> 下列信息**不是实现阻塞项**——方案的核心能力（REPL 工具、配置逃生舱、安全模式档位、原生对话框）在所有场景下通用可用。拿到以下信息后，可以针对性打磨特定产品的体验，属于 M4 阶段的锦上添花。

1. 管控软件的名称/版本（如 360 天擎、深信服 EDR、奇安信、北信源等）与策略类型：
   - 可加入特定产品的启发式检测（例如识别"天擎进程注入模式"并直接跳到 L2）；
   - 可为已知产品预置放行清单模板；
2. 故障机器的 `%APPDATA%\Sage\sage-emergency.log`、`logs/*.ndjson`、`Crashpad` 目录：
   - 可用于回归测试和档位阈值调优；
   - 没有也能跑（REPL 工具 + 原生对话框覆盖所有通用场景）；
3. 内网是否允许用户打开 `cmd.exe` / 运行未签名脚本：
   - 如不允许，原生对话框向导（§6.4.3）已覆盖；
   - 如允许，REPL 提供更丰富的交互；
4. IT 是否允许按清单放行：
   - 如允许，生成标准放行清单；
   - 如不允许（遗留产品无人维护），走 §6.7 主动处置流程；
5. 端点是否统一由管理员下发：决定"管理员配置包"优先还是"手工向导"优先。

**实现顺序**：M0 → M1 → M2 不依赖上述任何信息；M3/M4 在拿到 1–2 项后可针对性优化，但不阻塞发布。

---

## 参考：主流产品对应能力

| 产品 | 对应做法 | Sage 借鉴点 |
|---|---|---|
| Claude Code | `claude doctor`、`/status`、`/config` | 确定性命令 > 聊天提示词；检查项带修复建议 |
| VS Code | 崩溃后"以安全模式重新打开"；`--status` | 连续崩溃→降级重启；不依赖 renderer 的入口 |
| Chrome / Electron | Crashpad minidump；"页面崩溃，重新加载" | 修复 dump 采集；心跳与恢复对话框 |
| Flutter / Docker | `flutter doctor` / 诊断包 | 分级检查 + 支持包一键生成 |
| Windows 安全模式 | 最小驱动/服务启动 | 兼容档位状态机 |
