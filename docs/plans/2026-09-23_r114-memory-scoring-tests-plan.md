# R114 批次计划 —— memory scoring 四因子检索评分测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r114-scoring-tests`（基于 origin/main）

## 背景

`backend/memory/scoring.py`（157 行，四因子检索评分）无同名测试。该模块
是记忆检索排序的核心逻辑（recency × importance × confidence × relevance），
bug 会直接导致检索排序异常。

## 批次内容

新增 `backend/tests/unit/memory/test_scoring.py`（17 用例）：

- relevance：正常 RRF 映射到 [0,1]、零/缺失回退 0.5 中性、超高值钳位 1.0；
- recency：新记忆高 recency、旧记忆衰减、缺时间戳回退 0.5、
  accessed_at 晚于 created_at 时取较大值；
- importance：7 分 → 0.7、缺失回退 0.5、负值钳位 0.1、超高钳位 1.0；
- confidence：基线 0.5、晋升 source 加成、supersedes_id 加成、
  access_count 加成且钳位 1.0；
- composite_score：返回值 ∈ [0,1]；权重和 = 1.0；
- rank_by_composite：按 composite_score 降序排列、不修改入参。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过。
- CI：Backend (Python) pytest 全量。

## 不做

- 不改生产代码。
