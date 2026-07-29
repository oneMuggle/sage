"""``backend.adapters.out.compute`` — 外部计算能力 adapter 包。

包含：

- ``_resolver.ExecutableResolver`` — 按优先级解析 ghm 可执行文件入口
- ``subprocess_adapter.SubprocessComputeAdapter`` — 通过 subprocess CLI 调用
- ``mock_adapter.MockComputeAdapter`` — 测试用内存实现
"""
