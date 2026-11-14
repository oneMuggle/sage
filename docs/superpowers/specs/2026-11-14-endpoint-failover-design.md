# Endpoint Failover Design

> **Date**: 2026-11-14
> **Status**: Draft
> **Author**: Claude + User

## Background

Sage currently supports configuring multiple LLM endpoints but uses only one at a time (selected via `modelSelections.chatModel`). When that endpoint fails (5xx, timeout, auth error), the user must manually switch to another endpoint. This design adds automatic failover: when the active endpoint fails, the system automatically switches to the next priority endpoint and notifies the user.

## Goals

1. **High availability** - Automatic failover when primary endpoint fails
2. **Auto failback** - Probe failed endpoints periodically; switch back when healthy
3. **User visibility** - Show current active endpoint and failover status in UI
4. **Architecture-friendly** - Strategy pattern for future Load Balance / Budget modes
5. **Backward compatible** - Existing single-endpoint behavior unchanged when `failover.enabled=false`

## Non-Goals

- Load balancing (future extension point)
- Budget-driven switching (future extension point)
- Cross-session endpoint coordination (each session independently fails over)

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    UI Layer                          │
│  EndpointsTab: priority drag + failover toggle       │
│  StatusBanner: active endpoint + degraded status     │
└────────────────────────┬────────────────────────────┘
                         │ settings.endpoints + priority
                         ▼
┌─────────────────────────────────────────────────────┐
│              EndpointSelectionService                │
│  ├─ FailoverStrategy: select by priority             │
│  ├─ (future) LoadBalanceStrategy                     │
│  ├─ (future) BudgetStrategy                          │
│  └─ Interface: select(endpoints, health) → endpoint  │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              EndpointHealthMonitor                   │
│  ├─ Health state: {endpointId → status, failures}    │
│  ├─ Probe scheduler: periodic health checks          │
│  └─ Event bus: emit('failover', {from, to, reason})  │
└────────────────────────┬────────────────────────────┘
                         │ healthy endpoint
                         ▼
┌─────────────────────────────────────────────────────┐
│              LLMFactory (modified)                   │
│  build_client_for(endpoint_id) → LLMClient           │
│  load_llm_config_for_chat() → FailoverChainConfig    │
└────────────────────────┬────────────────────────────┘
                         │ LLMClient
                         ▼
┌─────────────────────────────────────────────────────┐
│              LLMClient (unchanged)                   │
│  Single-endpoint HTTP communication (pure)           │
└─────────────────────────────────────────────────────┘
```

## Data Model

### Settings Schema Extension

```typescript
// New top-level field in app_settings
interface AppSettings {
  endpoints: EndpointConfig[];  // existing
  failover: FailoverConfig;     // NEW
  modelSelections: { ... };     // existing
}

interface FailoverConfig {
  enabled: boolean;                    // global toggle
  mode: 'failover';                    // future: 'load-balance' | 'budget'
  healthProbeIntervalMs: number;       // default 300_000 (5min)
  failbackCooldownMs: number;          // default 30_000 (30s)
  consecutiveFailThreshold: number;    // fast-switch threshold, default 3
  timeoutCongestionThreshold: number;  // timeout threshold (seconds), default 60
}

// EndpointConfig extension
interface EndpointConfig {
  // existing fields...
  priority: number;       // NEW: priority (1=highest), used in failover mode
  enabled: boolean;       // NEW: participate in failover chain (default true)
}
```

### Health State

```typescript
interface EndpointHealthState {
  endpointId: string;
  status: 'healthy' | 'degraded' | 'failed';
  consecutiveFailures: number;
  lastFailureAt: number | null;
  lastSuccessAt: number | null;
  lastFailureReason: string | null;  // 'timeout' | '5xx' | '401' | 'retry_exhausted'
  failoverCount: number;             // cumulative switch count
}
```

**Persistence**:
- Health state in memory (`dict[str, EndpointHealthState]`)
- On startup, restore failed states from `session_state` KV table
- Periodic snapshot (every 30s) written to `session_state`

## EndpointSelectionService

### Strategy Interface

```python
# backend/services/endpoint_selection/strategy.py

class EndpointSelectionStrategy(Protocol):
    """Unified interface for endpoint selection strategies."""
    
    def select(
        self,
        endpoints: list[EndpointConfig],
        health: EndpointHealthSnapshot,
        context: SelectionContext,
    ) -> SelectionResult:
        """
        Args:
            endpoints: available endpoints (filtered by enabled=True)
            health: health state snapshot for all endpoints
            context: request context (task_type, session_id, etc.)
        
        Returns:
            Selected endpoint + metadata
        """
        ...


