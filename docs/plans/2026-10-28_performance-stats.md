# 性能统计功能：会话用时 + 模型调用用时

- **状态**：已完成（Phase 1 + Phase 2 + 后续优化 3/4 项）
- **分支**：`feat/win7-performance-stats`（同步自 main `feat/performance-stats`）
- **创建日期**：2026-10-28
- **优先级**：P2（增强功能，非核心阻塞）
- **最后更新**：2026-10-28 15:40

## 0. 背景与目标

### 背景

用户对比DSH（DeepSeek Harness）时发现，Sage缺少以下时间相关的统计功能：
1. **会话用时统计**：从会话创建到最后一次消息的总时长
2. **模型调用用时统计**：每次LLM API调用的耗时

Sage已有完善的token用量统计系统（`usage_events`表、`SessionUsageBadge`组件等），但缺少时间维度的性能指标。

### 目标

增加两个核心性能指标：
1. **会话用时**：帮助用户了解AI交互的时间成本
2. **模型调用用时**：性能监控的关键指标，识别慢请求

### 非目标

- **不实现"X轮X步"统计**：定义模糊，Sage已有`message_count`和`session_events`提供足够的结构信息
- **不改变现有用量统计逻辑**：仅做增量增强

## 1. 功能范围

### Phase 1：会话用时统计（快速收益）

**功能描述**：
- 在Session模型中提供会话总用时（`duration_minutes`）
- 可选：前端会话列表中展示（tooltip或徽章）

**实现方案**：
- 利用已有字段计算：`duration = last_message_at - created_at`
- 无需数据库迁移
- 后端API返回计算字段
- 前端展示（可选）

**涉及文件**：
- `backend/data/session_repo.py`：Session模型添加`duration_minutes`计算属性
- `backend/api/legacy_chat_routes.py`或新API：返回会话详情时包含用时
- `src/shared/api/sessionApi.ts`：类型定义
- `src/widgets/session/SessionItem.tsx`（可选）：前端展示

### Phase 2：模型调用用时统计（核心功能）

**功能描述**：
- 每次LLM API调用记录耗时（`duration_ms`）
- 会话级聚合：平均响应时间、P95、最慢请求
- 前端展示：会话用量徽章中增加平均响应时间

**实现方案**：
1. **数据库迁移**：
   - `usage_events`表新增`duration_ms`列（INTEGER，可选）
   - 迁移脚本：`backend/data/migrations/`
   
2. **后端记录**：
   - 在LLM API调用点（`backend/llm/`或`backend/chat/`）记录时间
   - 写入`usage_events`表
   
3. **聚合查询**：
   - `GET /api/v1/usage/session/{id}`返回：
     - `avg_duration_ms`：平均响应时间
     - `p95_duration_ms`：P95响应时间
     - `max_duration_ms`：最慢请求
   
4. **前端展示**：
   - `SessionUsageBadge`增加平均响应时间展示
   - 可选：慢请求警告（>10s）

**涉及文件**：
- `backend/data/migrations/`：新增迁移脚本
- `backend/data/usage_repo.py`：新增`duration_ms`字段
- `backend/llm/client.py`或`backend/chat/stream.py`：记录调用时间
- `backend/api/usage_routes.py`：聚合查询
- `src/shared/api/usageApi.ts`：类型定义
- `src/widgets/chat/SessionUsageBadge.tsx`：前端展示

## 2. 技术方案

### 2.1 会话用时（Phase 1）

**后端实现**：

```python
# backend/data/session_repo.py
@dataclass
class Session:
    # ... 已有字段 ...
    
    @property
    def duration_minutes(self) -> Optional[int]:
        """会话总用时（分钟），从创建到最后一次消息。"""
        if not self.last_message_at or not self.created_at:
            return None
        duration_ms = self.last_message_at - self.created_at
        return int(duration_ms / 60000)
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            # ... 已有字段 ...
            "duration_minutes": self.duration_minutes,
        }
        return result
```

**前端类型**：

```typescript
// src/shared/api/sessionApi.ts
export interface Session {
  // ... 已有字段 ...
  duration_minutes?: number;
}
```

**前端展示**（可选）：

```tsx
// src/widgets/session/SessionItem.tsx
{session.duration_minutes !== undefined && (
  <span className="text-ui-2xs text-text-muted" title="会话用时">
    ⏱️ {session.duration_minutes}分钟
  </span>
)}
```

### 2.2 模型调用用时（Phase 2）

**数据库迁移**：

