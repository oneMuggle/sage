# R160：被动读取循环检测 NudgeGuard 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；A13 NudgeGuard（from LLM_Simple，带
  Sage 工具名与可配置阈值）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`application/services/middleware/nudge_guard.py`（170 行，被动读取循环
检测：用户消息动作关键词 × 连续全被动轮数双条件 → 注入推动消息，兼容
OpenAI 嵌套与扁平两种 tool_call 结构）此前零测试。

## 覆盖矩阵（约 16 例）

1. passive_threshold < 1 → ValueError；2. 动作关键词命中 + 全被动 →
nudge（threshold 1）；3. 无动作关键词 → None 且 streak 重置；
4. 含主动工具 → None 且 streak 重置；5. 空 tool_calls 视为非被动；
6. threshold=2：第一轮 None、第二轮 nudge、streak 属性累积；
7. OpenAI 嵌套 {"function": {"name"}} 与扁平 {"name"} 两种结构；
8. reset 清零；9. 自定义 passive_tools / action_keywords / nudge_message；
10. 混合被动+主动 → None；11. 默认常量导出（frozenset、消息含
write_file）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
