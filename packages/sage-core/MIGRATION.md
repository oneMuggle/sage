# 迁移指南

本文档说明如何将 Sage 后端从 `backend.domain` 和 `backend.ports` 迁移到 `sage-core` 包。

---

## 迁移步骤

### 1. 安装 sage-core

```bash
cd /home/fz/project/sage
pip install -e packages/sage-core/
```

### 2. 更新导入路径

**旧代码**：
```python
from backend.domain.agent import AgentState, AgentDecision
from backend.domain.message import Message, Role
from backend.ports.storage import StoragePort
```

**新代码**：
```python
from sage_core import AgentState, AgentDecision
from sage_core import Message, Role
from sage_core.repositories import StoragePort
```

### 3. 批量替换脚本

```bash
# 替换 domain 导入
find backend -name "*.py" -exec sed -i 's/from backend\.domain\./from sage_core./g' {} +

# 替换 ports 导入
find backend -name "*.py" -exec sed -i 's/from backend\.ports\./from sage_core.repositories./g' {} +
```

### 4. 更新依赖

在 `backend/requirements.txt` 中添加：

```
-e ../packages/sage-core
```

### 5. 验证

```bash
# 运行测试
cd backend
pytest

# 类型检查
mypy backend
```

---

## 迁移映射表

| 旧路径 | 新路径 |
|--------|--------|
| `backend.domain.agent.AgentState` | `sage_core.AgentState` |
| `backend.domain.agent.AgentDecision` | `sage_core.AgentDecision` |
| `backend.domain.message.Message` | `sage_core.Message` |
| `backend.domain.message.Role` | `sage_core.Role` |
| `backend.domain.message.ToolCall` | `sage_core.ToolCall` |
| `backend.domain.skill.SkillSpec` | `sage_core.SkillSpec` |
| `backend.domain.skill.SkillResult` | `sage_core.SkillResult` |
| `backend.domain.tool.ToolSpec` | `sage_core.ToolSpec` |
| `backend.domain.tool.ToolResult` | `sage_core.ToolResult` |
| `backend.domain.compute.*` | `sage_core.entities.compute.*` |
| `backend.domain.errors.*` | `sage_core.entities.errors.*` |
| `backend.domain.exceptions.*` | `sage_core.exceptions.*` |
| `backend.ports.storage.StoragePort` | `sage_core.repositories.StoragePort` |
| `backend.ports.llm.LLMPort` | `sage_core.repositories.LLMPort` |
| `backend.ports.tool.ToolPort` | `sage_core.repositories.ToolPort` |
| `backend.ports.skill.SkillPort` | `sage_core.repositories.SkillPort` |
| `backend.ports.compute.ComputePort` | `sage_core.repositories.ComputePort` |
| `backend.ports.observability.*` | `sage_core.repositories.observability.*` |

---

## 注意事项

1. **零依赖**：`sage-core` 不依赖任何外部库，仅使用 Python 标准库
2. **不可变性**：所有实体都是 frozen dataclass，创建后不可修改
3. **类型安全**：完整的类型注解，支持 mypy 严格模式
4. **向后兼容**：迁移期间可以同时使用旧路径和新路径

---

## 回滚方案

如果迁移出现问题，可以：

1. 删除 `sage-core` 包：`pip uninstall sage-core`
2. 恢复旧代码：`git checkout backend/`
3. 更新 `requirements.txt`：移除 `sage-core` 依赖

---

## 常见问题

### Q: 为什么要迁移？

**A**: 提取核心领域模型为独立包，可以：
- 独立测试和发布
- 复用到其他项目
- 为 Rust 重写铺路
- 支持多语言绑定

### Q: 迁移会影响性能吗？

**A**: 不会。`sage-core` 是纯 Python 实现，与原 `backend.domain` 完全相同。

### Q: 可以同时使用新旧路径吗？

**A**: 可以。迁移期间可以逐步替换，不需要一次性全部迁移。

---

## 进一步阅读

- [sage-core 文档](./README.md)
- [设计哲学](../../PHILOSOPHY.md)
- [贡献指南](../../CONTRIBUTING.md)
