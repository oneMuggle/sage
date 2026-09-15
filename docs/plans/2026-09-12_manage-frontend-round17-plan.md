# Round 17 批次 A —— 管理面前端收口：技能 pin/固化巡检 + 压缩谱系「查看归档」

> 来源：docs/technical/33-self-evolution.md「剩余已知差距（Round 16 时点）」#4/#5——
> consolidation/pin 管理面（REST 已有，前端未接入）、压缩谱系（谱系查询已有，前端入口未接）。
> 两项均为**新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 侦察结论（关键落点）

| 端点 | 位置 | 说明 |
| --- | --- | --- |
| `POST /skills/{name}/pin` | legacy_routes.py:1177 | body `{pinned}` → `{name, pinned}`；pin 后 archive 409 |
| `POST /skills/consolidation/scan` | legacy_routes.py:3343 | query `auto_draft=true` → `{suggestions, scanned, drafts_created}` |
| `GET /skills/consolidation/suggestions` | legacy_routes.py:3455 | `[{skill_names, suggestion, created_at}]` |
| `POST /skills/consolidation/accept` | legacy_routes.py:3415 | body `{skill_names}` → `{archived, skipped_pinned, missing}` |
| `GET /sessions/{id}/lineage` | legacy_session_routes.py:391 | `{archives:[{archive_session_id,title,message_count,archived_at,reason}]}` |

缺口：`GET /skills` 列表未透出 `pinned`（`_skill_to_dict` 只带 enabled/usage_count）；
skillsApi 无 pin/consolidation 封装；sessionApi 无 lineage；electron/commands.ts 无对应通道。

## R17-A1 技能 pin + 固化巡检管理面

- **backend**（additive，py3.8 纪律）：`_skill_to_dict` 增加 `pinned` 序列化，
  `list_skills` / `toggle` / `archive` / `pin` 响应统一透出（lifecycle store 读取）。
- **types.ts**：`Skill.pinned?: boolean`；`ConsolidationScanResult` / `ConsolidationSuggestion` / `ConsolidationAcceptResult`。
- **skillsApi.ts**：`pinSkill` / `scanConsolidation` / `getConsolidationSuggestions` / `acceptConsolidation`（withRetry + handleApiError 惯例）。
- **electron/commands.ts**：`pin_skill` / `skills_consolidation_scan` / `skills_consolidation_suggestions` / `skills_consolidation_accept` 四条 REST 映射。
- **Skills.tsx**：行内 pin/unpin（pinned 徽标，乐观更新 + toast，409 skill_pinned 结构化提示）；
  「固化巡检」按钮（scan → toast drafts_created）；巡检建议折叠区（逐条采纳 = accept 该条 skill_names，已 pin 跳过回显）。

## R17-A2 压缩谱系「查看归档」

- **types.ts**：`LineageArchive` / `SessionLineage`。
- **sessionApi.ts**：`getLineage(sessionId)`（不经 withRetry，同 compact 惯例）。
- **electron/commands.ts**：`session_lineage` 通道（GET）。
- **Chat.tsx**：`handleCompact` 成功 toast 增「查看归档」action → 打开归档弹窗；
  会话存在更早谱系时侧栏入口可选（本期只做 toast action + 空态引导）。
- **ArchivesModal**（src/widgets/session/）：Modal.tsx 模板 + MessageList 只读渲染，
  点选归档 → `sessionApi.getMessages(archive_session_id)` 懒加载。

## 测试

- `skillsApi` 单测（pin/scan/accept 通道与错误结构化）；
- Skills 页 pin 交互 + 巡检建议采纳流（乐观更新回滚、409 提示）；
- commands 表新通道映射单测（沿用现有 COMMAND_ROUTES 测试模式）；
- Chat compact toast「查看归档」action → ArchivesModal 渲染与懒加载。

## 不做

- 记忆固化手动触发端点（差距 #3 curator 事件驱动，批次 B 候选）；
- Discord/Slack 网关、hex-legacy 结构收敛（大工程，另行排期）。
