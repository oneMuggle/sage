# 智能模型路由实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现智能模型路由系统，根据任务类型自动选择最佳模型，配合渐进式 UI 披露优化用户体验

**Architecture:** 后端新增路由引擎模块（`backend/routing/`），前端重构模型选择器（`SessionModelPicker`）和模型目录（`ModelCatalog`），支持 tier-based 自动选择和渐进式信息披露

**Tech Stack:** Python 3.10 (FastAPI), TypeScript (React), SQLite, Pydantic v1/v2 兼容

**Spec:** `docs/superpowers/specs/2026-10-28-smart-model-routing-design.md`

## Global Constraints

- Python 环境：必须使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`
- 端口：后端 8784（worktree），前端 1439（worktree）
- Pydantic：v1/v2 兼容（release/win7 用 v1，main 用 v2）
- 向后兼容：保留 `discoveredModels` 字段（deprecated），3 个月后移除
- 离线优先：builtin.json 必须包含 50-100 个模型的完整数据

---

## Phase 1：后端基础（1 周）

### Task 1：扩展 Schema 增加 Tier 字段

**Files:**
- Modify: `backend/model_catalog/schemas.py:15-45`
- Test: `backend/tests/unit/test_model_catalog_schemas.py`

**Interfaces:**
- Consumes: 现有 `CandidateModel` schema
- Produces: `CandidateModel` 增加 `tier: Optional[str]` 字段，`EffectiveModel` 的 `tier: str` 变为必须

- [ ] **Step 1: 读取现有 schema 定义**

```bash
cd /home/fz/project/sage/.worktrees/feat-smart-model-routing
/home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.model_catalog.schemas import CandidateModel; print(CandidateModel.__fields__.keys())"
```

- [ ] **Step 2: 编写失败测试**

创建 `backend/tests/unit/test_model_catalog_schemas.py`：

```python
import pytest
from backend.model_catalog.schemas import CandidateModel, EffectiveModel

def test_candidate_model_accepts_tier():
    model = CandidateModel(
        provider="openai",
        model_id="gpt-4o",
        tier="balanced",
        native_context_window=128000,
    )
    assert model.tier == "balanced"

def test_candidate_model_tier_optional():
    model = CandidateModel(
        provider="openai",
        model_id="gpt-4o",
        native_context_window=128000,
    )
    assert model.tier is None

def test_effective_model_requires_tier():
    model = EffectiveModel(
        provider="openai",
        model_id="gpt-4o",
        tier="balanced",
        native_context_window=128000,
    )
    assert model.tier == "balanced"

def test_effective_model_without_tier_raises():
    with pytest.raises(ValueError):
        EffectiveModel(
            provider="openai",
            model_id="gpt-4o",
            native_context_window=128000,
        )
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-smart-model-routing
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_model_catalog_schemas.py -v
```

Expected: FAIL（`tier` 字段不存在）

- [ ] **Step 4: 修改 schema 增加 tier 字段**

编辑 `backend/model_catalog/schemas.py`，在 `CandidateModel` 类中增加：

```python
class CandidateModel(BaseModel):
    provider: str
    model_id: str
    tier: Optional[str] = None  # 新增：'fast' | 'balanced' | 'powerful'
    native_context_window: Optional[int] = None
    # ... 其他字段保持不变
```

在 `EffectiveModel` 类中修改：

```python
class EffectiveModel(CandidateModel):
    tier: str  # 必须（解析后一定有值）
```

- [ ] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_model_catalog_schemas.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage/.worktrees/feat-smart-model-routing
git add backend/model_catalog/schemas.py backend/tests/unit/test_model_catalog_schemas.py
git commit -m "feat(model-catalog): add tier field to CandidateModel and EffectiveModel

- tier: Optional[str] in CandidateModel (fast/balanced/powerful)
- tier: str (required) in EffectiveModel
- Supports smart routing based on model capability tier"
```

---

