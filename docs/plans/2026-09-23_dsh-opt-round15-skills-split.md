# DSH 对标优化·第十五轮：C1 第二刀——技能 API 路由组拆分

- **状态**：批次 A 交付中（分支 `feat-dshopt-r15-skills-split`，基线 origin/main 含 R14）
- **系列定位**：`dsh-opt` 对标系列第 15 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round14（C1a 记忆 API 拆分，main #1573 / win7 #1589）
- **对标对象**：DeepSeek Harness Capability Seam——路由文件只做 HTTP 翻译。

## 0. 结论速览

C1 第二刀：技能 API 主块（10 端点 + 模型 + `_get_skill_adapter` 助手，
原 1279-1677 段 ~400 行）迁出为 `backend/api/legacy_skills_routes.py`
（582 行）。`legacy_routes.py` 收缩到 4388 行（棘轮 4395，累计两刀
**-1160 行**）。skill-drafts/audit/rollback/consolidation 后段（~440 行）
属下一刀（与 evolution/learn 域交界，需先厘清边界）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| C1b | 技能主块仍内联 legacy_routes | 1279-1677 段 | 同 C1a | **P1** |

## 2. 设计（批次 A：C1b）

与 R14 同模式：整块迁出 + 独立 router + legacy_routes 尾部 include；
`with_db_lock` 按 D3 模式在新文件重建；`_get_skill_adapter` 助手随块
迁移，legacy_routes 的 chat/编排区域经 import 继续使用（`/settings`、
`/preferences` handler 引用的 `LegacySettingsRequest/Response`、
`LegacyPreferenceItem` 亦由本模块回供——模型类随技能块迁出所致）。

## 3. 批次 A 实施与验证记录

- **抽取**：`legacy_skills_routes.py`（582 行）——技能主块整段迁出；
  `with_db_lock` 按 D3 模式重建；`_get_skill_adapter` 随块迁移。
- **回供导入**：legacy_routes 的 /settings、/preferences handler 引用的
  `LegacySettingsRequest/Response`、`LegacyPreferenceItem` 与 chat/编排
  区域引用的 `_get_skill_adapter` 经显式 import 回供（noqa F401 标注用途）。
- **验证**：api 全套 228 例全绿；skills 路由 18 条经链可达（脚本断言）；
  ruff 全过；py38 AST 3.8 通过；baseline 同步（legacy_routes.py 4395，
  累计两刀 -1160）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
