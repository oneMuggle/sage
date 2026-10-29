# 智能模型路由 + 渐进式 UI 披露设计方案

> **版本**: 1.0  
> **日期**: 2026-10-28  
> **状态**: 设计中（待用户审查）  
> **分支**: feat/smart-model-routing

---

## 1. 背景与目标

### 1.1 背景

Sage 当前的模型配置和模型目录功能存在以下问题：

- **用户体验差**：模型选择器只显示 `modelId · endpointName`，不显示上下文长度、价格、能力等关键信息
- **功能复杂但价值未体现**：用户需要手动配置参数（context length、temperature），但缺乏自动化支持
- **数据断裂**：后端已有完整的 model_catalog 模块（7 张表、REST API、layer 解析），但前端未充分利用
- **离线场景支持不足**：win7 分支部署到内网，无法访问互联网，需要预存模型数据

用户反馈："当前功能基本没怎么用"，意味着现有 UI 体验差，用户避免使用。这是重构的最佳时机。

### 1.2 目标

设计并实现一个**智能模型路由系统**，配合**渐进式 UI 披露**，达到以下效果：

1. **智能路由**：根据任务类型、上下文长度、模型能力自动选择最佳模型（类似 Claude Code 的 Haiku/Sonnet/Opus 自动选择）
2. **渐进式披露**：模型选择器默认简洁（模型名 + 能力图标），悬停/展开显示详细元数据
3. **离线优先**：预存 50-100 个主流模型的完整数据，支持内网部署
4. **统一数据流**：消除 `discoveredModels` 和 `catalog entries` 的双系统，统一使用 catalog 作为唯一数据源

### 1.3 成功标准

- 用户无需手动选择模型（默认"自动选择"模式）
- 模型选择器信息密度提升（显示 context/price/capabilities）
- 模型目录页面可用（卡片视图 + tier 标签 + 过滤/排序）
- 离线场景可用（builtin.json 包含 50-100 模型）
- 重构不破坏现有功能（向后兼容）

---

## 2. 现状分析

### 2.1 当前架构

**后端**：
- `backend/model_catalog/` 模块完整（schemas.py, repository.py, seed.py, probes.py, resolver.py 等）
- 7 张 SQLite 表：entries, bindings, probes, overrides, override_generations, snapshots, snapshot_items
- REST API：`/api/v1/model-catalog/*`（models, effective, overrides, probe, sync/openrouter, snapshots）
- Layer 解析：`user_override > service_probe > imported_snapshot > builtin > unknown`

**前端**：
- `src/pages/settings/ModelsTab.tsx`：模型选择设置（手动输入参数）
- `src/pages/settings/EndpointsTab.tsx`：端点配置（自动发现模型）
- `src/widgets/chat/SessionModelPicker.tsx`：会话级模型切换
- `src/pages/ModelCatalog.tsx`：模型目录管理页（表格视图）

**数据流**：
```
端点连接测试 → discoveredModels（前端 localStorage）
                          ↓
              ModelsTab 手动选择 → modelSelections
                          ↓
              SessionModelPicker 覆盖 → session_model_overrides
                          ↓
              llm_factory.py 解析 → LLM 客户端

catalog entries（后端 SQLite）
                          ↓
              resolver.py layer 解析 → effective model
                          ↓
              chat_request_policy.py → 上下文窗口
```

### 2.2 痛点

| 痛点 | 描述 | 影响 |
|------|------|------|
| **信息密度不足** | 模型选择器只显示 `modelId`，不显示 context/price/capabilities | 用户无法做出明智选择 |
| **能力推断粗糙** | `inferCapabilities()` 靠模型名猜测（`includes('vision')`） | 错误的模型推荐 |
| **双系统数据断裂** | `discoveredModels`（前端）和 `catalog entries`（后端）不互通 | 数据不一致 |
| **catalog 数据未反哺** | catalog 有丰富数据但选择器不用 | 数据浪费 |
| **autoContext 概念复杂** | 用户需理解"自动推断" vs "固定值"的区别 | 用户体验差 |
| **离线数据不足** | builtin.json 只有 17 个模型 | 内网部署场景模型选择有限 |
| **无智能路由** | 用户需手动选择模型，无自动化支持 | 决策疲劳 |

