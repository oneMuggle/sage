# 用户反馈转发脚本部署指南

- 日期：2026-10-29
- 脚本：`scripts/feedback_receiver.py`
- 适用：Sage `main` 与 `release/win7` 双分支（脚本本身不依赖分支）

## 1. 这个脚本是什么

`scripts/feedback_receiver.py` 是**管理员侧**的单文件中继服务，零第三方依赖（只用
Python 标准库），单文件拷过去就能跑：

```
桌面端 FeedbackSyncer ──POST /api/v1/feedback/conversations/{id}/messages──▶ 中继（落 SQLite）
桌面端 FeedbackSyncer ──GET  .../messages?since=<ms>──────────────────────▶ 中继（返回管理员回复）
Jira / GitLab ────────POST /api/v1/webhooks/{jira,gitlab}─────────────────▶ 中继
管理员浏览器 ──────────GET / 、POST /conversation/{id}/reply──────────────▶ 中继
中继 ─────────────────▶ Jira / GitLab / SMTP（建工单、追加评论、发邮件）
```

三条设计约束决定了它长这样：

| 约束 | 实现 |
|------|------|
| 桌面端"收到 2xx 即算送达"，30s 超时 | **先落库再转发**：消息写进 SQLite 后才回 200，外部系统在 daemon 线程里推，慢也不会拖垮客户端 |
| 桌面端会重发同一条消息直到成功 | 消息按 id 做 `INSERT OR IGNORE`，重复投递返回 `{"received": true, "duplicate": true}` |
| 桌面端 `remoteGet<RemoteMessage[]>` 直接 `.filter(...)` | `GET .../messages` 必须返回**裸 JSON 数组**，不能包 `{"messages": [...]}` |

## 2. 前置条件

- Python **3.8 及以上**（脚本已用 3.8 解释器验证过 `py_compile`）
- 管理员机器能访问 Jira / GitLab / SMTP（若使用转发）
- 桌面端能访问这台机器（内网 IP 即可，例如 `http://10.0.0.5:8900`）

不需要 `pip install`，不需要虚拟环境。

## 3. 快速开始

```bash
# 1) 生成共享密钥（桌面端与管理端必须一致）
export FEEDBACK_SHARED_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"

# 2) 管理页密码（不设则管理页禁用，但中继仍工作）
export FEEDBACK_ADMIN_PASSWORD="change-me"

# 3) 启动
python3 scripts/feedback_receiver.py
```

客户端在 Sage「设置 → 反馈」里填同一台机器的 URL 和同一个共享密钥即可。

## 4. 环境变量

### 4.1 中继本体

| 变量 | 默认 | 说明 |
|------|------|------|
| `FEEDBACK_SHARED_SECRET` | — | **必填**，缺省直接退出。桌面端 `Authorization: Bearer <它>` |
| `FEEDBACK_DATA_DIR` | `./feedback-data` | SQLite 与附件目录 |
| `FEEDBACK_LISTEN_HOST` | `127.0.0.1` | 要让其他机器连，改成 `0.0.0.0` 或内网 IP |
| `FEEDBACK_LISTEN_PORT` | `8900` | 监听端口 |
| `FEEDBACK_MAX_BODY_BYTES` | `8388608`（8 MiB） | 单个请求体上限，超了回 413 |
| `FEEDBACK_ADMIN_USER` | `admin` | 管理页 HTTP Basic 用户名 |
| `FEEDBACK_ADMIN_PASSWORD` | 空 | 空 = 管理页与回复表单全部禁用（404） |
| `FEEDBACK_WEBHOOK_TOKEN` | 空 | 空 = webhook 端点全部禁用（404）；Jira/GitLab 侧需带同一个值 |

### 4.2 转发后端（三选一，按 Jira → GitLab → SMTP 优先级取第一个配置完整的）

**Jira**

| 变量 | 例 |
|------|-----|
| `FEEDBACK_JIRA_URL` | `https://jira.example.com` |
| `FEEDBACK_JIRA_EMAIL` | `bot@example.com` |
| `FEEDBACK_JIRA_TOKEN` | API token（与 email 一起走 Basic 认证） |
| `FEEDBACK_JIRA_PROJECT` | `SAGE` |
| `FEEDBACK_JIRA_ISSUE_TYPE` | `Task`（默认） |

**GitLab**

| 变量 | 例 |
|------|-----|
| `FEEDBACK_GITLAB_URL` | `https://gitlab.example.com` |
| `FEEDBACK_GITLAB_TOKEN` | Personal/Project access token（`PRIVATE-TOKEN`） |
| `FEEDBACK_GITLAB_PROJECT` | `group/sub/project`（脚本会做 URL 编码） |

**SMTP**

