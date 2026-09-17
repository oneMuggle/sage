# 网关 Discord / Slack 适配（Round 16）

日期：2026-09-17 ｜ 分支：`feat/gateway-discord-slack` ｜ 基线：b71b9255

## 背景

`gateway/base.BaseGateway`（Round 17 平台抽象化）已把会话绑定 / 命令分发 /
审批转发 / LLM 对话 / 轮询线程全部平台无关化，Telegram 是唯一适配器。
「随身 agent」多通道补齐：Discord（REST 轮询 snowflake 游标）与 Slack
（Web API conversations.history 轮询）两个适配器，复用基类全部能力。

## 设计

两平台沿用 telegram.py 的分层与配置契约（Round 19 双源配置）：

| 层 | Discord | Slack |
|---|---|---|
| Transport | REST `/channels/{id}/messages?after=` + `/messages` POST | `/conversations.history?oldest=` + `/chat.postMessage` |
| 游标 | per-channel snowflake（int 原生单调，直接喂基类 offset） | per-channel ts（零填充字符串比较；event_ts 合成 int 供基类推进） |
| 自环防护 | `author.bot` 为真跳过 | `bot_id` / `subtype` 存在跳过 |
| 白名单 | `DISCORD_ALLOWED_CHANNEL_IDS`（channel 粒度） | `SLACK_ALLOWED_CHANNEL_IDS` |
| 截断 | 2000 字符 | 4000 字符 |
| 配置 | env `DISCORD_BOT_TOKEN` / settings `app_settings.discord` | env `SLACK_BOT_TOKEN` / settings `app_settings.slack` |
| kill-switch | settings `enabled=False` 显式关闭（env 不能越过） | 同左 |
| 绑定表 | `gateway_binds`（基类默认） | 同左 |

安全口径与 Telegram 一致：默认关闭（无 token 网关不启动）；白名单外拒答；
transport 全部可注入打桩；审批转发 / 命令（/help /status /new /approve /deny）
由基类直接继承，零平台代码。

## 改动

- `backend/gateway/discord.py`（新增）：`DiscordTransport` / `DiscordConfig` /
  `DiscordGateway` / `get_discord_gateway` / `reset_discord_gateway`
- `backend/gateway/slack.py`（新增）：`SlackTransport` / `SlackConfig` /
  `SlackGateway` / `get_slack_gateway` / `reset_slack_gateway`
- `backend/api/gateway_routes.py`：`/gateway/discord/*` 与 `/gateway/slack/*`
  的 status + config GET（token 打码）/ PUT（settings 持久化），与 telegram 同形
- `backend/main.py`：lifespan 注册两平台轮询（未配置零开销，同 telegram 模式）

## 测试（`test_gateway_discord_slack.py`）

- 两平台 config：env 优先 / settings 兜底 / kill-switch / 未配置 None
- fetch_updates：多通道游标推进、bot 消息过滤、游标越过被过滤消息
- parse_update 信封 → (chat_id, text)
- 白名单拒答 + 授权对话全链路（stub transport + llm_factory + tmp_db）
- 截断上限（transport 层）
- status / config 路由（打码、保存、enabled=False）

## 纪律

py3.8 兼容；httpx 延迟导入（同 telegram）；不动 Telegram 既有路径。
