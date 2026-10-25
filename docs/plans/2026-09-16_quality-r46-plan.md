# 代码质量清理（第四十六轮批次 A）实施计划

> 日期: 2026-09-16 . 分支: feat/quick-batch-r46 . 基于 main @ ec2e34be
> 来源: 积累性 lint 债务清理（backend/api + services 限定范围）。
> 与并发车道零交集。Win7 对齐: 纯代码质量，不迁。

## 实施
- ruff --fix 清理 backend/api + backend/services 的 UP045/F401/I001
- 350 处自动修复 + 级联清理，PLC0415（函数内 lazy import）为设计性模式不修改
## 测试
- 既有测试回归全过
