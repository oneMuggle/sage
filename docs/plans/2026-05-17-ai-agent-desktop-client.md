# Sage AI Agent Desktop Client - 完整实施方案

**日期**: 2026-05-17
**状态**: 实施中
**目标**: Windows 7 本地运行的具备记忆功能、自我进化及多Agent协作的桌面客户端
**参考项目**: Cherry Studio + Hermes Agent

---

## 1. 需求分析

### 1.1 核心需求

- **Windows 7 兼容**: 必须能在 Win7 SP1 上本地运行
- **记忆功能**: 持久化三层记忆系统（工作/情景/语义）
- **自我进化**: Agent能从交互中学习，更新规则和惯例
- **多Agent协作**: 多个专用Agent协同工作

### 1.2 参考项目关键特性

| 项目          | 核心特性                           | Sage借鉴                               |
| ------------- | ---------------------------------- | -------------------------------------- |
| Cherry Studio | 多模型聚合、Agent管理、知识库、MCP | 模型提供商抽象、知识记忆、工具系统     |
| Hermes Agent  | 多层记忆、自进化循环、多Agent编排  | 进化引擎、Shared Blackboard、Skill发现 |

---

## 2. Win7 技术约束与选型

### 2.1 硬性约束

| 约束                     | 影响                | 缓解措施                               |
| ------------------------ | ------------------- | -------------------------------------- |
| WebView2 未预装          | 需嵌入 bootstrapper | `embedBootstrapper` 已配置             |
| TLS 1.3 不支持           | 部分API需TLS 1.2    | 确保API端点使用TLS 1.2                 |
| Node.js 13.14.0 最后支持 | 现代构建工具不兼容  | 构建在Win10+，分发编译后产物           |
| Electron 11-22 最后支持  | 安全风险            | 使用Tauri 1.x（已选定）                |
| Python 3.8-3.11 兼容     | 3.12+ 不支持Win7    | 锁定 `requires-python = ">=3.8,<3.12"` |

### 2.2 技术栈

```
桌面壳:    Tauri 1.6.x (Rust)
前端:      React 18 + TypeScript 5 + Vite 5 + TailwindCSS 3
状态管理:  Zustand 4.x
后端:      Python 3.8-3.11 (FastAPI + subprocess)
数据库:    SQLite 3.x (内置FTS5)
LLM接口:   OpenAI-compatible API协议
调度器:    APScheduler 3.10.x
```

---

## 3. 现有代码状态分析

### 3.1 已完成

- [x] Tauri 1.6 项目骨架
- [x] React 前端骨架 + 路由
- [x] SQLite 数据库 schema (8个表 + FTS5 + 索引)
- [x] 三层记忆系统骨架
- [x] Agent 骨架 (SageAgent: chat, QueryCache, 记忆提取)
- [x] 工具系统 (Terminal, File, Web, Calculator, Memory)
- [x] 进化任务骨架 (DailySummary, MemoryPruning, PreferenceLearning, ImportanceReevaluation)
- [x] FastAPI 后端入口 + API路由
- [x] Win7 WebView2 embedBootstrapper 配置
- [x] LLM 客户端 (OpenAI-compatible)
- [x] Python 进程管理器 (Rust)
- [x] 记忆压缩管道 (ConsolidationPipeline)
- [x] FTS5 全文搜索触发器
- [x] 多Agent系统 (Profile + Blackboard + Orchestrator)
- [x] 自我进化 (ConventionManager + 错误分析)
- [x] Skill热加载系统 (SkillHotLoader)
- [x] Agents 管理页面 + 导航集成

### 3.2 待实施范围

- **Phase 1**: Python进程管理器 + LLM客户端 + Agent ReAct循环 + Rust命令重组
- **Phase 2**: 记忆FTS5完善 + 记忆压缩管道 + 记忆注入上下文
- [x] **Phase 3**: 工具执行完善 + Skill热加载
- [x] **Phase 4**: 多Agent (Profile + Blackboard + Orchestrator)
- [x] **Phase 5**: 自我进化 (Convention + 错误分析 + 惯例管理)
- [x] **Phase 6**: 前端完善 (Agents管理页面 + 导航集成)
- **Phase 7**: 发布

---

## 4. 系统架构

### 4.1 多Agent架构

- **主Agent**: 面向用户，编排其他Agent
- **研究Agent**: 网络搜索、信息收集
- **编码Agent**: 代码生成、调试
- **记忆Agent**: 记忆生命周期管理
- **通信**: Shared Blackboard (SQLite pub/sub)

### 4.2 自我进化

```
Observe -> Reflect -> Update -> Verify (循环)
```

- 惯例进化、偏好学习、Skill发现、错误分析
- 安全机制: 用户审批、回滚、置信度阈值、速率限制

---

_完整实施步骤和风险管理详见正文。_
