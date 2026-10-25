# R150：子代理自动批准包装器单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；live-events P1 分级信任（编排子代理
  autopilot 模式）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`orchestration/subagent_approval.py`（133 行，AutoApproveEnforcer——
needs_approval 二次风险裁决包装器：deny 永远胜出、边界类升级永不自动
批准、执行面危险命令保留人工、无法评估风险的执行面工具保守转人工、
非危险自动放行并打审计标记）此前零测试。安全不变式密度高，必须钉死。

## 覆盖矩阵（约 14 例）

1. base allow / deny 原样透传（不改写、不加后缀）；
2. needs_approval + 边界特征（"工作区外"/"边界"）→ 保留人工；
3. 非执行面工具（WRITE）needs_approval → 自动批准，reason 追加
   "（编排自动批准 auto）"、allowed=True、needs_approval=False；
4. 执行面（EXECUTE）：command 缺失/非字符串/空白 → 保守转人工；
   validate_bash DESTRUCTIVE / SUSPICIOUS → 保留人工；SAFE → 自动
   批准；5. mode/rules 委托 base；6. 审计落库 `_record_auto_approval`
   全吞降级（repo 抛错不影响返回）；7. build_subagent_enforcer：非
   auto → None；auto → AutoApproveEnforcer 实例；load 失败 → None。

base enforcer 用 fake（记录 check 实参、返回预设 decision）；
classify_tool / validate_bash / 审计 repo 全 monkeypatch。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
