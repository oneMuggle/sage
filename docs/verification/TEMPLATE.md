# g00X: [子系统名称] 验证映射

> **使用说明**：复制此模板到 `g0XX-subsystem-name.md`，替换所有占位符。

---

**状态**: 🔴 未验证  
**维护者**: @team-member  
**最后更新**: YYYY-MM-DD

---

## 1. 范围与职责

### 负责

- 职责 1：[描述]
- 职责 2：[描述]
- 职责 3：[描述]

### 不负责

- 非职责 1：[描述]（由 g00Y 负责）
- 非职责 2：[描述]（由 g00Z 负责）

### 依赖

- 依赖 g00Y：[依赖原因]
- 依赖 g00Z：[依赖原因]

---

## 2. 接口契约

### 2.1 输入断言

| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `param1` | `str` | 非空，长度 < 1000 | `assert param1 and len(param1) < 1000` |
| `param2` | `int` | > 0，< 10000 | `assert 0 < param2 < 10000` |
| `param3` | `Optional[dict]` | 如提供，必须包含 `key1` | `assert param3 is None or 'key1' in param3` |

### 2.2 输出断言

| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `result` | `dict` | 包含 `id`, `status`, `data` | `assert all(k in result for k in ['id', 'status', 'data'])` |
| `result.id` | `str` | UUID 格式 | `assert is_valid_uuid(result.id)` |
| `result.status` | `str` | 必须是 "success" / "error" | `assert result.status in ['success', 'error']` |

### 2.3 错误处理

| 错误场景 | 错误类型 | HTTP 状态码 | 处理方式 |
|----------|----------|-------------|----------|
| 参数非法 | `ValueError` | 400 | 返回错误详情 + 修复建议 |
| 资源不存在 | `NotFoundError` | 404 | 返回 404 + 可选的替代方案 |
| 权限不足 | `PermissionError` | 403 | 返回 403 + 权限要求说明 |
| 服务不可用 | `ServiceUnavailableError` | 503 | 返回 503 + 重试建议 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: [描述]

**定义**：[详细定义]

**验证方法**：
```python
def verify_invariant_1(state: SystemState) -> bool:
    """验证不变量 1"""
    # 检查逻辑
    return condition
```

**检查频率**：
- [ ] 每次写操作后
- [ ] 每次读操作后
- [ ] 每小时
- [ ] 每天

**测试用例**：
```python
def test_invariant_1():
    """测试不变量 1"""
    # Arrange
    # Act
    # Assert
    assert verify_invariant_1(state)
```

#### 不变量 2: [描述]

[同上格式]

### 3.2 行为不变量

#### 幂等性

**定义**：相同输入产生相同输出，且状态变更一致

**验证方法**：
```python
async def test_idempotency():
    """测试幂等性"""
    result1 = await operation(input_data)
    result2 = await operation(input_data)
    
    assert result1 == result2
    assert state_after_1 == state_after_2
```

#### 顺序无关性

**定义**：操作顺序不影响最终结果

**验证方法**：
```python
async def test_order_independence():
    """测试顺序无关性"""
    # 顺序 A: op1 -> op2
    state_a = await apply_operations([op1, op2])
    
    # 顺序 B: op2 -> op1
    state_b = await apply_operations([op2, op1])
    
    assert state_a == state_b
```

#### 并发安全性

**定义**：并发操作不会导致数据不一致

**验证方法**：
```python
async def test_concurrent_safety():
    """测试并发安全性"""
    # 并发执行 100 次操作
    tasks = [operation(i) for i in range(100)]
    results = await asyncio.gather(*tasks)
    
    # 验证状态一致性
    assert verify_consistency(state)
```

### 3.3 性能不变量

#### 延迟 P95 < Xms

**定义**：95% 的请求延迟低于 X 毫秒

**验证方法**：
```python
async def test_latency_p95():
    """测试 P95 延迟"""
    latencies = []
    for _ in range(1000):
        start = time.time()
        await operation()
        latencies.append((time.time() - start) * 1000)
    
    p95 = np.percentile(latencies, 95)
    assert p95 < 200  # 200ms
```

