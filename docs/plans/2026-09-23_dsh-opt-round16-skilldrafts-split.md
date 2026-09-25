# DSH 对标优化·第十六轮：C1 第三刀——Skill Draft/Audit/Rollback/Consolidation 路由组拆分

- **状态**：批次 A 交付中（分支 `feat-dshopt-r16-skilldrafts-split`，基线 origin/main 含 R15）
- **系列定位**：`dsh-opt` 对标系列第 16 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round14/15（C1a/C1b）
- **对标对象**：DeepSeek Harness Capability Seam——路由文件只做 HTTP 翻译。

## 0. 结论速览

C1 第三刀（收官刀）：Skill Draft Approval Queue / Audit / Rollback /
Consolidation 路由组（8 端点 + ConsolidationAcceptRequest，原 3935-4394
段 ~449 行）迁出为 `backend/api/legacy_skill_draft_routes.py`（649 行）。
`legacy_routes.py` 收缩到 3944 行（棘轮 4395 → 3944，累计三刀
**-1610 行**）。C1 拆分至此完成——legacy_routes.py 剩余为
chat/settings/preferences/evolution/learn 核心路径。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| C1c | Skill Draft/Audit/Rollback/Consolidation 路由组仍内联 | 3935-4394 段 | 同 C1a/C1b | **P1** |

## 2. 设计（批次 A：C1c）

与 R14/R15 同模式：整块迁出 + 独立 router + legacy_routes 尾部 include；
`with_db_lock` 按 D3 模式重建；`_safe_log_field` 助手随块迁移；
`_get_skill_adapter` 从 legacy_skills_routes 经显式 import 回供。

## 3. 批次 A 实施与验证记录

- **抽取**：`backend/api/legacy_skill_draft_routes.py`（649 行）——
  Skill Draft Approval Queue / Audit / Rollback / Consolidation 路由组
  整段迁出；`with_db_lock` 按 D3 模式重建；`_safe_log_field` /
  `_get_skill_adapter` 助手随块迁移。
- **验证**：api 全套 249 例全绿（含 /skills、/skill-drafts、
  /skills/consolidation 全部路由行为）；ruff 全过；py38 AST 3.8 通过；
  baseline 同步（legacy_routes.py 3944，累计三刀 **-1610 行**）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位；纯后端，pick 零冲突）
