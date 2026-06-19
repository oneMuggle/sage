# RAG 服务化计划

## 背景与目标

### 背景
当前 Sage 的记忆系统集成在 `backend/memory/` 中，使用 ChromaDB + SQLite 实现向量存储与检索。这种嵌入式架构存在以下问题：
- 后端进程重启时，索引状态可能丢失
- 无法支持多进程/多设备并发访问
- 难以扩展到 Web/移动端共享记忆
- 记忆检索与业务逻辑耦合，难以独立优化

### 目标
借鉴 claw-code 的 `claw-rag-service` 设计，将记忆检索功能剥离为独立的 RAG 服务：
1. 独立的 RAG 服务进程（HTTP API）
2. 支持多进程/多设备并发检索
3. 后端进程重启不影响索引状态
4. 可扩展到云端部署

## 涉及的文件与模块

### 当前模块
- `backend/memory/` - 记忆系统核心逻辑
  - `backend/memory/storage.py` - 存储层
  - `backend/memory/embeddings.py` - 向量嵌入
  - `backend/memory/consolidation.py` - 记忆整合
  - `backend/memory/vector_store.py` - ChromaDB 封装

### 新增模块
- `services/rag-service/` - 独立 RAG 服务
  - `services/rag-service/main.py` - 服务入口
  - `services/rag-service/api/` - HTTP API 端点
  - `services/rag-service/core/` - 核心检索逻辑
  - `services/rag-service/config.py` - 配置管理
  - `services/rag-service/Dockerfile` - 容器化部署

### 修改模块
- `backend/memory/` - 改为通过 HTTP 调用 RAG 服务
- `backend/config.py` - 添加 RAG 服务配置
- `docker-compose.yml` - 添加 RAG 服务编排

## 技术方案

### 架构设计

```
┌─────────────────┐
│  Sage Backend   │
│  (FastAPI)      │
└────────┬────────┘
         │ HTTP API
         ▼
┌─────────────────┐
│  RAG Service    │
│  (独立进程)      │
│  ├─ /search     │
│  ├─ /index      │
│  ├─ /delete     │
│  └─ /health     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SQLite + 向量   │
│  (持久化存储)    │
└─────────────────┘
```

### API 设计

#### 检索接口
```python
POST /api/v1/search
{
    "query": "用户问题",
    "top_k": 5,
    "filters": {
        "memory_type": "episodic",
        "date_range": {"start": "2026-01-01", "end": "2026-06-19"}
    }
}

Response:
{
    "results": [
        {
            "id": "mem_001",
            "content": "记忆内容",
            "score": 0.95,
            "metadata": {...}
        }
    ]
}
```

#### 索引接口
```python
POST /api/v1/index
{
    "documents": [
        {
            "id": "mem_001",
            "content": "记忆内容",
            "metadata": {"type": "episodic", "timestamp": "..."}
        }
    ]
}
```

#### 删除接口
```python
DELETE /api/v1/documents
{
    "ids": ["mem_001", "mem_002"]
}
```

### 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 与现有后端一致，异步支持好 |
| 向量存储 | SQLite + sqlite-vss | 轻量、单文件、易部署 |
| 嵌入模型 | sentence-transformers | 开源、质量稳定 |
| 部署 | Docker | 容器化、易扩展 |

## 实施步骤

### 阶段 1：RAG 服务骨架（1 周）
- [ ] 1.1 创建 `services/rag-service/` 目录结构
- [ ] 1.2 实现基础 FastAPI 服务骨架
- [ ] 1.3 配置 SQLite + sqlite-vss 向量存储
- [ ] 1.4 实现 `/health` 健康检查端点
- [ ] 1.5 编写基础单元测试

### 阶段 2：核心检索功能（2 周）
- [ ] 2.1 实现 `/search` 检索端点
- [ ] 2.2 实现 `/index` 索引端点
- [ ] 2.3 实现 `/delete` 删除端点
- [ ] 2.4 集成 sentence-transformers 嵌入模型
- [ ] 2.5 添加检索过滤器支持（日期、类型）
- [ ] 2.6 编写集成测试

### 阶段 3：后端集成（1 周）
- [ ] 3.1 创建 RAG 服务客户端封装
- [ ] 3.2 修改 `backend/memory/` 调用 RAG 服务
- [ ] 3.3 添加服务发现与配置管理
- [ ] 3.4 实现降级策略（RAG 服务不可用时）
- [ ] 3.5 端到端测试

### 阶段 4：部署与运维（1 周）
- [ ] 4.1 编写 Dockerfile
- [ ] 4.2 编写 docker-compose.yml
- [ ] 4.3 添加日志与监控
- [ ] 4.4 编写部署文档
- [ ] 4.5 性能测试与优化

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| RAG 服务不可用 | 高 | 实现降级策略，本地缓存热点数据 |
| 网络延迟增加 | 中 | 优化 API 设计，减少往返次数 |
| 数据一致性 | 高 | 实现事务性写入，添加数据校验 |
| 部署复杂度增加 | 中 | 提供 docker-compose 一键部署 |

### 依赖
- SQLite 版本 >= 3.35.0（支持窗口函数）
- sqlite-vss 扩展可用
- sentence-transformers 模型下载

### 性能指标
| 指标 | 目标值 |
|------|--------|
| 检索延迟 P95 | < 200ms |
| 索引吞吐量 | > 100 docs/s |
| 并发连接数 | > 50 |
| 内存占用 | < 512MB |

## 验证标准

1. **功能验证**：所有 API 端点通过集成测试
2. **性能验证**：达到性能指标要求
3. **可靠性验证**：RAG 服务重启后，后端能自动重连
4. **兼容性验证**：现有记忆功能不受影响

## 回滚计划

如果 RAG 服务化出现问题，可以：
1. 保留 `backend/memory/` 原有实现作为 fallback
2. 通过配置切换使用本地或远程 RAG
3. 必要时回退到嵌入式架构
