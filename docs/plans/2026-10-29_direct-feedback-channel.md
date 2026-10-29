# 用户反馈系统（直接通道版）规格

- 日期：2026-10-29
- 基线：`main` `161288c3e`
- 分支：`feat/direct-feedback-channel`
- Worktree：`.worktrees/feat-direct-feedback-channel`（后端 8790 / 前端 1445）
- 状态：草案

## 1. 设计决策

用户在评审上一版方案（`2026-10-29_user-feedback-system.md`）时明确两项决策：

| 维度 | 选择 | 含义 |
|------|------|------|
| **会话形态** | **双向会话** | 管理员可回复；用户在 Sage 内能看到并继续补充。结构像 ChatGPT 客服对话。 |
| **管理端** | **转发到现有系统** | Jira / GitLab / SMTP 任选；管理员用已有工具处理反馈；零新管理端开发。 |

**两选组合 → 架构必然走向**：转发脚本同时做中继。Jira 评论通过 webhook → 转发脚本本地 SQLite → 客户端定期 GET 拉取回复 → 显示在会话里。

**用户端配置**：用户填管理员的 `URL`（如 `http://10.0.0.5:8900`）+ 共享密钥。无需域名、无需 TLS（内网 HTTP 明文足够，密钥用 `hmac.compare_digest` 防重放）。

## 2. 架构

```
┌──────────────── Sage 桌面端 ────────────────┐
│                                              │
│  Renderer              Electron Main         │
│  ┌──────────────┐      ┌──────────────────┐  │
│  │ <FeedbackHub>│      │ FeedbackSyncer   │  │
│  │  - 发起反馈   │      │  - 提交消息      │  │
│  │  - 我的反馈   │      │  - 拉取管理员回复 │  │
│  │  - 会话消息流 │      │  - 重试 + 退避    │  │
│  │  - 截图/日志  │      │                  │  │
│  └──────┬───────┘      └────────┬─────────┘  │
│         │ IPC                   │ HTTPS      │
│         ▼                       ▼            │
│  ┌─────────────────────────────────────────┐ │
│  │ Backend (loopback 8765)                 │ │
│  │  POST /feedback/{id}/messages  (用户侧) │ │
│  │  GET  /feedback/{id}/messages  (读本地) │ │
│  │  表: feedback_conversations             │ │
│  │      feedback_messages                  │ │
│  │      feedback_attachments               │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────┘
                       │ HTTPS
                       ▼
┌──────────────────────────────────────────────┐
│ 转发脚本（管理员跑的）                         │
│ python -m scripts.feedback_receiver          │
│                                              │
│  ┌─────────────┐   ┌──────────────────┐      │
│  │ FastAPI     │   │ 转发器            │      │
│  │ - POST /fb  │   │ - Jira webhook   │      │
│  │ - GET  /fb  │──▶│ - GitLab webhook │      │
│  │ - POST /reply│  │ - SMTP webhook   │      │
│  └─────────────┘   └──────────────────┘      │
│  SQLite: feedback.db (中继镜像)               │
│  webhook: GET /feedback/{id}/replies         │
└──────────────────────────────────────────────┘
                       │
                       ▼
            ┌─────────────────┐
            │ Jira / GitLab   │
            │ 管理员在此看回复  │
            └─────────────────┘
```

## 3. 数据模型

### 3.1 SQLite 表（客户端 + 转发脚本共用 schema）

