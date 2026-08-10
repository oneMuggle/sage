# Sage 借鉴 pi / hermes-agent 功能增强方案

> **状态**: 计划（待评审）
> **日期**: 2026-08-07
> **作者**: Claude（基于深度对比 `/home/fz/project/pi` 与 `/home/fz/project/hermes-agent`）
> **目标分支**: `main`（Win7 LTS 按需 cherry-pick）
> **优先级原则**: 与现有架构（六边形 + FSD + Agent 协议层）解耦、可独立落地、不破坏 Win7 兼容性

---

## 0. TL;DR

参考 pi（coding-agent harness）与 hermes-agent（self-improving agent）的设计，结合 Sage 已具备的 M1-M6 生态扩展能力（Skills、三层记忆、Artifacts Panel、Office、MCP、Orchestration、Hooks、用量面板），从**新增能力 / 已有能力增强 / 工程化与生态**三个维度提炼 **14 项可落地建议**，按 ROI 排序分为 P0/P1/P2/P3 四档。

### 核心对照表

| 维度 | Sage 现状 | pi 借鉴 | hermes 借鉴 |
|---|---|---|---|
| 终端入口 | 仅 Electron GUI | CLI + TUI 优先 | CLI + 多端 gateway |
| 工具沙箱 | `workspace_root` 软隔离 | 容器/micro-VM 隔离 | 7 种 terminal backend |
| 自更新 | 无 | 离线 build script | `hermes update` |
| 跨端入口 | 无 | 无 | Telegram/Discord/Slack gateway |
| 定时任务 | M3 Scheduler（UI 内） | 无 | cron + 跨平台投递 |
| 轨迹导出 | 无 | 无 | OpenAI JSONL fine-tuning |
| 诊断 CLI | 无（仅运行时面板） | 无 | `hermes doctor` |
| 用户建模 | USER.md 单文档 | 无 | Honcho dialectic |
| 依赖固定 | `>=` | `==` + shrinkwrap | `uv` lock |
| 多模型 | LLM proxy（21 章） | 30+ provider 统一 | Nous Portal 聚合 |
| 供应链 | 基础 | lifecycle 白名单 | pin + audit |
| RFC 流程 | specs/ 单一形态 | RFC site | 无 |

### 阶段规划

| 阶段 | 周期 | 项目数 | 收益 |
|---|---|---|---|
| **Phase A 立即做** | 1-2 周 | 3 项 | 风险降低 + 用户痛点 |
| **Phase B 短中期** | 1-2 月 | 5 项 | 用户体验跃升 |
| **Phase C 中期** | 2-3 月 | 4 项 | 能力补全 |
| **Phase D 长期** | 持续 | 2 项 | 生态成熟 |

---

## 1. P0 优先级（Phase A — 1-2 周）

### 1.1 `sage doctor` 诊断 CLI

**参考**: hermes `hermes doctor` + Sage 06 诊断章节

**问题**: Win7 LTS 用户、conda/py38 误用、端口冲突、SQLite 权限等问题定位耗时。

**目标**:
- `python -m sage.doctor` 一键输出 CRITICAL/WARN/INFO 三级检查
- 检查项：conda 环境（py38 vs py311）、sage_backend 健康、SQLite 文件可写、`~/.sage/config` 完整性、端口 8765/1420 占用、conda vs py38 错用、关键目录权限

**涉及文件**:
- 新增 `backend/cli/doctor.py`
- 复用 `backend/services/health.py`（如有）
- 文档新增 `docs/technical/41-sage-doctor.md`

**实施步骤**:
- [ ] 设计 `Check` 协议（name / severity / run / message）
- [ ] 实现 8 项检查
- [ ] 输出格式：彩色分级（无 TTY 时退化为 `[CRITICAL]` 前缀）
- [ ] electron 启动前自动跑 doctor，结果写入启动日志
- [ ] 单测 10 个 case（环境错配 / 端口占用 / SQLite 锁 等）

**风险**: 低，纯只读诊断

### 1.2 容器化沙箱 backend（写操作工具隔离）

**参考**: pi containerization（Gondolin / Plain Docker / OpenShell 三模式）+ Sage ToolExecutionContext（PR #212 引入）

