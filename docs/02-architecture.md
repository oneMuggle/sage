# Sage - 系统架构

## 2.1 架构概览

### 2.1.1 三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      展示层 (Presentation Layer)                  │
│                    Tauri WebView + React 18                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   聊天界面   │  │   设置面板   │  │   记忆浏览器 │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                      控制层 (Control Layer)                      │
│                      Tauri IPC Commands                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   事件分发   │  │   状态同步   │  │   命令路由   │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                      服务层 (Service Layer)                      │
│                       Python Backend                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  SageAgent   │  │   Memory    │  │    Tools    │           │
│  │   引擎       │  │   System    │  │   System    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   Skills    │  │  Scheduler   │  │   Plugins   │           │
│  │   System    │  │   调度器     │  │   System    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                      数据层 (Data Layer)                        │
│                    SQLite + ChromaDB                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   sessions  │  │   memories  │  │  knowledge   │           │
│  │   会话表    │  │   记忆表    │  │   知识表     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1.2 技术栈全景

```
                    ┌─────────────────┐
                    │   Tauri 1.x     │
                    │   (Rust Core)   │
                    └────────┬────────┘
                             │ IPC (JSON-RPC)
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │  React   │  │  Python  │  │  SQLite  │
        │  Frontend│  │  Backend │  │  Data    │
        │  (Vite) │  │  (FastAPI)│  │          │
        └──────────┘  └─────┬─────┘  └──────────┘
                            │
                     ┌──────┴──────┐
                     ▼             ▼
              ┌──────────┐  ┌──────────┐
              │ ChromaDB │  │  External│
              │ (Vector)│  │   APIs   │
              └──────────┘  └──────────┘
```

---

### 2.1.3 后端：六边形架构（Hexagonal Architecture，2026-06-06 P2 完工）

> **P2 重构说明**：Sage 后端已从单体 `core/` 迁移到六边形架构（Ports & Adapters），实现"业务与技术分离"。本节为新架构概览；详细端口列表、依赖约束、双轨切换请阅读 [`docs/technical/18-hexagonal.md`](./technical/18-hexagonal.md)。

```
                    ┌──────────────────────┐
   HTTP/SSE/WS ───▶ │   api (adapters in)  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  application services │  ← 用例编排（ChatService 等）
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
   ┌──────────▼────┐  ┌─────────▼─────┐  ┌───────▼──────┐
   │  domain core  │  │     ports     │  │   ports      │
   │  (pure)       │◀─┤  (interfaces) │─▶│  (interfaces)│
   │  Agent        │  │  LLMPort      │  │  StoragePort │
   │  Message      │  │  ToolPort     │  │  EventPort   │
   │  Tool/Skill   │  │  SkillPort    │  │  MetricPort  │
   └───────────────┘  └────────┬──────┘  └───────┬──────┘
                               │                │
              ┌────────────────┼────────────────┤
              │                │                │
   ┌──────────▼────┐  ┌────────▼─────┐  ┌───────▼──────┐
   │  adapters out │  │  adapters   │  │  adapters    │
   │  httpx LLM    │  │  sqlite     │  │  prom client │
   │  in-proc tool │  │  in-mem     │  │  otel stdlib │
   └───────────────┘  └─────────────┘  └──────────────┘
```

**五层职责**：

| 层 | 路径 | 职责 |
|----|------|------|
| domain | `backend/domain/` | 纯领域模型（AgentState、Message、ToolSpec、LLMError） |
| ports | `backend/ports/` | 6 个 Protocol 接口（LLM / Tool / Skill / Storage / Metric / Event） |
| application | `backend/application/` | 用例编排（ChatService） |
| adapters | `backend/adapters/out/` | 端口的具体实现（httpx / sqlite / inproc / prometheus / file） |
| api | `backend/api/` | HTTP 路由（hex + legacy 双轨，`API_MODE` 切换） |

**双轨策略**：