class SelectionResult:
    endpoint_id: str
    strategy_used: str          # 'failover' | 'load-balance' | 'budget'
    fallback_chain: list[str]   # fallback endpoint IDs (by priority)
    metadata: dict              # strategy-specific extras
```

### FailoverStrategy Implementation

```python
class FailoverStrategy:
    """Select healthy endpoint by priority."""
    
    def select(self, endpoints, health, context) -> SelectionResult:
        # 1. Sort by priority
        sorted_eps = sorted(endpoints, key=lambda e: e.priority)
        
        # 2. Skip failed endpoints within cooldown
        candidates = []
        for ep in sorted_eps:
            h = health.get(ep.id)
            if h and h.status == 'failed':
                cooldown = self.failback_cooldown_ms
                if h.last_failure_at and (now() - h.last_failure_at) < cooldown:
                    continue  # skip during cooldown
            candidates.append(ep)
        
        # 3. Return first available + rest as fallback_chain
        selected = candidates[0]
        fallback = [ep.id for ep in candidates[1:]]
        
        return SelectionResult(
            endpoint_id=selected.id,
            strategy_used='failover',
            fallback_chain=fallback,
            metadata={'priority': selected.priority},
        )
```

### Service Layer

```python
class EndpointSelectionService:
    """Endpoint selection entry point. Reads settings to determine strategy."""
    
    def __init__(self, health_monitor: EndpointHealthMonitor):
        self.health_monitor = health_monitor
    
    def select(self, context: SelectionContext) -> SelectionResult:
        config = load_failover_config()
        endpoints = load_enabled_endpoints()
        health = self.health_monitor.snapshot()
        
        strategy = self._resolve_strategy(config.mode)
        return strategy.select(endpoints, health, context)
    
    def _resolve_strategy(self, mode: str):
        match mode:
            case 'failover': return FailoverStrategy(...)
            # case 'load-balance': return LoadBalanceStrategy(...)
            # case 'budget': return BudgetStrategy(...)
```

## EndpointHealthMonitor

### Responsibilities

Manage endpoint health state, provide probing and status queries.

### Core Interface

```python
# backend/services/endpoint_health/monitor.py

class EndpointHealthMonitor:
    """Endpoint health state management."""
    
    # --- State updates (called by run_loop / LLMClient) ---
    
    def record_success(self, endpoint_id: str, latency_ms: int) -> None:
        """Record successful request. Reset consecutive failure count."""
    
    def record_failure(
        self, 
        endpoint_id: str, 
        reason: FailureReason,  # 'timeout' | '5xx' | '401' | 'retry_exhausted'
    ) -> None:
        """Record failure. Increment consecutive_failures, may trigger status downgrade."""
    
    # --- State queries (called by Strategy) ---
    
    def get_status(self, endpoint_id: str) -> EndpointHealthState:
        """Get health state for single endpoint."""
    
    def snapshot(self) -> EndpointHealthSnapshot:
        """Get health state snapshot for all endpoints (for Strategy batch queries)."""
    
    # --- Probing (background task) ---
    
    async def start_probe_loop(self) -> None:
        """Start background probe loop. Probe failed/degraded endpoints every probe_interval_ms."""
    
    async def stop(self) -> None:
        """Stop probing."""
    
    async def _probe_endpoint(self, endpoint: EndpointConfig) -> bool:
        """
        Probe implementation:
        - Send GET /models (OpenAI-compatible) or /v1/models
        - Timeout 10s
        - 2xx → healthy, 4xx/5xx → still failed
        """

    # --- Event emission (for UI / logging) ---
    
    def on_status_change(
        self, 
        callback: Callable[[HealthChangeEvent], None]
    ) -> None:
        """Register status change callback."""
```

### State Machine

```
                  record_success
         ┌──────────────────────────┐
         │                          ▼
      ┌──────┐  consecutive≥3  ┌───────────┐  probe OK  ┌─────────┐
      │healthy│ ──────────────→ │  degraded │ ──────────→ │ healthy │
      └──────┘                  └───────────┘             └─────────┘
         │                           │
         │ 401 / consecutive≥5       │ probe fail
         ▼                           ▼
      ┌────────┐               ┌────────┐
      │ failed │               │ failed │
      └────────┘               └────────┘
         │                           │
         │ probe OK + cooldown       │
         └───────────────────────────┘
```

### Event Types

```python
class HealthChangeEvent:
    endpoint_id: str
    from_status: str
    to_status: str
    reason: str
    timestamp: int

class FailoverEvent:
    from_endpoint_id: str
    to_endpoint_id: str
    reason: str              # 'retry_exhausted' | 'auth_failed' | '5xx' | 'timeout'
    consecutive_failures: int
    timestamp: int
