# UX-IA Round 2 · 批次 A：本轮注入上下文可视化

## 1. 目标
对标 Claude 的 context 可视化：让用户看到"这一轮到底注入了哪些上下文、各占多少"。这也是后续统一上下文预算器的前置——先能量出来，再谈统一分配。

## 2. 现状与缺口
`ContextMeter` 已有按**消息角色**的分类明细（tools / system / skills / dynamic_context / history…，按 provider 实报校准）。但 `system` 里混着 SAGE.md、项目概览、约束、资料；`dynamic_context` 里混着环境、记忆、附件。用户看不出具体来源。

## 3. 方案
- 新增 `backend/chat/context_sources.py`：对**最终请求 payload** 的 system 消息，按各注入块的固定标题 / 标签切段并估算 token。
  - 标记直接对应 `project_context.py` 的 `RENDER_HEADER / METADATA_HEADER / CONSTRAINTS_HEADER / MATERIALS_HEADER`、`<available-skills>`、`<environment>`、记忆前缀、`<attachments>` / `<attached_document>`。
  - 带闭合标签的块在闭合处结束，之后的无标记内容归入 `base_system`（头部）或 `other_dynamic`（非头部），不会误记给前一个块。
- `build_breakdown_snapshot` 输出新增 `sources: [{key, tokens, count}]`，与 categories 同口径校准。失败时只省略这个字段。
- **不改装配链路**：`legacy_routes.py` 零改动；legacy / hex 两条路径和 agent 循环的每次迭代都自动覆盖。快照本来就整体以 JSON 落库，无需迁移。
- 前端：`ContextMeter` 弹层底部新增「本轮注入的上下文」列表。旧记录没有 `sources` 时不显示；未知 key 回退显示原始 key。

## 4. 测试
- 后端 `test_context_sources.py`（6 例）：用真实的构造函数生成块，改标题时测试会直接失败；覆盖闭合标签、嵌套附件、多模态、校准缩放。在 Python 3.11 与 3.8 上均通过（共 22 例，含原有 breakdown 测试）。
- 前端 `ContextSourceList.test.tsx`（2 例）；`src/widgets/chat` 下 514 例全部通过。

## 5. 后续
- 批次 B：统一预算器——各来源声明预算与优先级，超出时按相关性截断，而不是整条排除（`PromptAssembler`）。
- 技能自动激活块目前没有固定标记，暂时计入「其他动态上下文」；可以给它加一个标签后单独列出。

## 6. PR
- main：#1855（`21577ac46`）
- win7（release/win7）：#1856
