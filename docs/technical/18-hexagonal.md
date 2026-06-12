# 18. 六边形架构（Hexagonal Architecture）

**最后更新**：2026-06-06
**阶段**：P2 完工
**适用版本**：Sage 全栈质量优化 v0.1

## 18.1 概述

Sage 后端从单体 `core/` 迁移到六边形架构（Ports & Adapters），实现"业务与技术分离"。本章节描述五层职责、六个 Protocol 接口、双轨策略与依赖约束。

## 18.2 五层架构

| 层          | 路径                    | 职责                                                     | 不可 import                  |
| ----------- | ----------------------- | -------------------------------------------------------- | ---------------------------- |
| domain      | `backend/domain/`       | 纯领域模型（AgentState、Message、ToolSpec、LLMError 等） | 任何上层                     |
| ports       | `backend/ports/`        | 6 个 Protocol 接口                                       | adapters / application / api |
| application | `backend/application/`  | 用例编排（ChatService）                                  | adapters / api               |
| adapters    | `backend/adapters/out/` | 端口的具体实现（httpx/sqlite/inproc 等）                 | api                          |
| api         | `backend/api/`          | HTTP 路由（hex + legacy 双轨）                           | （顶层）                     |

## 18.3 6 个 Protocol 接口

| Port        | 方法                          | 生产 adapter                | Mock adapter           |
| ----------- | ----------------------------- | --------------------------- | ---------------------- |
| LLMPort     | `chat / chat_stream`          | `HttpxLLMAdapter`           | `MockLLMAdapter`       |
| ToolPort    | `list_tools / execute`        | `InprocToolAdapter`         | —                      |
| SkillPort   | `list_skills / execute`       | `InprocSkillAdapter` (PR-7) | —                      |
| StoragePort | 5 个会话/消息方法             | `SqliteStorageAdapter`      | `MemoryStorageAdapter` |
| MetricPort  | `counter / histogram / gauge` | `PrometheusMetricAdapter`   | `NoopMetricAdapter`    |
| EventPort   | `emit`                        | `FileEventAdapter`          | `StdoutEventAdapter`   |

## 18.4 双轨策略

```
api/routes.py  (dispatcher, 26 行)
   ├── API_MODE=hex（默认）→ api/hex_routes.py → ChatService → ports
   └── API_MODE=legacy      → api/legacy_routes.py → core/legacy/SageAgent
```

- **hex 模式**：新六边形路径。`/chat` 由 `hex_routes` 接管，其他端点转发给 legacy（避免破坏现有 509 测试）
- **legacy 模式**：旧路径完全回滚。`core/legacy/{agent,llm_client,orchestrator,agent_state}.py` 仍可独立工作
- 切换：通过 `API_MODE` 环境变量（默认 `hex`）

## 18.5 依赖约束（import-linter）

`backend/pyproject.toml` 配置 `importlinter.contracts.hexagonal-architecture`：

- api → adapters, application, ports, domain
- adapters → application, ports, domain
- application → ports, domain
- ports → domain
- domain → （最底层）

**0 violations**（实测）。

`backend/core/legacy/` 与 `backend/main.py` 故意不在声明的 5 层中：前者是双轨安全网，后者是 composition root。

## 18.6 测试覆盖

| 层                                   | 覆盖率       | 备注                                 |
| ------------------------------------ | ------------ | ------------------------------------ |
| domain/                              | 100%         | 35 个测试覆盖所有 dataclass + 状态机 |
| ports/                               | 100%         | 15 个测试验证 Protocol 结构          |
| application/services/chat_service.py | 96%          | 7 个测试覆盖 run_turn 主路径         |
| adapters/                            | 100% (15/16) | sqlite_adapter 33% (error 分支)      |
| api/hex_routes.py                    | 75%          | 1 个集成测试                         |
| api/legacy_routes.py                 | 83%          | 集成测试覆盖                         |

**整体 87%**（远超 80% 门禁）。

## 18.7 切换与回滚

```bash
# 切回旧路径（一键回滚）
cd backend
API_MODE=legacy pytest  # 509 + 3 skip

# 切回新路径（默认）
pytest                  # 507 + 5 skip（hex 接管 /chat）
```

CI 工作流同时跑两个路径（hex 强制覆盖率门禁，legacy 冒烟）。

## 18.8 已知遗留

- `core/legacy/` 在 5 层架构外，import-linter 不监控；后续 P3/P4 如清理可在 CI 加 dead code 检测
- `adapters/sqlite_adapter.py` 33% 覆盖率（error 分支），PG3 加更多错误场景测试
- `domain/` 中 `LLMError` 仍被 `core/legacy/errors.py` 镜像定义（避免双 import 圈）；统一时机：P3