```

## LLMFactory Integration + Run Loop Changes

### LLMFactory Changes

Modify `load_llm_config_for_chat()` to return chain config:

```python
# backend/orchestration/llm_factory.py

def load_llm_config_for_chat(
    session_id: str | None = None,
    profile_model: str | None = None,
    profile_max_tokens: int | None = None,
    task_type: str | None = None,
) -> FailoverChainConfig | None:
    """Return endpoint chain config (with fallback_chain), not single endpoint."""

class FailoverChainConfig:
    """Endpoint chain configuration."""
    primary: dict[str, Any]          # primary endpoint's LLMConfig-compatible dict
    fallback_chain: list[str]        # fallback endpoint IDs (by priority)
    strategy: str                    # 'failover'
    health_monitor: EndpointHealthMonitor  # injected reference
```

When `failover.enabled=False`, degrade to existing behavior (single endpoint, `fallback_chain=[]`).

### Run Loop Changes

Current `agent.run_loop` builds `LLMClient` at iteration start and reuses for entire run. Change to:

```python
# Simplified pseudocode

async def _call_llm_with_failover(messages, tools, ...):
    """LLM call with failover."""
    chain = load_llm_config_for_chat(session_id, ...)
    if chain is None:
        raise NoEndpointConfigured()
    
    # Try endpoint chain
    endpoint_ids = [chain.primary['endpoint_id']] + chain.fallback_chain
    
    for i, ep_id in enumerate(endpoint_ids):
        client = build_client_for_endpoint(ep_id, chain)
        try:
            response = await client.chat_stream_events(messages, tools, ...)
            # Success → record health
            health_monitor.record_success(ep_id, latency)
            return response
        except LLMError as err:
            health_monitor.record_failure(ep_id, map_reason(err))
            
            # Decide whether to switch
            if should_switch_endpoint(err, ep_id):
                # Emit failover event to frontend
                emit(FailoverEvent(from=ep_id, to=endpoint_ids[i+1], reason=...))
                continue  # try next
            
            raise  # non-retryable error, raise directly
    
    raise AllEndpointsFailed()


def should_switch_endpoint(err: LLMError, endpoint_id: str) -> bool:
    """Decide whether to switch to next endpoint."""
    health = health_monitor.get_status(endpoint_id)
    
    # 401 → switch immediately (auth failure pointless to retry)
    if err.type == LLMErrorType.AUTH_FAILED:
        return True
    
    # Consecutive 5xx ≥ threshold → fast switch
    if err.type == LLMErrorType.SERVER_ERROR:
        if health.consecutive_failures >= CONSECUTIVE_5XX_THRESHOLD:
            return True
    
    # Retry exhausted → switch
    if err.type in RETRYABLE_TYPES:
        # Already retried inside LLMClient; here we check if exhausted
        return True  # run_loop level: client threw → retries exhausted
    
    # Timeout congestion → switch
    if err.type == LLMErrorType.TIMEOUT:
        if health.consecutive_failures >= TIMEOUT_CONGESTION_THRESHOLD:
            return True
    
    return False
```

### Streaming Request Special Handling

```
_chat_stream_events_raw() fails before first event
  → Safe retry: run_loop gets new client and resends

_chat_stream_events_raw() fails after content_delta produced
  → Cannot safely retry (existing logic)
  → Record failure, but don't switch for this request
  → Next iteration automatically uses new endpoint
```

### Backward Compatibility

- `failover.enabled=False` → `load_llm_config_for_chat` returns identical single-endpoint config as now
- All existing tests and callers unaffected
- New behavior only active when `failover.enabled=True`

## UI Changes

### EndpointsTab Extension

```
┌─────────────────── Endpoint Configuration ────────────────────┐
│ [✓] Enable failover     Probe interval [5] minutes            │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ≡  OpenAI GPT-4o                                          │ │
│  │    https://api.openai.com/v1                               │ │
│  │    Priority 1 · 🟢 Active · Tested 230ms                  │ │
│  │                                         [Edit] [Test]      │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ≡  DeepSeek V3                                            │ │
│  │    https://api.deepseek.com/v1                             │ │
│  │    Priority 2 · 🟡 Degraded · 5xx×2                       │ │
│  │                                         [Edit] [Test]      │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ ≡  Ollama Local                                           │ │
│  │    http://localhost:11434/v1                               │ │
│  │    Priority 3 · ⚪ Standby                                 │ │
│  │                                         [Edit] [Test]      │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Drag ≡ handle to adjust priority order                        │
│  Failback cooldown [30]s · Consecutive failure threshold [3]   │
└──────────────────────────────────────────────────────────────────┘
```

### Drag Implementation

Use `@dnd-kit/core` (project already depends on it) or native HTML5 Drag & Drop:

```typescript
// Update priority field after drag ends
const handleDragEnd = (oldIndex: number, newIndex: number) => {
  const reordered = arrayMove(endpoints, oldIndex, newIndex);
  const withPriority = reordered.map((ep, i) => ({ ...ep, priority: i + 1 }));
  updateSettings({ endpoints: withPriority });
};
```

### Advanced Settings Collapsible

Collapsed by default, expand to show:
- Probe interval (default 5 minutes)
- Failback cooldown (default 30 seconds)
- Consecutive 5xx fast-switch threshold (default 3)
- Timeout congestion threshold (default 60 seconds)

## Status Banner + Toast

### StatusBanner Extension

Extend existing `BackendStatusBanner` with endpoint status:

```typescript
// New endpoint status area
interface EndpointStatusBarProps {
  activeEndpoint: string;      // current active endpoint name
  status: 'active' | 'failover' | 'all-failed';
  chainLength: number;         // total endpoints in chain
}

