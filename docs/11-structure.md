# Sage - 目录结构

## 11.1 项目根目录

```
sage/
├── .git/                      # Git 版本控制
├── .gitignore
│
├── src-tauri/                 # Tauri 后端 (Rust)
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── build.rs
│   ├── src/
│   │   ├── main.rs           # 入口
│   │   ├── lib.rs            # 库入口
│   │   ├── commands.rs        # Tauri Commands
│   │   ├── models.rs          # 数据模型
│   │   ├── state.rs           # 应用状态
│   │   └── utils.rs           # 工具函数
│   └── icons/                 # 应用图标
│
├── src/                       # React 前端
│   ├── components/            # React 组件
│   ├── pages/                 # 页面组件
│   ├── hooks/                 # 自定义 Hooks
│   ├── lib/                  # 工具库
│   ├── i18n/                  # 国际化
│   ├── App.tsx                # 根组件
│   ├── main.tsx               # 入口
│   └── index.css              # 全局样式
│
├── backend/                   # Python 后端
│   ├── main.py               # FastAPI 入口
│   ├── requirements.txt       # Python 依赖
│   ├── core/                 # 核心模块
│   ├── memory/               # 记忆系统
│   ├── tools/                # 工具系统
│   ├── skills/               # 技能系统
│   ├── plugins/              # 插件系统
│   ├── data/                 # 数据层
│   ├── api/                  # API 层
│   └── scheduler/            # 调度器
│
├── skills/                    # 技能定义
│   ├── builtin/              # 内置技能
│   └── custom/               # 用户技能
│
├── docs/                      # 文档
│   ├── README.md             # 文档首页
│   ├── 01-overview.md        # 项目概述
│   ├── 02-architecture.md   # 系统架构
│   ├── 03-database.md        # 数据库设计
│   ├── 04-memory.md          # 记忆系统
│   ├── 05-agent.md           # Agent 引擎
│   ├── 06-tools.md           # 工具系统
│   ├── 07-skills.md          # 技能系统
│   ├── 08-evolution.md       # 进化系统
│   ├── 09-frontend.md        # 前端设计
│   ├── 10-api.md             # API 接口
│   ├── 11-structure.md       # 目录结构
│   └── 12-plan.md            # 实施计划
│
├── scripts/                   # 脚本
│   ├── setup.sh              # 安装脚本
│   ├── build.sh              # 构建脚本
│   └── dev.sh                # 开发脚本
│
├── tests/                     # 测试
│   ├── unit/                 # 单元测试
│   ├── integration/           # 集成测试
│   └── fixtures/             # 测试数据
│
├── package.json               # Node.js 配置
├── vite.config.ts            # Vite 配置
├── tsconfig.json             # TypeScript 配置
├── tailwind.config.js        # Tailwind 配置
├── README.md                  # 项目说明
└── LICENSE                   # 许可证
```

---

## 11.2 Tauri 后端 (src-tauri)

```
src-tauri/
├── Cargo.toml                # Rust 依赖
├── tauri.conf.json          # Tauri 配置
├── build.rs                 # 构建脚本
│
├── src/
│   ├── main.rs              # 主入口
│   │   ├── use case:
│   │   │   fn main() {
│   │   │       tauri::Builder()
│   │   │           .setup()
│   │   │           .invoke_handler()
│   │   │           .run()
│   │   │   }
│   │
│   ├── lib.rs               # 库入口
│   │   ├── pub mod commands;
│   │   ├── pub mod models;
│   │   ├── pub mod state;
│   │   └── pub mod utils;
│   │
│   ├── commands.rs           # Tauri Commands
│   │   ├── Session Commands
│   │   │   ├── create_session()
│   │   │   ├── list_sessions()
│   │   │   ├── get_session()
│   │   │   └── delete_session()
│   │   │
│   │   ├── Message Commands
│   │   │   ├── get_messages()
│   │   │   └── delete_messages()
│   │   │
│   │   ├── Chat Commands
│   │   │   ├── agent_chat()
│   │   │   ├── agent_chat_stream()
│   │   │   └── interrupt_agent()
│   │   │
│   │   ├── Memory Commands
│   │   │   ├── search_memory()
│   │   │   ├── save_memory()
│   │   │   └── delete_memory()
│   │   │
│   │   ├── Settings Commands
│   │   │   ├── get_preferences()
│   │   │   └── set_preference()
│   │   │
│   │   └── Skills Commands
│   │       ├── list_skills()
│   │       ├── toggle_skill()
│   │       └── execute_skill()
│   │
│   ├── models.rs             # 数据模型
│   │   ├── Session
│   │   ├── Message
│   │   ├── Memory
│   │   ├── Preferences
│   │   └── SkillInfo
│   │
│   ├── state.rs             # 应用状态
│   │   └── struct AppState {
│   │           agent: PyAgent
│   │       }
│   │
│   └── utils.rs             # 工具函数
│
└── icons/                    # 应用图标
    ├── icon.ico              # Windows
    ├── icon.png              # macOS/Linux
    └── icon.icns             # macOS
```