### 2.3 竞品参考

| 产品 | 做法 | 可借鉴 |
|------|------|--------|
| **Claude Code** | 基于任务类型自动选择 Haiku/Sonnet/Opus | 智能路由 |
| **ChatGPT** | auto-router（曾移除后恢复），模型名 + 简短描述 | 简洁 UI |
| **Claude** | tier-based 选择（Opus/Sonnet/Haiku），渐进式披露 | 分层展示 |
| **OpenRouter** | 模型卡片 + 过滤/排序/对比，丰富的元数据 | 模型目录 |
| **Poe** | 能力图标标签（👁 Vision 🔧 Tools），多模型对比 | 能力展示 |

---

## 3. 设计方案（方案 A+）

### 3.1 核心概念

**方案 A+ = 智能路由 + 渐进式披露 + 离线优先**

三个核心机制：

1. **模型 Tier 系统**：为每个模型分配 tier（fast/balanced/powerful）
2. **智能路由引擎**：基于任务类型/上下文/能力自动选择模型
3. **渐进式 UI 披露**：默认简洁，悬停/展开显示详细信息

### 3.2 模型 Tier 系统

#### 3.2.1 Tier 定义

| Tier | 定位 | 典型模型 | 适用场景 |
|------|------|---------|---------|
| **fast** | 快速便宜 | Haiku, GPT-4o-mini, Llama-3-8B, Qwen-2-7B | 简单对话、快速回答、低延迟需求 |
| **balanced** | 平衡 | Sonnet, GPT-4o, Llama-3-70B, Qwen-2-72B | 代码生成、中等复杂度任务 |
| **powerful** | 强大 | Opus, GPT-4-turbo, Claude-3.5-Sonnet | 复杂分析、架构设计、深度推理 |

#### 3.2.2 Tier 分配策略

**优先级**：
1. 用户显式覆盖（override）
2. builtin.json 预存 tier
3. OpenRouter 同步数据（如果有）
4. 基于模型名推断（fallback）

**推断规则**（fallback）：
```python
def infer_tier(model_id: str) -> str:
    model_id_lower = model_id.lower()
    
    # Powerful tier
    if any(x in model_id_lower for x in ['opus', 'gpt-4-turbo', 'claude-3.5', 'o1']):
        return 'powerful'
    
    # Balanced tier
    if any(x in model_id_lower for x in ['sonnet', 'gpt-4', 'gpt-3.5-turbo', 'llama-3-70b', 'qwen-2-72b']):
        return 'balanced'
    
    # Fast tier (default)
    return 'fast'
```

#### 3.2.3 数据模型扩展

**后端 Schema 扩展**（`backend/model_catalog/schemas.py`）：

```python
class CandidateModel(BaseModel):
    provider: str
    model_id: str
    tier: Optional[str] = None  # 新增：'fast' | 'balanced' | 'powerful'
    native_context_window: Optional[int] = None
    capabilities: Optional[List[str]] = None  # 'chat' | 'vision' | 'embedding' | 'tool_use'
    pricing: Optional[Pricing] = None
    # ... 其他字段

class EffectiveModel(CandidateModel):
    # 继承 CandidateModel，增加 layer 解析后的确定值
    tier: str  # 必须（解析后一定有值）
```

**前端类型扩展**（`src/entities/model-catalog/types.ts`）：

```typescript
type ModelTier = 'fast' | 'balanced' | 'powerful';

interface CatalogModel {
  provider: string;
  modelId: string;
  tier: ModelTier;
  nativeContextWindow?: number;
  capabilities?: string[];
  pricing?: {
    inputPerMillion: string;
    outputPerMillion: string;
  };
}
```

### 3.3 智能路由引擎

#### 3.3.1 路由决策因素

```
路由决策 = f(任务类型, 上下文长度, 模型能力, 用户偏好, 端点可用性)
```

