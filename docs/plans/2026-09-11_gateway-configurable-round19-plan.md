# 网关配置可持久化 Round 19 实施计划

> 日期: 2026-09-11 · 分支: `feat/gateway-configurable` · 基于 main @ 59525f51
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Telegram 网关目前只能靠环境变量启用（`TELEGRAM_BOT_TOKEN` /
`TELEGRAM_ALLOWED_CHAT_IDS`）——对桌面应用用户不现实（无 env 配置习惯，
打包后也没有 shell）。本批让网关配置可从**持久化设置**读取
（`app_settings.telegram` 节点，经 SettingsRepository），环境变量优先级
更高（部署场景覆盖）。

## 批次任务

### A. `backend/gateway/telegram.py`

- `TelegramConfig.load()` 类方法：settings → env 双源合并
  1. env `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS`（部署覆盖）
  2. settings `app_settings.telegram.{bot_token, allowed_chat_ids}`
     （列表或逗号分隔字符串均可）
  3. 都无 → None（网关关闭）
- `get_telegram_gateway` 使用 `load()`
- 新增 `update_gateway_settings(bot_token, allowed_chat_ids, enabled)`:
  写 settings（前端设置卡保存入口），enabled=False 时清除 token 视为关闭

### B. `backend/api/gateway_routes.py`

- `GET /gateway/telegram/config` — 当前配置（token 打码，只回尾 4 位）
- `PUT /gateway/telegram/config` — 保存配置（写 settings，重启后生效或
  触发网关重启——MVP: 提示需重启）

### C. 测试

- settings 双源优先级 / 打码 / enabled=False 关闭语义