---

## 11.3 React 前端 (src)

```
src/
├── main.tsx                  # 入口
│   └── ReactDOM.createRoot()
│
├── App.tsx                  # 根组件
│   └── BrowserRouter
│       └── Routes
│           ├── /chat
│           ├── /memory
│           ├── /skills
│           └── /settings
│
├── index.css                # Tailwind 入口
│
├── components/               # 可复用组件
│   ├── chat/               # 聊天组件
│   │   ├── ChatInput.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   ├── MessageActions.tsx
│   │   └── TypingIndicator.tsx
│   │
│   ├── session/            # 会话组件
│   │   ├── SessionList.tsx
│   │   ├── SessionItem.tsx
│   │   ├── SessionSearch.tsx
│   │   └── NewSessionButton.tsx
│   │
│   ├── memory/             # 记忆组件
│   │   ├── MemoryBrowser.tsx
│   │   ├── MemoryItem.tsx
│   │   ├── MemorySearch.tsx
│   │   └── MemoryEditor.tsx
│   │
│   ├── settings/           # 设置组件
│   │   ├── SettingsPanel.tsx
│   │   ├── ModelSettings.tsx
│   │   ├── ThemeSettings.tsx
│   │   └── AboutSettings.tsx
│   │
│   ├── skills/             # 技能组件
│   │   ├── SkillList.tsx
│   │   ├── SkillCard.tsx
│   │   └── SkillDetail.tsx
│   │
│   ├── layout/             # 布局组件
│   │   ├── Layout.tsx
│   │   ├── Sidebar.tsx
│   │   └── Header.tsx
│   │
│   └── common/             # 通用组件
│       ├── Button.tsx
│       ├── Input.tsx
│       ├── Modal.tsx
│       ├── Dropdown.tsx
│       ├── Tooltip.tsx
│       ├── Spinner.tsx
│       └── Avatar.tsx
│
├── pages/                   # 页面
│   ├── Chat.tsx            # 主聊天页
│   │   ├── ChatPage
│   │   ├── useChat hook
│   │   └── MessageList + ChatInput
│   │
│   ├── Memory.tsx          # 记忆浏览页
│   │   ├── MemoryPage
│   │   └── MemoryBrowser
│   │
│   ├── Settings.tsx        # 设置页
│   │   ├── SettingsPage
│   │   └── SettingsPanel
│   │
│   └── Skills.tsx         # 技能商店页
│       ├── SkillsPage
│       └── SkillList
│
├── hooks/                   # 自定义 Hooks
│   ├── useChat.ts         # 聊天逻辑
│   │   ├── sendMessage()
│   │   ├── interrupt()
│   │   └── messages state
│   │
│   ├── useSessions.ts     # 会话管理
│   │   ├── createSession()
│   │   ├── deleteSession()
│   │   └── sessions state
│   │
│   ├── useMemory.ts       # 记忆操作
│   │   ├── searchMemory()
│   │   ├── saveMemory()
│   │   └── memories state
│   │
│   ├── useAgent.ts        # Agent 状态
│   │   ├── chat()
│   │   └── stream()
│   │
│   └── useStore.ts        # 全局状态
│       └── Zustand store
│
├── lib/                     # 工具库
│   ├── api.ts             # Tauri API 调用
│   │   ├── sessionApi
│   │   ├── messageApi
│   │   ├── chatApi
│   │   ├── memoryApi
│   │   └── skillApi
│   │
│   ├── store.ts           # Zustand store
│   │   └── useStore
│   │
│   └── utils.ts           # 工具函数
│       ├── formatDate()
│       ├── formatTokens()
│       └── cn.ts (中文工具)
│
└── i18n/                    # 国际化
    ├── index.ts            # i18next 配置
    └── locales/
        ├── zh-CN.json      # 中文
        └── en.json         # 英文
```

---

## 11.4 Python 后端 (backend)

