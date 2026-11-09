# 144. Win7 内网救援工具（Rescue Doctor）与启动看门狗

**最后更新**: 2026-11-08
**适用分支**: main + release/win7
**关联文档**: [20 Electron](./20-electron.md)、[29 Electron 日志](./29-electron-logging.md)、[31 Win7 LTS](./31-win7-lts.md)、[41 sage doctor](./41-sage-doctor.md)

---

## 144.1 背景

内网 Win7 现场常见问题：终端管控/EDR 软件拦截 Electron 前端（终止 renderer/GPU 子进程、注入 hook、阻断未签名可执行文件），导致 Sage 启动闪退；前端崩溃后用户没有任何入口配置端点/模型或查看原因。

本特性提供一个**不依赖前端/renderer 的通用自检修基座**：

- 终端 CLI（`SageDoctor.cmd` → `backend.cli.rescue`）用于体检、配置端点/模型、修复、生成诊断包；
- Electron 主进程的启动看门狗（last-run、崩溃 journal、心跳、原生恢复对话框）；
- 兼容档位（安全模式 L0–L3）在连续异常退出时自动升级；
- 遗留管控软件处置（用户显式确认后停止/禁用服务、备份/恢复）。

> 本工具默认只做应用侧降级与取证；主动处置遗留管控软件是显式选择的能力，不静默执行、不修改安全软件配置以外的系统状态。

## 144.2 组成模块

### 后端（Python，stdlib + 项目内模块）

| 路径 | 职责 |
|---|---|
| `backend/cli/rescue.py` | CLI 子命令 + 中文编号 REPL |
| `backend/services/rescue/paths.py` | userData / DB / diagnostics / backups 路径解析（env 优先） |
| `backend/services/rescue/config_wizard.py` | 端点/模型离线读写：`SettingsRepository` + SecretBox + canonicalizer 校验 + catalog 同步 |
| `backend/services/rescue/support_bundle.py` | 支持包 zip（日志/journal/doctor/脱敏配置摘要/EDR 清单），不依赖后端 |
| `backend/services/rescue/compat_profile.py` | 兼容档位 schema + 纯逻辑（与 Electron 镜像） |
| `backend/services/rescue/security_software.py` | 遗留管控软件识别（服务/进程/注入模块）+ 处置 + 备份恢复 |
| `backend/services/rescue/repair.py` | 缓存/窗口/日志/孤儿端口/DB/配置重置 |
| `backend/services/rescue/allowlist.py` | 给 IT 的放行清单（路径/进程链/端口/SHA-256） |
| `backend/cli/checks/rescue_checks.py` | 新增 6 项 doctor 检查（DB/端点/崩溃史/管控软件/端口/数据目录） |
| `backend/cli/checks/packaged_runtime.py` | 打包模式 resources 完整性检查 |

### Electron（主进程）

| 路径 | 职责 |
|---|---|
| `electron/lastRunState.ts` | 启动阶段时间线 + clean/unclean 判定 + crash streak |
| `electron/crashJournal.ts` | 结构化崩溃事件 NDJSON |
| `electron/compatProfile.ts` | 兼容档位读取/写入/档位→flags/功能映射 |
| `electron/heartbeat.ts` | renderer 心跳超时纯逻辑 |
| `electron/rescueDialogs.ts` | 原生恢复对话框 + 打开修复工具 + 运行诊断包 |
| `electron/main.ts` | 接线：启动阶段、崩溃 journal、心跳、恢复对话框、doctor-last、功能裁剪 |
| `electron/crashGuard.ts` | 修复 `crashReporter.start`（`uploadToServer:false`），恢复 minidump |
| `resources/SageDoctor.cmd` + `build/installer.nsh` | 安装目录启动器 + 开始菜单「Sage 修复工具」 |
| `electron-builder.yml` | `extraFiles` 打包 `SageDoctor.cmd` |

## 144.3 数据文件

均在 `<userData>/diagnostics/`（打包模式 = `%APPDATA%\Sage\diagnostics`）：

| 文件 | 内容 | 时间格式 |
|---|---|---|
| `last-run.json` | `{schema, bootId, appVersion, electron, startedAt, startedAtMs, stage, stages:[[stage,ms]], endedAt, endReason, safeModeLevel}` | ISO 8601 UTC + 相对 ms |
| `crash-journal.jsonl` | 每行 `{ts, bootId, appVersion, electron, event, reason, exitCode, type, rendererPid, serviceName, killed, windowAgeMs, url, route, safeModeLevel, edr}` | ISO 8601 UTC |
| `compat.json` | `{schema, level, flags, app:{petWindow,previewHost,browserBridge,updateCheck}, reason, updatedAt, stableBoots?}` | ISO 8601 UTC |
| `doctor-last.json` | 最近一次 doctor 报告（`status/summary/checks/stderr/exitCode/elapsed_ms`）+ `generatedAt` | ISO 8601 UTC |
| `rescue-actions.jsonl` | 处置动作审计（`clear_caches` / `reset_config` 等） | ISO 8601 UTC |
| `sage-support-*.zip` | 支持包（日志/journal/doctor/脱敏配置摘要/EDR 清单） | 文件名时间戳 |
| `Crashpad/` | minidump（由 Electron crashReporter 管理） | — |

备份：`<userData>/backups/sage-backup-*.db`（DB）、`<userData>/backups/security/service-*.json`（服务状态）、`<userData>/backups/logs/*.ndjson`（截断前日志）。