**问题**: `office_create`、`bash` 等写操作工具无进程/网络/凭据隔离；`office_create` 一旦被 LLM 误调，风险敞口大。

**目标**:
- 短期：在 ToolExecutionContext 加 `sandbox: "workspace_only" | "containerized" | "host"` 字段
- 中期：实现 Docker backend（默认不启用，需用户 opt-in）
- 文档：参考 pi 明确写"无沙箱 = 全权限"警告

**涉及文件**:
- `backend/core/legacy/agent.py`（ToolExecutionContext 扩展）
- 新增 `backend/sandbox/docker_backend.py`
- 新增 `backend/sandbox/protocol.py`（SandboxBackend Protocol）
- Settings → Security 新增"工具沙箱模式"选项

**实施步骤**:
- [ ] 定义 SandboxBackend Protocol
- [ ] 实现 LocalBackend（默认，行为不变）
- [ ] 实现 DockerBackend（用 `docker run --rm -v workspace:/workspace`）
- [ ] ToolExecutionContext 注入 sandbox 决策
- [ ] Settings UI + i18n + storage 字段
- [ ] 单测 20 个 + 集成测试 5 个

**风险**: 中。Docker 不可用的环境需 fail-open 到 local。需明确文档警告。

### 1.3 依赖固定与供应链加固

**参考**: pi `package-lock.json` + `.npmrc` (`save-exact=true`, `min-release-age=2`) + `npm-shrinkwrap.json` + lifecycle script 白名单

**问题**: `backend/requirements.txt` 用 `>=`（历史）；前端 `package.json` 未严格固定；Win7 LTS `requirements-py38.txt` 同理；新人 install 容易拉入当日新包。

**目标**:
- `requirements.txt` 改为 `==` 固定 + `requirements.in` 维护最小集 + `pip-compile` 生成 lockfile
- 前端 `package.json` 加 `.npmrc` 的 `save-exact=true`
- pre-commit hook 检测 lockfile 变更（参考 pi `PI_ALLOW_LOCKFILE_CHANGE=1` 逃生口）

**涉及文件**:
- `backend/requirements.in`（新增，最小集）
- `backend/requirements.txt`（改为 `==` 固定版本）
- `backend/requirements-py38.in` + `backend/requirements-py38.txt`（Win7 LTS）
- `.npmrc`（新增）
- `.pre-commit-config.yaml`（新增 `check-lockfile` hook）
- `docs/technical/15-quality-gates.md`（更新供应链章节）

**实施步骤**:
- [ ] 用 `pip-compile` 重新生成两个 lockfile（main + win7）
- [ ] 添加 `.npmrc`
- [ ] 添加 pre-commit hook
- [ ] CI 加一步 `pip-compile --check`（确保 lockfile 与 .in 同步）
- [ ] 文档更新 15 章

**风险**: 中。Pin 版本后升级需主动 workflow，但这就是目标。可在 CI 加一个 weekly `pip list --outdated` 报告。

---

## 2. P1 优先级（Phase B — 1-2 月）

### 2.1 跨平台消息网关（Telegram 优先）

**参考**: hermes gateway（Telegram/Discord/Slack/WhatsApp/Signal/Email 统一进程）

**问题**: Sage 仅 Electron 桌面，无远程入口；用户在 Win7 LTS 部署后无法远程触发。

**目标**:
- 新增 `backend/gateway/` 模块，复用 chat_stream_create NDJSON 协议
- 第一阶段：Telegram bot（最适合国内开发者）
- 后续：Discord/Slack/Webhook
- 复用 A24 session 树实现"手机端续接桌面会话"

**涉及文件**:
- 新增 `backend/gateway/`（telegram / discord / 抽象层）
- 新增 `backend/gateway/protocol.py`（MessagingBackend Protocol）
- 新增 `docs/technical/42-messaging-gateway.md`
- 新增用户手册章节 `docs/user-manual/09-telegram-gateway.md`

**实施步骤**:
- [ ] 设计 MessagingBackend Protocol（send / on_message / stream_reply）
- [ ] Telegram backend（用 `python-telegram-bot`）
- [ ] session 绑定：每个 telegram chat_id ↔ Sage session_id（SQLite 表）
- [ ] 流式输出：编辑同一条消息（telegram editMessageText）
- [ ] 图片/文件附件 → Artifacts Panel（PR #266）
- [ ] 单测 15 + 集成 5

