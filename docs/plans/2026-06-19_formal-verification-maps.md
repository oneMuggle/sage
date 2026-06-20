# 形式化验证映射计划

## 背景与目标

### 背景
当前 Sage 项目的测试覆盖主要集中在单元测试和集成测试层面，缺乏对核心子系统行为的形式化约束定义。这导致：
- 模块间契约不清晰，容易出现集成问题
- 难以验证系统是否满足设计约束
- 重构时缺乏行为一致性保证
- 新开发者难以理解模块边界与不变量

### 目标
借鉴 claw-code 的 `docs/g002-g013` 验证映射系统，为 Sage 核心子系统建立形式化契约：
1. 明确每个子系统的输入/输出断言
2. 定义不变量约束（系统必须始终满足的条件）
3. 规定验证脚本路径（如何自动化验证）
4. 列出失败模式与恢复策略

## 涉及的文件与模块

### 新增文件
- `docs/verification/` - 验证映射根目录
  - `docs/verification/README.md` - 验证地图总览
  - `docs/verification/g001-memory-system.md` - 记忆系统契约
  - `docs/verification/g002-tool-execution.md` - 工具执行契约
  - `docs/verification/g003-skill-lifecycle.md` - 技能生命周期契约
  - `docs/verification/g004-agent-orchestration.md` - Agent 编排契约
  - `docs/verification/g005-frontend-state.md` - 前端状态契约
  - `docs/verification/g006-api-contracts.md` - API 契约
  - `docs/verification/g007-data-persistence.md` - 数据持久化契约
  - `docs/verification/g008-security-boundaries.md` - 安全边界契约
  - `docs/verification/g009-performance-slas.md` - 性能 SLA 契约

### 关联模块
- `backend/memory/` - 记忆系统
- `backend/tools/` - 工具系统
- `backend/skills/` - 技能系统
- `backend/agents/` - Agent 系统
- `src/` - 前端状态管理
- `backend/api/` - API 层
- `backend/database/` - 数据持久化

## 技术方案

### 验证映射结构

每个验证映射文档遵循统一结构：

```markdown
# g00X: [子系统名称] 验证映射

## 1. 范围与职责
[该子系统负责什么，不负责什么]

## 2. 输入/输出断言

### 输入断言
- [ ] 所有输入必须经过验证
- [ ] 输入格式必须符合 schema
- [ ] 非法输入必须返回明确错误

### 输出断言
- [ ] 输出必须包含必要字段
- [ ] 输出格式必须一致
- [ ] 错误输出必须包含错误码

## 3. 不变量约束
[系统必须始终满足的条件]

### 数据不变量
- [ ] 数据一致性约束
- [ ] 状态转换约束

### 行为不变量
- [ ] 幂等性约束
- [ ] 顺序约束
- [ ] 并发约束

## 4. 失败模式与恢复

### 失败模式 1: [描述]
- 触发条件: [...]
- 影响: [...]
- 恢复策略: [...]
- 验证方法: [...]

### 失败模式 2: [描述]
...

## 5. 验证脚本
[如何自动化验证这些约束]

### 单元测试
- `tests/test_[module].py::test_[constraint]`

### 集成测试
- `tests/integration/test_[module].py`

### 属性测试（如适用）
- `tests/property/test_[module].py`

## 6. 监控指标
[用于运行时验证的指标]

- 指标 1: [名称] - [目标值]
- 指标 2: [名称] - [目标值]
```

### 验证自动化

#### 验证脚本框架
```python
# tests/verification/runner.py
class VerificationRunner:
    def __init__(self, mapping_path: str):
        self.mapping = self._load_mapping(mapping_path)
    
    def run_all_verifications(self) -> VerificationResult:
        """运行所有验证检查"""
        results = []
        for check in self.mapping.checks:
            result = self._run_check(check)
            results.append(result)
        return VerificationResult(results)
    
    def _run_check(self, check: VerificationCheck) -> CheckResult:
        """运行单个验证检查"""
        try:
            # 运行测试
            # 检查不变量
            # 验证性能指标
            return CheckResult(passed=True, details="...")
        except Exception as e:
            return CheckResult(passed=False, error=str(e))
```

