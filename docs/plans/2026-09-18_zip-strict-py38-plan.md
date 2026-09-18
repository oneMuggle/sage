# py38 zip strict= 残留清零（Round 24）

日期：2026-09-18 ｜ 分支：`feat/py38-zip-strict` ｜ 基线：#1040 系（1d06a1ebf）

## 发现

全量 py38 重测（#1146 后）尾部残余 2 例：`test_topic_detection` 的 embed 用例
在 py38 下恒返回 `no_signal`。根因：`chat/topic_detection.py::_cosine` 使用
`zip(a, b, strict=False)`——`strict=` 形参是 3.10+，py38 抛 TypeError，
被 `detect_topic_shift` 的 `except Exception: continue` 吞掉 → sims 为空 →
no_signal。**embed_similarity 话题检测路径在 py38 上完全失效的真实产品 bug**
（win7 目标解释器同样命中）。

同扫描另发现 model_catalog 并发集成测试的 zip strict 一处，一并清理。

## 修复

- `topic_detection._cosine`：移除 `strict=`（默认语义即非严格）+ `# noqa: B905`
  （ruff autofix 会回填 strict=，noqa 防回退）
- `test_model_catalog_repository.py`：zip strict 同步清理

## 验证

- py38（3.8.20）：test_topic_detection 5 passed；model_catalog 集成测试 modern 36 passed
- ruff 干净

## 派生修复说明

本分支还包含前序批次（#1106/#1146 同源）的派生修复：requirements-py38
cryptography 47.0.0 已在（win7 同款），本分支补装本地环境后重测即过。
