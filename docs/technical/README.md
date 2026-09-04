# 技术专题文档总览

> Sage 各技术专题的深入文档。本目录补充 [`../README.md`](../README.md) 中核心章节（01-14），聚焦质量门禁、可观测性、架构约束等横切关注点。当前专题编号为 15-44；本索引以目录中的实际文件为准。

---

## 章节目录

| 编号 | 标题                                                 | 一句话简介                                                                                            |
| ---- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 15   | [质量门禁](./15-quality-gates.md)                    | CI / pre-commit / pre-push / 工具链版本与质量阈值                                                     |
| 16   | [可观测性](./16-observability.md)                    | OpenTelemetry tracer / Prometheus 9 指标 / 审计 jsonl                                                 |
| 17   | [前端质量](./17-frontend-quality.md)                 | FSD 架构 / 测试覆盖 / a11y 状态                                                                       |
| 18   | [六边形架构](./18-hexagonal.md)                      | 五层职责 / 6 个 Protocol / 双轨策略 / import-linter 约束                                              |
| 19   | [ghm 外部计算集成](./19-ghm-integration.md)          | LLM 工具调用桥接 ghm CLI / ExecutableResolver / HTTP 升级预留                                         |
| 20   | [Electron 21 桌面壳](./20-electron.md)               | Tauri → Electron 21 迁移理由 / 7 个 Win7 启动开关 / CI 流水线 / Phase 5 真机烟测 SOP                  |
| 31   | [Win7 LTS 维护](./31-win7-lts.md)                    | 18 个月归档时间表 / Win7 用户 Web 化迁移 / 真机烟测 SOP / 风险声明                                    |
| 21   | [LLM 代理路由](./21-llm-proxy.md)                    | `/api/v1/llm/*` 透传上游,绕开浏览器到 Ollama/OpenAI 的 CORS 拦截                                      |
| 22   | [Agents CRUD 端到端](./22-agents-crud.md)            | list/update/toggle 三层链路 (后端路由 → Electron IPC → 前端 API → UI)                                 |
| 23   | [Chat 流式响应端到端](./23-chat-streaming.md)        | NDJSON 协议 + Electron IPC event 桥接 + NDJSON relay + chatStream 中间态文案                          |
| 24   | [Skills 系统端到端](./24-skills-system.md)           | InprocSkillAdapter + 9 个 Skills API 端点 + 4 builtin + SKILL.md v2（gating/scripts/dispatch/slash command）+ 使用跟踪/Nudge |
| 25   | [LLM Wiki 集成 (PR-8)](./25-llm-wiki-integration.md) | 4 LLM provider 抽象 + prompt 模板 + LanceDB RAG + 知识图谱 8 阶段实施                                 |
| 26   | [跨平台打包矩阵](./26-packaging-matrix.md)            | Win7/10/11 NSIS + VCRedist bundling 与 Ubuntu deb 覆盖,用户安装指南                                  |
| 27   | [多 Agent 编排层 (M1 typed 化)](./27-multi-agent-orchestration.md) | 12 条 PolicyEngine 规则 + Report schema v1 + Approval token 8 项校验门（参考 claw-code）               |
| 28   | [SKILL.md Spec Conformance (agentskills.io)](./28-skill-md-spec-conformance.md) | backend/skills/skill_md/ 全规范对齐:license/compatibility/allowed-tools + 长度校验 + 单文件形态             |
| 29   | [Electron 桌面日志](./29-electron-logging.md)         | 三层日志架构 / NDJSON 格式 / 路径与保留策略 / Win7 启动失败排查流程                                       |
| 30   | [Release Tiers（发布档位分级）](./30-release-tiers.md) | 4 档分级 (alpha/beta/RC/stable) + SemVer 预发布段 + Win7 LTS 派生 + 升档脚本与流程                            |
| 32   | [Settings Schema 规范化](./32-settings-canonicalization.md) | 后端 canonicalizer snake↔camel 翻译 + AppSettings 白名单 + 前端 deepMerge + 历史 snake 数据兼容             |
| 33   | [Office M1–M2 完整收尾](./33-office-m1-m2-completion.md) | session-bound Workspace + ChatOfficeRef 透传 + office_list/read 工具 + Electron→Python stub E2E            |
| 34   | [MCP 多服务器管理 (M3)](./34-mcp-multi-server.md)    | 多服务器 JSON 配置合并 + 同步池并行发现/故障隔离/重连 + 降级状态报告 + /api/v1/mcp/* + Settings MCP Tab     |
| 35   | [会话工程：压缩 + 分叉 (M4)](./35-session-compact-fork.md) | 上下文压缩（手动 /compact + 请求层自动阈值）+ 会话分叉全量前缀复制 + sessions 表 fork 两列幂等迁移           |
| 36   | [编排端到端 (M5)](./36-orchestration-e2e.md)        | Planner LLM 注入 + POST /orchestration/lanes + 循环内 agent 子代理（白名单 + 300s 超时 + run_in_executor 卸载）|
| 37   | [生态扩展 (M6)](./37-ecosystem-extensions.md)      | Hooks（pre/post 工具执行）+ 用量/成本面板 + SAGE.md/CLAUDE.md 项目上下文发现 + i18n 清扫 + 零依赖 mock LLM parity harness |
| 38   | [Artifacts Panel（产物面板）](./38-artifacts-panel.md) | Chat 右侧抽屉双 Tab：AI 工具调用进度 + write_file 产物追踪/多格式预览/文件管理器定位                                       |
| 39   | [记忆系统与用户画像](./39-memory-user-profile.md) | 三层记忆（Working/Episodic/Semantic）+ RRF 融合 + UserProfileStore(USER.md) 冻结快照/分类路由/core 独立预算 |
| 40   | [代码探索工具三件套](./40-code-exploration-tools.md) | grep_search / glob_search / file_summary：primary agent 工具白名单扩展 + ast 解析 + ReDoS 缓解 |
| 41   | [sage doctor](./41-sage-doctor.md) | 安装/环境级 self-check CLI：8 项检查（conda env / backend health / SQLite writable / config integrity / ports / py version / disk space）+ 退出码 0/1/2 + electron 启动前自动跑（5s 超时，fail-open） |
| 42   | [Chat-Native Multi-Agent Orchestration](./42-chat-multi-agent-orchestration.md) | 聊天链路多 agent 编排：语义判定 + tool-toggle 门 + ChatDispatcher 拓扑分波调度（depends_on/级联取消）+ task_plan/task_status/todo_snapshot 事件 + 前端任务树与 todo 清单镜像 + output_schema 结构化返回/followup 续聊/worktree 隔离（默认关）/LaneBoard 快照激活 |
| 43   | [§1.2 事件循环门禁升级](./43-event-loop-gate.md) | 单点 P99 → 5 轮 P99 中位数门禁：阈值演进 50→100→200→150→400ms 设计历史 + 抗抖动/回归敏感权衡 |
| 44   | [bash 命令行工具](./44-bash-tool.md) | 对齐 Claude Code Bash tool：放开 shell 操作符（危险判定收敛到 bash_validation + PermissionEnforcer）+ 后台执行三工具（bash/bash_output/kill_shell）+ 30 KiB 有界输出 + 进程组回收 + 跨平台 shell 探测（Git Bash / PowerShell 降级） |
| 45   | [渐进式功能披露](./44-progressive-disclosure.md) | sticky-unlock 存储、受门控入口及 `/skills` 始终可发现的设计边界 |
| 46   | [Sage 品牌图标资产与复用](./45-brand-icons.md) | 品牌主形象（几何 S + 星点 + 青紫渐变）的资产层级、`<BrandLogo>` 共享组件规范、macOS `.icns` 缺口与未来补全路径 |
| 47   | [内网 Web 访问（网络模式门禁 + 取页下载）](./46-intranet-web-access.md) | NetworkPolicy 三档门禁 + host 白名单通配 + web_fetch 四 mode + http_download 边界约束 + 不变量 |
| 48   | [Git Worktree 并行开发](./47-git-worktree-workflow.md) | `scripts/worktree.sh` helper（new/list/ports/remove/clean）+ `.worktrees/` 端口分配机制 + main/release-win7 并行 cherry-pick 场景 + 与 `.claude/worktrees/` agent 隔离的边界 |
| 48   | [Office CRUD 闭环完成](./48-office-crud-completion.md) | 2026-09 PR-1..5：profile 白名单接通 + archive/restore + pre-edit snapshot + chat @filename 兜底 + re-read 元数据保留 + write_file 二进制黑名单 + win7 同步；闭环增删改查 + chat ref + 二进制防护 + win7 兼容 |
| 49   | [本地开发环境助手](./49-local-development-assistant.md) | 运行时探测 + 项目诊断 + 安全执行：`backend/domain` + 3 tools + `/api/v1/runtime/*` + Electron IPC + Settings 开发环境 Tab + humanize 渲染 + doctor check |

---

## 与核心章节的关系

| 关注层     | 文档                                                        |
| ---------- | ----------------------------------------------------------- |
| 用户价值层 | [01 概述](../01-overview.md) — [12 实施计划](../12-plan.md) |
| 横切关注点 | 本目录（15-44）                                             |

---

_本目录文档命名规则：`XX-topic-name.md`（XX 为两位数字，topic-name 为 kebab-case）。_
