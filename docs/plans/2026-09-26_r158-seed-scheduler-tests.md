# R158：内置种子数据解析 + 调度端口契约单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；模型目录启动期种子（builtin.json）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`model_catalog/seed.py`（123 行，启动期把 builtin.json 灌入空目录：
`_parse_builtin_json` 纯解析 + `seed_if_empty` 幂等空目录判断）与
`domain/scheduler.py`（38 行，定时任务端口契约：SchedulerServicePort
协议 + ScheduledTaskNotFoundError / ScheduledTaskValidationError）此前
零测试。

## 覆盖矩阵（约 16 例）

_parse_builtin_json（纯函数）：
1. 根非 dict → ValueError；2. models 非 list → ValueError；
3. 非 dict 模型条目跳过；4. provider/model_id 缺失跳过；
5. native 非法（非 int / ≤0）→ None；6. price 双键透传；
7. pricing_scope 缺省 self-hosted、显式保留；8. source_updated_at：
per-model 优先、回退顶层 generated_at、双缺 → None；
9. source 固定 builtin；10. 多条目解析完整。

scheduler：
11. ScheduledTaskNotFoundError 是 KeyError 子类；12.
ScheduledTaskValidationError 是 ValueError 子类；13.
SchedulerServicePort 协议可被 duck-type 实现（三方法类通过静态赋值
校验）；14. 协议默认不可实例化成员无绑定。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
