# R144：编排事件协议 orch_events 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；编排事件协议 run-events@1.0（统一
  envelope + 状态转移表 + NDJSON 传输）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/orch_events.py`（470 行）是编排事件协议的权威定义：三级生命
周期状态机（Run/Task/Step，各带 terminal/active/waiting 判定与合法
转移表）、十类事件枚举、RunEvent 统一 envelope（NDJSON 序列化 + 幂等
command_id + 可见性级别）、make_event 便捷工厂、RunSnapshot 快照。
此前零测试。

## 覆盖矩阵（约 30 例）

1. **三级状态判定**：RunStatus 9 态 terminal/active 成员集合；
   TaskStatus 12 态 terminal/active/waiting；StepStatus 8 态 terminal；
2. **转移表全封闭断言**：三个 validate_* 对全部枚举对逐对校验，期望
   转移集合与实现转移表完全一致（以模块级私有表为 oracle，迁移表任何
   改动当场报警）；关键边 spot-check（RUNNING→COMPLETED ✓、
   DRAFT→RUNNING ✗、终态→任意 ✗、RECOVERY_REQUIRED→QUEUED 恢复边、
   INTERRUPTED→QUEUED 重入边）；
3. **事件枚举**：RunEventType 11 / TaskEventType 11 / StepEventType 7 /
   ControlEventType 7，取值点名；
4. **RunEvent**：make_event 工厂（evt- 前缀 id、毫秒 occurred_at、
   entity/payload 缺省空表）；to_dict 键集合与 command_id 条件键；
   from_dict 往返（含缺省键回填 visibility/schema_version）；
5. **快照**：TaskSummary 缺省；RunSnapshot.to_dict 结构（tasks 逐字段
   序列化 + 计数 summary + last_event_seq）；
6. SCHEMA_VERSION = "run-events@1.0"。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
