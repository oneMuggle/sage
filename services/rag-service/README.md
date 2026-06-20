# Sage RAG Service

独立记忆检索服务，提供 HTTP API 进行记忆存储、检索和删除。

## 特性

- ✅ 独立进程，不依赖主后端
- ✅ SQLite + FTS5 全文搜索
- ✅ HTTP API（/search, /index, /delete, /health）
- ✅ 支持过滤和分页
- ✅ 可水平扩展

## 快速开始

### 安装依赖

```bash
cd services/rag-service
pip install -e .
```

### 启动服务

```bash
python main.py
```

服务将在 `http://localhost:8766` 启动。

## API 文档

### POST /api/v1/search

检索记忆。

**请求**：
```json
{
  "query": "Python 教程",
  "top_k": 5,
  "filters": {
    "memory_type": "episodic"
  }
}
```

**响应**：
```json
{
  "results": [
    {
      "id": "mem_001",
      "content": "Python 是一门...",
      "score": 0.95,
      "metadata": {"type": "episodic"}
    }
  ]
}
```

### POST /api/v1/index

索引文档。

**请求**：
```json
{
  "documents": [
    {
      "id": "mem_001",
      "content": "Python 是一门...",
      "metadata": {"type": "episodic"}
    }
  ]
}
```

**响应**：
```json
{
  "indexed_count": 1
}
```

### DELETE /api/v1/documents

删除文档。

**请求**：
```json
{
  "ids": ["mem_001", "mem_002"]
}
```

**响应**：
```json
{
  "deleted_count": 2
}
```

### GET /health

健康检查。

**响应**：
```json
{
  "status": "healthy",
  "service": "rag-service",
  "version": "0.1.0"
}
```

## 架构

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
│  SQLite + FTS5  │
│  (持久化存储)    │
└─────────────────┘
```

## 配置

环境变量：
- `RAG_DB_PATH`: 数据库路径（默认：`data/rag.db`）
- `RAG_HOST`: 服务地址（默认：`0.0.0.0`）
- `RAG_PORT`: 服务端口（默认：`8766`）

## 开发

```bash
# 运行测试
pytest tests/

# 代码格式化
black .
isort .

# 类型检查
mypy .
```

## 部署

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install -e .

CMD ["python", "main.py"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  rag-service:
    build: ./services/rag-service
    ports:
      - "8766:8766"
    volumes:
      - rag-data:/app/data

volumes:
  rag-data:
```

## 许可证

MIT License