| 变量 | 例 |
|------|-----|
| `FEEDBACK_SMTP_HOST` / `FEEDBACK_SMTP_PORT` | `mail.example.com` / `587` |
| `FEEDBACK_SMTP_FROM` / `FEEDBACK_SMTP_TO` | `sage-bot@example.com` / `support@example.com` |
| `FEEDBACK_SMTP_USER` / `FEEDBACK_SMTP_PASSWORD` | 留空则不登录 |
| `FEEDBACK_SMTP_TLS` | `1` = 用 `SMTP_SSL`（**不是** STARTTLS），默认 `0` |

> **SMTP 是单向的**：脚本只发不收（不做 IMAP 轮询）。走邮件时，管理员回复要么用内置管理页，
> 要么改用 Jira/GitLab 的 webhook 回流。

一个都不配也能跑：`forwarder=none`，反馈只留在本机，靠管理页处理。

## 5. 数据落盘与备份

```
feedback-data/
├── feedback.db          # conversations / messages / attachments 三张表
└── attachments/<media_id>   # 桌面端上传的原始二进制
```

表结构（要点）：

- `conversations(id, client_id, title, status, app_version, os_info, remote_system, remote_ticket_id, remote_ticket_url, created_at, updated_at)`
- `messages(id, conversation_id, role ∈ {user, admin}, body, media_ids(JSON 数组), origin ∈ {client, admin-page, jira, gitlab}, created_at)`
- `attachments(id, conversation_id, mime_type, size_bytes, created_at)`

时间戳统一是 **epoch 毫秒**。`conversation_id` 就是桌面端生成并全程不变的 UUID。

备份：整个 `feedback-data/` 目录拷走即可。停机备份最省事；在线备份可
`sqlite3 feedback.db ".backup '/backup/feedback-$(date +%F).db'"`。

## 6. 转发侧配置

### 6.1 Jira webhook

Jira → 系统设置 → Webhooks → 新建：

- URL：`http://<relay-host>:8900/api/v1/webhooks/jira?token=<FEEDBACK_WEBHOOK_TOKEN>`
  （也可以用请求头 `X-Feedback-Token` 传同一个值）
- Events：勾选 **Comment created**（脚本只处理 `webhookEvent == "comment_created"`）

管理员在工单上回评论 → 脚本按 `issue.key` 找回对应会话 → 记一条 `role=admin` 消息 → 桌面端下次轮询拿到。

### 6.2 GitLab webhook

项目 → Settings → Webhooks：

- URL：`.../api/v1/webhooks/gitlab?token=<FEEDBACK_WEBHOOK_TOKEN>`
- Trigger：**Comments**（脚本只处理 `object_kind == "note"`，按 `issue.iid` 匹配）

### 6.3 映射关系

新建会话时脚本把工单号写回 `conversations.remote_ticket_id`；后续消息追加为工单评论。
因此**必须保留脚本自己建的工单**，手动新建的工单不会被识别。

## 7. 管理页

`GET http://<relay-host>:8900/`（HTTP Basic，用 `FEEDBACK_ADMIN_USER/PASSWORD`）：

- 列表：标题 / 状态 / 工单号 / 最后更新时间
- 详情：完整消息流（用户消息与管理员回复分色）、附件下载链接、回复输入框

回复走 `POST /conversation/{id}/reply`（表单字段 `body`），写入后 303 跳回详情页，
桌面端下一轮轮询即拉到。管理页是唯一不依赖任何外部系统的回复通道，建议始终启用。

## 8. 部署为常驻服务

### 8.1 Linux（systemd）

`/etc/systemd/system/sage-feedback.service`：

```ini
[Unit]
Description=Sage Feedback Relay
After=network-online.target

[Service]
Type=simple
User=sage
WorkingDirectory=/opt/sage
Environment=FEEDBACK_SHARED_SECRET=__REPLACE_ME__
Environment=FEEDBACK_ADMIN_PASSWORD=__REPLACE_ME__
Environment=FEEDBACK_DATA_DIR=/var/lib/sage-feedback
Environment=FEEDBACK_LISTEN_HOST=0.0.0.0
Environment=FEEDBACK_LISTEN_PORT=8900
ExecStart=/usr/bin/python3 /opt/sage/scripts/feedback_receiver.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sage-feedback
sudo journalctl -u sage-feedback -f
```

> 密钥别写进 unit 文件再提交到仓库。更稳妥的做法是
> `EnvironmentFile=/etc/sage-feedback.env`（`chmod 600`）。

### 8.2 Windows（计划任务）

脚本是纯标准库，Windows 上同样可跑（Electron 21 的 Win7 LTS 分支环境里就带 Python 3.8 运行时）：

