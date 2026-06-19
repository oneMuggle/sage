# g008: Security Boundaries 验证映射

> 安全边界契约：认证、授权、输入校验、密钥管理。参考 OWASP Top 10。

---

**状态**: 🔴 未验证
**维护者**: @security-team
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- 用户认证（登录、session 管理、token 签发/验证）
- 授权与权限控制（RBAC）
- 输入校验与净化（防注入、XSS）
- 密钥与敏感数据管理
- 安全审计日志

### 不负责

- 网络层安全（TLS 终止由部署配置负责）
- 操作系统级安全（由运行环境负责）
- 前端 UI 安全提示展示（由 g005 负责）

### 依赖

- 依赖 g006：API 层调用认证/授权中间件
- 依赖 g007：安全存储用户数据与密钥

---

## 2. 接口契约

### 2.1 认证接口

| 端点 | 方法 | 描述 | 输入 | 输出 |
|------|------|------|------|------|
| `/auth/login` | POST | 用户登录 | `{ email, password }` | `{ token, expires_at }` |
| `/auth/logout` | POST | 注销 | `Authorization` header | `{ success: true }` |
| `/auth/refresh` | POST | 刷新 token | `{ refresh_token }` | `{ token, expires_at }` |
| `/auth/me` | GET | 当前用户信息 | `Authorization` header | `{ user }` |

### 2.2 认证方式

| 方式 | 使用场景 | Token 格式 | 有效期 |
|------|----------|------------|--------|
| Bearer Token | API 请求 | JWT (RS256) | 15 分钟 |
| Refresh Token | Token 刷新 | Opaque (UUID) | 7 天 |
| IPC Auth | Tauri 内部通信 | Shared secret (env) | 应用生命周期 |

### 2.3 权限模型

| 角色 | 权限 | 描述 |
|------|------|------|
| `admin` | 全部 | 系统管理 |
| `user` | 读写自己的数据 | 普通用户 |
| `readonly` | 只读 | 访客 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 无硬编码密钥

**定义**：源代码中不得出现任何硬编码的 API key、密码、token 或私钥。

**验证方法**：
```bash
gitleaks detect --source . --verbose
```

**检查频率**：
- [x] 每次 commit（pre-commit hook）
- [x] 每次 PR（CI 扫描）
- [ ] 每周全量扫描

#### 不变量 2: 所有外部输入必须校验

**定义**：所有来自用户/外部的输入必须经过类型检查、长度限制、格式验证后才会被处理。

**验证方法**：
```python
def verify_input_validation(endpoint: str, payload: dict) -> bool:
    invalid_payloads = [
        {},
        {"field": "A" * 10000},
        {"field": "<script>alert(1)</script>"},
        {"field": "'; DROP TABLE users; --"},
    ]
    for invalid in invalid_payloads:
        response = requests.post(endpoint, json=invalid)
        if response.status_code not in [400, 422]:
            return False
    return True
```

**检查频率**：
- [x] 每次 API 请求（中间件自动校验）
- [ ] 每周 fuzz 测试

#### 不变量 3: 权限检查覆盖

**定义**：每个需要认证的 API 端点都必须有权限检查中间件。不允许绕过。

### 3.2 行为不变量

#### 密码安全存储

**定义**：密码必须使用 bcrypt/argon2 哈希存储，永远不明文存储或可逆加密。

#### Session 固定防护

**定义**：登录成功后必须生成新的 session ID，不能复用登录前的 session。

#### 暴力破解防护

**定义**：同一 IP/账户连续 5 次登录失败后，锁定 15 分钟。

### 3.3 性能不变量

#### 认证延迟 P95 < 100ms

**定义**：Token 验证（不含密码哈希）95% 延迟 < 100ms。

#### 密码哈希时间

**定义**：bcrypt 哈希耗时 200-500ms（cost factor 12）。

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: Token 泄露

**触发条件**：XSS 攻击窃取 token、日志中意外记录 token、网络中间人攻击

**影响**：严重性致命，攻击者可冒充用户

**检测方式**：异常地理位置登录、同时多处活跃 session

**恢复策略**：
1. 立即吊销所有受影响用户的 token
2. 强制用户重新登录
3. 审查审计日志确认影响范围
4. 修补泄露途径

### 4.2 失败模式 2: 密钥泄露到代码仓库

**触发条件**：开发者意外提交密钥

**检测方式**：pre-commit hook + CI gitleaks 扫描

**恢复策略**：立即轮换泄露的密钥，从 git 历史中清除，审查密钥使用记录，添加 pre-commit hook 防止再次发生

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/unit/security/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/unit/security/ -v
```

**覆盖范围**：Token 签发/验证、权限检查逻辑、输入校验规则、密码哈希

### 5.2 集成测试

**位置**：`tests/integration/security/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/integration/security/ -v
```

**覆盖范围**：认证流程（登录 → 访问 → 刷新 → 注销）、未认证访问拒绝、权限不足拒绝、暴力破解锁定

### 5.3 安全扫描

| 工具 | 用途 | 频率 |
|------|------|------|
| `gitleaks` | 密钥泄露检测 | 每次 commit |
| `bandit` | Python 安全静态分析 | 每次 PR |
| `npm audit` | Node.js 依赖漏洞 | 每次 PR |
| `OWASP ZAP` | DAST 动态扫描 | 每月 |

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 登录失败率 | 百分比 | < 5% | > 20% | Prometheus |
| 无效 Token 请求 | 计数器 | < 10/min | > 100/min | Prometheus |
| 暴力破解尝试 | 计数器 | 0 | > 5/hour | Prometheus |
| 密钥泄露事件 | 计数器 | 0 | > 0 | CI 扫描 |

### 6.2 审计日志

**格式**：
```json
{
  "timestamp": "2026-06-19T12:00:00Z",
  "event": "login_failed",
  "user_id": null,
  "ip": "192.168.1.1",
  "reason": "invalid_password",
  "attempt_count": 3
}
```

**关键事件**：登录成功/失败、权限变更、敏感操作、密钥轮换。

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 安全扫描 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 无硬编码密钥 | ❌ | - |
| 输入校验覆盖 | ❌ | - |
| 权限检查覆盖 | ❌ | - |

### 7.3 OWASP Top 10 覆盖

| OWASP 风险 | 状态 | 缓解措施 |
|------------|------|----------|
| A01: Broken Access Control | ❌ | RBAC + 中间件 |
| A02: Cryptographic Failures | ❌ | bcrypt + TLS |
| A03: Injection | ❌ | 参数化查询 + 输入校验 |
| A07: Identification Failures | ❌ | 暴力破解防护 |
| A08: Software Integrity | ❌ | 依赖扫描 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @security-team |

---

## 9. 参考

- [OWASP Top 10 (2021)](https://owasp.org/Top10/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [安全代码](../../backend/security/)
- [安全测试](../../tests/unit/security/)
- [JWT.io](https://jwt.io/)
