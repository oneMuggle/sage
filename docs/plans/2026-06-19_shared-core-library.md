# 共享核心库模式计划

## 背景与目标

### 背景
当前 Sage 后端采用六边形架构（`backend/domain`、`backend/ports`、`backend/application`、`backend/adapters` 等），但核心业务逻辑与适配器仍然耦合在同一代码库中。这导致：
- 核心逻辑难以独立测试
- 适配器更换需要修改大量代码
- 难以复用核心逻辑到其他项目
- 未来 Rust 重写困难

### 目标
借鉴 claw-code 的共享 `api` crate 模式，提取 `sage-core` 独立包：
1. 核心业务逻辑零依赖，可独立发布
2. 适配器可热插拔（换 LLM 提供商、数据库）
3. 为未来 Rust 重写铺路
4. 支持多语言绑定（Python、Rust、JS）

## 涉及的文件与模块

### 当前模块
- `backend/domain/` - 领域模型
- `backend/ports/` - 端口定义
- `backend/application/` - 应用服务
- `backend/adapters/` - 适配器实现

### 新增模块
- `packages/sage-core/` - 核心包（Python）
  - `packages/sage-core/sage_core/` - 核心代码
    - `entities/` - 领域实体
    - `value_objects/` - 值对象
    - `services/` - 领域服务
    - `repositories/` - 仓库接口
    - `events/` - 领域事件
  - `packages/sage-core/pyproject.toml` - 包配置
  - `packages/sage-core/README.md` - 使用文档

- `packages/sage-core-rs/` - 核心包（Rust，未来）
  - `packages/sage-core-rs/src/` - Rust 实现
  - `packages/sage-core-rs/Cargo.toml` - Cargo 配置

### 修改模块
- `backend/` - 改为依赖 `sage-core` 包
- `backend/adapters/` - 实现 `sage-core` 定义的接口

## 技术方案

### 包结构设计

```
sage-core (Python)
├── entities/          # 领域实体（不可变）
│   ├── memory.py      # Memory 实体
│   ├── conversation.py
│   ├── skill.py
│   └── tool.py
├── value_objects/     # 值对象（不可变）
│   ├── memory_id.py
│   ├── timestamp.py
│   └── content.py
├── services/          # 领域服务（无状态）
│   ├── memory_service.py
│   ├── conversation_service.py
│   └── skill_service.py
├── repositories/      # 仓库接口（抽象）
│   ├── memory_repository.py
│   ├── conversation_repository.py
│   └── skill_repository.py
├── events/            # 领域事件
│   ├── memory_created.py
│   ├── memory_updated.py
│   └── conversation_ended.py
└── exceptions/        # 领域异常
    ├── memory_not_found.py
    └── invalid_state.py
```

### 核心设计原则

#### 1. 零外部依赖
```python
# packages/sage-core/sage_core/entities/memory.py
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

# 不依赖任何外部库，只使用 Python 标准库
@dataclass(frozen=True)  # 不可变
class Memory:
    """记忆实体"""
    id: str
    content: str
    memory_type: str  # "episodic", "semantic", "procedural"
    created_at: datetime
    updated_at: datetime
    metadata: dict
    
    # 领域行为
    def update_content(self, new_content: str) -> 'Memory':
        """返回新的 Memory 实例（不可变）"""
        return Memory(
            id=self.id,
            content=new_content,
            memory_type=self.memory_type,
            created_at=self.created_at,
            updated_at=datetime.utcnow(),
            metadata=self.metadata
        )
```

#### 2. 仓库接口抽象
```python
# packages/sage-core/sage_core/repositories/memory_repository.py
from typing import Protocol, List, Optional
from sage_core.entities.memory import Memory
from sage_core.value_objects.memory_id import MemoryId

class MemoryRepository(Protocol):
    """记忆仓库接口（抽象）"""
    
    async def save(self, memory: Memory) -> None:
        """保存记忆"""
        ...
    
    async def find_by_id(self, id: MemoryId) -> Optional[Memory]:
        """根据 ID 查找"""
        ...
    
    async def find_all(self) -> List[Memory]:
        """查找所有"""
        ...
    
    async def delete(self, id: MemoryId) -> None:
        """删除"""
        ...
```

#### 3. 适配器实现
```python
# backend/adapters/repositories/sqlite_memory_repository.py
from sage_core.repositories.memory_repository import MemoryRepository
from sage_core.entities.memory import Memory
import sqlite3

class SqliteMemoryRepository:
    """SQLite 实现"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
    
    async def save(self, memory: Memory) -> None:
        # 实现保存逻辑
        ...
    
    async def find_by_id(self, id: str) -> Optional[Memory]:
        # 实现查找逻辑
        ...
```

