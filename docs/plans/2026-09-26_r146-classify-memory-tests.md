# R146：记忆分类规则 classify_memory_type 单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；MemoryManager 与 MemoryAdapter 共用的
  单一事实来源
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`memory/manager.py` 的模块级 `classify_memory_type`（显式类型透传 /
importance≥8 → semantic / 短内容(<200) 且 importance<5 → working /
其余 episodic）是记忆落库分流的统一规则，此前零测试。

## 覆盖矩阵（13 例）

1. 显式非 auto 类型透传（working/episodic/semantic/任意字符串）；
2. auto + importance≥8 → semantic（边界 8）；7 → 非 semantic；
3. auto + 短内容(<200) 且 importance<5 → working（边界 199/4、
   200 字符不满足、importance=5 不满足）；
4. 其余 → episodic（长内容低重要、短内容中重要）；
5. 空字符串 memory_type 按 auto 处理。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
