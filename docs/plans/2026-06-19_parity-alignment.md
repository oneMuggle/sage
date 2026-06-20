# PARITY.md 对齐验证计划

## 背景与目标

### 背景
Sage 项目包含多个子系统（后端、前端、数据库、API），这些子系统之间存在状态同步需求。当前缺乏明确的一致性约束，导致：
- 前后端状态可能不同步
- 本地与云端数据冲突难以解决
- 跨模块操作的一致性难以保证

### 目标
借鉴 claw-code 的 `PARITY.md`，建立 Sage 各模块的对齐标准：
1. 定义后端与前端状态一致性规则
2. 定义本地与云端一致性规则（为未来扩展准备）
3. 提供自动化验证机制
4. 明确冲突解决策略

## 涉及的文件与模块

### 新增文件
- `PARITY.md` - 项目根目录，对齐标准总览
- `docs/parity/` - 详细对齐规则
  - `docs/parity/backend-frontend.md` - 后端与前端状态对齐
  - `docs/parity/local-cloud.md` - 本地与云端数据对齐
  - `docs/parity/multi-device.md` - 多设备同步对齐

### 关联模块
- `backend/` - 后端状态管理
- `src/` - 前端状态管理（Zustand）
- `backend/database/` - 数据持久化
- `backend/api/` - API 层

## 技术方案

### PARITY.md 结构

```markdown
# Sage 对齐标准 (PARITY.md)

## 1. 后端与前端状态一致性

### 1.1 记忆条目
- [ ] CRUD 操作双向同步
- [ ] 乐观更新 + 回滚机制
- [ ] 冲突检测与合并

### 1.2 技能安装状态
- [ ] 安装/卸载状态实时同步
- [ ] 技能配置变更同步
- [ ] 技能依赖检查

### 1.3 配置变更
- [ ] 配置修改即时生效
- [ ] 配置版本控制
- [ ] 配置回滚支持

## 2. 本地与云端一致性（未来）

### 2.1 离线记忆
- [ ] 离线时本地缓存
- [ ] 上线后自动同步
- [ ] 冲突解决策略

### 2.2 配置同步
- [ ] 配置项云端备份
- [ ] 跨设备配置同步
- [ ] 配置冲突合并

## 3. 多设备同步

### 3.1 设备发现
- [ ] 局域网设备自动发现
- [ ] 设备认证与授权
- [ ] 设备能力协商

### 3.2 数据同步
- [ ] 增量同步（非全量）
- [ ] 冲突解决（last-write-wins / 手动合并）
- [ ] 同步状态可视化

## 4. 验证机制

### 4.1 自动化测试
- [ ] 状态一致性测试
- [ ] 冲突场景测试
- [ ] 性能基准测试

### 4.2 运行时监控
- [ ] 状态不一致检测
- [ ] 同步延迟监控
- [ ] 冲突率统计

## 5. 冲突解决策略

### 5.1 自动解决
- 时间戳优先（last-write-wins）
- 版本号优先
- 合并兼容变更

### 5.2 手动解决
- 用户选择保留版本
- 合并编辑器（复杂冲突）
```

### 状态同步机制

#### 后端 → 前端（推送）
```python
# WebSocket 推送状态变更
class StateSyncManager:
    async def broadcast_state_change(self, entity_type: str, entity_id: str, new_state: dict):
        """向后端所有连接的客户端广播状态变更"""
        message = {
            "type": "state_change",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "new_state": new_state,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.websocket_manager.broadcast(message)
```

#### 前端 → 后端（乐观更新）
```typescript
// 前端乐观更新 + 回滚
const updateMemory = async (id: string, updates: Partial<Memory>) => {
  // 乐观更新
  const previousState = queryClient.getQueryData(['memory', id]);
  queryClient.setQueryData(['memory', id], (old: Memory) => ({ ...old, ...updates }));
  
  try {
    // 发送请求
    await api.updateMemory(id, updates);
  } catch (error) {
    // 回滚
    queryClient.setQueryData(['memory', id], previousState);
    toast.error('更新失败，已回滚');
  }
};
```

