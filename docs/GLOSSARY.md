# Sage 领域词汇表

> 日期：2026-09-21
> 状态：强制约束
> 用途：统一 Sage 项目的领域术语，避免歧义和误读

## 核心术语

### Office

**正确定义**：用户文档工作区（Office CRUD 的抽象）。Office 是一个逻辑容器，包含多个文档和工具配置。

**常见误读/禁用词**：
- ❌ 不要与 Office Template 混淆（Template 是 Office 的初始化配置）
- ❌ 不要与 Office Tool 混淆（Tool 是 Office 内的具体工具）

---

### Office Tool

**正确定义**：工具集中的具体工具（`office_read` / `office_write` / `office_list` / `office_archive`）。Office Tool 是 Office 子系统暴露给 Agent 的操作接口。

**常见误读/禁用词**：
- ❌ 不要简称 "office"（Office 是容器，Office Tool 是工具）
- ❌ 不要与 Sandbox Tool 混淆（Sandbox Tool 是 profile 白名单暴露的工具集合）

---

### Sandbox Tool

**正确定义**：由 profile 白名单暴露给 agent 的工具集合。不是所有内置工具都是 sandbox tool——只有被 profile 显式允许的工具才会出现在 agent 的工具列表中。

**常见误读/禁用词**：
- ❌ 不要等同于 "所有内置工具"（内置工具需要 profile 白名单才能暴露）
- ❌ 不要与 MCP Server 混淆（MCP Server 是外部进程通信协议实例）

---

### Agent Profile

**正确定义**：定义 agent 可见工具集 + 系统 prompt 的配置对象。Profile 决定 agent 能看见什么工具、不能看见什么工具。

**常见误读/禁用词**：
- ❌ 不要与 agent 混淆（agent 是运行时实例，profile 是配置）
- ❌ 不要与 "角色" 混淆（profile 是技术配置，不是人设）

---

### Scheduler

**正确定义**：`SchedulerService` + `register_evolution_task`（apscheduler 3.10.4 驱动）。Scheduler 是定时任务调度系统，支持周期性任务和一次性任务。

**常见误读/禁用词**：
- ❌ 不要叫 cron（`cron.py` 已删除，Scheduler 是基于 apscheduler 的）
- ❌ 不要与 "定时任务" 混淆（定时任务是 Scheduler 调度的具体任务，Scheduler 是调度器本身）

---

### Working Memory

**正确定义**：`WorkingMemory` 实例——**非单例**，必须通过 `agent.memory_manager.working` 共享。Working Memory 存储当前会话的短期记忆。

**常见误读/禁用词**：
- ❌ **严禁**直接 `WorkingMemory()` 新建实例（会创建空实例，导致 context_reset 串味）
- ❌ 不要与 "长期记忆" 混淆（Working Memory 是短期的，Long-term Memory 是持久的）

**正确用法**：
```python
# ✅ 正确：通过 agent 的 memory_manager 访问
working_memory = agent.memory_manager.working

# ❌ 错误：直接新建实例
working_memory = WorkingMemory()  # 会创建空实例！
```

---

### Arena

**正确定义**：模型评测池（CDP + 账户池）。Arena 用于自动化评测不同模型的表现，默认已隐藏（PR #1347/#1349）。

**常见误读/禁用词**：
- ❌ 不要与 "测试环境" 混淆（Arena 是产品功能，不是开发测试）
- ❌ 不要认为 Arena 是主路径（Arena 已默认隐藏，不是常用功能）

---

### MCP Server

**正确定义**：外部进程通信协议实例（Model Context Protocol）。MCP Server 是独立进程，通过标准协议与 Sage 通信，提供额外工具能力。

**常见误读/禁用词**：
- ❌ 不要与 builtin tool 混淆（builtin tool 是内置工具，MCP Server 是外部进程）
- ❌ 不要与 "插件" 混淆（插件是更高层的抽象，MCP Server 是底层协议）

---

### Lockstep

**正确定义**：双分支版本号同步（main + release/win7）。Lockstep 仅对 `package.json` + `CHANGELOG`，不应用于功能性改动。

**常见误读/禁用词**：
- ❌ 不要用于功能性改动的同步（功能性改动应该 cherry-pick，不是 lockstep）
- ❌ 不要与 "合并分支" 混淆（lockstep 只同步版本号，不合并代码）

---

### Cherry-pick

**正确定义**：单/批 commit 跨分支搬运。Cherry-pick 是双分支同步的主要手段，用于将功能性改动从一个分支搬到另一个分支。

**常见误读/禁用词**：
- ❌ 不要用 `merge release → develop`（会带入 release 元数据，如版本号、CHANGELOG）
- ❌ 不要与 "合并" 混淆（cherry-pick 是选择性搬运，merge 是全量合并）

**正确用法**：
```bash
# ✅ 正确：cherry-pick 单个 commit
git cherry-pick abc1234

# ❌ 错误：merge release 分支
git merge release/win7  # 会带入 release 元数据！
```

---

## 术语关系图

```
Office (容器)
  └─ Office Tool (office_read / office_write / office_list / office_archive)

Agent Profile (配置)
  └─ Sandbox Tool (profile 白名单暴露的工具集合)
       ├─ Office Tool
       ├─ Builtin Tool
       └─ MCP Server (外部进程)

Scheduler (调度器)
  └─ Scheduled Task (定时任务)

Working Memory (短期记忆)
  └─ 必须通过 agent.memory_manager.working 访问
```