# R84 Harness 文件化、Lock 与差异视图 Spec

> 日期：2026-10-21
> 分支：`feat/plugin-kernel-r78`（PR #2206）
> 前置：R78 插件契约、R80 tool bundle、R81 三层 harness 配置与 CLI、R82 插件 UI/REST、R83 进程外插件宿主
> 本轮目标：把分散在代码、配置和既有文件系统中的 8 个行为面物化为一个可校验、可 diff、可快照、可回滚的 `harness/` 文件集；其中 `plugins.yaml` 的 bundle 选择段成为新的运行时输入，其余面先做只读投影，为 R85 提案引擎提供稳定的文件基质。

---

## 1. 盘点结论与落位决策

| 资产 | 现状 | R84 用法 |
| --- | --- | --- |
| `application/kernel/harness_config.py` | 已有三层 `harness.yaml`、四预设、provenance、mtime 缓存；生产 fail-open、CLI strict | 保持既有层级与默认行为；新增 fileized `plugins.yaml` 层与路径助手 |
| `backend/cli/harness.py` | 已有 `presets/dump-config/check`，是可同时 import kernel 与 tools 的组合层 | 在同一 CLI 下增加 `files` 子命令；不在 kernel 中 import 具体行为面 |
| `backend/agents/profiles.py` | `create_default_agents()` 给出 primary 与默认子代理的 prompt/tools/model | 生成 `system.md` 与 `subagents/*.md` 的内置基线 |
| `backend/agents/agents_files.py` | `.sage/agents/*.md` 已有 frontmatter 解析、导入、导出闭环，启动时已导入 | 导出时覆盖同名默认子代理；生成格式继续兼容其 parser；R84 不新增第二个子代理加载根，避免优先级漂移 |
| `backend/chat/project_context.py` | 运行时会发现 `SAGE.md/CLAUDE.md/AGENTS.md` 并注入项目指令 | `system.md` 记录内置 primary prompt，并附当前 workspace 命中的项目指令 |
| `domain/tool_policy.py`、`domain/permission.py`、`domain/risk.py`、`hooks/*` | 工具上限、权限模式、风险类、内置 hooks 与校验常量均为代码声明 | 汇总为 `guardrails.yaml` 与 `plugins.yaml` 的 hooks 段 |
| `backend/config.yaml`、`memory/scoring.py`、记忆分类规则 | memory 容量在 YAML，检索权重与分类阈值在代码 | 汇总为 `memory.yaml`，不导出任何用户记忆内容 |
| `tools/tool_bundles.py`、`ToolRegistry` | 31 个 bundle、工具 schema 与 declared risks 已可程序化枚举 | 生成 `tool-guidance.yaml`；导出时跳过会触发外部发现的 `mcp` bundle，只记录内置工具 |
| `skills/skill_md/shipped` 与用户/项目 `SKILL.md` | 已有文件形态、发现优先级与审批写回闭环 | 复制深度 1 的 `<name>/SKILL.md`，高优先级覆盖低优先级；不复制脚本/资源/二进制 |
| `tools/checkpoint_tool.py`、`services/permission_gate.py` | 已有安全快照、防 zip-slip 与 unified diff 模式，但分别绑定 workspace zip 与审批预览 | 复用安全语义，不直接耦合其工具类；核心层实现小文件集的目录快照与 `difflib` 差异 |
| 前端/API | 无 harness 专用 REST 或设置页；R81 已明确以 CLI 为首期面 | R84 的“差异视图”是稳定的 CLI 文本/JSON view，不新增可任意读文件的 REST 面；R85 再把同一 view 接入既有审批流 |

### 1.1 关键边界

