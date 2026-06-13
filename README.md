# Sage

**记忆型 AI 桌面助手 | Win10+/macOS/Linux 主线 + Windows 7 长期维护分支**

> "Sage - 你的记忆型 AI 助手"

## 项目愿景

Sage 是一款**轻量级 AI 桌面助手**，具备：

- 🧠 **持久记忆** - 跨会话记住你的偏好、习惯和重要信息
- 🔄 **自我进化** - 从对话中学习，不断优化响应质量
- 🛠️ **技能扩展** - 支持插件和自定义技能
- 💻 **轻量运行** - Electron + Python 架构，跨平台

## 🪟 双轨发布

Sage 维护**两条独立分支**，分别针对不同平台：

| 分支 | 目标平台 | 桌面框架 | Python | Win7 前置 | 状态 |
|---|---|---|---|---|---|
| **`main`** | Win10+ / macOS / Linux | Electron 21.4.4 | 3.10+ | n/a | ✅ 主线持续迭代 |
| **`release/win7`** | **Windows 7 SP1 x64**（**完全离线**部署）| Electron 21.4.4 | 3.10+ | KB3033929（必装）| ⚠️ 长期维护 |

**如何选择？**
- 普通用户：使用 `main` 分支，享受最新功能。
- **Win7 用户**（内网/无网/老硬件）：使用 `release/win7` 分支。下载方式见各分支的 [GitHub Releases](https://github.com/your-repo/sage/releases) 页面。

**Win7 部署前置**：
1. **KB3033929**（SHA-2 代码签名支持）— 必装，否则 Sage.exe 启动被拒
2. **x64 only** — Electron 21 不支持 Win7 32-bit
3. 详见 [docs/technical/20-electron-win7.md §6](./docs/technical/20-electron-win7.md#6-win7-部署前置)

**为什么 Electron 21 而非 Electron 28+？**
Electron 22 起官方 changelog 砍掉 Win7/8/8.1 支持。Electron 21.4.4 是最后一版自带 Chromium 106 + Node 16.20、能真正在 Win7 SP1 上启动的版本。详见 [docs/technical/20-electron-win7.md](./docs/technical/20-electron-win7.md)。

## 核心功能

```
┌─────────────────────────────────────────┐
│              Sage 核心功能                │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │  对话   │  │  记忆   │  │  技能   │ │
│  │  引擎   │  │  系统   │  │  商店   │ │
│  └─────────┘  └─────────┘  └─────────┘ │
│                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │  工具   │  │  设置   │  │ 系统    │ │
│  │  集    │  │  面板   │  │ 托盘   │ │
│  └─────────┘  └─────────┘  └─────────┘ │
│                                         │
└─────────────────────────────────────────┘
```

## 技术架构

```
┌─────────────────────────────────────────┐
│         桌面客户端 (Tauri + React)        │
├─────────────────────────────────────────┤
│         IPC 通信层 (Tauri Commands)      │
├─────────────────────────────────────────┤
│         Python 后端                      │
│  ├── Agent 编排引擎                      │
│  ├── 记忆系统 (情景 + 语义)               │
│  ├── 工具集 (terminal/file/web)          │
│  └── 技能系统                            │
├─────────────────────────────────────────┤
│         数据层 (SQLite + ChromaDB)       │
└─────────────────────────────────────────┘
```

## 技术栈

| 层级     | 技术     | 版本  |
| -------- | -------- | ----- |
| 桌面框架 | Tauri    | 1.x   |
| 前端     | React    | 18.x  |
| 构建     | Vite     | 5.x   |
| 后端     | Python   | 3.8+  |
| 数据库   | SQLite   | 3.x   |
| 向量存储 | ChromaDB | 0.4.x |

---

## 📦 安装步骤

### 环境要求

- **操作系统**: Windows 7+ / Linux / macOS
- **Node.js**: ≥ 18.x
- **Python**: ≥ 3.10
- **Conda**: `sage-backend` 环境（用于 FastAPI 后端）

### 1. 克隆项目

```bash
git clone https://github.com/your-repo/sage.git
cd sage
```

### 2. 安装前端依赖

```bash
npm install
```

### 3. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
cd ..
```

### 4. 配置环境变量

复制 `.env.example` 为 `.env` 并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# API 配置
API_BASE_URL=http://localhost:8000
API_KEY=your-api-key-here

# 数据库配置
DATABASE_PATH=./data/sage.db

# 记忆系统配置
MEMORY_TOP_K=10
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

### 5. 初始化数据库

```bash
cd backend
python -c "from database import init_db; init_db()"
cd ..
```

---

## 🚀 使用说明

### 开发模式

#### 启动前端开发服务器

```bash
npm run dev
```

前端将在 `http://localhost:5173` 运行。

#### 启动后端服务

```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 将在 `http://localhost:8000` 运行。

### 生产构建

#### 构建前端

```bash
npm run build
```

构建产物将输出到 `dist/` 目录。

#### 构建 Electron 桌面应用

```bash
# 开发模式（自动启动 vite dev server + electron 主进程 + FastAPI 子进程）
npm run electron:dev

# 生产构建（前端 + 主进程编译 + electron-builder 打包 NSIS）
npm run electron:dist
```

### 应用界面

启动后，您将看到以下主要界面：

1. **对话界面** - 与 AI 助手进行自然语言对话
2. **记忆面板** - 查看和管理 AI 的记忆
3. **技能商店** - 浏览和安装技能插件
4. **设置面板** - 配置应用参数

---

## ⚙️ 配置说明

### 配置文件位置

- **前端配置**: `src/config.ts`
- **后端配置**: `backend/config.py`
- **Tauri配置**: `src-tauri/tauri.conf.json`
- **环境变量**: `.env`

### 主要配置项

#### 前端配置 (`src/config.ts`)

```typescript
export const config = {
  // API 地址
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',

  // 默认模型
  defaultModel: 'gpt-4',

  // 主题设置
  theme: 'light', // 'light' | 'dark' | 'auto'

  // 日志级别
  logLevel: 'info', // 'debug' | 'info' | 'warn' | 'error'
};
```

#### 后端配置 (`backend/config.py`)

```python
# 数据库配置
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/sage.db")

# 记忆系统配置
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "10"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# API 配置
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
```

#### Tauri 配置 (`src-tauri/tauri.conf.json`)

```json
{
  "build": {
    "devtools": true
  },
  "app": {
    "windows": [
      {
        "title": "Sage",
        "width": 1200,
        "height": 800,
        "minWidth": 800,
        "minHeight": 600,
        "resizable": true,
        "fullscreen": false
      }
    ]
  }
}
```

---

## ❓ 常见问题

### Q1: 启动前端时出现模块未找到错误

**A**: 确保已运行 `npm install` 安装所有依赖。

```bash
npm install
npm run dev
```

### Q2: 后端启动失败，端口被占用

**A**: 更改后端端口或终止占用端口的进程。

```bash
# 查看端口占用
netstat -ano | findstr :8000

# 终止进程 (Windows)
taskkill /PID <PID> /F

# 或使用其他端口
python -m uvicorn main:app --port 8001
```

### Q3: 记忆系统不工作

**A**: 检查 ChromaDB 服务是否正常运行，并确认 `EMBEDDING_MODEL` 配置正确。

```bash
# 检查 ChromaDB
pip show chromadb

# 重新初始化记忆系统
python -c "from memory import init_memory; init_memory()"
```

### Q4: Windows 7 下无法运行

**A**: 确保已安装以下依赖：

- WebView2 Runtime (下载: https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
- Visual C++ Redistributable

### Q5: 构建产物巨大

**A**: 这是 Tauri 的正常行为。如需减小体积：

1. 在 `tauri.conf.json` 中启用 `bundle.resources`
2. 使用 `tauri build --debug` 进行开发构建
3. 考虑使用 UPX 压缩可执行文件

### Q6: 如何更新技能？

**A**:

1. 打开技能商店面板
2. 浏览可用技能
3. 点击安装按钮
4. 重启应用使技能生效

### Q7: 记忆占用过多空间

**A**: 在设置中调整记忆保留策略，或手动触发记忆修剪。

---

## 📂 项目结构

```
sage/
├── src/                    # React 前端源码
│   ├── components/         # UI 组件
│   ├── hooks/              # React Hooks
│   ├── lib/                # 工具库
│   ├── pages/              # 页面组件
│   └── config.ts           # 前端配置
├── src-tauri/              # Tauri Rust 后端
│   ├── src/                # Rust 源码
│   ├── icons/              # 应用图标
│   ├── Cargo.toml          # Rust 依赖
│   └── tauri.conf.json     # Tauri 配置
├── backend/                # Python 后端
│   ├── agents/             # Agent 引擎
│   ├── memory/             # 记忆系统
│   ├── tools/              # 工具集
│   ├── skills/             # 技能系统
│   ├── database/           # 数据库模块
│   ├── main.py             # 入口文件
│   └── requirements.txt    # Python 依赖
├── docs/                   # 详细设计文档
├── .github/                 # GitHub 配置
│   └── workflows/          # CI/CD 工作流
├── package.json            # npm 配置
└── README.md               # 项目文档
```

---

## 🔧 详细文档

| 文档                                  | 说明                         |
| ------------------------------------- | ---------------------------- |
| [设计方案](./docs/01-overview.md)     | 项目概述、目标、竞品对比     |
| [系统架构](./docs/02-architecture.md) | 整体架构、数据流设计         |
| [数据库设计](./docs/03-database.md)   | 表结构、索引、备份           |
| [记忆系统](./docs/04-memory.md)       | 三层记忆、检索、进化         |
| [Agent 引擎](./docs/05-agent.md)      | 对话引擎、消息构建、工具执行 |
| [工具系统](./docs/06-tools.md)        | 内置工具、注册表、权限       |
| [技能系统](./docs/07-skills.md)       | 技能定义、管理器、商店       |
| [进化系统](./docs/08-evolution.md)    | 定时任务、摘要、修剪         |
| [前端设计](./docs/09-frontend.md)     | UI 组件、状态管理            |
| [API 接口](./docs/10-api.md)          | Tauri Commands、REST API     |
| [目录结构](./docs/11-structure.md)    | 项目文件结构                 |
| [实施计划](./docs/12-plan.md)         | 开发阶段、里程碑             |

---

## 📊 构建验证结果

### T5.8 构建验证

- **前端构建**: ⚠️ TypeScript 类型错误 (开发阶段正常)
  - 主要问题: Tauri API 模块未安装、store API 导出问题
  - 解决方案: 完善 @tauri-apps/api 依赖和 store 模块导出

- **Rust 检查**: ⚠️ Cargo 未安装
  - 预期行为: 仅验证代码可用性，实际构建需在目标环境执行

---

## 项目状态

🚧 **开发中** - 详细设计阶段

## License

MIT
