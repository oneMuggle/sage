# 编码代理对标差距分析·第九轮：子代理档案文件化（2026-09-11）

- **状态**：批次 A 已交付（分支 `feat/parity-r9-batch-a`，基线 origin/main 597e89e3 = #610）
- **上游文档**：round8（执行前确认与失败后恢复，批次 A/B 已交付 main #598/#600、win7 #604）——本轮从"执行生命周期"转到**可定制性/可版本化**维度；与会话/skills/gateway 域的 hermes 对标系列（#607-#610，另一工作流）无交叠
- **对标对象**：Claude Code（custom agents：`.claude/agents/*.md`，frontmatter + system prompt 正文，随项目走、可进 git、可分享）、Cursor（项目级 rules/modes 文件化）
- **编号约定**：本轮用 **CA 系**（Custom Agents as files）
- **方法**：在最新 main（#610 后）复核 agents 面全部入口，逐条附 file:line

## 0. 结论速览

Sage 的子代理档案（AgentProfile）是**纯数据库资产**：默认种子在启动时落库（`main.py:315` → `ensure_default_agents`），增改走 REST（`legacy_routes.py:849-965` GET/POST/PATCH/toggle）+ EditAgentForm UI。对比 Claude Code 的 `.claude/agents/*.md` 模式，缺的是：

1. **CA1 无文件化定义**：无法用 markdown 在仓库里定义子代理（随项目走、可 review、可分享）；换机器/换项目无法文件携带。`agents/profiles.py` 全文无任何文件发现/导入逻辑（仅 DB 种子）。
2. **CA2 无导出**：DB 里调好的档案（system_prompt/tools/迭代上限）无法导出为文件——"UI 调优 → 文件固化 → 进 git"链路断在第一步。
3. **CA3 无体检**：`.sage/agents/` 若出现坏文件（frontmatter 缺字段/非法工具名），没有启动期/doctor 期告警，用户只能等派发时失败。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| CA1 | 子代理无 markdown 文件定义/发现/导入 | `agents/profiles.py`（无文件逻辑）；全库无 `.sage/agents` 引用 | Claude Code `.claude/agents/*.md` | **P1** |
| CA2 | 档案无导出为文件通路 | `legacy_routes.py:849-965`（仅 GET/POST/PATCH/toggle） | 同上（文件即真相） | **P1** |
| CA3 | 坏档案文件无 doctor 体检 | `backend/cli/checks/`（mcp_servers.py 等，无 agents 检查） | Claude Code 启动期 agent 校验 | P2 |
| — | 已具备：DB 档案 + 种子化 + UI 管理（EditAgentForm）+ validate_profile_tools 工具名校验（profiles.py:534）+ AgentRepository.upsert/update/set_enabled | `data/agent_repo.py:43-117` | — | 不再建设 |

## 2. 设计（批次 A：CA1-CA3）

- **文件格式**（`.sage/agents/<agent_id>.md`，agent_id = 文件名 stem 经 `[a-z0-9_-]` 清洗小写）：
  frontmatter 键值（`name`/`role`/`description`/`tools`（逗号分隔）/`memory_access`（逗号分隔）/`max_iterations`/`enabled`/`model`/`temperature`/`max_tokens`）+ `---` 分隔 + system prompt 正文。**stdlib-only 解析**（与 doctor 纪律一致，不引 yaml）。
- **发现目录**：env `SAGE_AGENTS_DIR` > `<cwd>/.sage/agents`；目录不存在 = 零导入（不告警）。
- **导入语义**：逐文件解析 → 与 DB 现值**逐字段比对**，有差异才 upsert（不碰 `enabled` 以外的用户态？——保留 DB `enabled`，文件不覆盖开关态）；解析失败计 errors 不中断其余文件。启动时在 `ensure_default_agents()` 之后调用；`POST /agents/import-files` 手动重扫。
- **导出语义**：`POST /agents/{agent_id}/export` → 以档案现值写 `<dir>/<agent_id>.md`（覆盖写，"导出即固化"）；目录不存在自动创建。
- **doctor**：`cli/checks/agents_files.py`（stdlib-only）——扫描目录、校验 frontmatter 必填（name 缺省取 stem）、tools 未知名告警（不经 DB，白名单从 tool_names 常量集？——doctor 纪律 stdlib-only，不做工具名校验，只查结构：frontmatter 可解析 + 正文非空 + id 合法）。

## 3. 批次 A 实施与验证记录（2026-09-11）

- **CA1**：新模块 `backend/agents/agents_files.py`——`agents_dir()`（env `SAGE_AGENTS_DIR` > `<cwd>/.sage/agents`）、`parse_agent_file()`（stdlib frontmatter 解析：未闭合/空正文/非法字段计 `AgentsFileError`；未知键忽略向前兼容）、`import_agents_from_files()`（逐字段比对有差异才 upsert；`enabled` 保留 DB 现值；坏文件计 errors 不中断不抛出；目录不存在全空 no-op）。`main.py` lifespan 在 `validate_profile_tools()` 之后调用，导入/告警仅日志，失败降级不阻塞启动。
- **CA2**：`export_agent_to_file()`（DB 现值 → markdown 覆盖写，目录自动创建）；端点 `POST /agents/import-files`（200 + imported/unchanged/errors）与 `POST /agents/{agent_id}/export`（200 + path / 404）。
- **CA3**：`backend/cli/checks/agents_files.py`（stdlib-only：frontmatter 闭合/行冒号/正文非空），注册进 `_import_all_checks` 模块清单；目录不存在 → INFO（正常态），坏文件 → WARN（前 3 条进消息）。
- 测试：`test_agents_files.py` 14 例（解析 6 + 导入 3 + 导出 roundtrip/404 2 + 端点 1 + doctor 1 + 目录 env 1）；agent/profiles/doctor/cli 回归面 231 passed——4 个失败与基线 stash 对照完全一致（doctor 2 + skill_md runner + wiki symlink，本地 Windows 环境既有）；ruff 全过；全仓收集 6590 用例零收集错误。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
