# 专家资产中心（Specialist Asset Hub）

> 面向开发者：专家私有记忆 / 知识绑定 / 技能的统一管理入口实现说明。
> 相关章节：[133 专家（数字员工）系统](./133-specialist-persona.md)。

## 1. 背景与范围

专家系统此前已具备三类资产，但入口分散：

| 资产     | 存储                                                       | 原有入口                               |
| -------- | ---------------------------------------------------------- | -------------------------------------- |
| 私有记忆 | `memories_episodic` / `memories_semantic` 的 `agent_id` 列 | 「记忆」页顶部「归属」筛选（管理视角） |
| 知识绑定 | `agent_knowledge_bindings`（`KnowledgeBinding`）           | 专家卡片「知识」按钮                   |
| 技能     | `agents.skills` 白名单                                     | 专家向导第 3 步                        |

第 143 章新增**专家资产对话框**（`SpecialistAssetsDialog`）：从专家卡片「资产」按钮进入，集中展示与操作专家私有记忆、知识绑定与技能；并打通「手动追加专家私有记忆」的后端链路。

本功能不改变既有隔离语义：记忆召回仍为「私有 ∪ 共享」，提升共享仍走同事务审计。

## 2. 记忆归属模型

`agent_id` 三态（与 M3 一致）：

| 值               | 语义                 | 可见范围                       |
| ---------------- | -------------------- | ------------------------------ |
| `NULL`           | 共享层（存量行默认） | 所有专家 + 主助手              |
| `'primary'`      | 默认助手私有         | 主助手（召回时并入共享）       |
| `'specialist-*'` | 专家私有             | 仅该专家（召回 = 私有 ∪ 共享） |

`GET /api/v1/memory/list?agent_id=<id>` 为**精确匹配**：只返回该专家私有行，不混入共享行 —— 资产对话框据此展示「该专家自己的记忆」。管理口径（全部/共享筛选）仍在「记忆」页。

## 3. 手动追加记忆链路

此前 `save_memory` 只有对话提取与工具写入两条路径，无法手动指定归属。本次打通 `agent_id`：

```
SpecialistAssetsDialog
  → memoryApi.saveMemory(content, type, importance, tags, undefined, agentId)
  → IPC save_memory { content, memory_type, importance, tags, agent_id }
  → POST /api/v1/memory/save
  → MemorySaveRequest.agent_id
  → MemoryManager.memorize(agent_id=...) / memorize_with_conflict_check(agent_id=...)
```

要点：

- `MemorySaveRequest.agent_id` 可选，缺省 `None` = 共享层 —— 旧调用方行为不变；
- `conflict_check=true` 分支同样透传（冲突消解按归属隔离）；
- Electron `save_memory` 路由仅当 `agentId` 非空时写入 `agent_id`，避免空串污染 payload；
- `ipc-manifest.json` 无需变化（body 字段不进入 argsProbe）。

## 4. 前端组件

`src/widgets/specialists/SpecialistAssetsDialog.tsx`

- 打开时并行加载：`memoryApi.getMemories('all', 1, 20, { agentId })` + `specialistKnowledgeApi.list(agentId)`；
- 知识绑定加载失败不影响记忆区块（独立错误态），记忆加载失败显示「重试」；
- 记忆列表操作：
  - **提升为共享**：`memoryApi.promoteMemory(id)` → 成功后从私有列表移除；
  - **删除**：`memoryApi.deleteMemory(id)`（episodic 软删 / semantic 硬删，沿用既有语义）；
- 「添加记忆」表单：内容 + 类型（情景/语义）+ 重要性（1-10），提交走上述链路，成功后重新加载；
- 「知识与技能」区块：绑定列表（来源类型徽标 + 名称 + 源标识）、「管理知识绑定」（跳转 `KnowledgeBindingsEditor`）、技能只读 chips（修改仍走向导）。

接线：`SpecialistCard` 新增 `onAssets` 回调与「资产」按钮；`Specialists.tsx` 管理 `assetsAgent` 状态，知识管理从资产对话框打开时先关闭资产、再打开知识编辑器。

## 5. 测试

- 前端：`src/widgets/specialists/__tests__/SpecialistAssetsDialog.test.tsx`
  - 加载记忆/绑定/统计、添加透传 `agentId` 并刷新、提升/删除后移除、空态、失败重试；
- 后端：`backend/tests/api/test_memory_save_agent_id.py`
  - 显式 `agent_id` 透传、缺省保持共享层、`conflict_check` 分支透传；
- 防漂移：`electron/__tests__/ipc-contract.test.ts`（命令/清单一致性）。

## 6. 边界与后续

- 记忆列表 MVP 取前 20 条 + 总数，分页留待后续；
- 知识绑定为「选源」模型（项目资料 / Wiki / Zotero），本版本不提供「已灌入条目」管理；
- 本功能不依赖 win7-only 代码，可直接 cherry-pick 到 `release/win7`（`Optional[str]` 在 pydantic 1.x/2.x 行为一致）。
