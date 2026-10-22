# R87 Electron smoke 新 Windows 镜像修复 spec

## 背景与证据

- PR #2206 合并后，main 的 Electron smoke 在 GitHub `windows-2025-vs2026` 新镜像 `20261018.275` 上持续失败；同一 tree 在旧镜像 `20261007.264` 上 2 passed。
- 失败 job 的主进程日志证明 `dist/index.html` 已生成且可读（2426 bytes、含 `<script>`），因此不是构建产物缺失。
- `loadFile` 开始约 3 秒后，renderer 以 `render-process-gone: crashed, exitCode=-1073741819` 退出；该 exitCode 对应 Windows `0xC0000005`（access violation）。随后 `loadFile` 返回 `ERR_FAILED (-2)`，Playwright `firstWindow` 超时。
- Sage 固定 Electron 21.4.4 以支持 Win7 LTS。现代 Windows 上当前产品策略是启用 Chromium sandbox；但新 Windows runner 构建与旧 Chromium sandbox 初始化的组合已在同类 Electron 问题中被 A/B 隔离为 `--no-sandbox` 可恢复、`--disable-gpu-sandbox` 不足。

## 目标

让 `e2e/electron/smoke.spec.ts` 在新 `windows-latest` 镜像上也能验证：Electron 启动、主窗口出现、preload 暴露 `electronAPI`、前端 HTML 加载、IPC 桥往返。

## 方案与边界

- 只改 smoke 测试启动面：Playwright `_electron.launch` 在主进程入口前传 `--no-sandbox`，并在子进程 env 设置既有逃生门 `SAGE_NO_SANDBOX=1`，使 `electron/main.ts` 的 `NEEDS_NO_SANDBOX` 分支同时关闭 `webPreferences.sandbox`。
- 不改产品默认安全策略：普通用户启动不设置 `SAGE_NO_SANDBOX`，现代平台仍启用 sandbox；不改 `electron/main.ts` 的 GPU/Win7 兼容 flags。
- 不处理 Win7 Sync parity，也不处理 Backend unit (Windows) 的 3 个路径断言失败；两者均为合并前已存在的问题，另行开轮。

## 验收

1. `e2e/electron/smoke.spec.ts` diagnostics 为 0，类型检查覆盖该文件时无新增错误。
2. PR CI 的 Electron smoke job 成功；必须回读 job 日志确认 runner 镜像。若成功 job 落在旧镜像 `20261007.264`，不得宣称新镜像已修复，应重跑该 job 或等待新镜像样本。
3. PR 其余 checks 无新增失败。