### 冲突检测与解决

#### 冲突检测
```python
class ConflictDetector:
    def detect_conflict(self, local: dict, remote: dict) -> Optional[Conflict]:
        """检测本地与远程数据的冲突"""
        if local['version'] == remote['version']:
            return None  # 无冲突
        
        if local['last_modified'] > remote['last_modified']:
            # 本地更新，但远程版本更高
            return Conflict(
                entity_id=local['id'],
                local_version=local['version'],
                remote_version=remote['version'],
                resolution_strategy='manual'
            )
        
        return None
```

#### 冲突解决策略
```python
class ConflictResolver:
    def resolve(self, conflict: Conflict, strategy: str = 'auto') -> dict:
        """解决冲突"""
        if strategy == 'last_write_wins':
            return self._resolve_by_timestamp(conflict)
        elif strategy == 'version_priority':
            return self._resolve_by_version(conflict)
        elif strategy == 'manual':
            return self._prompt_user_resolution(conflict)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
```

## 实施步骤

### 阶段 1：PARITY.md 框架（0.5 周）
- [ ] 1.1 创建 `PARITY.md` 项目根目录
- [ ] 1.2 定义对齐标准结构
- [ ] 1.3 列出所有需要对齐的实体
- [ ] 1.4 定义冲突解决策略

### 阶段 2：后端-前端对齐（1.5 周）
- [ ] 2.1 实现 WebSocket 状态推送
- [ ] 2.2 实现前端乐观更新机制
- [ ] 2.3 实现冲突检测逻辑
- [ ] 2.4 编写状态一致性测试
- [ ] 2.5 编写冲突场景测试

### 阶段 3：本地-云端对齐（预留）（2 周）
- [ ] 3.1 设计云端同步协议
- [ ] 3.2 实现离线缓存机制
- [ ] 3.3 实现增量同步算法
- [ ] 3.4 实现冲突合并策略
- [ ] 3.5 编写同步测试

### 阶段 4：监控与可视化（1 周）
- [ ] 4.1 实现状态不一致检测
- [ ] 4.2 添加同步延迟监控
- [ ] 4.3 实现冲突率统计
- [ ] 4.4 开发同步状态仪表板（可选）

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 状态不一致难以检测 | 高 | 添加版本号 + 时间戳双重校验 |
| 冲突解决用户体验差 | 中 | 提供清晰的冲突提示与合并选项 |
| 同步延迟过高 | 中 | 优化 WebSocket 推送，减少轮询 |
| 云端同步复杂度 | 高 | 分阶段实施，先本地后云端 |

### 依赖
- WebSocket 支持（后端 + 前端）
- Zustand 状态管理（前端）
- 云端存储（未来扩展）

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| PARITY.md 框架 | 0.5 周 |
| 后端-前端对齐 | 1.5 周 |
| 本地-云端对齐 | 2 周（预留） |
| 监控与可视化 | 1 周 |
| **总计** | **5 周** |

## 验证标准

1. **一致性验证**：前后端状态 100% 一致
2. **冲突验证**：冲突检测率 > 99%
3. **性能验证**：状态同步延迟 < 500ms
4. **用户验证**：冲突解决用户满意度 > 80%

## 示例场景

### 场景 1：记忆条目更新
```
1. 用户在前端修改记忆条目
2. 前端乐观更新本地状态
3. 前端发送更新请求到后端
4. 后端更新数据库
5. 后端通过 WebSocket 广播状态变更
6. 其他客户端接收变更并更新状态
7. 如果发生冲突，触发冲突解决流程
```

### 场景 2：技能安装同步
```
1. 用户在设备 A 安装技能
2. 设备 A 后端记录安装状态
3. 设备 A 通过 WebSocket 通知其他设备
4. 设备 B、C 接收通知
5. 设备 B、C 自动下载并安装技能
6. 所有设备状态保持一致
```

## 长期收益

1. **数据一致性**：避免状态不同步导致的问题
2. **用户体验**：即时反馈，无感知同步
3. **多设备支持**：为跨设备协作铺路
4. **可维护性**：明确的一致性规则，易于调试