### Task 2：扩展 builtin.json 添加 Tier 信息

**Files:**
- Modify: `backend/builtin.json`
- Test: `backend/tests/unit/test_builtin_models.py`

**Interfaces:**
- Consumes: 现有 `builtin.json`（17 模型）
- Produces: `builtin.json` 扩展到 50+ 模型，每个模型包含 `tier` 字段

- [ ] **Step 1: 读取现有 builtin.json**

```bash
cd /home/fz/project/sage/.worktrees/feat-smart-model-routing
cat backend/builtin.json | head -50
```

- [ ] **Step 2: 编写测试验证 tier 字段**

创建 `backend/tests/unit/test_builtin_models.py`：

```python
import json
from pathlib import Path

def test_builtin_json_has_tier_field():
    builtin_path = Path(__file__).parent.parent.parent / "builtin.json"
    with open(builtin_path) as f:
        models = json.load(f)
    
    assert len(models) >= 50, "builtin.json should have at least 50 models"
    
    for model in models:
        assert "provider" in model
        assert "model_id" in model
        assert "tier" in model, f"Model {model['model_id']} missing tier field"
        assert model["tier"] in ["fast", "balanced", "powerful"], \
            f"Model {model['model_id']} has invalid tier: {model['tier']}"

def test_builtin_json_tier_distribution():
    """Ensure reasonable tier distribution"""
    builtin_path = Path(__file__).parent.parent.parent / "builtin.json"
    with open(builtin_path) as f:
        models = json.load(f)
    
    tier_counts = {"fast": 0, "balanced": 0, "powerful": 0}
    for model in models:
        tier_counts[model["tier"]] += 1
    
    # At least 10 models per tier
    assert tier_counts["fast"] >= 10
    assert tier_counts["balanced"] >= 10
    assert tier_counts["powerful"] >= 10
```

- [ ] **Step 3: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_builtin_models.py -v
```

Expected: FAIL（`tier` 字段不存在，模型数量不足）

- [ ] **Step 4: 扩展 builtin.json**

编辑 `backend/builtin.json`，为所有现有模型添加 `tier` 字段，并增加新模型。

**Tier 分配规则**：
- `fast`: Haiku, GPT-4o-mini, Llama-3-8B, Qwen-2-7B, Mistral-7B
- `balanced`: Sonnet, GPT-4o, Llama-3-70B, Qwen-2-72B, Mistral-Large
- `powerful`: Opus, GPT-4-turbo, o1, o1-mini

**新增模型清单**（至少 50 个）：

```json
[
  {
    "provider": "openai",
    "model_id": "gpt-4o",
    "tier": "balanced",
    "native_context_window": 128000,
    "capabilities": ["chat", "vision", "tool_use"],
    "pricing": {"input_per_million": "2.50", "output_per_million": "10.00"}
  },
  {
    "provider": "anthropic",
    "model_id": "claude-3-5-sonnet-20241022",
    "tier": "balanced",
    "native_context_window": 200000,
    "capabilities": ["chat", "vision", "tool_use"],
    "pricing": {"input_per_million": "3.00", "output_per_million": "15.00"}
  },
  {
    "provider": "anthropic",
    "model_id": "claude-3-haiku-20240307",
    "tier": "fast",
    "native_context_window": 200000,
    "capabilities": ["chat", "vision"],
    "pricing": {"input_per_million": "0.25", "output_per_million": "1.25"}
  },
  {
    "provider": "anthropic",
    "model_id": "claude-3-opus-20240229",
    "tier": "powerful",
    "native_context_window": 200000,
    "capabilities": ["chat", "vision", "tool_use"],
    "pricing": {"input_per_million": "15.00", "output_per_million": "75.00"}
  },
  {
    "provider": "openai",
    "model_id": "gpt-4o-mini",
    "tier": "fast",
    "native_context_window": 128000,
    "capabilities": ["chat", "vision"],
    "pricing": {"input_per_million": "0.15", "output_per_million": "0.60"}
  }
]
```

**完整模型清单参考**（按 tier 分组）：

**Fast tier**（至少 15 个）：
- gpt-4o-mini, gpt-3.5-turbo
- claude-3-haiku-20240307
- llama-3-8b-instruct, llama-3.1-8b-instruct
- qwen-2-7b-instruct, qwen-2.5-7b-instruct
- mistral-7b-instruct, mistral-small
- gemini-1.5-flash
- deepseek-coder, deepseek-chat
- phi-3-mini, phi-3-small
- yi-1.5-6b-chat

**Balanced tier**（至少 20 个）：
- gpt-4o, gpt-4-turbo
- claude-3-5-sonnet-20241022, claude-3-sonnet-20240229
- llama-3-70b-instruct, llama-3.1-70b-instruct
- qwen-2-72b-instruct, qwen-2.5-72b-instruct
- mistral-large, mixtral-8x7b-instruct
- gemini-1.5-pro
- deepseek-v2, deepseek-v3
- yi-1.5-34b-chat
- command-r-plus
- dbrx-instruct
- jamba-1.5-large
- grok-2

**Powerful tier**（至少 15 个）：
- claude-3-opus-20240229
- o1, o1-mini, o1-preview
- gpt-4-turbo (if not in balanced)
- llama-3.1-405b-instruct
- qwen-2.5-110b-instruct
- mistral-large-2
- gemini-1.5-ultra
- deepseek-r1
- yi-1.5-200b-chat
- command-r-plus-082024
- grok-3

- [ ] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_builtin_models.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/builtin.json backend/tests/unit/test_builtin_models.py
git commit -m "feat(model-catalog): expand builtin.json to 50+ models with tier info

- Add tier field to all models (fast/balanced/powerful)
- Expand from 17 to 50+ models
- Cover OpenAI, Anthropic, Google, Meta, Mistral, Qwen, DeepSeek
- Ensure at least 10 models per tier
- Support offline-first deployment scenarios"
```

