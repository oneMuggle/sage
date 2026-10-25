# R173：question_routes（AskUserQuestion）单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；M2 part B AskUserQuestion（question_gate）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/question_routes.py`（90 行，AskUserQuestion 的 REST 端点——
list_pending + answer）此前零测试。错误语义（HTTP 恒 200 + ok 字段、
Origin 守卫 403）必须钉死。

## 覆盖矩阵（约 10 例）

1. list_pending：gate 未初始化 → []；gate 有挂起 → 逐条 to_dict；
2. origin 守卫返回 403 时短路；3. answer：gate 未初始化 →
question_gate_not_initialized；4. gate.answer 返回 falsy →
unknown_or_expired；5. 正常应答 → {ok: true}；6. answers/custom 透传；
7. QuestionAnswerBody extra=forbid。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
