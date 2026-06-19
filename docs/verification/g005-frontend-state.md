# g005: Frontend State Management 验证映射

> 前端状态管理契约：Zustand stores、React Query cache、IPC state sync。

---

**状态**: 🔴 未验证
**维护者**: @frontend-team
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- Zustand 全局状态 stores（UI 状态、用户偏好、应用配置）
- React Query 服务端数据缓存（API 响应缓存与同步）
- Tauri IPC 状态同步（前端 ↔ 后端状态一致性）
- Optimistic updates 与回滚机制

### 不负责

- 后端数据持久化（由 g007 负责）
- API 端点实现（由 g006 负责）
- 安全认证逻辑（由 g008 负责）

### 依赖

- 依赖 g006：前端通过 API 获取/更新数据
- 依赖 g007：持久化数据最终存储在 SQLite

---

## 2. 接口契约

### 2.1 Zustand Store 定义

| Store | 状态字段 | 操作 | 订阅者 |
|-------|----------|------|--------|
| `useAppStore` | `theme`, `locale`, `sidebarOpen` | `setTheme()`, `toggleSidebar()` | 全局 UI 组件 |
| `useUserStore` | `user`, `preferences`, `sessionToken` | `login()`, `logout()`, `updatePrefs()` | Header, Settings |
| `useChatStore` | `messages`, `activeChat`, `streamingState` | `sendMessage()`, `clearChat()` | ChatPanel |

### 2.2 React Query Cache Keys

| Cache Key | 数据类型 | Stale Time | GC Time |
|-----------|----------|------------|---------|
| `['sessions']` | `Session[]` | 30s | 5min |
| `['session', id]` | `Session` | 10s | 2min |
| `['skills']` | `Skill[]` | 60s | 10min |
| `['config']` | `AppConfig` | 5min | 30min |

### 2.3 IPC State Sync

| IPC Channel | Direction | Payload | Sync Behavior |
|-------------|-----------|---------|---------------|
| `state:sync` | Backend → Frontend | `Partial<AppState>` | Merge into Zustand |
| `state:request` | Frontend → Backend | `{ key: string }` | 请求最新状态 |
| `state:notify` | Frontend → Backend | `{ key, value }` | 通知后端状态变更 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: Store 间状态一致性

**定义**：当 `useUserStore.user` 为 `null` 时，`useChatStore.messages` 必须为空数组（未登录用户无聊天记录）。

**验证方法**：
```typescript
function verifyStoreConsistency(
  userState: UserState,
  chatState: ChatState
): boolean {
  if (userState.user === null) {
    return chatState.messages.length === 0;
  }
  return true;
}
```

**检查频率**：
- [x] 每次 store 更新后（通过 Zustand middleware）
- [ ] 每小时

#### 不变量 2: Optimistic Update 回滚

**定义**：Optimistic update 失败后，必须在 500ms 内回滚到更新前状态。

**验证方法**：
```typescript
async function testOptimisticRollback() {
  const before = queryClient.getQueryData(['sessions']);
  mockApi.fail();
  await mutateAsync({ id: '1', name: 'updated' });
  await waitFor(() => {
    expect(queryClient.getQueryData(['sessions'])).toEqual(before);
  }, { timeout: 500 });
}
```

### 3.2 行为不变量

#### 幂等性

**定义**：连续两次 `setTheme('dark')` 调用后状态与一次调用相同。

#### 并发安全性

**定义**：多个 IPC `state:sync` 消息并发到达时，最终状态一致且无数据丢失。

**验证方法**：
```typescript
async function testConcurrentIpcSync() {
  const updates = Array.from({ length: 100 }, (_, i) => ({
    key: 'counter', value: i,
  }));
  await Promise.all(updates.map((u) => ipcSync(u)));
  expect(useAppStore.getState().counter).toBe(99);
}
```

### 3.3 性能不变量

#### React 渲染次数

**定义**：单次 store 更新触发的组件重渲染次数 ≤ 相关订阅组件数量。

#### IPC 同步延迟 P95 < 50ms

**定义**：IPC 消息从发送到 store 更新完成，95% 低于 50ms。

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: IPC 通道断开

**触发条件**：Tauri 后端进程崩溃、IPC 桥接超时

**影响**：严重性高，前端状态与后端不同步

**检测方式**：IPC heartbeat 超时（5s 无响应）

**恢复策略**：
1. 显示连接断开提示
2. 尝试自动重连（指数退避，最多 3 次）
3. 重连成功后全量同步状态
4. 重连失败后提示用户重启应用

### 4.2 失败模式 2: React Query 缓存失效

**触发条件**：后端 API 返回格式变更、Cache key 不匹配

**影响**：严重性中，显示旧数据或 loading 状态

**恢复策略**：
1. `onError` 回调清除失效缓存
2. 显示 fallback UI
3. 自动 retry（最多 2 次）

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/unit/frontend/stores/`

**运行命令**：
```bash
cd /home/fz/project/sage && npm run test -- --run stores/
```

**覆盖范围**：Store 初始状态、Action 正确性、Middleware 行为、Optimistic update + rollback

### 5.2 集成测试

**位置**：`tests/integration/frontend/ipc/`

**运行命令**：
```bash
cd /home/fz/project/sage && npm run test -- --run ipc/
```

**覆盖范围**：IPC 双向通信、状态同步一致性、断连恢复

### 5.3 E2E 测试

**位置**：`tests/e2e/`

**运行命令**：
```bash
cd /home/fz/project/sage && npm run test:e2e
```

**覆盖范围**：完整用户流程中的状态一致性、多窗口状态同步

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| Store 更新频率 | 计数器 | < 100/s | > 500/s | 前端 telemetry |
| IPC 消息延迟 P95 | 直方图 | < 50ms | > 200ms | 前端 telemetry |
| React Query 命中率 | 百分比 | > 80% | < 50% | 前端 telemetry |
| Optimistic 回滚率 | 百分比 | < 5% | > 20% | 前端 telemetry |

### 6.2 健康检查

**端点**：前端 `/health` 组件

**检查项**：IPC 通道连通性、React Query client 状态、Store 一致性校验

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| E2E 测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| Store 间一致性 | ❌ | - |
| Optimistic 回滚 | ❌ | - |
| IPC 并发安全 | ❌ | - |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @frontend-team |

---

## 9. 参考

- [Zustand 文档](https://docs.pmnd.rs/zustand/)
- [React Query 文档](https://tanstack.com/query/latest)
- [Tauri IPC 文档](https://v2.tauri.app/develop/calling-rust/)
- [前端代码](../../src/)
