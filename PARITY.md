# Sage 对齐标准 (PARITY.md)

> 定义 Sage 各子系统间的状态一致性标准和验证机制。

> **ⓘ 状态（2026-09-23 事实核对）**：本文最初为 2026-06-20（Tauri 时代）的
> 设计草案，其中「WebSocket 推送」「多设备同步」「parity/health 端点」等
> 内容**从未实现**。本次已按真实实现重写 §1 与 §4，未实施的远期设计集中
> 移入 §5 并明确标注。引用本文时以 §1 为准。

---

## 概述

PARITY.md 定义了 Sage 项目中不同子系统之间必须保持的一致性约束：

- **前后端状态同步**：前端 UI 状态与后端数据保持一致
- **可验证性**：所有对齐标准都可自动化验证

**真实通信拓扑**（三条链路，无 WebSocket）：

| 链路 | 通道 | 实现 |
|---|---|---|
| 渲染层 → 主进程 | IPC `sage:invoke`（请求）/ `sage:listen`（事件订阅，`sage:event:` 前缀通道） | `electron/preload.ts` 经 contextBridge 暴露 |
| 主进程 → 后端 | HTTP `127.0.0.1:8765`（`PYTHON_BACKEND_PORT` 可覆写） | `electron/backendLauncher.ts` + `backendSupervisor.ts` |
| chat 流式响应 | POST `/chat/stream` 取 streamId → GET NDJSON → `webContents.send` 转发 | `electron/relay.ts` + `eventRouting.ts` |

---

## 1. 后端与前端状态一致性（现行实现）

### 1.1 记忆条目

| 对齐项 | 后端状态 | 前端状态 | 同步机制（真实） |
|--------|----------|----------|----------|
| 记忆列表 | `backend/memory/manager.py`（REST `/api/v1/memory/*`） | `memoryApi.getMemories()` → 页面级加载 | REST 拉取 + 变更后重新拉取/回填 |
| 记忆创建/更新/删除 | 同上 REST 变更端点 | 变更成功后本地 store/页面状态更新 | REST 响应回填，无服务端推送 |
| 记忆召回（chat 内） | 注入/召回在 chat 流内完成 | `store.memory_refs` / `memory_applied`（流事件携带） | NDJSON 流事件经 relay 转发 |

### 1.2 会话状态

| 对齐项 | 后端状态 | 前端状态 | 同步机制（真实） |
|--------|----------|----------|----------|
| 会话列表 | `SessionRepository.list()`（REST） | Zustand store `sessions[]`（`loadSessions()`） | REST 拉取；排序在后端 SQL（pinned > running > 新序） |
| 活跃会话 | 由前端持有（`currentSessionId`） | Zustand store | 前端单一事实源，切换即 IPC 调用后端读写消息 |
| 消息历史 | `SessionRepository` 分页（REST） | store `messages[]` | REST 分页加载 |
| 流式输出 | NDJSON 事件流 | `chatStreamStore` | relay：`/chat/stream` NDJSON → 主进程 → `webContents.send` |

### 1.3 配置状态

| 对齐项 | 后端状态 | 前端状态 | 同步机制（真实） |
|--------|----------|----------|----------|
| 模型端点/偏好 | `settings` REST + SQLite | `settingsStore`（`useSettings`） | REST 读写；变更经 `settingsClient` 持久化 |
| 主题/语言 | 前端持有（theme_storage / i18n） | Zustand store + localStorage | 前端单一事实源 |

---

## 2. 验证机制（现行实现）

### 2.1 自动化测试

| 层 | 通道 | 覆盖的状态契约 |
|---|---|---|
| Vitest（jsdom） | `src/**/*.test.tsx`（~405 文件） | store 更新、API envelope 契约、组件状态渲染 |
| Playwright stub | `electron-stub-smoke/deep`（PR 门禁） | UI 流程 × stub 后端（不真连模型） |
| Playwright live | `electron-live-boot/deep`（nightly/release） | 真实后端启动 + 冒烟 |
| 后端 pytest | coverage ≥ 80% 强门禁；win7 线另有 py38 job | 服务层契约 |

> 原 §4.1 的 `tests/parity/` 目录与 §4.3 的 `GET /api/v1/parity/health`
> 端点**未实施**；状态契约验证由上表通道承担。

### 2.2 运行时监控

- 后端启动埋点（R22-D7）与结构化日志（`electron/logRotate.ts` 分级轮转）
- 依赖契约审计：CI `dependency-audit` job（npm audit + pip-audit + environment.yml 漂移校验）

---

## 3. 冲突解决策略（现行实现）

- **会话/消息**：乐观并发 hash 保存（ArtifactViewer 编辑路径），冲突以服务端最新为准并提示刷新
- **配置**：last-write-wins（设置页单项写入即生效）
- **多设备/离线同步**：见 §5（未实施）

---

## 4. 实施检查清单（现状）

### 已落地
- [x] REST 契约测试（前端 vitest + 后端 pytest 双侧）
- [x] chat NDJSON 流断连续传（`after_seq` 游标，orch 与 arena JobConsole）
- [x] 依赖契约审计（CI dependency-audit）
- [x] 分层 E2E 门禁（stub-smoke/deep + live-boot 分 PR/nightly/release 通道）

### 未实施（远期设计，见 §5）
- [ ] WebSocket/服务端推送（当前为 REST 拉取 + 流式 relay，够用）
- [ ] `/api/v1/parity/health` 聚合健康端点
- [ ] 多设备发现与同步（mDNS / 云端注册）
- [ ] 离线缓存（IndexedDB）与同步冲突解决 UI

---

## 5. 未实施的远期设计（原 §2/§3/§4.3 保留备查）

> 以下为 2026-06-20 草案的远期设想，**当前代码库中不存在对应实现**，
> 引用前务必核对。若未来启动多设备/离线方向，从这里接续。

### 5.1 离线记忆（原 §2.1）
IndexedDB 本地缓存变更、上线同步、时间戳冲突检测与用户裁决。

### 5.2 多设备同步（原 §3）
mDNS/DNS-SD 设备发现、云端注册中心、版本号 diff 同步协议。

### 5.3 parity/health 聚合端点（原 §4.3）
`GET /api/v1/parity/health` 返回 memory_sync/session_sync 一致性检查结果。

---

## 6. 故障排查（按真实链路）

### 问题 1：前端状态不同步
1. 渲染层 → 主进程：确认 `sage:invoke` 通道有响应（DevTools console 看 electronAPI 错误）
2. 主进程 → 后端：确认 8765 端口进程存活（`backendSupervisor` 世代管理 + `orphanBackendKiller` 清理）
3. 流式路径：`electron/relay.ts` 的 NDJSON 拉取是否断流（`after_seq` 续传语义兜底）
4. store 更新逻辑：变更后是否触发重新拉取（页面级加载模型，无服务端推送）

### 问题 2：流式输出中断
1. 看 relay 日志（`sage:event:` 通道是否持续收到帧）
2. 后端 job 事件端点为批量回放型 NDJSON——断连后靠 `after_seq` 游标续传
3. 长任务挂起参考 arena JobConsole 的 2s 轮询模式

---

## 7. 参考

- [设计哲学](./PHILOSOPHY.md) - 透明可控原则
- [验证映射 g005](./docs/verification/g005-frontend-state.md) - 前端状态契约
- [验证映射 g006](./docs/verification/g006-api-contracts.md) - API 契约

---

**创建时间**：2026-06-20
**事实核对与重写**：2026-09-23
**维护者**：Sage 团队