```
backend/
├── main.py                  # FastAPI 入口
│   └── app = FastAPI()
│
├── requirements.txt          # Python 依赖
│
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── agent.py            # SageAgent 主类
│   │   ├── class SageAgent
│   │   ├── chat()
│   │   ├── run_loop()
│   │   └── interrupt()
│   │
│   ├── session.py          # 会话管理
│   │   ├── class SessionManager
│   │   ├── create_session()
│   │   ├── get_session()
│   │   └── list_sessions()
│   │
│   ├── message_builder.py  # 消息构建
│   │   ├── class MessageBuilder
│   │   ├── build_system_prompt()
│   │   └── build_messages()
│   │
│   ├── tool_executor.py    # 工具执行
│   │   ├── class ToolExecutor
│   │   ├── execute()
│   │   └── execute_all()
│   │
│   ├── config.py           # 配置管理
│   │   ├── load_config()
│   │   └── Config dataclass
│   │
│   └── exceptions.py       # 异常定义
│       ├── AgentError
│       ├── ToolCallError
│       └── MaxIterationsError
│
├── memory/                  # 记忆系统
│   ├── __init__.py
│   ├── base.py            # 记忆基类
│   ├── working.py          # 工作记忆
│   │   └── class WorkingMemory
│   │
│   ├── episodic.py          # 情景记忆
│   │   └── class EpisodicMemory
│   │
│   ├── semantic.py          # 语义记忆
│   │   └── class SemanticMemory
│   │
│   ├── manager.py          # 记忆管理器
│   │   └── class MemoryManager
│   │       ├── remember()
│   │       ├── memorize()
│   │       └── compress()
│   │
│   └── evolution.py        # 记忆进化
│       └── class MemoryEvolution
│
├── tools/                   # 工具系统
│   ├── __init__.py
│   ├── registry.py         # 工具注册表
│   │   └── class ToolRegistry
│   │
│   ├── base.py             # 工具基类
│   │   ├── class BaseTool
│   │   └── class ToolSchema
│   │
│   ├── terminal.py          # 终端工具
│   ├── file_tool.py         # 文件工具
│   │   ├── ReadFileTool
│   │   ├── WriteFileTool
│   │   └── ListDirTool
│   │
│   ├── web_tool.py         # 网络工具
│   │   ├── WebSearchTool
│   │   └── WebFetchTool
│   │
│   ├── memory_tool.py       # 记忆工具
│   │   ├── MemorySearchTool
│   │   └── MemorySaveTool
│   │
│   ├── calculator.py        # 计算器工具
│   └── delegate.py         # 委托工具
│
├── skills/                  # 技能系统
│   ├── __init__.py
│   ├── registry.py         # 技能注册表
│   ├── base.py             # 技能基类
│   │   ├── class BaseSkill
│   │   └── class SkillSchema
│   │
│   ├── manager.py          # 技能管理器
│   │   └── class SkillManager
│   │
│   ├── builtin/            # 内置技能
│   │   ├── __init__.py
│   │   ├── search.py       # SearchSkill
│   │   ├── writer.py       # WriterSkill
│   │   ├── coder.py        # CoderSkill
│   │   ├── travel.py       # TravelSkill
│   │   └── calculator.py    # CalculatorSkill
│   │
│   └── store.py            # 技能商店
│       └── class SkillStore
│
├── plugins/                 # 插件系统
│   ├── __init__.py
│   ├── base.py             # 插件基类
│   ├── manager.py           # 插件管理器
│   └── loader.py            # 插件加载器
│
├── data/                    # 数据层
│   ├── __init__.py
│   ├── database.py         # 数据库连接
│   │   └── class DatabasePool
│   │
│   ├── session_repo.py     # 会话仓库
│   │   └── class SessionRepository
│   │
│   ├── memory_repo.py      # 记忆仓库
│   │   └── class MemoryRepository
│   │
│   └── migrations.py       # 数据库迁移
│       └── run_migrations()
│
├── api/                     # API 层
│   ├── __init__.py
│   ├── routes.py           # 路由定义
│   │   ├── /api/v1/sessions
│   │   ├── /api/v1/messages
│   │   ├── /api/v1/chat
│   │   ├── /api/v1/memory
│   │   └── /api/v1/skills
│   │
│   ├── schemas.py          # Pydantic 模型
│   │   ├── SessionCreate
│   │   ├── ChatRequest
│   │   ├── MemoryResponse
│   │   └── ...
│   │
│   └── dependencies.py     # 依赖注入
│
├── scheduler/               # 调度器
│   ├── __init__.py
│   ├── cron.py            # Cron 任务调度
│   │   └── class EvolutionScheduler
│   │
│   ├── evolution.py        # 进化任务
│   │   ├── DailySummaryTask
│   │   ├── MemoryPruningTask
│   │   ├── PreferenceLearningTask
│   │   └── ImportanceReevaluationTask
│   │
│   └── tasks.py            # 定时任务
│
└── utils/                   # 工具函数
    ├── __init__.py
    ├── logging.py          # 日志配置
    └── security.py         # 安全工具
```

---

## 11.5 配置文件

```
配置文件位置:
├── Tauri 配置
│   └── src-tauri/tauri.conf.json
│
├── Python 配置
│   └── backend/config.yaml
│
├── 前端配置
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── tsconfig.json
│
└── Python 依赖
    └── backend/requirements.txt
```

### 11.5.1 requirements.txt

```
# Core
fastapi==0.109.0
uvicorn==0.27.0
pydantic==2.5.0

# Database
sqlite3 (built-in)
chromadb==0.4.22

# AI
openai==1.12.0
httpx==0.26.0

# Utils
python-dotenv==1.0.0
pyyaml==6.0.1
```

---

*文档版本: v1.0*
