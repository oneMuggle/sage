# 网关多平台抽象基类 Round 17 实施计划

> 日期: 2026-09-11 · 分支: `feat/gateway-base-class` · 基于 main @ b09f0c10
> 来源: hermes-agent 对标（gateway 平台适配层抽象，为 Discord/Slack 铺路）
> Win7 对齐: 纯重构，无新功能；不 cherry-pick 到 release/win7。

## 背景

Round 6/10/12 的 Telegram 网关把「平台协议」与「Sage 会话/审批/命令」
逻辑写在同一个类里。接入第二个平台（Discord/Slack）时绑定存储、命令
分发、审批转发、轮询线程、LLM 对话全部要复制。本批抽出平台无关基类。

## 方案

### A. `backend/gateway/base.py`（新）

- `GatewayStats`（原样迁入）
- `BaseGateway`：绑定存储（telegram_chats → **gateway_binds** 通用表）、
  命令分发（/pending /approve /deny /status /reset /help /未知）、
  审批转发（去重集合 + poll 尾部触发）、LLM 对话（历史预算 + 省略提示）、
  轮询线程（fetch → parse → handle → forward）
- 子类实现的抽象点：
  - `fetch_updates()` → 平台原始事件列表（含稳定递增 id 字段名由
    `event_id_key` 类属性声明）
  - `send_reply(chat_id, text)`
  - `parse_update(update) -> Optional[Tuple[chat_id, text]]`
- 表名抽象：`binds_table` 类属性（Telegram 延续 `telegram_chats`，
  新平台用 `gateway_binds` 通用名）

### B. `backend/gateway/telegram.py`

- `TelegramGateway(BaseGateway)`：只留 Telegram 特有部分
  （transport/handle_update 信封解析/白名单拒答文案）
- 行为与端点零变化（既有 24 例网关测试全过即验收）

### C. 测试

- 既有网关测试全量回归；新增 `test_gateway_base.py`：
  用最小子类验证抽象点（parse/fetch/send）即可驱动完整轮询+命令流

## 验收

- [ ] 既有网关/审批测试全绿；ruff 干净；CI 绿