**风险**: 中高。需用户配 bot token；流式响应在 telegram 限制下需要特殊处理。

### 2.2 定时任务 + 跨平台投递

**参考**: hermes cron + §2.1 gateway

**问题**: M3 Scheduler 已有，但只在 UI 内通知；长任务（30min+ 代码迁移）无远程感知。

**目标**:
- 在 M3 Scheduler 上加 `deliver_to: ["desktop_toast", "telegram", "email", "webhook"]` 字段
- 与 §2.1 gateway 共用投递层
- 典型场景：长任务完成时手机收到通知

**涉及文件**:
- 扩展 `backend/services/scheduler.py`（PR #75 M3 已合并）
- 复用 §2.1 gateway
- `docs/technical/35-session-compact-fork.md` 关联章节

**实施步骤**:
- [ ] Scheduler 表 schema 扩展 `deliver_to TEXT`
- [ ] 投递抽象 DeliveryChannel Protocol
- [ ] 集成 telegram（§2.1）/ desktop_toast（已有）/ email（SMTP）/ webhook（POST）
- [ ] UI 任务编辑表单加多选
- [ ] 单测 12 + 集成 4

**风险**: 中。投递失败需本地持久化（避免静默丢失），参考 hermes 的"持久重试队列"做法。

### 2.3 自更新通道

**参考**: hermes `hermes update` + pi SHA256SUMS + 离线 build

**问题**: NSIS/deb 包各自独立发布，无 in-app 检查；用户不知道有新版本。

**目标**:
- 加 `GET /api/v1/release/check?channel={stable|beta|alpha}&current_version=X.Y.Z` 端点
- 前端 Settings → About 显示"有新版本"提示，下载链接到 GitHub release
- 与现有 release tiers（chapter 30）天然契合

**涉及文件**:
- 新增 `backend/api/release_check.py`
- 复用 `backend/services/release_tiers.py`（如有）
- 前端 Settings → About 卡片
- 新增 `docs/user-manual/10-self-update.md`

**实施步骤**:
- [ ] GitHub Releases API 包装（无需 token，公开仓库）
- [ ] channel 过滤（稳定/beta/alpha/LTS）
- [ ] semver 比较（用 `packaging.version`）
- [ ] UI 提示 + "Download" 按钮（外部链接）
- [ ] 单测 10 + 集成 3

**风险**: 低。纯展示 + 跳转，不做自动下载/安装。

### 2.4 CLI 模式（终端入口）

**参考**: pi `coding-agent` CLI + textual / rich

**问题**: 服务器/远程场景（Win7 LTS 离线部署、SSH 远程办公、容器内）无法使用 GUI。

**目标**:
- 复用 `backend/core/legacy/agent.py` + `agent.run_loop`（已与 UI 解耦）
- 最小 CLI：`python -m sage.cli --workspace /path`
- 可选 TUI（textual）

**涉及文件**:
- 新增 `backend/cli/main.py`
- 复用 `agent.run_loop`、`memory_*`、`skills` 等
- 新增 `docs/technical/43-sage-cli.md`

**实施步骤**:
- [ ] 最小 CLI：read-eval-print + slash 命令（/new /compact /memory 等）
- [ ] NDJSON 输出（与 23 章 UI 协议同源）
- [ ] Win7 LTS 烟测（CI 加 step）
- [ ] 可选：textual TUI（差异化体验）
- [ ] 单测 10 + 集成 5

**风险**: 中。CLI 与 GUI 共用 agent loop 需重构部分 import 路径，避免 GUI-only 依赖。

### 2.5 跨会话 LLM 摘要召回

**参考**: hermes FTS5 + LLM summarization（"我上周让你做的 XX" 自然语言检索）

**问题**: 三层记忆（chapter 39）有结构化存储，但跨 session 自然语言召回的 LLM 摘要层缺失。

**目标**:
- 在 memory_search 之上加 memory_recall 工具
- FTS5 命中 → 取前 N 条 → LLM 生成 100 字摘要
- 配合 24 章 usage tracking，召回时附带"上次使用 X 是在 2026-08-01"