| 因素 | 权重 | 说明 |
|------|------|------|
| **任务类型** | 高 | coding → balanced/powerful；chat → fast |
| **上下文长度** | 高 | >32K → 需要长上下文模型 |
| **模型能力** | 中 | vision 任务需要 vision 模型 |
| **用户偏好** | 中 | 用户可锁定特定 tier 或模型 |
| **端点可用性** | 高 | 只考虑已配置 apiKey 的端点 |

#### 3.3.2 路由规则

**规则 1：任务类型 → Tier 映射**

```python
TASK_TYPE_TO_TIER = {
    'simple_chat': 'fast',
    'code_generation': 'balanced',
    'code_review': 'powerful',
    'analysis': 'powerful',
    'writing': 'balanced',
    'translation': 'fast',
    'summarization': 'balanced',
}
```

**规则 2：上下文长度 → 模型过滤**

```python
def filter_by_context(models: List[CatalogModel], required_context: int) -> List[CatalogModel]:
    return [m for m in models if m.native_context_window >= required_context]
```

**规则 3：能力匹配**

```python
def filter_by_capability(models: List[CatalogModel], required_capability: str) -> List[CatalogModel]:
    return [m for m in models if required_capability in m.capabilities]
```

**规则 4：Tier 优先级**

```python
def select_by_tier(models: List[CatalogModel], preferred_tier: str) -> CatalogModel:
    # 优先选择 preferred_tier，否则降级
    tier_priority = ['balanced', 'fast', 'powerful']  # 默认优先 balanced
    
    for tier in tier_priority:
        tier_models = [m for m in models if m.tier == tier]
        if tier_models:
            return tier_models[0]
    
    return models[0]  # 兜底
```

#### 3.3.3 路由引擎实现

**新增文件**：`backend/routing/routing_engine.py`

```python
class RoutingEngine:
    def __init__(self, catalog_repository: ModelCatalogRepository):
        self.catalog = catalog_repository
    
    def route(
        self,
        task_type: str,
        context_length: int,
        required_capabilities: List[str],
        user_preference: Optional[RoutingPreference] = None,
    ) -> RoutingResult:
        """
        根据任务需求选择最佳模型
        
        Returns:
            RoutingResult: 包含 selected_model, reason, alternatives
        """
        # 1. 获取所有可用模型（已配置 apiKey 的端点）
        available_models = self._get_available_models()
        
        # 2. 过滤：上下文长度
        filtered = filter_by_context(available_models, context_length)
        
        # 3. 过滤：能力匹配
        for cap in required_capabilities:
            filtered = filter_by_capability(filtered, cap)
        
        # 4. 用户偏好检查
        if user_preference and user_preference.locked_model:
            return RoutingResult(
                selected_model=user_preference.locked_model,
                reason="用户已锁定模型",
                alternatives=filtered[:3]
            )
        
        # 5. 确定目标 tier
        preferred_tier = TASK_TYPE_TO_TIER.get(task_type, 'balanced')
        if user_preference and user_preference.preferred_tier:
            preferred_tier = user_preference.preferred_tier
        
        # 6. 选择模型
        selected = select_by_tier(filtered, preferred_tier)
        
        # 7. 生成路由理由
        reason = f"已为 {task_type} 选择 {selected.tier} 模型"
        
        return RoutingResult(
            selected_model=selected,
            reason=reason,
            alternatives=filtered[:3]
        )
    
    def _get_available_models(self) -> List[EffectiveModel]:
        """获取所有可用模型（已配置 apiKey 的端点）"""
        # 从 catalog 读取 effective 模型
        # 只返回有 apiKey 的端点的模型
        pass
```

#### 3.3.4 路由结果

```python
class RoutingResult(BaseModel):
    selected_model: EffectiveModel
    reason: str  # "已为 code_generation 选择 balanced 模型 (Sonnet)"
    alternatives: List[EffectiveModel]  # 前 3 个备选
```

### 3.4 渐进式 UI 披露

#### 3.4.1 模型选择器改造

**SessionModelPicker 改造**：

