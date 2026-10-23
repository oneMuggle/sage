# Harness 自进化系统设计方案

> **创建日期**: 2026-10-21
> **状态**: Draft
> **分支**: `feat/harness-evolution`
> **对标参考**: DeepSeek Harness (Cordis) + Google Harness 2 (RSI)

## 1. 背景与目标

### 1.1 背景

2026-10 月，两个重量级 harness 框架先后发布：

| 框架 | 核心思想 | 关键创新 |
|---|---|---|
| **DeepSeek Harness** | Everything-is-a-plugin | Cordis 插件树 + Capability seams + HMR |
| **Google Harness 2** | Recursive Self-Improvement | Propose–Probe–Compose + 两层递归 |

两者代表同一方向的两条路径：
- **DeepSeek**：把"可扩展性"做到极致——一切可替换
- **Google**：把"自我优化"做到极致——harness 自动进化

行业共识：**Agent = Model + Harness**，模型权重不变，优化 harness。

### 1.2 Sage 现状

已有基础（详见 `docs/technical/33-self-evolution.md`）：
- ✅ 六边形架构：6 个 Protocol 接口（LLMPort / ToolPort / SkillPort 等）
- ✅ 学习闭环：记忆抽取 + 技能学习 + 巡检维护 + 偏好学习
- ✅ Skills 系统：SKILL.md + Loader gating + ScriptRunner

缺失能力：
- ❌ Harness 组件可观测性：无 effectiveness tracking
- ❌ 热替换机制（HMR）：改组件需重启后端
- ❌ 自动优化闭环：技能改进仍需人工审批

### 1.3 目标

**总目标**：让 Sage 具备 harness 自进化能力，在保持"人工审批"哲学差异点的前提下，引入数据驱动的自动优化机制。

**分阶段目标**：
1. **阶段 1（可观测）**：harness 8 个组件显式化 + effectiveness 量化
2. **阶段 2（可替换）**：运行时热替换 harness 组件（HMR）
3. **阶段 3（可进化）**：Propose–Probe–Compose 自动优化闭环

## 2. 涉及的文件与模块

### 2.1 后端（Python）

| 模块 | 现有文件 | 新增/改动 |
|---|---|---|
| Domain | `backend/domain/` | 新增 `harness_component.py`（HarnessComponent dataclass） |
| Ports | `backend/ports/` | 新增 `harness_port.py`（HarnessPort Protocol） |
| Application | `backend/application/services/` | 新增 `harness_service.py`（HarnessService 用例）<br>新增 `harness_recorder.py`（HarnessRecorder / HarnessProbe 埋点） |
| Adapters | `backend/adapters/out/harness/` | 新增 `sqlite_adapter.py`（SqliteHarnessAdapter） |
| API | `backend/api/harness_routes.py` | 新增 `/api/v1/harness/*` 路由（独立路由模块，未并入 `hex_routes.py`） |
| Database | `backend/data/database.py` | 新增 `harness_components` / `harness_improvements` 表 |
| Assembly | `backend/main.py` | lifespan 内装配 `SqliteHarnessAdapter` + `HarnessRecorder` |
| 埋点接入 | `backend/core/legacy/agent.py`<br>`backend/adapters/out/tool/inproc_adapter.py`<br>`backend/tools/skill_tool.py` | 用 `HarnessProbe` 包裹工具 / 技能执行链 |
| Skills | `backend/skills/` | 阶段 2（M14）再扩展 SKILL.md frontmatter |

### 2.2 前端（React/TypeScript）

> Sage 前端采用 **FSD 分层**（`entities` / `features` / `widgets` / `pages` / `shared`），
> 方案初稿里的 `src/types/` `src/api/` `src/components/` 目录在仓库中并不存在，
> 落地时按 FSD 约定归位。

| 模块 | 目录 | 新增/改动 |
|---|---|---|
| Types | `src/entities/harness/types.ts` | HarnessComponent / EffectivenessMetrics 类型 + 类型中文标签表 |
| API | `src/shared/api/harnessApi.ts` | harness API client（走 `backendRequest` Electron IPC 桥，含 demo 模式桩） |
| UI | `src/widgets/harness/HarnessDashboard.tsx` | 组件 effectiveness 可视化（调用次数 / 成功率 / 延迟 / 满意度 + 待改进标记 + 类型筛选） |
| Settings | `src/pages/settings/Settings.tsx`<br>`settingsNavigation.ts`<br>`settingsSearchIndex.ts` | 注册 `harness` tab（tab key + 导航可见性 + 渲染分支） |
| i18n | `src/shared/lib/i18n/locales/{zh,en}/chatAndSider.ts` | `settings.tab.harness`（zh/en 必须同步改，否则 `tsc` 失败） |

