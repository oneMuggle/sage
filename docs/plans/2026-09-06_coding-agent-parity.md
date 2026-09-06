# 编码代理功能对标与增强方案（2026-09-06）

- **状态**：Phase-1 已交付（#440/#441）；Phase-2 已交付（G3/G4/G5/G6/G8/G9/G10，#443/#444/#447）—— 仅剩 G7 浏览器自动化（需 Electron 跨端里程碑）
- **对标对象**：ZCode（CLI 编码代理）、Qoder（Agentic 编码 IDE）、Codex（OpenAI 编码代理）
- **范围**：main 落地后 cherry-pick 对齐 `release/win7`（沿用 PR #402→#404 惯例路径）

## 1. 现状盘点（Sage 已有能力，不重复建设）

| 能力域 | 现状 | 证据 |
| --- | --- | --- |
| 执行三件套 | bash / bash_output / kill_shell + repl | tools/bash_tool.py（2026-09-04 优化） |
| 文件读写与搜索 | read/write/edit/list/grep/glob/file_summary | tools/file_tool.py 等 |
| 子代理编排 | agent 工具（只读子代理白名单）、orchestration 页 | tools/agent_tool.py |
| 任务清单 | todo_write | tools/todo_tool.py |
| 结构化输出 | structured_output | tools/structured_output_tool.py |
| 技能系统 | SKILL.md 生命周期 / 草稿 / 脚本沙箱 | skills/ 全链路 |
| 记忆系统 | working/episodic/semantic + memory 工具 | memory_tool.py |
| MCP | MCP 客户端 + wiki MCP server + doctor 检查 | backend/mcp/client.py |
| Hooks | 用户自定义工具钩子 | backend/hooks/ |
| 出网三件套 | web_search / web_fetch / http_download + NetworkPolicy 门禁 | tools/web_tool.py |
| 定时任务 | scheduled_router + 前端 ScheduledTasks 页 | api/scheduled_router.py |
| Worktree 并行开发 | scripts/worktree.sh + orchestration/worktree.py | docs/technical/47 |
| Office CRUD | docx/xlsx/pptx 增删改查 + 归档/快照 | office/ 模块 |
| 本地开发环境助手 | runtime_probe / project_diagnose / runtime_exec | tools/runtime_*.py |
| 诊断 | sage doctor CLI + 日志 | cli/doctor.py |
| 权限与审批 | RiskClass 四级 + INTERACTIVE/AUTO 模式门禁 | permissions.py |
| 会话压缩 | M4 token 阈值压缩 | chat/compaction.py |

## 2. 差距矩阵（对标结论）

| # | 缺失能力 | 对标参考 | 价值 | 本轮 |
| --- | --- | --- | --- | --- |
| G1 | **一等 Git 工具组**（status/diff/log/commit，结构化输出 + 审批门禁） | Codex/ZCode 均以工具面暴露 git；Qoder 内置 SCM 感知 | 高：LLM 现在只能裸 bash 拼 git 命令，无结构化结果、无按操作分级审批 | ✅ Phase-1 |
| G2 | **工作区检查点/回滚**（代理改文件前可快照、可恢复） | ZCode rewind、Cursor checkpoints、Codex 回滚 | 高：代理批量写文件缺乏 undo 安全网 | ✅ Phase-1 |
| G3 | Plan 模式（plan_write 结构化计划：goal + steps + status） | Qoder Quest Mode、ZCode 计划模式 | 中 | ✅ Phase-2（后端工具；UI 接入属前端里程碑） |
| G4 | 代码库索引/检索（symbol_search：ast 符号提取 + 分词概念匹配） | Qoder Context Engine、ZCode 代码检索 | 中 | ✅ Phase-2（务实版；embedding 版留待有实证需求） |
| G5 | 多模型切换：全局端点选择已有；新增会话级覆盖（session → model KV）+ profile 模型路由 | 三家均支持 | 中 | ✅ Phase-2（后端 + REST；设置页属前端里程碑） |
| G6 | 聊天图片输入（ChatRequest.images → OpenAI 多模态 content，4 张/5MiB 校验） | 三家均支持 | 中 | ✅ Phase-2（后端；上传 UI 属前端里程碑） |
| G7 | 浏览器自动化 / GUI 操作 | ZCode browser-use / computer-use | 中：需 Electron 侧驱动，跨端改动大 | Phase-3 |
| G8 | 写后语法诊断（stdlib ast，write/edit/apply_patch 成功结果附 diagnostics） | Qoder 实时诊断 | 中 | ✅ Phase-2（提前实施；LSP 语义层留待后续） |
| G9 | Commit message 素材工具（git_commit_message：staged 摘要 + 风格参照） | Codex/Qoder | 低-中 | ✅ Phase-2（提前实施） |
| G10 | 多文件原子 apply_patch | Codex apply_patch | 低：edit_file + G2 检查点已覆盖主要风险 | ✅ Phase-2（提前实施） |

## 2.1 剩余项实施路径勘察（2026-09-06）

