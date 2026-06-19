# Sage 设计哲学

> Sage 是一个记忆增强的 AI 桌面助手，致力于成为用户的"第二大脑"。  
> 本文档定义了我们如何思考、如何决策、如何构建。

---

## 核心原则

### 1. 记忆优先 (Memory First)

**所有交互默认持久化，除非显式拒绝。**

Sage 的核心价值在于记忆。每一次对话、每一个决策、每一个偏好都应该被记住。但这不意味着无脑记录——我们需要：

- ✅ **智能过滤**：区分重要信息与噪声
- ✅ **结构化存储**：便于检索与推理
- ✅ **隐私保护**：用户完全控制自己的数据
- ❌ **黑盒记录**：用户不知道什么被记住
- ❌ **不可删除**：用户无法清除记忆

**实践指南**：

```python
# ✅ 好的设计
async def process_conversation(message: str, remember: bool = True):
    """默认记住，但允许用户选择"""
    if remember:
        await memory.store(message)
    return response

# ❌ 反模式
async def process_conversation(message: str):
    """强制记录，用户无法控制"""
    await memory.store(message)  # 违反隐私保护
```

---

### 2. 渐进式自演化 (Progressive Self-Evolution)

**Agent 可从错误中学习，但需人类审批。**

Sage 应该越来越懂用户，但这种演化必须是：

- ✅ **透明的**：用户能看到 Agent 学到了什么
- ✅ **可控的**：用户可以批准或拒绝学习
- ✅ **可逆的**：用户可以撤销学习结果
- ❌ **黑盒的**：用户不知道为什么 Agent 变了
- ❌ **不可逆的**：用户无法撤销变化

**实践指南**：

```python
# ✅ 好的设计
async def learn_from_mistake(mistake: Mistake):
    """学习并请求用户批准"""
    lesson = await extract_lesson(mistake)
    await user.approve_lesson(lesson)  # 人类审批
    await memory.store(lesson, status="pending")

# ❌ 反模式
async def learn_from_mistake(mistake: Mistake):
    """静默学习，用户不知情"""
    lesson = await extract_lesson(mistake)
    await memory.store(lesson)  # 违反透明原则
```

---

### 3. 透明可控 (Transparent & Controllable)

**所有自动化行为可审计、可回滚。**

Sage 的自动化必须建立在信任之上：

- ✅ **可审计**：每一步都有日志
- ✅ **可解释**：能说明为什么这样做
- ✅ **可回滚**：能撤销已执行的操作
- ❌ **黑盒自动化**：用户不知道发生了什么
- ❌ **不可逆操作**：无法撤销

**实践指南**：

```python
# ✅ 好的设计
async def auto_organize_memories():
    """自动整理记忆，但提供审计日志"""
    log.info("Starting memory organization")
    changes = []
    for memory in await memory.find_all():
        new_category = await categorize(memory)
        changes.append(Change(memory.id, memory.category, new_category))
    
    await audit_log.record("auto_organize", changes)
    await user.review_changes(changes)  # 用户确认

# ❌ 反模式
async def auto_organize_memories():
    """静默整理，无日志"""
    for memory in await memory.find_all():
        memory.category = await categorize(memory)  # 无审计
```

---

### 4. 简单胜于复杂 (Simple Over Complex)

**优先选择简单方案，除非复杂性能证明其价值。**

Sage 的架构应该：

- ✅ **易于理解**：新开发者能快速上手
- ✅ **易于测试**：每个模块可独立测试
- ✅ **易于演进**：修改一处不影响全局
- ❌ **过度设计**：为假设需求构建抽象
- ❌ **魔法行为**：隐式依赖、黑盒逻辑

**实践指南**：

```python
# ✅ 好的设计
def calculate_similarity(query: str, memory: str) -> float:
    """简单的余弦相似度"""
    vec1 = embed(query)
    vec2 = embed(memory)
    return cosine_similarity(vec1, vec2)

# ❌ 反模式
def calculate_similarity(query: str, memory: str, **kwargs) -> float:
    """过度设计的相似度计算"""
    strategy = kwargs.get('strategy', 'cosine')
    if strategy == 'cosine':
        ...
    elif strategy == 'euclidean':
        ...
    elif strategy == 'manhattan':
        ...
    # ... 10 种策略，但只用 1 种
```