// Render
function EndpointStatusBar({ activeEndpoint, status, chainLength }) {
  const icons = { active: '🟢', failover: '🟡', 'all-failed': '🔴' };
  const labels = {
    active: activeEndpoint,
    failover: `${activeEndpoint} (failover in progress)`,
    'all-failed': 'All endpoints unavailable',
  };
  return (
    <div className="endpoint-status-bar">
      <span>{icons[status]}</span>
      <span>{labels[status]}</span>
      {chainLength > 1 && <span className="chain-indicator">1/{chainLength}</span>}
    </div>
  );
}
```

### Toast Notifications

```typescript
// Listen to failover events
useEffect(() => {
  const unsub = ipcRenderer.on('llm:endpoint:failover', (event: FailoverEvent) => {
    toast.warning(
      t('failover.switched', { from: event.from, to: event.to }),
      { duration: 5000 }
    );
  });
  return unsub;
}, []);
```

### Status Data Flow

```
Backend: EndpointHealthMonitor
  → Status change → emit FailoverEvent
  → IPC → Frontend

Frontend:
  → EndpointStatusBar updates display
  → Toast popup notification
  → Settings page endpoint list updates status icons in real-time
```

## IPC Event Protocol

New IPC channels:

```typescript
// Backend → Frontend
'llm:endpoint:failover': FailoverEvent;
'llm:endpoint:health-change': HealthChangeEvent;
```

Backend sends at:
1. `EndpointHealthMonitor.record_failure()` causes status downgrade
2. Run loop switches to next endpoint
3. Probe succeeds causing failback

Frontend consumes at:
1. `EndpointStatusBar` component subscribes to `health-change` to update display
2. Chat UI subscribes to `failover` to show toast
3. `EndpointsTab` subscribes to `health-change` to update list status icons in real-time

## Testing Strategy

| Component | Test Type | Coverage Focus |
|-----------|-----------|----------------|
| `FailoverStrategy` | Unit | priority sort, skip failed endpoints, cooldown judgment |
| `EndpointHealthMonitor` | Unit | state machine transitions, consecutive failure accumulation, probe mock |
| `should_switch_endpoint()` | Unit | four trigger conditions covered |
| Run loop failover | Integration | mock two endpoints, first returns 5xx, verify switch to second |
| EndpointsTab drag | E2E | priority updates correctly persist after drag |
| StatusBanner | Component | three states render correctly |

## New Modules

- `backend/services/endpoint_selection/` — Strategy + Service
- `backend/services/endpoint_health/` — Monitor + state machine

## Modified Modules

- `backend/orchestration/llm_factory.py` — return FailoverChainConfig
- `backend/agent/run_loop.py` — endpoint chain retry logic
- `src/pages/settings/EndpointsTab.tsx` — drag sort + advanced settings
- `src/widgets/system/EndpointStatusBanner.tsx` — status banner

## New IPC

- `llm:endpoint:failover`
- `llm:endpoint:health-change`

## Future Extensions

This architecture naturally supports:

1. **Load Balance Mode**
   - Add `LoadBalanceStrategy implements EndpointSelectionStrategy`
   - UI adds mode dropdown
   - Zero changes to LLMClient / LLMFactory / HealthMonitor

2. **Budget-Driven Mode**
   - Add `BudgetStrategy implements EndpointSelectionStrategy`
   - Reuse existing `quota.monthlyBudgetUsd` field
   - Strategy checks budget remaining before selecting

3. **Hybrid Modes**
   - Failover + Budget: failover to next endpoint, each with budget cap
   - Load Balance + Health: weighted distribution with health-aware weight adjustment
