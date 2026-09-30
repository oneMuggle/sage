# UX-IA Round 2 · 批次 C：预算截断可见化

## 1. 目标
批次 B 的统一预算会在超出时截断低优先级注入块，但用户看不到"这一轮被截了什么"。对标 Claude / Cursor 的上下文提示，让截断在 ContextMeter 里可见。

## 2. 方案
- **不新增数据通路**：截断说明 `…[已按上下文预算截断约 N tokens]` 本来就写在最终请求 payload 里。`context_sources` 切分来源时解析块内说明，给来源条目加上 `trimmed`（与 `tokens` 同口径校准）。legacy 链路、agent 循环每次迭代自动覆盖，快照照旧整体 JSON 落库，无需迁移。
- 说明格式抽成 `context_sources.TRIM_NOTE_FMT`，`context_budget` 复用，两端不会漂移。
- 前端 `ContextSourceList`：被截来源行显示「已截断 N」角标；列表顶部显示汇总提示「注入内容超出预算（窗口的 35%），已截掉约 N tokens 低优先级内容」。旧记录 / 未截断时不显示。

## 3. 测试
- 后端 `test_context_trim_visibility.py`（4 例）：说明解析、未截断时无字段、预算截断端到端出现在来源明细、校准缩放。`unit/chat` 134 例通过；Python 3.8 相关 18 例通过；ruff 全仓通过。
- 前端 `ContextSourceList.test.tsx` 新增 1 例；`src/widgets/chat` 515 例通过；tsc / eslint / 架构检查通过。

## 4. 后续
- hex 路径（`chat_service.py`）仍未接入预算（批次 B 遗留）。
- 按相关性截断（需 embedding）。
- 技能自动激活块尚无固定标记。

## 5. PR
- main：待回填
- win7：待回填
