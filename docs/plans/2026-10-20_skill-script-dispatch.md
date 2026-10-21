# 2026-10-20 技能脚本调度端到端修复

> 由 `khazix-skills/storage-analyzer` 加载/可用性测试驱动的 sage 侧修复。

## 背景

对 `/home/fz/project/khazix-skills/storage-analyzer` 技能做了端到端测试（4 个 E2E 脚本，覆盖加载器、InprocSkillAdapter、沙箱边界、快照镜像），发现 sage 技能系统存在两类问题：

- **技能侧**（khazix-skills 仓库，不在本 PR 范围）：SKILL.md 缺 `os` 平台门控、缺 `when_to_use` 触发词、正文用裸相对路径指向脚本、`server.py` 与沙箱模型不兼容 → 另开 khazix-skills PR 修复
- **sage 侧**（本 PR 范围）：
  1. **T-1**：`ScriptRunner._create_snapshot` 扁平复制脚本 → 技能脚本 `dirname(__file__)` 失效，无法通过相对路径找到 `../assets/` 模板
  2. **T-2**：`skill` 工具和 slash 路径都不设 `params["script"]` → LLM 完全够不到脚本调度通道，即使正文告知 LLM 也无法触发
  3. **T-3**（本期不做，独立排期）：前端缺少「允许执行技能脚本」开关
  4. **T-4**（本期不做，独立排期）：前端缺少技能目录设置项；`POST /skills/import` 只接单个 SKILL.md 文件，不带 scripts/references/assets

## 本 PR 范围

**只实施 T-1 和 T-2**。T-3 / T-4 涉及前端设置 UI，独立排期避免把沙箱路径修复与设置系统改动混在一起（前者风险更高，需要完整回归；后者是 UX 改进）。

## 涉及的文件

### T-1 快照镜像
- `backend/skills/skill_md/script_runner.py` — 改 `_create_snapshot`、`run_script`、`_cleanup_snapshot`
- `backend/tests/unit/test_skill_md_script_runner.py` — 更新/新增断言
- `backend/tests/integration/test_skill_md_integration.py` — 端到端脚本执行测试（如有）
- 新增 `backend/tests/unit/test_skill_md_script_runner_mirror.py` — 镜像布局专项

### T-2 脚本调度可达
- `backend/tools/skill_tool.py` — schema 加可选 `script` 参数；dispatch 走 `adapter.execute`
- `backend/adapters/out/skill/inproc.py` — `execute_command` 增加 `script=<path>` 分支
- `backend/tests/unit/test_skill_tool.py` — 已有用例 + 新增 script 参数
- `backend/tests/unit/test_skill_script_dispatch.py`（新增）— 验证 slash `script=` 分支必须过权限闸口

## 技术方案

### T-1 快照镜像

**现状**：`ScriptRunner._create_snapshot` 把脚本扁平拷到 `<tmp>/sage-skill-XXXX/<script_name>.py`，执行副本。`cwd` 仍指向真实技能目录。技能脚本用 `HERE = dirname(abspath(__file__))` 拼 `../assets/report_template.html` 时指向 `/tmp/assets/...`（不存在）。

**改法**：

1. 快照布局改为**镜像** `doc.base_dir` 的相对结构：
   - 脚本拷到 `<tmp>/scripts/build_report.py`（保留 `scripts/` 子目录）
   - 把 `build_resource_index` 白名单目录（`scripts` / `references` / `assets` / `templates`）整体复制进快照
2. **安全约束**：
   - 逐文件走 `_read_bound_regular_file`（O_NOFOLLOW + inode 绑定 + `st_nlink == 1`）
   - 符号链接/重解析点一律跳过
   - 仅复制 `_read_bound_regular_file` 校验通过的普通文件
3. `SandboxRequest.cwd` 从真实 `validated_path.parent` 改为 **快照内对应目录**（镜像后的 scripts 目录）
4. `SandboxRequest.env` 注入 `SAGE_SKILL_BASE_DIR=<真实技能目录>`（可选，便于脚本做兜底探测）
5. `_cleanup_snapshot` 不变：`shutil.rmtree(snapshot_path.parent)` 仍是快照根

