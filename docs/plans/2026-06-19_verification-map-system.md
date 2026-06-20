# 验证地图系统计划

## 背景与目标

### 背景
当前 Sage 项目的测试主要关注功能正确性，但缺乏对模块间关系、系统边界、行为约束的形式化验证。这导致：
- 模块边界不清晰，容易出现职责混乱
- 系统行为约束不明确，难以验证
- 重构时缺乏行为一致性保证
- 难以发现跨模块的集成问题

### 目标
借鉴 claw-code 的 `g002-g013` 验证地图编号系统，建立 Sage 的验证地图：
1. 为每个核心子系统分配唯一编号（g001-g0XX）
2. 定义每个子系统的验证契约（输入/输出/不变量）
3. 提供自动化验证脚本
4. 建立验证仪表板（可视化验证状态）

## 涉及的文件与模块

### 新增文件
- `docs/verification-maps/` - 验证地图根目录
  - `docs/verification-maps/README.md` - 验证地图总览
  - `docs/verification-maps/g001-memory-system.md`
  - `docs/verification-maps/g002-tool-execution.md`
  - `docs/verification-maps/g003-skill-lifecycle.md`
  - `docs/verification-maps/g004-agent-engine.md`
  - `docs/verification-maps/g005-conversation-flow.md`
  - `docs/verification-maps/g006-data-persistence.md`
  - `docs/verification-maps/g007-api-boundaries.md`
  - `docs/verification-maps/g008-frontend-state.md`
  - `docs/verification-maps/g009-security-boundaries.md`
  - `docs/verification-maps/g010-performance-slas.md`

- `scripts/verification/` - 验证脚本
  - `scripts/verification/run_all.sh` - 运行所有验证
  - `scripts/verification/generate_report.py` - 生成验证报告
  - `scripts/verification/check_invariants.py` - 检查不变量

### 关联模块
- 所有核心子系统（memory、tools、skills、agents、api 等）
- 测试框架（pytest）
- CI/CD 配置

## 技术方案

### 验证地图结构

```
验证地图 (g00X)
├── 1. 范围与职责
│   ├── 负责什么
│   └── 不负责什么
├── 2. 接口契约
│   ├── 输入断言
│   ├── 输出断言
│   └── 错误处理
├── 3. 不变量约束
│   ├── 数据不变量
│   ├── 行为不变量
│   └── 性能不变量
├── 4. 失败模式
│   ├── 可预见的失败
│   ├── 恢复策略
│   └── 降级方案
├── 5. 验证方法
│   ├── 单元测试
│   ├── 集成测试
│   ├── 属性测试
│   └── 性能测试
└── 6. 监控指标
    ├── 运行时指标
    ├── 健康检查
    └── 告警阈值
```

### 验证地图模板

```markdown
# g00X: [子系统名称] 验证地图

**状态**: 🟢 已验证 / 🟡 部分验证 / 🔴 未验证  
**维护者**: @team-member  
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责
- 职责 1
- 职责 2

### 不负责
- 非职责 1（由 g00Y 负责）

---

## 2. 接口契约

### 输入断言
| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `param1` | `str` | 非空，长度 < 1000 | `assert param1 and len(param1) < 1000` |
| `param2` | `int` | > 0 | `assert param2 > 0` |

### 输出断言
| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `result` | `dict` | 包含 `id`, `status` | `assert 'id' in result and 'status' in result` |

### 错误处理
| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|
| 参数非法 | `ValueError` | 返回 400 + 错误信息 |
| 资源不存在 | `NotFoundError` | 返回 404 |

---

## 3. 不变量约束

### 数据不变量
- [ ] **不变量 1**: [描述]
  - 验证方法: `test_invariant_1()`
  - 检查频率: 每次写操作后

- [ ] **不变量 2**: [描述]
  - 验证方法: `test_invariant_2()`
  - 检查频率: 每小时

### 行为不变量
- [ ] **幂等性**: 相同输入产生相同输出
  - 验证方法: `test_idempotency()`
  
- [ ] **顺序无关性**: 操作顺序不影响结果
  - 验证方法: `test_order_independence()`

### 性能不变量
- [ ] **延迟 P95 < 200ms**
  - 验证方法: `test_latency_p95()`
  - 监控指标: `http_request_duration_seconds`

---

## 4. 失败模式

### 失败模式 1: [描述]
- **触发条件**: [...]
- **影响**: [高/中/低]
- **恢复策略**: [...]
- **降级方案**: [...]
- **验证测试**: `test_failure_mode_1()`

### 失败模式 2: [描述]
...

---

## 5. 验证方法

### 单元测试
```bash
pytest tests/verification/g00X/ -v
```

### 集成测试
```bash
pytest tests/integration/g00X/ -v
```

### 属性测试（如适用）
```bash
pytest tests/property/g00X/ -v
```

### 性能测试
```bash
pytest tests/performance/g00X/ -v
```

---

## 6. 监控指标

| 指标 | 目标值 | 告警阈值 | 监控方式 |
|------|--------|----------|----------|
| 请求延迟 P95 | < 200ms | > 500ms | Prometheus |
| 错误率 | < 1% | > 5% | Prometheus |
| 吞吐量 | > 100 req/s | < 50 req/s | Prometheus |

---

## 7. 验证状态

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🟢 | 95% | 2026-06-19 |
| 集成测试 | 🟢 | 80% | 2026-06-19 |
| 性能测试 | 🟡 | 60% | 2026-06-18 |
```

