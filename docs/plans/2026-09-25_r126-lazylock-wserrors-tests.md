# R126：LazyLock + workspace 错误层级单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；issue #536（LazyLock 修复）、
  session-workspace 绑定错误契约
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`orchestration/_lazy_lock.py`（103 行，线程感知的惰性 `asyncio.Lock`
工厂——issue #536 的生产修复：无事件循环线程实例化服务对象不再炸）
与 `office/workspace_errors.py`（69 行，会话工作区绑定错误层级——
`safe_message` 不泄漏文件系统布局的日志/HTTP 契约）此前零测试。

## 覆盖矩阵（约 18 例）

### `backend/tests/unit/orchestration/test_lazy_lock.py`（10 例）

1. 构造时不创建锁（`_lock is None`——惰性核心）；
2. 首次 acquire 创建、后续访问返回同一把锁；
3. `async with` 互斥：持锁期间第二协程 blocked、locked() True；
4. locked() 三态：未构造 False / 持有 True / 释放后 False；
5. acquire/release 手动配对；6. 未持锁 release → RuntimeError；
7. **#536 回归**：普通线程（无事件循环）中实例化，主线程
   asyncio.run 进入临界区成功；
8. `async with` 返回 self（aenter 契约）；
9. 异常路径 aexit 正常释放（临界区内抛错不泄漏锁）。

### `backend/tests/unit/office/test_workspace_errors.py`（8 例）

1. 六个具体错误均继承 WorkspaceBindingError；
2. code 属性逐类断言（session_not_found / workspace_not_bound /
   workspace_revoked / workspace_generation_mismatch /
   workspace_path_mismatch / document_not_found）；
3. safe_message 属性等于构造消息且不额外拼接路径；
4. str(exc) 保留原消息（日志兼容）；
5. except WorkspaceBindingError 可统一捕获（500 兜底契约）。

## 验证

- pytest 新文件 + 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 HTTP 映射（路由层职责，workspace 路由已有用例）；
- 不测 topology.py（编排拓扑属后续专项）。