- **G5 多模型切换（推荐下一个）**：`LLMConfig`（core/legacy/llm_client.py:78）已支持 openai/claude/gemini/deepseek/ollama/custom 多 provider；注入点为 `SageAgent(llm_config=dict)`（agent.py:300）。落地路径：preferences KV 新增 `model_override`（仿 bash_config 的 fail-safe KV 模式）→ chat_service 构造 llm_config 时按「会话覆盖 > profile.model_config > 全局 config.yaml」三级取值 → 设置页加 provider/model 下拉。改动面：后端 2 文件 + 前端 1 设置页。
- **G6 聊天图片输入**：vision 通道已有（wiki ingest），缺 chat 消息体的 image 附件字段与前端上传入口；需动 chat API 契约，前端改 Dashboard 输入组件。
- **G3 Plan 模式**：已有 todo_write（会话内）与 docs/plans 约定（跨会话文件），产品化 = plan 工具 + UI 视图；建议在 G5 之后做（模型选择影响 plan 生成质量）。
- **G4 语义索引**：wiki 向量库（hnsw）可复用；需独立索引器与增量更新，工作量最大。
- **G7 浏览器自动化**：依赖 Electron 侧 CDP/playwright 桥，跨端改动最大。

## 3. Phase-1 规格（本轮实施）

### T1 Git 工具组（`backend/tools/git_tool.py`）

四个工具，全部以 `policy.workspace_root` 为仓库根（未绑定则报错提示），`subprocess.run` 参数列表调用（不经 shell，Windows/Linux 一致），输出 utf-8 replace 解码，30s 超时：

- `git_status`（READ）：`status --porcelain=v1 -b` → `{branch, ahead, behind, entries:[{index, worktree, path}]}`。
- `git_diff`（READ）：args `{staged?:bool, path?:str}` → `{diff, truncated}`（输出上限 64KiB）。
- `git_log`（READ）：args `{limit?:int≤100 默认20, path?:str}` → `{commits:[{hash, author, date, message}]}`（`--pretty=format:%H%x1f%an%x1f%ci%x1f%s`，\x1f 分隔防注入）。
- `git_commit`（WRITE_LOCAL，INTERACTIVE 审批）：args `{message:str, add_all?:bool, paths?:list}` → 先 add 后 commit；返回 `{commit_hash}`；空提交/无变更优雅报错；绝不 push。

安全：不使用 shell；path 参数经 `_enforce_workspace` 守卫；git 不在 PATH / 非仓库 → 优雅 `ToolResult(success=False)`。

### T2 工作区检查点（`backend/tools/checkpoint_tool.py`）

- `checkpoint_create`（READ —— 仅向 sage 自有数据目录追加，不改工作区）：把工作区打 zip 存 `{SAGE_USER_DATA_DIR|~/.sage}/checkpoints/<workspace-sha1>/`；排除 `.git/node_modules/__pycache__/.venv/venv/dist/build/.sage`；单文件 >8MiB 跳过并记录；总量 >256MiB 报错；保留最近 10 份（超出淘汰最旧）→ `{checkpoint_id, files, skipped, bytes}`。
- `checkpoint_list`（READ）→ 最近快照元数据列表。
- `checkpoint_restore`（WRITE_LOCAL，INTERACTIVE 审批）：安全解包覆盖（逐成员校验 `..`/绝对路径/越界，兼容 py3.8 无 `Path.is_relative_to`）→ `{restored, files}`。语义为覆盖恢复，不删除快照后新建的文件（文档注明）。

### T3 注册与白名单

- `domain/tool_names.py`：`GIT_TOOLS = ("git_commit", "git_diff", "git_log", "git_status")`、`CHECKPOINT_TOOLS = ("checkpoint_create", "checkpoint_list", "checkpoint_restore")`，并入 `ALL_BUILTIN_TOOL_NAMES`（`test_tool_names.py` 注册面双向锁自动覆盖）。
- `register_all_tools` 注册 7 个新工具。
- primary / coder 种子追加 7 个名字；`_PRIMARY_TOOLS_BEFORE_BASH` 快照同步 +4+3（保持 `test_current_primary_untouched` / office 一致性锁语义）；intranet coder 精确清单测试同步。

### T4 验收

- `tests/unit/test_git_tool.py`：真实临时 git 仓库（git 跨平台可用），覆盖 status/diff/log/commit 正常流 + 非仓库 + 空提交 + path 越界 + 超时注入。
- `tests/unit/test_checkpoint_tool.py`：tmp_path 工作区，覆盖 create/list/restore 往返、排除目录、大文件跳过、zip 路径穿越拒绝、保留策略淘汰。
- 既有 profiles/tool_names 测试保持绿；`ruff check` 干净；全量单测失败集与基线一致。

## 4. win7 对齐（Phase-1 交付口径）

1. main 上两个独立提交：① bash 优化 PR-1+PR-2（已验证的存量 WIP）；② 本方案 Phase-1。
2. `release/win7` worktree 内按序 cherry-pick；① 的 profiles.py 冲突按 2026-09-04 方案 §5 适配（win7 种子无 web 两件套，`_PRIMARY_TOOLS_BEFORE_BASH` 单独定义）；② 为新增文件为主，冲突限于 tools/__init__ 与 profiles 种子段，手工并入。
3. cherry-pick 后在 win7 worktree 跑：`test_git_tool` / `test_checkpoint_tool` / `test_bash_config` / `test_tool_names` / profiles 套件，绿后提交。不 push（未获授权）。