### 验证自动化

#### 验证运行器
```python
#!/usr/bin/env python3
# scripts/verification/run_all.py

import sys
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List

@dataclass
class VerificationResult:
    map_id: str
    name: str
    passed: bool
    coverage: float
    duration: float

def run_verification(map_path: Path) -> VerificationResult:
    """运行单个验证地图的测试"""
    map_id = map_path.stem.split('-')[0]  # g001
    name = map_path.stem.split('-', 1)[1]  # memory-system
    
    # 运行测试
    result = subprocess.run(
        ["pytest", f"tests/verification/{map_id}/", "-v", "--cov"],
        capture_output=True,
        text=True
    )
    
    # 解析结果
    passed = result.returncode == 0
    coverage = parse_coverage(result.stdout)
    duration = parse_duration(result.stdout)
    
    return VerificationResult(map_id, name, passed, coverage, duration)

def main():
    """运行所有验证"""
    maps_dir = Path("docs/verification-maps")
    results = []
    
    for map_path in sorted(maps_dir.glob("g*.md")):
        result = run_verification(map_path)
        results.append(result)
        print(f"{result.map_id}: {'✅' if result.passed else '❌'} ({result.coverage:.1f}%)")
    
    # 生成报告
    generate_report(results)
    
    # 返回退出码
    sys.exit(0 if all(r.passed for r in results) else 1)

if __name__ == "__main__":
    main()
```

#### 验证报告生成器
```python
#!/usr/bin/env python3
# scripts/verification/generate_report.py

from datetime import datetime
from typing import List
from jinja2 import Template

REPORT_TEMPLATE = """
# 验证报告

**生成时间**: {{ timestamp }}

## 总览

| 验证地图 | 状态 | 覆盖率 | 耗时 |
|----------|------|--------|------|
{% for result in results %}
| {{ result.map_id }}: {{ result.name }} | {{ '✅' if result.passed else '❌' }} | {{ result.coverage }}% | {{ result.duration }}s |
{% endfor %}

## 统计

- **总验证数**: {{ results | length }}
- **通过数**: {{ results | selectattr('passed') | list | length }}
- **失败数**: {{ results | rejectattr('passed') | list | length }}
- **平均覆盖率**: {{ average_coverage }}%

## 失败详情

{% for result in results if not result.passed %}
### {{ result.map_id }}: {{ result.name }}
- 覆盖率: {{ result.coverage }}%
- 耗时: {{ result.duration }}s
- 查看日志: `logs/{{ result.map_id }}.log`
{% endfor %}
"""

def generate_report(results: List[dict]):
    """生成验证报告"""
    template = Template(REPORT_TEMPLATE)
    
    report = template.render(
        timestamp=datetime.utcnow().isoformat(),
        results=results,
        average_coverage=sum(r['coverage'] for r in results) / len(results)
    )
    
    # 写入文件
    with open("docs/verification-report.md", "w") as f:
        f.write(report)
    
    print("✅ 验证报告已生成: docs/verification-report.md")
```

### CI/CD 集成