**涉及文件**:
- 新增 `backend/memory/recall.py`
- 扩展 `backend/tools/`（memory_recall 工具）
- `docs/technical/39-memory-user-profile.md` 关联章节

**实施步骤**:
- [ ] FTS5 召回（已存在）
- [ ] 上下文打包（top 5 条）
- [ ] LLM 摘要（Haiku 级别，控制成本）
- [ ] cache 24h（避免重复 LLM 调用）
- [ ] UI 展示
- [ ] 单测 10

**风险**: 低。复用现有 FTS5 + LLM proxy。

---

## 3. P2 优先级（Phase C — 2-3 月）

### 3.1 工具轨迹导出（fine-tuning 数据）

**参考**: hermes batch trajectory generation

**目标**:
- `backend/services/trajectory_exporter.py`：把 session_messages + tool_calls + results 序列化为 OpenAI/Anthropic fine-tuning JSONL
- Settings → Developer → "Export Trajectory (last N sessions)"
- 价值：用户用自己的真实工作流微调本地小模型（Qwen3.5-7B）

**涉及文件**:
- 新增 `backend/services/trajectory_exporter.py`
- 新增 `docs/technical/44-trajectory-export.md`

**实施步骤**:
- [ ] 消息 → JSONL 转换（OpenAI / Anthropic 两种 schema）
- [ ] 去敏（用户提示词可选择 redact）
- [ ] UI 导出按钮
- [ ] 单测 8

**风险**: 低。纯导出，无副作用。

### 3.2 self-extensible 边界设计

**参考**: pi "self-extensible" 卖点 + Sage Background Review（PR #273）

**问题**: Skills 系统支持 SKILL.md，但技能是用户定义的，不是 agent 自我修改。

**目标**（谨慎）:
- 增加 skill_create 工具：让 agent 在成功完成非平凡任务后，主动建议把 workflow 固化为 Skill
- 与 Background Review 联动：review 发现的高频模式可升级为 Skill 提案
- 明确边界：禁止 agent 修改自身 system prompt / tools 白名单（这些需 PR）

**涉及文件**:
- 扩展 `backend/skills/`
- 文档新增"Skill 提案审批"章节

**实施步骤**:
- [ ] skill_propose 工具（只生成 SKILL.md 草稿，不写入）
- [ ] 用户审批 UI（参考 §3.3 dialectic）
- [ ] 边界检查：禁止修改 system prompt / tools 白名单
- [ ] 单测 8

**风险**: 高。需谨慎设计"禁止修改"清单 + 人工审核。

### 3.3 用户建模 dialectic 升级

**参考**: hermes + Honcho dialectic user modeling

**问题**: USER.md 是静态快照（chapter 39）。

**目标**:
- 把 USER.md 拆为 USER.core.md（冻结）+ USER.working.md（动态）
- memory_consolidate 后台任务：每 N 次会话，把 working 与已有 core 做 dialectic 比对
- 用户审批后才 merge core

**涉及文件**:
- 扩展 `backend/memory/user_profile.py`
- `docs/technical/39-memory-user-profile.md` 重写

**实施步骤**:
- [ ] USER.md → core + working 双文件
- [ ] dialectic 流程（LLM 生成"建议更新"提案）
- [ ] UI 审批对话框
- [ ] 单测 10

**风险**: 中。dialectic 质量依赖 LLM，需 fallback。

### 3.4 工具网关统一订阅（未来商业化铺垫）

**参考**: hermes + Nous Portal

**问题**: 每个工具用户自己接 key。

**目标**:
- `backend/services/tool_gateway.py` 抽象层
- BUILTIN_TIER（免费/web 抓取）+ PREMIUM_TIER（聚合订阅）两档
- 与现有 LLM proxy（chapter 21）一脉相承

**涉及文件**:
- 新增 `backend/services/tool_gateway.py`
- `docs/technical/21-llm-proxy.md` 扩展

**实施步骤**:
- [ ] ToolProvider Protocol
- [ ] registry + 配置
- [ ] UI 订阅管理（占位，预留 API）

**风险**: 低（暂不实现真实订阅，留接口）。

---

## 4. P3 优先级（Phase D — 持续）

