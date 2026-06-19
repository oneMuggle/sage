# PHILOSOPHY.md 理念文档计划

## 背景与目标

### 背景
Sage 项目当前缺乏一份明确的设计哲学文档，导致：
- 新开发者难以理解设计决策背后的理念
- 功能开发时缺乏统一的指导原则
- 团队对"什么该做、什么不该做"缺乏共识
- 项目演进方向不够清晰

### 目标
借鉴 claw-code 的 `PHILOSOPHY.md`，建立 Sage 的设计哲学：
1. 明确核心原则（什么是最重要的）
2. 定义反模式（我们拒绝什么）
3. 提供决策框架（如何做取舍）
4. 建立文化认同（团队共识）

## 涉及的文件与模块

### 新增文件
- `PHILOSOPHY.md` - 项目根目录，设计哲学总览
- `docs/philosophy/` - 详细理念说明
  - `docs/philosophy/core-principles.md` - 核心原则详解
  - `docs/philosophy/anti-patterns.md` - 反模式详解
  - `docs/philosophy/decision-framework.md` - 决策框架

### 关联文件
- `README.md` - 添加哲学引用
- `CONTRIBUTING.md` - 添加哲学要求
- `docs/plans/*.md` - 计划文档需符合哲学

## 技术方案

### PHILOSOPHY.md 结构

```markdown
# Sage 设计哲学

> Sage 是一个记忆增强的 AI 桌面助手，致力于成为用户的"第二大脑"。
> 本文档定义了我们如何思考、如何决策、如何构建。

## 核心原则

### 1. 记忆优先 (Memory First)

**所有交互默认持久化，除非显式拒绝。**

Sage 的核心价值在于记忆。每一次对话、每一个决策、每一个偏好都应该被记住。
但这不意味着无脑记录——我们需要：

- ✅ **智能过滤**：区分重要信息与噪声
- ✅ **结构化存储**：便于检索与推理
- ✅ **隐私保护**：用户完全控制自己的数据
- ❌ **黑盒记录**：用户不知道什么被记住
- ❌ **不可删除**：用户无法清除记忆

**实践指南**：
```python
# 好的设计
async def process_conversation(message: str, remember: bool = True):
    """默认记住，但允许用户选择"""
    if remember:
        await memory.store(message)
    return response

# 反模式
async def process_conversation(message: str):
    """强制记录，用户无法控制"""
    await memory.store(message)  # 违反隐私保护
```

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
# 好的设计
async def learn_from_mistake(mistake: Mistake):
    """学习并请求用户批准"""
    lesson = await extract_lesson(mistake)
    await user.approve_lesson(lesson)  # 人类审批
    await memory.store(lesson, status="pending")

# 反模式
async def learn_from_mistake(mistake: Mistake):
    """静默学习，用户不知情"""
    lesson = await extract_lesson(mistake)
    await memory.store(lesson)  # 违反透明原则
```

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
# 好的设计
async def auto_organize_memories():
    """自动整理记忆，但提供审计日志"""
    log.info("Starting memory organization")
    changes = []
    for memory in await memory.find_all():
        new_category = await categorize(memory)
        changes.append(Change(memory.id, memory.category, new_category))
    
    await audit_log.record("auto_organize", changes)
    await user.review_changes(changes)  # 用户确认

# 反模式
async def auto_organize_memories():
    """静默整理，无日志"""
    for memory in await memory.find_all():
        memory.category = await categorize(memory)  # 无审计
