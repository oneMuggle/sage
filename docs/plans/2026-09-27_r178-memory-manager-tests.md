# R178：MemoryManager（记忆管理器协调层）单测补齐（2026-09-27）

- **上游文档**：parity-loop-sop；三层记忆协调（working/episodic/semantic）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`memory/manager.py`（731 行，MemoryManager——三层记忆协调层）中
`classify_memory_type` 已在 r146 覆盖，但 MemoryManager 类本身的协调
委托路径（memorize 分派 / recall / delete_memory / get_stats /
add_to_working / compress）此前零测试。

## 覆盖矩阵（约 14 例）

用 SimpleNamespace fake 三层记忆，验证协调层的委托方向与返回值：
1. remember → episodic.save 透传；2. memorize 分派 working（低重要短
内容）；3. memorize 分派 episodic；4. memorize 分派 semantic（高重要）；
5. memorize tags 注入 metadata；6. delete_memory 委托（episodic/
semantic 两路）；7. get_stats 聚合三层；8. add_to_working 委托；
9. compress 委托；10. recall 委托 episodic。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