### 2.3 测试

| 层 | 文件 |
|---|---|
| Unit (backend) | `backend/tests/unit/test_harness.py`（35 个用例：domain / adapter / service / recorder / probe） |
| Unit (frontend) | `src/widgets/harness/__tests__/HarnessDashboard.test.tsx`（8 个用例） |
| Integration | 阶段 2 随 HMR 路由一并补 |
| E2E | 阶段 2 随 `HarnessTab` 一并补 |

## 3. 技术方案

### 3.1 Harness 8 组件模型

参考 Google Harness 2，定义 Sage 的 8 个 harness 组件：

| 组件 | Sage 对应 | 当前实现位置 | 可替换性 |
|---|---|---|---|
| **system_prompt** | System prompt 组装 | `backend/core/legacy/agent.py:system_prompt` | 段落级可配置 |
| **guardrails** | 安全守卫 | `backend/core/legacy/agent.py:guardrails` | 规则级可配置 |
| **memory** | 记忆系统 | `backend/services/memory.py` | 适配器级可替换 |
| **tool_guidance** | 工具描述 | `backend/tools/*.py` docstring | 描述级可配置 |
| **subagents** | 子代理编排 | `backend/services/orchestration.py` | 策略级可配置 |
| **skills** | 技能系统 | `backend/skills/` | 完整 SKILL.md |
| **scripts** | 脚本工具 | `backend/tools/bash_tool.py` | 白名单可配置 |
| **plugins** | 扩展插件 | 无（新增） | 全新机制 |

### 3.2 阶段 1：Harness 可观测

#### 3.2.1 数据模型

```python
# backend/domain/harness_component.py

from dataclasses import dataclass
from typing import Literal

HarnessComponentType = Literal[
    "system_prompt", "guardrails", "memory", "tool_guidance",
    "subagents", "skills", "scripts", "plugins"
]

@dataclass(frozen=True)
class HarnessComponent:
    id: str  # e.g., "skill:academic-search"
    type: HarnessComponentType
    name: str
    version: str
    config: dict  # 组件配置（JSON）
    effectiveness: EffectivenessMetrics
    created_at: str
    updated_at: str

@dataclass(frozen=True)
class EffectivenessMetrics:
    usage_count: int  # 调用次数
    success_rate: float  # 成功率 [0, 1]
    avg_latency_ms: float  # 平均延迟
    user_satisfaction: float | None  # 用户满意度 [0, 1]，可选
    last_used_at: str | None  # 最后使用时间
```

#### 3.2.2 数据库表

```sql
-- backend/data/database.py

CREATE TABLE IF NOT EXISTS harness_components (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN (
        'system_prompt', 'guardrails', 'memory', 'tool_guidance',
        'subagents', 'skills', 'scripts', 'plugins'
    )),
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    config_json TEXT NOT NULL DEFAULT '{}',
    usage_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    total_latency_ms REAL NOT NULL DEFAULT 0.0,
    user_satisfaction_sum REAL NOT NULL DEFAULT 0.0,
    user_satisfaction_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS harness_improvements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id TEXT NOT NULL REFERENCES harness_components(id),
    proposal_json TEXT NOT NULL,  # 改进提案（JSON）
    probe_result_json TEXT,       # 测试结果（JSON）
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected', 'rolled_back')),
    evidence_json TEXT,           # 改进证据（JSON）
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at TEXT,
    rolled_back_at TEXT
);
```

#### 3.2.3 API 设计

```
GET    /api/v1/harness/components              # 列出所有 harness 组件（?type= 过滤）
GET    /api/v1/harness/components/:id          # 获取单个组件详情
POST   /api/v1/harness/components              # 登记新组件（201）
POST   /api/v1/harness/components/:id/record   # 记录一次使用（effectiveness tracking）
GET    /api/v1/harness/needing-improvement     # 列出触发改进阈值的组件
```

> 阶段 1 只实现只读 + 登记 + 埋点。以下写操作属于阶段 2（HMR），
> 阶段 3 再补改进提案的审批链路：
>
> ```
> PATCH  /api/v1/harness/components/:id           # 更新组件配置（不重启）— M12
> GET    /api/v1/harness/improvements             # 列出改进提案 — M23
> POST   /api/v1/harness/improvements             # 创建改进提案 — M23
> POST   /api/v1/harness/improvements/:id/approve # 审批通过 — M23
> POST   /api/v1/harness/improvements/:id/reject  # 审批拒绝 — M23
> POST   /api/v1/harness/improvements/:id/rollback# 回滚 — M23
> ```

### 3.3 阶段 2：Harness 热替换（HMR）

#### 3.3.1 机制设计