---

### Task 3：实现路由引擎核心

**Files:**
- Create: `backend/routing/__init__.py`
- Create: `backend/routing/routing_engine.py`
- Test: `backend/tests/unit/test_routing_engine.py`

**Interfaces:**
- Consumes: `ModelCatalogRepository`, `EffectiveModel` (from model_catalog)
- Produces: `RoutingEngine.route()` → `RoutingResult`

- [ ] **Step 1: 创建 routing 模块骨架**

创建 `backend/routing/__init__.py`：

```python
"""Smart model routing engine."""

from .routing_engine import RoutingEngine, RoutingResult, RoutingPreference

__all__ = ["RoutingEngine", "RoutingResult", "RoutingPreference"]
```

- [ ] **Step 2: 编写路由引擎失败测试**

创建 `backend/tests/unit/test_routing_engine.py`：

```python
import pytest
from unittest.mock import Mock
from backend.routing.routing_engine import RoutingEngine, RoutingResult
from backend.model_catalog.schemas import EffectiveModel

@pytest.fixture
def mock_repository():
    repo = Mock()
    repo.list_effective_models.return_value = [
        EffectiveModel(
            provider="openai",
            model_id="gpt-4o-mini",
            tier="fast",
            native_context_window=128000,
            capabilities=["chat"],
        ),
        EffectiveModel(
            provider="openai",
            model_id="gpt-4o",
            tier="balanced",
            native_context_window=128000,
            capabilities=["chat", "vision"],
        ),
        EffectiveModel(
            provider="anthropic",
            model_id="claude-3-opus",
            tier="powerful",
            native_context_window=200000,
            capabilities=["chat", "vision", "tool_use"],
        ),
    ]
    return repo

def test_routing_engine_selects_balanced_for_code_generation(mock_repository):
    engine = RoutingEngine(mock_repository)
    result = engine.route(
        task_type="code_generation",
        context_length=8000,
        required_capabilities=["chat"],
    )
    
    assert isinstance(result, RoutingResult)
    assert result.selected_model.tier == "balanced"
    assert "code_generation" in result.reason

def test_routing_engine_filters_by_context_length(mock_repository):
    engine = RoutingEngine(mock_repository)
    result = engine.route(
        task_type="analysis",
        context_length=150000,  # Requires >128K
        required_capabilities=["chat"],
    )
    
    # Should select powerful tier (200K context)
    assert result.selected_model.native_context_window >= 150000

def test_routing_engine_filters_by_capability(mock_repository):
    engine = RoutingEngine(mock_repository)
    result = engine.route(
        task_type="vision_task",
        context_length=8000,
        required_capabilities=["chat", "vision"],
    )
    
    assert "vision" in result.selected_model.capabilities

def test_routing_engine_returns_alternatives(mock_repository):
    engine = RoutingEngine(mock_repository)
    result = engine.route(
        task_type="code_generation",
        context_length=8000,
        required_capabilities=["chat"],
    )
    
    assert len(result.alternatives) <= 3
    assert result.selected_model not in result.alternatives
```

