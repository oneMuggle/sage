# R85 提案引擎（Propose–Probe–Compose + 证据锚定）Spec

> 日期：2026-10-21
> 分支：`feat/plugin-kernel-r78`（PR #2206）
> 前置：R81 harness 配置与 CLI、R84 fileized harness / lock / snapshot / diff / rollback，既有 Background Review（ReviewQueue / ReviewService / SkillDraft / 审计与技能回滚）
> 本轮目标：在不新建第二套人工审批面的前提下，让 harness 行为变更以“候选 + 轨迹证据 + 离线 Probe 指标 + 确定性 Compose + 人工批准 + 快照采纳/回滚”的形式进入可审计闭环。默认只离线生成和审阅，不自动采纳。

---

## 1. 盘点结论与落位决策

| 资产 | 现状 | R85 用法 |
| --- | --- | --- |
| `backend/skills/review_queue.py` | SQLite 事件队列 + 单 worker；`_process_event` 固定调用 `ReviewService.generate_draft()` 生成技能草稿 | 不把多文件 harness 变更硬塞进该 worker；它继续负责技能学习触发。R85 的人工门复用其下游 `skill_drafts` 待审队列，而不是伪装成一种技能生成事件 |
| `backend/skills/review_service.py` / `SkillDraft` | 已有 LLM provider 装配、JSON 解析和 `pending/approved/rejected` 状态；草稿字段是技能专属的 `name/description/when_to_use/content` | `HarnessProposal` 与之同构：文件仓保存权威 manifest、候选与证据；提交时镜像为一条 `trigger_type=harness_proposal` 的 SkillDraft，`content` 是可读 review packet（摘要、证据、指标、diff） |
| `backend/api/legacy_skill_draft_routes.py` + Skills 页待审草稿 | 已有 list/approve/reject REST 与 UI；普通 approve 写单个 `SKILL.md` 且不覆盖 | approve/reject 在技能校验前识别 harness 镜像并分流：批准 = 记录人工批准并立即按快照采纳 harness；拒绝只更新提案与草稿状态。普通技能草稿路径逐字保持 |
| `backend/skills/audit.py` / loader rollback | 技能级 append-only 台账与单文件 before 快照已跑通 | harness 级回滚使用 R84 多文件 snapshot；提案 manifest 的 append-only `history` 记录 create/probe/compose/submit/approve/adopt/reject/rollback，不把多文件变更伪造成一条技能审计 |
| `PatternDetector`、`SkillUsageStore`、ReviewQueue triggers | 已能从重复工具签名、低成功率、复杂回合与显式 `/learn` 产生技能学习信号 | R85 不改 chat 热路径触发；这些信号可被离线导出为 evidence。候选生成首期为手动/CLI 离线触发，避免把 harness 根选择和目标面猜测塞进会话 worker |
| `session_event_repo`、`llm_record_replay`、session fork | 会话事实可按 seq 回放；LLM 流可录制/回放；会话可 fork，但没有“换 harness 后自动重跑同一任务并打分”的通用 runner | evidence 支持 `session_event/message/tool_trajectory/llm_replay` 定位与摘录哈希；Probe 消费外部离线回放/影子运行产出的指标报告，并叠加本地静态 staging 校验。R85 不冒充已实现在线 shadow 执行器 |
| R84 `harness_files/harness_snapshots` | lock 钉住托管文件；`proposals/**`、`evidence/**` 除 README 外不进 lock；snapshot/diff/rollback 已验证 | 提案与证据直接落这两个预留区；创建必须锚定当前有效 lock，采纳前建 snapshot，采纳后刷新 lock 并 verify，回滚复用 R84 |

### 1.1 硬边界

1. **无证据不入选。** 每条 candidate edit 至少引用一份有效的轨迹类 evidence；只有指标摘录不能单独支撑编辑。
2. **无 Probe 支持不 Compose。** Probe 报告必须给 base 与 candidate 的同名行为指标，并逐 edit 标记 `supported`；指标任一退化即整条 candidate 不合格。
3. **每轮最多一个组件面。** 一份提案的全部候选只能触及 `system/guardrails/memory/tool-guidance/subagents/skills/scripts/plugins` 中一个 component；禁止改 lock、snapshot、proposal/evidence README 与 `.gitignore`。
4. **人类批准是默认且唯一的生效门。** 生成、Probe、Compose、submit 都不改托管文件；CLI 需 `approve` 后再 `adopt`，既有 UI 的批准按钮是明确的“批准并采纳”最终确认。
5. **基线漂移即 stale。** 提案锚定 `base_lock_content_sha256` 与每文件 base hash；批准/采纳时不一致即拒绝，不做三方合并猜测。
6. **不执行候选脚本、不在线自动学习。** 静态 Probe 只在临时目录物化候选并做 lock/YAML/JSON/配置/SKILL.md 解析；不运行候选代码，不改 chat 热路径。

