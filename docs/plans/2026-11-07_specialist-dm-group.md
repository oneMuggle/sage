# 专家私聊与群聊（M1 + M2）

- 日期：2026-11-07
- 分支：`feat/specialist-dm-group`
- worktree：`.worktrees/feat-specialist-dm-group`（后端 8884 / 前端 1539）

## 背景与目标

当前专家系统把「专家」与 primary/coder 等内置智能体混在同一概念层：`/agents` 管理页、`/specialists` 画廊、聊天会话单值绑定。用户期望像 IM 一样：

1. **私聊（DM）**：专家是「联系人」，点开即聊，管理动作退居二线；
2. **群聊（Group）**：一次拉多个专家进同一会话，各自以自己的人设发言。

参考：Character.ai Rooms（多角色房间 + @）、Coze 多 Agent 群聊、Discord（DM + Channel）、钉钉/飞书数字员工。

本计划交付 **M1（概念分层）** 与 **M2（群聊 MVP v1：@ 显式调度）**。

## M1：概念分层（前端为主）

### 1.1 卡片点击 = 直接私聊

- `SpecialistCard` 头部点击行为：从「进入详情页」改为「发起私聊」（创建会话 + 绑定专家 + 跳转 `/chat`）。
- 详情页入口移到「更多」菜单（`查看详情`）与卡片次操作区保持不变（编辑/知识/资产）。
- 现有 `handleStartChat` 逻辑复用。

### 1.2 会话列表显示联系人身份

- 侧边栏会话列表项：会话绑定了非 primary 专家时，显示专家头像（`persona_ui.avatar`）+ 专家名作为副标题/徽标；群聊显示群聊图标 + 成员头像组。
- 实现位置：`src/widgets/layout/sidebar/` 的会话列表组件（找到具体文件后注入）。

### 1.3 文案统一

- 「专家」页面副标题、空态文案强调「数字员工/联系人」心智。
- `/agents` 页面保留为「智能体管理」（后台配置）。

## M2：群聊 MVP

### 2.1 数据模型（migration v16）

```sql
-- sessions 增加会话类型
ALTER TABLE sessions ADD COLUMN conversation_type TEXT DEFAULT 'dm';  -- 'dm' | 'group'

-- 群聊参与者
CREATE TABLE IF NOT EXISTS conversation_participants (
    conversation_id TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',  -- 'host' | 'member'
    speak_order     INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    added_at        INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, agent_id)
);

-- messages 增加发送者（NULL = 用户 / primary 也可记录）
ALTER TABLE messages ADD COLUMN sender_agent_id TEXT;
```

守卫：旧库无表时跳过（与 v14/v15 同模式）。

### 2.2 后端 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/sessions/{id}/participants` | 列出参与者（含 agent 头像/名字） |
| POST | `/sessions/{id}/participants` | `{agent_ids: string[]}` 拉群（自动置 conversation_type=group；首个为 host，其余 member） |
| DELETE | `/sessions/{id}/participants/{agent_id}` | 移除成员 |

会话创建：`POST /sessions` 增加可选 `conversation_type` 与 `participant_ids`（一次建群）。

### 2.3 群聊调度 v1（@ 显式）

- 用户消息解析 **@专家名**（按参与者 `agents.name` 匹配；支持「@写作专家」）。
- 命中 → 该专家回答（通过现有 `resolve_effective_agent_id` 的 `requested_agent_id` 路径）。
- 未命中 → host（会话 `specialist_id`，默认 primary）回答。
- assistant 消息落库时写入 `sender_agent_id`；流式事件携带 `sender_agent_id`（前端显示头像/名字）。

实现位置：
- `backend/api/legacy_routes.py` `/chat/stream`：解析 @ → 选 agent → 现有 pipeline；
- `backend/application/services/chat_service.py`：`append_message` 增加 `sender_agent_id`；
- `backend/data/session_repo.py` / `message_repo`：DTO 增加字段。

### 2.4 前端

**群聊创建**：
- `/specialists` 页新增「新建群聊」按钮 → 对话框多选专家（复用卡片头像列表）→ 创建 group 会话 → 跳转 `/chat`。
- `sessionApi.create` 支持 `participant_ids`。

**聊天页**：
- 顶部显示参与者头像组（hover 显示名字）；点开可管理成员（M2 只读展示 + 移除）。
- assistant 消息气泡：显示 `[头像] [专家名]`；用户消息不变。
- 输入框上方提示可 @ 的成员（简单 chips，点击插入 `@名字`）。
- 群聊会话在侧边栏显示群图标 + 成员数。

**类型**：
- `Session` 增加 `conversation_type?: 'dm' | 'group'`；
- `Message` 增加 `sender_agent_id?: string | null`；
- 新增 `ConversationParticipant { agent_id, name, avatar, role, enabled }`。

### 2.5 记忆语义（v1）

- 群聊中每个专家的发言仍写入**实际发言专家**的私有记忆（现有 `resolve_bound_specialist` → 改为"实际回答者"）。
- 共享层照常。

## 实施步骤

- [ ] M1.1 卡片点击直接私聊 + 详情入口移位
- [ ] M1.2 会话列表联系人身份（头像/名称徽标）
- [ ] M2.1 迁移 v16 + 参与者表 + sessions.conversation_type + messages.sender_agent_id
- [ ] M2.2 参与者 CRUD API + 会话创建扩展 + electron IPC
- [ ] M2.3 @ 解析调度（legacy + hex 路径）+ sender_agent_id 落库/事件
- [ ] M2.4 前端：建群对话框、群聊头部参与者、气泡头像名字、@ chips
- [ ] 测试：后端参与者/@解析/迁移；前端建群/群聊展示
- [ ] 文档：技术手册 + 用户手册；删除计划文件
- [ ] 提交推送开 PR（main），合并后同步 win7

## 风险

| 风险 | 缓解 |
|---|---|
| `/chat/stream` 改动触碰核心链路 | @ 解析仅影响"选择哪个 agent"，LLM/工具/流式管线不动；测试覆盖缺省路径 |
| 旧会话兼容 | conversation_type 默认 'dm'；participants 表按需回填（M2 不强制迁移旧会话，仅群聊新会话写 participants） |
| `sender_agent_id` 全链路（事件/落库/前端） | 字段可选，缺省 null → 前端回退现有展示 |
| win7 迁移编号 | main 当前 v15 → v16；win7 同步时按当时编号避让 |