- [ ] **Step 3: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_routing_engine.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现路由引擎**

创建 `backend/routing/routing_engine.py`：

```python
"""Smart model routing engine."""

from typing import List, Optional
from pydantic import BaseModel
from backend.model_catalog.schemas import EffectiveModel
from backend.model_catalog.repository import ModelCatalogRepository

# Task type to tier mapping
TASK_TYPE_TO_TIER = {
    "simple_chat": "fast",
    "chat": "fast",
    "code_generation": "balanced",
    "code_review": "powerful",
    "analysis": "powerful",
    "writing": "balanced",
    "translation": "fast",
    "summarization": "balanced",
    "vision_task": "balanced",
}

class RoutingPreference(BaseModel):
    """User preference for routing."""
    preferred_tier: Optional[str] = None
    locked_model: Optional[EffectiveModel] = None

class RoutingResult(BaseModel):
    """Result of routing decision."""
    selected_model: EffectiveModel
    reason: str
    alternatives: List[EffectiveModel]

class RoutingEngine:
    """Smart model routing engine."""
    
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
        Route to the best model based on task requirements.
        
        Args:
            task_type: Type of task (e.g., "code_generation", "analysis")
            context_length: Required context window size
            required_capabilities: List of required capabilities
            user_preference: Optional user preferences
        
        Returns:
            RoutingResult with selected model, reason, and alternatives
        """
        # 1. Get all available models
        available_models = self.catalog.list_effective_models()
        
        # 2. Filter by context length
        filtered = [m for m in available_models if m.native_context_window >= context_length]
        
        # 3. Filter by capabilities
        for cap in required_capabilities:
            filtered = [m for m in filtered if cap in (m.capabilities or [])]
        
        if not filtered:
            raise ValueError(f"No models match requirements: context={context_length}, capabilities={required_capabilities}")
        
        # 4. Check user preference
        if user_preference and user_preference.locked_model:
            return RoutingResult(
                selected_model=user_preference.locked_model,
                reason="用户已锁定模型",
                alternatives=filtered[:3],
            )
        
        # 5. Determine target tier
        preferred_tier = TASK_TYPE_TO_TIER.get(task_type, "balanced")
        if user_preference and user_preference.preferred_tier:
            preferred_tier = user_preference.preferred_tier
        
        # 6. Select model by tier
        selected = self._select_by_tier(filtered, preferred_tier)
        
        # 7. Generate reason
        reason = f"已为 {task_type} 选择 {selected.tier} 模型"
        
        # 8. Get alternatives
        alternatives = [m for m in filtered if m != selected][:3]
        
        return RoutingResult(
            selected_model=selected,
            reason=reason,
            alternatives=alternatives,
        )
    
    def _select_by_tier(self, models: List[EffectiveModel], preferred_tier: str) -> EffectiveModel:
        """Select model by tier with fallback."""
        # Tier priority: preferred → balanced → fast → powerful
        tier_priority = [preferred_tier, "balanced", "fast", "powerful"]
        
        for tier in tier_priority:
            tier_models = [m for m in models if m.tier == tier]
            if tier_models:
                return tier_models[0]
        
        return models[0]  # Fallback
```