---

## 2. 文件仓与证据模型

### 2.1 目录

```text
harness/
  evidence/
    README.md                 # R84 托管
    <evidence-id>.json        # R85 证据记录（不进 lock）
  proposals/
    README.md                 # R84 托管
    <proposal-id>/
      proposal.json           # 权威 manifest + history
      base/files/<path>       # 创建时被改文件的基线副本（新增文件无）
      candidates/<candidate-id>/files/<path>
      composed/files/<path>   # Compose 选中的 write 内容（delete 无文件）
      probe.json              # 已校验的 Probe 报告副本
  .snapshots/
    pre-proposal-.../         # 采纳前快照
```

`proposal.json`、evidence 与 probe 均有内容哈希；候选/基线/选中文件逐文件 SHA-256 记录在 manifest 中。所有 ID 与路径必须是根内安全相对名，拒绝符号链接、盘符、`..` 与超限文件，复用 R84 上限（单文件 2 MiB、总量 32 MiB）。

### 2.2 Evidence

`evidence/<id>.json`：

```json
{
  "schema_version": 1,
  "kind": "sage-harness-evidence",
  "id": "ev-tool-errors-001",
  "evidence_kind": "tool_trajectory",
  "source": {"session_id": "s-1", "tool": "bash", "signature": "bash:command"},
  "excerpt": "tool bash failed ...; retried ...",
  "excerpt_sha256": "<sha256>",
  "metrics": {"tool_error_rate": 0.2},
  "created_at": "2026-10-21T00:00:00Z",
  "evidence_sha256": "<canonical-json-sha256>"
}
```

- 轨迹类：`session_event`（session + seq）、`message`（session + message）、`tool_trajectory`（session + tool/signature）、`llm_replay`（`rec_NNNN.jsonl` + line）。
- 补充类：`metric_snapshot`、`test_report`；可被引用，但不能单独满足 edit 的证据门。
- `excerpt` 上限 16 KiB；metrics 只允许有限数值。evidence 哈希是内容锚定而非签名，能发现摘录、来源或指标被事后改动；与 R84 lock 一样，不抵抗能同时改写全部本地文件的写者。

### 2.3 Proposal manifest

核心字段：`id/title/summary/author/component/status`、`base_lock_content_sha256`、candidates、selected_edits、probe/compose/review/adoption 摘要与 append-only `history`。状态机：

```text
draft -> probed -> pending -> approved -> adopting -> adopted -> rolled_back
  \         \          \           \
   -> rejected  -> compose_failed  -> stale
```

- `draft`：候选已锚定但未 Probe；`probed`：报告已校验；`pending`：已 Compose、等待人工；
- `approved`：人工已批准但尚未改文件；`adopting`：已建采纳前 snapshot，正在应用；失败自动恢复并回到 `approved`；
- `stale/compose_failed/rejected/rolled_back` 均为显式终态或需新建提案处理的状态，不静默重基。

每条 edit 记录 `path/operation/base_sha256/after_sha256/size/evidence_ids/rationale`。写操作必须与基线不同；删除必须有基线。候选 lane 首期使用 `invariant`（通用缺陷）与 `domain`（领域流程），手动导入也允许其他安全 lane 名，但仍受同一证据/指标门约束。

---

## 3. Propose–Probe–Compose

### 3.1 Propose

两种离线入口产出同一 candidate JSON 契约：

1. **导入**：`proposals create --input proposal.json`，供人工、外部 agent 或后续调度器提交 1–4 个候选；
2. **LLM 生成**：`proposals generate --path <managed-file> --goal ... --evidence <id>...` 复用 ReviewService 已装配的 provider/model，只针对一个目标文件生成 invariant/domain 两份完整替换候选。目标文件与证据摘录有大小上限；输出 JSON 必须逐项引用输入 evidence，解析或引用不合格即拒绝，不落半成品。

创建时引擎从当前有效 lock 读取 base hash 与内容，逐候选写 staging 后原子 rename；任一 evidence、路径、组件、大小或 hash 不合格都不创建提案。

### 3.2 Probe

Probe 报告是离线回放/影子运行的机器可读结果：

