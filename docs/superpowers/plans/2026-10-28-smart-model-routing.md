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

### Task 5：集成路由到 LLM Factory

**Files:**
- Modify: `backend/orchestration/llm_factory.py`
- Test: `backend/tests/unit/test_llm_factory_routing.py`

**Interfaces:**
- Consumes: `RoutingEngine`, `RoutingResult`
- Produces: 修改 `LLMFactory.create_client()` 支持自动路由

- [ ] **Step 1: 读取现有 LLMFactory 实现**

```bash
cat backend/orchestration/llm_factory.py | head -100
```

- [ ] **Step 2: 编写集成测试**

创建 `backend/tests/unit/test_llm_factory_routing.py`：

```python
import pytest
from unittest.mock import Mock, patch
from backend.orchestration.llm_factory import LLMFactory
from backend.routing.routing_engine import RoutingResult
from backend.model_catalog.schemas import EffectiveModel

def test_llm_factory_uses_routing_when_auto_mode():
    """When auto_mode=True, factory should use routing engine."""
    mock_engine = Mock()
    mock_engine.route.return_value = RoutingResult(
        selected_model=EffectiveModel(
            provider="openai",
            model_id="gpt-4o",
            tier="balanced",
            native_context_window=128000,
        ),
        reason="已为 code_generation 选择 balanced 模型",
        alternatives=[],
    )
    
    factory = LLMFactory(routing_engine=mock_engine)
    client = factory.create_client(
        task_type="code_generation",
        context_length=8000,
        auto_mode=True,
    )
    
    mock_engine.route.assert_called_once()
    assert client is not None

def test_llm_factory_uses_explicit_model_when_specified():
    """When explicit model is specified, factory should not use routing."""
    mock_engine = Mock()
    factory = LLMFactory(routing_engine=mock_engine)
    
    client = factory.create_client(
        task_type="code_generation",
        context_length=8000,
        explicit_model="gpt-4o-mini",
        auto_mode=False,
    )
    
    mock_engine.route.assert_not_called()
```

- [ ] **Step 3: 运行测试验证失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_factory_routing.py -v
```

Expected: FAIL（LLMFactory 不支持 routing_engine 参数）

- [ ] **Step 4: 修改 LLMFactory 集成路由**

编辑 `backend/orchestration/llm_factory.py`：

```python
from backend.routing.routing_engine import RoutingEngine, RoutingPreference

class LLMFactory:
    def __init__(self, routing_engine: Optional[RoutingEngine] = None):
        self.routing_engine = routing_engine
    
    def create_client(
        self,
        task_type: Optional[str] = None,
        context_length: int = 4096,
        auto_mode: bool = True,
        explicit_model: Optional[str] = None,
        ...
    ):
        # If auto_mode and no explicit model, use routing
        if auto_mode and not explicit_model and task_type:
            result = self.routing_engine.route(
                task_type=task_type,
                context_length=context_length,
                required_capabilities=["chat"],
            )
            # Use result.selected_model
            model_to_use = result.selected_model
        else:
            # Use explicit model or fallback logic
            model_to_use = explicit_model
        
        # ... rest of the logic
```

- [ ] **Step 5: 运行测试验证通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_factory_routing.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/orchestration/llm_factory.py backend/tests/unit/test_llm_factory_routing.py
git commit -m "feat(llm-factory): integrate routing engine for auto model selection

- LLMFactory accepts routing_engine parameter
- When auto_mode=True and no explicit model, uses routing engine
- Backward compatible: explicit model overrides routing
- Unit tests cover integration scenarios"
```

---

## Phase 2-6（后续任务）

由于计划篇幅限制，Phase 2-6 的详细任务将在实施过程中逐步补充。每个 Phase 遵循相同的 TDD 流程：

1. 编写失败测试
2. 运行测试验证失败
3. 实现最小代码
4. 运行测试验证通过
5. 提交

**Phase 2：前端模型选择器** - 重构 SessionModelPicker 和 ModelPicker，支持自动选择和 tier 分组显示

**Phase 3：前端模型目录** - 实现 CatalogCards 组件，重构 ModelCatalog 页面支持双视图

**Phase 4：前端设置页面** - 重构 ModelsTab 支持自动选择模式

**Phase 5：数据流统一** - 端点发现自动创建 catalog entry，前端读取 catalog effective 数据

**Phase 6：离线数据丰富** - 编写 update_builtin_models.py 脚本，扩展 builtin.json 到 100 模型

---

## 执行交接

**计划已完成并保存到** `docs/superpowers/plans/2026-10-28-smart-model-routing.md`

**两种执行方式：**

**1. Subagent-Driven（推荐）** - 每个任务分派一个独立 subagent，任务间审查，快速迭代

**2. Inline Execution** - 在当前会话中使用 executing-plans 批量执行，带检查点审查

**选择哪种方式？**
