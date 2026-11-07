# 专家私聊与群聊（M1 + M2）

> 面向开发者：把「专家」从内嵌智能体升格为 IM 式「联系人」，并支持多专家群聊。
> 相关章节：[133 专家（数字员工）系统](./133-specialist-persona.md)、[143 专家资产中心](./143-specialist-asset-hub.md)、[145 专家页面交互](./145-specialist-page-ux.md)。

## 1. 概念分层（M1）

| 层 | 页面 | 定位 |
| --- | --- | --- |
| 联系人 | `/specialists` | 面向使用者的专家画廊，点击即私聊；管理动作（编辑/知识/资产/版本/评测/导出）退居次位 |
| 管理 | `/agents` | 面向配置者的智能体管理后台 |

### 1.1 卡片点击 = 直接私聊

- `SpecialistCard` 头部（头像/名称区域）点击 → `onStartChat`（创建会话 + 绑定专家 + 跳转 `/chat`）。
- 详情页入口移至「更多」菜单 → `查看详情`（`/specialists/:id`）。
- 无 `onStartChat` 时头部点击回退到 `onOpenDetail`。

### 1.2 会话列表显示联系人身份

- `SessionItem` 通过 `useAgentDirectory` 查当前会话绑定的专家；绑定非 `primary` 专家时，显示专家名字徽标（并带 `persona_ui.avatar`）。
- `useAgentDirectory` 是模块级缓存的 hook：多个会话项共享一次 `agentsApi.list()` 加载，避免 N+1。

## 2. 群聊（M2）

### 2.1 数据模型（migration v16）

```sql
ALTER TABLE sessions ADD COLUMN conversation_type TEXT DEFAULT 'dm';  -- 'dm' | 'group'
CREATE TABLE IF NOT EXISTS conversation_participants (
    conversation_id TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',  -- 'host' | 'member'
    speak_order     INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    added_at        INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, agent_id)
);
ALTER TABLE messages ADD COLUMN sender_agent_id TEXT;  -- NULL = 用户
```

守卫：旧库缺 `sessions`/`messages` 表时直接返回（与 v11/v12/v14/v15 同模式），保证首次启动不炸。

### 2.2 仓储（`backend/data/participant_repo.py`）

| 函数 | 行为 |
| --- | --- |
| `list_participants(conn, cid)` | JOIN `agents` 带出 `name` / `avatar`（从 `persona_ui.avatar` 解析），按 `speak_order, added_at` 升序 |
| `add_participants(conn, cid, ids, host_agent_id?)` | 幂等；无显式 host 时首个新成员成为 host；`speak_order` 递增 |
| `remove_participant(conn, cid, agent_id)` | 返回是否实际删除 |
| `resolve_mention_agent(conn, cid, message)` | @ 解析：按参与者 `name` 精确匹配，**最长名字优先**，跳过 `enabled=0` 成员；无 `@` 直接返回 `None` |

### 2.3 参与者 CRUD API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/sessions/{id}/participants` | 列表（含头像/名字/role） |
| POST | `/api/v1/sessions/{id}/participants` | `{agent_ids: string[]}` 拉群；自动置 `conversation_type='group'` |
| DELETE | `/api/v1/sessions/{id}/participants/{agent_id}` | 移除成员 |

会话创建 `POST /api/v1/sessions` 增加可选 `participant_ids` 与 `conversation_type`，支持一次建群。

### 2.4 @ 调度（v1：显式）

`resolve_effective_agent_id_for_message(session_id, requested_agent_id, message)` 优先级：

```
显式 agent_id  >  消息内的 @专家名  >  会话绑定 specialist  >  primary
```

- `@` 解析失败（数据库异常等）只打 debug 日志并回落，**绝不阻塞对话**。
- 命中的 agent 还要过 `_is_usable_agent`（存在且启用）检查。
- assistant 消息落库写 `sender_agent_id`；前端据此渲染专家头像与名字。

### 2.5 前端

| 组件 | 职责 |
| --- | --- |
| `GroupChatDialog` | `/specialists` 页「新建群聊」：多选专家 → `createSession(false, { participantIds, conversationType: 'group' })` → 跳转 `/chat` |
| `SessionParticipantsStrip` | DM 复用 `SessionSpecialistPicker`；群聊显示成员 chips，host 标「主持」不可移除，其余可 × |
| `Message` | 依据 `message.sender_agent_id` 从 `useAgentDirectory` 取头像/名字，在气泡上方显示发言专家 |
| `ChatHeaderBar` | 群聊时渲染参与者条 |

### 2.6 记忆语义

群聊中每个专家的发言仍写入**实际发言专家**的私有记忆（调用方按解析后的 agent 绑定），共享层照常。

## 3. 测试

- `backend/tests/test_participant_repo.py`：6 例（首个为 host、幂等、显式 host、移除、@ 最长优先、禁用成员跳过）。
- 前端 `Specialists` 页测试覆盖建群入口渲染。

## 4. 兼容与风险

| 风险 | 缓解 |
| --- | --- |
| 旧会话兼容 | `conversation_type` 默认 `'dm'`；旧会话不写 participants，仍走 `specialist_id` |
| `sender_agent_id` 缺省 | 字段可空，前端回退到原有单头像展示 |
| `/chat/stream` 改动 | @ 解析只影响「选哪个 agent」，LLM/工具/流式管线不变 |
| py38 / pydantic v1 | 新增模型字段均为 `Optional[...]`；仓储仅用 `typing.Dict/List/Optional`，无 PEP 604 语法 |
