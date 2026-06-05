# Sage - API 接口设计

## 10.1 API 概览

### 10.1.1 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Tauri IPC Layer                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Frontend (React)  ══════ IPC ══════>  Backend (Python)        │
│                                                                  │
│   invoke()                                      FastAPI          │
│   +──────────┐                               +──────────┐        │
│   │ Commands │                               │  Routes  │        │
│   └──────────┘                               └──────────┘        │
│                                                  │               │
│                                         ┌────────┴────────┐     │
│                                         │   Services      │     │
│                                         │ +──────────────+│     │
│                                         │ │ Agent         ││     │
│                                         │ │ Session       ││     │
│                                         │ │ Memory        ││     │
│                                         │ │ Skills        ││     │
│                                         │ └──────────────+│     │
│                                         └─────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 10.1.2 Tauri Commands vs REST API

| 场景        | 方式           | 说明               |
| ----------- | -------------- | ------------------ |
| 前端 ↔ 后端 | Tauri Commands | 同一进程内，低延迟 |
| 后端 ↔ 外部 | HTTP REST      | 调用外部 API       |
| 插件/扩展   | Plugin API     | 独立模块接口       |

---

## 10.2 Tauri Commands

### 10.2.1 命令定义

```rust
// src-tauri/src/main.rs

#[tauri::command]
async fn create_session(
    state: State<'_, AppState>,
    title: Option<String>,
) -> Result<Session, String> {
    state.agent.create_session(title).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_sessions(
    state: State<'_, AppState>,
    limit: Option<usize>,
) -> Result<Vec<Session>, String> {
    state.agent.list_sessions(limit).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_session(
    state: State<'_, AppState>,
    id: String,
) -> Result<(), String> {
    state.agent.delete_session(&id).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_messages(
    state: State<'_, AppState>,
    session_id: String,
    limit: Option<usize>,
    before: Option<i64>,
) -> Result<Vec<Message>, String> {
    state.agent.get_messages(&session_id, limit, before)
        .await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn agent_chat(
    state: State<'_, AppState>,
    session_id: String,
    message: String,
) -> Result<ChatResponse, String> {
    state.agent.chat(&session_id, &message).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn agent_chat_stream(
    state: State<'_, AppState>,
    session_id: String,
    message: String,
) -> Result<impl Stream<Item = String>, String> {
    Ok(state.agent.chat_stream(&session_id, &message).await)
}

#[tauri::command]
async fn interrupt_agent(
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.agent.interrupt();
    Ok(())
}

#[tauri::command]
async fn search_memory(
    state: State<'_, AppState>,
    query: String,
    memory_type: Option<String>,
    limit: Option<usize>,
) -> Result<Vec<Memory>, String> {
    state.agent.search_memory(&query, memory_type.as_deref(), limit)
        .await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn save_memory(
    state: State<'_, AppState>,
    content: String,
    memory_type: String,
    importance: Option<i32>,
    tags: Option<Vec<String>>,
) -> Result<Memory, String> {
    state.agent.save_memory(&content, &memory_type, importance, tags)
        .await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_preferences(
    state: State<'_, AppState>,
) -> Result<Preferences, String> {
    state.agent.get_preferences().map_err(|e| e.to_string())
}

#[tauri::command]
async fn set_preference(
    state: State<'_, AppState>,
    key: String,
    value: String,
) -> Result<(), String> {
    state.agent.set_preference(&key, &value).map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_skills(
    state: State<'_, AppState>,
) -> Result<Vec<SkillInfo>, String> {
    state.agent.list_skills().map_err(|e| e.to_string())
}

#[tauri::command]
async fn toggle_skill(
    state: State<'_, AppState>,
    name: String,
    enabled: bool,
) -> Result<(), String> {
    state.agent.toggle_skill(&name, enabled).map_err(|e| e.to_string())
}
```

### 10.2.2 数据模型