- `API_MODE=hex`（默认）：新六边形路径，`hex_routes.py` → `ChatService` → ports
- `API_MODE=legacy`：旧路径完全回滚，`legacy_routes.py` → `core/legacy/SageAgent`

**依赖约束**：由 `import-linter` 在 `backend/pyproject.toml` 中配置，5 层单向依赖，**0 violations**。

**测试覆盖**：整体 87%（domain 100% / ports 100% / application 96% / adapters 100% 15/16 / api 75-83%）。

> 旧 `backend/core/agent.py`、`core/orchestrator.py` 等单体文件已迁移至 `backend/core/legacy/`，作为双轨安全网保留。

---

## 2.2 前端架构 (React + Vite)

### 2.2.1 组件层次

```
src/
├── components/           # 可复用组件
│   ├── chat/           # 聊天相关
│   │   ├── ChatInput.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   └── TypingIndicator.tsx
│   ├── session/        # 会话相关
│   │   ├── SessionList.tsx
│   │   └── SessionItem.tsx
│   ├── memory/        # 记忆相关
│   │   ├── MemoryBrowser.tsx
│   │   └── MemoryItem.tsx
│   └── common/        # 通用组件
│       ├── Button.tsx
│       ├── Input.tsx
│       └── Modal.tsx
├── pages/             # 页面
│   ├── Chat.tsx       # 主聊天页
│   ├── Settings.tsx   # 设置页
│   └── Memory.tsx    # 记忆浏览页
├── hooks/             # 自定义 Hooks
│   ├── useChat.ts    # 聊天逻辑
│   ├── useMemory.ts  # 记忆逻辑
│   └── useAgent.ts   # Agent 交互
├── lib/               # 工具库
│   ├── api.ts        # Tauri API 调用
│   ├── store.ts      # Zustand 状态
│   └── utils.ts      # 工具函数
└── App.tsx            # 根组件
```

### 2.2.2 状态管理 (Zustand)

```typescript
// store.ts
interface AppState {
  // 会话状态
  sessions: Session[];
  currentSessionId: string | null;

  // 消息状态
  messages: Record<string, Message[]>;

  // 记忆状态
  memories: Memory[];
  memorySearchQuery: string;

  // UI 状态
  isTyping: boolean;
  sidebarOpen: boolean;

  // Actions
  createSession: () => void;
  sendMessage: (content: string) => Promise<void>;
  searchMemory: (query: string) => Promise<void>;
}
```

### 2.2.3 Tauri API 调用

```typescript
// lib/api.ts
import { invoke } from '@tauri-apps/api/core';

// 会话管理
export const sessionApi = {
  create: () => invoke<string>('create_session'),
  list: () => invoke<Session[]>('list_sessions'),
  delete: (id: string) => invoke('delete_session', { id }),
  getMessages: (sessionId: string) => invoke<Message[]>('get_messages', { sessionId }),
};

// 记忆管理
export const memoryApi = {
  search: (query: string) => invoke<Memory[]>('search_memory', { query }),
  save: (content: string, type: MemoryType) => invoke('save_memory', { content, memoryType: type }),
  delete: (id: string) => invoke('delete_memory', { id }),
};

// Agent 交互
export const agentApi = {
  chat: (sessionId: string, message: string) =>
    invoke<string>('agent_chat', { sessionId, message }),
  interrupt: () => invoke('interrupt_agent'),
};
```

---

## 2.3 后端架构 (Python)

### 2.3.1 模块结构

