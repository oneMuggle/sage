# Telegram 消息网关

> Round 6 起提供（Round 10 加审批转发，Round 11 加上下文预算，Round 12
> 加命令完善）。对标 hermes-agent 的 messaging gateway。

## 功能

在 Telegram 上远程与家里的 Sage 对话：收发消息、远程审批危险操作、
会话跨消息持续。配合定时任务与唤醒调度，实现「随身 agent」。

## 启用（默认关闭）

```bash
# 必需
set TELEGRAM_BOT_TOKEN=123456:ABC-DEF...        # BotFather 创建的 bot token
# 必需（安全白名单，逗号分隔；之外的 chat 一律拒答）
set TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
# 可选
set SAGE_GW_HISTORY_TOKEN_BUDGET=4000           # 网关对话历史 token 预算（<=0 关闭）
```

配置后启动 Sage 后端，日志出现「Telegram 网关已启动」即生效。
状态查询：`GET /api/v1/gateway/telegram/status`。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/pending` | 列出待审批请求 |
| `/approve <短id>` | 批准挂起的危险操作 |
| `/deny <短id>` | 拒绝挂起的危险操作 |
| `/status` | 网关统计 |
| `/reset` | 重置本对话（全新上下文） |
| `/help` | 命令总览 |

其他文本直接与 Sage 对话（LLM 回复）。

## 审批转发

Agent 请求执行危险操作（bash 写操作等）时，审批请求自动转发到白名单
chats；回复 `/approve <短id>` 或 `/deny <短id>` 即可远程裁决。
裁决走 `ApprovalGate`（与桌面端同一闸口），落盘前仍需批准的安全模型
不变；Round 3 的审计台账与回滚设施照常生效。

## 安全边界

- 默认关闭：未配置 `TELEGRAM_BOT_TOKEN` 网关完全不启动
- 白名单：`TELEGRAM_ALLOWED_CHAT_IDS` 之外的 chat 显式拒答
- HTTP 全部可注入 transport；测试零真实外发
- 子进程执行（repl/execute_code）**不是 OS 沙箱**——与桌面端一致的
  权限模型，远程批准等同桌面端批准