#### 吞吐量 > Y req/s

**定义**：系统每秒处理至少 Y 个请求

**验证方法**：
```python
async def test_throughput():
    """测试吞吐量"""
    start = time.time()
    tasks = [operation() for _ in range(1000)]
    await asyncio.gather(*tasks)
    duration = time.time() - start
    
    throughput = 1000 / duration
    assert throughput > 100  # 100 req/s
```

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: [描述]

**触发条件**：
- [条件 1]
- [条件 2]

**影响**：
- 严重性：[高/中/低]
- 影响范围：[描述]

**检测方式**：
```python
def detect_failure_mode_1(state: SystemState) -> bool:
    """检测失败模式 1"""
    return condition
```

**恢复策略**：
1. [步骤 1]
2. [步骤 2]
3. [步骤 3]

**降级方案**：
- [降级措施 1]
- [降级措施 2]

**验证测试**：
```python
async def test_failure_mode_1():
    """测试失败模式 1 的恢复"""
    # 模拟失败条件
    simulate_failure_mode_1()
    
    # 验证检测
    assert detect_failure_mode_1(state)
    
    # 执行恢复
    await recovery_strategy()
    
    # 验证恢复成功
    assert state.is_healthy()
```

### 4.2 失败模式 2: [描述]

[同上格式]

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/verification/g00X/`

**运行命令**：
```bash
pytest tests/verification/g00X/ -v --cov=backend/subsystem
```

**覆盖范围**：
- [ ] 输入验证
- [ ] 输出验证
- [ ] 错误处理
- [ ] 数据不变量
- [ ] 行为不变量

### 5.2 集成测试

**位置**：`tests/integration/g00X/`

**运行命令**：
```bash
pytest tests/integration/g00X/ -v
```

**覆盖范围**：
- [ ] 与其他子系统的集成
- [ ] 端到端流程
- [ ] 并发场景

### 5.3 属性测试（如适用）

**位置**：`tests/property/g00X/`

**运行命令**：
```bash
pytest tests/property/g00X/ -v
```

**使用的库**：`hypothesis`

**测试的属性**：
- [ ] 属性 1
- [ ] 属性 2

### 5.4 性能测试

**位置**：`tests/performance/g00X/`

**运行命令**：
```bash
pytest tests/performance/g00X/ -v
```

**测试的指标**：
- [ ] 延迟
- [ ] 吞吐量
- [ ] 资源占用

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 请求延迟 P95 | 直方图 | < 200ms | > 500ms | Prometheus |
| 错误率 | 计数器 | < 1% | > 5% | Prometheus |
| 吞吐量 | 计数器 | > 100/s | < 50/s | Prometheus |
| 活跃连接数 | 仪表 | < 1000 | > 2000 | Prometheus |

### 6.2 业务指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| [业务指标 1] | [类型] | [目标] | [阈值] | [方式] |

### 6.3 健康检查

**端点**：`/health/g00X`

**检查项**：
- [ ] 依赖服务可用性
- [ ] 资源使用率
- [ ] 不变量一致性

**返回格式**：
```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "cache": "ok",
    "invariants": "ok"
  },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🟢 | 95% | 2026-06-19 |
| 集成测试 | 🟢 | 80% | 2026-06-19 |
| 性能测试 | 🟡 | 60% | 2026-06-18 |
| 属性测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 不变量 1 | ✅ | 2026-06-19 |
| 不变量 2 | ✅ | 2026-06-19 |
| 不变量 3 | ❌ | 2026-06-18 |

### 7.3 失败模式测试

| 失败模式 | 检测测试 | 恢复测试 | 状态 |
|----------|----------|----------|------|
| 失败模式 1 | ✅ | ✅ | 🟢 |
| 失败模式 2 | ✅ | ❌ | 🟡 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @team-member |

---

## 9. 参考

- [相关设计文档](../design/...)
- [相关代码](../../backend/subsystem/...)
- [相关测试](../../tests/verification/g00X/...)
