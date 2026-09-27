# R151：OpenRouter 数据源映射 + 写作技能单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；OpenRouter schema（2026-09-15 官方文档
  校对）/ 内置技能
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`model_catalog/sources.py`（110 行，OpenRouter /api/v1/models 响应 →
CandidateModel 纯映射：model_id 拆分、per-token→per-million 价格换算、
"0 免费与未知区分"、负值/非法 → None）与 `skills/builtin/writer.py`
（107 行，写作技能：mock 模板回退 / prompt 构建 / LLM 分派与异常映射）
此前零测试。

## 覆盖矩阵（约 24 例）

### `backend/tests/unit/model_catalog/test_sources.py`（14 例）

1. `_split_model_id`：provider/slug 拆分、无斜杠 → openrouter 兜底、
   多段斜杠取首段、空 slug 回退原 id；2. `_price_per_million`：None/
   bool/负值/非数字/空串 → None；"0" → Decimal 0（免费≠未知）；
   数字透传 ×1e6；3. map_openrouter：非 dict → TypeError、data 非
   list → TypeError、非 dict 条目跳过、id 缺失/空白跳过、native 取
   正 context_length（非正 → None）、pricing 非 dict → 双价未知、
   source/pricing_scope/时间戳 Z 格式。

### `backend/tests/unit/skills/test_builtin_writer.py`（10 例）

1. schema：name=writer、required=[type, topic]；2. 无 LLM → mock
   内容 + metadata.mock=True（type/topic/length/style 透传）；
3. 有 LLM → prompt 构建（article/email/report/social 各自特征文案、
   未知类型回退 article）、complete 结果即 content、metadata 无 mock；
4. LLM 抛异常 → "写作失败"。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