#### 4. 依赖注入
```python
# backend/main.py
from sage_core.services.memory_service import MemoryService
from backend.adapters.repositories.sqlite_memory_repository import SqliteMemoryRepository

# 组装依赖
repository = SqliteMemoryRepository("data/sage.db")
service = MemoryService(repository)

# 使用服务
await service.create_memory("用户问题", "episodic")
```

### 多语言绑定（未来）

#### Rust 绑定
```rust
// packages/sage-core-rs/src/memory.rs
use pyo3::prelude::*;

#[pyclass]
pub struct Memory {
    id: String,
    content: String,
    memory_type: String,
}

#[pymethods]
impl Memory {
    #[new]
    fn new(id: String, content: String, memory_type: String) -> Self {
        Memory { id, content, memory_type }
    }
}
```

#### JavaScript 绑定
```typescript
// packages/sage-core-js/src/memory.ts
export class Memory {
  constructor(
    public id: string,
    public content: string,
    public memoryType: string
  ) {}
  
  updateContent(newContent: string): Memory {
    return new Memory(this.id, newContent, this.memoryType);
  }
}
```

## 实施步骤

### 阶段 1：核心提取（2 周）
- [ ] 1.1 创建 `packages/sage-core/` 目录结构
- [ ] 1.2 提取领域实体到 `entities/`
- [ ] 1.3 提取值对象到 `value_objects/`
- [ ] 1.4 提取仓库接口到 `repositories/`
- [ ] 1.5 编写 `pyproject.toml` 配置
- [ ] 1.6 编写核心单元测试

### 阶段 2：适配器改造（1.5 周）
- [ ] 2.1 修改 `backend/adapters/` 实现核心接口
- [ ] 2.2 修改 `backend/application/` 使用核心服务
- [ ] 2.3 配置依赖注入
- [ ] 2.4 编写集成测试
- [ ] 2.5 验证功能完整性

### 阶段 3：测试与文档（1 周）
- [ ] 3.1 核心包 100% 测试覆盖
- [ ] 3.2 编写 API 文档
- [ ] 3.3 编写使用示例
- [ ] 3.4 编写迁移指南
- [ ] 3.5 性能基准测试

### 阶段 4：发布与集成（0.5 周）
- [ ] 4.1 发布到 PyPI（或私有仓库）
- [ ] 4.2 修改 `backend/requirements.txt`
- [ ] 4.3 更新 CI/CD 配置
- [ ] 4.4 团队培训

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 核心接口设计不合理 | 高 | 充分评审，迭代优化 |
| 性能下降（包边界） | 中 | 基准测试，优化关键路径 |
| 迁移复杂度高 | 中 | 分阶段迁移，保持兼容 |
| 团队学习成本 | 低 | 提供培训与文档 |

### 依赖
- Python 3.8+（dataclass 支持）
- pytest（测试）
- poetry 或 pip（包管理）

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| 核心提取 | 2 周 |
| 适配器改造 | 1.5 周 |
| 测试与文档 | 1 周 |
| 发布与集成 | 0.5 周 |
| **总计** | **5 周** |

## 验证标准

1. **功能验证**：所有现有功能正常工作
2. **性能验证**：性能下降 < 5%
3. **测试验证**：核心包测试覆盖率 > 95%
4. **兼容性验证**：向后兼容旧接口（过渡期）

## 示例：迁移前后对比

### 迁移前
```python
# backend/domain/memory.py
from backend.database import get_db

class Memory:
    def __init__(self, id, content, ...):
        self.id = id
        self.content = content
    
    def save(self):
        db = get_db()
        db.execute("INSERT INTO ...")
```

**问题**：领域逻辑与数据库耦合

### 迁移后
```python
# packages/sage-core/sage_core/entities/memory.py
@dataclass(frozen=True)
class Memory:
    id: str
    content: str
    # 纯领域逻辑，无依赖

# backend/adapters/repositories/sqlite_memory_repository.py
class SqliteMemoryRepository:
    async def save(self, memory: Memory):
        # 适配器负责持久化
```

**优势**：核心逻辑可独立测试、复用、替换适配器

## 长期收益

1. **可测试性**：核心逻辑可独立单元测试
2. **可替换性**：适配器可热插拔
3. **可复用性**：核心逻辑可用于其他项目
4. **可演进性**：为 Rust 重写铺路
5. **多语言支持**：可绑定到 JS/Rust/其他语言