```json
{
  "schema_version": 1,
  "kind": "sage-harness-probe-report",
  "dataset": {"id": "replay-2026-10-21", "evidence_ids": ["ev-tool-errors-001"]},
  "base_metrics": {"tool_error_rate": 0.2, "success_rate": 0.7},
  "candidates": {
    "invariant": {
      "metrics": {"tool_error_rate": 0.1, "success_rate": 0.75},
      "edits": {"plugins.yaml": {"supported": true, "evidence_ids": ["ev-tool-errors-001"]}}
    }
  }
}
```

- 识别指标：低优为 `tool_error_rate/tool_errors/invalid_loop_count/interruption_rate/correction_rate/duration_ms/*_tokens/static_errors`，高优为 `success_rate/completion_rate/task_success_rate`；未知指标仅展示不计分。
- candidate 必须与 base 至少共享一个行为指标，且每个共享指标不得退化（零容忍，仅浮点 epsilon）；分数为共享指标相对改善的均值。
- CLI `--static` 将每个候选物化到临时 harness 根，验证 lock、YAML/JSON、plugins 配置 strict 解析与 SKILL.md frontmatter，并注入 `static_errors`。静态通过不等于行为支持，不能替代逐 edit 的 `supported` 与行为指标。

### 3.3 Compose

Composer 是确定性纯函数式筛选：

1. 先淘汰无报告、指标退化或静态失败的 candidate；
2. 只保留 Probe 明确 `supported=true` 且引用有效轨迹证据的 edit；
3. 同路径同结果合并证据；同路径不同结果选择分数最高 candidate，平分冲突则两边都丢弃并记录原因；
4. 无任何入选 edit -> `compose_failed`；否则写入 `composed/files` 并进入 `pending`。

入选结果生成稳定 JSON view 与 Markdown review packet：标题、组件、base lock、Probe 分数/淘汰原因、每份 evidence 的来源与摘录（截断展示）、逐文件 unified diff。

---

## 4. 审批、采纳与回滚

### 4.1 CLI 人类门

```bash
python -m backend.cli.harness proposals evidence-add [root args] --input evidence.json
python -m backend.cli.harness proposals create [root args] --input proposal.json
python -m backend.cli.harness proposals generate [root args] --path plugins.yaml --goal "..." --evidence ev-1
python -m backend.cli.harness proposals probe [root args] <id> --report probe.json [--static] [--compose]
python -m backend.cli.harness proposals compose|show|list [root args] [<id>] [--patch]
python -m backend.cli.harness proposals submit [root args] <id> [--db-path PATH]
python -m backend.cli.harness proposals approve|reject|adopt|rollback [root args] <id>
```

root args 与 R84 `files` 相同；退出码延续 0 成功、1 校验/状态拒绝、2 参数或文件错误。`show/list` 是查询操作，差异或 stale 本身不冒充进程失败；`validate` 视图中的 stale 以 1 返回供脚本把关。

### 4.2 SkillDraft 镜像

`submit` 只接受 `pending` 提案，并向既有 `SkillDraftStore` 插入一条镜像：

- `name=harness-<component>-<short-id>`（满足既有 slug 约束）、`trigger_type=harness_proposal`；
- `description/when_to_use` 明示这是 harness 行为变更且批准即采纳；
- `content` 为完整 review packet；`source_context={kind, proposal_id, harness_root, component, base_lock_content_sha256, selected_paths}`；
- manifest 记录 `review.draft_id`，重复 submit 返回同一条 pending 草稿，不刷屏。

REST approve 对镜像先调用桥接层 `approve + adopt`，成功后才把草稿置 `approved`；stale/无效以 409 保持 pending。reject 先把提案置 `rejected`（已采纳则 409），再更新草稿。普通技能草稿不经过该分支。

### 4.3 Adopt / rollback

采纳只接受 `approved`：再次验证 base lock、evidence 与 composed hash -> 创建 `pre-proposal-*` snapshot -> manifest 标记 `adopting` -> 逐文件原子写/删 -> 以 `harness-proposal:<id>` provenance 刷新 lock -> verify。任何失败都用该 snapshot 恢复并把状态退回 `approved`，history 记录失败。

回滚只接受 `adopted` 且当前 lock 等于采纳后 lock（显式 `--force` 才允许覆盖后续变更）；调用 R84 rollback 恢复采纳前 snapshot（同时保留回滚前 snapshot），验证回到 base lock 后标记 `rolled_back`。

---

## 5. 代码落位

