# Sage 对齐标准 (PARITY.md)

> 定义 Sage 各子系统间的状态一致性标准和验证机制。

---

## 概述

PARITY.md 定义了 Sage 项目中不同子系统之间必须保持的一致性约束。这些约束确保：

- **前后端状态同步**：前端 UI 状态与后端数据保持一致
- **数据完整性**：跨模块操作保持数据一致性
- **冲突可检测**：自动检测状态不一致并提供解决机制
- **可验证性**：所有对齐标准都可自动化验证

---

## 1. 后端与前端状态一致性

### 1.1 记忆条目

| 对齐项 | 后端状态 | 前端状态 | 验证方法 |
|--------|----------|----------|----------|
| 记忆列表 | `MemoryManager.list()` | Zustand store `memories[]` | WebSocket 推送 + 轮询校验 |
| 记忆详情 | `MemoryManager.get(id)` | Zustand store `currentMemory` | WebSocket 推送 |
| 记忆删除 | `MemoryManager.delete(id)` | 从 store 移除 | WebSocket 推送 |
| 记忆创建 | `MemoryManager.create()` | 添加到 store | WebSocket 推送 |

**验证机制**：
```python
# 后端：状态变更时推送
async def update_memory(memory_id: str, updates: dict):
    memory = await memory_manager.update(memory_id, updates)
    await websocket.broadcast("memory_updated", memory.to_dict())

# 前端：接收推送并更新 store
websocket.on("memory_updated", (data) => {
  store.updateMemory(data);
});
```

### 1.2 会话状态

| 对齐项 | 后端状态 | 前端状态 | 验证方法 |
|--------|----------|----------|----------|
| 活跃会话 | `SessionManager.active_session` | Zustand store `activeSession` | WebSocket 推送 |
| 会话列表 | `SessionManager.list()` | Zustand store `sessions[]` | WebSocket 推送 |
| 消息历史 | `SessionManager.get_messages()` | Zustand store `messages[]` | 分页加载 + WebSocket 推送 |

### 1.3 配置状态

| 对齐项 | 后端状态 | 前端状态 | 验证方法 |
|--------|----------|----------|----------|
| API 配置 | `config.api_base_url` | Zustand store `config.apiBaseUrl` | 配置变更事件 |
| 主题设置 | `config.theme` | Zustand store `config.theme` | 配置变更事件 |
| 语言设置 | `config.language` | Zustand store `config.language` | 配置变更事件 |

---

## 2. 本地与云端一致性（未来）

### 2.1 离线记忆

**场景**：用户在离线状态下创建/修改记忆

**对齐策略**：
1. 离线时本地缓存变更（IndexedDB）
2. 上线后自动同步到云端
3. 冲突检测：比较本地和云端的时间戳
4. 冲突解决：用户选择保留版本

**验证方法**：
```python
# 离线缓存
class OfflineCache:
    async def save_change(self, change: Change):
        await indexeddb.save(change)
    
    async def sync_when_online(self):
        changes = await indexeddb.get_all()
        for change in changes:
            conflict = await detect_conflict(change)
            if conflict:
                await resolve_conflict(conflict)
            else:
                await apply_change(change)
```

### 2.2 配置同步

**场景**：用户在多个设备间同步配置

**对齐策略**：
1. 配置变更时推送到云端
2. 其他设备拉取最新配置
3. 冲突解决：最后写入优先（last-write-wins）

---

## 3. 多设备同步

### 3.1 设备发现

**机制**：
1. 局域网广播（mDNS/DNS-SD）
2. 云端注册中心
3. 手动输入设备 ID

### 3.2 数据同步