---

## 反模式（我们拒绝的）

### ❌ 1. 黑盒决策

**绝不允许系统在不解释的情况下做出决策。**

每一个重要决策都必须：
- 记录决策原因
- 提供可解释的输出
- 允许用户审查

**示例**：
```python
# ❌ 错误
if should_block_user():
    block()  # 为什么？不知道

# ✅ 正确
reason = analyze_risk(user_action)
if reason.severity > THRESHOLD:
    log.info(f"Blocking user: {reason}")
    block(reason=reason)
```

---

### ❌ 2. 不可逆操作

**绝不允许无法撤销的操作。**

每一个修改操作都必须：
- 提供回滚机制
- 保留历史记录
- 允许用户恢复

**示例**：
```python
# ❌ 错误
def delete_memory(id: str):
    db.delete(id)  # 永久删除，无法恢复

# ✅ 正确
def delete_memory(id: str):
    memory = db.find(id)
    memory.status = "deleted"
    memory.deleted_at = datetime.utcnow()
    db.update(memory)  # 软删除，可恢复
```

---

### ❌ 3. 静默失败

**绝不允许错误被无声吞没。**

每一个错误都必须：
- 明确报告给用户
- 提供详细的错误上下文
- 给出恢复建议

**示例**：
```python
# ❌ 错误
try:
    process()
except Exception:
    pass  # 吞掉错误

# ✅ 正确
try:
    process()
except Exception as e:
    log.error(f"Process failed: {e}")
    notify_user(f"处理失败: {e}", suggestion="请重试或联系支持")
```

---

### ❌ 4. 数据锁定

**绝不允许用户无法访问自己的数据。**

所有数据都必须：
- 可导出（标准格式）
- 可删除（完全清除）
- 可迁移（不依赖特定系统）

**示例**：
```python
# ✅ 提供导出功能
def export_all_data(user_id: str) -> ExportResult:
    """导出用户所有数据为标准 JSON"""
    data = {
        "memories": db.find_memories(user_id),
        "conversations": db.find_conversations(user_id),
        "preferences": db.find_preferences(user_id),
    }
    return ExportResult(format="json", data=data)
```

---

## 决策框架

当面临设计选择时，使用以下框架：

### 1️⃣ 用户价值优先

**问：这个决策对用户有什么价值？**

- 如果用户价值不明确 → 暂停，重新评估
- 如果用户价值明确 → 继续

**示例**：
```
功能：自动记忆清理
用户价值：节省存储空间 ✅
决策：继续
```

---

### 2️⃣ 简单优先

**问：有更简单的方案吗？**

- 如果有更简单方案 → 先尝试简单方案
- 如果简单方案不够 → 再考虑复杂方案

**示例**：
```
需求：相似度计算
简单方案：余弦相似度 ✅
复杂方案：深度学习语义匹配
决策：先用余弦，不够再升级
```

---

### 3️⃣ 可逆优先

**问：这个决策可逆吗？**

- 如果可逆 → 快速决策，快速迭代
- 如果不可逆 → 谨慎评估，充分测试

**示例**：
```
决策 A：修改 UI 颜色 → 可逆 → 快速实施
决策 B：删除用户数据 → 不可逆 → 谨慎评估
```

---

### 4️⃣ 透明优先

**问：用户能理解这个决策吗？**

- 如果用户能理解 → 继续
- 如果用户不能理解 → 简化或提供解释

**示例**：
```
决策：自动删除 90 天未访问的记忆
用户理解：✅ 简单明了
决策：继续
```

---

## 文化认同

Sage 不仅仅是一个产品，它是一种理念：

- **我们相信**：AI 应该增强人类能力，而不是取代人类
- **我们相信**：记忆是智能的基础，应该被尊重
- **我们相信**：透明与信任是长期关系的基石
- **我们相信**：简单胜于复杂，可逆胜于不可逆

**加入我们，构建有记忆、有温度、可信赖的 AI 助手。**

---

## 进一步阅读

- [核心原则详解](./docs/philosophy/core-principles.md)
- [反模式详解](./docs/philosophy/anti-patterns.md)
- [决策框架详解](./docs/philosophy/decision-framework.md)
- [贡献指南](./CONTRIBUTING.md)

---

**最后更新**：2026-06-19  
**维护者**：Sage 团队
