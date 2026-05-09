# Sage - Win7 兼容 AI 助手设计方案

## 一、项目概述

**项目名称**: Sage
**核心定位**: 适配 Windows 7 系统的轻量级 AI 桌面助手，具备记忆系统和自我进化能力
**Slogan**: "Sage - 你的记忆型 AI 助手"
**对标参考**: Chatbox (UI交互) + Hermes Agent (记忆/Agent架构)

---

## 二、Win7 兼容性分析

### 2.1 关键技术约束

| 技术组件 | Chatbox/Hermes 原始方案 | Win7 兼容替代方案 |
|---------|------------------------|------------------|
| 运行时 | Electron (Chromium) | Tauri 1.x (WebView2) 或 C# .NET WPF |
| Node.js | ≥20.0.0 | Node.js 16.x (或纯 Python 方案) |
| 系统API | 现代 Windows API | Win32 API / Windows 7 API |
| TLS | 现代 TLS 1.3 | Windows 7 最高 TLS 1.2 (KB3140245) |
| WebView | Chromium | IE11 WebView 或 WebView2 (需Win7支持版) |

### 2.2 Electron vs Tauri 对比

```
Electron 问题:
- Chromium 内核对 Win7 支持已终止
- Electron 32+ 要求 Node 20+
- 内存占用大 (~150MB+ 基础)

Tauri 1.x 优势:
- 使用系统 WebView2 (Win10/11 内置)
- WebView2 兼容 Win7 (KB4549949)
- 二进制体积小 (~10MB)
- Rust 后端，性能好
```

**结论**: 推荐 **Tauri 1.x** + **Python 后端** 架构

---

## 三、系统架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    桌面客户端 (Tauri + React)              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │   聊天界面   │  │   设置面板   │  │   记忆浏览器 │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
├─────────────────────────────────────────────────────────┤
│                    IPC 通信层 (Tauri Commands)            │
├─────────────────────────────────────────────────────────┤
│                    Python 后端服务                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ 会话管理  │  │ 记忆系统  │  │ Agent   │  │ 插件   │ │
│  │ (SQLite) │  │ (向量DB) │  │ 编排引擎 │  │ 系统   │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ 工具集   │  │ 技能系统  │  │ 调度器   │               │
│  └──────────┘  └──────────┘  └──────────┘               │
└─────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
hermes-win7/
├── src-tauri/                 # Tauri Rust 后端
│   ├── src/
│   │   ├── main.rs           # 入口
│   │   ├── commands/         # Tauri Commands
│   │   └── webview/          # WebView 配置
│   ├── Cargo.toml
│   └── tauri.conf.json
│
├── src/                      # React 前端
│   ├── components/          # UI 组件
│   ├── pages/               # 页面
│   ├── hooks/               # 自定义 Hooks
│   └── lib/                 # 前端工具库
│
├── backend/                  # Python 后端
│   ├── core/
│   │   ├── agent.py         # Agent 核心类
│   │   ├── session.py       # 会话管理
│   │   ├── memory/          # 记忆系统
│   │   │   ├── episodic.py   # 情景记忆
│   │   │   ├── semantic.py   # 语义记忆
│   │   │   └── working.py    # 工作记忆
│   │   ├── skills/          # 技能系统
│   │   └── tools/           # 工具集
│   ├── plugins/             # 插件目录
│   ├── data/                # 数据存储 (SQLite)
│   └── requirements.txt
│
├── skills/                   # 技能定义
├── docs/                     # 文档
└── README.md
```

---

## 四、核心模块设计

### 4.1 记忆系统 (Memory System)

参考 Hermes Agent 的 `memories/` 设计:

```
记忆层级:
┌─────────────────────────────────────────┐
│         Working Memory (工作记忆)         │
│   当前对话上下文，Token 限制内的信息       │
└─────────────────────────────────────────┘
                    ↓ 压缩/摘要
┌─────────────────────────────────────────┐
│       Episodic Memory (情景记忆)          │
│   对话历史摘要，SQLite 存储               │
│   表: conversations(id, summary, ts)     │
└─────────────────────────────────────────┘
                    ↓ 定期归档