1. **无 lock 即旧行为。** 当前所有没有 `harness/harness.lock.json` 的安装不改变启动、工具装配或配置结果。
2. **有 lock 即显式采用。** `files export` 默认生成 `startup_enforced: true` 的 lock；后端 lifespan 在 DB 初始化前校验采用的 user/project 文件集，失败拒绝启动。
3. **只有一个新运行时输入。** `plugins.yaml` 的 `harness_config` 段按作用域进入 R81 合并链；其余生成文件在 R84 是可版本化投影，不冒充已经替代 prompt/memory/hooks 的原生加载器。
4. **不复制秘密与用户数据。** 不导出 settings 密钥、会话、记忆正文、插件 DB、脚本文件或任意二进制。
5. **不新增审批系统。** R84 只提供文件、lock、snapshot、diff 的确定性机制；提案、证据与人工审批仍是 R85。

---

## 2. 文件集与目录

### 2.1 根目录解析

- project：`<workspace>/harness/`
- user：`<user_home>/.sage/harness/`
- CLI `--output DIR` 可显式覆盖任一 scope。
- workspace/home 的解析继续复用 R81：显式参数 > `SAGE_WORKSPACE` / `SAGE_HARNESS_HOME` > cwd / 系统 home。
- `scope=user` 只钉 builtin/env/user 层，不把当前 workspace 的 agents、项目指令或 skills 烘焙进用户文件集；`scope=project` 才纳入 workspace 覆盖层。

### 2.2 物化布局

```text
harness/
  .gitignore
  system.md
  guardrails.yaml
  memory.yaml
  tool-guidance.yaml
  plugins.yaml
  subagents/
    primary.md
    researcher.md
    ...
  skills/
    <skill-name>/SKILL.md
  scripts/
    README.md
    policy.yaml
  proposals/
    README.md
  evidence/
    README.md
  harness.lock.json
  .snapshots/
    <snapshot-id>/
      snapshot.json
      harness.lock.json
      files/<managed files...>
```

- `.snapshots/`、lock 本身不进入 lock 的文件清单。
- `proposals/**`、`evidence/**` 中只有 README 是 R84 托管文件；其余内容为 R85 预留区，不参与 lock 校验。
- 生成的 Markdown 带 frontmatter：`version/provenance/owner/updated_at`；生成的 YAML 带顶层 `_meta`；复制的 `SKILL.md` 保持原生 frontmatter，来源与 owner 记录在 lock。

### 2.3 八个行为面来源

| 文件 | 来源 | R84 权威性 |
| --- | --- | --- |
| `system.md` | primary 默认 prompt + workspace `SAGE.md/CLAUDE.md/AGENTS.md` | 只读投影 |
| `guardrails.yaml` | `ToolPolicy()`、PermissionMode、RiskClass、hooks 限制与内置 guard 元数据 | 只读投影 |
| `memory.yaml` | `backend/config.yaml` 的 memory 段、scoring 权重、分类阈值 | 只读投影；无用户记忆 |
| `tool-guidance.yaml` | bundle 顺序、resolved 选择、内置工具 schema 与 declared risks | 只读投影 |
| `subagents/*.md` | 默认 profiles，workspace `.sage/agents/*.md` 同名覆盖 | 与既有 agents file 格式兼容的投影 |
| `skills/*/SKILL.md` | env > workspace `skills/` > user `~/.sage/skills` > shipped，逐级覆盖 | 已有文件闭环的快照副本 |
| `scripts/policy.yaml` | EXEC/SANDBOX 工具面、默认命令 allowlist 为空、脚本根标签 | 只读策略投影；不复制可执行脚本 |
| `plugins.yaml` | resolved harness config + hooks 目录 | **其中 `harness_config` 段是运行时输入** |

---

## 3. Lock 格式与校验

`harness.lock.json` 为 schema v1：

```json
{
  "schema_version": 1,
  "kind": "sage-harness-lock",
  "generated_at": "2026-10-21T00:00:00Z",
  "generator": "backend.cli.harness files export",
  "startup_enforced": true,
  "file_count": 23,
  "content_sha256": "<canonical file-entry digest>",
  "files": {
    "system.md": {
      "sha256": "...",
      "size": 1234,
      "component": "system",
      "provenance": "backend.agents.profiles:create_default_agents#primary",
      "owner": "sage-builtin",
      "authority": "projection"
    }
  }
}
```

