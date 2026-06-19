# MCP 生命周期管理计划

## 背景与目标

### 背景
当前 Sage 的 MCP（Model Context Protocol）实现在 `backend/mcp/` 中，提供基础的工具调用能力。但缺乏明确的生命周期管理，导致：
- 资源清理不可靠（进程崩溃时资源泄漏）
- 状态转换不清晰（难以调试）
- 健康检查缺失（无法自动恢复）
- 缺乏暂停/恢复能力

### 目标
借鉴 claw-code 的 MCP 生命周期文档，实现明确的生命周期管理：
1. 定义清晰的生命周期阶段（初始化 → 就绪 → 运行 → 暂停 → 恢复 → 终止）
2. 规定每个阶段的状态转换规则
3. 实现健康检查与自动恢复
4. 保证资源清理（即使进程崩溃）

## 涉及的文件与模块

### 当前模块
- `backend/mcp/` - MCP 核心实现
  - `backend/mcp/server.py` - MCP 服务器
  - `backend/mcp/tools.py` - 工具定义
  - `backend/mcp/context.py` - 上下文管理

### 修改/新增模块
- `backend/mcp/lifecycle.py` - 生命周期管理器
- `backend/mcp/health.py` - 健康检查
- `backend/mcp/state.py` - 状态机定义
- `backend/mcp/cleanup.py` - 资源清理保证
- `backend/mcp/recovery.py` - 自动恢复策略

## 技术方案

### 生命周期状态机

```
                    ┌──────────────┐
                    │   CREATED    │
                    └──────┬───────┘
                           │ initialize()
                           ▼
                    ┌──────────────┐
                    │ INITIALIZING │
                    └──────┬───────┘
                           │ on_ready()
                           ▼
                    ┌──────────────┐
              ┌─────│    READY     │<────┐
              │     └──────┬───────┘     │
              │            │ start()     │ resume()
              │            ▼             │
              │     ┌──────────────┐     │
              │     │   RUNNING    │─────┘
              │     └──────┬───────┘ pause()
              │            │
              │            │ pause()
              │            ▼
              │     ┌──────────────┐
              │     │   PAUSED     │
              │     └──────┬───────┘
              │            │ resume()
              │            ▼
              │     ┌──────────────┐
              └─────│   ERROR      │
                    └──────┬───────┘
                           │ shutdown()
                           ▼
                    ┌──────────────┐
                    │  SHUTTING    │
                    │    DOWN      │
                    └──────┬───────┘
                           │ cleanup()
                           ▼
                    ┌──────────────┐
                    │ TERMINATED   │
                    └──────────────┘
```

### 状态定义

```python
from enum import Enum, auto
from typing import Optional, Callable
import asyncio

class MCPState(Enum):
    CREATED = auto()
    INITIALIZING = auto()
    READY = auto()
    RUNNING = auto()
    PAUSED = auto()
    ERROR = auto()
    SHUTTING_DOWN = auto()
    TERMINATED = auto()

class MCPStateMachine:
    """MCP 状态机"""
    
    def __init__(self):
        self.state = MCPState.CREATED
        self.transitions = self._define_transitions()
        self.listeners = []
    
    def _define_transitions(self) -> dict:
        """定义合法的状态转换"""
        return {
            MCPState.CREATED: [MCPState.INITIALIZING],
            MCPState.INITIALIZING: [MCPState.READY, MCPState.ERROR],
            MCPState.READY: [MCPState.RUNNING, MCPState.SHUTTING_DOWN],
            MCPState.RUNNING: [MCPState.PAUSED, MCPState.ERROR, MCPState.SHUTTING_DOWN],
            MCPState.PAUSED: [MCPState.RUNNING, MCPState.SHUTTING_DOWN],
            MCPState.ERROR: [MCPState.SHUTTING_DOWN, MCPState.READY],  # 可恢复
            MCPState.SHUTTING_DOWN: [MCPState.TERMINATED],
            MCPState.TERMINATED: [],
        }
    
    def can_transition_to(self, target: MCPState) -> bool:
        """检查是否可以转换到目标状态"""
        return target in self.transitions.get(self.state, [])
    
    async def transition_to(self, target: MCPState, context: dict = None):
        """执行状态转换"""
        if not self.can_transition_to(target):
            raise InvalidStateTransition(
                f"Cannot transition from {self.state} to {target}"
            )
        
        old_state = self.state
        self.state = target
        
        # 通知监听器
        for listener in self.listeners:
            await listener.on_state_change(old_state, target, context)
```

### 生命周期管理器