```sql
CREATE TABLE IF NOT EXISTS feedback_conversations (
    id TEXT PRIMARY KEY,                          -- UUID v4, 客户端生成
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'           -- open / resolved / closed
        CHECK(status IN ('open', 'resolved', 'closed')),
    remote_ticket_id TEXT,                        -- Jira/GitLab 工单号（转发后回写）
    remote_ticket_url TEXT,                       -- Jira/GitLab 工单链接
    app_version TEXT NOT NULL,
    os_info TEXT NOT NULL,
    last_activity_at INTEGER NOT NULL,            -- epoch ms
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_messages (
    id TEXT PRIMARY KEY,                          -- UUID v4
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
    body TEXT NOT NULL,                           -- markdown
    media_ids TEXT,                               -- JSON array of MediaStore ids
    created_at INTEGER NOT NULL,
    synced_at INTEGER,                            -- 已同步到远程时填时间戳
    FOREIGN KEY(conversation_id) REFERENCES feedback_conversations(id)
);

CREATE TABLE IF NOT EXISTS feedback_attachments (
    id TEXT PRIMARY KEY,                          -- MediaStore id
    conversation_id TEXT NOT NULL,
    message_id TEXT,                              -- 可选,绑到特定消息
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES feedback_conversations(id)
);

CREATE INDEX idx_fb_msg_conv ON feedback_messages(conversation_id, created_at);
CREATE INDEX idx_fb_conv_last ON feedback_conversations(last_activity_at DESC);
CREATE INDEX idx_fb_conv_remote ON feedback_conversations(remote_ticket_id);
```

**关键设计**：
- `conversation_id` 即客户端 UUID，**全程不变**；转发脚本用它作为主键
- `role` = 'user' 是 Sage 用户发的；'admin' 是管理员通过 Jira/GitLab 回的
- `media_ids` 走 `MediaStore`（复用截图存储），不直接写 base64

### 3.2 Repo 层

`backend/data/feedback_repo.py`（参考 `design_repo.py`）：
- `create_conversation(conv)` / `get_conversation(id)` / `list_conversations(limit)`
- `add_message(msg)` / `list_messages(conv_id)` / `mark_synced(msg_id)`
- `upsert_remote_ticket(conv_id, ticket_id, url)` — Jira/GitLab webhook 写回

## 4. API 契约

### 4.1 客户端 → 转发脚本

**Endpoint A：创建/更新会话**
```
POST {managerUrl}/api/v1/feedback/conversations
Authorization: Bearer {shared-secret}
Content-Type: application/json
X-Client-Id: {installation-uuid}

{
  "id": "uuid-v4",
  "title": "导出 PDF 乱码",
  "app_version": "0.2.0",
  "os_info": "Windows 10",
  "messages": [
    {
      "id": "msg-uuid-1",
      "role": "user",
      "body": "导出后中文变乱码，见截图",
      "media_ids": ["m-123", "m-456"],
      "created_at": 1730214000000
    }
  ],
  "created_at": 1730214000000
}

Response 200: { "id": "uuid", "remote_ticket_id": "PROJ-123", "remote_ticket_url": "..." }
Response 401: unauthorized
```

**Endpoint B：追加消息（用户补充 / 管理员回复）**
```
POST {managerUrl}/api/v1/feedback/conversations/{id}/messages
Authorization: Bearer {shared-secret}
Content-Type: application/json

{
  "id": "msg-uuid-2",
  "role": "user",
  "body": "版本是 0.2.0，附截图",
  "media_ids": ["m-789"],
  "created_at": 1730214100000
}

Response 200: { "id": "msg-uuid-2", "received": true }
```

**Endpoint C：拉取管理员回复**
```
GET {managerUrl}/api/v1/feedback/conversations/{id}/messages?since=<epoch-ms>
Authorization: Bearer {shared-secret}

Response 200: {
  "messages": [
    {
      "id": "admin-msg-1",
      "role": "admin",
      "body": "已复现，下周修复",
      "created_at": 1730300000000
    }
  ]
}
```

**Endpoint D：附件上传（raw binary）**
```
POST {managerUrl}/api/v1/feedback/conversations/{id}/attachments/{media_id}
Authorization: Bearer {shared-secret}
Content-Type: image/png

<raw PNG bytes>

Response 200: { "id": "m-123", "received": true }
```

**Endpoint E：健康检查**
```
GET {managerUrl}/api/v1/feedback/health
Response 200: { "status": "ok" }
```

### 4.2 Jira/GitLab → 转发脚本（webhook）

**Jira webhook**：`POST /api/v1/webhooks/jira`
```
{
  "webhookEvent": "comment_created",
  "issue": { "key": "PROJ-123", "fields": { "summary": "..." } },
  "comment": { "body": "已复现，下周修", "author": { "displayName": "Alice" } }
}

→ 转发脚本解析 comment.body，写入本地 feedback.db，role='admin'
→ 客户端下次轮询 GET /feedback/{id}/messages?since=... 能拿到
```