```
┌─────────────────────────────────────┐
│  🤖 已选择 GPT-4o (balanced) 👁 🔧 │
│     └─ 悬停显示：                   │
│        Context: 128K                │
│        Price: $2.50 / $10.00        │
│        Capabilities: chat, vision   │
└─────────────────────────────────────┘

点击展开 ↓

┌─────────────────────────────────────┐
│  当前模型                            │
│  ┌───────────────────────────────┐  │
│  │ GPT-4o (balanced) 👁 🔧       │  │
│  │ Context: 128K                 │  │
│  │ Price: $2.50 / $10.00         │  │
│  │ Capabilities: chat, vision    │  │
│  └───────────────────────────────┘  │
│                                      │
│  切换模型                            │
│  ┌─ Fast ──────────────────────┐    │
│  │ • GPT-4o-mini               │    │
│  │ • Haiku                     │    │
│  │ • Llama-3-8B                │    │
│  └─────────────────────────────┘    │
│  ┌─ Balanced ──────────────────┐    │
│  │ • GPT-4o ✓                  │    │
│  │ • Sonnet                    │    │
│  │ • Llama-3-70B               │    │
│  └─────────────────────────────┘    │
│  ┌─ Powerful ──────────────────┐    │
│  │ • Opus                      │    │
│  │ • GPT-4-turbo               │    │
│  └─────────────────────────────┘    │
│                                      │
│  [自动选择] [手动锁定]               │
└─────────────────────────────────────┘
```

**关键设计**：
- 默认显示"自动选择"模式，显示当前选择的模型 + 路由理由
- 悬停 tooltip 显示详细信息（context/price/capabilities）
- 点击展开显示 tier 分组列表
- 用户可切换到"手动锁定"模式，手动选择模型

#### 3.4.2 模型目录重构

**双视图切换**：

```
┌──────────────────────────────────────┐
│  模型目录                            │
│                                      │
│  [🔍 搜索] [过滤 ▼] [排序 ▼]        │
│  [📋 表格] [🎴 卡片]  ← 视图切换    │
│                                      │
│  ┌─ 卡片视图 ──────────────────────┐│
│  │                                  ││
│  │ ┌──────────┐ ┌──────────┐       ││
│  │ │ GPT-4o   │ │ Sonnet   │       ││
│  │ │ balanced │ │ balanced │       ││
│  │ │ 👁 🔧    │ │ 🔧       │       ││
│  │ │ 128K     │ │ 200K     │       ││
│  │ │ $2.5/$10 │ │ $3/$15   │       ││
│  │ └──────────┘ └──────────┘       ││
│  │                                  ││
│  │ ┌──────────┐ ┌──────────┐       ││
│  │ │ Haiku    │ │ Opus     │       ││
│  │ │ fast     │ │ powerful │       ││
│  │ │ 👁 🔧    │ │ 🔧       │       ││
│  │ │ 200K     │ │ 200K     │       ││
│  │ │ $0.25/$1 │ │ $15/$75  │       ││
│  │ └──────────┘ └──────────┘       ││
│  │                                  ││
│  └──────────────────────────────────┘│
│                                      │
│  [高级 ▼]  ← 折叠区域               │
│  ┌────────────────────────────────┐ │
│  │ • 导入 Bundle                  │ │
│  │ • 同步 OpenRouter              │ │
│  │ • 管理 Override                │ │
│  └────────────────────────────────┘ │
└──────────────────────────────────────┘
```

**关键设计**：
- 默认卡片视图（视觉吸引力）
- 每个卡片显示：模型名、tier、能力图标、context、price
- 过滤/排序：按 tier、provider、capabilities、context、price
- 高级功能折叠（导入/同步/override）

#### 3.4.3 设置页面简化

**ModelsTab 改造**：

