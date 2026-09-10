# 技能审计台账 + 单条回滚 Round 3 实施计划（对标 hermes-agent curator）

> 日期: 2026-09-11 · 分支: `feat/skill-audit-rollback` · 基于 main @ 92f25a90
> 来源: hermes-agent 对标分析（curator 设施第一块）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。
> 冲突规避: 继续避开 feat-p10-retrieval-tuning 占用的 memory/embedder 区域。

## 背景

Round 1/2 补齐了语义向量、循环守卫与会话检索。对标 hermes `agent/curator.py`
剩余的最大结构性差距是**技能生命周期维护的安全网**：

- hermes: 每次技能修改前备份 + append-only 审计台账 + **单条一键回滚**
  + provenance（agent-created / user-created）
- Sage: 技能审批落盘后**没有任何变更历史**——update/archive 不可追溯、
  不可撤销，这是"事后审计替代事前审批"模型的前提设施缺失

Sage 的哲学（PHILOSOPHY.md §透明可控）要求所有自动化行为可审计、可回滚。
本批补齐技能维度的这一承诺。

## 批次任务

### A. `backend/skills/audit.py`（新）: `SkillAuditLog`

- SQLite 表 `skill_audit_log`: id / skill_name / action(create·update·
  archive·restore·rollback) / actor(user·system) / before_content /
  after_content / source(draft_id 等) / created_at
- `record()`（append-only，best-effort 不拖垮调用方）、
  `list_entries(skill_name=None, limit=50)`、
  `latest_before_snapshot(skill_name)`（回滚取数）
- 全局单例 + `reset_skill_audit_log()`（conftest 按用例重置）

### B. 写入挂钩（append-only 埋点）

- `approve_skill_draft`（legacy_routes）成功落盘 → record(create, actor=user,
  source=draft_id)
- `lifecycle.py` 归档/恢复迁移 → record(archive/restore, actor=system)

### C. 回滚 API

- `POST /skills/{name}/rollback`: 取 latest_before_snapshot →
  safe_writer 原地覆盖恢复 → record(rollback, actor=user)。
  无可回滚快照 → 409
- `GET /skills/{name}/audit`: 台账查询（前端审计视图数据源）

### D. 测试

- `backend/tests/unit/test_skill_audit.py`（台账/快照/单例重置）
- `backend/tests/integration/test_skill_rollback_api.py`（审批→回滚闭环）

## 验收

- [ ] 新测试全绿 + 存量 skills/legacy 路由测试不回归
- [ ] `ruff check backend/` 干净；CI 覆盖率 ≥80% 绿
- [ ] PR 注明「新功能，不 cherry-pick 到 release/win7」

## Round 4 候选

- 压缩谱系（fork_session 派生子会话 + 查看压缩前原文）
- docker 沙箱执行后端
- hex/legacy 双 chat 栈收敛
- 消息网关（Telegram MVP）
