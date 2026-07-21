# Sage

**记忆型 AI 桌面助手 | Win10+/macOS/Linux 主线 + Windows 7 长期维护分支**

> "Sage - 你的记忆型 AI 助手"

## 项目愿景

Sage 是一款**轻量级 AI 桌面助手**，具备：

- 🧠 **持久记忆** - 跨会话记住你的偏好、习惯和重要信息
- 🔄 **自我进化** - 从对话中学习，不断优化响应质量
- 🛠️ **技能扩展** - 支持插件和自定义技能
- 💻 **轻量运行** - Electron + Python 架构，跨平台

## 🎯 设计哲学

Sage 遵循 4 个核心设计原则：

1. **记忆优先** - 所有交互默认持久化，除非显式拒绝
2. **渐进式自演化** - Agent 可从错误中学习，但需人类审批
3. **透明可控** - 所有自动化行为可审计、可回滚
4. **简单胜于复杂** - 优先选择简单方案，除非复杂性能证明其价值

详见 [PHILOSOPHY.md](./PHILOSOPHY.md)

## 🪟 双轨发布

Sage 维护**两条独立的 GitHub Release 通道**，分别针对不同平台：

| 通道        | 触发分支       | 目标平台                                  | 产物                                                          | Electron       | Python  | 状态                   |
| ----------- | -------------- | ----------------------------------------- | ------------------------------------------------------------- | -------------- | ------- | ---------------------- |
| **main release**   | `main`         | Win10+ / Linux / macOS (Phase 3+)         | `Sage-Setup-${version}-win10.exe` / `sage_${version}_amd64.deb` / `Sage-${version}.AppImage` | 21.4.4         | 3.11+   | ✅ 主线持续迭代        |
| **LTS release**    | `release/win7` | **Windows 7 SP1 x64**（完全离线部署）     | `Sage-Setup-${version}-win7.exe`                               | 21.4.4 (冻结)  | 3.8     | ⚠️ 长期维护, 仅 hotfix, 2027-12-13 EOL |

**预发布档位**（v0.5.0+ 适用，main 与 win7 LTS 同步）：

| 档位 | 触发 tag 格式 | 适合谁 | 风险 | GitHub Release 标记 |
|------|---------------|--------|------|---------------------|
| **alpha** | `vX.Y.Z-alpha.N` | Sage 贡献者 | 高 | `prerelease=true` |
| **beta** | `vX.Y.Z-beta.N` | 公开测试者 | 中高 | `prerelease=true` |
| **RC / preview** | `vX.Y.Z-rc.N` | 早期采用者 | 中 | `prerelease=true` |
| **stable** | `vX.Y.Z` | 全量用户 | 低 | `latest`（默认） |

Win7 LTS 派生在档位后追加 `-lts`（如 `vX.Y.Z-beta.N-lts`），artifact 同步加 `-lts` 后缀（`alpha-lts` / `beta-lts` / `rc-lts` / `win7`）。预发布版默认不在 "Latest" 展示，避免误装。完整分级系统见 [`docs/technical/30-release-tiers.md`](./docs/technical/30-release-tiers.md)；升档脚本与 artifact 命名规则见 [`docs/technical/26-packaging-matrix.md` §7](./docs/technical/26-packaging-matrix.md)。

**下载入口**:

- **普通用户 (Win10+/Linux/macOS)**:  https://github.com/oneMuggle/sage/releases/latest
- **Win7 SP1 x64 用户**: https://github.com/oneMuggle/sage/releases?q=tag%3Av*-lts (tag 形如 `v0.2.0-lts`)

**为什么需要两条通道？**

- main release 已经移除了 Win7 特定兼容代码路径（Chromium 启动开关等），产物不再支持 Win7
- LTS release 锁在 Electron 21.4.4 + Python 3.8，单独维护 Win7 SP1 x64
- 两条通道独立迭代：main 后续可升 Electron 28+/32+，LTS 维持冻结