```
┌──────────────────────────────────────┐
│  模型设置                            │
│                                      │
│  ┌─ 路由模式 ────────────────────┐  │
│  │ • 自动选择（推荐）            │  │
│  │   根据任务类型自动选择最佳模型  │  │
│  │ • 手动选择                    │  │
│  │   手动指定每个能力的模型        │  │
│  └───────────────────────────────┘  │
│                                      │
│  [自动选择模式]                      │
│  ┌─ 默认偏好 ────────────────────┐  │
│  │ 默认 Tier: [balanced ▼]       │  │
│  │ 任务类型映射:                  │  │
│  │   简单对话 → fast              │  │
│  │   代码生成 → balanced          │  │
│  │   复杂分析 → powerful          │  │
│  └───────────────────────────────┘  │
│                                      │
│  [手动选择模式]                      │
│  ┌─ 按能力选择 ──────────────────┐  │
│  │ 对话模型: [GPT-4o ▼]          │  │
│  │ 视觉模型: [GPT-4o ▼]          │  │
│  │ 嵌入模型: [text-embedding ▼]  │  │
│  └───────────────────────────────┘  │
│                                      │
│  ┌─ 高级设置 ────────────────────┐  │
│  │ 自动推断上下文窗口: [✓]       │  │
│  │ Temperature: [0.7]            │  │
│  │ 会话标题模型: [GPT-4o-mini ▼] │  │
│  └───────────────────────────────┘  │
└──────────────────────────────────────┘
```

**关键设计**：
- 默认"自动选择"模式（推荐）
- 手动模式保留现有功能
- 高级设置折叠

### 3.5 离线数据策略

#### 3.5.1 混合方案

**三层数据源**：

1. **builtin.json 扩展**（50-100 模型）
   - 覆盖主流模型：OpenAI/Anthropic/Google/Meta/Mistral/Qwen
   - 包含完整数据：tier + context + price + capabilities
   - 每次发版时手动更新

2. **Bundle 导入机制**（保留）
   - 管理员在外网导出 OpenRouter 数据为 bundle
   - 内网用户导入 bundle 更新本地 catalog
   - REST API：`POST /api/v1/model-catalog/snapshots/import`

3. **端点探测增强**（补充）
   - 扩展 probe 机制支持更多协议
   - 用户添加端点时自动探测并填充 catalog

#### 3.5.2 builtin.json 扩展计划

**目标**：从 17 个模型扩展到 50-100 个

**模型清单**（示例）：

```json
[
  {
    "provider": "openai",
    "model_id": "gpt-4o",
    "tier": "balanced",
    "native_context_window": 128000,
    "capabilities": ["chat", "vision", "tool_use"],
    "pricing": {
      "input_per_million": "2.50",
      "output_per_million": "10.00"
    }
  },
  {
    "provider": "anthropic",
    "model_id": "claude-3-5-sonnet-20241022",
    "tier": "balanced",
    "native_context_window": 200000,
    "capabilities": ["chat", "vision", "tool_use"],
    "pricing": {
      "input_per_million": "3.00",
      "output_per_million": "15.00"
    }
  },
  {
    "provider": "anthropic",
    "model_id": "claude-3-haiku-20240307",
    "tier": "fast",
    "native_context_window": 200000,
    "capabilities": ["chat", "vision"],
    "pricing": {
      "input_per_million": "0.25",
      "output_per_million": "1.25"
    }
  }
]
```

#### 3.5.3 数据更新流程

**发版时更新**：
1. 维护者在外网运行脚本：`python scripts/update_builtin_models.py`
2. 脚本调用 OpenRouter API 获取最新模型列表
3. 自动分配 tier（基于模型名推断）
4. 生成新的 builtin.json
5. 提交 PR，review 后合并

**内网用户更新**：
1. 管理员在外网导出 bundle：`POST /api/v1/model-catalog/snapshots/export`
2. 将 bundle 文件传输到内网
3. 内网用户导入：`POST /api/v1/model-catalog/snapshots/import`

### 3.6 数据流统一

#### 3.6.1 当前数据流（双系统）

```
端点连接测试 → discoveredModels（前端 localStorage）
                          ↓
              ModelsTab 手动选择 → modelSelections
                          ↓
              SessionModelPicker 覆盖 → session_model_overrides
                          ↓
              llm_factory.py 解析 → LLM 客户端

catalog entries（后端 SQLite）
                          ↓
              resolver.py layer 解析 → effective model
                          ↓
              chat_request_policy.py → 上下文窗口
```