```python
# backend/ports/harness_port.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class HarnessPort(Protocol):
    """Harness 组件管理端口"""
    
    async def list_components(self) -> list[HarnessComponent]:
        ...
    
    async def get_component(self, component_id: str) -> HarnessComponent | None:
        ...
    
    async def update_component(self, component_id: str, config: dict) -> HarnessComponent:
        """热更新组件配置，不重启后端"""
        ...
    
    async def record_usage(
        self, component_id: str, success: bool, latency_ms: float
    ) -> None:
        """记录一次使用，更新 effectiveness 指标"""
        ...
```

#### 3.3.2 HMR 通知机制

```python
# backend/application/services/harness_service.py

class HarnessService:
    def __init__(self, harness_port: HarnessPort, event_port: EventPort):
        self._harness = harness_port
        self._events = event_port
    
    async def update_component(self, component_id: str, config: dict) -> HarnessComponent:
        # 1. 验证配置合法性
        validated = self._validate_config(component_id, config)
        
        # 2. 持久化到数据库
        component = await self._harness.update_component(component_id, validated)
        
        # 3. 发送 HMR 通知（前端 + 其他监听者）
        await self._events.emit("harness:component_updated", {
            "component_id": component_id,
            "version": component.version,
            "timestamp": datetime.now().isoformat()
        })
        
        return component
```

#### 3.3.3 前端订阅

```typescript
// src/shared/api/harnessApi.ts

export function subscribeToHarnessUpdates(
  onUpdated: (component: HarnessComponent) => void
): () => void {
  // 通过 Electron IPC 或 SSE 订阅 harness:component_updated 事件
  // 返回 unsubscribe 函数
}
```

### 3.4 阶段 3：Harness 自动优化闭环

#### 3.4.1 Propose–Probe–Compose 流程

```python
# backend/application/services/harness_improver.py

class HarnessImprover:
    """参考 Harness 2 的 Propose–Probe–Compose"""
    
    async def propose_improvements(
        self, component_id: str
    ) -> list[ImprovementProposal]:
        """
        基于 effectiveness 数据，LLM 提出改进候选
        """
        component = await self._harness.get_component(component_id)
        metrics = component.effectiveness
        
        # 如果成功率 < 0.8 或延迟 > 1000ms，触发改进
        if metrics.success_rate < 0.8 or metrics.avg_latency_ms > 1000:
            proposals = await self._llm_propose(component, metrics)
            return proposals
        return []
    
    async def probe_proposal(
        self, proposal: ImprovementProposal
    ) -> ProbeResult:
        """
        在隔离环境测试改进效果（对比式）
        """
        # 1. 创建临时组件副本
        test_component = self._create_test_copy(proposal.component_id)
        
        # 2. 应用改进
        await test_component.apply(proposal.config_changes)
        
        # 3. 跑 N 次测试任务，对比 effectiveness
        baseline = await self._measure_baseline(proposal.component_id, n=10)
        improved = await self._measure_improved(test_component, n=10)
        
        # 4. 对比式评估（无需 ground-truth）
        if improved.success_rate > baseline.success_rate * 1.1:
            return ProbeResult(status="success", evidence=improved)
        return ProbeResult(status="failed", evidence=improved)
    
    async def compose_improvements(
        self, proposals: list[ImprovementProposal]
    ) -> ImprovementPlan:
        """
        选择改进组合，生成改进计划
        """
        # 选成功率最高的 top-k 改进
        successful = [p for p in proposals if p.probe_result.status == "success"]
        top_k = sorted(successful, key=lambda p: p.probe_result.score, reverse=True)[:3]
        
        return ImprovementPlan(proposals=top_k)
```

#### 3.4.2 人工审批保留

```python
# 自动优化闭环的结果仍进入 ReviewQueue（保留"人工审批"哲学差异点）

async def submit_for_review(self, plan: ImprovementPlan) -> None:
    """
    自动优化闭环的结果，仍需人工审批
    """
    await self._review_queue.submit(
        type="harness_improvement",
        payload=plan.to_dict(),
        priority="medium",
        evidence=plan.evidence  # 附带 Propose–Probe–Compose 的证据
    )
```

## 4. 实施步骤

### 4.1 阶段 1：Harness 可观测（0.5-1 周）

