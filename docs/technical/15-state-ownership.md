# 状态所有者原则

> 日期：2026-09-21
> 状态：强制约束
> 优先级：最高（覆盖所有其他状态管理规范）

本文档定义 Sage 项目中状态管理的三条铁律。所有状态（内存、持久化、UI）必须遵守这些原则。

---

## 铁律 1：单一状态所有者

**每个状态有且仅有一个写入路径，禁止重复状态或多条写入路径。**

### 为什么？

- 多条写入路径导致状态不一致
- 重复状态导致同步问题
- 调试时无法确定"谁改了这个状态"

### 反例：WorkingMemory 不是单例

```python
# ❌ 错误：直接新建实例
working_memory = WorkingMemory()  # 创建空实例，导致 context_reset 串味

# ✅ 正确：通过 agent 的 memory_manager 访问共享实例
working_memory = agent.memory_manager.working
```

**教训**：[[sage-working-memory-not-singleton]] —— `WorkingMemory()` 新建空实例导致 context_reset 跨段串味。

### 正确模式

```python
# Backend: 通过服务层访问
class OfficeService:
    def __init__(self, office_repo: OfficeRepository):
        self._office_repo = office_repo  # 单一所有者

    async def get_office(self, office_id: str) -> Office:
        return await self._office_repo.find_by_id(office_id)
```

```typescript
// Frontend: 通过 Zustand store 访问
const useOfficeStore = create<OfficeState>((set) => ({
  currentOffice: null,
  setCurrentOffice: (office) => set({ currentOffice: office }),
}));

// ✅ 正确：通过 store 访问
const office = useOfficeStore((state) => state.currentOffice);

// ❌ 错误：直接修改组件本地状态（与 store 重复）
const [localOffice, setLocalOffice] = useState(null);
```

---

## 铁律 2：接口 + 依赖方向 + 事件顺序 + 幂等边界

**UI 组件通过 hooks 访问服务，不直接调用实现；backend 服务层必须定义 ports（接口），adapters 实现。**

### 依赖方向

```
Frontend:
  UI Component → Hook → Service → Store
  (不允许跳过 Hook 直接调用 Service)

Backend:
  API → Service → Port (接口) → Adapter (实现)
  (不允许 Service 直接依赖 Adapter 实现)
```

### 事件顺序

当状态变更时，必须明确事件传播顺序：

```
1. 用户操作 → UI Component
2. UI Component → Hook (调用 Service)
3. Service → Backend API
4. Backend → 状态变更
5. Backend → WebSocket 推送事件
6. Frontend → 接收事件 → 更新 Store
7. Store → UI Component 重新渲染
```

**禁止**：
- ❌ UI Component 直接调用 Backend API
- ❌ Backend 直接修改 Frontend Store（必须通过事件）
- ❌ 跳过 Hook，Service 直接操作 DOM

### 幂等边界

所有跨模块操作必须是幂等的：

```python
# ✅ 正确：幂等操作
async def process_document(doc_id: str):
    if await self._is_processed(doc_id):
        return  # 已处理，跳过
    await self._mark_as_processed(doc_id)
    await self._do_actual_processing(doc_id)

# ❌ 错误：非幂等操作
async def process_document(doc_id: str):
    await self._do_actual_processing(doc_id)  # 重复调用会重复处理
```

---

## 铁律 3：跨模块事件传播

**状态变更通过事件广播，而不是直接修改消费者状态。**

### 为什么？

- 直接修改消费者状态导致模块耦合
- 事件广播允许模块独立演进
- 事件可以记录、回放、调试

### 示例：后端状态变更 → 前端更新

```python
# Backend: 状态变更时推送事件
class OfficeService:
    async def update_office(self, office_id: str, data: dict):
        office = await self._office_repo.update(office_id, data)
        # ✅ 正确：通过 WebSocket 推送事件
        await self._event_bus.emit("office.updated", {"office_id": office_id})
        return office

    # ❌ 错误：直接修改前端状态（后端不应该知道前端的存在）
    async def update_office(self, office_id: str, data: dict):
        office = await self._office_repo.update(office_id, data)
        await self._frontend_store.set_current_office(office)  # 耦合！
```

```typescript
// Frontend: 订阅事件并更新 Store
const useOfficeEvents = () => {
  const setCurrentOffice = useOfficeStore((state) => state.setCurrentOffice);

  useEffect(() => {
    const unsubscribe = ws.subscribe("office.updated", (event) => {
      // ✅ 正确：接收事件，更新 Store
      setCurrentOffice(event.data);
    });
    return unsubscribe;
  }, []);
};
```

### 事件命名规范

```
<domain>.<action>

示例：
- office.created
- office.updated
- office.deleted
- session.started
- session.ended
- memory.added
```

---

## 检查清单

在修改状态相关代码前，检查：

- [ ] 这个状态有且仅有一个写入路径吗？
- [ ] 是否有重复状态（同一个数据存在多处）？
- [ ] UI 组件是否通过 Hook 访问服务？
- [ ] Backend 服务层是否依赖 Port（接口）而非 Adapter（实现）？
- [ ] 状态变更是否通过事件广播？
- [ ] 跨模块操作是否幂等？

---

## 相关 Memory 条目

- [[sage-working-memory-not-singleton]]：WorkingMemory 非单例教训
- [[sage-settings-toggle-a11y-gap]]：UI 组件 a11y 缺陷（状态所有者不明确）
- [[py38-run-in-executor-contextvar-loss]]：ContextVar 丢失（状态传播问题）
