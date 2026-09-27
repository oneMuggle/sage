# 编码代理对标差距分析·第六十三轮：win7 对齐收口 + R2b 单测补齐

- **状态**：批次 A 交付中（分支 `feat-parity-r63`，基线 origin/main 7e4789a29）
- **上游文档**：R57（BU23）、R61（BU24/RD25）、R62（RT27）、#1733（ast_unparse/R2b）
- **对标对象**：Devin / 双分支一致性基线
- **编号约定**：延续 BU/RD/RT/OPS 系 + 对齐批次（ALG）

## 0. 结论速览

并行会话连续交付后，`release/win7` 与 main 出现 **6 项已确认漂移**（BU23 /
BU24+formatOffset clamp / RT27 / ast_unparse+R2b / r163 测试 / r164 测试）；
同时 main 侧 #1733 新增的 R2b 扫描器规则**缺单元测试**，总账缺
R55-R62 共 5 行交付记录。本轮三件套一次收口。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-1 | win7 缺 BU23 per-agent 工作量分布 | win7 chat_dispatcher 无 BU23 标记 | **P2** |
| ALG-2 | win7 缺 BU24 token 分布 + RD25 clamp | win7 无 `_agent_tokens`；EventTimeline 无 clamp | **P2** |
| ALG-3 | win7 缺 RT27 run 级聚合统计 | win7 orch_routes 无 `total_used_tokens` | **P2** |
| ALG-4 | win7 缺 #1733（py_compat.ast_unparse + R2b 规则） | win7 py_compat 无 `ast_unparse`；扫描器无 R2b | **P1** |
| ALG-5 | win7 缺 r163/r164 测试文件 | test_runtime_adapter / test_runtime_safe_run 不存在 | **P3** |
| T-1 | main R2b 规则无单测 | test_py38_hazard_scan 无 R2b 用例 | **P2** |
| T-2 | 总账缺 R55/R57/R58/R61/R62 行 | parity-rounds-index.md 停在 R54 | **P3** |

## 2. 设计

### 批次 A（main，本 PR）

- T-1：`test_r2b_ast_unparse` 正例 + 垫片/`ast.parse` 反例各一。
- T-2：总账 §1 补 R55/R57/R58/R61/R62 行（SHA 均从 git log 实证），
  §回填记录补记。
- round63 本文档。

### 批次 B（win7 对齐，独立 PR）

按依赖顺序 cherry-pick：#1733（ALG-4，先落 R2b 规则再过扫描）
→ #1691（ALG-1）→ #1727（ALG-2）→ #1731（ALG-3）→ #1729/#1732（ALG-5）
→ 批次 A 的 R2b 单测。已知冲突点：win7 `api_doc_generator.py` 有本地
ast_unparse 包装（与 #1733 的 py_compat 集中化冲突，取 py_compat 方案）。

## 3. 批次 A 实施与验证记录

- T-1：3 例（正例 1 + 反例 2）追加至 `test_py38_hazard_scan.py` R2 之后，
  规则编号连排。
- T-2：总账 5 行 + 回填记录。
- 验证：`pytest backend/tests/unit/tools/test_py38_hazard_scan.py -q` 全绿
  （本地 3.11）；win7 侧批次 B 落地后同一测试在 py3.8 门再验。

## 4. 批次 B

（见 §2，独立 PR 交付，交付号回填至本节与总账）

## 5. 交付记录

（交付后回填）
