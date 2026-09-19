# 2026-09-19 Sage Hooks 系统优化方案

> **状态**：Phase 1 已完成 ✅ (feat/hooks-builtin-phase1)
> **作者**：Claude (Fable 5)
> **背景**：当前 M6 生态扩展（hooks 子系统）已实现基础框架，但缺少内置 hook、事件类型不足、配置层级单一。参考主流 AI 应用后提出以下优化方案。

---

## 1. 现状分析

### 1.1 当前架构（已完成）

| 维度 | 现状 |
|------|------|
| **事件类型** | 4 种：`pre_tool_use` / `post_tool_use` / `user_prompt_submit` / `stop` |
| **配置存储** | SQLite `preferences` 表，`"hooks"` 键，JSON 数组 |
| **通信协议** | Shell 命令 + stdin JSON → stdout JSON |
| **匹配器** | fnmatch glob（`*` / `Bash` / `Write*`） |
| **决策模型** | `allow` / `deny` / `modify` / `noop`（fail-open） |
| **配置层级** | 仅用户级（全局） |
| **内置 hook** | **无** |

### 1.2 核心问题

| # | 问题 | 影响 |
|---|------|------|
| P1 | 无内置 hook，用户从零配置 | 功能形同虚设，99% 用户不会手写 shell 脚本 |
| P2 | 缺少会话生命周期事件 | 无法在启动时注入上下文、结束时清理资源 |
| P3 | 无 HTTP hook 支持 | 无法对接外部系统（CI/CD、审批流、合规平台） |
| P4 | `post_tool_use` 只能观察，无法注入反馈 | AI 无法从 hook 获取纠正信息（如 lint 报错） |
| P5 | 无项目级 hook | 团队无法共享统一策略（如禁止 rm -rf） |
| P6 | 无错误事件 | 无法在 AI 出错时自动触发修复/告警流程 |
| P7 | 无通知/展示能力 | hook 结果不透明，用户不知道被拦截了什么 |

---

## 2. 主流 AI 应用 Hook 对标

| 产品 | 事件数 | 配置层级 | HTTP hook | 内置模板 | 反馈注入 |
|------|--------|----------|-----------|----------|----------|
| **Claude Code** | 30+ | User + Project | ❌ | ❌（示例驱动） | ✅ `additionalContext` |
| **Windsurf** | 12 | User + Project + Team | ✅ | ✅ 企业策略模板 | ✅ |
| **GitHub Copilot** | 6 | User + Project | ❌ | ❌ | ✅ `continue` 控制流 |
| **Continue.dev** | 17 | User | ✅ | ❌ | ✅ |
| **Cursor** | 0 | User + Project | ❌ | ❌（仅 rules） | ❌ |
| **Sage（当前）** | 4 | User only | ❌ | ❌ | ❌ |

**结论**：Sage 在事件丰富度、配置层级、反馈能力三个维度全面落后。但"fail-open + JSON 协议"的基础设计是行业共识，不需要推倒重来。

---

## 3. 优化方案

### 3.1 Phase 1：内置 Hook 模板（解决 P1，优先级最高）

**目标**：用户打开设置页，一键启用常用 hook，零配置上手。

#### 内置 Hook 列表

| 名称 | 事件 | matcher | 功能 | 实现方式 |
|------|------|---------|------|----------|
| **安全守卫** | `pre_tool_use` | `Bash` | 拦截 `rm -rf /`、`sudo`、`curl \| sh` 等危险命令 | 内置 Python 检查器 |
| **文件写后格式化** | `post_tool_use` | `Write\|Edit` | 自动运行 Prettier / Black / ruff format | Shell 命令模板 |
| **Git 提交规范** | `pre_tool_use` | `Bash` | 检查 commit message 是否符合 Conventional Commits | Shell 命令模板 |
| **敏感信息拦截** | `pre_tool_use` | `Write\|Edit` | 拦截含 API key / 密码 / token 的文件写入 | 内置 Python 检查器 |
| **成本预警** | `stop` | `*` | 单次会话 token 超阈值时通知用户 | 内置 Python 计数器 |
| **操作审计日志** | `post_tool_use` | `*` | 记录所有工具调用到 `~/.sage/audit.jsonl` | 内置 Python 写入器 |

