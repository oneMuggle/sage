# 29. Electron 桌面日志

**最后更新**: 2026-07-02
**适用版本**: Sage v0.4+

## 29.1 概述

Sage 桌面壳(Electron 主进程 + React 渲染进程)使用 electron-log 4.x 作为底层引擎,封装项目内的 `electron/logger.ts`,把所有日志以 NDJSON 格式写入 `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson`。

## 29.2 三层日志架构

### 主进程
- 入口: `electron/logger.ts`(包 electron-log)
- 调用方: `electron/main.ts` 第 2-3 行初始化,~14 处 console.* 替换为 logger.*
- 触发场景: backend spawn / IPC handler / 启动失败 / 进程退出

### 渲染进程
- 入口: `src/shared/log/client.ts`(fire-and-forget IPC 客户端)
- 调用方: `ErrorBoundary.tsx` + 关键 fetch 失败 + 未来 hooks
- 触发场景: React 组件崩溃 / API 调用失败

### IPC 桥接
- 入口: `electron/ipc/logIpc.ts`
- 通道: `sage:log:write`
- 限速: 100 msg/sec per sender(超出丢弃)

## 29.3 文件格式

每行一个 NDJSON 对象:
```json
{"ts":"2026-07-02T10:23:11.456Z","level":"info","source":"main","msg":"backend ready","meta":{"port":8765}}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| ts | string | ISO 8601 UTC,毫秒精度 |
| level | enum | debug / info / warn / error |
| source | enum | main / renderer / preload / backend |
| msg | string | 人类可读消息 |
| meta | object? | 可选,JSON-safe,循环引用 fallback 为字符串 |

## 29.4 路径

| 平台 | 路径 |
|---|---|
| Windows | `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson` |
| macOS | `~/Library/Application Support/sage/logs/sage-YYYY-MM-DD.ndjson` |
| Linux | `~/.config/sage/logs/sage-YYYY-MM-DD.ndjson` |

## 29.5 保留策略

- 每天一个文件(按本地日期)
- 启动时清理 >7 天的文件(`cleanupOlderThan(7)`)
- 单文件 >10MB 自动切到 `.1` 后缀
- 用户可在设置页 「诊断与日志」 卡片点 「立即清理旧日志」 按钮强制清理

## 29.6 启动优先级

`SAGE_LOG_LEVEL` env > `userData/config.json` 持久化值 > 默认 `info`

## 29.7 三个用户入口

| 入口 | 位置 | 行为 |
|---|---|---|
| 菜单 | 帮助 → 打开日志目录 | shell.openPath(logDir) |
| 菜单 | 帮助 → 复制日志路径 | clipboard.writeText(logDir) |
| 设置页 | /settings → 诊断与日志 卡片 | 列出文件 + 4 个按钮 + 级别选择 |
| 启动失败对话框 | 启动失败时自动弹 | 打开日志目录 / 重试 / 退出 |

## 29.8 测试覆盖

| 文件 | 验证 |
|---|---|
| electron/__tests__/logger.test.ts | NDJSON 格式 / 级别过滤 / meta 序列化 / append 不覆盖 |
| electron/__tests__/logPaths.test.ts | 路径解析 + 目录创建 |
| electron/__tests__/logRotate.test.ts | 7 天清理 + 文件识别 |
| electron/__tests__/logIpc.test.ts | renderer 转发 + rate limit |
| electron/__tests__/menu.test.ts | 菜单结构 + 点击行为 |
| electron/__tests__/showStartupFailureDialog.test.ts | 对话框内容 + logger 先于 dialog |
| src/shared/log/__tests__/client.test.ts | fire-and-forget + IPC 失败静默 |
| src/widgets/settings/__tests__/DiagnosticsCard.test.tsx | 列表 + 按钮 + 级别切换 |

## 29.9 Win7 启动失败排查流程

1. 用户双击 Sage.exe 无反应
2. 自动弹 「Sage 启动失败」 对话框
3. 用户点 「打开日志目录」 → 资源管理器打开 `%APPDATA%/sage/logs/`
4. 用户点 「复制日志路径」 → 粘贴到反馈中
5. 维护者收到路径 → `tail -f` 最新文件 → 用 grep 找 `level=error` 行
6. 常见错误:
   - `backend: stderr` 含 Python ImportError → conda env 缺包
   - `loadFile failed` 含 ENOENT → 安装包损坏,重装
   - `uncaughtException` 含 GPU 错误 → 调整 `app.disableHardwareAcceleration()`