┌─────────────────────────────────────────┐
│       Semantic Memory (语义记忆)          │
│   持久化知识，向量搜索 (ChromaDB/SQLite)  │
│   表: knowledge(id, embedding, content) │
└─────────────────────────────────────────┘
```

**关键特性**:
- `memory.tools()`: 自动保存对话摘要
- `session_search()`: 跨会话搜索
- 记忆衰减 + 重要性加权

### 4.2 Agent 编排引擎

参考 Hermes `run_agent.py` 的 AIAgent 类:

```python
class HermesWin7Agent:
    def __init__(self, model, session_id, memory_system):
        self.model = model
        self.session_id = session_id
        self.memory = memory_system
        self.tools = load_tools()
        self.skills = load_skills()

    def chat(self, message: str) -> str:
        # 1. 检索记忆
        context = self.memory.retrieve(message)

        # 2. 构建消息
        messages = self.build_messages(message, context)

        # 3. 模型推理
        response = self.model.complete(messages, tools=self.tools)

        # 4. 处理工具调用
        while response.tool_calls:
            result = self.execute_tool(response.tool_calls)
            messages.append(result)
            response = self.model.complete(messages)

        # 5. 保存记忆
        self.memory.save(message, response)

        return response.content
```

### 4.3 工具系统 (Tools)

参考 Hermes `toolsets.py`:

| 工具类别 | 功能 | 实现方式 |
|---------|------|---------|
| terminal | 执行命令 | subprocess |
| file | 文件读写 | pathlib |
| web | 网络搜索 | requests |
| code | 代码执行 | subprocess + REPL |
| memory | 记忆操作 | SQLite |
| delegate | 任务委托 | multiprocessing |

### 4.4 技能系统 (Skills)

参考 Hermes `skills/` + agency-agents:

```python
# skill 定义结构
class Skill:
    name: str
    description: str
    triggers: list[str]  # 触发关键词
    execute: function    # 执行函数
    metadata: dict       # 角色/权限配置
```

**内置技能**:
- 写作代理 (Writing Agent)
- 编程助手 (Coding Agent)
- 研究助理 (Research Agent)
- 旅行规划 (Travel Agent)
- 购物向导 (Shopping Agent)

---

## 五、UI/UX 设计

### 5.1 技术选型

| 层级 | 技术 | 理由 |
|-----|------|------|
| 框架 | React 18 | 成熟生态，Chatbox 已用 |
| 状态管理 | Zustand | 轻量，Win7 兼容 |
| 样式 | Tailwind CSS | Chatbox 已用 |
| 打包 | Vite | 快速构建 |
| Tauri | 1.x | Win7 兼容 |

### 5.2 界面布局

```
┌────────────────────────────────────────────────────────┐
│  Sage                              [_] [□] [X]  │
├────────────┬───────────────────────────────────────────┤
│            │                                           │
│  会话列表   │           聊天区域                         │
│            │                                           │
│  ─────────  │  ┌─────────────────────────────────────┐  │
│  新建对话   │  │ AI: 你好，我是 Sage           │  │
│            │  │    有什么可以帮你的吗？                │  │
│  [对话1]   │  └─────────────────────────────────────┘  │
│  [对话2]   │                                           │
│  [对话3]   │  ┌─────────────────────────────────────┐  │
│            │  │ User: 帮我写一个 Python 脚本         │  │
│            │  └─────────────────────────────────────┘  │
│            │                                           │
├────────────┴───────────────────────────────────────────┤
│  [记忆] [技能] [设置]        [发送]                     │
└────────────────────────────────────────────────────────┘
```

### 5.3 特殊界面功能

1. **记忆浏览器**: 查看/编辑/搜索个人记忆
2. **技能商店**: 安装/管理 AI 技能
3. **系统托盘**: 最小化到托盘，后台运行
4. **快捷键**: 全局热键唤醒

---

## 六、进化系统设计

### 6.1 自我进化机制

```
┌─────────────────────────────────────────────────────┐
│                   进化循环                           │
│                                                     │
│   收集反馈 ──→ 分析模式 ──→ 生成改进 ──→ 验证效果   │
│       ↑                                       │     │
│       └──────────── 循环迭代 ←────────────────┘     │
└─────────────────────────────────────────────────────┘
```

### 6.2 进化维度

| 维度 | 方式 | 实现 |
|-----|------|------|
| 记忆优化 | 定期摘要 | 自动压缩旧对话 |
| 技能习得 | 从对话学习 | 提取新技能模式 |
| 响应优化 | 反馈学习 | 用户评分 → RL |
| 个性化 | 用户画像 | 偏好记忆 |

### 6.3 进化触发条件

```python
EVOLUTION_TRIGGERS = {
    'daily_summary': '0 2 * * *',      # 每日凌晨2点摘要
    'weekly_review': '0 3 * * 0',       # 每周日凌晨回顾
    'skill_discovery': 'on_conversation_end',  # 对话结束时
    'feedback_learning': 'on_rating',   # 用户评分时
}
```

---

## 七、数据存储设计

### 7.1 SQLite 表结构

```sql
-- 会话表
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    metadata TEXT  -- JSON
);

