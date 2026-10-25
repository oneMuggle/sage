# DSH 对标优化·第三十三轮：T1——chat_stream_support 纯函数直测补齐

- **状态**：批次 A 交付中（分支 `feat-dshopt-r33-t1-support-tests`，基线 origin/main 含 R32）

## 0. 结论速览

R31 迁出的 `chat_stream_support.py` 此前只有经 producer 的间接覆盖。
本轮新增 `tests/unit/test_chat_stream_support.py`（10 例）直测四个纯函数：

- `_memory_used_event_from_hits`：空命中 None、非 dict/空白 preview 过滤、
  类型缺省、5 条截断、事件形状；
- `_ndjson`：换行 + ensure_ascii=False；
- `_finalize_orch_run`：None run_id no-op、失败降级不抛、正常调用；
- `_build_orchestration_dispatcher`：非法 run_id 文案改写（拒绝语义保留 +
  原始信息保留）、合法 run_id 透传。

对齐仓库 r-series 惯例（r163-r179 每个抽取模块配直测）。

## 验证

- 10 例全绿；ruff 通过；py38 AST 兼容；guardrail 0 violation