```

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
# 好的设计
def calculate_similarity(query: str, memory: str) -> float:
    """简单的余弦相似度"""
    vec1 = embed(query)
    vec2 = embed(memory)
    return cosine_similarity(vec1, vec2)

# 反模式
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

## 反模式（我们拒绝的）

### 1. 黑盒决策 ❌

**绝不允许系统在不解释的情况下做出决策。**

每一个重要决策都必须：
- 记录决策原因
- 提供可解释的输出
- 允许用户审查

### 2. 不可逆操作 ❌

**绝不允许无法撤销的操作。**

每一个修改操作都必须：
- 提供回滚机制
- 保留历史记录
- 允许用户恢复

### 3. 静默失败 ❌

**绝不允许错误被无声吞没。**

每一个错误都必须：
- 明确报告给用户
- 提供详细的错误上下文
- 给出恢复建议

### 4. 数据锁定 ❌

**绝不允许用户无法访问自己的数据。**

所有数据都必须：
- 可导出（标准格式）
- 可删除（完全清除）
- 可迁移（不依赖特定系统）

## 决策框架

当面临设计选择时，使用以下框架：

### 1. 用户价值优先

**问：这个决策对用户有什么价值？**

- 如果用户价值不明确 → 暂停，重新评估
- 如果用户价值明确 → 继续

### 2. 简单优先

**问：有更简单的方案吗？**

- 如果有更简单方案 → 先尝试简单方案
- 如果简单方案不够 → 再考虑复杂方案

### 3. 可逆优先

**问：这个决策可逆吗？**

- 如果可逆 → 快速决策，快速迭代
- 如果不可逆 → 谨慎评估，充分测试

### 4. 透明优先

**问：用户能理解这个决策吗？**

- 如果用户能理解 → 继续
- 如果用户不能理解 → 简化或提供解释

## 文化认同

Sage 不仅仅是一个产品，它是一种理念：

- **我们相信**：AI 应该增强人类能力，而不是取代人类
- **我们相信**：记忆是智能的基础，应该被尊重
- **我们相信**：透明与信任是长期关系的基石
- **我们相信**：简单胜于复杂，可逆胜于不可逆

**加入我们，构建有记忆、有温度、可信赖的 AI 助手。**
```

## 实施步骤

### 阶段 1：核心哲学编写（0.5 周）
- [ ] 1.1 编写 `PHILOSOPHY.md` 核心原则
- [ ] 1.2 定义反模式清单
- [ ] 1.3 设计决策框架
- [ ] 1.4 团队评审与迭代

### 阶段 2：详细文档扩展（1 周）
- [ ] 2.1 编写 `core-principles.md` 详解
- [ ] 2.2 编写 `anti-patterns.md` 详解
- [ ] 2.3 编写 `decision-framework.md` 详解
- [ ] 2.4 收集实际案例

### 阶段 3：整合与推广（0.5 周）
- [ ] 3.1 更新 `README.md` 添加哲学引用
- [ ] 3.2 更新 `CONTRIBUTING.md` 添加哲学要求
- [ ] 3.3 团队培训与讨论
- [ ] 3.4 收集反馈并迭代

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 哲学过于理想化 | 中 | 结合实际案例，保持务实 |
| 团队不认同 | 低 | 充分讨论，达成共识 |
| 难以落地 | 中 | 提供具体指南与检查清单 |
| 与现有代码冲突 | 中 | 渐进式改进，不强求一步到位 |

### 依赖
- 团队共识
- 实际案例收集

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| 核心哲学编写 | 0.5 周 |
| 详细文档扩展 | 1 周 |
| 整合与推广 | 0.5 周 |
| **总计** | **2 周** |

## 验证标准

1. **完整性**：核心原则、反模式、决策框架都已定义
2. **清晰性**：新开发者能快速理解
3. **实用性**：能指导实际设计决策
4. **认同度**：团队成员都认同并遵循

## 示例：设计决策应用

### 场景：是否添加自动记忆清理功能

**应用哲学**：

1. **用户价值优先**：自动清理对用户有价值（节省空间）✅
2. **简单优先**：简单规则（如基于时间）优于复杂算法 ✅
3. **可逆优先**：清理前必须备份，允许恢复 ✅
4. **透明优先**：清理前必须告知用户，显示清理日志 ✅

**决策**：添加自动清理功能，但必须：
- 使用简单规则（如 90 天未访问）
- 清理前备份
- 清理前告知用户
- 提供恢复机制

**反模式检查**：
- ❌ 黑盒决策？否，有清理日志
- ❌ 不可逆操作？否，有备份
- ❌ 静默失败？否，有错误报告
- ❌ 数据锁定？否，可导出

**结论**：符合哲学，可以实施

## 长期收益

1. **决策一致性**：团队有统一的决策框架
2. **新人上手**：快速理解项目理念
3. **文化认同**：建立团队文化
4. **长期演进**：指导项目长期发展方向
