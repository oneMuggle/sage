# Telegram 消息网关 MVP Round 6 实施计划（对标 hermes-agent gateway）

> 日期: 2026-09-11 · 分支: `feat/telegram-gateway-mvp` · 基于 main @ 47920a9f
> 来源: hermes-agent 对标分析（消息网关 —— hermes 增长最快的产品面）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: 避开 feat-p11-embedding-distribution（embedder 区域）。

## 背景

hermes 的核心竞争力之一是「随身 agent」：Telegram/Discord 等 25+ 平台
收发消息、远程唤醒、审批转发。Sage 已有全部后端基建（会话、消息仓储、
LLM 工厂、审批闸口、定时任务、唤醒调度）——离「在 Telegram 上远程使唤
家里的 Sage」只差一个平台适配层。

**MVP 安全边界**：
- 默认关闭：未配置 `TELEGRAM_BOT_TOKEN` 时网关完全不启动
- 白名单：`TELEGRAM_ALLOWED_CHAT_IDS` 之外的 chat 一律拒答
- HTTP 全部经可注入 transport，测试零外发

## 批次任务

### A. `backend/gateway/telegram.py`（新）

- `TelegramConfig`: bot_token / allowed_chat_ids / poll timeout
- `TelegramTransport`: httpx 封装（getUpdates / sendMessage），可注入
- `TelegramGateway`:
  - `poll_once()` — 长轮询一次 + 逐条 handle + 维护 offset（崩溃安全）
  - `handle_update()` — 白名单校验（未授权 chat 显式拒答一次）→
    chat_id→session 绑定（无则建新会话）→ 取会话历史 → LLM 单轮
    （`orchestration/llm_factory` settings 解析，与 planner 同模式）→
    sendMessage 回复
  - 绑定表 `telegram_chats(chat_id PK, session_id, created_at)`
- 历史/持久化复用 `MessageRepository`/`SessionRepository`

### B. 调度接入（`backend/main.py` lifespan，一行级改动）

- token 已配置时注册 APScheduler interval job（3s tick）跑 `poll_once`；
  未配置零开销

### C. REST（`backend/api/gateway_routes.py` 新）

- `GET /gateway/telegram/status`（enabled / configured / 绑定数）
- 测试面复用（不新增管理面 CRUD——MVP 从简）

### D. 测试

- `backend/tests/unit/test_telegram_gateway.py`：白名单拒绝、新会话
  绑定、既有会话续聊、offset 推进、LLM 未配置降级提示
- transport 全部注入 fake，零真实外发

## Round 7 候选

- execute_code RPC 工具调用 / docker 沙箱
- 网关平台扩展（Discord/Slack）+ 审批转发到 Telegram
- hex-legacy 双栈收敛