#### CI/CD 集成
```yaml
# .github/workflows/verification.yml
name: Verification Checks

on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run verification checks
        run: |
          python -m pytest tests/verification/ -v
      - name: Generate verification report
        run: |
          python scripts/generate_verification_report.py
```

## 实施步骤

### 阶段 1：框架建立（1 周）
- [ ] 1.1 创建 `docs/verification/` 目录结构
- [ ] 1.2 编写 `README.md` 验证地图总览
- [ ] 1.3 定义验证映射模板
- [ ] 1.4 实现 `VerificationRunner` 框架
- [ ] 1.5 配置 CI/CD 集成

### 阶段 2：核心子系统契约（2 周）
- [ ] 2.1 编写 g001-memory-system.md
- [ ] 2.2 编写 g002-tool-execution.md
- [ ] 2.3 编写 g003-skill-lifecycle.md
- [ ] 2.4 编写 g004-agent-orchestration.md
- [ ] 2.5 为每个契约编写验证测试

### 阶段 3：外围子系统契约（1.5 周）
- [ ] 3.1 编写 g005-frontend-state.md
- [ ] 3.2 编写 g006-api-contracts.md
- [ ] 3.3 编写 g007-data-persistence.md
- [ ] 3.4 编写 g008-security-boundaries.md
- [ ] 3.5 编写 g009-performance-slas.md

### 阶段 4：自动化与监控（1.5 周）
- [ ] 4.1 实现验证报告生成器
- [ ] 4.2 添加运行时监控指标
- [ ] 4.3 实现不变量自动检查
- [ ] 4.4 编写验证仪表板（可选）
- [ ] 4.5 编写使用文档

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 契约定义不准确 | 高 | 与团队评审，迭代优化 |
| 验证测试维护成本高 | 中 | 自动化生成，复用现有测试 |
| 性能指标难以量化 | 中 | 基准测试，历史数据分析 |
| 开发者抵触 | 低 | 培训，展示长期收益 |

### 依赖
- pytest（测试框架）
- hypothesis（属性测试，可选）
- prometheus_client（监控指标，可选）

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| 框架建立 | 1 周 |
| 核心子系统 | 2 周 |
| 外围子系统 | 1.5 周 |
| 自动化与监控 | 1.5 周 |
| **总计** | **6 周** |

## 验证标准

1. **完整性**：所有核心子系统都有验证映射
2. **可执行性**：所有验证检查都能自动化运行
3. **可维护性**：验证测试与代码同步更新
4. **可追溯性**：每个契约都能追溯到具体代码

## 示例：g001-memory-system.md 片段

```markdown
# g001: 记忆系统验证映射

## 2. 输入/输出断言

### 输入断言
- [x] 记忆存储请求必须包含 `content` 字段
- [x] 记忆查询必须包含 `query` 字段
- [x] 非法输入必须返回 400 错误

### 输出断言
- [x] 检索结果必须包含 `id`, `content`, `score` 字段
- [x] 结果必须按相关性降序排列
- [x] 空结果必须返回空列表（非 null）

## 3. 不变量约束

### 数据不变量
- [x] 记忆 ID 全局唯一
- [x] 记忆内容不可变（只能删除重建）
- [x] 向量维度必须一致（384 维）

### 行为不变量
- [x] 存储操作是幂等的
- [x] 并发检索不会互相阻塞
- [x] 删除后立即不可见

## 4. 失败模式与恢复

### 失败模式 1: 向量数据库不可用
- 触发条件: ChromaDB 进程崩溃
- 影响: 无法检索记忆
- 恢复策略: 降级到本地 SQLite 缓存
- 验证方法: `test_memory_fallback_on_vectordb_failure`

### 失败模式 2: 嵌入模型加载失败
- 触发条件: 模型文件损坏
- 影响: 无法生成向量
- 恢复策略: 使用预计算向量（缓存）
- 验证方法: `test_memory_embedding_model_failure`
```

## 长期收益

1. **重构信心**：验证映射保证重构不破坏行为
2. **文档即代码**：契约定义可执行、可验证
3. **新人上手**：快速理解系统边界与约束
4. **质量保证**：持续验证系统健康度
