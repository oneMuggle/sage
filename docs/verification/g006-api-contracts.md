# g006: API Contracts 验证映射

> REST API 契约：端点定义、请求/响应格式、错误码、分页、速率限制。

---

**状态**: 🔴 未验证
**维护者**: @backend-team
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- REST API 端点定义与实现
- 请求/响应格式标准化（统一 envelope）
- 错误码体系与错误响应
- 分页、排序、过滤参数
- 速率限制与请求校验

### 不负责

- 前端状态管理（由 g005 负责）
- 数据持久化与迁移（由 g007 负责）
- 认证/授权机制设计（由 g008 负责）

### 依赖

- 依赖 g007：API 读写 SQLite 数据库
- 依赖 g008：请求认证与权限校验

---

## 2. 接口契约

### 2.1 统一响应 Envelope

所有 API 响应必须遵循统一格式：

```json
{
  "success": true,
  "data": { "...": "..." },
  "error": null,
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100,
    "total_pages": 5
  }
}
```

错误响应：
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [{ "field": "name", "message": "不能为空" }]
  },
  "meta": null
}
```

### 2.2 端点列表

| 方法 | 路径 | 描述 | 认证 | 速率限制 |
|------|------|------|------|----------|
| GET | `/health` | 健康检查 | 否 | 60/min |
| GET | `/api/sessions` | 会话列表 | 是 | 30/min |
| POST | `/api/sessions` | 创建会话 | 是 | 10/min |
| GET | `/api/sessions/:id` | 获取会话详情 | 是 | 60/min |
| DELETE | `/api/sessions/:id` | 删除会话 | 是 | 10/min |
| GET | `/api/skills` | 技能列表 | 是 | 30/min |
| POST | `/api/skills/:id/execute` | 执行技能 | 是 | 5/min |
| GET | `/api/config` | 应用配置 | 是 | 30/min |
| PUT | `/api/config` | 更新配置 | 是 | 5/min |

### 2.3 分页参数

| 参数 | 类型 | 默认值 | 约束 |
|------|------|--------|------|
| `page` | `int` | 1 | ≥ 1 |
| `per_page` | `int` | 20 | 1-100 |
| `sort_by` | `string` | `created_at` | 允许字段白名单 |
| `sort_order` | `string` | `desc` | `asc` / `desc` |

### 2.4 错误码体系

| HTTP 状态码 | 错误码 | 描述 |
|-------------|--------|------|
| 400 | `VALIDATION_ERROR` | 请求参数校验失败 |
| 401 | `UNAUTHORIZED` | 未认证或 token 过期 |
| 403 | `FORBIDDEN` | 权限不足 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 资源冲突（如重复创建） |
| 429 | `RATE_LIMITED` | 超过速率限制 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 |
| 503 | `SERVICE_UNAVAILABLE` | 服务暂不可用 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 响应 Envelope 一致性

**定义**：所有 API 响应必须包含 `success`, `data`, `error`, `meta` 四个顶层字段。

**验证方法**：
```python
def verify_response_envelope(response: dict) -> bool:
    required_keys = {'success', 'data', 'error', 'meta'}
    if not required_keys.issubset(response.keys()):
        return False
    if response['success']:
        assert response['error'] is None
    else:
        assert response['data'] is None
        assert response['error']['code'] is not None
    return True
```

**检查频率**：
- [x] 每次 API 响应（中间件自动校验）
- [ ] 每天

#### 不变量 2: 分页总数一致

**定义**：`meta.total` 必须等于满足过滤条件的实际记录数，`total_pages = ceil(total / per_page)`。

### 3.2 行为不变量

#### 幂等性

**定义**：`GET`, `PUT`, `DELETE` 操作必须是幂等的。

#### 速率限制一致性

**定义**：同一客户端在滑动窗口内的请求数不得超过限额。超限时返回 429 + `Retry-After` header。

### 3.3 性能不变量

#### P95 延迟 < 200ms

**定义**：简单 CRUD 操作 95% 请求延迟 < 200ms。

#### P99 延迟 < 1000ms

**定义**：复杂查询（含 JOIN）99% 请求延迟 < 1000ms。

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: 数据库连接池耗尽

**触发条件**：并发请求超过连接池上限

**影响**：严重性高，所有数据库操作阻塞

**检测方式**：连接等待时间 > 5s

**恢复策略**：返回 503 + `Retry-After: 5`，记录告警日志，自动扩容连接池（如配置允许）

### 4.2 失败模式 2: OpenAPI Schema 不一致

**触发条件**：代码变更未同步更新 OpenAPI spec

**检测方式**：CI 中运行 `openapi diff`

**恢复策略**：CI 阻断 + 提醒开发者更新 spec

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/unit/api/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/unit/api/ -v
```

**覆盖范围**：请求参数校验、响应 envelope 格式、错误码正确性、分页逻辑

### 5.2 集成测试

**位置**：`tests/integration/api/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/integration/api/ -v
```

**覆盖范围**：端到端 API 流程、认证/授权拦截、速率限制行为

### 5.3 Contract 测试

**位置**：`tests/contract/api/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/contract/api/ -v
```

**覆盖范围**：响应与 OpenAPI spec 一致、错误码与文档一致、分页参数边界值

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 请求延迟 P95 | 直方图 | < 200ms | > 500ms | Prometheus |
| 错误率 | 计数器 | < 1% | > 5% | Prometheus |
| 429 比率 | 计数器 | < 2% | > 10% | Prometheus |
| 活跃连接数 | 仪表 | < 100 | > 500 | Prometheus |

### 6.2 健康检查

**端点**：`/health`

**返回格式**：
```json
{
  "status": "healthy",
  "checks": { "database": "ok", "openapi_valid": "ok" },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| Contract 测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 响应 Envelope 一致性 | ❌ | - |
| 分页总数一致 | ❌ | - |
| 幂等性 | ❌ | - |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [OpenAPI 3.1 规范](https://spec.openapis.org/oas/v3.1.0)
- [后端 API 代码](../../backend/api/)
- [API 测试](../../tests/integration/api/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
