# R140：ToolPolicy + Wake 领域模型单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；M2 显式限制 / A4 Suspend-Resume 唤醒
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/tool_policy.py`（67 行，工具执行统一上限：中心超时 + byte/turn/
glob caps + M3 workspace_root 安全边界 + M6 subagent_only）与
`domain/wake.py`（150 行，A4 挂起/恢复的唤醒记录：三种触发类型工厂
校验、PENDING→DUE→FIRED 状态机、不可变 replace 迁移、UTC ISO 归一化）
此前零测试。

## 覆盖矩阵（约 25 例）

### `backend/tests/unit/domain/test_tool_policy.py`（8 例）

1. 七字段默认值（30s/256KB/200 条/2MB/25 次/None/False）；
2. from_config 全字段覆盖；3. 缺字段回退默认；4. frozen 不可变；
5. workspace_root 传入保留。

### `backend/tests/unit/domain/test_wake.py`（17 例）

1. to_utc_iso：naive 按 UTC、aware 转换、+00:00 后缀统一；
2. 枚举值；3. create 工厂校验：TIMER 缺 fire_at / COMPLETION 缺
job_id / EVENT 缺 event_key → ValueError；4. 三个 happy path（uuid
hex、PENDING、created_at 自动）；5. mark_due：PENDING→DUE 新实例
（原实例不变），非 PENDING → ValueError；6. mark_fired：PENDING/DUE
→ FIRED + fired_at（显式 ts 生效），FIRED 再 fire → ValueError；
7. is_fired；8. frozen。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
