# Recap 功能计划

> 日期：2026-11-08
> 状态：进行中
> 分支：feat/recap-feature

## 背景与目标

### 背景

Claude Code 提供了 `/recap` 命令，可以总结当前会话进度并给出下一步建议。Sage 已有上下文压缩机制（`compaction.py`），但是后台静默执行，用户无法主动触发或查看结构化进度。

### 目标

1. 提供手动 recap 命令，让用户随时获取进度总结
2. 离开回归时自动显示 recap（M2）
3. 结构化展示：进度、关键决策、下一步建议、未解决问题

## 涉及的文件与模块

### 后端
| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `backend/chat/recap.py` | 新增 | Recap 生成核心逻辑 |
| `backend/api/routes/chat.py` | 修改 | 添加 `/api/v1/chat/recap` 端点 |
| `backend/models/chat.py` | 修改 | 添加 RecapRequest/RecapResponse |

### 前端
| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `src/shared/api/chatApi.ts` | 修改 | 添加 recap API 调用 |
| `src/shared/api/types/chatAndEventTypes.ts` | 修改 | 添加 RecapResult 类型 |
| `src/widgets/chat/RecapCard.tsx` | 新增 | Recap 展示卡片组件 |
| `src/widgets/chat/ChatMessageList.tsx` | 修改 | 集成 RecapCard 渲染 |
| `src/features/send-message/useChat.ts` | 修改 | 处理 /recap 命令 |

## 技术方案

### 1. Recap 数据模型

```typescript
interface RecapResult {
  progress: string;        // 当前进度总结
  decisions: string[];     // 关键决策列表
  nextSteps: string[];     // 建议的下一步
  openQuestions?: string[]; // 未解决问题
  generatedAt: string;     // 生成时间
}
```

### 2. 后端实现

复用 `compaction.py` 的 LLM 调用模式，但使用面向人类的 prompt：

```python
# backend/chat/recap.py
RECAP_SYSTEM_PROMPT = """你是一个对话进度总结助手。根据对话历史生成结构化 recap。

输出格式：
- progress: 一句话总结当前进度（20字以内）
- decisions: 本次对话中做出的关键决策（最多3条）
- nextSteps: 建议的下一步行动（最多3条）
- openQuestions: 尚未解决的问题（如有）

要求：
- 简洁、可操作
- 使用用户的语言
- 聚焦任务本身，不重复细节
"""

async def generate_recap(session_id: str) -> RecapResult:
    """生成会话 recap"""
    # 1. 获取最近消息
    messages = await message_repo.list_recent(session_id, limit=20)

    # 2. 获取已有摘要（如有）
    session = await session_repo.get(session_id)
    existing_summary = session.summary if session else None

    # 3. 调用 LLM 生成
    result = await llm_client.generate(
        system=RECAP_SYSTEM_PROMPT,
        messages=messages,
        context={"existing_summary": existing_summary},
    )

    return RecapResult.from_llm_output(result)
```

### 3. API 端点

```python
# POST /api/v1/chat/recap
# Request: { session_id: str }
# Response: { recap: RecapResult }
```

### 4. 前端交互

#### 触发方式
1. 输入 `/recap` 命令
2. 侧栏菜单"进度总结"按钮（M2）

#### 展示位置
插入聊天流，作为系统消息卡片：

```tsx
// RecapCard.tsx
<CollapsibleCard title="进度总结" icon={SummaryIcon}>
  <ProgressText>{recap.progress}</ProgressText>
  {recap.decisions.length > 0 && (
    <Section title="关键决策">
      {recap.decisions.map((d, i) => <DecisionItem key={i}>{d}</DecisionItem>)}
    </Section>
  )}
  {recap.nextSteps.length > 0 && (
    <Section title="建议下一步">
      {recap.nextSteps.map((s, i) => <NextStepItem key={i}>{s}</NextStepItem>)}
    </Section>
  )}
  {recap.openQuestions?.length > 0 && (
    <Section title="待解决问题">
      {recap.openQuestions.map((q, i) => <QuestionItem key={i}>{q}</QuestionItem>)}
    </Section>
  )}
</CollapsibleCard>
```

## 实施步骤

### M1：手动 Recap（最小可用）

- [x] 步骤 1：创建 `backend/chat/recap.py`，实现 `generate_recap()` 函数
- [x] 步骤 2：添加 API 端点 `POST /api/v1/chat/recap`
- [x] 步骤 3：前端添加 `RecapResult` 类型定义
- [x] 步骤 4：前端添加 `requestRecap()` API 调用
- [x] 步骤 5：创建 `RecapCard.tsx` 展示组件
- [x] 步骤 6：处理 `/recap` 命令，调用 API 并插入 RecapCard
- [x] 步骤 7：编写单元测试（后端 19 条 + 前端 13 条全部通过）

### M2：自动触发（后续迭代）

> M1 已实现并归档：见 [technical/140-recap-feature.md](../technical/140-recap-feature.md) + [user-manual/42-recap.md](../user-manual/42-recap.md)。M2 尚未开始。

- [ ] 步骤 8：Electron 端添加离开检测（blur/focus 事件）
- [ ] 步骤 9：5分钟回归自动触发 recap
- [ ] 步骤 10：compaction 触发时通知用户

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 调用延迟 | 用户等待 | 显示 loading 状态，设置 10s 超时 |
| 短对话无内容 | recap 无意义 | 消息少于 3 条时返回提示"对话太短" |
| 重复 recap | 资源浪费 | 前端节流：5分钟内不重复请求 |

## 依赖

- 复用现有 `llm_client` 和 `message_repo`
- 无新依赖
