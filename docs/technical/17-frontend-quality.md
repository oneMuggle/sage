# 17. 前端质量（Frontend Quality）

**最后更新**：2026-06-06
**阶段**：P1 完工
**适用版本**：Sage 全栈质量优化 v0.1

## 17.1 概述

Sage 前端（React + TypeScript + Vite）当前阶段质量基线：

- **测试**：53/53 通过（vitest）
- **覆盖率**：features 87.72%，entities 91.18%，widgets 51.43%
- **FSD 架构**：7 层物理隔离 + 边界规则 enforcement
- **Lint**：ESLint 9 flat config，0 FSD 违规

## 17.2 FSD 架构

### 七层目录

| 层        | 路径             | 职责                  | 不可 import                                                |
| --------- | ---------------- | --------------------- | ---------------------------------------------------------- |
| app       | `src/app/`       | 入口、Provider        | processes / pages / widgets / features / entities / shared |
| processes | `src/processes/` | 跨页长流程（P1 留空） | —                                                          |
| pages     | `src/pages/`     | 路由级页面            | app                                                        |
| widgets   | `src/widgets/`   | 复合 UI               | pages / app / processes                                    |
| features  | `src/features/`  | 用户场景              | widgets / pages / app / processes                          |
| entities  | `src/entities/`  | 业务实体 + store      | features / widgets / pages / app / processes               |
| shared    | `src/shared/`    | 通用代码              | **任何上层**                                               |

### 边界规则

由 `eslint-plugin-import` 的 `import/no-restricted-paths` 实现（`eslint.config.js`）。任何逆向 import 立即 fail。

## 17.3 测试

### 工具链

- `vitest 4.1.8` + `@vitest/coverage-v8`
- `@testing-library/react 16.3.2`
- 配置文件：`vite.config.ts`（test 字段）

### 当前测试覆盖

| 层       | 文件数 | 覆盖率 | 主要测试目标                                        |
| -------- | ------ | ------ | --------------------------------------------------- |
| entities | 2      | 91.18% | storage / store                                     |
| features | 2      | 87.72% | useChat / useSettings                               |
| widgets  | 4      | 51.43% | AgentCard / MemoryItem / SkillCard / MessageList    |
| lib      | 4      | n/a    | apiErrorMapping / llmStream / logger / errorMapping |

## 17.4 a11y 状态（P3 待完善）

| 检查项             | 当前状态      | P3 目标    |
| ------------------ | ------------- | ---------- |
| 错误/加载/重试统一 | ❌            | ✅         |
| 键盘可达性         | ❌            | ✅         |
| 焦点环             | ⚠️ 浏览器默认 | ✅ 自定义  |
| 颜色对比度         | ❌ 未审       | ✅ ≥ 4.5:1 |
| 语义化结构         | ⚠️ 部分       | ✅         |
| 表单 label 关联    | ⚠️ 部分       | ✅         |
| 跳过链接           | ❌            | ✅         |
| Lighthouse 评分    | 未测          | ≥ 95       |

## 17.5 已知遗留（P2/P3 收尾）

| ID     | 描述                                                                                                      | 阶段 |
| ------ | --------------------------------------------------------------------------------------------------------- | ---- |
| PG0-2  | 3 条 ESLint pre-existing 错误（`useEndpoints.ts`、`useKnowledge.ts`、`lib/api.ts`）                       | P2   |
| PG1-L1 | `src/components/` 仍有 legacy 目录（layout / session / common）                                           | P2   |
| PG1-L2 | `src/components/wiki/`、`src/components/skills/`、`src/components/agents/`、`src/components/memory/` 目录 | P2   |
| PG1-L3 | `lib/store.ts` 跨实体未拆分                                                                               | P2   |
| PG1-L4 | ErrorBoundary / LoadingState / RetryButton / Skeleton 共享组件未建                                        | P3   |
| PG1-L5 | 9 个共享组件 + 5 页面 a11y 改造                                                                           | P3   |