```python
class MCPLifecycleManager:
    """MCP 生命周期管理器"""
    
    def __init__(self, config: MCPConfig):
        self.config = config
        self.state_machine = MCPStateMachine()
        self.health_checker = HealthChecker()
        self.resource_tracker = ResourceTracker()
        self.recovery_strategy = RecoveryStrategy()
        
        # 注册状态转换钩子
        self.state_machine.listeners.append(self)
    
    async def initialize(self):
        """初始化 MCP 服务"""
        await self.state_machine.transition_to(MCPState.INITIALIZING)
        
        try:
            # 加载配置
            await self._load_config()
            
            # 初始化资源
            await self._init_resources()
            
            # 注册清理钩子
            self._register_cleanup_hooks()
            
            await self.state_machine.transition_to(MCPState.READY)
        except Exception as e:
            await self.state_machine.transition_to(MCPState.ERROR, {"error": e})
            raise
    
    async def start(self):
        """启动 MCP 服务"""
        if self.state_machine.state != MCPState.READY:
            raise RuntimeError("MCP must be in READY state to start")
        
        await self.state_machine.transition_to(MCPState.RUNNING)
        
        # 启动健康检查
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        
        # 启动服务
        await self._start_service()
    
    async def pause(self):
        """暂停 MCP 服务"""
        if self.state_machine.state != MCPState.RUNNING:
            raise RuntimeError("MCP must be in RUNNING state to pause")
        
        await self.state_machine.transition_to(MCPState.PAUSED)
        
        # 暂停服务（释放资源但保持状态）
        await self._pause_service()
    
    async def resume(self):
        """恢复 MCP 服务"""
        if self.state_machine.state != MCPState.PAUSED:
            raise RuntimeError("MCP must be in PAUSED state to resume")
        
        await self.state_machine.transition_to(MCPState.RUNNING)
        
        # 恢复服务
        await self._resume_service()
    
    async def shutdown(self):
        """关闭 MCP 服务"""
        await self.state_machine.transition_to(MCPState.SHUTTING_DOWN)
        
        # 取消健康检查
        if hasattr(self, 'health_check_task'):
            self.health_check_task.cancel()
        
        # 清理资源
        await self._cleanup_resources()
        
        await self.state_machine.transition_to(MCPState.TERMINATED)
    
    async def _health_check_loop(self):
        """定期健康检查"""
        while self.state_machine.state == MCPState.RUNNING:
            try:
                is_healthy = await self.health_checker.check()
                if not is_healthy:
                    await self._handle_unhealthy()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check failed: {e}")
    
    async def _handle_unhealthy(self):
        """处理不健康状态"""
        logger.warning("MCP service unhealthy, attempting recovery")
        
        # 尝试自动恢复
        recovery_result = await self.recovery_strategy.attempt_recovery()
        
        if not recovery_result.success:
            logger.error("Recovery failed, transitioning to ERROR state")
            await self.state_machine.transition_to(MCPState.ERROR)
    
    def _register_cleanup_hooks(self):
        """注册清理钩子（保证即使进程崩溃也能清理）"""
        import atexit
        import signal
        
        # atexit 钩子
        atexit.register(lambda: asyncio.run(self._emergency_cleanup()))
        
        # 信号处理
        signal.signal(signal.SIGTERM, lambda s, f: asyncio.run(self.shutdown()))
        signal.signal(signal.SIGINT, lambda s, f: asyncio.run(self.shutdown()))
    
    async def _emergency_cleanup(self):
        """紧急清理（进程退出时）"""
        if self.state_machine.state != MCPState.TERMINATED:
            logger.warning("Emergency cleanup triggered")
            await self._cleanup_resources()
```

### 健康检查

```python
class HealthChecker:
    """健康检查器"""
    
    def __init__(self, checks: List[HealthCheck]):
        self.checks = checks
    
    async def check(self) -> bool:
        """执行所有健康检查"""
        results = await asyncio.gather(
            *[check.run() for check in self.checks],
            return_exceptions=True
        )
        
        # 所有检查必须通过
        return all(
            isinstance(r, HealthCheckResult) and r.healthy
            for r in results
        )

class ResourceHealthCheck(HealthCheck):
    """资源健康检查"""
    
    async def run(self) -> HealthCheckResult:
        """检查资源状态"""
        try:
            # 检查数据库连接
            db_healthy = await self._check_database()
            
            # 检查向量存储
            vector_healthy = await self._check_vector_store()
            
            # 检查内存使用
            memory_healthy = await self._check_memory()
            
            return HealthCheckResult(
                healthy=db_healthy and vector_healthy and memory_healthy,
                details={
                    "database": db_healthy,
                    "vector_store": vector_healthy,
                    "memory": memory_healthy
                }
            )
        except Exception as e:
            return HealthCheckResult(healthy=False, error=str(e))
```

