# UX-IA Round 2 · 批次 D：预算收尾（相关度截断 / hex 接入 / 自动激活技能标记）

## 1. 目标
清掉批次 B / C 的三项遗留，让 Round 2 的"注入上下文统一预算"在两条聊天路径上行为一致。

## 2. 改动
- **按相关度截断（无需 embedding）**：`apply_context_budget` 新增可选 `query`（本轮用户输入）。项目资料、记忆召回这两类由多条独立条目组成的块，超预算时按条目与输入的字符二元组重合度排序，优先保留相关条目，输出保持原顺序，并附同格式截断说明（ContextMeter 角标照常生效）。条目不足 2 条、或没有任何条目相关时，回退到原来的"保留开头"截断。中英文通用、零依赖，Python 3.8 兼容。
- **hex 路径接入**：`ChatService` 新增可选 `context_window_resolver`，在记忆与技能自动激活块拼好之后、发送前调用同一预算器；`backend/main.py` 装配时传入按已保存设置解析窗口的函数（复用 legacy 的 `_resolve_effective_window`）。窗口未知 / 异常时原样放行。legacy 路径同时把 `data.message` 传给预算器。
- **标记补全**：
  - 技能自动激活块（A16 固定标题）成为独立来源 `skills_activated`（「自动激活的技能」），截断优先级位于技能清单之后、项目概览之前。
  - hex 路径的记忆前缀用半角冒号，此前未被识别，现已计入「记忆召回」。

## 3. 测试
- `test_context_budget_r2d.py`（6 例）：相关条目即使在末尾也被保留、无 query / 无相关条目时回退、hex 记忆前缀与自动激活块识别、ChatService 钩子（无 resolver / 截断 / resolver 异常）、main 装配。
- `unit/chat` + `unit/api` + ChatService 相关单测 813 例通过；Python 3.8 相关 24 例通过；ruff 全仓、tsc、`src/widgets/chat` 515 例、架构检查通过（chat_service / main 基线按棘轮上调）。

## 4. 仍可改进
- 相关度目前是字符二元组重合度；若后续引入本地 embedding，可在 `_truncate_by_relevance` 中替换打分函数。
- 需要在运行中的 app 里实测（小窗口模型 + 大量项目资料）。

## 5. PR
- main：#1864（已合并）
- win7：#1865（已合并；解决了与 win7 记忆生命周期装配的冲突）