**问题**：`discoveredModels` 和 `catalog entries` 不互通

#### 3.6.2 新数据流（单一数据源）

```
端点连接测试 → 自动创建 catalog entry（如果不存在）
                          ↓
              catalog entries（后端 SQLite，唯一数据源）
                          ↓
              resolver.py layer 解析 → effective model
                          ↓
              routing_engine.py 路由选择 → selected model
                          ↓
              llm_factory.py 装配 → LLM 客户端

前端 UI：
  - SessionModelPicker 读取 catalog effective 数据
  - ModelCatalog 读取 catalog 数据
  - ModelsTab 读取 catalog 数据
```

**关键变化**：
- 移除 `discoveredModels`（前端）
- 端点发现直接写入 catalog（后端）
- 所有 UI 读取 catalog effective 数据

#### 3.6.3 迁移策略

**向后兼容**：
1. 保留 `discoveredModels` 字段（deprecated）
2. 启动时自动迁移到 catalog
3. 前端读取时优先使用 catalog，fallback 到 `discoveredModels`
4. 3 个月后移除 `discoveredModels`

---

## 4. 技术架构

### 4.1 后端架构

```
backend/
├─ model_catalog/
│  ├─ schemas.py              # 扩展 tier 字段
│  ├─ repository.py           # 无变化
│  ├─ seed.py                 # 加载扩展后的 builtin.json
│  ├─ resolver.py             # 无变化
│  └─ ...
│
├─ routing/                   # 新增模块
│  ├─ __init__.py
│  ├─ routing_engine.py       # 智能路由引擎
│  ├─ routing_rules.py        # 路由规则定义
│  └─ task_classifier.py      # 任务类型分类器（可选）
│
├─ api/
│  ├─ model_catalog_routes.py # 无变化
│  └─ routing_routes.py       # 新增：路由 API
│
└─ orchestration/
   └─ llm_factory.py          # 集成路由引擎
```

### 4.2 前端架构

```
src/
├─ entities/
│  ├─ model-catalog/
│  │  ├─ types.ts             # 扩展 tier 类型
│  │  └─ api.ts               # 无变化
│  │
│  └─ routing/                # 新增
│     ├─ types.ts             # RoutingResult 类型
│     └─ api.ts               # 路由 API 客户端
│
├─ widgets/
│  ├─ chat/
│  │  └─ SessionModelPicker.tsx  # 重构：自动选择 + tier 分组
│  │
│  ├─ model-catalog/
│  │  ├─ CatalogTable.tsx      # 保留，增加列
│  │  ├─ CatalogCards.tsx      # 新增：卡片视图
│  │  └─ ModelDetails.tsx      # 保留
│  │
│  └─ welcome/
│     └─ ModelPicker.tsx       # 重构：同 SessionModelPicker
│
└─ pages/
   ├─ settings/
   │  └─ ModelsTab.tsx         # 重构：自动选择 + 手动选择
   │
   └─ ModelCatalog.tsx        # 重构：双视图 + 高级折叠
```

### 4.3 API 设计

**新增 API**：

```
POST /api/v1/routing/route
Request:
{
  "task_type": "code_generation",
  "context_length": 8000,
  "required_capabilities": ["chat", "tool_use"],
  "user_preference": {
    "preferred_tier": "balanced",
    "locked_model": null
  }
}

Response:
{
  "selected_model": {
    "provider": "openai",
    "model_id": "gpt-4o",
    "tier": "balanced",
    "native_context_window": 128000,
    "capabilities": ["chat", "vision", "tool_use"]
  },
  "reason": "已为 code_generation 选择 balanced 模型",
  "alternatives": [
    {"provider": "anthropic", "model_id": "claude-3-5-sonnet-20241022", ...},
    {"provider": "openai", "model_id": "gpt-4o-mini", ...}
  ]
}
```

---

## 5. 实施步骤

### Phase 1：后端基础（1 周）

**目标**：完成模型 tier 系统和路由引擎

