# 后台任务可靠性收尾 · Phase 4（PID 强校验 / Webhook 签名与重试）

> 日期：2026-11-06
> 分支：`feat/background-task-phase4`（main）；win7 同步另起分支
> 状态：实施中

## 背景

Phase 3 交付后遗留两项可靠性缺口（见 Phase 3 plan「后续」）：

1. **PID 复用弱校验**：Windows 恢复仅 `tasklist` 探测存活；POSIX 仅 pgid
   校验。极端情况下重启后 PID 被复用，可能把无关进程当作自己的后台 shell。
2. **Webhook 无签名 / 无重试**：接收方无法验证来源；瞬时失败即丢通知。

TaskCenter 后台任务面板 UI 增强留到 Phase 5（范围较大，独立 PR）。

## Item A: PID 强校验（process start token）

### 方案
- `subprocess_util.py`：
  - 新增 `process_start_token(pid)`：
    - Linux：`/proc/<pid>/stat` 字段 22（starttime ticks）+ `/proc/sys/kernel/random/boot_id`
      → `"<boot_id>:<ticks>"`；
    - macOS：`ps -o lstart=` 输出 → `"ps:<lstart>"`；
    - Windows：`wmic process where ProcessId=<pid> get CreationDate` → `"wmic:<value>"`；
    - 读取失败 → `None`（恢复时退化为原校验强度）。
  - `ResurrectedProcess` 新增 `start_token: Optional[str]`；`poll()` 在存活判定
    后比较当前 token：提供了 token 但读取失败或不匹配 → 视为已退出（fail-closed）。
- `bash_session.py`：
  - `BashSession` 新增 `start_token`；`register()` 在 spawn 后记录。
  - `restore()` 构造 `ResurrectedProcess(..., start_token=rec.start_token)`。
- `bash_session_persistence.py`：
  - 表新增 `start_token TEXT`；`_ensure_schema` 用 `PRAGMA table_info` 检查并
    `ALTER TABLE ADD COLUMN`（老库平滑迁移）。
  - `persist` / `list_all` 读写该字段。

### 测试
- `process_start_token`：当前进程可读且稳定；不存在的 PID → None；
  Linux stat 解析对 comm 含空格/括号健壮。
- `ResurrectedProcess`：token 匹配 → 存活；token 不匹配 → 已退出；
  token 读取失败（mock 返回 None）→ fail-closed。
- 持久化：roundtrip + 老 schema 迁移（先建无列的表再包装仓储）。
- 恢复：错误 token 的记录被删除并推完成通知。

## Item B: Webhook HMAC 签名 + 重试

### 方案
- `notificationPrefs` 新增 `webhookSecret`（string，默认空）。
- `webhookDelivery.ts`：
  - 通用 Webhook 在 secret 非空时附加头
    `X-Sage-Signature: sha256=<hex(hmac_sha256(secret, body))>`；
    Slack 不加（Incoming Webhook 无签名约定）。
  - 重试：每条 URL 最多 3 次尝试（初始 + 2 次重试），退避 1s / 3s；
    仅对网络异常/非 2xx 重试；`sleep` 可注入以便单测。
  - 仍为 fire-and-forget：重试不阻塞轮询器循环（在后台异步任务内完成）。
- 设置 UI：Webhook 行内新增 secret 输入（password 类型）；i18n +2 键。
- main.ts IPC / preload / types 同步字段。

### 测试
- 签名：有 secret → header 存在且为确定的 HMAC；无 secret → 无 header。
- 重试：首次失败后成功 → fetch 调用 2 次；持续失败 → 3 次后放弃且只记日志；
  sleep 注入验证退避序列（不真实等待）。
- prefs roundtrip 含 secret。

## 实施步骤

- [x] M1: 本 plan 文档
- [x] M2: Item A（start token）+ 测试
- [x] M3: Item B（签名 + 重试 + UI）+ 测试
- [x] M4: ruff / py38 / typecheck / 架构 / IPC 契约
- [ ] M5: main PR → CI → 合并
- [ ] M6: win7 同步 PR

## 风险

| 风险 | 缓解 |
|---|---|
| `wmic` 在受限环境不可用 | token 读取失败按 fail-closed 处理（拒绝恢复，避免误认） |
| `/proc` 不存在（非 Linux POSIX） | 走 `ps -o lstart` 后备 |
| 老数据库无 start_token 列 | PRAGMA 检查 + ALTER TABLE 幂等迁移 |
| 重试放大流量 | 仅 3 次 / 单 URL / 退避 1s+3s |
| 签名密钥泄露风险 | secret 仅存主进程 JSON，不随日志输出；设置页 password 输入 |