| 文件 | 责任 |
| --- | --- |
| `backend/application/kernel/harness_evidence.py` | evidence schema、来源/摘录/指标校验与内容哈希；只依赖 R84 kernel 文件机制 |
| `backend/application/kernel/harness_proposals.py` | proposal manifest、candidate 文件仓、创建/列表、review view；不调用 LLM 或 DB |
| `backend/application/kernel/harness_proposal_engine.py` | probe 校验、确定性 compose、candidate staging、批准/采纳/回滚状态机 |
| `backend/skills/harness_proposal_service.py` | 复用 ReviewService provider/model 的单文件双候选 LLM 生成与严格 JSON 校验 |
| `backend/skills/harness_proposal_bridge.py` | HarnessProposal <-> SkillDraft 镜像、submit 与 UI approve/reject 桥接 |
| `backend/skills/review_service.py` | 仅暴露只读 `model` 属性，供同域服务复用已装配模型 |
| `backend/api/legacy_skill_draft_routes.py` | harness 镜像 approve/reject 分流；普通技能路径不变 |
| `backend/cli/harness_proposals.py` | `proposals` CLI 参数、JSON 输入、静态 probe staging 与文本/JSON view |
| `backend/cli/harness.py` | 只注册/分发 `proposals` 子命令并映射错误码 |
| `backend/cli/harness_export.py` | 更新 R85 proposals/evidence README 文案 |
| `backend/tests/unit/test_kernel_harness_proposals.py` | evidence/hash/单组件/compose/状态机/采纳回滚纯机制测试 |
| `backend/tests/unit/test_harness_proposal_bridge.py` | LLM 双候选、SkillDraft 镜像与桥接采纳/拒绝测试 |
| `backend/tests/unit/test_cli_harness_proposals.py` | CLI 全流程、静态 probe 与 JSON 契约 |
| `backend/tests/integration/test_approval_api.py` | 增补 harness 镜像 approve/reject 分流且普通技能不回归 |

约束：Python 3.8 兼容；单文件 ≤800 行；不新增第三方依赖或 DB schema；kernel 不 import skills/LLM；桥接与 CLI 承担组合依赖。

---

## 6. 验收矩阵

| 主张 | 证据 |
| --- | --- |
| 无提案时默认行为不变 | R84 harness 相关测试保持通过；新 CLI/桥接只在显式命令或 harness 镜像草稿时触发 |
| 无轨迹证据的编辑被拒 | create 对空 evidence、仅 metric evidence、evidence hash 篡改、未知 ID 均失败且不留提案目录 |
| 提案锚定基线 | base lock 或单文件漂移后 approve/adopt 进入 stale/拒绝，托管文件不变 |
| Probe 退化不入选 | 任一共享行为指标退化的 candidate 被淘汰；未标记 supported 的 edit 被丢弃 |
| Compose 确定性 | 同结果合并、冲突按分数选一、平分冲突丢弃、无入选进入 compose_failed 均有单测 |
| LLM 只产候选不生效 | fake provider 生成 invariant/domain 后状态仍 draft，文件与 lock 不变；坏 JSON/越权 evidence 被拒 |
| 人工审批同面 | submit 在既有待审队列出现一条 harness 镜像；REST approve 真采纳、reject 真拒绝，普通 SkillDraft 既有测试不回归 |
| 采纳可回滚 | approve->adopt 后目标文件与 lock 更新且有 pre-proposal snapshot；rollback 后逐哈希回到 base；后续漂移默认拒绝回滚、显式 force 才恢复 |
| 静态 Probe 不执行候选 | staging 中坏 YAML/坏 plugins 配置/坏 SKILL.md 得 static_errors，候选被淘汰 |
| 门禁 | 定向 pytest、Ruff、py38、静默异常 ratchet、architecture-check、PR CI/E2E 全绿 |

---

## 7. 非目标与后续

- 不实现在线 shadow 任务执行器、自动指标采集调度或自动采纳（原方案档 2/3）；R85 只提供离线报告契约与静态 staging，真实回放运行器可后续按同一报告接入。
- 不把 ReviewQueue 改造成通用工作流引擎；其技能生成触发与去重语义保持不变。
- 不新增 harness 专用 REST/UI；待审面复用 Skills 页 SkillDraft 列表与详情。review packet 必须自带 diff/证据，避免 UI 再读任意本地路径。
- 不做多组件提案、三方合并、跨根同步、签名/远程证据库；冲突与 stale 一律显式拒绝后重建提案。
- 不允许提案修改可执行脚本内容本身；`scripts` 面首期仅限 R84 已托管的 policy/README 文本，且静态 Probe 不执行它们。