```
backend/
├── main.py                 # FastAPI 应用入口
├── core/                   # 核心模块
│   ├── __init__.py
│   ├── agent.py           # Agent 主类
│   ├── session.py         # 会话管理
│   ├── config.py          # 配置管理
│   └── exceptions.py      # 异常定义
├── memory/                 # 记忆系统
│   ├── __init__.py
│   ├── base.py           # 记忆基类
│   ├── episodic.py        # 情景记忆
│   ├── semantic.py        # 语义记忆
│   ├── working.py        # 工作记忆
│   └── manager.py        # 记忆管理器
├── tools/                  # 工具系统
│   ├── __init__.py
│   ├── registry.py       # 工具注册表
│   ├── base.py           # 工具基类
│   ├── terminal.py       # 终端工具
│   ├── file_tool.py      # 文件工具
│   ├── web_tool.py       # 网络工具
│   └── calculator.py     # 计算器
├── skills/                 # 技能系统
│   ├── __init__.py
│   ├── base.py           # 技能基类
│   ├── manager.py        # 技能管理器
│   ├── builtin/          # 内置技能
│   │   ├── __init__.py
│   │   ├── search.py     # 搜索技能
│   │   ├── writer.py    # 写作技能
│   │   └── coder.py      # 编程技能
│   └── store.py          # 技能商店
├── plugins/               # 插件系统
│   ├── __init__.py
│   ├── base.py           # 插件基类
│   └── manager.py        # 插件管理器
├── data/                  # 数据层
│   ├── __init__.py
│   ├── database.py       # 数据库连接
│   ├── session_repo.py   # 会话仓库
│   └── memory_repo.py    # 记忆仓库
├── api/                   # API 层
│   ├── __init__.py
│   ├── routes.py         # 路由定义
│   ├── schemas.py        # Pydantic 模型
│   └── dependencies.py   # 依赖注入
└── scheduler/            # 调度器
    ├── __init__.py
    ├── cron.py           # Cron 任务
    └── evolution.py     # 进化任务
```

### 2.3.2 核心类图

```
┌─────────────────────────────────────────────────────────┐
│                        Sage                             │
│                   (主入口类)                              │
├─────────────────────────────────────────────────────────┤
│ - agent: Agent                                          │
│ - session_manager: SessionManager                       │
│ - memory_manager: MemoryManager                         │
│ - tool_registry: ToolRegistry                           │
│ - skill_manager: SkillManager                           │
├─────────────────────────────────────────────────────────┤
│ + chat(session_id, message) -> str                      │
│ + create_session() -> str                              │
│ + search_memory(query) -> list                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                      Agent                              │
│                   (对话引擎)                              │
├─────────────────────────────────────────────────────────┤
│ - model: ChatModel                                      │
│ - memory: MemoryManager                                │
│ - tools: list[Tool]                                    │
│ - skills: list[Skill]                                 │
│ - max_iterations: int                                  │
├─────────────────────────────────────────────────────────┤
│ + run(user_message) -> str                             │
│ + run_with_history(history) -> str                     │
│ + add_tool(tool)                                       │
│ + remove_tool(name)                                    │
└─────────────────────────────────────────────────────────┘
         │                    │                │
         ▼                    ▼                ▼
┌─────────────┐      ┌─────────────┐   ┌─────────────┐
│MemoryManager│      │ToolRegistry │   │SkillManager │
├─────────────┤      ├─────────────┤   ├─────────────┤
│- working    │      │- tools: dict│   │- skills: dict│
│- episodic    │      │- registry   │   │- enabled    │
│- semantic    │      │+ register() │   │+ load()     │
│+ retrieve() │      │+ get()      │   │+ execute()  │
│+ save()      │      │+ list()     │   │+ install()  │
│+ compress()  │      └─────────────┘   └─────────────┘
└─────────────┘
```

---

## 2.4 IPC 通信设计

### 2.4.1 Tauri Commands 定义

```rust
// src-tauri/src/main.rs
#[tauri::command]
async fn create_session(state: State<'_, AppState>) -> Result<String, String> {
    // 创建新会话
}

#[tauri::command]
async fn agent_chat(
    state: State<'_, AppState>,
    session_id: String,
    message: String,
) -> Result<String, String> {
    // 发送消息给 Agent
}

#[tauri::command]
async fn search_memory(
    state: State<'_, AppState>,
    query: String,
) -> Result<Vec<Memory>, String> {
    // 搜索记忆
}
```