- 文件键一律为 POSIX 相对路径并排序；`content_sha256` 对排序后的 `path + sha256 + size` 规范串再取 SHA-256。
- verify 检查：schema、lock 自身内容摘要、缺失、大小/哈希不一致、未跟踪托管文件、符号链接、文件数/单文件/总大小上限。
- 上限：2000 个文件、单文件 2 MiB、总量 32 MiB；超出时明确失败，不做静默截断。
- lock 是漂移/篡改可见性机制，不是签名；能同时改文件与 lock 的本地写者仍可伪造，签名与信任链不在 R84。
- `SAGE_HARNESS_LOCK_ENFORCE=0|false|no|off` 是紧急恢复旁路，仅跳过启动 gate；CLI `verify` 仍如实报告失败。

### 3.1 启动与加载语义

1. FastAPI lifespan 在 DB 初始化前调用 `assert_adopted_harness_files_valid()`：
   - user/project 任一根存在 lock 且 `startup_enforced` 不为 false，就必须 verify 通过；
   - 无 lock 时 no-op；
   - 失败抛 `HarnessFilesError`，拒绝启动，错误包含根目录与首批 issue。
2. R81 `load_harness_config` 的新层级为：
   `builtin < user harness.yaml < user harness/plugins.yaml < project harness.yaml < project harness/plugins.yaml < env preset < patch`。
3. `plugins.yaml` 只有在同根 lock verify 通过时才应用其 `harness_config` 段：
   - 非 strict：warning + 忽略该层，保持工具装配 fail-open；
   - strict：抛 `HarnessConfigError`；
   - 缓存键纳入两个 `plugins.yaml` 与两个 lock 的 mtime。

---

## 4. Snapshot、Diff 与 Rollback

### 4.1 Snapshot

- snapshot 复制当前全部托管文件与当前 lock，并写 `snapshot.json`（id、创建时间、文件哈希、lock 哈希）。
- 默认 id 为 UTC 时间戳 + 6 位随机后缀；显式 id 只允许 `[A-Za-z0-9._-]`。
- 写入先落 `.snapshots/.staging-<id>`，校验 copy 后再 rename，避免半成品被列为可用快照。

### 4.2 Diff view

`harness_diff_view()` 返回 JSON 友好结构，CLI 再渲染文本：

- 默认与最新 snapshot 比；也可指定 snapshot id。
- 每项包含 `path/status/component/before_sha256/after_sha256/before_size/after_size`。
- 文本且未超限时可选附 unified patch；二进制或超限只给哈希级差异。
- `files status` 给 lock 视角的 unchanged/modified/missing/added 计数；`files diff` 给 snapshot 视角的内容差异。

### 4.3 Rollback

1. 先校验目标 snapshot 的 manifest 与全部文件哈希，未通过不触碰当前目录。
2. 默认先为当前状态建 pre-rollback snapshot，使回滚本身可逆。
3. 删除当前托管文件，复制 snapshot 文件，最后原子恢复对应 lock。
4. 恢复后立即 verify；失败明确报错并保留 pre-rollback snapshot 供再次恢复。

所有托管路径都拒绝绝对路径、`..`、盘符与符号链接；单文件写入采用同目录临时文件 + `os.replace`。

---

## 5. CLI 契约

现有命令保持不变：`presets`、`dump-config`、`check`。其中 `check` 在 strict 配置通过后，继续校验已采用的 harness lock。

新增：

```text
python -m backend.cli.harness files export
  [--workspace P] [--user-home P] [--scope project|user] [--output DIR]
  [--force] [--no-snapshot] [--no-enforce-startup] [--json]

python -m backend.cli.harness files status   [root args] [--json]
python -m backend.cli.harness files verify   [root args] [--json]
python -m backend.cli.harness files update-lock [root args] [--json]
python -m backend.cli.harness files diff
  [root args] [--snapshot ID] [--patch] [--json]
python -m backend.cli.harness files snapshot [root args] [--name ID] [--json]
python -m backend.cli.harness files snapshots [root args] [--json]
python -m backend.cli.harness files rollback
  [root args] [--snapshot ID] [--no-pre-snapshot] [--json]
```

