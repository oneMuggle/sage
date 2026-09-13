# R28 批次 —— 固化巡检增量/事件驱动（差距 #3 后半收口）

> 背景：33-self-evolution.md 差距 #3 前半已由 #681 收口（手动触发）；本批收口
> 后半——巡检此前只支持全量扫描（每周 cron + 手动），无增量水位。

## 设计

### 水位（无状态）
- 台账 `skill_audit_log` 每次巡检都会写一条 `consolidation_note`，故
  `MAX(created_at) WHERE action='consolidation_note'` 即"上次巡检时点"。
- `SkillAuditLog.last_note_at()` 新增读取方法（无记录 → None）。

### 增量候选（两路并集，索引现成）
- `skill_usage.last_used_at > 水位`（水位后被使用）
- `skill_audit_log.created_at > 水位`（draft 批准/归档/恢复/回滚事件）
- 盲区：未经 draft 审批的文件级新建不进台账 → 由每周 cron 全量巡检兜底。

### 接口
- `collect_active_skills(names: Optional[Set[str]])`：可选候选过滤 +
  **补齐 `stale` 字段**（scan prompt 读取 `s.get("stale")`，历史实现从未填过
  ——顺手修的标注缺失 bug；lifecycle_map() 现成）。
- `POST /skills/consolidation/scan?mode=full|auto`：缺省 full 行为不变；
  auto = 以水位取增量候选，无水位自动退化全量；未知 mode 视为 full。
- 响应新增 `"mode"` 字段（additive）。cron 路径保持全扫（周频兜底）。

### 前端
- `skillsApi.scanConsolidation(autoDraft, mode)`；Skills 页固化巡检卡新增
  「增量巡检」按钮（与全量按钮并列，共用建议列表与 toast）。

## 测试
- consolidator 4 例（names 过滤 / stale 字段 / 无水位 None / delta 并集）
- 路由 4 例（full 缺省 / auto+水位取 delta / auto 无水位退化 / 未知 mode 视为 full）
- 既有 consolidator + curator provenance + async-safety 不变式回归 28/28 绿；
  前端 skillsApi 6 例 + Skills 页回归 14/14 绿；tsc / eslint / ruff 全过。

## 不做
- 事件推送式触发（技能使用即入队）——水位增量已覆盖 90% 价值，推送式
  需要事件总线，另行评估；
- Windows no-follow 原语（已知产品缺口族，W1-W3 批次已记录）。

**新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