**任务**：
1. 扩展 `backend/model_catalog/schemas.py`，增加 tier 字段
2. 扩展 `backend/builtin.json`，添加 tier 信息（50 模型）
3. 实现 `backend/routing/routing_engine.py`
4. 实现 `backend/routing/routing_rules.py`
5. 实现 `backend/api/routing_routes.py`
6. 集成到 `backend/orchestration/llm_factory.py`
7. 编写单元测试（覆盖路由逻辑）

**交付物**：
- ✅ 后端 API 可用：`POST /api/v1/routing/route`
- ✅ 单元测试覆盖 80%+

### Phase 2：前端模型选择器（1 周）

**目标**：改造 SessionModelPicker 和 ModelPicker

**任务**：
1. 重构 `src/widgets/chat/SessionModelPicker.tsx`
   - 增加"自动选择"模式
   - 显示路由理由
   - 悬停 tooltip 显示详细信息
   - 展开显示 tier 分组列表
2. 重构 `src/widgets/welcome/ModelPicker.tsx`（同上）
3. 实现 `src/entities/routing/api.ts`
4. 编写前端测试

**交付物**：
- ✅ 模型选择器支持自动选择
- ✅ 显示 tier 分组和详细信息

### Phase 3：前端模型目录（1 周）

**目标**：重构模型目录页面

**任务**：
1. 实现 `src/widgets/model-catalog/CatalogCards.tsx`（卡片视图）
2. 重构 `src/pages/ModelCatalog.tsx`
   - 双视图切换（表格/卡片）
   - 过滤/排序功能
   - 高级功能折叠
3. 编写前端测试

**交付物**：
- ✅ 模型目录支持卡片视图
- ✅ 高级功能折叠

### Phase 4：前端设置页面（0.5 周）

**目标**：简化设置页面

**任务**：
1. 重构 `src/pages/settings/ModelsTab.tsx`
   - 增加"自动选择"模式
   - 默认偏好设置
   - 高级设置折叠
2. 编写前端测试

**交付物**：
- ✅ 设置页面支持自动选择模式

### Phase 5：数据流统一（0.5 周）

**目标**：统一数据流，移除双系统

**任务**：
1. 端点发现时自动创建 catalog entry
2. 前端读取 catalog effective 数据
3. 迁移逻辑（`discoveredModels` → catalog）
4. 编写集成测试

**交付物**：
- ✅ 单一数据源（catalog）
- ✅ 向后兼容

### Phase 6：离线数据丰富（持续）

**目标**：扩展 builtin.json

**任务**：
1. 编写 `scripts/update_builtin_models.py`
2. 扩展 builtin.json 到 100 模型
3. 建立更新流程（发版时运行脚本）

**交付物**：
- ✅ builtin.json 包含 100 模型
- ✅ 更新脚本可用

**总计**：4 周

---

## 6. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **路由引擎性能问题** | 中 | 高 | 路由结果缓存（5 分钟 TTL） |
| **tier 推断不准确** | 高 | 中 | 允许用户 override，持续优化规则 |
| **数据迁移破坏现有功能** | 中 | 高 | 向后兼容，保留 fallback |
| **离线数据不足** | 中 | 中 | 提供 bundle 导入机制 |
| **UI 改动影响用户体验** | 中 | 中 | 渐进式上线，A/B 测试 |

---

## 7. 附录

### 7.1 参考资源

- [Claude Code 模型选择策略](https://docs.anthropic.com/en/docs/claude-code)
- [OpenRouter 模型目录](https://openrouter.ai/models)
- [ChatGPT Model Picker](https://chat.openai.com/)
- [Sage 现有 model_catalog 模块](backend/model_catalog/)
- [Sage 模型目录设计文档](2026-09-15-model-catalog-design.md)

### 7.2 术语表

| 术语 | 定义 |
|------|------|
| **Tier** | 模型层级（fast/balanced/powerful） |
| **Routing** | 根据任务需求自动选择模型 |
| **Progressive Disclosure** | 渐进式披露（默认简洁，展开显示详情） |
| **Effective Model** | Layer 解析后的确定模型 |
| **Bundle** | 可移植的模型数据打包（SHA-256 签名） |

---

**文档结束**