```yaml
# .github/workflows/verification.yml
name: Verification Maps

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 0 * * *'  # 每天运行

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Run verification
        run: |
          python scripts/verification/run_all.py
      
      - name: Generate report
        if: always()
        run: |
          python scripts/verification/generate_report.py
      
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: verification-report
          path: docs/verification-report.md
      
      - name: Check coverage threshold
        run: |
          COVERAGE=$(grep "average_coverage" docs/verification-report.md | awk '{print $2}')
          if (( $(echo "$COVERAGE < 80" | bc -l) )); then
            echo "❌ 覆盖率低于 80%: ${COVERAGE}%"
            exit 1
          fi
```

## 实施步骤

### 阶段 1：框架建立（1 周）
- [ ] 1.1 创建 `docs/verification-maps/` 目录
- [ ] 1.2 编写 `README.md` 验证地图总览
- [ ] 1.3 定义验证地图模板
- [ ] 1.4 实现验证运行器框架
- [ ] 1.5 实现报告生成器

### 阶段 2：核心子系统验证地图（2 周）
- [ ] 2.1 编写 g001-memory-system.md
- [ ] 2.2 编写 g002-tool-execution.md
- [ ] 2.3 编写 g003-skill-lifecycle.md
- [ ] 2.4 编写 g004-agent-engine.md
- [ ] 2.5 编写 g005-conversation-flow.md
- [ ] 2.6 为每个地图编写验证测试

### 阶段 3：外围子系统验证地图（1.5 周）
- [ ] 3.1 编写 g006-data-persistence.md
- [ ] 3.2 编写 g007-api-boundaries.md
- [ ] 3.3 编写 g008-frontend-state.md
- [ ] 3.4 编写 g009-security-boundaries.md
- [ ] 3.5 编写 g010-performance-slas.md

### 阶段 4：自动化与集成（1.5 周）
- [ ] 4.1 配置 CI/CD 集成
- [ ] 4.2 实现验证仪表板（可选）
- [ ] 4.3 添加 Slack/邮件通知
- [ ] 4.4 编写使用文档
- [ ] 4.5 团队培训

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 验证地图维护成本高 | 中 | 自动化生成，复用现有测试 |
| 验证脚本复杂度高 | 中 | 提供模板，简化编写 |
| 团队抵触 | 低 | 展示长期收益，渐进式推广 |
| CI/CD 时间过长 | 中 | 并行运行，优化测试 |

### 依赖
- pytest（测试框架）
- pytest-cov（覆盖率）
- Jinja2（报告模板）
- CI/CD 平台（GitHub Actions）

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| 框架建立 | 1 周 |
| 核心子系统 | 2 周 |
| 外围子系统 | 1.5 周 |
| 自动化与集成 | 1.5 周 |
| **总计** | **6 周** |

## 验证标准

1. **完整性**：所有核心子系统都有验证地图
2. **可执行性**：所有验证都能自动化运行
3. **可维护性**：验证地图与代码同步更新
4. **可视化**：验证状态清晰可见

## 示例：g001-memory-system.md 片段

```markdown
# g001: 记忆系统验证地图

**状态**: 🟢 已验证  
**维护者**: @backend-team  
**最后更新**: 2026-06-19

---

## 2. 接口契约

### 输入断言
| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `content` | `str` | 非空，长度 < 10000 | `assert content and len(content) < 10000` |
| `memory_type` | `str` | 必须是 "episodic"/"semantic"/"procedural" | `assert memory_type in VALID_TYPES` |

### 输出断言
| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `memory_id` | `str` | UUID 格式 | `assert is_valid_uuid(memory_id)` |

## 3. 不变量约束

### 数据不变量
- [x] **记忆 ID 全局唯一**
  - 验证方法: `test_memory_id_uniqueness()`
  - 检查频率: 每次写操作后

- [x] **向量维度一致（384 维）**
  - 验证方法: `test_vector_dimension_consistency()`
  - 检查频率: 每次嵌入后

### 行为不变量
- [x] **存储操作幂等**
  - 验证方法: `test_store_idempotency()`
```

## 长期收益

1. **质量保证**：持续验证系统健康度
2. **重构信心**：验证地图保证重构不破坏行为
3. **文档即代码**：契约定义可执行、可验证
4. **团队协作**：明确模块边界与责任
5. **新人上手**：快速理解系统架构与约束