#### 数据结构

```python
# backend/hooks/builtin.py（新建）

BUILTIN_HOOKS = {
    "security_guard": {
        "id": "security_guard",
        "name": "安全守卫",
        "description": "拦截危险 Shell 命令（rm -rf /、sudo、curl|sh 等）",
        "event": "pre_tool_use",
        "matcher": "Bash",
        "type": "python",           # "python" | "shell" | "http"
        "handler": "sage.hooks.builtin.security_guard",
        "enabled": False,           # 默认关闭，用户手动启用
        "config": {
            "blocklist": ["rm -rf /", "sudo", "mkfs", ":(){:|:&};:"],
            "require_confirm": ["curl", "wget", "ssh"],
        }
    },
    "sensitive_data_guard": {
        "id": "sensitive_data_guard",
        "name": "敏感信息拦截",
        "description": "阻止写入含 API key、密码、token 的文件",
        "event": "pre_tool_use",
        "matcher": "Write|Edit",
        "type": "python",
        "handler": "sage.hooks.builtin.sensitive_data_guard",
        "enabled": False,
        "config": {
            "patterns": [
                r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][\w-]{16,}",
                r"AKIA[0-9A-Z]{16}",               # AWS
                r"ghp_[0-9a-zA-Z]{36}",             # GitHub PAT
                r"sk-[0-9a-zA-Z]{32,}",             # OpenAI
            ]
        }
    },
    "auto_format": {
        "id": "auto_format",
        "name": "文件写后格式化",
        "description": "文件写入后自动运行格式化工具",
        "event": "post_tool_use",
        "matcher": "Write|Edit",
        "type": "shell",
        "command": "sage-format-on-save",  # 内置 wrapper 脚本
        "enabled": False,
        "config": {
            "formatters": {
                "*.py": "ruff format {file}",
                "*.ts": "prettier --write {file}",
                "*.js": "prettier --write {file}",
                "*.md": "prettier --write {file}",
            }
        }
    },
    "audit_log": {
        "id": "audit_log",
        "name": "操作审计日志",
        "description": "记录所有工具调用到审计日志文件",
        "event": "post_tool_use",
        "matcher": "*",
        "type": "python",
        "handler": "sage.hooks.builtin.audit_logger",
        "enabled": False,
        "config": {
            "log_path": "~/.sage/audit.jsonl",
            "max_size_mb": 50,
        }
    },
    "cost_alert": {
        "id": "cost_alert",
        "name": "成本预警",
        "description": "单次会话 token 消耗超阈值时通知",
        "event": "stop",
        "matcher": "*",
        "type": "python",
        "handler": "sage.hooks.builtin.cost_alert",
        "enabled": False,
        "config": {
            "threshold_tokens": 100000,
            "notification": "ui",     # "ui" | "sound" | "both"
        }
    },
}
```

#### 前端 UI 变更

`HooksCard.tsx` 新增 **"推荐 Hook"** 区域：

```
┌─────────────────────────────────────────────────┐
│ 推荐 Hook                                       │
├─────────────────────────────────────────────────┤
│ 🔒 安全守卫              [启用]                  │
│    拦截危险 Shell 命令                            │
│                                                 │
│ 🛡️ 敏感信息拦截          [启用]                  │
│    阻止写入 API key / 密码                        │
│                                                 │
│ 📝 文件写后格式化          [启用]                  │
│    自动运行 Prettier / Black                      │
│                                                 │
│ 📊 操作审计日志            [启用]                  │
│    记录所有工具调用                               │
│                                                 │
│ 💰 成本预警               [启用]                  │
│    Token 超阈值时通知                             │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ 自定义 Hook                                     │
├─────────────────────────────────────────────────┤
│ + 添加 Hook                                     │
│  (现有的 CRUD 表格)                               │
└─────────────────────────────────────────────────┘
```

#### 涉及文件（Phase 1）