### 4.1 远端执行 backend（Docker/SSH）

**参考**: hermes 7 terminal backend

**目标**:
- 抽象 ExecutionBackend Protocol（local / docker / ssh）
- office_create、bash 等重型工具可路由到 docker backend
- 配合 §1.2 沙箱化

**涉及文件**:
- 新增 `backend/sandbox/remote_backend.py`
- `docs/technical/41-sandbox.md`（与 §1.2 合并）

**实施步骤**:
- [ ] Protocol 抽象
- [ ] Docker / SSH 实现
- [ ] UI 配置入口

**风险**: 中。SSH 凭据管理需谨慎。

### 4.2 RFC 流程

**参考**: pi rfc.earendil.com

**目标**:
- 把 specs/ 拆为 rfcs/（提案）+ specs/（已批准）
- 大决策走 RFC：写作期 → review → 接受/拒绝

**涉及文件**:
- 新增 `docs/rfcs/README.md`
- 现有 specs 迁移

**实施步骤**:
- [ ] 目录迁移
- [ ] RFC 模板
- [ ] 评审流程文档

**风险**: 低（流程改进）。

---

## 5. 不建议抄的部分

| 项目 | 原因 |
|---|---|
| hermes "agent 完全开放改自己" | 风险大（误删 system prompt），Sage 应保留审批 |
| pi "无内置权限系统，靠沙箱" | 国内用户不友好，Sage 应保留细粒度 workspace policy |
| hermes 7 种 terminal backend | Serverless 平台（Modal/Daytona）需信用卡，国内落地难 |
| hermes 全开放 Discord/Telegram | 需明确隐私边界（截图/消息可被三方平台索引） |

---

## 6. 风险评估总表

| 项 | 技术风险 | 产品价值 | 推荐指数 |
|---|---|---|---|
| §1.1 sage doctor | 低 | 中 | 5/5 |
| §1.2 沙箱 backend | 中 | 高 | 5/5 |
| §1.3 依赖固定 | 中 | 中（长期） | 4/5 |
| §2.1 消息网关 | 中高 | 高 | 5/5 |
| §2.2 任务投递 | 中 | 中高 | 4/5 |
| §2.3 自更新 | 低 | 中 | 4/5 |
| §2.4 CLI 模式 | 中 | 中 | 4/5 |
| §2.5 跨会话召回 | 低 | 中 | 3/5 |
| §3.1 轨迹导出 | 低 | 低（长期） | 3/5 |
| §3.2 self-extensible | 高 | 中 | 2/5 |
| §3.3 dialectic | 中 | 中 | 3/5 |
| §3.4 工具网关 | 低 | 低（未来） | 2/5 |
| §4.1 远端 backend | 中 | 低 | 2/5 |
| §4.2 RFC 流程 | 低 | 中（长期） | 3/5 |

---

## 7. 实施路线图

```
Week 1-2  (§1.1 doctor + §1.3 依赖固定)     — 立即收益
Week 3-6  (§1.2 沙箱 backend)              — 风险降低
Week 7-12 (§2.1 消息网关 + §2.2 投递)       — 体验跃升
Week 13-16(§2.3 自更新 + §2.4 CLI)         — 入口补全
Week 17-24(§2.5 召回 + §3.1 轨迹导出)      — 能力深化
Long-term (§3.2-4.2)                       — 生态成熟
```

---

## 8. 验收标准

每个 P0/P1 项目完成后：

- [ ] 单测覆盖率 ≥ 80%
- [ ] 集成测试通过
- [ ] Win7 LTS（Py3.8 / pydantic 1.x）兼容性已验证
- [ ] 文档同步更新（技术专题 + 用户手册）
- [ ] 已入 §1.3 依赖锁定
- [ ] 一份 CHANGELOG 条目

---

## 9. 后续动作

1. **本计划评审**：用户阅读本文档，对优先级提出调整
2. **拆分为独立 plan**：每个 P0/P1 项目单独写一份 `docs/plans/YYYY-MM-DD_<feature>.md`
3. **建 feature 分支**：按 feature-branch-workflow.md 走分支
4. **同步到 release/win7**：按 CLAUDE.md 的 cherry-pick 规则选择性同步