```rust
// src-tauri/src/models.rs

#[derive(Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub title: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub message_count: i32,
    pub is_pinned: bool,
}

#[derive(Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub session_id: String,
    pub role: String,  // "user" | "assistant" | "system" | "tool"
    pub content: String,
    pub tool_calls: Option<Vec<ToolCall>>,
    pub created_at: i64,
    pub tokens: Option<i32>,
}

#[derive(Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: String,  // JSON string
}

#[derive(Serialize, Deserialize)]
pub struct ChatResponse {
    pub content: String,
    pub finish_reason: String,
    pub tool_calls: Option<Vec<ToolCall>>,
    pub usage: Option<Usage>,
}

#[derive(Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: i32,
    pub output_tokens: i32,
    pub total_tokens: i32,
}

#[derive(Serialize, Deserialize)]
pub struct Memory {
    pub id: String,
    pub content: String,
    pub summary: Option<String>,
    pub memory_type: String,  // "episodic" | "semantic"
    pub importance: i32,
    pub tags: Vec<String>,
    pub created_at: i64,
    pub accessed_at: Option<i64>,
}

#[derive(Serialize, Deserialize)]
pub struct Preferences {
    pub model: String,
    pub temperature: f32,
    pub max_tokens: i32,
    pub theme: String,
    pub language: String,
}

#[derive(Serialize, Deserialize)]
pub struct SkillInfo {
    pub name: String,
    pub description: String,
    pub is_enabled: bool,
    pub is_builtin: bool,
    pub usage_count: i64,
}
```

---

## 10.3 Python Backend API

### 10.3.1 FastAPI 应用

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .core.agent import SageAgent
from .core.config import load_config
from .api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    config = load_config()
    app.state.agent = SageAgent(config)
    yield
    # 关闭时清理
    await app.state.agent.shutdown()