-- 消息表
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    role TEXT,  -- 'user' | 'assistant' | 'system'
    content TEXT,
    tokens INTEGER,
    created_at INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 记忆表
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT,
    type TEXT,  -- 'episodic' | 'semantic'
    importance INTEGER,
    embedding TEXT,  -- 序列化向量
    created_at INTEGER,
    accessed_at INTEGER
);

-- 技能表
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT,
    code TEXT,
    enabled INTEGER,
    created_at INTEGER
);

-- 用户偏好表
CREATE TABLE preferences (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER
);
```

### 7.2 数据路径 (Win7 兼容)

```python
import os
from pathlib import Path

# Win7 兼容路径
DATA_DIR = Path(os.environ['APPDATA']) / 'Sage'
CACHE_DIR = Path(os.environ['LOCALAPPDATA']) / 'Sage' / 'Cache'

# 兼容 Windows 7
if sys.getwindowsversion()[:2] <= (6, 1):  # Win7
    DATA_DIR = Path(os.environ['USERPROFILE']) / 'AppData' / 'Roaming' / 'Sage'
```

---

## 八、技术栈总结

### 8.1 最终技术选型

| 层级 | 技术 | 版本 | 说明 |
|-----|------|------|------|
| 桌面框架 | Tauri | 1.x | Win7 兼容，轻量 |
| 前端框架 | React | 18.x | 成熟生态 |
| 前端构建 | Vite | 5.x | 快速 |
| 后端语言 | Python | 3.8-3.11 | 兼容性广泛 |
| 数据库 | SQLite | 3.x | 零依赖 |
| 向量存储 | ChromaDB | 0.4.x | 轻量级 |
| AI SDK | openai-python | 1.x | 统一接口 |
| HTTP 客户端 | httpx | 0.25.x | 异步支持 |

### 8.2 Win7 特殊处理

1. **TLS 问题**: 强制使用 `httpx` 并配置 `verify=False` 测试，或要求用户安装 KB3140245
2. **WebView2**: 打包时内嵌 WebView2 引导安装程序
3. **Node.js**: 前端构建在开发机完成，打包后无 Node 依赖
4. **权限**: 避开需要 Windows 10+ 的 API

---

## 九、实施计划

### 阶段一: 基础框架 (第1-2周)
- [ ] 项目初始化 (Tauri + React + Python)
- [ ] 基础聊天界面
- [ ] SQLite 会话管理
- [ ] 基础 Agent 类

### 阶段二: 记忆系统 (第3-4周)
- [ ] 情景记忆实现
- [ ] 语义记忆 + 向量搜索
- [ ] 记忆检索 API
- [ ] 记忆浏览器 UI

### 阶段三: 工具与技能 (第5-6周)
- [ ] 基础工具集 (terminal, file, web)
- [ ] 技能系统框架
- [ ] 内置技能实现
- [ ] 技能商店 UI

### 阶段四: 进化系统 (第7-8周)
- [ ] 自动摘要任务
- [ ] 反馈学习机制
- [ ] 定期进化调度
- [ ] 进化日志

### 阶段五: 优化与打包 (第9-10周)
- [ ] 性能优化
- [ ] Win7 兼容性测试
- [ ] 安装包制作
- [ ] 文档完善

---

## 十、参考项目

1. **Chatbox** (`chatboxai/chatbox`)
   - UI 设计参考
   - React + TypeScript 最佳实践
   - Electron 跨平台经验

2. **Hermes Agent** (`hermes-agent`)
   - Agent 架构
   - 记忆系统设计
   - 工具/技能系统
   - 插件架构

3. **相关技术**
   - Tauri: https://tauri.app/
   - ChromaDB: https://www.trychroma.com/
   - SQLite: 内置 Python

---

*文档版本: v1.0*  
*创建时间: 2026-05-09*
