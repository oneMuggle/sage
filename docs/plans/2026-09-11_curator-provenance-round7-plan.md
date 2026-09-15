# Curator 第三块 — provenance frontmatter + 巡检 cron 化 Round 7 实施计划

> 日期: 2026-09-11 · 分支: `feat/curator-provenance` · 基于 main @ 597e89e3
> 来源: hermes-agent 对标分析（curator 第三块：provenance + consolidation review 自动化）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: 避开 feat-p11-embedding-distribution（embedder 区域）。

## 背景

Round 5 落地了 pin 与手动触发的 LLM 巡检；Round 3 落地了审计台账。
本批收口两点：

1. **provenance frontmatter**：hermes 的技能带来源标记
   （agent-created / user-created）。Sage 目前只把来源记在审计台账
   （`source=draft:{id}`），SKILL.md 本体无标记——拷贝技能文件到别处
   即丢失来源信息。
2. **巡检 cron 化**：Round 5 的巡检只能手动 `POST /skills/consolidation/scan`
   触发；hermes 是定期自动 review。挂进既有 evolution cron 体系
   （`_evolution_register`），LLM 未装配时任务 no-op。

## 批次任务

### A. provenance frontmatter 注入（`backend/api/legacy_routes.py`）

- `approve_skill_draft` 写盘前：`parse_skill_md` →
  `metadata.provenance = "agent-created"`（setdefault，保留已有标记）→
  `dump_skill_md` 回写
- 注入失败（解析异常）按原文落盘 + warning（不阻塞审批）
- 审计 `create` 条目的 after_content 快照记录**注入后**内容
  （快照 = 实际落盘内容，回滚语义才正确）

### B. 巡检 cron 化

- `skills/consolidator.py`: 抽出 `collect_active_skills()` 助手
  （REST 与 cron 任务共用，惰性取 InprocSkillAdapter）
- `scheduler/evolution.py`: `SkillConsolidationTask` —— 扫描 → 建议 →
  `consolidation_note` 台账 + `evolution_log`；无 LLM → no-op
- `services/_evolution_register.py`: 默认调度
  `skill_consolidation = 每周六 05:30`（config.yaml evolution.tasks 可覆盖）

### C. 测试

- `backend/tests/unit/test_curator_provenance.py`（建议落台账/no-op/
  pinned 透传/调度注册/工厂）
- `backend/tests/integration/test_provenance_injection.py`（审批落盘
  frontmatter 含 provenance + 台账快照一致）
- `test_approval_api.py` write 断言对齐注入后契约（镜像注入逻辑）

## 验收

- [ ] 新测试全绿 + 存量不回归
- [ ] ruff 干净；CI 覆盖率 ≥80% 绿
- [ ] PR 注明「新功能，不 cherry-pick 到 release/win7」