**同步协议**：
```python
class SyncProtocol:
    async def sync(self, device_id: str):
        # 1. 交换版本号
        local_version = await self.get_version()
        remote_version = await remote.get_version()
        
        # 2. 计算差异
        if local_version > remote_version:
            diff = await self.compute_diff(remote_version)
            await remote.apply_diff(diff)
        elif remote_version > local_version:
            diff = await remote.compute_diff(local_version)
            await self.apply_diff(diff)
        
        # 3. 确认同步完成
        await self.acknowledge_sync(device_id)
```

---

## 4. 验证机制

### 4.1 自动化测试

**位置**：`tests/parity/`

**测试用例**：
```python
# tests/parity/test_backend_frontend_sync.py
@pytest.mark.asyncio
async def test_memory_update_syncs_to_frontend():
    """测试记忆更新同步到前端"""
    # 1. 后端更新记忆
    await memory_manager.update(memory_id, {"content": "new content"})
    
    # 2. 等待 WebSocket 推送
    await asyncio.sleep(0.1)
    
    # 3. 验证前端状态
    frontend_state = await get_frontend_state()
    assert frontend_state.memories[memory_id].content == "new content"
```

### 4.2 运行时监控

**指标**：
- 状态不一致检测次数
- 同步延迟 P95
- 冲突发生率

**告警阈值**：
- 不一致检测 > 10 次/小时 → 警告
- 同步延迟 P95 > 500ms → 警告
- 冲突率 > 5% → 警告

### 4.3 健康检查端点

**端点**：`GET /api/v1/parity/health`

**响应**：
```json
{
  "status": "healthy",
  "checks": {
    "memory_sync": {
      "status": "ok",
      "last_sync": "2026-06-20T10:00:00Z",
      "inconsistencies": 0
    },
    "session_sync": {
      "status": "ok",
      "last_sync": "2026-06-20T10:00:00Z",
      "inconsistencies": 0
    }
  }
}
```

---

## 5. 冲突解决策略

### 5.1 自动解决

**策略 1：时间戳优先（last-write-wins）**
```python
def resolve_by_timestamp(local: dict, remote: dict) -> dict:
    if local["updated_at"] > remote["updated_at"]:
        return local
    else:
        return remote
```

**策略 2：版本号优先**
```python
def resolve_by_version(local: dict, remote: dict) -> dict:
    if local["version"] > remote["version"]:
        return local
    else:
        return remote
```

### 5.2 手动解决

**场景**：自动策略无法解决（如双方都修改了同一字段）

**流程**：
1. 检测冲突
2. 通知用户
3. 用户选择保留版本
4. 应用用户选择

---

## 6. 实施检查清单

### 后端
- [ ] 实现 WebSocket 推送机制
- [ ] 所有状态变更都推送事件
- [ ] 实现 `/api/v1/parity/health` 端点
- [ ] 编写状态同步测试

### 前端
- [ ] 实现 WebSocket 客户端
- [ ] 所有 store 更新都监听 WebSocket
- [ ] 实现离线缓存（IndexedDB）
- [ ] 编写状态同步测试

### 集成
- [ ] 端到端状态同步测试
- [ ] 冲突检测和解决测试
- [ ] 性能测试（同步延迟）
- [ ] 压力测试（高并发同步）

---

## 7. 故障排查

### 问题 1：前端状态不同步

**排查步骤**：
1. 检查 WebSocket 连接是否正常
2. 检查后端是否推送了事件
3. 检查前端是否接收并处理了事件
4. 检查 store 更新逻辑是否正确

### 问题 2：状态冲突

**排查步骤**：
1. 查看冲突日志
2. 分析冲突原因（并发修改？）
3. 检查时间戳/版本号逻辑
4. 验证冲突解决策略

---

## 8. 参考

- [设计哲学](./PHILOSOPHY.md) - 透明可控原则
- [验证映射 g005](./docs/verification/g005-frontend-state.md) - 前端状态契约
- [验证映射 g006](./docs/verification/g006-api-contracts.md) - API 契约

---

**创建时间**：2026-06-20  
**维护者**：Sage 团队  
**最后更新**：2026-06-20
