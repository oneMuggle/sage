# 专家页面交互（P0–P2）

> 面向开发者：专家页面 / 卡片 / 详情页的交互实现说明。
> 相关章节：[133 专家（数字员工）系统](./133-specialist-persona.md)、[135 专家资产中心](./135-specialist-asset-hub.md)。

## 1. 范围

专家（数字员工）页面在 M0–M4 功能落地后的三轮交互优化：

| 阶段 | 内容                                                                                                                                   |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------- |
| P0   | 卡片主操作放大（开始试聊大按钮）、次操作收进「更多」菜单、avatar 色调渐变、禁用态灰度 + 徽章 + tooltip                                 |
| P1   | 来源筛选 Tab（全部/内置/我的/导入）、搜索（名称/标语/描述本地过滤）、空态三态（无专家引导 / 无匹配 + 清除筛选 / 正常网格）、卡片技能数 |
| P2   | 卡片知识数、批量操作（删除/启用/禁用）、最近使用时间、专家详情页 `/specialists/:id`、手动排序 + 置顶                                   |

## 2. 关键实现

### 2.1 卡片（`SpecialistCard.tsx`）

- 色调：`generateCardTone(avatar)` —— `hue = avatar.charCodeAt(0) * 37 % 360` 的 HSL 渐变；禁用态 `grayscale(100%) + opacity 0.7`。
- 知识数：卡片挂载时 `specialistKnowledgeApi.list(agentId)` 取 `length`（N+1，MVP 可接受；如需优化可新增后端聚合端点）。
- 点击头部（头像/名称区域）→ `onOpenDetail` 进入详情页；「更多」菜单含置顶 / 版本历史 / 评测 / 导出。

### 2.2 页面（`Specialists.tsx`）

- 筛选/搜索为纯前端派生（`useMemo`），按 `sort_order` 升序、同序按名称 `zh-Hans` collation 排序。
- 批量模式：卡片显示复选框；操作栏按钮 → `agentsApi.batch(action, ids)`。
- 置顶：将选中专家移到序列首位，`agentsApi.reorder([{id, sort_order}])` 一次性提交。

### 2.3 批量操作 API（`POST /agents/batch`）

```
POST /api/v1/agents/batch
body: { action: 'delete' | 'enable' | 'disable', ids: string[] }
resp: { succeeded: string[], failed: [{ id, error }] }
```

- `delete` 复用 `_delete_agent_internal`（级联清理私有记忆 / 版本快照 / 评测记录；`primary` 受保护）。
- `enable` / `disable` 走 `AgentRepository.update({enabled})`。

### 2.4 最近使用时间（migration v14）

- `agents.last_used_at INTEGER`（毫秒 Unix 时间戳，可空）。
- `touch_specialist_usage(agent_id)`（`backend/chat/specialist_binding.py`）：best-effort 更新，失败只 warning。
- 调用点：legacy `/chat/stream` DONE 后收尾段 + hex `ChatService._run_turn_inner` 最终响应后。
- 前端卡片显示「今天使用 / N 天前使用 / 未使用过」。

### 2.5 手动排序（migration v15 + `POST /agents/reorder`）

- `agents.sort_order INTEGER NOT NULL DEFAULT 0`；存量回填按 `updated_at` 倒序。
- `AgentRepository.update()` 支持 `sort_order` 字段。
- 前端置顶：`[{id, sort_order: index}]` 整序列提交。

### 2.6 详情页（`/specialists/:id`）

- `src/pages/SpecialistDetail.tsx`：头部（头像/名称/徽标/试聊/编辑）+ Tab：
  - 概览：技能数 / 版本 / 最近使用 / 启停状态
  - 人设：`parsePersonaSections` 六段只读
  - 技能：chips
  - 管理：知识绑定 / 资产中心 / 版本历史 / 黄金任务评测（打开既有对话框）
- 路由注册于 `src/App.tsx`（懒加载）。

## 3. 测试

- 前端：`src/pages/__tests__/Specialists.test.tsx`（筛选/搜索/空态/批量）、`src/widgets/specialists/__tests__/`（对话框组件）。
- 后端：`backend/tests/api/test_batch_agents.py`（批量 enable/disable/delete + primary 保护）、`test_schema_migrations.py`（v14/v15）。
- 防漂移：`electron/__tests__/ipc-contract.test.ts`（`batch_agents` / `reorder_agents` 命令）。

## 4. 双分支说明

全部改动为前端组件 + `Optional`/整型字段迁移，无 win7-only 依赖；`release/win7` 迁移编号需按 win7 现状避让（win7 已有 v13/v14 的差异）。