```sql
-- backend/data/migrations/XXX_add_duration_to_usage_events.sql
ALTER TABLE usage_events ADD COLUMN duration_ms INTEGER;
```

**后端记录**：

```python
# backend/llm/client.py 或 backend/chat/stream.py
import time

async def call_llm_api(...):
    start_time = time.time()
    try:
        response = await llm_client.chat_completion(...)
        return response
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        # 写入 usage_events
        await usage_repo.record_duration(
            session_id=session_id,
            duration_ms=duration_ms,
            ...
        )
```

**聚合查询**：

```python
# backend/api/usage_routes.py
@router.get("/api/v1/usage/session/{session_id}")
async def get_session_usage(session_id: str):
    # ... 已有逻辑 ...
    
    # 新增：时间统计
    duration_stats = await usage_repo.get_duration_stats(session_id)
    
    return {
        **existing_data,
        "avg_duration_ms": duration_stats.avg,
        "p95_duration_ms": duration_stats.p95,
        "max_duration_ms": duration_stats.max,
    }
```

**前端展示**：

```tsx
// src/widgets/chat/SessionUsageBadge.tsx
{usage.avg_duration_ms !== null && (
  <span className="ml-1" title="平均响应时间">
    · ⚡ {Math.round(usage.avg_duration_ms / 1000)}s
  </span>
)}
```

## 3. 实施步骤

### Phase 1：会话用时（已完成 ✅）

- [x] **步骤1.1**：Session模型添加`duration_minutes`计算属性
  - 文件：`backend/data/session_repo.py`
  - 完成时间：2026-10-28
  - 实现：在Session类中添加@property方法，计算`last_message_at - created_at`
  
- [x] **步骤1.2**：API返回会话详情时包含用时
  - 文件：`backend/data/session_repo.py`
  - 完成时间：2026-10-28
  - 实现：在Session.to_dict()中包含`duration_minutes`字段
  
- [x] **步骤1.3**：前端类型定义
  - 文件：`src/shared/api/types/chatAndEventTypes.ts`
  - 完成时间：2026-10-28
  - 实现：Session接口添加`duration_minutes?: number | null`字段
  
- [x] **步骤1.4**（可选）：前端会话列表展示
  - 文件：`src/widgets/session/SessionItem.tsx`
  - 完成时间：2026-10-28
  - 实现：会话元数据行展示 Clock 图标 + 用时（分钟 / 小时+分钟自动切换）

### Phase 2：模型调用用时（已完成 ✅）

> **发现**：`latency_ms`字段已存在于`usage_events`表中，且`backend/core/legacy/llm_client.py`已在记录LLM API调用延迟。因此无需数据库迁移和数据采集步骤。

- [x] ~~**步骤2.1**：数据库迁移~~
  - **跳过**：`usage_events`表已有`latency_ms`列（INTEGER类型）
  - 数据库模式：`backend/data/database.py` line 1343-1347
  
- [x] ~~**步骤2.2**：usage_repo支持duration_ms~~
  - **跳过**：字段已存在，无需新增方法
  - `UsageRepo`已支持`latency_ms`字段的读写
  
- [x] ~~**步骤2.3**：LLM API调用点记录时间~~
  - **跳过**：`backend/core/legacy/llm_client.py`已使用`time.monotonic()`记录延迟
  - 实现位置：llm_client.py中的API调用点
  
- [x] **步骤2.4**：API聚合查询
  - 文件：`backend/services/usage_tracker.py`
  - 完成时间：2026-10-28
  - 实现：在`session_summary()`方法中查询`latency_ms`并计算avg/p95/max统计
  - P95计算：使用排序数组索引法 `p95_index = min(int(n * 0.95), n - 1)`
  
- [x] **步骤2.5**：前端类型定义
  - 文件：`src/shared/api/usageApi.ts`
  - 完成时间：2026-10-28
  - 新增字段：
    - `avg_latency_ms: number | null`
    - `p95_latency_ms: number | null`
    - `max_latency_ms: number | null`
  
- [x] **步骤2.6**：前端展示
  - 文件：`src/widgets/chat/SessionUsageBadge.tsx`
  - 完成时间：2026-10-28
  - 实现：展示平均响应时间（格式化为秒，保留1位小数）
  - Tooltip：显示完整统计（avg/p95/max）
  - 图标：使用⚡符号标识

### Phase 3：后续优化（已完成 3/4 项 ✅）