### 2.4.2 前后端交互流程

```
User Input
    │
    ▼
┌─────────────┐
│ React UI    │  1. 用户输入消息
└──────┬──────┘
       │ invoke('agent_chat', ...)
       ▼
┌─────────────┐
│ Tauri IPC   │  2. JSON-RPC 调用
└──────┬──────┘
       │ 命令路由
       ▼
┌─────────────┐
│ Python API  │  3. FastAPI 处理
└──────┬──────┘
       │ Agent 推理
       ▼
┌─────────────┐
│ Memory/     │  4. 记忆检索
│ Tools       │     工具执行
└──────┬──────┘
       │ AI 响应
       ▼
┌─────────────┐
│ Response    │  5. 返回结果
└──────┬──────┘
       │
       ▼
    Display
```

---

## 2.5 数据流设计

### 2.5.1 对话数据流

```
User: "明天北京天气怎么样？"
    │
    ▼
┌──────────────────────────────────────┐
│ 1. Input Processing                  │
│    - 文本清洗                         │
│    - 特殊字符处理                      │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ 2. Memory Retrieval                  │
│    - Working Memory 检查              │
│    - Episodic 检索相似对话             │
│    - Semantic 检索相关知识             │
│    - 组装上下文                       │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ 3. Tool Detection                    │
│    - 意图识别: weather                │
│    - 工具: web_search                │
└──────────────────┬───────────────────┘
                   │
         ┌────────┴────────┐
         ▼                 ▼
┌─────────────────┐  ┌─────────────────┐
│ 4a. Tool Execution │ │ 4b. Direct Response │
│    - 调用天气 API  │  │    - 无需工具    │
└────────┬────────┘  └────────┬────────┘
         │                      │
         └──────────┬───────────┘
                    │
                    ▼
┌──────────────────────────────────────┐
│ 5. Response Generation               │
│    - 构建 prompt                      │
│    - 调用 LLM                         │
│    - 格式化输出                       │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ 6. Memory Update                     │
│    - 保存用户消息                     │
│    - 保存 AI 回复                     │
│    - 更新 Working Memory              │
│    - 触发进化检查                     │
└──────────────────┬───────────────────┘
                   │
                   ▼
AI: "明天北京多云转晴，气温 15-23°C..."
```

### 2.5.2 记忆数据流

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Architecture                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Working Memory                        │   │
│  │   (当前对话上下文，Token 窗口内的信息)                 │   │
│  │   - 最近 N 条消息                                    │   │
│  │   - 当前会话摘要                                     │   │
│  │   - 活跃实体/话题                                    │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │ 定时压缩/摘要                      │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Episodic Memory                      │   │
│  │   (情景记忆，SQLite 存储)                             │   │
│  │   - 会话历史                                         │   │
│  │   - 事件序列                                         │   │
│  │   - 情感标记                                         │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │ 定期归档/向量化                     │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Semantic Memory                      │   │
│  │   (语义记忆，ChromaDB 向量存储)                       │   │
│  │   - 知识概念                                         │   │
│  │   - 用户偏好                                         │   │
│  │   - 技能知识                                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2.6 跨平台考虑

### 2.6.1 Windows 7 特殊处理

```python
# backend/core/config.py
import platform
import sys

def get_data_dir() -> Path:
    """获取平台兼容的数据目录"""
    if sys.platform == 'win32':
        if platform.win32_ver()[0] == '7':
            # Windows 7 特殊路径
            return Path(os.environ['USERPROFILE']) / 'AppData' / 'Roaming' / 'Sage'
        else:
            return Path(os.environ['APPDATA']) / 'Sage'
    else:
        return Path.home() / '.sage'
```

### 2.6.2 WebView2 引导

```json
// src-tauri/tauri.conf.json
{
  "bundle": {
    "windows": {
      "webviewInstallMode": {
        "type": "downloadBootstrapper",
        "silent": true
      }
    }
  }
}
```

---

_文档版本: v1.0_