| 文件 | 变更 |
|------|------|
| `backend/hooks/builtin.py` | **新建**，内置 hook 注册表 |
| `backend/hooks/builtin_guards.py` | **新建**，`security_guard` + `sensitive_data_guard` 实现 |
| `backend/hooks/builtin_formatter.py` | **新建**，`auto_format` 实现 |
| `backend/hooks/builtin_audit.py` | **新建**，`audit_logger` 实现 |
| `backend/hooks/builtin_cost.py` | **新建**，`cost_alert` 实现 |
| `backend/hooks/config.py` | 修改，`HookConfig` 新增 `type` 字段 + `builtin_id` 字段 |
| `backend/hooks/runner.py` | 修改，支持 `type: "python"` 直接调用 Python 函数（不走 subprocess） |
| `backend/hooks/__init__.py` | 修改，导出内置 hook 注册表 |
| `src/widgets/settings/HooksCard.tsx` | 修改，新增"推荐 Hook"区域 |
| `backend/tests/unit/test_hooks_builtin.py` | **新建**，内置 hook 测试 |

---

### 3.2 Phase 2：新增生命周期事件（解决 P2 + P6）

#### 新增事件

```python
HOOK_EVENTS = (
    "session_start",        # 新增：会话开始（Agent 创建时）
    "session_stop",         # 新增：会话结束（替代原 stop，语义更明确）
    "pre_tool_use",         # 已有
    "post_tool_use",        # 已有
    "user_prompt_submit",   # 已有
    "error_occurred",       # 新增：工具执行失败 / LLM 报错时
    "stop",                 # 已有，保持兼容
)
```

#### 各事件 Payload 设计

```python
# session_start
{
    "hook_event_name": "session_start",
    "session_id": "uuid",
    "model": "claude-sonnet-4-20250514",
    "workspace": "/home/fz/project/sage",
    "git_branch": "feat/hooks-optimization",
    "timestamp": "2026-09-19T10:30:00Z"
}

# error_occurred
{
    "hook_event_name": "error_occurred",
    "error_type": "tool_execution_failed",  # "llm_error" | "tool_error" | "parse_error"
    "tool_name": "Bash",
    "error_message": "Command exited with code 1",
    "error_traceback": "...",               # 可选，截断到 4KB
    "attempt_count": 1,                     # 当前重试次数
    "session_id": "uuid",
    "timestamp": "2026-09-19T10:30:00Z"
}
```

#### 集成点

| 事件 | 触发位置 | 能否拦截 |
|------|----------|----------|
| `session_start` | `agent.py` `__init__` 或首次 `run()` | ❌ 仅观察 |
| `session_stop` | `legacy_routes.py` 会话销毁时 | ❌ 仅观察 |
| `error_occurred` | `agent.py` 异常捕获处（L1287 附近） | ❌ 仅观察 + 反馈注入 |

#### 涉及文件（Phase 2）

| 文件 | 变更 |
|------|------|
| `backend/hooks/config.py` | `HOOK_EVENTS` 新增 3 项 |
| `backend/hooks/runner.py` | `build_payload` 支持新事件的 payload 结构 |
| `backend/core/legacy/agent.py` | 在 `__init__` / 异常捕获处插入 hook 调用 |
| `backend/api/legacy_routes.py` | `session_stop` 调用点 |
| `src/widgets/settings/HooksCard.tsx` | 事件下拉菜单新增选项 |

---

### 3.3 Phase 3：PostToolUse 反馈注入（解决 P4）

**核心思路**：`post_tool_use` 的 hook 输出可以携带 `additional_context` 字段，
注入回 AI 的下一轮上下文，让 AI 看到 hook 的反馈。

#### 协议扩展

```python
# 当前 post_tool_use stdout 协议（仅观察，不影响 AI）
{"decision": "allow"}  # 唯一用途

# 扩展后（Phase 3）
{
    "decision": "allow",
    "additional_context": "ruff 检测到 3 个问题：F401 未使用的导入 (line 5, 12, 18)。建议删除。",
    "severity": "info"   # "info" | "warning" | "error"
}
```

#### 实现机制

```python
# agent.py 中 post_tool_use 后
outcome = run_event_hooks(hooks, "post_tool_use", tool_name, tool_input, tool_output)

# 如果有 additional_context，注入到 working memory
if outcome.additional_context:
    agent.working_memory.add(WorkingMemoryItem(
        source="hook_feedback",
        content=f"[Hook 反馈] {outcome.additional_context}",
        tool_name=tool_name,
        severity=outcome.severity,
    ))
```