- [ ] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_routing_engine.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/routing/ backend/tests/unit/test_routing_engine.py
git commit -m "feat(routing): implement smart routing engine core

- RoutingEngine.route() selects best model based on task type, context, capabilities
- TASK_TYPE_TO_TIER mapping for automatic tier selection
- Tier-based selection with fallback (preferred → balanced → fast → powerful)
- RoutingResult includes selected model, reason, and alternatives
- Unit tests cover all routing scenarios"
```

---

### Task 4：实现路由 API

**Files:**
- Create: `backend/api/routing_routes.py`
- Test: `backend/tests/integration/test_routing_api.py`

**Interfaces:**
- Consumes: `RoutingEngine`, `RoutingPreference`
- Produces: `POST /api/v1/routing/route` endpoint

- [ ] **Step 1: 编写 API 失败测试**

创建 `backend/tests/integration/test_routing_api.py`：

```python
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_routing_api_route(client):
    response = client.post(
        "/api/v1/routing/route",
        json={
            "task_type": "code_generation",
            "context_length": 8000,
            "required_capabilities": ["chat"],
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "selected_model" in data
    assert "reason" in data
    assert "alternatives" in data
    assert data["selected_model"]["tier"] in ["fast", "balanced", "powerful"]

def test_routing_api_with_user_preference(client):
    response = client.post(
        "/api/v1/routing/route",
        json={
            "task_type": "code_generation",
            "context_length": 8000,
            "required_capabilities": ["chat"],
            "user_preference": {
                "preferred_tier": "powerful",
            },
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["selected_model"]["tier"] == "powerful"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_routing_api.py -v
```

Expected: FAIL（路由不存在）

- [ ] **Step 3: 实现路由 API**

创建 `backend/api/routing_routes.py`：

```python
"""Routing API endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from backend.routing.routing_engine import RoutingEngine, RoutingPreference, RoutingResult
from backend.model_catalog.schemas import EffectiveModel
from backend.model_catalog.repository import ModelCatalogRepository
from backend.data.database import get_database

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])

class RoutingRequest(BaseModel):
    task_type: str
    context_length: int
    required_capabilities: List[str]
    user_preference: Optional[RoutingPreference] = None

class RoutingResponse(BaseModel):
    selected_model: EffectiveModel
    reason: str
    alternatives: List[EffectiveModel]

def get_routing_engine() -> RoutingEngine:
    db = get_database()
    repo = ModelCatalogRepository(db)
    return RoutingEngine(repo)

@router.post("/route", response_model=RoutingResponse)
def route(request: RoutingRequest, engine: RoutingEngine = Depends(get_routing_engine)):
    """Route to the best model based on task requirements."""
    result = engine.route(
        task_type=request.task_type,
        context_length=request.context_length,
        required_capabilities=request.required_capabilities,
        user_preference=request.user_preference,
    )
    
    return RoutingResponse(
        selected_model=result.selected_model,
        reason=result.reason,
        alternatives=result.alternatives,
    )
```

- [ ] **Step 4: 注册路由到 main.py**

编辑 `backend/main.py`，在路由注册部分添加：

```python
from backend.api.routing_routes import router as routing_router

app.include_router(routing_router)
```

- [ ] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_routing_api.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/api/routing_routes.py backend/tests/integration/test_routing_api.py backend/main.py
git commit -m "feat(api): add routing API endpoint

- POST /api/v1/routing/route accepts task type, context, capabilities
- Returns selected model, reason, and alternatives
- Integrates with RoutingEngine
- Unit tests cover API contract"
```

---

### Task 5：路由助手集成到 LLM Factory（已按裁定重写）

> **原计划的本节假设了一个 `LLMFactory` 类与 `create_client(task_type, ..., auto_mode, explicit_model)` 方法，
> 以及 `EffectiveModel(provider=..., model_id=..., native_context_window=...)` 形状。两者都不存在。**
> 实际文件是函数模块，`EffectiveModel` 是扁平结构（`model_key` / `limits.native` / `capabilities`）。
> 本节按裁定 R10–R12 重写，并已实现、审查通过。完整 brief 见
> `.superpowers/sdd/2026-10-28-smart-model-routing/task-5-brief-ruled.md`。

**Files:**
- Modify: `backend/model_catalog/repository.py` — `list_effective_models(endpoint_id: Optional[str] = None)` 前置 SQL 过滤
- Modify: `backend/routing/routing_engine.py` — `route()` / `_get_available_models()` 增加可选 `endpoint_id`（默认 None 行为不变）
- Modify: `backend/orchestration/llm_factory.py` — 新增 `resolve_routed_chat_model(...) -> Optional[str]`
- Test: `backend/tests/unit/test_llm_factory_routing.py`

**接口（实际形状）:**
```python
def resolve_routed_chat_model(
    task_type: str,
    context_length: int = 4096,
    required_capabilities: Optional[List[str]] = None,
    endpoint_id: Optional[str] = None,
    catalog_repository: Optional[Any] = None,
) -> Optional[str]: ...   # selected model_key.model_id，失败/无匹配返回 None
```

**关键约束（已由审查验证）:**
- 端点作用域是正确性要求：工厂把一个模型 id 与**单个**端点的 `api_key`/`base_url` 配对
- 纯增量、默认保持：不重连任何现有调用方，`endpoint_id=None` 时与 Task 3 行为逐字节一致
- fail-safe：任何 catalog/路由异常返回 None，仅 debug 日志，绝不抛错、不记录凭据

**状态：** 已完成（`03bbd17ad` + fix round），审查 Approved，无 Critical/Important。

---

## Phase 2-6（已细化，2026-10-28）

> Phase 1 的 Task 1-5 已完成并逐任务审查。以下任务在分派前由 controller 写入
> `.superpowers/sdd/2026-10-28-smart-model-routing/task-<N>-brief*.md` 的详细 brief；
> 本节锁定范围、接口与验收，避免分派时重新设计。前端真实代码位置、行号与数据源
> 现状见同目录 `frontend-map.md`。

### 影响 Phase 2-6 的设计裁定

- **R16 — 任务类型由调用方显式传入，不做运行时内容分类器。** spec §3.3 只定义
  `TASK_TYPE_TO_TIER` 映射，从未定义"如何推断任务类型"。自动模式的选择器提供
  任务类型选择器（默认 `chat`），随 `/chat` 请求下发，后端据此路由。
  理由：内容启发式分类无法稳定验收；显式输入可测试、可撤销；将来若加分类器，
  只是改变默认值，纯增量。代价：用户需选择任务类型。
- **R17 — 自动模式不写 session override。** 自动模式 = 后端按请求路由；用户显式
  选模型 = 手动模式并写 override。避免"前端算一次 + 后端再算一次"的双实现。
- **R18 — 卡片视图先展示 candidate tier。** `listModels` 已是批量接口；逐模型
  调 `getEffective` 会 N+1。卡片展示 candidate `tier`（null 显示"未知"），
  `ModelDetails` 仍读 effective。
- **R19 — 自定义任务映射延后。** spec §3.4.3 的"任务类型映射"在 Phase 4 以只读表
  呈现后端常量；用户自定义映射需要新的 settings 键与 6 处同步，留作后续任务。

### Task 6：路由 API endpoint 作用域 + 前端 routing 客户端

**Files:**
- Modify: `backend/api/routing_routes.py` — `RoutingRequest` 增 `endpoint_id: Optional[str] = None`，透传 `engine.route(..., endpoint_id=payload.endpoint_id)`
- Modify: `backend/tests/integration/test_routing_api.py` — scoped 用例
- Modify: `src/entities/model-catalog/types.ts` — `EffectiveModel` 同步后端（补 `model_key`、`tier`、`capabilities`）；`CandidateModel` 补 `tier?: string | null`
- Create: `src/entities/routing/types.ts`
- Create: `src/entities/routing/api.ts`
- Create: `src/entities/routing/__tests__/api.test.ts`

**接口:**
```ts
export type Tier = 'fast' | 'balanced' | 'powerful';
export interface RoutingPreference {
  preferred_tier?: Tier | null;
  locked_model?: string | null;
}
export interface RouteRequest {
  task_type: string;
  context_length: number;
  required_capabilities: string[];
  user_preference?: RoutingPreference | null;
  endpoint_id?: string | null;
}
export interface RouteResponse {
  selected_model: EffectiveModel;
  reason: string;
  alternatives: EffectiveModel[];
}
export async function routeModel(req: RouteRequest): Promise<RouteResponse>;
```

**验收:**
- 带 `endpoint_id` 的请求只返回该端点绑定的模型；该端点无匹配 → 422（不是 500）
- `routeModel` 走 `backendRequest` 漏斗（与 `model-catalog/api.ts` 一致），401/422 原样抛出
- 前端 `EffectiveModel` 与后端字段一一对应，`model_key.provider` / `model_key.model_id` 可用
- py38 gates + ruff + `npx tsc --noEmit` + 相关 vitest 全绿

### Task 7：SessionModelPicker 自动模式 + tier 分组

**Files:**
- Modify: `src/widgets/chat/SessionModelPicker.tsx`
- Test: `src/widgets/chat/__tests__/SessionModelPicker.test.tsx`

**行为:**
- 数据源：`listModels({ endpointId })` 取 tier 与价格；请求失败（离线）回退
  `settings.endpoints[].discoveredModels`，平铺显示、无 tier 分组
- **自动模式（默认）**：不写 override；展开面板显示 `routeModel(...)` 的结果
  （模型名 + tier + reason）与任务类型选择器（默认 `chat`，存 localStorage
  `routingTaskType`，参照 `welcomeModelId` 先例）
- **手动模式**：现行为不变（`sessionApi.setModelOverride`），清空仍传 `""`
- `endpointId` 取全局 chat 模型所属端点（`modelSelections.chatModel.endpointId`）
- 展开列表按 tier 分组（fast / balanced / powerful / 未分类，固定顺序），每项显示 context / price

**验收:** 自动模式不发 `setModelOverride`；手动模式发；离线回退仍可手动选择；
tier 分组顺序稳定；现有 6 个用例保持绿

### Task 8：Welcome ModelPicker 对齐

**Files:** `src/widgets/welcome/ModelPicker.tsx`、`src/pages/Welcome.tsx`、
`src/widgets/welcome/__tests__/ModelPicker.test.tsx`

**行为:** 与 Task 7 相同的 tier 分组 + 自动选项；自动模式提交时不写
`welcomeModelId` 覆盖，手动仍写；`global` 哨兵保留

### Task 9：后端自动路由激活（settings + /chat）

**Files:**
- Modify: `backend/api/settings_models.py`、`backend/data/settings_canonicalizer.py`
- Modify: `backend/orchestration/llm_factory.py` — `load_llm_config_for_chat(..., task_type=None)` 增加 auto 覆盖
- Modify: `backend/api/legacy_chat_routes.py` — `ChatRequest` 增 `task_type: Optional[str] = None`，传给 `load_llm_config_for_chat`
- Modify: `src/entities/setting/types.ts`、`src/entities/setting/storage.ts`（`TOP_KEYS`）
- Modify: `src/pages/settings/settingsSearchIndex.ts`
- Modify: `backend/tests/contract/test_settings_schema_parity.py` + 后端/前端单测

**新增设置键（必须 6 处同步）:**
```ts
routing: { mode: 'auto' | 'manual' }   // 默认 'manual'，保证现行为不变
```

**行为:** `mode === 'auto'` 时，`load_llm_config_for_chat` 调
`resolve_routed_chat_model(task_type=task_type or 'chat', context_length=settings.maxContext or 4096, endpoint_id=cfg['endpoint_id'])`；
返回值非 None 则覆盖 `cfg['model']`。任何失败保持 settings 模型（Task 5 fail-safe）。

**验收:** `manual` 下 `test_llm_factory` / `test_session_model_override` 全部不变；
`auto` 下只在同一端点内路由、不跨端点泄漏；catalog 为空不抛错；settings 契约 parity 绿

### Task 10：模型目录卡片视图（Phase 3）

**Files:** Create `src/widgets/model-catalog/CatalogCards.tsx`；Modify
`src/pages/ModelCatalog.tsx`、`src/widgets/model-catalog/index.ts`；
Test 扩充 `src/pages/__tests__/ModelCatalog.test.tsx`

**行为:** 表格/卡片视图切换（默认卡片，localStorage `modelCatalogView`）；卡片显示
模型名、tier、capabilities 图标、native context、price；过滤（tier / provider /
capability）与排序（context / price）纯前端；导入 / 同步 / override 折叠进"高级"

**验收:** 视图切换持久化；无新增 API；`ModelDetails` 仍走 effective；
现有 287 行测试不回归

### Task 11：ModelsTab 路由模式 UI（Phase 4）

**Files:** Modify `src/pages/settings/ModelsTab.tsx`、
`src/pages/settings/__tests__/ModelsTab.test.tsx`

**行为:** `routing.mode` 单选（自动 / 手动）；自动模式显示默认 tier 选择器 +
**只读**任务类型映射表（R19）；手动模式保留六个 `ModelSelector`；
`autoContext` / `temperature` / `titleModelId` 折叠进"高级"

**验收:** 切换写 `routing.mode`；手动模式行为不变；radio group 有 label/描述；
i18n zh/en 同步

### Task 12：数据流统一（Phase 5）

**Files:** 端点发现后端 handler、catalog 幂等迁移钩子、前端读取顺序

**行为:** 端点发现成功后，对每个 discovered 模型 upsert catalog entry（已存在跳过；
只填未知字段，**不覆盖** `user_override`）；前端优先读 catalog、回退
`discoveredModels`（Task 7 已实现回退）；启动时一次性幂等迁移 settings 里的
`discoveredModels` → catalog

**验收:** 迁移幂等；不覆盖 `user_override`；离线仍可用；`discoveredModels`
标记 deprecated 并注明移除期限（2027-01-28）

### Task 13：离线数据丰富（Phase 6）

**Files:** Create `scripts/update_builtin_models.py`；Modify `backend/builtin.json`；
Test `backend/tests/unit/test_builtin_models.py`

**行为:** 脚本从 OpenRouter `/models` 拉取、按名字启发式分配 tier、与现有条目去重合并、
稳定排序；提供 `--dry-run` 与 `--check`（校验结构 / 无重复）。
**网络不可用（内网）时跳过本任务**，保留现有 55 模型，不阻塞 Phase 1-5

**验收:** `--check` 在现有 `builtin.json` 上通过；无网络不阻塞其他任务

---

## 执行交接

**计划已完成并保存到** `docs/superpowers/plans/2026-10-28-smart-model-routing.md`

**两种执行方式：**

**1. Subagent-Driven（推荐）** - 每个任务分派一个独立 subagent，任务间审查，快速迭代

**2. Inline Execution** - 在当前会话中使用 executing-plans 批量执行，带检查点审查

**选择哪种方式？**
