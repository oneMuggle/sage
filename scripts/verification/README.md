# 验证映射自动化脚本

本目录包含 Sage 验证映射系统的自动化脚本。

## 脚本列表

### `run_all.py` - 验证运行器

运行所有验证映射的测试。

**用法**：

```bash
# 运行所有验证
python scripts/verification/run_all.py

# 运行特定子系统的验证
python scripts/verification/run_all.py g001

# 详细输出
python scripts/verification/run_all.py --verbose

# JSON 格式输出
python scripts/verification/run_all.py --json
```

**输出示例**：

```
🔍 发现 9 个验证映射

▶ 运行 g001-memory-system... ✅ (2.3s, 覆盖率 95.0%)
▶ 运行 g002-tool-execution... ✅ (1.8s, 覆盖率 92.0%)
▶ 运行 g003-skill-lifecycle... ❌ (1.5s, 覆盖率 78.0%)
...

============================================================
验证统计
============================================================
总验证数: 9
通过数: 7
失败数: 2
平均覆盖率: 85.5%
============================================================
```

---

### `generate_report.py` - 报告生成器

生成验证状态的 Markdown/JSON/HTML 报告。

**用法**：

```bash
# 生成 Markdown 报告（默认）
python scripts/verification/generate_report.py

# 生成 JSON 报告
python scripts/verification/generate_report.py --format json

# 生成 HTML 报告
python scripts/verification/generate_report.py --format html

# 指定输出文件
python scripts/verification/generate_report.py --output docs/verification-report.md
```

**输出示例**（Markdown）：

```markdown
# 验证报告

**生成时间**: 2026-06-19 12:00:00 UTC

## 总览

| 指标 | 数值 |
|------|------|
| 总验证数 | 9 |
| ✅ 通过 | 7 |
| ❌ 失败 | 2 |
| 平均覆盖率 | 85.5% |

## 详细结果

| 验证地图 | 状态 | 维护者 | 覆盖率 | 测试数 | 最后更新 |
|----------|------|--------|--------|--------|----------|
| g001: Memory System | ✅ | @backend-team | 95.0% | 45 | 2026-06-19 |
...
```

---

## CI/CD 集成

### GitHub Actions 示例

```yaml
name: Verification Maps

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

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
          cd backend
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Run verification
        run: python scripts/verification/run_all.py
      
      - name: Generate report
        if: always()
        run: |
          python scripts/verification/generate_report.py \
            --format markdown \
            --output docs/verification-report.md
      
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: verification-report
          path: docs/verification-report.md
      
      - name: Check coverage threshold
        run: |
          # 从报告中提取覆盖率
          COVERAGE=$(grep "平均覆盖率" docs/verification-report.md | grep -o '[0-9.]*%')
          echo "平均覆盖率: $COVERAGE"
          
          # 检查是否低于阈值（例如 80%）
          THRESHOLD=80
          if (( $(echo "${COVERAGE%\%} < $THRESHOLD" | bc -l) )); then
            echo "❌ 覆盖率低于 $THRESHOLD%: $COVERAGE"
            exit 1
          fi
```

---

## 开发新脚本

### 脚本结构

```python
#!/usr/bin/env python3
"""脚本说明"""

import sys
from pathlib import Path

def main():
    # 主逻辑
    pass

if __name__ == "__main__":
    main()
```

### 最佳实践

1. **使用 type hints**：提高代码可读性
2. **提供详细帮助**：使用 `argparse` 提供命令行帮助
3. **错误处理**：捕获异常并提供清晰的错误信息
4. **日志输出**：使用 `print` 输出到 stderr，结果输出到 stdout
5. **退出码**：成功返回 0，失败返回非 0

---

## 故障排查

### 脚本无法运行

```bash
# 检查 Python 版本
python --version  # 应该 >= 3.8

# 检查依赖
pip list | grep pytest

# 检查脚本权限
chmod +x scripts/verification/*.py
```

### 测试未找到

```bash
# 检查测试目录结构
ls -la tests/verification/

# 检查测试文件命名
ls tests/verification/g001/  # 应该是 test_*.py
```

### 覆盖率报告缺失

```bash
# 安装 pytest-cov
pip install pytest-cov

# 检查 coverage 配置
cat .coveragerc  # 或 pyproject.toml 中的 [tool.coverage]
```

---

## 进一步阅读

- [验证映射总览](../../docs/verification/README.md)
- [验证映射模板](../../docs/verification/TEMPLATE.md)
- [pytest 文档](https://docs.pytest.org/)
- [pytest-cov 文档](https://pytest-cov.readthedocs.io/)