## 144.4 CLI

```text
python -m backend.cli.rescue                 # REPL（默认）
python -m backend.cli.rescue diag [--json]
python -m backend.cli.rescue config list|add|update|remove|test|use|import|export
python -m backend.cli.rescue repair cache|window|logs|port|config|db
python -m backend.cli.rescue report [--include-crashdumps] [--include-hostname]
python -m backend.cli.rescue security detect|stop|disable|restore|plan
python -m backend.cli.rescue safe-mode status|set 0-3|off
python -m backend.cli.rescue allowlist [--output PATH]
```

退出码：`0` OK / `1` 警告或部分失败 / `2` 严重错误或未确认。

打包模式由 `SageDoctor.cmd` 注入：

- `SAGE_USER_DATA_DIR=%APPDATA%\Sage`
- `SAGE_DB_PATH=%APPDATA%\Sage\sage.db`
- `PYTHONPATH=<install>\resources\backend;<install>\resources\sage-core`
- 运行 `<install>\resources\python\python.exe`

## 144.5 端点/模型配置

- **唯一真相源**：SQLite `preferences.app_settings`（camelCase；白名单 `LEGAL_ENDPOINT_KEYS`）。
- 写路径：`SettingsRepository.set_json` → SecretBox（Windows DPAPI）自动加密 `apiKey`。
- 写前：`create_backup("rescue")` 备份 DB。
- 写后：`validate_settings_shape` + `validate_settings_payload` + `reconcile_endpoint_bindings`。
- **不要改 `endpoint.id`**（macOS/Linux 下 keychain/secret-tool account 绑定 id，改了旧 key 会变空）。
- **不要写空 apiKey 表示"保持"**：按 id 保留原 key。
- 新增 `apiKeyUpdatedAt`（ms epoch）：前端 `restoreRedactedApiKeys` 在远程时间戳更新时不回灌 localStorage 旧 key。

## 144.6 兼容档位（安全模式）

| 档位 | 追加 flags | 功能裁剪 |
|---|---|---|
| L0 | 无 | 全部开启 |
| L1 | `disable-gpu-compositing`, `disable-accelerated-2d-canvas` | 桌宠关、HTML 预览关 |
| L2 | L1 + `disable-site-isolation-trials` | + 内置浏览器桥关 |
| L3 | L2 + `single-process`（实验） | + 更新启动健康检查关 |

- 触发：上次运行被判定为 unclean（无 `clean_exit`）→ 下次启动升一档（上限 L3）。
- 手动：`safe-mode set 0-3|off`；环境变量 `SAGE_SAFE_MODE=0-3` 强制。
- 恢复对话框：renderer gone / 心跳丢失时，主进程弹「安全模式重启 / 运行修复工具 / 生成诊断包 / 退出」。
- 心跳：renderer 每 15s `sage:heartbeat`；60s 无心跳 → journal `frontend-heartbeat-lost` + 对话框（每 boot 一次）。`SAGE_HEARTBEAT_DISABLED=1` 可关闭。

## 144.7 遗留管控软件处置（安全边界）

- 识别：`sc query` 已知服务名、`tasklist` 进程、`tasklist /m` 注入模块（仅 Windows；失败 fail-open）。
- 动作（按风险）：结束进程 → 停止服务 → 禁用服务（备份原 start type）→ 禁用启动项/修改白名单配置（建议）→ 绕过启动链/环境隔离（建议）。
- **所有动作必须用户确认**（`confirm=True`），非 Windows 返回 `unsupported`。
- 备份写入 `backups/security/service-*.json`；`security restore` 按备份恢复原启动类型。
- 不提供永久删除/卸载；不修改内核驱动（高风险，需单独评审）。
- 审计：`rescue-actions.jsonl` + 每个 `ActionResult.rollback` 输出回滚命令。

## 144.8 测试

| 层 | 文件 |
|---|---|
| Python 服务 | `backend/tests/unit/services/test_rescue_{config_wizard,support_bundle,compat_profile,security,repair}.py` |
| Python CLI | `backend/tests/unit/cli/test_rescue_cli.py` |
| Doctor 契约 | `backend/tests/unit/cli/test_doctor.py`（检查数 25）、`backend/tests/integration/test_doctor_cli.py` |
| 设置契约 | `backend/tests/contract/test_settings_schema_parity.py`（`apiKeyUpdatedAt` + snake 别名） |
| Electron 纯逻辑 | `electron/__tests__/{lastRunState,compatProfile,heartbeat,crashJournal,rescueDialogs}.test.ts` |
| Electron 对话框 | `electron/__tests__/showStartupFailureDialog.test.ts`（4 按钮） |
| 前端设置 | `src/entities/setting/__tests__/storage-restore-redacted.test.ts`（apiKeyUpdatedAt 回归） |

## 144.9 已知限制 / 后续

- 浏览器回退模式（仅后端 + 系统浏览器）未实现，需安全评审。
- 内核驱动禁用（动作 F）未实现。
- 自动降档：连续 3 次 clean 启动自动降一档（已实现，无询问对话框）。
- `Sage.exe --doctor`（`ELECTRON_RUN_AS_NODE`）备选入口未评估。
- CLI 在 cmd 被策略禁用时不可用；依赖 Electron 原生对话框兜底。
- 管控软件特征表只覆盖常见遗留产品；未知产品需手动输入服务名/进程名。