**GitLab webhook**：`POST /api/v1/webhooks/gitlab`
```
{
  "object_kind": "note",
  "issue": { "iid": 123, "title": "..." },
  "object_attributes": { "note": "已复现，下周修" }
}
```

## 5. 实施步骤

### Phase 1：本地会话（P0 优先落地）

**目标**：用户能在 Sage 内发起双向会话，消息在本地 SQLite 流转，**即使没有转发脚本也能自己用**。

- [x] 1.1 后端：建表（`feedback_conversations` / `feedback_messages` / `feedback_attachments`）
- [x] 1.2 后端：`feedback_repo.py`（CRUD + `mark_synced` + `list_recent`）
- [x] 1.3 后端：`feedback_routes.py`（会话级 + 追加消息 + `pending` / `mark-synced` 给 syncer 用；DTO snake_case 对齐仓库惯例）
- [x] 1.4 后端：`MediaStore` 集成存截图
- [x] 1.5 后端：`log_tail.py`（复用 `redact_text`）
- [x] 1.6 Electron：`feedback/feedbackSyncer.ts`（提交 + 拉取回复）
- [x] 1.7 Electron：`feedback/feedbackConfig.ts`（safeStorage + 配置文件）
- [x] 1.8 Electron：IPC 路由 `commandRoutes/feedback.ts`
- [ ] 1.9 前端：`<FeedbackHub>` 组件（会话列表 + 消息流）
- [ ] 1.10 前端：全局 store `useFeedbackStore.ts`
- [ ] 1.11 前端：菜单 IPC 监听 + "帮助"菜单加"反馈问题..."
- [x] 1.12 前端：设置页 "反馈" Tab（管理员 URL + 密钥配置）
- [x] 1.13 i18n（zh + en）
- [x] 1.14 测试：后端 repo + 路由（37 passed）；组件/syncer 测试待前端落地后补

### Phase 2：转发脚本（管理员侧）

**目标**：管理员能一键启动转发脚本，反馈自动进 Jira/GitLab，回复自动回流客户端。

- [ ] 2.1 `scripts/feedback_receiver.py`（单文件，零第三方依赖）
- [ ] 2.2 SQLite 中继 + 附件目录
- [ ] 2.3 Jira webhook 转发（解析 comment → role='admin'）
- [ ] 2.4 GitLab webhook 转发
- [ ] 2.5 SMTP 转发（邮件附件带截图）
- [ ] 2.6 管理页：简单的 HTML 列表 + 详情（零依赖，Python 内置 jinja2 模板）
- [ ] 2.7 部署文档（systemd / Windows 服务）

### Phase 3：增强

- [ ] 3.1 消息通知（管理员回复时客户端托盘气泡）
- [ ] 3.2 消息搜索
- [ ] 3.3 会话标签（bug / feature / other）
- [ ] 3.4 自动附加诊断信息开关

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 转发脚本挂了 → 用户回复丢失 | 客户端先落本地 SQLite，再异步提交；pending 永不丢 |
| Jira webhook 延迟 → 管理员回复不及时到客户端 | 客户端同时轮询 `/messages?since=`（默认 60s 一次） |
| 自签 HTTPS 在内网常见 | `safeStorage` + 设置页"允许自签名证书"开关（仅针对 feedback URL） |
| 截图体积大 | 单张 ≤ 5MB（客户端压缩），会话 ≤ 20 张 |
| 多客户端同 UUID 上报 | `safeStorage` 持久化 `installation-uuid`，首次生成 |

## 7. 工作量估算

| Phase | 工作量 | 备注 |
|-------|--------|------|
| Phase 1（本地会话） | 2-3 天 | 可独立使用 |
| Phase 2（转发脚本） | 1-2 天 | 需管理员配合 |
| Phase 3（增强） | 1 天 | 可选 |

本会话目标：完成 Phase 1 核心骨架（建表 + 路由 + 前端 UI + 本地流转），Phase 2/3 留到下个会话。