- [x] **M1**: Domain 层 — 定义 `HarnessComponent` / `EffectivenessMetrics` dataclass
- [x] **M2**: Database 层 — 新增 `harness_components` / `harness_improvements` 表
- [x] **M3**: Ports 层 — 定义 `HarnessPort` Protocol
- [x] **M4**: Adapters 层 — 实现 `SqliteHarnessAdapter`
- [x] **M5**: Application 层 — 实现 `HarnessService`（list / get / record_usage）
- [x] **M6**: API 层 — 实现 `/api/v1/harness/*` 路由（只读 + record_usage）
- [x] **M7**: 集成 — 在现有工具/技能调用链中埋点 `record_usage`
- [x] **M8**: 测试 — unit 测试覆盖（backend 35 例 + frontend 8 例）
- [x] **M9**: 前端 — `HarnessDashboard` 组件（effectiveness 可视化 + 设置页 `harness` tab）

**交付物**：harness 组件 effectiveness 看板，可在前端查看每个组件的使用情况

### 4.2 阶段 2：Harness 热替换（1-2 周）

- [ ] **M10**: Application 层 — `HarnessService.update_component` 方法
- [ ] **M11**: Event 层 — `harness:component_updated` 事件发布
- [ ] **M12**: API 层 — `PATCH /api/v1/harness/components/:id` 路由
- [ ] **M13**: 前端 — `subscribeToHarnessUpdates` 订阅机制
- [ ] **M14**: Skills 系统 — SKILL.md frontmatter 扩展 `effectiveness` 字段
- [ ] **M15**: System prompt — 段落级可配置（从硬编码迁移到数据库）
- [ ] **M16**: Tool guidance — 工具描述可配置（从 docstring 迁移到数据库）
- [ ] **M17**: 测试 — HMR 端到端测试（改配置 → 立即生效 → 回滚）
- [ ] **M18**: 前端 — `HarnessTab` 设置页（管理 harness 组件）

**交付物**：运行时修改 harness 组件配置，无需重启后端，有回滚机制

### 4.3 阶段 3：Harness 自动优化闭环（2-4 周）

- [ ] **M19**: Application 层 — `HarnessImprover` service（Propose–Probe–Compose）
- [ ] **M20**: Cron 层 — 每周六触发 `HarnessImprover.propose_improvements`
- [ ] **M21**: Integration — 与 `ReviewQueue` 集成（自动提交改进提案）
- [ ] **M22**: Database 层 — `harness_improvements` 表记录改进证据
- [ ] **M23**: API 层 — 改进提案审批 API（approve / reject / rollback）
- [ ] **M24**: 前端 — 改进提案审批 UI（在 `HarnessDashboard` 中）
- [ ] **M25**: 测试 — 自动优化闭环端到端测试
- [ ] **M26**: 文档 — 更新 `docs/technical/33-self-evolution.md`

**交付物**：harness 自动优化闭环，人工审批保留，有完整的 evidence chain

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|---|---|---|---|
| **legacy 代码阻碍 HMR** | 高 | 高 | 阶段 2 前必须先收尾 hex/legacy 双轨 |
| **effectiveness 数据不准** | 中 | 中 | 阶段 1 先做数据验证，加数据质量监控 |
| **自动优化引入 regression** | 中 | 高 | 保留人工审批，改进必须有 evidence |
| **性能开销** | 低 | 中 | record_usage 异步化，不阻塞主路径 |

### 5.2 依赖

| 依赖 | 状态 | 说明 |
|---|---|---|
| hex 架构收尾 | 未完成 | 阶段 2 的 HMR 需要 composition root 干净 |
| Skills 系统 v2 | 已完成 | 阶段 1 可直接扩展 |
| ReviewQueue | 已完成 | 阶段 3 可直接集成 |
| EventPort | 已完成 | 阶段 2 可直接使用 |

### 5.3 与 hermes-agent 的差异化

Sage 的"人工审批"哲学差异点**保留**，但在阶段 3 引入"自动提交 + 人工审批"模式：
- 自动优化闭环的结果进入 ReviewQueue
- 人工仍有一票否决权
- 改进提案必须附带 evidence（Propose–Probe–Compose 的对比数据）

这是与 Harness 2 全自动模式的关键差异，也是 Sage 的安全护栏。

## 6. 成功标准

| 阶段 | 成功标准 |
|---|---|
| 阶段 1 | 前端可查看 harness 8 个组件的 effectiveness 指标 |
| 阶段 2 | 运行时修改 harness 组件配置，无需重启后端，有回滚机制 |
| 阶段 3 | 自动优化闭环运行，人工审批保留，有完整的 evidence chain |

## 7. 时间线

| 阶段 | 预估时间 | 依赖 |
|---|---|---|
| 阶段 1 | 0.5-1 周 | 无 |
| 阶段 2 | 1-2 周 | 阶段 1 完成 + hex 架构收尾 |
| 阶段 3 | 2-4 周 | 阶段 2 完成 |

**总时间线**：4-7 周

---

**下一步**：从阶段 1 开始实施，先输出 Domain 层 dataclass 定义。