#### 典型用例

| Hook | 触发 | 反馈内容 |
|------|------|----------|
| `auto_format` | 写完 .py 文件 | "已自动格式化，修改了 3 行" |
| `lint_check` | 写完 .ts 文件 | "ESLint 检测到 2 个 error + 5 个 warning" |
| `type_check` | 写完 .ts 文件 | "TypeScript 编译通过" / "类型错误: Property 'x' does not exist" |
| `security_scan` | 写完含 SQL 的文件 | "检测到字符串拼接 SQL，建议使用参数化查询" |

#### 涉及文件（Phase 3）

| 文件 | 变更 |
|------|------|
| `backend/hooks/runner.py` | `HookOutcome` 新增 `additional_context` + `severity` |
| `backend/core/legacy/agent.py` | post_tool_use 后检查并注入 working memory |
| `backend/core/working_memory.py` | 新增 `source="hook_feedback"` item 类型 |

---

### 3.4 Phase 4：多级配置合并（解决 P5）

#### 三级配置

```
优先级（高→低）：
  Team 级  >  Project 级  >  User 级

Team 级:    企业管理员通过 API 下发（远期，Phase 4b）
Project 级: <repo>/.sage/hooks.json（提交到 Git，团队共享）
User 级:    SQLite preferences（现有机制）
```

#### Project 级配置文件

```json
// .sage/hooks.json（提交到 Git）
{
    "version": 1,
    "hooks": [
        {
            "event": "pre_tool_use",
            "matcher": "Bash",
            "command": "scripts/check-dangerous-commands.sh",
            "timeout_seconds": 5,
            "scope": "project"
        },
        {
            "event": "post_tool_use",
            "matcher": "Write|Edit",
            "matcher_scope": "project",
            "command": "npm run lint:fix",
            "timeout_seconds": 15
        }
    ],
    "builtin_overrides": {
        "security_guard": {
            "enabled": true,
            "config": {
                "blocklist": ["rm -rf /", "sudo", "dd if="]
            }
        }
    }
}
```

#### 合并逻辑

```python
def load_hooks_merged(settings_repo, workspace_path: str) -> list[HookConfig]:
    """三级合并：User ← Project ← (Team, 远期)"""
    user_hooks = load_hooks(settings_repo)                    # 现有逻辑
    project_hooks = load_project_hooks(workspace_path)         # 新增
    # team_hooks = load_team_hooks(enterprise_api)             # 远期

    merged = []

    # 1. 项目级 hook 优先（团队策略不可被用户覆盖）
    merged.extend(project_hooks)

    # 2. 用户级 hook（个人定制）
    for uh in user_hooks:
        if not any(ph.conflicts_with(uh) for ph in project_hooks):
            merged.append(uh)

    # 3. 内置 hook 覆盖（项目可强制启用/禁用内置 hook）
    apply_builtin_overrides(merged, project_hooks)

    return merged
```

#### 安全约束

- 项目级 `pre_tool_use` hook **不能** 禁用用户级 `deny` 规则（防团队策略绕过用户安全设置）
- 项目级 hook 中 `command` 路径必须以 `${workspace}/` 开头或为全局命令名（防路径穿越）
- `.sage/hooks.json` 加载时需要用户确认（首次进入项目时弹通知）

#### 涉及文件（Phase 4）

| 文件 | 变更 |
|------|------|
| `backend/hooks/config.py` | 新增 `load_project_hooks()` + `HookConfig.scope` |
| `backend/hooks/merger.py` | **新建**，三级合并逻辑 |
| `backend/core/legacy/agent.py` | 改用 `load_hooks_merged()` |
| `docs/technical/XX-hooks-project-config.md` | **新建**，项目级配置文档 |

---

### 3.5 Phase 5：HTTP Hook 支持（解决 P3，远期）

#### 配置格式扩展