app = FastAPI(
    title="Sage API",
    description="Sage AI Assistant Backend API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(router)

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
```

### 10.3.2 API 路由

```python
# backend/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel

from ..schemas import (
    SessionCreate, SessionResponse,
    MessageResponse, ChatRequest, ChatResponse,
    MemorySearchRequest, MemoryResponse,
    PreferencesResponse, SkillResponse
)

router = APIRouter(prefix="/api/v1")

# ========== Sessions ==========

@router.post("/sessions", response_model=SessionResponse)
async def create_session(title: Optional[str] = None):
    """创建新会话"""
    session = await agent.create_session(title)
    return session

@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(limit: int = 50):
    """列出会话"""
    sessions = await agent.list_sessions(limit)
    return sessions

@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话"""
    session = await agent.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, message="Session not found")
    return session

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    await agent.delete_session(session_id)
    return {"success": True}

# ========== Messages ==========

@router.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    session_id: str,
    limit: int = 50,
    before: Optional[int] = None
):
    """获取会话消息"""
    messages = await agent.get_messages(session_id, limit, before)
    return messages

# ========== Chat ==========

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """发送消息"""
    response = await agent.chat(
        session_id=request.session_id,
        message=request.message,
        stream=False
    )
    return response

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式发送消息"""
    # 返回流式响应
    return StreamingResponse(
        agent.chat_stream(request.session_id, request.message),
        media_type="text/plain"
    )

@router.post("/interrupt")
async def interrupt():
    """中断当前对话"""
    agent.interrupt()
    return {"success": True}

# ========== Memory ==========

@router.post("/memory/search", response_model=List[MemoryResponse])
async def search_memory(request: MemorySearchRequest):
    """搜索记忆"""
    memories = await agent.search_memory(
        query=request.query,
        memory_type=request.memory_type,
        limit=request.limit
    )
    return memories

@router.post("/memory", response_model=MemoryResponse)
async def save_memory(
    content: str,
    memory_type: str = "episodic",
    importance: int = 5,
    tags: Optional[List[str]] = None
):
    """保存记忆"""
    memory = await agent.save_memory(content, memory_type, importance, tags)
    return memory

@router.get("/memory", response_model=List[MemoryResponse])
async def list_memories(
    memory_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """列出记忆"""
    memories = await agent.list_memories(memory_type, page, page_size)
    return memories

@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除记忆"""
    await agent.delete_memory(memory_id)
    return {"success": True}

# ========== Skills ==========

@router.get("/skills", response_model=List[SkillResponse])
async def list_skills():
    """列出技能"""
    skills = await agent.list_skills()
    return skills

@router.post("/skills/{skill_name}/toggle")
async def toggle_skill(skill_name: str, enabled: bool):
    """启用/禁用技能"""
    await agent.toggle_skill(skill_name, enabled)
    return {"success": True}

@router.post("/skills/{skill_name}/execute")
async def execute_skill(skill_name: str, params: dict):
    """执行技能"""
    result = await agent.execute_skill(skill_name, params)
    return result
```

### 10.3.3 Pydantic Schemas

```python
# backend/api/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class SessionCreate(BaseModel):
    title: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    message_count: int = 0
    is_pinned: bool = False

class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    created_at: int
    tokens: Optional[int] = None

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    content: str
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, int]] = None

class MemorySearchRequest(BaseModel):
    query: str
    memory_type: Optional[str] = None
    limit: int = 10

class MemoryResponse(BaseModel):
    id: str
    content: str
    summary: Optional[str] = None
    memory_type: str
    importance: int
    tags: List[str] = []
    created_at: int
    accessed_at: Optional[int] = None

class PreferencesResponse(BaseModel):
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 4096
    theme: str = "light"
    language: str = "zh-CN"

class SkillResponse(BaseModel):
    name: str
    description: str
    triggers: List[str] = []
    is_enabled: bool
    is_builtin: bool
    usage_count: int = 0
```

---

## 10.4 IPC 通信协议

### 10.4.1 请求格式

```typescript
// 前端调用示例
import { invoke } from '@tauri-apps/api/core';

// 创建会话
const session = await invoke<SessionResponse>('create_session', {
  title: '我的新对话',
});

// 发送消息
const response = await invoke<ChatResponse>('agent_chat', {
  sessionId: session.id,
  message: '你好',
});

// 搜索记忆
const memories = await invoke<MemoryResponse[]>('search_memory', {
  query: '用户偏好',
  memoryType: 'semantic',
  limit: 10,
});
```

### 10.4.2 事件系统

```rust
// src-tauri/src/events.rs

#[derive(Clone, Serialize)]
pub struct TypingEvent {
    pub session_id: String,
    pub is_typing: bool,
}

#[derive(Clone, Serialize)]
pub struct ProgressEvent {
    pub session_id: String,
    pub message: String,
    pub progress: f32,
}

#[derive(Clone, Serialize)]
pub struct ToolCallEvent {
    pub session_id: String,
    pub tool_name: String,
    pub status: String,  // "started" | "completed" | "failed"
}

// 发送事件
app.emit("typing", TypingEvent {
    session_id: session_id.clone(),
    is_typing: true,
}).unwrap();
```

---

## 10.5 错误处理

### 10.5.1 错误码

| 错误码 | 说明         | HTTP 状态 |
| ------ | ------------ | --------- |
| 1001   | 会话不存在   | 404       |
| 1002   | 会话已删除   | 410       |
| 2001   | 记忆不存在   | 404       |
| 2002   | 记忆存储失败 | 500       |
| 3001   | 技能不存在   | 404       |
| 3002   | 技能执行失败 | 500       |
| 4001   | Agent 超时   | 504       |
| 4002   | Agent 中断   | 499       |
| 9001   | 未知错误     | 500       |

### 10.5.2 错误响应

```typescript
interface ErrorResponse {
  error: {
    code: number
    message: string
    details?: any
  }
}

// 示例
{
  "error": {
    "code": 1001,
    "message": "Session not found",
    "details": {
      "session_id": "abc123"
    }
  }
}
```

---

## 10.6 API 使用示例

### 10.6.1 完整对话流程

```typescript
// 1. 创建会话
const session = await invoke<Session>('create_session', { title: '测试对话' });

// 2. 发送消息
const response = await invoke<ChatResponse>('agent_chat', {
  sessionId: session.id,
  message: '帮我写一个 Python Hello World',
});

console.log('AI 回复:', response.content);

// 3. 获取消息历史
const messages = await invoke<Message[]>('get_messages', {
  sessionId: session.id,
  limit: 50,
});

// 4. 搜索相关记忆
const memories = await invoke<Memory[]>('search_memory', {
  query: '用户之前的代码偏好',
});

// 5. 保存重要信息到记忆
await invoke('save_memory', {
  content: '用户喜欢用 Python 3.10+',
  memoryType: 'semantic',
  importance: 8,
  tags: ['编程', 'Python'],
});
```

---

_文档版本: v1.0_