详细同步策略和风险说明见 [`release/win7` 分支的 BRANCH_NOTES.md](https://github.com/oneMuggle/sage/blob/release/win7/BRANCH_NOTES.md) 和 [`docs/technical/31-win7-lts.md`](./docs/technical/31-win7-lts.md)。

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
│         桌面客户端 (Electron + React)        │
├─────────────────────────────────────────┤
│         IPC 通信层 (BrowserWindow + preload)      │
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

| 层级     | 技术     | 版本   |
| -------- | -------- | ------ |
| 桌面框架 | Electron | 21.4.4 |
| 前端     | React    | 18.x   |
| 构建     | Vite     | 5.x    |
| 后端     | Python   | 3.8+   |
| 数据库   | SQLite   | 3.x    |
| 向量存储 | ChromaDB | 0.4.x  |

---

## 📦 安装步骤

### 环境要求

- **操作系统**: Windows 7+ / Linux / macOS
- **Node.js**: ≥ 18.x
- **Python**: ≥ 3.8
- **Rust**: (不需要，Electron 是 JS 运行时)

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

#### 构建 Electron 应用

```bash
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
- **Electron配置**: `electron-builder.yml` + `tsconfig.electron.json`
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

#### Electron 配置 (`electron-builder.yml` + `tsconfig.electron.json`)

```yaml
# electron-builder.yml (节选)
appId: com.sage.desktop
productName: Sage
directories:
  output: release
files:
  - dist/**
  - dist-electron/**
win:
  target: nsis
mac:
  target: dmg
linux:
  target: AppImage
```

```jsonc
// tsconfig.electron.json (节选)
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "CommonJS",
    "outDir": "dist-electron",
    "strict": true,
  },
  "include": ["electron/**/*"],
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

### Q4: Windows 7 下无法运行 / 哪里下载 Win7 版

**A**:

- **main release (`Sage-Setup-${version}-win10.exe`) 已不再支持 Win7**（自 2026-06-23 起）
- **Win7 SP1 x64 用户**请从 LTS release 下载 `Sage-Setup-${version}-win7.exe`：
  https://github.com/oneMuggle/sage/releases?q=tag%3Av*-lts
- 前置条件: 装 **KB3033929** (SHA-2 代码签名, 2016 年发布)；x64 only
- 详细: [`docs/technical/31-win7-lts.md` §6](./docs/technical/31-win7-lts.md) 风险声明

### Q5: 构建产物巨大

**A**: 这是 Electron 的正常行为（基础安装包约 100-150MB，含 Chromium）。如需减小体积：

1. 在 `electron-builder.yml` 中使用 `asar` 打包
2. 排除不必要的 `node_modules` 子模块
3. 考虑按目标平台分别构建（win/mac/linux 各占约 50-80MB）

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
├── electron/              # Electron 主进程源码
│   ├── main.ts            # Electron 主进程入口
│   └── preload.ts         # preload 脚本（IPC 桥）
├── electron-builder.yml    # Electron 打包配置
├── build/                  # 应用图标资源
│   ├── icon.ico
│   └── icon.png
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
| [API 接口](./docs/10-api.md)          | BrowserWindow IPC、REST API  |
| [目录结构](./docs/11-structure.md)    | 项目文件结构                 |
| [实施计划](./docs/12-plan.md)         | 开发阶段、里程碑             |

---

## 📊 构建验证结果

### T5.8 构建验证

- **前端构建**: ⚠️ TypeScript 类型错误 (开发阶段正常)
  - 主要问题: Electron API 模块未安装、preload 类型导出问题
  - 解决方案: 完善 electron 类型定义和 preload 模块导出

- **Electron 主进程构建**: ✅ `npm run build:electron` 通过
  - 预期行为: 仅验证代码可用性，实际打包需在目标环境执行

---

## 项目状态

🚧 **开发中** - 详细设计阶段

## License

MIT
