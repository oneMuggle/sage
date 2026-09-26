# R137：Agent 事件信封 + RunEventScope 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；M1 结构化可观测性（claw-code §4 原则 3）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/agent_event.py`（70 行，M1 可观测性核心：版本化信封 envelope()
+ RunEventScope 稳定 run_id/单调 seq——r127 的 file_adapter 已依赖
envelope 但其本体零测试）。

## 覆盖矩阵（8 例）

1. envelope 五键（schema/format_version/ts/type/payload）、常量值；
2. payload 原样携带、不拷贝语义由调用方保证（引用同一 dict）；
3. RunEventScope：run_id 稳定；4. emit 返回自增 seq（0,1,2…）；
5. payload 恒含 run_id + seq 且与调用方 data 合并；6. data 覆盖不
   影响 run_id/seq 注入（先 **data 后无覆盖——以实现为准断言）；
7. 空 emit（仅事件名）→ payload 仅 run_id+seq；8. sink 记录完整
   (type, payload) 序列。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