```json
{
    "event": "pre_tool_use",
    "matcher": "Bash",
    "type": "http",
    "url": "https://hooks.company.com/sage/validate",
    "method": "POST",
    "headers": {
        "Authorization": "Bearer ${env:COMPANY_HOOK_TOKEN}"
    },
    "timeout_seconds": 5
}
```

#### 协议

```
POST https://hooks.company.com/sage/validate
Content-Type: application/json

{
    "hook_event_name": "pre_tool_use",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf build/"},
    "session_id": "...",
    "timestamp": "..."
}

Response (200):
{
    "decision": "deny",
    "reason": "危险命令被企业安全策略拦截",
    "escalation_url": "https://company.com/approvals/request/123"
}
```

#### 涉及文件（Phase 5）

| 文件 | 变更 |
|------|------|
| `backend/hooks/runner.py` | `run_hook()` 支持 `type: "http"` 分支 |
| `backend/hooks/http_client.py` | **新建**，带连接池的 HTTP hook 客户端 |
| `src/widgets/settings/HooksCard.tsx` | 新增 HTTP hook 配置表单 |

---

### 3.6 Phase 6：Hook 诊断与可视化（解决 P7）

#### Hook 执行历史

```python
# backend/hooks/history.py（新建）

class HookExecutionRecord:
    hook_id: str
    event: str
    tool_name: str
    decision: str        # "allow" | "deny" | "modify" | "noop" | "error"
    duration_ms: float
    reason: str | None
    timestamp: datetime       # ISO 8601: "2026-09-19T10:30:00.123Z"
    stdout_snippet: str  # 截断到 1KB
    stderr_snippet: str  # 截断到 1KB
```

存储：SQLite `hook_executions` 表，保留最近 7 天 / 1000 条。

#### 前端 UI 新增 Hook 面板

```
┌─────────────────────────────────────────────────┐
│ Hook 执行历史                              [清空] │
├─────────────────────────────────────────────────┤
│ 🔴 10:23:15  安全守卫 → Bash              12ms  │
│    DENY: 拦截 `rm -rf /tmp/build`               │
│                                                 │
│ 🟢 10:23:14  auto_format → Write          245ms │
│    ALLOW: 格式化 main.py (3 行变更)              │
│                                                 │
│ 🟢 10:23:10  审计日志 → Bash               3ms  │
│    LOG: 记录到 ~/.sage/audit.jsonl               │
│                                                 │
│ 🟡 10:22:58  lint_check → Write          1.2s   │
│    WARN: ESLint 3 errors, 5 warnings            │
└─────────────────────────────────────────────────┘
```

#### 涉及文件（Phase 6）

| 文件 | 变更 |
|------|------|
| `backend/hooks/history.py` | **新建**，执行记录存储 |
| `backend/hooks/runner.py` | 每次执行写入 `hook_executions` 表 |
| `backend/api/legacy_routes.py` | 新增 `GET /api/v1/hooks/history` 端点 |
| `src/widgets/settings/HookHistoryPanel.tsx` | **新建**，历史面板组件 |

---

## 4. 实施路线图

```
Phase 1  ─── 内置 Hook 模板 ──────────── 1.5 周
  │  T1: builtin.py 注册表 + config.py 扩展        [2d]
  │  T2: security_guard + sensitive_data_guard     [2d]
  │  T3: auto_format + audit_logger + cost_alert   [2d]
  │  T4: HooksCard.tsx "推荐 Hook" UI              [2d]
  │  T5: 单元测试                                   [1d]
  │
Phase 2  ─── 生命周期事件 ──────────── 1 周
  │  T6: session_start + session_stop              [2d]
  │  T7: error_occurred                            [2d]
  │  T8: agent.py 集成 + 测试                      [1d]
  │
Phase 3  ─── PostToolUse 反馈注入 ──── 1 周
  │  T9: HookOutcome 扩展 + additional_context     [2d]
  │  T10: working_memory 注入机制                  [2d]
  │  T11: 端到端测试                                [1d]
  │
Phase 4  ─── 多级配置 ─────────────── 1 周
  │  T12: .sage/hooks.json 加载 + 合并逻辑         [3d]
  │  T13: 安全约束 + 用户确认流程                  [2d]
  │
Phase 5  ─── HTTP Hook ────────────── 1 周（远期）
  │  T14: HTTP hook runner + 连接池                [3d]
  │  T15: UI 配置表单 + 环境变量替换               [2d]
  │
Phase 6  ─── 诊断与可视化 ────────── 1 周（远期）
  │  T16: hook_executions 表 + history.py          [2d]
  │  T17: HookHistoryPanel UI                      [2d]
  │  T18: API 端点 + 集成测试                      [1d]
```

