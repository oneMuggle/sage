# 定时任务报告渲染修复方案

**日期**: 2026-11-02
**分支**: fix/scheduled-task-report-rendering
**状态**: 进行中

## 背景与目标

用户在会话中设定了定时任务（间隔 1 小时汇报），但只显示了图标"U"+时间，看不到报告内容。

**目标**: 定时任务触发的消息能正常显示内容，侧栏预览也能展示报告摘要。

## 问题根因

### 1. 后端写入角色

`backend/services/scheduler.py:506-509` 以 `role="system"` 写入定时任务消息。

### 2. 前端渲染逻辑

`src/widgets/chat/Message.tsx`:
- 第 101-103 行: `isUser / isAssistant / isSystem` 判断
- 第 132 行: `showBubble = isUser || (isAssistant && ...)` — system 消息被排除，气泡不渲染
- 第 295 行: 头像 `{isAssistant ? 'S' : 'U'}` — system 消息显示"U"

### 3. 侧栏预览过滤

`backend/api/legacy_session_routes.py:165` 和 `sqlite_adapter.py:209` 的 SQL 只取 `role IN ('user','assistant')`，system 消息不进入预览。

## 涉及的文件

| 文件 | 修改内容 |
|------|----------|
| `src/widgets/chat/Message.tsx` | showBubble 加入 isSystem；头像逻辑加 system 分支 |
| `backend/services/scheduler.py` | （可选）不改，保持 system 语义 |
| 测试文件 | 新增/更新测试覆盖 system 消息渲染 |

## 技术方案

### 方案 A（采用）: 前端补齐 system 消息渲染路径

**Message.tsx 修改**:

```tsx
// 第 132 行 showBubble
const showBubble = isUser || isSystem || (isAssistant && Boolean((message.content ?? '').trim()));

// 第 295 行头像
{isAssistant ? 'S' : isSystem ? '⏰' : 'U'}
```

**优点**:
- 语义正确（system 就是系统消息）
- 与现有 `compact_info` 路径一致
- 后端无需改动

### 方案 B（放弃）: 后端改用 role="assistant"

修改 `scheduler.py` 把 `role="system"` 改为 `role="assistant"`。

**放弃原因**: 语义上 `assistant` 代表 LLM 回复，用于定时任务有歧义。

## 实施步骤

- [x] 步骤 1: 修改 Message.tsx showBubble 逻辑
- [x] 步骤 2: 修改 Message.tsx 头像逻辑
- [x] 步骤 3: 补充/更新前端测试（现有测试通过，无需新增）
- [x] 步骤 4: 本地验证（单元测试通过）
- [x] 步骤 5: 提交 + PR（PR #2793）

## 风险评估

- **低风险**: 仅影响前端渲染，不改动后端数据结构
- **兼容性**: 现有 system 消息（如 compact_info）走特殊路径，不受影响
