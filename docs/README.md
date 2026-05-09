# Sage - 详细技术方案

**版本**: v1.0
**日期**: 2026-05-09
**状态**: 设计方案

---

## 目录

1. [项目概述](./01-overview.md)
2. [系统架构](./02-architecture.md)
3. [数据库设计](./03-database.md)
4. [记忆系统](./04-memory.md)
5. [Agent 引擎](./05-agent.md)
6. [工具系统](./06-tools.md)
7. [技能系统](./07-skills.md)
8. [进化系统](./08-evolution.md)
9. [前端设计](./09-frontend.md)
10. [API 接口](./10-api.md)
11. [目录结构](./11-structure.md)
12. [实施计划](./12-plan.md)

---

## 核心技术参考

### Hermes Agent 参考点

| 模块 | Hermes 实现 | Sage 实现 |
|-----|------------|----------|
| 会话存储 | SQLite + FTS5 (`hermes_state.py`) | SQLite + FTS5 |
| 记忆管理 | `memory_manager.py`, `memory_provider.py` | 自研三层记忆 |
| 工具系统 | `toolsets.py`, `tools/registry.py` | `tools/registry.py` |
| 技能系统 | `skills/` 目录, `skill_commands.py` | `skills/` 目录 |
| Agent 核心 | `run_agent.py` (~12k LOC) | `agent.py` |
| CLI | `cli.py` (~11k LOC) | `cli.py` |

### Chatbox 参考点

| 模块 | Chatbox 实现 | Sage 实现 |
|-----|------------|----------|
| 桌面框架 | Electron | Tauri 1.x |
| 前端框架 | React 18 | React 18 |
| 构建工具 | electron-vite | Vite |
| 状态管理 | zustand | zustand |
| 会话管理 | `electron-store` | SQLite |
| UI 组件 | 自研组件 | 参考+自研 |
| 多语言 | i18next | i18next |

---

## 文档索引

各模块详细设计请阅读对应章节文档。