退出码延续 R81：成功 0；verify/check 的校验失败 1；参数、路径或文件操作错误 2。`status/diff/snapshots` 是查询操作，成功执行即 0，差异本身不冒充进程失败。

---

## 6. 代码落位

| 文件 | 责任 |
| --- | --- |
| `backend/application/kernel/harness_files.py` | 纯文件集机制：路径安全、lock、verify、写 specs、启动 gate；不认识具体 prompt/tools |
| `backend/application/kernel/harness_snapshots.py` | 基于已校验文件集的 snapshot、status、diff、rollback 与带 snapshot 的写盘编排 |
| `backend/application/kernel/harness_config.py` | 新增 fileized 根目录助手；把已校验 `plugins.yaml` 接入既有合并链与缓存键 |
| `backend/cli/harness_export.py` | 组合层：从 agents/domain/hooks/memory/tools/skills 收集 8 个面，渲染 `HarnessFileSpec` |
| `backend/cli/harness.py` | 新增 `files` 子命令与文本/JSON view；`check` 增加 lock gate |
| `backend/main.py` | lifespan DB 初始化前调用启动 gate；预计只增数行并按 ratchet 更新单文件基线 |
| `backend/tests/unit/test_kernel_harness_files.py` | lock/snapshot/diff/rollback/路径安全/启动 gate 纯机制测试 |
| `backend/tests/unit/test_cli_harness_files.py` | exporter 来源覆盖、CLI 契约、`plugins.yaml` 运行时层与 strict 拒绝测试 |

约束：Python 3.8 兼容（不用 match、PEP 604 运行时并集、`datetime.UTC`、`Path.is_relative_to`）；单文件 ≤800 行；不放宽 domain/ports 白名单；不新增第三方依赖。

---

## 7. 验收矩阵

| 主张 | 证据 |
| --- | --- |
| 无 fileized harness 时零行为变更 | R81 既有 94 工具黄金快照与 harness config 测试保持通过；startup gate 对无 lock 根 no-op |
| 8 个面全部物化 | exporter 单测断言 system/guardrails/memory/tool-guidance/subagents/skills/scripts/plugins 均有文件，lock 记录 provenance |
| lock 能发现漂移 | 改一字节、删文件、加未跟踪文件、改 lock 内容摘要、符号链接均得到稳定 issue code |
| lock 失败拒绝采用 | `assert_adopted_harness_files_valid` 抛错；CLI `check/verify` 返回 1；有效 lock 返回 0 |
| 每份文件可 diff | 对最新 snapshot 的 added/modified/deleted 均有条目，文本 patch 含 unified diff 头 |
| 每份文件可回滚 | 修改+删除+新增后 rollback，文件集与 lock 与 snapshot 逐哈希相等，且产生 pre-rollback snapshot |
| `plugins.yaml` 真正影响装配选择 | 在 project fileized 文件中改 preset/bundle 并 update-lock 后，`load_harness_config` 与 CLI dump-config 反映新选择；lock 失效时非 strict 忽略、strict 拒绝 |
| 快照不被半成品污染 | snapshot manifest 哈希校验、非法 id/越界路径拒绝；损坏 snapshot rollback 不改当前文件 |
| 门禁 | 定向 pytest、Ruff、py38 兼容、architecture-check、前端无改动时不重复改 UI；提交后 PR CI/E2E 全绿 |

---

## 8. 非目标与后续

- 不把 system prompt、guardrails、memory 权重、hooks 的原生加载器一次性切换到 harness 副本；这些面在 R84 是可审查投影。
- 不新增 harness REST/UI，不允许浏览器请求任意本地路径；R85 的提案审批应复用既有 SkillDraft/ReviewQueue 面并消费本轮 diff view。
- 不实现提案生成、回放、证据锚定或自动采纳（R85）。
- 不做 lock 签名、远程同步、多人合并或 CRDT；冲突仍由 git/人工审查处理。
- 不复制 skill 附带脚本与资源；脚本执行继续走既有 sandbox 与审批边界。
