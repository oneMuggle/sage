# 验证映射系统 (Verification Maps)

> Sage 核心子系统的形式化契约定义，保证系统行为一致性和可验证性。

---

## 什么是验证映射？

验证映射（Verification Maps）是为每个核心子系统定义的**形式化契约**，明确：
- **范围与职责**：该子系统负责什么，不负责什么
- **输入/输出断言**：所有接口的前置和后置条件
- **不变量约束**：系统必须始终满足的条件
- **失败模式**：可能的失败场景及恢复策略
- **验证方法**：如何自动化验证这些约束

---

## 验证地图总览

| 编号 | 子系统 | 状态 | 维护者 | 最后更新 |
|------|--------|------|--------|----------|
| [g001](./g001-memory-system.md) | 记忆系统 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g002](./g002-tool-execution.md) | 工具执行 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g003](./g003-skill-lifecycle.md) | 技能生命周期 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g004](./g004-agent-orchestration.md) | Agent 编排 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g005](./g005-frontend-state.md) | 前端状态 | 🔴 未验证 | @frontend-team | 2026-06-19 |
| [g006](./g006-api-contracts.md) | API 契约 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g007](./g007-data-persistence.md) | 数据持久化 | 🔴 未验证 | @backend-team | 2026-06-19 |
| [g008](./g008-security-boundaries.md) | 安全边界 | 🔴 未验证 | @security-team | 2026-06-19 |
| [g009](./g009-performance-slas.md) | 性能 SLA | 🔴 未验证 | @ops-team | 2026-06-19 |

**状态说明**：
- 🟢 已验证 - 所有验证测试通过
- 🟡 部分验证 - 部分验证测试通过
- 🔴 未验证 - 尚未编写验证测试

---

## 验证映射结构

每个验证映射文档遵循统一结构：

```markdown
# g00X: [子系统名称] 验证映射

**状态**: 🟢 / 🟡 / 🔴
**维护者**: @team-member
**最后更新**: YYYY-MM-DD

## 1. 范围与职责
[该子系统负责什么，不负责什么]

## 2. 接口契约

### 输入断言
| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|

### 输出断言
| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|

### 错误处理
| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|

## 3. 不变量约束

### 数据不变量
- [ ] 不变量 1
- [ ] 不变量 2

### 行为不变量
- [ ] 幂等性
- [ ] 顺序无关性

### 性能不变量
- [ ] 延迟 P95 < Xms

## 4. 失败模式与恢复

### 失败模式 1
- 触发条件: [...]
- 影响: [高/中/低]
- 恢复策略: [...]
- 验证测试: `test_failure_mode_1()`

## 5. 验证方法

### 单元测试
pytest tests/verification/g00X/ -v

### 集成测试
pytest tests/integration/g00X/ -v

## 6. 监控指标
| 指标 | 目标值 | 告警阈值 |
|------|--------|----------|
```

---

## 验证自动化

### 运行所有验证

```bash
# 运行所有验证映射的测试
python scripts/verification/run_all.py

# 运行特定子系统的验证
python scripts/verification/run_all.py g001

# 生成验证报告
python scripts/verification/generate_report.py
```

### CI/CD 集成

验证测试已集成到 CI/CD 流程：

```yaml
# .github/workflows/verification.yml
name: Verification Maps

on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run verification
        run: python scripts/verification/run_all.py
      - name: Generate report
        if: always()
        run: python scripts/verification/generate_report.py
```

---

## 验证状态仪表板

运行验证后会生成报告：

```bash
# 生成 Markdown 报告
python scripts/verification/generate_report.py --format markdown

# 生成 JSON 报告
python scripts/verification/generate_report.py --format json

# 生成 HTML 报告
python scripts/verification/generate_report.py --format html
```

报告示例：

```markdown
# 验证报告

**生成时间**: 2026-06-19 12:00:00 UTC

## 总览

| 验证地图 | 状态 | 覆盖率 | 耗时 |
|----------|------|--------|------|
| g001: 记忆系统 | ✅ | 95% | 2.3s |
| g002: 工具执行 | ✅ | 92% | 1.8s |
| g003: 技能生命周期 | ⚠️ | 78% | 1.5s |
| g004: Agent 编排 | ❌ | 65% | 2.1s |

## 统计
- 总验证数: 9
- 通过数: 2
- 失败数: 1
- 警告数: 1
- 平均覆盖率: 82.5%
```

---

## 如何添加新的验证映射

### 1. 创建映射文档

```bash
# 复制模板
cp docs/verification/TEMPLATE.md docs/verification/g0XX-subsystem-name.md

# 编辑文档
vim docs/verification/g0XX-subsystem-name.md
```

### 2. 编写验证测试

```python
# tests/verification/g0XX/test_subsystem.py
import pytest

class TestSubsystemInvariants:
    """测试子系统不变量"""
    
    @pytest.mark.verification("g0XX")
    async def test_invariant_1(self):
        """测试不变量 1"""
        # Arrange
        # Act
        # Assert
        pass
```

### 3. 更新总览

在 `docs/verification/README.md` 中添加新的映射条目。

### 4. 运行验证

```bash
python scripts/verification/run_all.py g0XX
```

---

## 验证最佳实践

### 1. 从小开始

不要试图一次验证所有东西。从最关键的不变量开始，逐步扩展。

### 2. 自动化优先

所有验证测试都应该能自动化运行。手动验证不可接受。

### 3. 持续验证

验证不是一次性的。每次代码变更后都应该重新运行验证。

### 4. 保持同步

代码变更时，验证映射必须同步更新。过时的映射比没有映射更糟。

### 5. 明确责任

每个验证映射都有明确的维护者。维护者负责：
- 编写和更新验证测试
- 确保验证测试通过
- 响应验证失败

---

## 故障排查

### 验证测试失败

1. **查看失败详情**：
   ```bash
   pytest tests/verification/g001/ -v --tb=short
   ```

2. **检查不变量**：
   确认代码是否违反了某个不变量约束

3. **更新映射**：
   如果需求变更导致不变量失效，更新验证映射文档

4. **修复代码**：
   如果代码 bug 导致验证失败，修复代码

### 验证覆盖率低

1. **识别缺失的不变量**：
   审查代码，找出未覆盖的关键约束

2. **添加验证测试**：
   为每个缺失的不变量编写测试

3. **运行验证**：
   确认覆盖率提升

---

## 进一步阅读

- [g001: 记忆系统](./g001-memory-system.md)
- [g002: 工具执行](./g002-tool-execution.md)
- [g003: 技能生命周期](./g003-skill-lifecycle.md)
- [g004: Agent 编排](./g004-agent-orchestration.md)
- [验证映射模板](./TEMPLATE.md)

---

**创建时间**：2026-06-19  
**维护者**：Sage 团队  
**最后更新**：2026-06-19