### 自动恢复策略

```python
class RecoveryStrategy:
    """自动恢复策略"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.retry_count = 0
    
    async def attempt_recovery(self) -> RecoveryResult:
        """尝试恢复"""
        while self.retry_count < self.max_retries:
            self.retry_count += 1
            logger.info(f"Recovery attempt {self.retry_count}/{self.max_retries}")
            
            try:
                # 策略 1: 重启服务
                if self.retry_count == 1:
                    await self._restart_service()
                    return RecoveryResult(success=True)
                
                # 策略 2: 重建连接
                elif self.retry_count == 2:
                    await self._rebuild_connections()
                    return RecoveryResult(success=True)
                
                # 策略 3: 完整重启
                elif self.retry_count == 3:
                    await self._full_restart()
                    return RecoveryResult(success=True)
            
            except Exception as e:
                logger.error(f"Recovery attempt {self.retry_count} failed: {e}")
        
        return RecoveryResult(success=False, error="Max retries exceeded")
```

## 实施步骤

### 阶段 1：状态机实现（1 周）
- [ ] 1.1 定义 MCPState 枚举与状态转换规则
- [ ] 1.2 实现 MCPStateMachine
- [ ] 1.3 编写状态机单元测试
- [ ] 1.4 添加状态转换日志

### 阶段 2：生命周期管理器（1.5 周）
- [ ] 2.1 实现 MCPLifecycleManager 核心方法
- [ ] 2.2 实现 initialize/start/pause/resume/shutdown
- [ ] 2.3 注册清理钩子（atexit + signal）
- [ ] 2.4 编写生命周期集成测试
- [ ] 2.5 测试进程崩溃时的资源清理

### 阶段 3：健康检查与恢复（1.5 周）
- [ ] 3.1 实现 HealthChecker 框架
- [ ] 3.2 实现资源健康检查（数据库、向量存储、内存）
- [ ] 3.3 实现自动恢复策略
- [ ] 3.4 编写健康检查单元测试
- [ ] 3.5 编写恢复策略测试

### 阶段 4：集成与监控（1 周）
- [ ] 4.1 集成到现有 MCP 实现
- [ ] 4.2 添加监控指标（状态转换次数、恢复成功率）
- [ ] 4.3 实现管理 API（查询状态、手动恢复）
- [ ] 4.4 编写使用文档
- [ ] 4.5 压力测试与性能优化

## 风险评估与依赖

### 风险
| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 状态转换逻辑复杂 | 中 | 充分测试，状态转换日志 |
| 自动恢复可能掩盖问题 | 中 | 限制重试次数，记录恢复事件 |
| 资源清理不彻底 | 高 | 使用上下文管理器，双重保证 |
| 健康检查误判 | 中 | 多次确认，避免抖动 |

### 依赖
- asyncio（异步支持）
- signal（信号处理）
- atexit（清理钩子）

### 工作量估算
| 阶段 | 工作量 |
|------|--------|
| 状态机实现 | 1 周 |
| 生命周期管理器 | 1.5 周 |
| 健康检查与恢复 | 1.5 周 |
| 集成与监控 | 1 周 |
| **总计** | **5 周** |

## 验证标准

1. **状态转换验证**：所有非法状态转换都被拒绝
2. **资源清理验证**：进程崩溃时资源 100% 清理
3. **健康检查验证**：健康检查准确率 > 95%
4. **恢复验证**：自动恢复成功率 > 80%

## 示例场景

### 场景 1：正常生命周期
```
1. MCP 服务启动 → CREATED → INITIALIZING
2. 初始化完成 → READY
3. 用户触发启动 → RUNNING
4. 运行中定期健康检查
5. 用户触发暂停 → PAUSED
6. 用户触发恢复 → RUNNING
7. 用户触发关闭 → SHUTTING_DOWN → TERMINATED
```

### 场景 2：自动恢复
```
1. MCP 服务运行中
2. 健康检查发现数据库连接断开
3. 触发自动恢复
4. 重试 1: 重启服务 → 成功
5. 恢复到 RUNNING 状态
6. 记录恢复事件日志
```

### 场景 3：进程崩溃
```
1. MCP 服务运行中
2. 进程收到 SIGKILL（无法捕获）
3. atexit 钩子触发（如果可能）
4. 执行紧急清理
5. 释放数据库连接、文件句柄
6. 下次启动时检测并修复不一致状态
```

## 长期收益

1. **可靠性提升**：明确的资源清理保证
2. **可调试性**：清晰的状态转换日志
3. **自恢复能力**：减少人工干预
4. **可维护性**：标准化的生命周期管理
