# R145：运行时领域模型 runtime.py 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime_probe / runtime_exec /
  project_diagnose 工具的领域表示
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/runtime.py`（221 行，frozen 数据模型全家桶：RuntimeInfo/
ProbeRequest/ProbeResult/ExecutionRequest/ExecutionResult/
ProjectManifest/Diagnostic/ProjectDiagnosis + `_runtime_to_dict`
序列化）此前零测试。to_dict 的字段舍入（duration_seconds round 4）、
None 命令条件序列化、嵌套能力块等契约钉死。

## 覆盖矩阵（约 18 例）

1. 三枚举取值（RuntimeSource 六值 / DiagnosticLevel 三值 /
   DiagnosticSeverity 三值）；
2. RuntimeCapability 缺省（can_execute False、双 source True）；
3. RuntimeInfo 缺省与 `_runtime_to_dict` 全字段形状（capabilities
   嵌套块、compatibility_notes 列表化）；
4. ProbeRequest 缺省与自定义；ProbeResult.to_dict（runtimes 逐项
   序列化 + errors 列表化）；
5. ExecutionRequest 缺省；ExecutionResult.to_dict：duration_seconds
   round(4)、command None 不变 / 列表拷贝、布尔缺省 False；
6. ProjectManifest 缺省；Diagnostic.to_dict（severity 取 .value、
   remediation/related_path None 透传）；ProjectDiagnosis.to_dict
   嵌套结构（level.value + diagnostics/manifests 逐项）；
7. frozen 不可变（RuntimeInfo 赋值抛 FrozenInstanceError）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