**效果**：技能脚本 `dirname(__file__)` 指向镜像内的 `scripts/`，`../assets/` 指向镜像内复制的模板文件。一行不改技能脚本即可工作。

**验证**：
- 单测：快照目录结构断言（含镜像 scripts/references/assets 布局）
- 集成：在沙箱内跑 storage-analyzer 的 `build_report.py` 应成功产出 27KB HTML
- 回归：现有 `test_skill_md_script_runner.py` 全绿

### T-2 脚本调度可达

**现状**：
- `POST /skills/{name}/execute` 的 `args: {"script": "..."}` → `adapter.execute` → `_is_script_dispatch` → `_enforce_permission` → `skill.execute_v2(params={"script": ..., "args": ...})` ✅
- `POST /skills/command`（slash 路径）→ `InprocSkillAdapter.execute_command` → `slash_registry.execute_command` → `skill.execute_v2(params={"args": [...]})` ❌ 永远不设 `script`
- skill 工具 → `_invoke` → 同上 ❌

**改法**：

1. `SkillTool._build_schema` 增加可选 `script` 参数（schema description 明示"相对技能目录的脚本路径"）
2. `SkillTool._invoke` 检测 `script` 存在时调用 `adapter.execute(skill_name, "", {"script": script, "args": args_list})`（权限闸口自动生效）
3. `InprocSkillAdapter.execute_command` 增加分支：解析 args 中的 `script=<path>` 前缀，提取后调 `self.execute(resolved_name, "", {"script": ..., "args": rest})`（**必须**走 `self.execute` 而非直接 `slash_registry`，确保权限闸口生效）
4. 安全：**slash 路径的 script 分发必须与 REST 路径同一权限模型**（`_enforce_permission` 不可绕过）

**验证**：
- 单测：skill 工具带 script 参数 → 成功触发脚本
- 集成：slash `/storage-analyzer script=scripts/scan.py` 过权限闸口（负向用例：无 allowlist 时应返回权限拒绝）

## 实施步骤

- [x] 步骤 1：写 `docs/plans/2026-10-20_skill-script-dispatch.md` 本计划文档
- [x] 步骤 2：实施 T-1（快照镜像）—— 改 script_runner.py + 跑现有测试
- [x] 步骤 3：新增 T-1 专项测试（镜像布局断言 + storage-analyzer 端到端）—— `backend/tests/unit/test_skill_md_script_runner_mirror.py` (8 tests)
- [x] 步骤 4：实施 T-2（脚本调度可达）—— 改 skill_tool.py + inproc.py
- [x] 步骤 5：新增 T-2 专项测试（权限闸口负向用例 + skill 工具 script 参数）—— `backend/tests/unit/test_skill_script_dispatch.py` (10 tests) + 5 tests 增补至 `test_skill_tool.py`
- [x] 步骤 6：跑本次 4 个 E2E 脚本（`/tmp/skill_e2e_test{,2,3,4}_wt.py`）验证端到端
- [ ] 步骤 7：code-review + security-review 两个 agent 走一遍
- [ ] 步骤 8：提交 + 推送 + 开 PR

## 风险评估

- **T-1 风险高**：触碰脚本执行完整性路径，影响所有 SKILL.md 带脚本的技能。需要完整回归 `backend/tests/unit/test_skill_md_script_runner.py` 和 `backend/tests/integration/test_skill_md_integration.py`
- **T-2 风险中**：改动涉及权限闸口。必须保证 slash `script=` 分支与 REST 路径同一权限模型，否则是安全漏洞
- **cwd 语义变化**：脚本写到 cwd 相对路径的产物会随快照清理消失。storage-analyzer 输出走显式 argv，不受影响；其他技能需逐个确认

## 依赖

- 无前置 PR
- 后续 PR（独立排期）：T-3 技能脚本开关设置、T-4 技能目录设置