```bat
:: run-relay.bat
set FEEDBACK_SHARED_SECRET=__REPLACE_ME__
set FEEDBACK_ADMIN_PASSWORD=__REPLACE_ME__
set FEEDBACK_DATA_DIR=D:\sage-feedback
set FEEDBACK_LISTEN_HOST=0.0.0.0
C:\Python38\python.exe C:\sage\scripts\feedback_receiver.py
```

计划任务 → 触发器「计算机启动时」→ 操作指向该 bat → 勾选「不管用户是否登录都运行」。
需要开机自启 + 崩溃重启时可用 [NSSM](https://nssm.cc/)：
`nssm install SageFeedback C:\Python38\python.exe C:\sage\scripts\feedback_receiver.py`。

## 9. 安全注意事项

- 桌面端走的是**内网明文 HTTP**。共享密钥用于防误连和防随意投递，不是传输加密。
  跨网段/公网部署请在前面放反向代理加 TLS，并把 `FEEDBACK_LISTEN_HOST` 收回 `127.0.0.1`。
- 三组凭据相互独立：`FEEDBACK_SHARED_SECRET`（客户端）、`FEEDBACK_ADMIN_PASSWORD`（管理页）、
  `FEEDBACK_WEBHOOK_TOKEN`（Jira/GitLab 回调）。
- 脚本用 `hmac.compare_digest` 比较所有凭据，不要改成 `==`。
- `media_id` / `conversation_id` 落盘前都过白名单正则（`^[A-Za-z0-9._-]{1,128}$`），
  防止路径穿越；管理页所有用户内容都做 HTML 转义。
- 每个响应都带 `Connection: close`：鉴权失败等早退路径不会读请求体，保持 keep-alive 会让后续请求错位。
- 轮换共享密钥时：先改管理端并重启，再通知用户改设置页；期间客户端会 401 并在日志里
  留下 `remote POST 401 — shared secret mismatch`。

## 10. 排障

| 现象 | 检查点 |
|------|--------|
| 客户端日志 `remote POST 401` | 两端 `FEEDBACK_SHARED_SECRET` 是否一致 |
| 客户端 `remote GET 401` | 同上；GET 也带 Bearer |
| 客户端 `remote POST failed` 4xx | 看脚本日志；`id/body` 缺失会 400，`conversation_id` 含非法字符也 400 |
| 客户端 `remote POST failed` 413 | 单条消息体超 `FEEDBACK_MAX_BODY_BYTES` |
| 管理页打不开 | `FEEDBACK_ADMIN_PASSWORD` 为空时管理页是 404（设计如此） |
| webhook 返回 404 | `FEEDBACK_WEBHOOK_TOKEN` 为空时全部禁用 |
| webhook 返回 401 | token 不匹配；支持 `?token=` 与 `X-Feedback-Token` 两种传法 |
| Jira 评论没回流 | 事件必须是 `comment_created`；`issue.key` 必须等于 `conversations.remote_ticket_id` |
| 工单没建出来 | 脚本日志里找 `create_ticket failed`；检查 Jira/GitLab 凭据与项目字段 |
| 用户看到重复回复 | 不应发生：消息按 id 幂等；若出现，检查桌面端是否把 `since` 算错 |

健康检查（无需鉴权）：

```bash
curl -s http://127.0.0.1:8900/api/v1/feedback/health
# {"status": "ok", "conversations": 3}
```

## 11. 客户端侧设计（桌面端）

中继只是链路的一端。另一端由桌面端三层组成：**本地 SQLite（真源）→ 本地 FastAPI 路由 →
Electron 同步器 / 渲染进程**。渲染进程从不直接访问管理员地址，所有出网都由主进程的
`FeedbackSyncer` 发起。

### 11.1 本地数据模型

本地库与中继的三张表同名，但**不是同一份数据**，字段也不一样（本地多了 `tag`、`synced_at`）：

- `feedback_conversations(id, title, status ∈ {open,resolved,closed}, tag ∈ {bug,feature,other},
  remote_ticket_id, remote_ticket_url, app_version, os_info, last_activity_at, created_at, updated_at)`
- `feedback_messages(id, conversation_id, role ∈ {user,admin}, body, media_ids(JSON), created_at, synced_at)`
- `feedback_attachments(id, conversation_id, message_id, filename, mime_type, size_bytes)`

`conversation_id` 是客户端生成的 UUID v4，全程不变，也是中继侧的主键。
`tag` 由迁移 **v10** 加入（老库历史会话落 `'other'`）。
`synced_at IS NULL` 表示消息还在 outbox，UI 显示「待送达」；转发成功后由
`POST /messages/{id}/synced` 打上时间戳。

### 11.2 本地后端 API 契约

前缀 `/api/v1/feedback`（`backend/api/feedback_routes.py`）：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/conversations` | 新建会话（客户端生成 UUID） |
| GET | `/conversations?limit=` | 会话列表（默认 50） |
| GET | `/conversations/{id}` | 详情 + 消息 |
| GET | `/conversations/{id}/pending` | outbox：尚未转发给管理员的消息 |
| POST | `/conversations/{id}/messages` | 追加消息（`role` 只能是 user / admin） |
| POST | `/conversations/{id}/attachments` | 上传截图（请求体是原始二进制） |
| PATCH | `/conversations/{id}/status` | open / resolved / closed |
| POST | `/messages/{id}/synced` | 标记已成功转发到管理员侧 |
| GET | `/search?q=&limit=` | 搜消息正文 |
| GET | `/log-tail?max_lines=` | 日志尾部（诊断附带用，已脱敏） |

对**管理员侧**，同步器只用两个端点：

- `POST /api/v1/feedback/conversations/{id}/messages` —— 携带
  `{id, role, body, media_ids, created_at, title, app_version, os_info, conversation_created_at}`。
  中继首次见到该 id 时用这些元数据建工单，之后忽略。
- `GET /api/v1/feedback/conversations/{id}/messages?since=<毫秒>` —— 必须返回**裸 JSON 数组**，
  客户端直接 `.filter(...)`，包一层对象会崩。

### 11.3 同步节奏与退避

没有固定短轮询：**每轮结束后按当前退避档排下一轮**。

- 成功 → 退避档重置为 0，下一轮 **5 分钟**后
- 失败 → 逐档升：`5min → 15min → 1h → 4h → 24h`，之后定格在 24h
- 单轮最多处理 `CONVERSATIONS_PER_TICK_LIMIT = 50` 个本地会话（避免长时间锁库）
- 单请求超时 `REQUEST_TIMEOUT_MS = 30_000`
- 只有 `status = open` 的会话参与提交与拉取
- 配置被清空时循环自行 `running = false`，等设置页重新启用再 `start()`

「立即同步」按钮和设置页的同名按钮都直接调 `syncOnce()`，不受退避影响。

### 11.4 代码地图

| 文件 | 职责 |
|---|---|
| `backend/api/feedback_routes.py` | 本地 HTTP 路由（§11.2） |
| `backend/data/feedback_repo.py` | 仓储层：会话 / 消息 / 附件的读写 |
| `backend/data/database.py` | 三张本地表的 DDL（建表在 `_init_schema` 内） |
| `backend/data/migrations/runner.py` | 迁移 v10：`feedback_conversations.tag` |
| `electron/feedback/feedbackConfig.ts` | 地址 / 密钥 / 本机 ID / 诊断开关（safeStorage 加密） |
| `electron/feedback/feedbackSyncer.ts` | 周期循环：提交 outbox + 拉取回复 + 退避 |
| `electron/feedback/feedbackIpc.ts` | 渲染进程 ↔ 主进程的配置与手动同步 IPC |
| `electron/commandRoutes/feedback.ts` | 会话/消息 CRUD 到本地后端的 HTTP 映射 |
| `src/features/feedback/FeedbackHub.tsx` | `/feedback` 页面：列表、消息流、输入框、截图 |
| `src/features/feedback/feedbackStore.ts` | 渲染层状态（zustand） |
| `src/features/feedback/diagnosticsSuffix.ts` | 诊断日志附带（最近 80 行 / ≤4000 字符） |
| `src/shared/api/feedbackApi.ts` | 渲染进程调本地后端的封装 |

---

## 12. 已知边界

- 桌面端只对 `status = open` 的会话提交/拉取，本地标记 resolved/closed 后不再同步（已有消息不回删）。
- 附件目前只做**存储**，不会自动追加到 Jira/GitLab 评论；SMTP 会作为邮件附件带上。
- 会话的**状态与标签由桌面端提供**（`PATCH /conversations/{id}/status` 与迁移 v10 的 `tag` 列）；
  管理页只展示状态，不提供改状态/打标签的入口，需要时直接用 SQLite。
- 单进程 + SQLite 足够支撑小型团队；不要用 gunicorn 多 worker 并发写同一个 db 文件。

## 13. 相关文档

- 用户手册：[`docs/user-manual/25-user-feedback.md`](../user-manual/25-user-feedback.md)
- 客户端侧设计（本地表 / 本地 API / 同步节奏 / 代码地图）：本文 §11
- 客户端同步器：`electron/feedback/feedbackSyncer.ts`（退避 `[5min, 15min, 1h, 4h, 24h]`，单次请求超时 30s）
- 本地路由 / 仓储：`backend/api/feedback_routes.py`、`backend/data/feedback_repo.py`
- 渲染层：`src/features/feedback/FeedbackHub.tsx`
- 测试：`scripts/tests/test_feedback_receiver.py`（46 个用例，含真 HTTP 闭环；CI 不跑 `scripts/tests`，需手动执行）