**总计**：~6.5 周（Phase 1-3 为 3.5 周，可解决 80% 的核心问题）

---

## 5. 与现有架构的兼容性

| 维度 | 兼容性 |
|------|--------|
| **数据迁移** | 无需迁移。`HookConfig` 新增字段用默认值填充 |
| **API 兼容** | 现有 4 事件的 payload 格式不变 |
| **前端兼容** | `HooksCard.tsx` 增量扩展，不重写 |
| **fail-open 原则** | 保持。所有新事件/新类型同样遵循 fail-open |
| **并行执行** | Phase 1 内置 hook 中的 `type: "python"` 走进程内调用，不触发 subprocess，性能更优 |

---

## 6. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 内置 hook 中的 Python 检查器引入 bug | 中 | 全部 fail-open + 充分单元测试 |
| `additional_context` 注入污染 AI 上下文 | 中 | 限制总长度 ≤ 2KB；标记 `source="hook_feedback"` 便于 AI 辨别 |
| 项目级 hook 被恶意仓库利用 | 高 | 首次加载必须用户确认；command 路径白名单 |
| HTTP hook 延迟拖慢 agent loop | 高 | 强制超时上限 10s；连接池 + 重试退避 |
| `error_occurred` 事件风暴（大量错误时） | 低 | 同一 session 内限流：10 次/分钟 |

---

## 7. 实施步骤

- [x] Phase 1, Step 1：新建 `backend/hooks/builtin.py` 注册表，扩展 `HookConfig` 支持 `type` 字段
- [x] Phase 1, Step 2：实现 `security_guard` + `sensitive_data_guard`（`builtin_guards.py`）
- [x] Phase 1, Step 3：实现 `audit_logger`（`builtin_audit.py`）
- [x] Phase 1, Step 4：实现 `cost_alert`（`builtin_cost.py`）
- [x] Phase 1, Step 5：修改 `runner.py` 支持 `type: "python"` 进程内调用 + 注册表默认配置合并
- [x] Phase 1, Step 6：`HooksCard.tsx` 新增"推荐 Hook"区域 + 一键启用
- [x] Phase 1, Step 7：编写 `test_hooks_builtin.py` (61 用例) + `test_hooks_routes.py` (4 用例) + HooksCard 测试 (10 用例)
- [x] 额外修复：`matches_tool` 支持 `|` 交替语法；内置 matcher 对齐真实工具名（`bash` / `write_file` / `edit_file` / `apply_patch`）
- [x] Phase 2, Step 1：`HOOK_EVENTS` 新增 `session_start` / `session_stop` / `error_occurred`
- [x] Phase 2, Step 2：`build_session_payload` / `build_error_payload` + `run_event_hooks_sync` 同步桥接
- [x] Phase 2, Step 3：`agent._maybe_fire_error_hook` 集成（串行 + 并行两条路径）
- [x] Phase 2, Step 4：`legacy_session_routes.py` 集成 `session_start` / `session_stop`
- [x] Phase 3, Step 1：`HookOutcome` 新增 `additional_context` + `severity` + `has_feedback`
- [x] Phase 3, Step 2：`agent.py` post_tool_use 后注入 `system` 消息到对话历史（串行 + 并行）
- [x] Phase 3, Step 3：端到端测试（hook → additional_context → 对话历史可见）
- [ ] Phase 4, Step 1：`.sage/hooks.json` 加载 + `load_project_hooks()`
- [ ] Phase 4, Step 2：`merger.py` 三级合并逻辑 + 安全约束
- [ ] Phase 5, Step 1：`http_client.py` + `run_hook()` HTTP 分支
- [ ] Phase 6, Step 1：`history.py` + `hook_executions` 表 + API 端点 + UI 面板