- [x] **步骤3.1**：会话列表展示用时
  - 文件：`src/widgets/session/SessionItem.tsx`
  - 完成时间：2026-10-28
  - 实现：元数据行追加 Clock 图标 + 用时（< 60 分钟显示分钟，否则显示小时+分钟）

- [x] **步骤3.2**：慢请求警告
  - 文件：`src/widgets/chat/SessionUsageBadge.tsx`
  - 完成时间：2026-10-28
  - 实现：平均响应时间 > 10000ms 时徽章改用 `text-warning` 色

- [x] **步骤3.3**：按模型统计
  - 文件：`backend/services/usage_tracker.py`、`src/shared/api/usageApi.ts`、`src/widgets/chat/SessionUsageBadge.tsx`
  - 完成时间：2026-10-28
  - 实现：后端 `GROUP BY model` 聚合 avg_latency_ms + count，按次数降序；前端 tooltip 分组展示

- [x] **步骤3.4**：CSV 导出包含时间统计
  - **无需改动**：`GET /api/v1/usage/export/csv` 既有输出 `latency_ms` 列

- [ ] **步骤3.5**：性能趋势图（未实施）
  - 需扩展 `GET /api/v1/usage/trend` 增加延迟序列（当前仅 token/成本/缓存）+ 前端图表

## 4. 测试计划

### 单元测试

1. **Session.duration_minutes**：
   - 正常情况：有created_at和last_message_at
   - 边界情况：last_message_at为None
   - 边界情况：created_at为None

2. **usage_repo.get_duration_stats()**：
   - 正常情况：有多条记录，计算avg/p95/max
   - 边界情况：无记录
   - 边界情况：只有一条记录

### 集成测试

1. **LLM API调用记录时间**：
   - 发送聊天请求，验证usage_events表中duration_ms字段有值
   
2. **API聚合查询**：
   - 调用`GET /api/v1/usage/session/{id}`，验证返回时间统计

### E2E测试

1. **前端展示**：
   - 打开会话，验证SessionUsageBadge展示平均响应时间

## 5. 风险评估

### 低风险

- **会话用时**：纯计算字段，无数据库变更，风险极低
- **向后兼容**：新字段都是可选的，不影响现有功能

### 中风险

- **性能影响**：每次LLM调用多一次数据库写入
  - 缓解：异步写入，不阻塞主流程
  - 监控：观察写入延迟
  
- **数据一致性**：duration_ms与usage_events的其他字段必须同步
  - 缓解：同事务写入

### 未知风险

- **LLM API调用点定位**：需要确认所有调用点，可能分散在多个文件
  - 缓解：代码审查 + grep搜索

## 6. 验收标准

### Phase 1 验收

- [x] Session API返回`duration_minutes`字段
- [x] 前端类型定义完整
- [x] 单元测试覆盖
- [ ] 文档更新（用户手册）

### Phase 2 验收

- [x] 数据库迁移成功（**N/A**——`latency_ms`列已存在，无需迁移）
- [x] LLM API调用记录duration_ms（**既有实现**——`llm_client.py` 已用 `time.monotonic()` 记录）
- [x] API返回时间统计（avg/p95/max）
- [x] 前端展示平均响应时间
- [x] 集成测试通过
- [x] 性能测试：写入延迟<10ms（**N/A**——无新增写入路径，仅只读聚合查询）

### Phase 3 验收（后续优化）

- [x] 慢请求警告：平均响应时间 > 10s 时徽章转为 `text-warning`
- [x] 按模型统计：`GROUP BY model` 返回每个模型的 avg_latency_ms + count
- [x] CSV导出包含时间统计（**既有实现**——`usage_export_csv` 已输出 `latency_ms` 列）
- [ ] 性能趋势图（未实施，见 §7）

## 7. 后续优化（可选）

- [x] **慢请求警告**：响应时间>10s时前端提示 → `SessionUsageBadge` 徽章警告色
- [ ] **性能趋势图**：展示响应时间随时间的变化 → 需扩展 `GET /api/v1/usage/trend` 增加延迟序列 + 前端图表
- [x] **按模型统计**：不同模型的平均响应时间对比 → tooltip 内分组展示
- [x] **导出功能**：CSV导出包含时间统计 → `usage_export_csv` 既有 `latency_ms` 列

## 8. 参考资料

- DSH（DeepSeek Harness）：对标对象
- Sage现有用量统计：`usage_events`表、`SessionUsageBadge`组件
- 会话事件日志：`session_events`表（DSH对标R1）
- 数据库迁移框架：`backend/data/migrations/`
