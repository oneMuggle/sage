# R32 定性报告 —— 串行主路径中心超时暂缓 + 新发现的 Windows 产品缺口

> 背景：hex-legacy 切片 A 延伸——给 legacy 串行主路径（
> `_await_tool_execution` 同步内联分支）接入 `tool_policy.timeout_seconds`
> 中心超时（对齐 hex 适配器与并行批次语义）。实施后触及簇全绿，但
> **office_create 集成流回归**，定性后撤回实施、保留结论。

## 定性结论一：串行内联中心超时暂缓（前置条件成立后再做）

同步内联工具与事件循环线程亲和：迁入 executor 后，office_create 的
workspace 注册/审批应答跨线程失联（集成流 `asks_then_creates` /
`denial_does_not_create` 双双回归，本地+CI 复现）。

**前置条件**：先解决内联工具的线程亲和（DB/注册表连接的线程约束梳理，
或 workspace 注册改造为跨线程安全），中心超时才能安全接入。
恢复代码已含于本报告历史（#830 分支历次提交可考）。

## 定性结论二（新发现的 Windows 产品缺口，W8 候选）

干净 main 上，**office_create 的 workspace 外写入审批流在 Windows 本地
不触发**（`answered={}`、`pending=[]`，工具未经询问即执行）：

- enforcer 的 workspace 包含性判定在 Windows 上失效（疑似大小写/
  盘符/`resolve()` 对不存在路径的行为差异）；
- 该集成测试仅在 ubuntu CI 运行，Windows 从未覆盖 —— 本地/CI 双盲区。

**建议批次**：
1. permission enforcer 的 Windows 路径包含性判定修复
   （`Path.resolve()` + 大小写归一后重判）；
2. 集成测试矩阵补 windows-latest（#728 windows unit job 已铺路）。

## 附带
- 串行超时的实现快照可考（分支历史 4c73fba1 等提交）；
- `test_agent_loop_guards` 的挂死超时用例随实现一并撤回，
  前置条件满足后恢复。
